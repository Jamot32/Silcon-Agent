"""Research-only cocotb clock/reset primitive; single synchronous clock."""
from cocotb.triggers import ReadOnly, Timer


def check_value(signal, expected, label):
    """None explicitly means do not inspect this unspecified signal."""
    if expected is None:
        return
    value = signal.value
    if not value.is_resolvable:
        raise AssertionError(f"{label}: unresolved value {value}")
    actual = int(value)
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def _check(checks):
    for signal, expected, label in checks:
        check_value(signal, expected, label)


def _drive(inputs):
    for signal, value in inputs:
        signal.value = value


class ClockReset:
    """Explicit handles, no RTL introspection, background clock or DUT oracle."""

    def __init__(self, clock, reset_n):
        self.clock = clock
        self.reset_n = reset_n
        self._reset_done = False

    async def reset(self, inputs, checks, cycles=2):
        if type(cycles) is not int or cycles < 1:
            raise ValueError("reset cycles must be a positive integer")
        self._reset_done = False
        self.clock.value = 0
        self.reset_n.value = 0
        _drive(inputs)
        for _ in range(cycles):
            await Timer(1, unit="ns")
            self.clock.value = 1
            await Timer(1, unit="ns")
            await ReadOnly()
            _check(checks)
            await Timer(1, unit="ns")
            self.clock.value = 0
        await Timer(1, unit="ns")
        self._reset_done = True

    async def cycle(self, inputs, before, after):
        if not self._reset_done:
            raise RuntimeError("reset must complete before normal cycles")
        self.clock.value = 0
        self.reset_n.value = 1
        _drive(inputs)
        await Timer(1, unit="ns")
        await ReadOnly()
        _check(before)
        await Timer(1, unit="ns")
        self.clock.value = 1
        await Timer(1, unit="ns")
        await ReadOnly()
        _check(after)
        await Timer(1, unit="ns")
        self.clock.value = 0
        await Timer(1, unit="ns")
