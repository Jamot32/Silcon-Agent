"""Trusted, explicitly supplied faulty designs for honest repair demonstrations."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from pydantic import JsonValue

from app.schemas import DesignSpec

ROOT = Path(__file__).resolve().parents[3]
STARTER_ID = "uart_off_by_one"
_PORTS = (
    ("clk", "input", 1), ("rst_n", "input", 1), ("send", "input", 1),
    ("data", "input", 8), ("busy", "output", 1), ("tx", "output", 1),
)
_SPEC_TEXT = """Evaluate the supplied UART transmitter starter against this required contract before repairing it. This is a deliberately supplied faulty starting design, not a model-generated design or failure. Preserve top module uart_tx and the exact ports: inputs clk, rst_n, send, data[7:0]; outputs busy and tx.

Implement an 8N1 UART transmitter: one low start bit, eight data bits least significant bit first, and one high stop bit. The positive integer parameter BAUD_DIV defaults to 4. Every serial bit, including the complete start and stop bits, must last exactly BAUD_DIV rising-edge clock periods; use the default value 4 for this run. Target a 50 MHz input clock.

Use a synchronous active-low rst_n. Reset overrides send, aborts any frame, clears busy, and drives tx high only at a rising clock edge. Idle tx is high and busy is low. On an idle rising edge with send high, latch data, raise busy, and start the low start bit immediately. Ignore subsequent data changes and every send request while busy, including the edge that completes the frame. Do not queue requests. Clear busy only after the full stop bit. A new request can be accepted at the following rising edge.

First write independent cocotb tests from this contract and run them against the unchanged supplied source. Cover synchronous reset and priority, exact bit periods and bit order, changing data while busy, rejected busy requests, the full stop interval, and consecutive frames. If a test fails, record a failure hypothesis and repair the RTL without weakening tests. Keep the design small; standalone DRC/LVS does not establish Tiny Tapeout wrapper or shuttle readiness."""


@dataclass(frozen=True)
class Starter:
    id: str
    title: str
    top_module: str
    ports: tuple[tuple[str, str, int], ...]
    spec_text: str
    source_path: Path
    source: str
    sha256: str

    def metadata(self) -> dict[str, JsonValue]:
        return {
            "id": self.id, "title": self.title,
            "origin": "supplied_known_faulty_starter", "model_generated": False,
            "top_module": self.top_module,
            "ports": [{"name": name, "direction": direction, "width": width}
                      for name, direction, width in self.ports],
            "source": self.source_path.relative_to(ROOT).as_posix(),
            "sha256": self.sha256,
        }

    def validate_spec(self, spec: DesignSpec) -> None:
        if spec.top_module != self.top_module:
            raise ValueError(f"Supplied UART starter requires top_module {self.top_module}")
        actual = {(port.name, port.direction, port.width) for port in spec.ports}
        if actual != set(self.ports) or spec.purely_combinational:
            expected = ", ".join(f"{direction} {name} (width {width})" for name, direction, width in self.ports)
            raise ValueError(f"Supplied UART starter requires exactly these sequential ports: {expected}")


def load_starter(starter_id: str) -> Starter:
    if starter_id != STARTER_ID:
        raise ValueError("Unknown supplied starter")
    directory = ROOT / "designs/starters/uart_off_by_one"
    path = directory / "src/uart_tx.v"
    raw = path.read_bytes()
    provenance = json.loads((directory / "provenance.json").read_text())
    digest = hashlib.sha256(raw).hexdigest()
    if provenance.get("origin") != "supplied_known_faulty_starter" or provenance.get("model_generated") is not False:
        raise ValueError("Supplied starter provenance is invalid")
    if digest != provenance.get("sha256"):
        raise ValueError("Supplied starter source does not match its provenance hash")
    return Starter(
        id=STARTER_ID, title="Supplied faulty UART starter", top_module="uart_tx",
        ports=_PORTS, spec_text=_SPEC_TEXT, source_path=path,
        source=raw.decode("utf-8"), sha256=digest,
    )
