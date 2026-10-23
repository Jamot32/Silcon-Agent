Hand-written UART transmitter reference, independent of model-generated designs.

- Verilog-2005, 8 data bits, no parity, one stop bit, least significant bit first.
- `BAUD_DIV` is a positive integer number of clock periods per serial bit; default 4.
- `rst_n` is synchronous and active low. Reset aborts a frame, sets `busy=0`, and drives `tx=1`.
- An idle rising edge with `send=1` latches `data[7:0]`, sets `busy=1`, and starts `tx=0`.
- Start, each data bit, and stop last exactly `BAUD_DIV` clock periods. `busy` remains high for all ten bits and clears at the end of the complete stop bit.
- Data changes and send requests while busy are ignored, including the edge that completes a frame. A new request can be accepted on the following rising edge; requests are not queued.

The six cocotb tests check reset priority and timing, idle behavior, exact bit periods and bit order, input latching and rejected busy requests, consecutive frames, and a deterministic randomized cycle reference. They observe only ports and the public `BAUD_DIV` parameter.

`config.json` uses the established golden-counter sky130 baseline. The config alone is not evidence that this UART has completed physical design or Tiny Tapeout integration.
