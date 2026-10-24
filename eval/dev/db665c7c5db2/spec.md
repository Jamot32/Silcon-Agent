Can you build this controller? Find three-byte packet boundaries in the input byte stream in. Discard bytes until a byte with bit3=1 appears; it is byte1. Accept the next two bytes regardless of bit3. done is high in the cycle immediately following the third sampled byte, and a new packet can start on the next byte. Synchronous rst_n=0 returns to searching.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input in[7:0], output done.
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
