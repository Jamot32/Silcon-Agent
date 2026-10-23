import cocotb
from cocotb.triggers import Timer


async def tick(dut):
    dut.clk.value = 0
    await Timer(5, unit="ns")
    dut.clk.value = 1
    await Timer(5, unit="ns")


async def reset(dut, duty=0):
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.duty.value = duty
    await tick(dut)
    assert int(dut.pwm_out.value) == 0
    dut.rst_n.value = 1


def period(dut):
    value = int(dut.PERIOD.value)
    assert 1 <= value <= 256
    return value


@cocotb.test()
async def synchronous_reset_restarts_phase(dut):
    await reset(dut, 1)
    await tick(dut)
    assert int(dut.pwm_out.value) == 1
    dut.clk.value = 0
    dut.rst_n.value = 0
    await Timer(2, unit="ns")
    assert int(dut.pwm_out.value) == 1, "Reset must wait for the rising edge"
    await tick(dut)
    assert int(dut.pwm_out.value) == 0
    dut.rst_n.value = 1
    await tick(dut)
    assert int(dut.pwm_out.value) == 1, "First active edge must compare phase zero"


@cocotb.test()
async def zero_duty_is_always_low(dut):
    await reset(dut, 0)
    for _ in range(2 * period(dut) + 3):
        await tick(dut)
        assert int(dut.pwm_out.value) == 0


@cocotb.test()
async def duty_boundaries_and_exact_period(dut):
    clocks = period(dut)
    for duty in (1, 2, 63, 128, 254, 255):
        await reset(dut, duty)
        high_count = 0
        for cycle in range(2 * clocks):
            await tick(dut)
            expected = int(cycle % clocks < duty)
            assert int(dut.pwm_out.value) == expected, f"duty={duty}, cycle={cycle}"
            high_count += int(dut.pwm_out.value)
        assert high_count == 2 * min(duty, clocks)


@cocotb.test()
async def duty_changes_sampled_at_edges(dut):
    await reset(dut, 0)
    clocks = period(dut)
    for cycle in range(2 * clocks + 19):
        duty = (cycle * 73 + 19) & 255
        previous = int(dut.pwm_out.value)
        dut.clk.value = 0
        dut.duty.value = duty
        await Timer(2, unit="ns")
        assert int(dut.pwm_out.value) == previous, "Duty changes must not change the registered output asynchronously"
        await tick(dut)
        assert int(dut.pwm_out.value) == int(cycle % clocks < duty)
