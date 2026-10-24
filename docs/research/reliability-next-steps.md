# Reliability implementation sequence

This is an engineering plan, not a completed-feature or performance claim.
R1 remains frozen until all 90 development trials finish. No held-out
specifications or golden implementations informed this plan.

## Measurement boundaries

- Commit the R1 result and its keep/revert decision before changing runtime
  sources. Preserve G0 results and the separately audited G1 observation bridge.
- Hold the provider, model, caps, concurrency, EDA image ID, PDK and Python/tool
  versions constant. Runtime snapshot hashes are expected to change.
- Record every treatment as a whole. A treatment containing multiple related
  fixes cannot establish which individual component caused its observed delta.
- Compare full development cohorts with three repeats, retaining every planned
  case in the denominator. Unknown plan cost remains unknown.
- Do not run held-out performance until development success and failure-clarity
  targets are satisfied. Do not use held-out results for subsequent tuning.

## Next verification treatment

The baseline's seven hardware failures read an unresolved output before the
first synchronous reset edge. R1 additionally exposed an incorrect expected
LFSR sequence in a generated test plan. These need distinct protections:

1. A trusted simulator adapter owns clock/reset and DUT handles. Generated
   cases supply stimulus and expected values; they cannot sample uninitialized
   handles before reset. An immutable observation API supports adaptive
   handshakes without forcing an unstated microarchitecture or response cycle.
2. Bounded tool replies retain the first actual exception/assertion, test name,
   counts and artifact locations. Logs are truncated separately. The current
   serialized-tail truncation discards useful exceptions.
3. Directed and random cases cover numbered behavior requirements, reset and
   input boundaries. Passing test count alone is not a coverage argument.
4. A subsequent reference-model stage defines cycle transitions independently
   of RTL. Its own examples must be checked against the public behavior;
   comparing a generated RTL with a generated model does not establish hidden
   golden correctness. A SPEC critic must check invented test-plan examples.

The helper should live in frozen backend-owned source and be mounted read-only
into the pinned image's existing import directory. Validate this with an actual
Docker run before relying on it. Record its API/version/hash and imported
origin in app evidence, not evaluator `tool_versions`; the latter is the exact
toolchain comparison identity. Reserve the helper module name in generated
files and snapshots, and include the helper in downloadable test bundles.

Qualification must include correct synchronous reset, missing reset, X-valued
controls, payload-valid masking, combinational behavior, deterministic random
seeds and bounded eventual response. Two implementations with different
publicly permitted latencies must pass the same protocol case. Lost/reordered
data and forbidden latency must fail. Compile/import/timeout failures are not
functional-test failures or mutation kills.

## Repair and context

Use deterministic failure evidence to choose a focused repair prompt. Check
search/replace patches against an exact base digest and unique match; apply
atomically, then validate the unchanged interface and run static checks.
Repeated RTL hashes or the same diagnostic three times trigger bounded
escalation rather than repeated simulation. Keep a clean best source snapshot
and retain all proposed/rejected patches in the trace.

Stage memory can be derived from actual structured evidence without asking the
model to recite it. The baseline failure audit found 83 summary requests using
43% of input tokens in seven failed hardware runs. Treat removing those calls
as an explicit measured context change; do not silently alter evaluation caps.

Test/model edits need a recorded contradiction with the frozen public
requirement, a concrete correction and a retained diff. A model's assertion
that a test is wrong is not independently verified semantic evidence for the
failure classifier. Hidden tests remain private and are never repair feedback.

## Remaining dependencies

| Component | Prerequisite and evidence |
| --- | --- |
| Frozen interface | Validated SPEC plus exact elaborated top-level port comparison |
| SPEC critic/defaults | Separate bounded critic, typed assumptions and explicit user overrides |
| Feasibility | Public block estimates and exact pin-allocation math; estimates labeled as estimates |
| Static checks | Pinned Verilator diagnostics plus actual Yosys `check -assert` outputs |
| Hierarchical generation | Frozen top interface and bounded per-module static checks |
| Pattern retrieval | Independently verified small public patterns; no eval-derived sources |
| Flow sizing | Mapped synthesis area, actual flow configuration schema and placement constraints |
| Flow repair | Failed-stage diagnostics and bounded handlers; fixed tile geometry stays fixed |
| TT wrapper | Typed port roles, deterministic bit mapping and real wrapper simulation |
| TT readiness | Pinned shuttle configuration and precheck, separate from clean standalone DRC/LVS |
| Optimization | Passing verification and clean initial flow; retain best clean candidate |
| Retry from stage | Source/test/config/tool identity-bound checkpoints; invalidate downstream evidence |
| Reliability UI | Aggregate eval reports, development-only access and honest unknown cost |
| Final proof | Full dev repeats, held-out repeats once, QA and fixed-reference CI regression gate |

The standalone physical flow is already clean for every completed baseline
hardware trial. Deterministic flow changes therefore follow the measured
verification failures; they are not a reason to guess new metric keys or
change the image during the current experiment.
