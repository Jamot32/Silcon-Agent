# Independent evaluation references

The model under evaluation does not author its own oracle. The build cases use
unchanged external RTL or Python reference code at the commits below, with original licenses preserved
inside each case. `expect.yaml` records upstream paths and SHA-256 values;
`golden/oracle.json` maps each local source to that exact upstream path and hash.
The evaluator validates all three before compilation. The cocotb adapters,
port adapters, public wording, decision rubrics, and test selection are authored
for this evaluation; they are not described as upstream human code.

| Source | Commit | License | Basis for selection |
| --- | --- | --- | --- |
| [NVIDIA VerilogEval](https://github.com/NVlabs/verilog-eval/tree/c498220d0a52248f8e3fdffe279075215bde2da6) | `c498220d0a52248f8e3fdffe279075215bde2da6` | MIT; full upstream notice retained | HDLBits references and tests. The [paper's acknowledgment](https://arxiv.org/html/2309.07544v2) credits HDLBits creator Henry Wong for the reference solutions and testbenches. The generated training corpus is not used. |
| [Alex Forencich UART](https://github.com/alexforencich/verilog-uart/tree/1b867e53af738e4a8bc7c839ca2f1c07f40382dc) | `1b867e53af738e4a8bc7c839ca2f1c07f40382dc` | MIT | Established parameterized UART implementation with source attribution and upstream tests. |
| [Alex Forencich AXIS](https://github.com/alexforencich/verilog-axis/tree/48ff7a7e2ef782cf778d47910cf85835c64b1bce) | `48ff7a7e2ef782cf778d47910cf85835c64b1bce` | MIT | Streaming FIFO with explicit handshake and pipeline configuration. |
| [Alex Forencich I2C](https://github.com/alexforencich/verilog-i2c/tree/a65be4045e898a52e791c6ee71f8f79a7cd2e129) | `a65be4045e898a52e791c6ee71f8f79a7cd2e129` | MIT | Stateful bus controller with open-drain, clock stretching and command/data interfaces. |
| [Alex Forencich LFSR/CRC](https://github.com/alexforencich/verilog-lfsr/tree/c1f86d036745935f3812ec6ddc7821c70ef4c9de) | `c1f86d036745935f3812ec6ddc7821c70ef4c9de` | MIT | Parameterized polynomial and bit-order definitions, plus upstream CRC tests. |
| [Project F](https://github.com/projf/projf-explore/tree/dd212c2e5e0e0d8bdcf93ba077630dbfd49ae708) | `dd212c2e5e0e0d8bdcf93ba077630dbfd49ae708` | MIT | Attributed unsigned integer division and raster timing modules. Signed arithmetic sources with incorrect zero/rounded-overflow behavior were removed from active references before the baseline. |
| [Nandland SPI master](https://github.com/nandland/spi-master/tree/1ab581969f8ea2f794072a144b55cd74e5a54f34) | `1ab581969f8ea2f794072a144b55cd74e5a54f34` | MIT | Attributed SPI controller with documented CPOL/CPHA and divider behavior. |
| [CPython exact rational arithmetic](https://github.com/python/cpython/blob/8183fa5e3f78ca6ab862de7fb8b14f3d929421e0/Lib/fractions.py) | `8183fa5e3f78ca6ab862de7fb8b14f3d929421e0` (`v3.13.9`) | PSF and historical Python licenses, full `LICENSE` retained | Human-authored `Fraction` and nearest-even `round` provide an independent full-range signed fixed-point mathematical reference. [Python documentation](https://docs.python.org/3.13/library/fractions.html) defines exact rational construction and rounding. |

The legacy Forencich repositories are pinned deliberately; their READMEs point
to successors, but changing implementation or license mid-baseline would make
the result less reproducible.

## Corpus scope and limitations

There are 30 development and 30 isolated held-out cases, each split into tiers
8/10/6/6. Forty-eight cases build hardware; twelve evaluate an explicit visible
scope decision. Tier 3 covers five families: I2C, CRC, raster timing, iterative
division, and staged rounded arithmetic. Two cases per split are division
variants. CPU and matrix multiplication are not covered. Tier 1 emphasizes
counters, edge detection and shift/data registers; debouncers and seven-segment
decoders are not covered. Tier 2 covers serial/streaming peripherals, LFSRs and
state machines; it does not exhaust the user-suggested family list.

Eight of sixteen elementary cases omit the exact top/interface table and
clock/reset names. These cases use permitted aliases or a unique
direction/width match, rejecting ambiguous mappings. Five omit an explicit
output bit count and permit wider zero-extended numerical outputs. Four omit
a frequency target; other build targets include 25 and 50 MHz. Eight omit reset
synchrony/polarity and rely on the product's documented defaults, and one omits
reset behavior entirely. The remaining protocol and arithmetic cases specify
canonical interfaces to make their hidden checks meaningful. Informal phrasing
and a few abbreviations are included, but this is a focused, mostly specified
digital-design corpus, not representative coverage of arbitrary user language.

Eighteen interfaces exceed a single Tiny Tapeout harness pin budget: six in the
development split and twelve in the isolated split. These specifications
explicitly request a standalone digital core and exclude a TT pin-fit claim.
Success is a clean standalone flow and its deliverables, not shuttle submission
compatibility. UART prescalers are fixed inside the reference adapter, and
raster coordinates are internal; configuration-only inputs and debug outputs
are not inflated into external pins. The other wide interfaces are retained
honestly rather than silently changing their behavioral scope.

Several external source families occur in both splits with different tasks or
fixed configurations. This measures transfer between related contracts, not
strict family-disjoint generalization. The references are public and may have
appeared in model training. Held-out isolation prevents evaluation-time leakage;
it cannot establish that a pretrained model has never seen the upstream code.

## Oracle mechanics

Each build oracle runs four deterministic cocotb tests in the disconnected
pinned EDA container. Thirty-four cases compare reference and candidate cycles
where the public contract defines those transitions. Reference X bits are
don't-cares; a candidate X fails wherever the reference bit is defined. Data
validity guards avoid checking unspecified idle data. Numeric wider outputs are
compared against a zero-extended reference, including their upper bits.

Fourteen serial, FIFO and arithmetic cases use transaction assertions instead:
candidate handshakes, SPI edges and complete UART bytes define the observation
points, and documented completion bounds permit different valid latencies.
FIFO capacity permits the requested RAM depth plus up to two pipeline slots.
UART framing-error signaling is checked, then reset is used before subsequent
traffic; recovery without reset after a malformed frame is outside that case's
contract. No particular upstream recovery state machine is required.

Four signed arithmetic cases use the pinned CPython `fractions.py` directly in
the hidden container, with no fallback to another Python reference. This checks
ordinary full-range signed math, zero, minimum signed operands, ties, and overflow
after rounding. Their positive qualification RTL is an explicitly labeled
finite response ROM generated with the host's standard-library `Fraction` and
independently checked against the pinned Python mathematical oracle in Docker,
not a human RTL design or a solution written by the model under test. Literal
unit vectors independently qualify the adapter's flags/sign/range mapping;
the former buggy signed RTL is rejected by the corrected semantic checks.

Admission requires the reference implementation or Python response fixture to pass and a deliberate
all-zero-output implementation to fail, with raw logs/XML and source hashes.
This detects empty/constant-pass oracles; it is not proof that the complete
public specification is covered or that all possible design bugs are caught.
Only module identifiers are mechanically namespaced in temporary RTL compile
views. Original upstream source bytes remain intact. Differential cycle checks
do not establish universal equivalence across unconstrained microarchitectures.
The two I2C cases explicitly request the selected upstream cycle behavior and
are tagged `implementation_compatibility` in their expectations and reports.
They remain in the declared corpus denominator, but are not evidence of
acceptance of arbitrary functionally valid I2C microarchitectures.

The [NVIDIA README](https://github.com/NVlabs/verilog-eval/blob/c498220d0a52248f8e3fdffe279075215bde2da6/README.md)
supports Icarus 12 and excludes development Icarus 13. An actual untouched
counter upstream test fails elaboration on this project's pinned Icarus 13 at
a waveform-only `$dumpvars` forward reference. Removing waveform dump calls
in a temporary compile view produces zero mismatches for that counter. The
app image remains unchanged; the production hidden oracle uses its own cocotb
stimulus, not NVIDIA's unsupported whole harness. This distinction is retained
in qualification evidence rather than treating a harness error as an RTL bug.

## Isolation

Held-out assets are provisioned under `eval/heldout/` with owner-only directory
permissions and are ignored by Git. Evaluation output and the admission index
are private too. Git cannot preserve these permissions: provisioning on another
machine must restore the private corpus and run the CLI's permission check.
The full hash manifest lives inside the private corpus; an outer manifest
contains counts and opaque hashes only. These permissions do not protect
against the trusted host owner running under the same UID.

Only each case's `spec.md` and public timing/area targets are passed into the
app. References, expected behavior metadata, hidden tests and outcomes never
enter the model's work directory, EDA input mount, prompts, memory, or retrieval
index. Post-run verification uses a sibling sandbox containing an immutable
copy of the selected delivered RTL. No hidden result is fed back to the agent.
