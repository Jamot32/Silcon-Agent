"""Functional transactions, with bounded latency rather than cycle equivalence."""
import random

import cocotb
from cocotb.triggers import Timer
from oracle_config import CONFIG
from arithmetic_oracle import expected, vectors

if CONFIG.get('kind') == 'python_fraction':
    from oracle_reference import Fraction
else:
    Fraction = None  # Unsigned divmod and serial protocols need no rational import.


class Bench:
    def __init__(self, dut, phase):
        self.dut = dut
        self.rng = random.Random(CONFIG['seed'] + phase)
        self.inputs = {p['name']: p['width'] for p in CONFIG['ports'] if p['direction'] == 'input'}
        self.output_names = [p['name'] for p in CONFIG['ports'] if p['direction'] == 'output']
        self.values = {name: 0 for name in self.inputs}
        for name in self.inputs:
            getattr(dut, name).value = 0

    def outputs(self):
        result = {}
        for name in self.output_names:
            value = getattr(self.dut, 'dut_' + name).value
            result[name] = int(value) if value.is_resolvable else None
        return result

    async def tick(self, values=None):
        self.dut.clk.value = 0
        for name, value in (values or {}).items():
            if name in self.inputs:
                self.values[name] = value & ((1 << self.inputs[name]) - 1)
                getattr(self.dut, name).value = self.values[name]
        await Timer(2, unit='ns')
        before = self.outputs()
        self.dut.clk.value = 1
        await Timer(2, unit='ns')
        return before, self.outputs()

    async def reset(self):
        await self.tick({**CONFIG.get('input_defaults', {}), 'rst_n': 0})
        await self.tick({'rst_n': 0})
        await self.tick({'rst_n': 1})


async def uart_tx(bench, phase):
    await bench.reset()
    assert bench.outputs()['txd'] == 1 and bench.outputs()['busy'] == 0
    width = bench.inputs['s_axis_tdata']
    bit_clocks = 16
    words = [0, (1 << width)-1, 0x55 & ((1 << width)-1), bench.rng.getrandbits(width)]
    for word in words:
        for _ in range(64):
            if bench.outputs()['s_axis_tready'] == 1:
                break
            await bench.tick({'s_axis_tvalid': 0})
        else:
            assert False, 'UART never became ready'
        before, after = await bench.tick({'s_axis_tvalid': 1, 's_axis_tdata': word})
        assert before['s_axis_tready'] == 1
        samples, busy, ready = [after['txd']], [after['busy']], [after['s_axis_tready']]
        for _ in range(32 + bit_clocks*(width+2) + 64):
            _, after = await bench.tick({'s_axis_tvalid': 0, 's_axis_tdata': bench.rng.getrandbits(width)})
            samples.append(after['txd']); busy.append(after['busy']); ready.append(after['s_axis_tready'])
        start = next((i for i, bit in enumerate(samples[:33]) if bit == 0), None)
        assert start is not None, 'Accepted UART byte produced no start bit'
        bits = [0] + [(word >> bit) & 1 for bit in range(width)]
        for index, bit in enumerate(bits):
            assert samples[start+index*bit_clocks:start+(index+1)*bit_clocks] == [bit]*bit_clocks, 'UART start/data bit content or duration is incorrect'
        stop = start + len(bits)*bit_clocks
        assert samples[stop:stop+bit_clocks] == [1]*bit_clocks, 'UART stop interval must be at least one bit'
        assert all(bit == 1 for bit in samples[stop:]), 'UART emitted an unrequested extra frame'
        assert busy[start:stop+bit_clocks] == [1]*(len(bits)*bit_clocks+bit_clocks), 'UART busy did not cover the complete frame'
        assert any(busy[i] == 0 and ready[i] == 1 for i in range(stop+bit_clocks, stop+bit_clocks+65)), 'UART ready completion exceeded the permitted post-frame delay'
        assert after['busy'] == 0 and after['s_axis_tready'] == 1, 'UART busy/ready did not complete within bound'
    if phase == 3:
        await bench.tick({'s_axis_tvalid': 1, 's_axis_tdata': 0x55})
        for _ in range(5):
            await bench.tick({'s_axis_tvalid': 0})
        _, after = await bench.tick({'rst_n': 0})
        assert after['txd'] == 1 and after['busy'] == 0


async def uart_rx(bench, phase):
    await bench.reset()
    width = CONFIG['reference_parameters']['DATA_WIDTH']
    received, errors, busy = [], {'frame_error': 0, 'overrun_error': 0}, []
    async def step(values=None, count=1):
        for _ in range(count):
            before, after = await bench.tick(values)
            if before['m_axis_tvalid'] == 1 and bench.values['m_axis_tready'] == 1:
                assert before['m_axis_tdata'] is not None
                received.append(before['m_axis_tdata'])
            for name in errors:
                errors[name] += after[name] == 1
            busy.append(after['busy'])
    async def frame(word, stop=1):
        beginning = len(busy)
        for bit in [0] + [(word >> bit) & 1 for bit in range(width)] + [stop]:
            await step({'rxd': bit}, 16)
        if stop:
            await step({'rxd': 1}, 40)
        assert busy[beginning+16:beginning+16*(width+1)] == [1]*(16*width), 'UART busy did not cover the data bits'
        if stop:
            assert bench.outputs()['busy'] == 0, 'UART busy did not clear after the frame'
    mask = (1 << width)-1
    if phase in (0, 1):
        await step({'rxd': 1, 'm_axis_tready': 1}, 16)
        words = [0, mask, 0x55 & mask, bench.rng.getrandbits(width)]
        for word in words:
            await frame(word)
        assert received == words, 'UART received bytes are missing, duplicated or incorrect'
        assert errors == {'frame_error': 0, 'overrun_error': 0}
        assert 1 in busy and bench.outputs()['busy'] == 0
        if phase == 1:
            await step({'m_axis_tready': 0})
            await frame(0x35 & mask)
            assert bench.outputs()['m_axis_tvalid'] == 1
            for _ in range(24):
                assert bench.outputs()['m_axis_tvalid'] == 1 and bench.outputs()['m_axis_tdata'] == (0x35 & mask), 'Pending UART output did not hold while stalled'
                await step()
            await step({'m_axis_tready': 1}, 8)
            assert received == words + [0x35 & mask]
    elif phase == 2:
        await step({'rxd': 1, 'm_axis_tready': 0}, 16)
        await frame(0x15 & mask)
        await frame(0x6A & mask)
        assert errors == {'overrun_error': 1, 'frame_error': 0}, 'Overrun must produce exactly one error pulse'
        assert bench.outputs()['m_axis_tvalid'] == 1 and bench.outputs()['m_axis_tdata'] == (0x6A & mask), 'Overrun must retain the latest completed byte'
        await step({'m_axis_tready': 1}, 12)
        assert received == [0x6A & mask]
    else:
        await step({'rxd': 1, 'm_axis_tready': 1}, 16)
        await frame(0x22 & mask, stop=0)
        assert not received and errors == {'frame_error': 1, 'overrun_error': 0}, 'Bad stop must produce exactly one frame-error pulse'
        # Framing-error resynchronization without reset is unspecified. Reset
        # before subsequent traffic instead of rewarding a particular recovery FSM.
        await step({'rst_n': 0, 'rxd': 1}, 2)
        await step({'rst_n': 1}, 16)
        await step({'rxd': 0}, 2)
        await step({'rxd': 1}, 48)
        assert not received, 'Short false start was accepted'
        await step({'rxd': 0}, 24)
        await step({'rst_n': 0, 'rxd': 1}, 2)
        await step({'rst_n': 1}, 48)
        assert bench.outputs()['m_axis_tvalid'] == 0 and bench.outputs()['busy'] == 0
        await frame(0x57 & mask)
        assert received == [0x57 & mask], 'Receiver did not recover after reset'
        assert errors == {'frame_error': 1, 'overrun_error': 0}


async def fifo(bench, phase):
    await bench.reset()
    depth = CONFIG['reference_parameters']['DEPTH']
    queue, stalled = [], None
    async def step(valid, data, ready):
        nonlocal stalled
        before, after = await bench.tick({'s_axis_tvalid': valid, 's_axis_tdata': data, 'm_axis_tready': ready})
        if stalled is not None:
            assert before['m_axis_tvalid'] == 1 and before['m_axis_tdata'] == stalled, 'FIFO output changed under backpressure'
        accepted = before['s_axis_tready'] == 1 and valid == 1
        if accepted:
            queue.append(data)
        if before['m_axis_tvalid'] == 1 and ready:
            assert queue, 'FIFO produced data without an accepted input'
            assert before['m_axis_tdata'] == queue.pop(0), 'FIFO reordered, lost or corrupted a beat'
        stalled = before['m_axis_tdata'] if before['m_axis_tvalid'] == 1 and not ready else None
        return accepted, after
    data = (phase*71 + 3) & 255
    accepted_count = 0
    for _ in range(depth+64):
        accepted, _ = await step(1, data, 0)
        if accepted:
            accepted_count += 1; data = (data+17) & 255
    assert accepted_count >= depth, 'FIFO capacity is below the requested minimum'
    assert accepted_count <= depth+2 and bench.outputs()['s_axis_tready'] == 0, 'FIFO exceeds the permitted capacity or fails to backpressure when full'
    # Finish the currently pending input without violating producer hold rules.
    pending = True
    for _ in range(depth+80):
        accepted, _ = await step(int(pending), data, 1)
        if accepted:
            pending = False
        if not pending and not queue and bench.outputs()['m_axis_tvalid'] == 0:
            break
    else:
        assert False, 'FIFO did not drain accepted inputs'
    pending, data = False, bench.rng.randrange(256)
    for _ in range(300):
        if not pending and bench.rng.randrange(3):
            pending = True
        accepted, _ = await step(int(pending), data, bench.rng.randrange(2))
        if accepted:
            pending = False; data = bench.rng.randrange(256)
    for _ in range(depth+100):
        accepted, _ = await step(int(pending), data, 1)
        if accepted:
            pending = False
        if not pending and not queue and bench.outputs()['m_axis_tvalid'] == 0:
            break
    else:
        assert False, 'Randomized FIFO traffic did not drain'
    # Reset with queued/stalled data must flush it rather than leak old beats.
    for word in range(4):
        await step(1, word, 0)
    _, after = await bench.tick({'rst_n': 0, 's_axis_tvalid': 0})
    assert after['m_axis_tvalid'] == 0
    queue.clear(); stalled = None
    await bench.tick({'rst_n': 1})
    for _ in range(8):
        await step(0, 0, 1)


async def spi(bench, phase):
    await bench.reset()
    mode = CONFIG['reference_parameters']['SPI_MODE']
    half = CONFIG['reference_parameters']['CLKS_PER_HALF_BIT']
    polarity, cpha = int(mode in (2, 3)), int(mode in (1, 3))
    assert bench.outputs()['sclk'] == polarity
    for word, response in [(0,255), (255,0), (0xA5,0x69), (bench.rng.randrange(256),bench.rng.randrange(256))]:
        for _ in range(64):
            if bench.outputs()['tx_ready'] == 1:
                break
            await bench.tick({'tx_valid': 0})
        else:
            assert False, 'SPI never became ready'
        previous = bench.outputs()['sclk']
        _, after = await bench.tick({'tx_valid': 1, 'tx_data': word, 'miso': (response >> 7) & 1})
        edges, sampled, rx, last_edge = 0, [], [], None
        previous_mosi, completed = after['mosi'], False
        for cycle in range(half*40 + 65):
            if cycle:
                bit = (response >> (7-len(sampled))) & 1 if len(sampled)<8 else 1
                _, after = await bench.tick({'tx_valid': 0, 'miso': bit})
            assert after['sclk'] in (0,1)
            changed = after['sclk'] != previous
            sampling_edge = changed and ((after['sclk'] != polarity) != bool(cpha))
            if sampled and after['mosi'] != previous_mosi:
                assert changed and not sampling_edge, 'MOSI changed away from a permitted non-sampling edge'
            if after['sclk'] != previous:
                if last_edge is None:
                    assert cycle <= half*20+32, 'SPI start exceeded the permitted latency'
                if last_edge is not None:
                    assert cycle-last_edge == half, 'SPI half-period differs from the configured divider'
                last_edge = cycle; edges += 1
                leading = after['sclk'] != polarity
                if leading != bool(cpha):
                    assert len(sampled)<8, 'Extra SPI sample edge'
                    sampled.append(after['mosi'])
                previous = after['sclk']
            if after['rx_valid'] == 1:
                rx.append(after['rx_data'])
            if 0 < edges < 16:
                assert after['tx_ready'] == 0, 'SPI ready asserted during the active transfer'
            if edges >= 16 and rx and after['tx_ready'] == 1:
                completed = True
                break
            previous_mosi = after['mosi']
        assert completed and edges == 16 and sampled == [(word >> i) & 1 for i in range(7,-1,-1)], 'SPI byte, edge count, or bounded ready completion is incorrect'
        assert rx == [response], 'SPI receive byte or completion pulse is incorrect'
        for _ in range(8):
            _, after = await bench.tick()
            assert after['sclk'] == polarity and after['rx_valid'] == 0


async def arithmetic(bench, phase):
    await bench.reset()
    assert bench.outputs()['busy'] == 0 and bench.outputs()['done'] == 0 and bench.outputs()['valid'] == 0
    for name in ('val', 'rem', 'dbz', 'ovf'):
        if name in bench.outputs():
            assert bench.outputs()[name] == 0, 'Arithmetic reset value is incorrect'
    width = CONFIG['reference_parameters']['WIDTH']
    for a, b in vectors(CONFIG, phase):
        wanted = expected(CONFIG, a, b, Fraction)
        _, after = await bench.tick({'a': a, 'b': b, 'start': 1})
        for _ in range(width*4 + 33):
            if after['done'] == 1:
                break
            assert after['busy'] == 1, 'Arithmetic busy must cover an outstanding transaction'
            assert after['valid'] == 0, 'New arithmetic operation did not clear prior result validity'
            # The operands must have been latched at the accepted start.
            _, after = await bench.tick({'start': 0, 'a': bench.rng.getrandbits(width), 'b': bench.rng.getrandbits(width)})
        else:
            assert False, 'Arithmetic transaction exceeded completion bound'
        assert after['busy'] == 0, 'Arithmetic done while still busy'
        for name, value in wanted.items():
            assert after[name] == value, f'Arithmetic {name}: got {after[name]}, expected {value}, a={a}, b={b}'
        for _ in range(3):
            _, after = await bench.tick({'start': 0})
            assert after['done'] == 0, 'done must be a one-cycle pulse'
            assert after['valid'] == wanted['valid'], 'Result validity did not hold until the next start'
            if wanted['valid']:
                for name in ('val', 'rem'):
                    if name in wanted:
                        assert after[name] == wanted[name], 'Completed arithmetic result did not hold until the next start'
    if phase == 3:
        await bench.tick({'a': 23, 'b': 3, 'start': 1})
        _, after = await bench.tick({'rst_n': 0, 'start': 0})
        assert after['busy'] == after['done'] == after['valid'] == 0


SCENARIOS = {'uart_tx': uart_tx, 'uart_rx': uart_rx, 'fifo': fifo, 'spi': spi, 'arithmetic': arithmetic}


async def run(dut, phase):
    await SCENARIOS[CONFIG['scenario']](Bench(dut, phase), phase)


@cocotb.test()
async def reset_and_directed(dut):
    await run(dut, 0)


@cocotb.test()
async def normal_transactions(dut):
    await run(dut, 1)


@cocotb.test()
async def deterministic_randomized(dut):
    await run(dut, 2)


@cocotb.test()
async def boundary_and_recovery(dut):
    await run(dut, 3)
