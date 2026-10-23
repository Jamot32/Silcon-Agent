import random

import cocotb
from cocotb.triggers import Timer


async def tick(dut):
    dut.clk.value = 0
    await Timer(5, unit="ns")
    dut.clk.value = 1
    await Timer(5, unit="ns")


def outputs(dut):
    values = (int(dut.green.value), int(dut.yellow.value), int(dut.red.value), int(dut.walk.value))
    assert sum(values[:3]) == 1, "Exactly one vehicle signal must be active"
    assert not values[3] or values == (0, 0, 1, 1), "Walk must only coexist with red"
    return values


def durations(dut):
    values = {"green": int(dut.GREEN_CYCLES.value), "yellow": int(dut.YELLOW_CYCLES.value),
              "red": int(dut.RED_CYCLES.value), "walk": int(dut.WALK_CYCLES.value)}
    assert all(1 <= value <= 255 for value in values.values())
    return values


async def reset(dut):
    dut.clk.value = 0
    dut.rst_n.value = 0
    dut.ped_request.value = 0
    await tick(dut)
    assert outputs(dut) == (0, 0, 1, 0)
    dut.rst_n.value = 1


async def phase(dut, current, clocks, following):
    assert outputs(dut) == current
    for edge in range(1, clocks + 1):
        await tick(dut)
        assert outputs(dut) == (current if edge < clocks else following), f"Wrong transition at phase edge {edge}"


async def reach_green(dut):
    await phase(dut, (0, 0, 1, 0), durations(dut)["red"], (1, 0, 0, 0))


async def await_walk(dut):
    for _ in range(sum(durations(dut).values()) + 2):
        if outputs(dut)[3]:
            return
        await tick(dut)
    assert False, "Latched request was not served at the safe red phase"


@cocotb.test()
async def synchronous_safe_reset(dut):
    await reset(dut)
    await reach_green(dut)
    dut.clk.value = 0
    dut.rst_n.value = 0
    await Timer(2, unit="ns")
    assert outputs(dut) == (1, 0, 0, 0), "Reset must wait for a rising edge"
    await tick(dut)
    assert outputs(dut) == (0, 0, 1, 0)


@cocotb.test()
async def exact_normal_phase_durations(dut):
    await reset(dut)
    times = durations(dut)
    for _ in range(3):
        await phase(dut, (0, 0, 1, 0), times["red"], (1, 0, 0, 0))
        await phase(dut, (1, 0, 0, 0), times["green"], (0, 1, 0, 0))
        await phase(dut, (0, 1, 0, 0), times["yellow"], (0, 0, 1, 0))


@cocotb.test()
async def one_cycle_request_latched_until_red(dut):
    await reset(dut)
    await reach_green(dut)
    dut.ped_request.value = 1
    await tick(dut)
    dut.ped_request.value = 0
    await await_walk(dut)
    await phase(dut, (0, 0, 1, 1), durations(dut)["walk"], (0, 0, 1, 0))
    await reach_green(dut)


@cocotb.test()
async def held_request_is_served_once(dut):
    await reset(dut)
    await reach_green(dut)
    dut.ped_request.value = 1
    entries = 0
    was_walking = False
    for _ in range(4 * sum(durations(dut).values())):
        await tick(dut)
        walking = bool(outputs(dut)[3])
        entries += int(walking and not was_walking)
        was_walking = walking
    assert entries == 1, "A held button must not cause repeated walk phases"


@cocotb.test()
async def requests_during_walk_are_not_queued(dut):
    await reset(dut)
    await reach_green(dut)
    dut.ped_request.value = 1
    await tick(dut)
    dut.ped_request.value = 0
    await await_walk(dut)
    dut.ped_request.value = 1
    await tick(dut)
    dut.ped_request.value = 0
    while outputs(dut)[3]:
        await tick(dut)
    for _ in range(2 * sum(durations(dut).values())):
        await tick(dut)
        assert outputs(dut)[3] == 0


@cocotb.test()
async def randomized_public_state_reference(dut):
    await reset(dut)
    times = durations(dut)
    generator = random.Random(130)
    state, age, pending, previous_button = "red", 0, False, False
    expected = {"green": (1, 0, 0, 0), "yellow": (0, 1, 0, 0),
                "red": (0, 0, 1, 0), "walk": (0, 0, 1, 1)}
    for cycle in range(500):
        button = generator.random() < 0.25
        resetting = cycle in (43, 121, 122, 308)
        dut.rst_n.value = int(not resetting)
        dut.ped_request.value = int(button)
        if resetting:
            state, age, pending, previous_button = "red", 0, False, False
        else:
            rising = button and not previous_button
            previous_button = button
            pending = pending or rising and state != "walk"
            age += 1
            if age == times[state]:
                age = 0
                if state == "green":
                    state = "yellow"
                elif state == "yellow" or state == "walk":
                    state = "red"
                elif pending:
                    state, pending = "walk", False
                else:
                    state = "green"
        await tick(dut)
        assert outputs(dut) == expected[state], f"Reference mismatch at clock {cycle}"
