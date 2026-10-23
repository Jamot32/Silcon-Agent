import cocotb
from cocotb.triggers import Timer


async def tick(dut):
    dut.clk.value = 0
    await Timer(5, unit="ns")
    dut.clk.value = 1
    await Timer(5, unit="ns")


async def reset(dut):
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.enable.value = 0
    dut.up.value = 1
    dut.load.value = 0
    dut.load_value.value = 0
    await tick(dut)
    dut.rst_n.value = 1


@cocotb.test()
async def synchronous_reset(dut):
    await reset(dut)
    dut.load.value = 1
    dut.load_value.value = 73
    await tick(dut)
    dut.clk.value = 0
    dut.rst_n.value = 0
    await Timer(2, unit="ns")
    assert int(dut.count.value) == 73, "Reset must wait for a rising edge"
    await tick(dut)
    assert int(dut.count.value) == 0


@cocotb.test()
async def count_and_hold(dut):
    await reset(dut)
    dut.enable.value = 1
    for expected in range(1, 17):
        await tick(dut)
        assert int(dut.count.value) == expected
    dut.enable.value = 0
    for _ in range(3):
        await tick(dut)
        assert int(dut.count.value) == 16


@cocotb.test()
async def load_has_priority(dut):
    await reset(dut)
    dut.enable.value = 1
    dut.load.value = 1
    dut.load_value.value = 165
    await tick(dut)
    assert int(dut.count.value) == 165
    dut.enable.value = 0
    dut.load_value.value = 42
    await tick(dut)
    assert int(dut.count.value) == 42, "Load must work while disabled"


@cocotb.test()
async def wrap_in_both_directions(dut):
    await reset(dut)
    dut.enable.value = 1
    dut.up.value = 0
    await tick(dut)
    assert int(dut.count.value) == 255
    dut.up.value = 1
    await tick(dut)
    assert int(dut.count.value) == 0
    dut.up.value = 0
    for expected in (255, 254, 253):
        await tick(dut)
        assert int(dut.count.value) == expected
