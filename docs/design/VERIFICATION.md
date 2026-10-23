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

Aside's browser does not expose `setViewportSize` (TypeError). Initial current-window screenshot is 2880×1800 device pixels; native concept-size and mobile checks will use a supported browser fallback. Temporary QA screenshots stay outside committed source.
