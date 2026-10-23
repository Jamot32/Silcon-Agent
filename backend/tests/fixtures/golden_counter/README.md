# Real golden-counter fixture

Recorded by `make eda-check` using pinned LibreLane 3.0.16 / sky130A / sky130_fd_sc_hd. This is tool output from a real successful full flow, not generated sample data. See `provenance.json` for the exact source directory, image digest, tool/harness/source hashes, and the SHA256/byte count of every copied file.

- `metrics.json`: untouched LibreLane `runs/golden/final/metrics.json` (includes nonstandard JSON `Infinity` tokens from upstream).
- `counter.gds`, `counter.png`: final GDS and real KLayout render.
- `test_results.xml`: all four cocotb tests passed.
- `reports/`: actual Magic/KLayout DRC, Netgen LVS, post-route timing and power output.
- `logs/`: full lint, simulation, synthesis, flow and tool-version logs, including warnings.

Discovered metric names for M2: `design__instance__area` includes filler, `design__instance__area__stdcell` is standard-cell area, `design__core__area` and `design__die__area` describe physical regions, `timing__setup__wns` is clamped worst negative slack, and `timing__setup__ws` is worst slack. DRC/LVS/XOR zero counts are explicit in the metrics. Power reports explicitly label watts; conversion and corner selection must be documented by the parser.

These fixtures establish format and toolchain behavior. They are not an agent event recording or a Tiny Tapeout submission bundle. Do not expose them as a live model result.
