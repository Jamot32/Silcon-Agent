Hand-written 8-bit PWM reference, independent of model-generated designs.

Inputs are `clk`, synchronous active-low `rst_n`, and `duty[7:0]`; output is registered `pwm_out`. The integer parameter `PERIOD` is 1 through 256, default 256. Reset clears the internal phase and output. Each subsequent rising edge compares phase 0 through PERIOD-1 against the current duty, then advances the phase modulo PERIOD. The output is high when phase is below duty; duty zero is always low, and duty at least PERIOD is always high. At default PERIOD=256, duty255 produces 255 high periods and one low period.

Four independent cocotb tests cover synchronous reset/phase restart, zero duty, boundary duties and wrap timing, and live duty changes sampled at rising edges. They observe only ports and the public PERIOD parameter.
