Hand-written, purely combinational 4-bit ALU. It has no clock or reset.

Inputs are `a[3:0]`, `b[3:0]`, and `op[2:0]`; outputs are `result[3:0]`, `zero`, and `carry`. Operation codes: 0 add, 1 subtract, 2 AND, 3 OR, 4 XOR, 5 one-bit logical left shift of a, 6 one-bit logical right shift of a, 7 reserved (result/carry zero). Shifts ignore b. Arithmetic wraps modulo 16. Carry means carry-out for add, no-borrow for subtract, and the shifted-out bit for shifts; logic/reserved operations clear carry. Zero is true exactly when result is zero.

Four independent cocotb tests exhaustively cover all operands, operation results, zero/carry flags, shifts, and transitions through reserved operation 7 to expose incomplete assignments. Tests use propagation waits only and never invent a clock input. A physical-flow clock period, if present, is a virtual timing constraint, not a clock port or measured Fmax.

The pinned [LibreLane 3.0.16 base SDC](https://github.com/librelane/librelane/blob/3.0.16/librelane/scripts/base.sdc) creates `__VIRTUAL_CLK__` when no clock port is supplied and applies input/output delay constraints against that virtual clock.
