Please help me make this little digital chip. A 5-bit maximal-length Galois LFSR. Synchronous rst_n=0 seeds q=1. Each clock q_next[4]=q[0], q_next[3]=q[4], q_next[2]=q[3] XOR q[0], q_next[1]=q[2], q_next[0]=q[1].

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; output q[4:0].
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
