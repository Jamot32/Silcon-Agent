Can you build this controller? A 4-bit right shift register: asynchronous rst_n=0 clears q. Otherwise load has priority over ena; load data when load=1; else shift right filling the MSB with zero when ena=1; otherwise hold.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input load, input ena, input data[3:0], output q[3:0].
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
