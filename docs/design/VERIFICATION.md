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
