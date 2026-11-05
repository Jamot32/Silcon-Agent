# Silicon Agent — 3-minute pitch script

Slides: `docs/pitch-deck.excalidraw` (7 frames). Slide 5 is a cue card; the
demo itself is your screen recording. About 350 scripted words plus your
narration over the demo.

## 1 · Title (0:00–0:10)

> This is Silicon Agent. You describe a small digital chip, and it gives you
> tested Verilog and a clean sky130 layout, in minutes.

## 2 · The Problem (0:10–0:40)

> Here's the problem. Turning an idea into a working chip means writing
> Verilog, writing tests, and running a whole chain of design tools. And
> proving it actually works is the hardest part. In the 2024 Wilson Research
> study, only 14 percent of chip projects worked on first silicon. Everything
> else needed another expensive manufacturing run. And design engineers spend
> half their time, 49 percent, just on verification. Silicon Agent automates
> that checking: real tests, a real layout, and real signoff on every build.

## 3 · Why Meta Muse Spark (0:40–0:55)

> I chose this project because of what Meta built Muse Spark for. Meta
> describes it as trained for long-horizon, agentic workflows: it tracks
> context and prior results, and it calls tools reliably. A chip build is
> exactly that: a long chain of steps, each graded by real tools, so the model
> gets concrete feedback and keeps working on its own.

## 4 · How it works (0:55–1:15)

> You write a spec. Muse Spark writes the Verilog. Real tools run the tests,
> synthesis and the full layout. If anything fails, the real tool report goes
> back to the model, and it fixes and retries. The AI proposes; open-source
> EDA tools measure.

## 5 · Live demo (1:15–2:15) — switch to your screen recording

> Here's an 8-bit up/down counter at 50 megahertz. *(Narrate what's on
> screen: the spec, the Verilog appearing, tests passing, the layout, the
> optimized second layout, the download.)*

Facts you can say during the counter recording (`demo_recordings/counter-improvement`):
lint-clean at 0:30, 6/6 tests at 1:06, first DRC/LVS-clean layout at 1:58,
AI rewrite re-tested at 2:19, done at 3:29. Area 1097.30 → 980.94 µm²
(−10.6 %), power −8.6 %, timing met at 50 MHz. If you play the recording,
the UI shows REPLAY; keep it visible.

## 6 · Why it works (2:15–2:45)

> This isn't a lucky demo. On 90 trials of designs it had never seen, graded
> by hidden tests it never sees, 81 succeeded, and every delivered design was
> correct, 66 out of 66. Larger designs too: 21 of 21 correct, up to almost
> 12,000 cells. Median time from spec to signed-off layout: under five
> minutes. These numbers were measured on our temporary Codex route; the
> Muse Spark run is next.

## 7 · Close (2:45–3:00)

> Silicon Agent: spec to verified silicon layout in minutes, with real tools
> and real numbers. Next, a tapeout-ready Tiny Tapeout wrapper. Thanks for
> watching.

## Sources

- 14 %, 49 %: [2024 Wilson Research Group IC/ASIC functional verification trend report](https://static.sw.cdn.siemens.com/siemens-disw-assets/public/1NyfMZJ3nuPhMGQCGFDITG/en-US/ic-asic-functional-verification-trend-report-wp-86424-d3.pdf) (Siemens EDA, n=597).
- Muse Spark quotes: [dev.meta.ai/models/muse-spark](https://dev.meta.ai/models/muse-spark).
- 81/90, 66/66, 21/21, 4.73 min, 11,932 cells: `docs/RELIABILITY_REPORT.md` (held-out set G2 and complexity stress probe).

## Disclosure (keep)

- The recordings and reliability numbers used the temporary Codex /
  ChatGPT-plan provider. The Meta adapter (`LLM_PROVIDER=meta`,
  `muse-spark-1.3`) is built in, but no live Muse Spark run has been measured
  yet. If you record a live Meta build for the demo, say so and drop the
  Codex line on slide 6.
- The earlier held-out set G1 scored 62/90; it's on slide 6's footnote.
- The bundle is a metadata draft; `tapeout_ready` is false.
