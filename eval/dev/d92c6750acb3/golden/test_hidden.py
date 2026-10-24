"""Evaluator-authored cocotb adapter for pinned external reference RTL.

This is copied into each private case. It is not a human-authored golden design.
The compare uses reference X bits as don't-cares, but candidate X bits fail for
every defined reference bit. Data buses are compared only when their contract
marks them valid. Fixed seeds make each trial exactly reproducible.
"""
import random

import cocotb
from cocotb.triggers import Timer
from oracle_config import CONFIG


class Check:
    def __init__(self, dut, seed):
        self.dut = dut
        self.random = random.Random(seed)
        self.comparisons = 0
        self.inputs = {port['name']: port['width'] for port in CONFIG['ports'] if port['direction'] == 'input'}
        self.outputs = [port['name'] for port in CONFIG['ports'] if port['direction'] == 'output']
        for name in self.inputs:
            getattr(dut, name).value = 0
        self.dut.clk.value = 0
        self.dut.rst_n.value = 0

    def reference(self, name):
        value = getattr(self.dut, 'ref_' + name).value
        return int(value) if value.is_resolvable else None

    def compare(self):
        for name in self.outputs:
            guard = CONFIG.get('output_guards', {}).get(name)
            if guard and self.reference(guard) != 1:
                continue
            reference = str(getattr(self.dut, 'ref_' + name).value).lower()
            candidate = str(getattr(self.dut, 'dut_' + name).value).lower()
            for expected, actual in zip(reference, candidate):
                if expected in '01':
                    assert actual == expected, f'{name}: got {candidate}, expected {reference}'
                    self.comparisons += 1

    async def tick(self, values=None, *, compare=True):
        self.dut.clk.value = 0
        for name, value in (values or {}).items():
            if name not in self.inputs and CONFIG.get('driven_constants', {}).get(name) == value:
                continue
            getattr(self.dut, name).value = value & ((1 << self.inputs[name]) - 1)
        await Timer(2, unit='ns')
        if compare:
            self.compare()
        self.dut.clk.value = 1
        await Timer(2, unit='ns')
        if compare:
            self.compare()

    async def reset(self):
        defaults = CONFIG.get('input_defaults', {})
        await self.tick({**defaults, 'rst_n': 0}, compare=False)
        await self.tick({'rst_n': 0})
        await self.tick({'rst_n': 1})
        for vector in CONFIG.get('warmup', []):
            await self.tick(vector)


async def generic(check, phase):
    await check.reset()
    for vector in CONFIG.get('directed', []):
        await check.tick(vector)
    names = [name for name in check.inputs if name not in ('clk', 'rst_n')]
    cycles = CONFIG.get('cycles', 600)
    constants = CONFIG.get('input_defaults', {})
    allowed = CONFIG.get('allowed_values', {})
    for cycle in range(cycles):
        values = {}
        for name in names:
            if name in constants:
                values[name] = constants[name]
            elif name in allowed:
                values[name] = check.random.choice(allowed[name])
            elif phase == 0:
                values[name] = 0 if cycle % 3 else (1 << check.inputs[name]) - 1
            elif phase == 1:
                values[name] = (cycle * 17 + 3) & ((1 << check.inputs[name]) - 1)
            elif phase == 2:
                values[name] = check.random.getrandbits(check.inputs[name])
            else:
                values[name] = 1 << (cycle % check.inputs[name])
        for group in CONFIG.get('mutually_exclusive', []):
            if sum(bool(values.get(name)) for name in group) > 1:
                for name in group[1:]:
                    values[name] = 0
        if phase == 3 and cycle in (31, 137, 249):
            await check.tick({'rst_n': 0})
            await check.tick({'rst_n': 1})
        await check.tick(values)


async def uart_tx(check, phase):
    await check.reset()
    width = check.inputs['s_axis_tdata']
    prescale = CONFIG['input_defaults']['prescale']
    for word in [0, (1 << width) - 1, 0x55 & ((1 << width)-1), check.random.getrandbits(width)]:
        for _ in range(30):
            if check.reference('s_axis_tready') == 1:
                break
            await check.tick({'s_axis_tvalid': 0})
        await check.tick({'s_axis_tvalid': 1, 's_axis_tdata': word})
        # Valid stays low while serial output completes; changing tdata is legal.
        for cycle in range((width + 4) * prescale * 8 + 12):
            await check.tick({'s_axis_tvalid': 0, 's_axis_tdata': check.random.getrandbits(width)})
        if phase == 3:
            await check.tick({'rst_n': 0})
            await check.tick({'rst_n': 1})


async def uart_rx(check, phase):
    await check.reset()
    width = CONFIG['reference_parameters']['DATA_WIDTH']
    clocks = CONFIG['input_defaults']['prescale'] * 8
    for index, word in enumerate([0, (1 << width)-1, 0x55 & ((1 << width)-1), check.random.getrandbits(width)]):
        for bit in [1, 0] + [(word >> bit) & 1 for bit in range(width)] + [0 if phase == 3 and index == 1 else 1, 1, 1]:
            for cycle in range(clocks):
                await check.tick({'rxd': bit, 'm_axis_tready': 0 if phase == 2 else 1})
        for _ in range(clocks * 3):
            await check.tick({'rxd': 1, 'm_axis_tready': 1})


async def fifo(check, phase):
    await check.reset()
    for cycle in range(500):
        # Fill, full/backpressure, drain, then simultaneous randomized transfers.
        valid = 1 if cycle < 100 else 0 if cycle < 200 else check.random.randrange(2)
        ready = 0 if cycle < 100 else 1 if cycle < 200 else check.random.randrange(2)
        await check.tick({'s_axis_tdata': (cycle*13 + phase*17) & 255, 's_axis_tvalid': valid, 'm_axis_tready': ready})
    if phase == 3:
        await check.tick({'rst_n': 0})
        await check.tick({'rst_n': 1, 's_axis_tvalid': 0, 'm_axis_tready': 1})
        for _ in range(20):
            await check.tick()


async def spi(check, phase):
    await check.reset()
    half = CONFIG['reference_parameters']['CLKS_PER_HALF_BIT']
    for word in [0, 255, 0xA5, 0x5A, check.random.getrandbits(8)]:
        for _ in range(100):
            if check.reference('tx_ready') == 1:
                break
            await check.tick({'tx_valid': 0})
        await check.tick({'tx_data': word, 'tx_valid': 1})
        for cycle in range(half * 20 + 12):
            await check.tick({'tx_valid': 0, 'miso': ((cycle // half) ^ phase) & 1})


async def maths(check, phase):
    await check.reset()
    width = check.inputs['a']
    vectors = [(0,1), (1,1), (7,3), (31,7), ((1<<width)-1, 1), (10,0)]
    vectors += [(check.random.getrandbits(width), check.random.getrandbits(width)) for _ in range(20)]
    for a, b in vectors:
        await check.tick({'start': 1, 'a': a, 'b': b})
        await check.tick({'start': 0})
        for _ in range(width*3 + 20):
            if check.reference('busy') == 0:
                break
            # Operands may change after start; the implementation must latch them.
            await check.tick({'a': check.random.getrandbits(width), 'b': check.random.getrandbits(width)})
        for _ in range(3):
            await check.tick()
    if phase == 3:
        await check.tick({'start': 1, 'a': 23, 'b': 3})
        await check.tick({'rst_n': 0, 'start': 0})
        await check.tick({'rst_n': 1})


async def vga(check, phase):
    await check.reset()
    params = CONFIG['reference_parameters']
    total = (params['H_RES'] + params['H_FP'] + params['H_SYNC'] + params['H_BP']) * (params['V_RES'] + params['V_FP'] + params['V_SYNC'] + params['V_BP'])
    for _ in range(total * 2 + 4):
        await check.tick()


async def i2c(check, phase):
    await check.reset()
    # Host requests include write and read, START/STOP, idle release, and NACK.
    # Model a pulled-up open drain bus: reference_o is the master's release bit;
    # external ACK/data pull SDA low on selected cycles. Candidate must match all
    # observable bus and status cycles under the same resolved input stimulus.
    for transaction in range(3):
        read = transaction == 2
        for _ in range(50):
            if check.reference('s_axis_cmd_ready') == 1:
                break
            await check.tick({'scl_i': check.reference('scl_o') or 0, 'sda_i': check.reference('sda_o') or 0})
        await check.tick({'s_axis_cmd_address': (0x50 + phase) & 0x7f, 's_axis_cmd_start': 1, 's_axis_cmd_read': int(read), 's_axis_cmd_write': int(not read), 's_axis_cmd_stop': 1, 's_axis_cmd_valid': 1, 's_axis_data_tdata': 0xA5 ^ phase, 's_axis_data_tvalid': 1, 's_axis_data_tlast': 1})
        for cycle in range(700):
            scl = check.reference('scl_o')
            sda = check.reference('sda_o')
            await check.tick({'s_axis_cmd_valid': 0, 's_axis_data_tvalid': int(cycle < 100), 'scl_i': 0 if phase == 2 and 30 <= cycle < 40 else (scl or 0), 'sda_i': (sda or 0) & (0 if transaction == 1 and cycle % 13 < 4 else 1), 'm_axis_data_tready': 0 if phase == 1 and cycle < 200 else 1})
        await check.tick({'scl_i': 1, 'sda_i': 1})


SCENARIOS = {'generic': generic, 'uart_tx': uart_tx, 'uart_rx': uart_rx, 'fifo': fifo, 'spi': spi, 'maths': maths, 'vga': vga, 'i2c': i2c}


async def run(dut, phase):
    check = Check(dut, CONFIG['seed'] + phase)
    await SCENARIOS[CONFIG['scenario']](check, phase)
    assert check.comparisons >= 16, 'Oracle never observed enough defined output bits'


@cocotb.test()
async def reset_and_directed(dut):
    await run(dut, 0)


@cocotb.test()
async def normal_operation(dut):
    await run(dut, 1)


@cocotb.test()
async def deterministic_randomized(dut):
    await run(dut, 2)


@cocotb.test()
async def boundaries_and_reset_interruption(dut):
    await run(dut, 3)
