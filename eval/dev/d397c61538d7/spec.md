Need a working Verilog block for my project: For each bit of the 8-bit input in, pedge is a registered one-cycle pulse on a sampled 0-to-1 transition only. The rst_n input is reserved and has no effect; initial internal state is unspecified until enough input samples or a load establish it.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input in[7:0], output pedge[7:0].
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
