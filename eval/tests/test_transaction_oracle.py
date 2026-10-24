"""Synthetic protocol traces only; no simulator, DUT, corpus or benchmark run."""

import asyncio
from fractions import Fraction
import importlib.util
from pathlib import Path
import random
import sys
from types import SimpleNamespace

import pytest

from eval.oracles import arithmetic


@pytest.fixture
def transaction_checks(monkeypatch):
    config = {"kind": "python_fraction", "operation": "multiply", "reference_parameters": {"WIDTH": 8, "FBITS": 4}, "seed": 42}
    monkeypatch.setitem(sys.modules, "cocotb", SimpleNamespace(test=lambda: lambda function: function))
    monkeypatch.setitem(sys.modules, "cocotb.triggers", SimpleNamespace(Timer=None))
    monkeypatch.setitem(sys.modules, "oracle_config", SimpleNamespace(CONFIG=config))
    monkeypatch.setitem(sys.modules, "oracle_reference", SimpleNamespace(Fraction=Fraction))
    monkeypatch.setitem(sys.modules, "arithmetic_oracle", arithmetic)
    path = Path(__file__).resolve().parents[1] / "oracles/transactions.py"
    spec = importlib.util.spec_from_file_location("unit_only_transaction_checks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "vectors", lambda config, phase: [(16, 16)])
    return module


class ArithmeticTrace:
    """A literal 1.0 x 1.0 trace; deliberately not an arithmetic implementation."""

    def __init__(self, latency=3, mutant=None):
        self.latency = latency
        self.mutant = mutant
        self.rng = random.Random(42)
        self.remaining = None
        self.after_completion = False
        self.signals = {}
        self.output_names = ["busy", "done", "valid", "ovf", "val"]

    async def reset(self):
        self.signals = {"busy": 0, "done": 0, "valid": 0, "ovf": 0, "val": 0}

    def outputs(self):
        return dict(self.signals)

    async def tick(self, values=None):
        before = self.outputs()
        self.signals["done"] = 0
        if (values or {}).get("start") and self.remaining is None:
            self.remaining = self.latency
            self.signals.update(busy=1, valid=0)
        elif self.remaining is not None:
            self.remaining -= 1
            if self.remaining == 0 and self.mutant != "never_finishes":
                self.remaining = None
                self.after_completion = True
                self.signals.update(busy=0, done=1, valid=1, val=16)
        elif self.after_completion:
            if self.mutant == "result_drift":
                self.signals["val"] = 17
            elif self.mutant == "valid_drops":
                self.signals["valid"] = 0
            elif self.mutant == "done_sticks":
                self.signals["done"] = 1
        if self.remaining is not None and self.mutant == "busy_missing":
            self.signals["busy"] = 0
        if self.remaining is not None and self.mutant == "valid_during_pending":
            self.signals["valid"] = 1
        return before, self.outputs()


@pytest.mark.parametrize("latency", [1, 3, 20])
def test_arithmetic_contract_accepts_different_bounded_transaction_latencies(transaction_checks, latency):
    asyncio.run(transaction_checks.arithmetic(ArithmeticTrace(latency), 0))


@pytest.mark.parametrize("mutant,reason", [
    ("busy_missing", "busy"),
    ("valid_during_pending", "validity"),
    ("never_finishes", "completion bound"),
    ("done_sticks", "one-cycle pulse"),
    ("valid_drops", "validity"),
    ("result_drift", "val|result"),
])
def test_arithmetic_contract_rejects_status_or_held_result_violations(transaction_checks, mutant, reason):
    with pytest.raises(AssertionError, match=reason):
        asyncio.run(transaction_checks.arithmetic(ArithmeticTrace(mutant=mutant), 0))


def test_missing_pinned_python_reference_cannot_fall_back_to_host_stdlib(transaction_checks, monkeypatch):
    monkeypatch.setitem(sys.modules, "oracle_reference", None)
    path = Path(transaction_checks.__file__)
    spec = importlib.util.spec_from_file_location("unit_only_missing_reference", path)
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(ModuleNotFoundError):
        spec.loader.exec_module(module)


def test_bench_output_snapshot_remains_callable_after_construction(transaction_checks):
    class KnownZero:
        is_resolvable = True

        def __int__(self):
            return 0

    transaction_checks.CONFIG["ports"] = [{"name": "busy", "direction": "output", "width": 1}]
    dut = SimpleNamespace(dut_busy=SimpleNamespace(value=KnownZero()))
    bench = transaction_checks.Bench(dut, 0)
    assert bench.outputs() == {"busy": 0}


class UARTTrace:
    """Literal UART wire framing with independently chosen legal start/ready delays."""

    def __init__(self, start_delay, ready_delay):
        self.start_delay, self.ready_delay = start_delay, ready_delay
        self.inputs = {"s_axis_tdata": 8}
        self.rng = random.Random(42)
        self.elapsed = None

    async def reset(self):
        self.signals = {"txd": 1, "busy": 0, "s_axis_tready": 1}

    def outputs(self):
        return dict(self.signals)

    async def tick(self, values=None):
        before = self.outputs()
        if (values or {}).get("s_axis_tvalid") and before["s_axis_tready"]:
            self.word = values["s_axis_tdata"]
            self.elapsed = 0
        elif self.elapsed is not None:
            self.elapsed += 1
        if self.elapsed is not None:
            bit = (self.elapsed-self.start_delay)//16
            active = self.start_delay <= self.elapsed < self.start_delay+160
            txd = 0 if bit == 0 else ((self.word >> (bit-1)) & 1) if 1 <= bit <= 8 else 1
            ready = self.elapsed >= self.start_delay+160+self.ready_delay
            self.signals.update(txd=txd, busy=int(active), s_axis_tready=int(ready))
        return before, self.outputs()


@pytest.mark.parametrize("start_delay,ready_delay", [(0, 0), (5, 8), (32, 64)])
def test_uart_accepts_full_public_start_and_ready_latency_bounds(transaction_checks, start_delay, ready_delay):
    asyncio.run(transaction_checks.uart_tx(UARTTrace(start_delay, ready_delay), 0))


class SPITrace:
    """A mode-0 byte trace; first-edge phase and ready completion vary independently."""

    def __init__(self, first_edge, ready_at):
        self.first_edge, self.ready_at = first_edge, ready_at
        self.rng = random.Random(42)
        self.elapsed = None
        self.miso = 0

    async def reset(self):
        self.signals = {"sclk": 0, "tx_ready": 1, "rx_valid": 0, "rx_data": 0, "mosi": 0}

    def outputs(self):
        return dict(self.signals)

    async def tick(self, values=None):
        values = values or {}
        before = self.outputs()
        self.miso = values.get("miso", self.miso)
        self.signals["rx_valid"] = 0
        if values.get("tx_valid") and before["tx_ready"]:
            self.word, self.elapsed, self.edges, self.received = values["tx_data"], 0, 0, 0
            self.signals.update(tx_ready=0, mosi=(self.word >> 7) & 1)
        elif self.elapsed is not None:
            self.elapsed += 1
        if self.elapsed is not None:
            if self.elapsed >= self.first_edge and (self.elapsed-self.first_edge) % 2 == 0 and self.edges < 16:
                self.edges += 1
                self.signals["sclk"] ^= 1
                if self.signals["sclk"]:
                    self.received = (self.received << 1) | self.miso
                    if self.edges == 15:
                        self.signals.update(rx_valid=1, rx_data=self.received)
                elif self.edges < 16:
                    self.signals["mosi"] = (self.word >> (7-self.edges//2)) & 1
            if self.elapsed >= self.ready_at and self.edges == 16:
                self.signals["tx_ready"] = 1
        return before, self.outputs()


@pytest.mark.parametrize("first_edge,ready_at", [(1, 32), (3, 35), (72, 144)])
def test_spi_accepts_unspecified_start_phase_and_full_public_ready_bound(transaction_checks, first_edge, ready_at):
    transaction_checks.CONFIG["reference_parameters"] = {"SPI_MODE": 0, "CLKS_PER_HALF_BIT": 2}
    asyncio.run(transaction_checks.spi(SPITrace(first_edge, ready_at), 0))


def test_spi_rejects_start_after_public_first_edge_deadline(transaction_checks):
    transaction_checks.CONFIG["reference_parameters"] = {"SPI_MODE": 0, "CLKS_PER_HALF_BIT": 2}
    with pytest.raises(AssertionError, match="start|first|latency"):
        asyncio.run(transaction_checks.spi(SPITrace(73, 144), 0))
