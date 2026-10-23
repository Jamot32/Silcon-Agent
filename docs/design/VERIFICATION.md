# M0 design verification

Reference: `m0-concept.png`, generated through built-in Image Gen for this scaffold only. Inspected via `view_image`. Aside Browser verified the actual API-backed page, selected UART TX and observed the specification change, then followed Run history and confirmed the empty state. The browser screenshot was also inspected via `view_image`.

| Comparison | Evidence / disposition |
| --- | --- |
| Copy and hierarchy | H1, explanatory sentence, form labels, five presets, disabled CTA, and recordings empty state match. No added claims or metrics. |
| Composition | Quiet header; form and narrower toolchain column; full-width recorded-runs region. |
| Typography | Large sans-serif title; deliberate control sizes; monospace health labels. |
| Palette | Near-black flat background, dark surfaces, muted rules, cyan navigation and controls. No generated layout/illustration. |
| Controls | Native editable textarea, numeric clock, tile checkbox; preset selection updates text; disabled build explains milestone gate. |
| Real state | API and Database change from concept Checking to Ready based on actual health; EDA/Model remain unverified/unconfigured. Intentional dynamic deviation. |

Aside's browser does not expose `setViewportSize` (TypeError). Initial current-window screenshot is 2880×1800 device pixels. Playwright using installed Chrome therefore captured 1505×1045 (the concept size) and a 390px mobile viewport; both were inspected via `view_image`. No clipping or horizontal overflow is visible. Empty-state heading weight was corrected to match the reference. Temporary QA screenshots remain gitignored and are removed after inspection.

The above-the-fold copy matches the reference, except for real health status and the intentional milestone-gate message updated after the EDA check passes. The implementation was verified against the reference for the five comparison areas above; no material visual mismatches remain.

User-authorized M3 provider steering changes the Model row to the actual selected provider (Codex or Meta). The status comes from cached real smoke verification, not a hardcoded success. This is an intentional functional copy change from the initial M0 concept.

# M7 dashboard verification

Reference: `m7-concept.png` (1672×941), inspected directly with `view_image` before implementation. Aside verified the app first; its browser surface cannot set the requested viewport, and the built-in IAB surface was unavailable. Playwright/Chrome captured the native reference size, 1920×1080, and 390px mobile. Both the reference and the latest rendered captures (`/tmp/silicon-m7-1080-v2.png`, `/tmp/silicon-m7-mobile-v2.png`) were inspected with `view_image`. These are temporary QA captures, not product assets.

| Comparison | Evidence / disposition |
| --- | --- |
| Palette and navigation | Original near-black M0 surfaces, muted rules, Arial chrome, and one teal accent retained. Run history is correctly active for a run URL. |
| Header and timeline | Run/top name, actual provider and nullable cost, nine stages, and result/download controls follow the reference. Real elapsed time, tokens, and connection state are intentional functional additions. |
| Three-column composition | Scrollable event log, central read-only source editor, and verification/metrics inspector retain the reference hierarchy. Panels compact to 470px so the real layout is fully visible within a 1080px viewport. |
| Source and changes | Actual RTL/test file tabs mount Monaco; latest recorded edits have an inline diff mode. No source text is baked into the page. Read-only E2E checks both file tabs and the mounted editor. |
| Verification and chart | Real test totals/case statuses and API metric rows drive the inspector. The completed M6 recording has aggregate totals only and says so explicitly. The two real area/WNS points and selected best run agree with the API. |
| Layout and controls | The reference placeholder is replaced with the actual 1000px GDS render. Zoom, fit, and pointer panning operate on that image. The canvas is deliberately taller than the concept; the full chip ends around 1008px in the 1080p capture. |
| Mobile continuation | File tabs and timeline scroll horizontally; source, inspector, log, and layout stack without page overflow. The chart now draws its actual axes and series after fixing an indefinite flex height. |
| Copy and contrast | Actual module/file names, event text, metrics, statuses, and counts supersede concept examples. Unknown ChatGPT-plan USD cost remains unavailable. Cyan action links now use dark text; a global anchor rule had overridden the initial foreground. |

Above-the-fold copy differs only for actual recorded state, correct navigation selection, and the functional additions above. The duplicate summary below the layout was removed; the real summary remains in the design log. No generated chip imagery or synthetic chart points are used. The implementation has been faithfully compared against the accepted composition across the areas above; no material visual mismatch remains. Read-only rendered checks pass for presets, actual RTL/test editor tabs, API-matched metric count, and a decoded real layout image with no browser page errors. Full live SSE acceptance is recorded separately in the milestone progress evidence.

Dependencies were checked against current official documentation and npm metadata, then pinned: Monaco `0.57.0`, [`@monaco-editor/react` `4.7.0`](https://github.com/suren-atoyan/monaco-react#loader-config), [Recharts `3.10.1`](https://recharts.github.io/en-US/api/LineChart/), and [shadcn CLI/source primitives `4.22.1`](https://ui.shadcn.com/docs/installation/next) using the `radix-nova` style. The [documented esbuild resolve hook](https://esbuild.github.io/plugins/#resolve-results) bundles the editor and worker locally and substitutes pinned DOMPurify `3.4.17` for Monaco's vendored older sanitizer. Generated bundles include license notices and need no CDN. `npm audit` reports zero vulnerabilities after that substitution. Playwright `1.64.1` is pinned for browser checks.

# M9 result-page verification

Reference: `m9-concept.png` (1672×941), inspected with `view_image` before coding. The latest native and mobile renders (`/tmp/silicon-m9-native-v2.png`, `/tmp/silicon-m9-mobile-v2.png`) were also inspected directly with `view_image` alongside the reference. Aside verified the real selected layout, target/signoff text, and zoom/fit controls; Playwright supplied exact native-size and 390px viewport captures because Aside does not expose viewport sizing. These captures remain temporary QA artifacts.

| Comparison | Evidence / disposition |
| --- | --- |
| Composition | The selected-layout panel retains roughly 63% of the primary row, with targets and signoff on the right and a full-width design log below. The existing dark instrument tokens and native controls are preserved. |
| Sizing and Fit | The desktop layout panel has a definite 580px height, matching the concept's intended proportions. This corrected an initial intrinsic-image expansion to 1000px. The full selected chip is visible at Fit. |
| Selected artifact | Actual UART run `caf95489…` selects `flow_41725ad89a984a1f`, while its latest flow is different. The result image URL and measurement row use the selected tag, not the latest layout event. |
| Targets | Explicit run targets merge over the structured design targets. The real WNS value is `0 ns`, correcting the concept's text-generation typo. Clock is Met only with known nonnegative WNS at or above the requested configured frequency. Absent max area is No target; Tiny Tapeout integration remains Unverified. |
| Signoff and package | DRC/LVS badges use the selected metric's actual tri-state values. Clean block signoff is distinguished from Tiny Tapeout integration. The done run's real ZIP link passed content type, filename, and ZIP-magic checks; failed/active results have no download button. |
| Design log | Reused event-log components display actual source timestamps and messages. The concept's sample summaries are not copied. Initial event history follows the latest entries; user interaction can pause following, and Latest events uses immediate scrolling. |
| Typography, color, and controls | Header hierarchy, subdued metadata, teal download action with dark text, thin panel rules, and read-only measurement tables follow the reference. Zoom changed the real image scale to 1.25; Fit returned it to 1. |
| Mobile and failure state | Layout, measurements/signoff, and log stack without horizontal page overflow at 390px. The selected tag and clock wrap rather than truncate. A real failed run preserved its error and Unknown measurements, with no fabricated layout or bundle. |

Above-the-fold copy follows the reference except for actual API values/status, correct navigation selection, the full actual run tag, and the functional corrections above. The layout placeholder becomes the real GDS image; no generated image, metric, timestamp, or log summary is used as product evidence. All new code reuses the pinned M7 component/dependency system. Typecheck and production build pass, and the read-only browser suite passes three checks, including the result's selected PNG and real ZIP. No model or EDA job was created for this verification. The latest desktop/mobile pair faithfully implements the accepted composition; no material visual mismatch remains.

# M10 record/replay verification

Replay is a small functional extension of the accepted M0/M7/M9 design system; no new visual concept was needed. Root verified the first real replay in Aside and compared the completed dashboard with the M7 reference. Independent, read-only Playwright contexts captured 1920×1080 and 390×844 dashboard views, plus native 1672×941 and mobile catalog/result/history views. All screenshots below were inspected with `view_image`; these are temporary QA evidence, not product assets. No model, EDA, or replay job was created by these visual checks, and their API mutations were blocked.

| Comparison | Evidence / disposition |
| --- | --- |
| Existing composition | Navigation, dark surfaces, teal controls, three-column dashboard, selected-layout result, and actual metric tables retain the accepted hierarchy. The completed replay's real chip remains visible within the 1080px dashboard capture. |
| Recorded-run catalog | Three actual authenticated recording packs appear with their API names, descriptions, original duration, physical-run count, and source ID. Clearly named Replay 1× and Replay 4× controls have pending/error handling. No simulated recording cards or live supplied-starter action were added. |
| Replay provenance | Dashboard, result, and history display REPLAY 4× for the actual repair playback `534d0b18…`, plus the actual source `f17167a0…`. Playback elapsed, recorded provider/cost, and historical token/call labels prevent confusion with a live run or fresh charges. Unknown ChatGPT-plan USD cost remains unavailable. |
| Supplied starter | The real repair and its recording visibly identify a Supplied faulty starter and explain that the first UART RTL was supplied with a known timing bug. Catalog copy distinguishes the real fail-then-fix demonstration from the from-scratch UART that passed its first test cycle. |
| Actual evidence | File edits, tests, chart points, event times, and images come from recorded real events and artifacts. The result still renders the selected best tag, rather than the latest flow, with its measured 1291.24 µm² area, actual signoff, and genuine bundle link. No runtime metric or test case was invented. |
| Contextual wording | Replay empty states, the recorded design log, Back to replay, and Stop replay describe playback accurately. Source IDs derive from catalog metadata and remain explicitly unavailable if that lookup fails. |
| Mobile continuation | At 390×844, catalog actions remain usable, header badges/source/usage wrap, result panels stack, and long metric tables scroll locally. Home, replay dashboard, result, and history have no horizontal page overflow or browser errors. |
| Editor lifecycle | A real live repair exposed Monaco's model-disposal ordering error when switching diff/file views. A read-only reproduction failed before the fix. The native diff view now detaches its model, disposes the widget, then disposes its owned models; it does not suppress errors or retain orphan models. Repeated actual file/diff transitions and the committed regression now pass with zero page errors. |

Inspected evidence: `/tmp/silicon-m10-replay-desktop.png`, `/tmp/silicon-m10-replay-mobile.png`, `/tmp/silicon-m10-recordings.png`, `/tmp/silicon-m10-result.png`, `/tmp/silicon-m10-history.png`, `/tmp/silicon-m10-home-mobile.png`, `/tmp/silicon-m10-result-mobile.png`, and `/tmp/silicon-m10-history-mobile.png`. Root independently accepted the dashboard desktop/mobile pair against the M7 concept. No material visual mismatch remains.

The pinned M7 dependencies are unchanged. Typecheck, production build, and 15 frontend unit checks pass. The read-only browser suite passes five checks, including the Monaco regression. Root's final `make test` passes 318 backend tests, 15 frontend unit tests, and the offline replay E2E in 54.7 seconds, with actual chart/image/bundle evidence and editor transitions. Replay submission and live recording acceptance are recorded separately in the milestone progress evidence.


## M10 replay extension and lifecycle regression

Root compared `m7-concept.png` with the native completed UART repair replay at 1920px and 390px in the same image-viewing pass. Screens were `/tmp/silicon-m10-replay-desktop.png` and `/tmp/silicon-m10-replay-mobile.png`; passive home/result/history captures use the same existing instrument design. This is a functional extension of the accepted M7/M9 surfaces.

| Area | Verified result |
| --- | --- |
| Composition | Desktop retains log/code/evidence columns, stage timeline and full-width actual layout. Mobile stacks code/evidence/log/layout and scrolls bounded comparison tables. |
| Typography and color | Existing restrained dark panels, legible code, teal active/action accents and pass/fail colors remain consistent. |
| Evidence | Four real measurements, six named passing tests and the original rendered PNG are visible; no generated layout is used. |
| Replay origin | REPLAY 4×, source run ID, playback elapsed, recorded provider/cost/tokens and supplied faulty starter disclosure appear together. Result/history retain their replay origin. |
| Interaction | Actual SSE playback advances without refresh; zoom/Fit, source/test tabs, Changes and ZIP work. A native diff-model cleanup fixed the real disposed-model error; repeated switches now produce zero page errors. |
| Verification | Main offline replay E2E passed (54.7s); clean-data/no-key/no-PDK instance passed (55.2s). Read-only regression checks passed 5/5. Real failure/repair provenance remains separately documented. |

No material composition or functional mismatch remains. New replay rows use real recording names, durations and flow counts; replay actions are separate from live Build my chip.
