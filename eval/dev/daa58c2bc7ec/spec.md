An unsigned 8-bit integer divider with remainder. Pulse start only while idle and latch a,b then. For b!=0 produce val=a//b, rem=a%b, valid=1 and dbz=0. For b=0 produce valid=0, dbz=1; val/rem are unspecified. busy is high while pending, done pulses for one clock on completion, and valid plus successful results hold until the next start. A new start clears valid. Any latency up to 64 clocks after start is acceptable, including immediate completion. Synchronous active-low rst_n clears flags/results and aborts an operation.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input start, output busy, output done, output valid, output dbz, input a[7:0], input b[7:0], output val[7:0], output rem[7:0].
Use synthesizable Verilog-2005. Target 25 MHz.

This is a standalone digital core. Its interface may exceed a single Tiny Tapeout harness pin budget; Tiny Tapeout pin-fit is not a requirement. Produce a clean standalone layout rather than claim shuttle pin compatibility.
