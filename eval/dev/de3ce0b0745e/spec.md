Need a working Verilog block for my project: A 12-hour BCD clock. Each ena=1 clock increments one second; ena=0 holds. hh,mm,ss are packed BCD; hours run 01 through 12, minutes/seconds 00 through 59. pm toggles on 11:59:59 -> 12:00:00, not on 12:59:59 -> 01:00:00. Synchronous rst_n=0 sets 12:00:00 AM and has priority.

Exact interface: module `chip`, rising-edge `clk`, active-low `rst_n`; input ena, output pm, output hh[7:0], output mm[7:0], output ss[7:0].
Use synthesizable Verilog-2005. Target 25 MHz. No analog behavior is requested.

This is a standalone digital core. Its interface may exceed a single Tiny Tapeout harness pin budget; Tiny Tapeout pin-fit is not a requirement. Produce a clean standalone layout rather than claim shuttle pin compatibility.
