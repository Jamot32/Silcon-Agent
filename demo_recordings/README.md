# Authentic recordings

These packs contain actual completed runs, exported through the public API with `scripts/export_recording.py`. No fixture/test double is presented as a live model run. Replay makes no model or EDA requests.

| Pack | Original run | Actual evidence |
| --- | --- | --- |
| `uart-repair` | `f17167a0d7984e89b87a5774285f0037` | Explicitly supplied faulty UART, not a model-generated first attempt; independent unchanged tests: 1 pass / 5 fail → model RTL repair → 6 pass / 0 fail; four clean physical runs. |
| `uart-optimization` | `caf95489e137445a963de920048a3961` | From-scratch model UART passed its first test cycle; four clean physical results, including three parallel configuration variants. The original smallest-area design was retained. |
| `counter-improvement` | `fe6f7664848840b596784df0f499cc10` | Six passing tests; verified RTL optimization reduces standard-cell area from 1097.30 to 980.941 µm² at the same 50 MHz target, with clean DRC/LVS. |

Each `recording.json` contains the original public run, exact ordered event history, metric rows, full file writes, final files, layout paths, and selected bundle path. `manifest.json` uses SHA256 for every asset, including the recording and bounded real raw reports/XML/logs under `provenance/`. Original LibreLane files retain their bytes, including optional nonfinite fields in raw metrics. The canonical displayed measurements are finite and fixture-tested.

The loader checks hashes, source/event/metric agreement, contained paths, asset sizes, PNG signatures, and the selected ZIP/spec/metric identity. Playback creates a new `is_replay=true` run, copies the original artifacts, and emits original events at 1× or 4× speed. New event IDs/timestamps belong to playback; `source_event_id` and `source_event_ts` retain the real original identity/time. Cost and token totals are explicitly labeled recorded usage. Failed original tests remain failures until their original passing event arrives.

The supplied faulty starter's origin and hash are in `designs/starters/uart_off_by_one/`. It exists to demonstrate a real independent-test/repair cycle transparently. Normal from-scratch builds never receive this starter.
