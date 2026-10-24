# Read-only sa_tb research — 2026-10-23

Repository source stayed frozen. No EDA, simulation, LLM, dependency, build, graphify, retrieval-index, or evaluation commands were run. No heldout files, heldout results, or golden source/results were opened. The explicitly permitted publicdev baseline diagnosis was read. This is a proposal, not a validated implementation or measured improvement.

## Recommendation

After the active experiment finishes, add one small trusted `eda/sa_tb.py` module to a **new** EDA image revision. It should own primitive clock/reset scheduling and strict comparison only. First migrate only clock/reset/check mechanics while expectations and stimuli remain authored from the public spec; measure that change independently. A later MODEL stage uses the required `Model.reset()` and `Model.step(inputs) -> outputs` contract. Keep those reference models and deterministic stimuli in each generated test file; do not embed design-specific reference implementations or dispatch by preset/corpus identity.

Scope the first API to a single synchronous positive-edge clock. Default active-low reset follows the existing product prompt; an explicit active reset level can be supported. Do not imply that this API verifies asynchronous reset, multiple clock domains, or arbitrary external timing.

## Verified current constraints

- `CLAUDE.md` requires current official API documentation, pinned EDA tools, honest real measurements, small changes, and isolated generated code.
- `backend/app/agent/tools.py` accepts only flat `src/*.v`, `test/*.py`, and allowlisted `config.json`. Generated tests may import `cocotb`, its public submodules, `random`, and `math`; relative and wildcard/private imports are rejected. `getattr` is forbidden, so the API must take direct handles such as `dut.ready`, not names that generated code must resolve dynamically. Generated code cannot import `dataclasses`, `typing`, `collections`, or another generated model module. A local Python class/dict/list model needs no new imports.
- `backend/app/eda/service.py` copies flat RTL/tests into an immutable per-call input snapshot. `eda/runtime.py` uses `get_runner("icarus")`, `sources=...`, `timescale=("1ns", "1ps")`, `/output/build`, and absolute `/output/test_results.xml`. It runs the generated module from `/input/test`.
- `eda/Dockerfile` installs exact `cocotb==2.0.1` and `find_libpython==0.5.1` under `/opt/silicon-python`, already exported through `PYTHONPATH` and `NIX_PYTHONPATH`. It copies only `runtime.py` under `/opt/silicon-agent` today. Base LibreLane 3.0.16 is pinned by digest `sha256:02d50f259d483979e126ef188a50f5b61e1d285b9d538312f280b087439b0302`.
- `backend/app/eda/sandbox.py` and `eda/versions.env` currently select the mutable local tag `silicon-agent-eda:librelane-3.0.16-cocotb-2.0.1-tools1`; `EDA_IMAGE` may override it. This proposal must not rebuild or reuse that tag during the live experiment. The closure pins Icarus indirectly; its exact installed version was not measured in this read-only task.
- The sandbox mounts only the input snapshot read-only and separate output writable, with no network/credentials/socket, read-only root, dropped capabilities, nonroot user, and bounded resources. Preserve that boundary; do not mount the repo, backend package, or host Python installation to expose a helper.
- VERIFY currently filters source files to tests, rejects RTL reads, and retains the original test module. Existing test edits require an explicit spec-contradiction note. Verification proof currently binds RTL hash, test hash, and top, not helper/image revision.

## Official cocotb 2.0.1 findings

An edge trigger resumes before downstream HDL reacts; sampling registered results requires a later settled phase. `ReadOnly` reaches the final read phase and forbids writes; leave it using a positive timer before driving again. `Timer(0)` is invalid, and `NextTimeStep` is unsafe when no future event is scheduled. These support a helper with explicit positive timed phases rather than delta-cycle tricks. [Timing model](https://docs.cocotb.org/en/v2.0.1/timing_model.html#the-time-step).

Use `unit=`, strict `is_resolvable` guards before integer conversion, and explicit expected-value masking. `Logic`/`LogicArray` conversion can fail on unresolved values. Avoid `COCOTB_RESOLVE_X` coercion. In 2.0, `Clock.start()` already starts its own task; wrapping it again in `start_soon` is unnecessary. The runner API is experimental; preserve the exact pinned version. [Library reference](https://docs.cocotb.org/en/v2.0.1/library_reference.html#cocotb.types.LogicArray.is_resolvable), [Clock.start](https://docs.cocotb.org/en/v2.0.1/library_reference.html#cocotb.clock.Clock.start), [runner](https://docs.cocotb.org/en/v2.0.1/runner.html).

The official 2.0.1 runner source sets subprocess `PYTHONPATH` from the parent Python `sys.path`, overwriting an `extra_env` value; it runs the simulator with `cwd=test_dir`. Therefore install the helper into the image's existing import path, and address shadowing explicitly. [Runner source](https://docs.cocotb.org/en/v2.0.1/_modules/cocotb_tools/runner.html#Runner.test).

Official support is Icarus 11.0+. The helper still needs a real timing regression in this project's exact image. [Simulator support](https://docs.cocotb.org/en/v2.0.1/simulator_support.html#icarus-verilog).

## Stage 1 entry contract: avoid reintroducing raw pre-reset reads

Merely teaching the LLM to call `CycleBench` is not enough: a generated direct `@cocotb.test` body can still read DUT outputs before calling reset. Prefer a small trusted adapter/decorator such as `@sa_tb.case` that turns a **scenario factory/generator with no DUT access** into an ordinary cocotb testcase. The generated function takes no DUT or signal-handle arguments and yields complete `{inputs, before, after}` cycle records. Reset input values and expected reset outputs are explicit spec-derived scenario metadata. The adapter receives the DUT, binds the validated `DesignSpec.ports`, performs bootstrap, then executes each record through the helper. Preserve individual case names and four-case gate in real XML.

`DesignSpec` already has validated input/output names/widths, `purely_combinational`, and mandatory scalar `clk`/`rst_n` for sequential designs. Add only the small metadata/adapter connection needed to transfer those validated bindings. Do not infer anything from RTL. In harness mode, require the trusted entry protocol and reject direct cocotb testcase/clock/Timer/signal-driving APIs in the generated module; no broad security claim is implied. The adapter's cocotb registration mechanics need an exact-version integration test.

This first stage needs no reference-model class and no new MODEL orchestration stage: directed vectors and generated Python calculations still provide before/after expectations from the public contract. The later reference-first migration supplies a model with required `reset()` and `step(inputs) -> outputs`, plus optional `outputs(inputs)` for pre-edge combinational observations, to the same adapter. Measure the stages separately.

## Small internal helper API and edge contract

The following shows the trusted adapter's handle binding, not a generated-test body. Future model use has the required `step` method:

```python
from sa_tb import CycleBench

bench = CycleBench(
    clock=dut.clk,
    reset=dut.rst_n,
    reset_active=0,
    inputs={"enable": dut.enable, "data_in": dut.data_in},
    outputs={"ready": dut.ready, "valid": dut.valid, "data_out": dut.data_out},
)
model = Model()                  # Pure spec-derived Python, no DUT argument
model.reset()
await bench.reset(idle_inputs, after=model.outputs(idle_inputs), cycles=2) # Optional outputs() form

for cycle, stimulus in enumerate(stimuli):
    before = model.outputs(stimulus)  # Fresh mapping, state before rising edge
    after = model.step(stimulus)     # Advance once; return post-edge outputs
    await bench.drive_and_check(stimulus, before=before, after=after, label=str(cycle))
```

Proposed semantics:

1. No background clock task: `CycleBench` is the sole clock/input owner. Its constructor stores handles only. A normal cycle before `reset()` fails clearly. No concurrent helper calls or second clock driver.
2. `reset()` first drives clock low, every input to caller-supplied safe values, and reset active. **It reads no output at all before the first real rising reset edge.** At each held-reset rising edge, wait for `ReadOnly` and check the caller's reset expectation. Advance positive simulation time, lower clock, and return in a writable phase with reset still asserted. `cycles` must be at least one; the public spec determines longer requirements.
3. `drive_and_check()` starts with clock low. It deasserts reset and applies all current inputs together away from the rising edge. Check settled `before`, then generate exactly one rising edge, then check `after` at `ReadOnly`. Return after a positive high interval and falling drive, in a writable phase. The first normal `before` check therefore observes reset release **before** any active rising edge, retaining registered-versus-combinational behavior checks.
4. A concrete default schedule is 10 ns per full cycle: at low-phase start drive inputs; at +4 ns await `ReadOnly` and check `before`; at +5 ns drive clock high and await `ReadOnly` for `after`; at +10 ns lower clock and return. Both pre-edge setup segments must be positive and precision-aligned. No write follows `ReadOnly` without a positive timer. No raw output conversion or bus-resolution hook runs during reset bootstrap.
5. For exact-cycle reference models, interpret accepted transfers from the pre-edge expected valid/ready state. Post-edge valid/ready are values for the following cycle. The future pure model must not infer accepted transfers from newly updated outputs or DUT observations. Current adaptive black-box scoreboards may observe public pre-edge handshakes and assert independent protocol/queue properties; see the refinement below.
6. Require exact input and output mapping keys, reject unknown keys and out-of-width input/expected values. Expected mappings cover every registered output. Support an explicit `None` for a spec-unspecified output; omission is an error. Copy expectations so model state mutation cannot alter them later.
7. Compare concrete expectations as exact integers after strict `.is_resolvable` checks. `None` skips equality, not every check: all declared control outputs must still resolve. Snapshot collection occurs only after bootstrap and may preserve a masked payload as a raw X/Z string without integer conversion. Never replace X/Z with zero. An unknown cared-for value fails with a concise diagnostic, e.g. `SA_TB cycle=3 phase=after signal=valid expected=1 got=X`. See the refinement below for adaptive payload capture.
8. Payload masking is derived from **model expected valid**, never observed DUT valid. Expected valid=1 normally requires payload checking even when ready=0; masking only at handshake would hide backpressure errors. Use `None` only where the written public contract leaves the value unspecified. Check valid/ready and explicit idle/reset levels regardless of payload validity.

This helper does not make generated expectations trustworthy by itself. Existing spec-only VERIFY context and frozen tests remain necessary. The helper should have no DUT-derived oracle, RTL parser, design template dispatch, environment/file loader, or embedded reference designs.

## Stimuli and external pin environments

Keep directed boundary/reset/stall cases and a bounded explicit `random.Random(seed)` sequence in the generated module. Use fixed local seeds and log the seed/cycle on failure; avoid global random state and test-order dependence. Set the trusted runner's `seed` explicitly as well if future tests use cocotb's random facilities; record it in provenance.

A pin environment is distinct from the oracle. For example, open-drain resolution may need observed pin-release outputs after the first reset edge, but must never execute before bootstrap. Do not add an unbounded callback framework to the initial cycle helper. If a public spec needs combinational pin feedback, add a small separately reviewed generic open-drain environment only when its real integration test establishes settle behavior; its observations must not manufacture expected functional results from the DUT. Observed public handshakes can drive a black-box protocol scoreboard and subsequent external stimulus, as detailed below. Safe reset pullups alone must not be mistaken for a full bus model.

## Minimal integration after experiment freeze ends

1. Add `eda/sa_tb.py`; `COPY` it to `/opt/silicon-python/sa_tb.py` in a new image revision. Keep the current runner build/test arguments and mounts.
2. Permit only exact public `sa_tb` imports in `_validate_test` (optionally only `CycleBench` and a public API version constant); do not allow arbitrary `sa_tb.*` imports or expand stdlib access. Keep direct handles in generated code.
3. Reserve `test/sa_tb.py` at write and snapshot/runtime validation, so an uploaded/existing file cannot shadow the trusted module. Check `test_module` cannot select it. Confirm the child imports the image copy in an integration test. Installing a library on PYTHONPATH alone is insufficient origin assurance because the child starts in the test directory.
4. Add the small restricted-case entry API/example and edge/masking rules to the prompt; enforce the trusted adapter route rather than relying on prompt-only discipline. Preserve the independent model/test-before-RTL-inspection boundary and four-real-test gate. No scenario IDs, presets, or benchmark-derived reference hints.
5. Emit helper API version/content hash, actual image identity, cocotb/Icarus versions, seed, RTL/test hashes and top alongside simulation provenance. New helper revisions must invalidate old verification proof (or the image/helper fingerprint must be fixed for the entire runner lifetime). Do not relabel old experiment evidence.
6. Independently fix the existing diagnostic truncation path: compare messages must retain phase, cycle, port, expected/actual and test name as bounded structured fields before log tails. Preserve XML/log artifact paths through stage summaries. A helper cannot repair evidence that is subsequently discarded.

The security boundary remains Docker; Python AST checks and the trusted helper are usability/reliability measures, not proof that arbitrary generated Python cannot tamper with its own checker.

## Necessary meaningful validation (future; not run here)

- One real Icarus integration fixture with synchronous-reset, initially uninitialized registers, nonblocking sequential updates and a downstream combinational chain: reset succeeds without any pre-edge output read; pre/post assertions observe the correct cycle; back-to-back calls never write in ReadOnly. Include reset while busy and repeated reset.
- Mutations of that fixture must fail: omitted reset assignment, one-cycle latency error, and combinational ready on reset release when the fixture contract requires registered ready. A passing helper smoke alone is insufficient.
- Invalid payload fixture: data remains X while model valid=0 and is explicitly masked; the same X when valid=1 fails. Unknown valid always fails. Valid=1/ready=0 still checks data and hold behavior. A pure test double can additionally prove masked payloads are never coerced to integers, while required-known controls are still checked.
- Validator/runtime integration requires the trusted restricted-case entry route (direct cocotb entry/clock/Timer APIs are rejected), accepts the documented generated import, rejects relative/private/wildcard/submodule imports, rejects generated `sa_tb.py`, and confirms the trusted module origin and read-only image mount. Existing escape and immutable-input checks continue to pass.
- A spec-only generated model with local seeded stimuli produces the same input sequence and failure cycle across repeated exact-image runs. RTL/test/helper/image changes invalidate the corresponding proof; normal four-case gating remains unchanged.

No tests or measurements above have been executed in this task.

## Follow-up: preserve exact EDA image identity with one read-only file mount

This recommendation **supersedes baking the helper into a new image** for the planned before/after comparison. The comparator requires exact EDA image identity. Changing the image would add a toolchain qualification difference; a separately versioned trusted-library input preserves the existing image and binaries while making the intended harness change explicit.

Smallest controlled path:

```text
--mount type=bind,source=<absolute frozen trusted sa_tb.py>,target=/opt/silicon-python/sa_tb.py,readonly
```

`DockerSandbox.run` should add this fixed-target file mount only for simulation. The source is backend-owned, e.g. `backend/app/eda/sa_tb.py` from the frozen runtime, never selected by generated/model arguments. Validate that the source is an existing readable regular file, reject symlinks, and bind only that file. Prefer `--mount` to `-v`: a missing source should fail closed rather than be auto-created as a host directory. This does not expose the backend directory or repository to generated code.

Docker documents bind mounts of files/directories, absolute target paths, read-only options, and using mounted paths with a read-only container root. [Bind mount options](https://docs.docker.com/engine/storage/bind-mounts/#options-for---mount), [read-only root and mounts](https://docs.docker.com/reference/cli/docker/container/run/#mount-volume-read-only---read-only).

The docs do not explicitly spell out the complete case “missing file target inside read-only root.” Current first-party runc source supplies that missing detail: `createOpenMountpoint` creates an empty target file for an absent file-bind destination; `prepareRootfs` installs mounts, and `finalizeRootfs` applies read-only root afterward. Therefore an absent `/opt/silicon-python/sa_tb.py` under the existing parent is supported by the Linux runtime design. This is source verification, not a run on the installed Docker Desktop/runc version. [Official runc rootfs implementation](https://github.com/opencontainers/runc/blob/main/libcontainer/rootfs_linux.go).

No PYTHONPATH or NIX_PYTHONPATH adjustment is needed: the unchanged image already places `/opt/silicon-python` on both. The parent runtime imports cocotb successfully from that directory, and cocotb runner copies that parent `sys.path` to the child. A new file there is the least disruptive choice and does not touch the Nix wrapper environment. Reserve `test/sa_tb.py` and check child import origin as previously described.

Read-only applies against the container, not against host edits. For the frozen experiment, keep the trusted source fixed across the whole cohort. For general use, bind a backend-owned content-addressed helper snapshot (outside model-writable source/test directories), or otherwise enforce unchanged helper bytes for the runner lifetime. Record host SHA256, child-loaded SHA256/origin, helper API version, exact image ID, RTL/test hashes, and seed. Compare expected and loaded helper hashes; a mismatch must fail the run. Include the helper hash in verification proof so it cannot change between passing tests and flow. A small separate provenance artifact or bounded structured field can carry the child observation without altering the pinned image's simulator runtime file.

Future qualification, after the active cohort completes: one import-origin check; attempts to modify the helper fail; initially missing target works with `--read-only`; legacy cocotb import and simulation continue through the unchanged Nix wrappers; child helper hash matches recorded host content. Do not drop `--read-only`, mount a whole package directory, or silently fall back to a different helper path if qualification fails. No Docker, EDA, build, or simulation command was run for this follow-up.

## Generality refinement: adaptive black-box cases without DUT access

This refines the initial factory/generator contract. Open-loop vectors alone can force an exact latency/capacity that the public spec never required. They can also prevent legitimate ready/valid or serial-bus stimulus adaptation. The harness-only change must preserve every latency/capacity/handshake behavior permitted by the user; do not introduce canonical cycle choices before a separately reviewed SPEC/model migration.

Use a synchronous generator send protocol:

```python
observed = yield Cycle(inputs=stimulus, before=expected_before, after=expected_after)
pre = observed["before"]
post = observed["after"]
```

The trusted adapter starts the case, performs primitive reset before any snapshot exists, executes each yielded `Cycle`, and sends the resulting snapshot back through `generator.send(observed)`. The generated function receives no DUT, signal handles, simulator trigger, clock object, or callback with hidden DUT access. Snapshots are fresh recursively immutable mappings with primitive integer/string values only; a mapping proxy is sufficient. They must not contain live cocotb `LogicArray`, handle, task, or simulator objects. No observation can be requested before reset bootstrap.

- `before` is the settled snapshot before the active edge. Derive accepted transfers and external clock/pin events from this phase. `after` is settled post-edge state; use it to plan the following cycle, not to retroactively accept a transfer at the preceding edge.
- Declared controls, e.g. valid/ready/busy and pin-release controls, must resolve on every sampled phase after bootstrap. This applies even when their expected value is `None` because their exact cycle value is deliberately unconstrained by the public spec. `None` is an equality-skip marker, not an X permission.
- For a future exact-cycle model, concrete expected valid is always compared independently. Payload `None` is allowed only when the public contract and model expected state make it a don't-care. Never build an expectation by copying the observed DUT valid, or turn an unexpected valid low into a masked payload pass.
- For current adaptive tests with allowed variable latency, add one explicit payload-capture marker, e.g. public `OBSERVE`, distinct from `None`. `OBSERVE` means “compare this payload in the protocol/queue assertion after observing a legal event,” not “the payload is don't-care.” Preserve unresolved payload bits as a string in the snapshot; do not integer-coerce them. Where the spec defines a valid-to-payload association, case metadata can declare that association so the trusted adapter enforces known payload whenever the DUT claims valid. That check cannot excuse wrong valid behavior; it only rejects unknown claimed payloads.
- The generated scoreboard must separately assert that every claimed output event is legal, ordered, has the expected value, stays stable during required stalls, and arrives within the public bounds. It can update its queue on observed public pre-edge handshakes and hold source valid/data until acceptance. It must assert bounded progress and finish with the queue drained. Observed valid chooses when to check a claimed event; it must not determine the expected valid or silently suppress required output/progress assertions.
- If capacity is permitted in a range, test loss/order/backpressure/overflow properties consistent with the whole range, rather than fixing occupancy thresholds to one implementation. If latency is permitted in a range, check the allowed window and eventual completion rather than a chosen cycle. Simultaneous input/output events follow the public contract, including any permitted fall-through behavior; queue update order must not impose an unstated policy.
- SPI/I2C response and ready/valid driving can adapt through these public snapshots. This alone does not implement combinational wire resolution: any required open-drain environment remains a separately reviewed generic trusted primitive that starts reading only after bootstrap. Never provide the generator a raw DUT callback to obtain this functionality.

This retains spec-authored adaptive tests while removing clock/reset boilerplate. The later required `Model.reset()` + `step(inputs) -> outputs` contract is a separate intervention. Optional `outputs(inputs)` can add pre-edge expectations when the contract makes those determinate. A future SPEC stage may explicitly choose canonical behavior only when the user permits that choice and the frozen specification records it; this first harness treatment makes no such selection.

Additional meaningful qualification: two small implementations with different publicly allowed latency/capacity choices must both pass the same adaptive case. An out-of-range latency, data loss, reordering, unknown control, unknown valid payload, illegal valid event, or missing eventual response must fail. Also verify snapshots cannot mutate later observations or expose simulator handles, and generator exceptions preserve the original named cocotb failure.
