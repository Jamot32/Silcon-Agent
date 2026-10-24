Need a working Verilog block for my project: An HDLC bit-stream recognizer. Count consecutive input in=1 bits. After exactly five ones followed by zero, disc pulses high (stuffed zero); after six ones followed by zero, flag pulses high; a seventh consecutive one enters err and err remains high while ones continue. A zero clears the error. All pulses/status are Moore outputs of the updated registered state. A new sequence following a disc/flag starts with count one if the next bit is one. Synchronous rst_n=0 returns to zero consecutive ones.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input in, output disc, output flag, output err.
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.
