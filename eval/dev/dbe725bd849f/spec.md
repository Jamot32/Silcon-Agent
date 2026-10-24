Please help me make this little digital chip. A parallel byte-stream CRC-32 engine, Galois polynomial 32'h04c11db7, initial all-ones internal state, reflected LSB-first input/output, and bitwise complemented crc_out. Each data_in_valid clock updates the state for all 8 bits of data_in; otherwise hold. Synchronous rst_n=0 restores the all-ones state, so crc_out is zero. The highest polynomial term is implicit. No start/end framing signal: use reset to begin a new message.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input data_in[7:0], input data_in_valid, output crc_out[31:0].
Fixed configuration (implement these values; parameters with these defaults are optional): LFSR_WIDTH=32, LFSR_POLY=32'h04c11db7, LFSR_INIT=32'hffffffff, LFSR_CONFIG="GALOIS", REVERSE=1, INVERT=1, DATA_WIDTH=8, STYLE="REDUCTION".
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.

This is a standalone digital core. Its interface may exceed a single Tiny Tapeout harness pin budget; Tiny Tapeout pin-fit is not a requirement. Produce a clean standalone layout rather than claim shuttle pin compatibility.
