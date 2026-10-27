"""Neutral, hand-authored qualification expectations; not generated tests."""
import cocotb
import sa_clock
from sa_clock import ClockReset, check_value


@cocotb.test()
async def test_initial_reset_and_nba_settle(dut):
    assert sa_clock.__file__ == "/opt/silicon-python/sa_clock.py"
    assert not dut.q.value.is_resolvable
    bench = ClockReset(dut.clk, dut.rst_n)
    await bench.reset([(dut.enable, 0), (dut.d, 0)], [(dut.q, 0, "reset q")])
    await bench.cycle([(dut.enable, 1), (dut.d, 7)],
                      [(dut.q, 0, "before q"), (dut.combined, 1, "before comb")],
                      [(dut.q, 7, "after q"), (dut.combined, 8, "after comb")])


@cocotb.test()
async def test_hold_and_reset_while_busy(dut):
    bench = ClockReset(dut.clk, dut.rst_n)
    await bench.reset([(dut.enable, 0), (dut.d, 0)], [(dut.q, 0, "first reset")])
    await bench.cycle([(dut.enable, 1), (dut.d, 5)], [], [(dut.q, 5, "load")])
    await bench.cycle([(dut.enable, 0), (dut.d, 9)], [], [(dut.q, 5, "hold")])
    await bench.reset([(dut.enable, 1), (dut.d, 12)], [(dut.q, 0, "busy reset")], cycles=1)
    await bench.reset([(dut.enable, 0), (dut.d, 0)], [(dut.q, 0, "repeat reset")])


@cocotb.test()
async def test_unresolved_control_and_explicit_mask(dut):
    bench = ClockReset(dut.clk, dut.rst_n)
    await bench.reset([(dut.enable, 0), (dut.d, 0)], [(dut.q, 0, "reset")])
    assert not dut.unknown_control.value.is_resolvable
    try:
        check_value(dut.unknown_control, 0, "required control")
    except AssertionError as error:
        assert "unresolved" in str(error)
    else:
        raise AssertionError("unknown control was accepted")
    check_value(dut.unknown_payload, None, "unspecified payload")
    try:
        check_value(dut.unknown_payload, 0, "required payload")
    except AssertionError as error:
        assert "unresolved" in str(error)
    else:
        raise AssertionError("unknown required payload was accepted")


@cocotb.test()
async def test_cycle_requires_completed_reset(dut):
    bench = ClockReset(dut.clk, dut.rst_n)
    try:
        await bench.cycle([], [], [])
    except RuntimeError as error:
        assert "reset" in str(error)
    else:
        raise AssertionError("uninitialized cycle was accepted")
