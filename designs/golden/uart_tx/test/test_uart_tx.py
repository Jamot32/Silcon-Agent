import random

import cocotb
from cocotb.triggers import Timer


async def tick(dut):
    dut.clk.value = 0
    await Timer(5, unit="ns")
    dut.clk.value = 1
    await Timer(5, unit="ns")


def divisor(dut):
    value = int(dut.BAUD_DIV.value)
    assert value >= 1, "The reference contract requires BAUD_DIV >= 1"
    return value


async def reset(dut):
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.send.value = 0
    dut.data.value = 0
    await tick(dut)
    assert int(dut.busy.value) == 0
    assert int(dut.tx.value) == 1
    dut.rst_n.value = 1


async def frame(dut, value, noise=False):
    clocks = divisor(dut)
    dut.send.value = 1
    dut.data.value = value
    await tick(dut)
    assert int(dut.busy.value) == 1, "Idle send must be accepted at its rising edge"
    assert int(dut.tx.value) == 0, "Accepted send must start the low start bit"
    bits = [0] + [(value >> index) & 1 for index in range(8)] + [1]
    for elapsed in range(1, 10 * clocks + 1):
        dut.send.value = 1 if noise else 0
        dut.data.value = (value + elapsed + 37) & 255
        await tick(dut)
        expected_busy = int(elapsed < 10 * clocks)
        expected_tx = bits[elapsed // clocks] if expected_busy else 1
        assert int(dut.busy.value) == expected_busy, f"Wrong busy at frame clock {elapsed}"
        assert int(dut.tx.value) == expected_tx, f"Wrong serial bit at frame clock {elapsed}"
    dut.send.value = 0


@cocotb.test()
async def synchronous_reset_and_reset_priority(dut):
    await reset(dut)
    dut.send.value = 1
    dut.data.value = 0
    await tick(dut)
    dut.send.value = 0
    await tick(dut)
    assert int(dut.busy.value) == 1
    assert int(dut.tx.value) == 0
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.send.value = 1
    dut.data.value = 255
    await Timer(2, unit="ns")
    assert int(dut.busy.value) == 1, "Reset must have no asynchronous effect"
    assert int(dut.tx.value) == 0, "Reset must wait for the clock edge"
    await tick(dut)
    assert int(dut.busy.value) == 0, "Reset must abort the frame and override send"
    assert int(dut.tx.value) == 1
    dut.send.value = 0
    dut.rst_n.value = 1
    for _ in range(12 * divisor(dut)):
        await tick(dut)
        assert int(dut.busy.value) == 0
        assert int(dut.tx.value) == 1, "Aborted data must not reappear after reset"


@cocotb.test()
async def idle_high_and_edge_only_acceptance(dut):
    await reset(dut)
    for _ in range(3 * divisor(dut)):
        await tick(dut)
        assert int(dut.busy.value) == 0
        assert int(dut.tx.value) == 1
    dut.clk.value = 0
    dut.send.value = 1
    dut.data.value = 165
    await Timer(2, unit="ns")
    assert int(dut.busy.value) == 0, "send must wait for a rising edge"
    assert int(dut.tx.value) == 1
    await frame(dut, 165)


@cocotb.test()
async def exact_bit_period_and_lsb_first_patterns(dut):
    await reset(dut)
    for value in (0, 255, 85, 166, 129):
        await frame(dut, value)


@cocotb.test()
async def input_latched_and_busy_requests_ignored(dut):
    await reset(dut)
    await frame(dut, 150, noise=True)
    for _ in range(12 * divisor(dut)):
        await tick(dut)
        assert int(dut.busy.value) == 0, "Busy requests must not queue a later frame"
        assert int(dut.tx.value) == 1


@cocotb.test()
async def next_frame_after_complete_stop_bit(dut):
    await reset(dut)
    await frame(dut, 18)
    await frame(dut, 231)
    await frame(dut, 0)


@cocotb.test()
async def randomized_cycle_reference(dut):
    await reset(dut)
    clocks = divisor(dut)
    generator = random.Random(130)
    elapsed = None
    captured = 0
    for cycle in range(900):
        send = int(generator.random() < 0.35)
        data = generator.randrange(256)
        resetting = cycle in (37, 38, 179, 411, 602)
        dut.rst_n.value = int(not resetting)
        dut.send.value = send
        dut.data.value = data
        if resetting:
            elapsed = None
        elif elapsed is None:
            if send:
                elapsed = 0
                captured = data
        else:
            elapsed += 1
            if elapsed == 10 * clocks:
                elapsed = None
        expected_busy = int(elapsed is not None)
        if elapsed is None:
            expected_tx = 1
        elif elapsed < clocks:
            expected_tx = 0
        elif elapsed < 9 * clocks:
            expected_tx = (captured >> (elapsed // clocks - 1)) & 1
        else:
            expected_tx = 1
        await tick(dut)
        assert int(dut.busy.value) == expected_busy, f"Reference busy mismatch at clock {cycle}"
        assert int(dut.tx.value) == expected_tx, f"Reference serial mismatch at clock {cycle}"
