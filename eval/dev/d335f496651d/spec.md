Please help me make this little digital chip. For each bit of the 8-bit input in, anyedge reports whether that bit changed since the preceding clock sample. Register the pulse; both rising and falling edges count. The rst_n input is reserved and has no effect; initial internal state is unspecified until enough input samples or a load establish it.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input in[7:0], output anyedge[7:0].
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
