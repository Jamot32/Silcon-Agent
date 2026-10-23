This is a **supplied, intentionally faulty UART starter**, not a model-generated design or failure. It exists to demonstrate a real independent-test failure followed by a model-authored RTL repair.

The source is the hand-written golden UART with one deliberate change: its divider terminal-count expression subtracts two instead of one. At the required default `BAUD_DIV=4`, each serial bit lasts three clock periods rather than four. `provenance.json` records the exact change and source hashes.

The required interface is top `uart_tx` with inputs `clk`, `rst_n`, `send`, `data[7:0]` and outputs `busy`, `tx`. Required behavior is 8N1, LSB first, synchronous active-low reset, idle high, input data latched on an accepted send, and no queued requests while busy. The complete stop bit must finish before `busy` clears.

The orchestrator loads this source once, records its supplied-faulty provenance visibly, lints it, and lets VERIFY author tests from the required contract without seeing RTL internals. Any repair is made by the normal model-driven RTL stage and must pass the same tests. The required contract is available as `load_starter("uart_off_by_one").spec_text`.

No measurements, test outcomes, or layout claims are implied by this starter file. Full real simulator evidence is retained separately under `runs/`.
