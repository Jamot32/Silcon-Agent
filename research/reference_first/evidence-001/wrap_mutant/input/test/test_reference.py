"""Neutral 3-bit saturating accumulator; synchronous reset and clear."""
class ReferenceModel:
    def __init__(self):
        self.reset()

    def reset(self):
        self.q = 0

    def step(self, inputs):
        if not inputs['rst_n'] or inputs['clear']:
            self.reset()
        elif inputs['enable']:
            self.q = min(7, self.q + inputs['amount'])
        return {'q': self.q}


"""Host-assembled neutral cocotb tests; literal expectations are hand-checked."""
import cocotb
from cocotb.triggers import ReadOnly, Timer


async def cycle(dut, model, rst_n, clear, enable, amount, expected):
    dut.clk.value = 0
    dut.rst_n.value = rst_n
    dut.clear.value = clear
    dut.enable.value = enable
    dut.amount.value = amount
    await Timer(1, unit='ns')
    dut.clk.value = 1
    await Timer(1, unit='ns')
    await ReadOnly()
    predicted = model.step({'rst_n': rst_n, 'clear': clear, 'enable': enable, 'amount': amount})['q']
    assert predicted == expected, f'model: expected literal {expected}, got {predicted}'
    assert dut.q.value.is_resolvable, f'DUT output unresolved: {dut.q.value}'
    actual = int(dut.q.value)
    assert actual == predicted, f'DUT: expected {predicted}, got {actual}'
    await Timer(1, unit='ns')
    dut.clk.value = 0
    await Timer(1, unit='ns')


@cocotb.test()
async def test_reset_then_add(dut):
    model = ReferenceModel()
    await cycle(dut, model, 0, 0, 1, 7, 0)
    await cycle(dut, model, 1, 0, 1, 2, 2)
    await cycle(dut, model, 1, 0, 1, 3, 5)


@cocotb.test()
async def test_disabled_holds(dut):
    model = ReferenceModel()
    await cycle(dut, model, 0, 0, 0, 0, 0)
    await cycle(dut, model, 1, 0, 1, 4, 4)
    await cycle(dut, model, 1, 0, 0, 7, 4)


@cocotb.test()
async def test_saturates_instead_of_wrapping(dut):
    model = ReferenceModel()
    await cycle(dut, model, 0, 0, 0, 0, 0)
    await cycle(dut, model, 1, 0, 1, 5, 5)
    await cycle(dut, model, 1, 0, 1, 4, 7)
    await cycle(dut, model, 1, 0, 1, 1, 7)


@cocotb.test()
async def test_clear_has_priority(dut):
    model = ReferenceModel()
    await cycle(dut, model, 0, 0, 0, 0, 0)
    await cycle(dut, model, 1, 0, 1, 6, 6)
    await cycle(dut, model, 1, 1, 1, 3, 0)
    await cycle(dut, model, 0, 0, 1, 5, 0)
