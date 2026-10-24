Please help me make this little digital chip. A Moore controller for a walking character. Asynchronous rst_n=0 starts walk_left. A left bump while walking left reverses to right; right bump while walking right reverses to left; both bumps still reverse. ground=0 takes priority and enters falling, asserting aaah with both walk outputs low. While falling ignore bumps and remember direction. On ground returning, resume the remembered direction; bumps in that landing cycle are ignored.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input bump_left, input bump_right, input ground, output walk_left, output walk_right, output aaah.
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
