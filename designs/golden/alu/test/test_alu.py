import cocotb
from cocotb.triggers import Timer


async def check(dut, a, b, op, result, carry):
    dut.a.value = a
    dut.b.value = b
    dut.op.value = op
    await Timer(1, unit="ns")
    assert int(dut.result.value) == result, f"a={a}, b={b}, op={op}"
    assert int(dut.carry.value) == carry, f"carry: a={a}, b={b}, op={op}"
    assert int(dut.zero.value) == int(result == 0), f"zero: a={a}, b={b}, op={op}"


@cocotb.test()
async def exhaustive_add_and_subtract_flags(dut):
    for a in range(16):
        for b in range(16):
            await check(dut, a, b, 0, (a + b) & 15, int(a + b > 15))
            await check(dut, a, b, 1, (a - b) & 15, int(a >= b))


@cocotb.test()
async def exhaustive_bitwise_operations(dut):
    for a in range(16):
        for b in range(16):
            await check(dut, a, b, 2, a & b, 0)
            await check(dut, a, b, 3, a | b, 0)
            await check(dut, a, b, 4, a ^ b, 0)


@cocotb.test()
async def single_bit_shifts_and_shifted_out_carry(dut):
    for a in range(16):
        for b in range(16):
            await check(dut, a, b, 5, (a << 1) & 15, (a >> 3) & 1)
            await check(dut, a, b, 6, a >> 1, a & 1)


@cocotb.test()
async def reserved_operation_has_full_assignments(dut):
    for a in range(16):
        for b in range(16):
            await check(dut, a, b, 0, (a + b) & 15, int(a + b > 15))
            await check(dut, a, b, 7, 0, 0)
            await check(dut, a, b, 1, (a - b) & 15, int(a >= b))
            await check(dut, a, b, 7, 0, 0)
