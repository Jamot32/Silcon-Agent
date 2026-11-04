# Three-minute demo

Run `make demo` beforehand. Keep the browser at 1920×1080 and open the home page,
the completed counter result, and the completed UART result in separate tabs.
Find recordings under **Recorded runs** in the sidebar. The backup below uses
authentic committed recordings and remains visibly labeled REPLAY. Clicking a
recording does **not** build the text currently in the input.

| Time | Action and narration |
| --- | --- |
| 0:00–0:15 | “Making a chip usually means learning several tools before you can test one idea. Silicon Agent gives students and small teams a guided path from a digital specification to a real layout.” |
| 0:15–0:30 | In **New design**, type a UART transmitter specification and show its editable text and clock target. Explain that **Build my chip** starts a new model/tool run, while the separately labeled replay buttons play saved evidence. A full live UART run takes longer than this three-minute presentation; start it before the presentation if using the live path. |
| 0:30–1:15 | Open **Recorded runs** and click **Replay 4×** for **UART TX: supplied-starter repair**. Point out REPLAY and the supplied faulty starter disclosure. “For this repair demonstration, we supplied a UART with a known baud-counter bug. The model wrote independent tests from the specification, saw one pass and five failures, recorded a hypothesis, and repaired RTL. The same tests then passed six out of six.” Show the test results and source Changes view as those events arrive. The faulty first version was hand-written, not attributed to the model. |
| 1:15–2:00 | Follow the four actual physical measurements. “Three configuration variants ran in parallel. These are tradeoffs: one larger layout has lower reported power, while the original wins our timing-then-area ranking.” Zero slack indicates timing met at the configured 50 MHz target; it is not a measured maximum clock frequency. For an area-improvement example, show the completed counter tab: 1097.30→980.941 µm² at 50 MHz. Do not describe every UART iteration as an improvement. |
| 2:00–2:30 | Open the replay result. Zoom the rendered GDS, point to the selected run tag, block-level DRC/LVS checks, and download the ZIP. Show GDS, LEF, selected RTL/tests, metrics, checksums, and `info.yaml`. “The Tiny Tapeout metadata is a draft. Wrapper integration and tile fit have not been verified.” |
| 2:30–3:00 | “This is for first-time digital chip makers using open tools and shared runs. The next step is validating the Tiny Tapeout wrapper and shuttle integration.” Explain the current temporary ChatGPT-plan/Codex provider, the selectable Meta adapter, and that the live Muse Spark acceptance remains pending competition credentials. Recorded token usage is labeled; plan dollar cost is unknown. |

At 4×, the UART repair recording takes about 56 seconds, so its test repair and
four flow measurements finish during the two middle sections. Playback preserves
original event order and durations divided by four; network/UI overhead may add
a few seconds. The log and Changes view remain available after DONE.

## Live presentation path

With the host Codex login and EDA setup verified, open **New design**, type the UART
specification, and click **Build my chip**. Observe SPEC, source writes, tests,
synthesis, the real flow and optimization comparisons. This from-scratch design may pass its first
test cycle, as the recorded M8 run did. Never promise a spontaneous model mistake.
For a live reproducible repair demonstration, run `make record-repair`: this starts
a **real** model/tool job using the explicitly disclosed supplied faulty UART.
Do not run it while another build or replay is active. Allow several minutes and
keep the labeled recording available if model quotas or tools fail.

## Evidence and recovery

- `demo_recordings/README.md` identifies each real source run and its provenance.
- `docs/evidence/M10.json` records the actual UART failure/repair, preserved tests,
  parallel flow overlap, real artifact hashes and selected bundle checks.
- An API/model/tool failure stays visible as a failure. Use a separate labeled
  replay if needed; never replace the failed live run's metrics or status.
- Use `make test` with the app idle for an offline browser check. It starts only
  a replay and needs no model credentials or PDK.
