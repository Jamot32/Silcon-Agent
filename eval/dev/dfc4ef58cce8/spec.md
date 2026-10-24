Pls make this small chip; I want it to do this: A 10-bit countdown timer: when load=1 load data; otherwise decrement each clock until zero and saturate at zero. tc is combinational high exactly when the stored count is zero. The rst_n input is reserved and has no effect; initial internal state is unspecified until enough input samples or a load establish it.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input load, input data[9:0], output tc.
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
