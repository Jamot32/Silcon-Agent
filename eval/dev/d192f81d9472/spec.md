Pls make this small chip; I want it to do this: A serial receiver taking exactly one input in bit per rising clock: idle=1, start=0, eight LSB-first data bits, then stop=1. done is a one-cycle pulse after a valid stop; out_byte is valid only when done=1. A bad stop enters an error state that waits for a high bit before searching for another start. Consecutive frames may have no extra idle bit. Synchronous rst_n=0 returns to idle.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input in, output out_byte[7:0], output done.
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
