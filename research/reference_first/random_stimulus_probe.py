"""Offline probe: does long model-driven stimulus add verification value?

For each delivered design analyzed by mutation_sensitivity.py, this composes one
cocotb module from the run's own prechecked reference model and drives seeded,
biased random inputs (reset asserted on the first cycle and rarely afterwards),
comparing every output to the model after every rising edge. It replays the
delivered RTL (which passed the independent hidden tests) to count false alarms,
then the same deterministic mutants to compare kills with the earlier gates. No
model call is made; the reference models already exist in the trial records.

    PYTHONPATH=backend:research/reference_first uv run --offline --python 3.12.13 \
      --with-requirements backend/requirements.txt python -B \
      research/reference_first/random_stimulus_probe.py <cohort-dir> <mutation-report.json> <scratch-dir>
"""
import asyncio
import json
from pathlib import Path
import shutil
import sys

from app.agent.tools import _validate_test
from app.eda import sim
from app.eda.sandbox import DockerSandbox
from mutation_sensitivity import CONCURRENCY, IMAGE, REFERENCE, mutation_sites, selected_snapshot

MODULE = "test_reference_random"
SEEDS = (11, 23, 37)
CYCLES = 400


def compose_random(model_source: str, contract: dict) -> str:
    sync = contract["profile"].startswith("sync_")
    clock, reset = contract["clock_port"], contract["reset_port"]
    inputs = [(p["name"], p["width"]) for p in contract["ports"] if p["direction"] == "input" and p["name"] != clock]
    outputs = [(p["name"], p["width"]) for p in contract["ports"] if p["direction"] == "output"]
    lines = ["# Research probe: seeded model-driven stimulus; not a correctness proof.",
             "import random", "import cocotb", "from cocotb.triggers import ReadOnly, Timer", "",
             model_source, "",
             f"INPUTS = {inputs!r}", f"OUTPUTS = {outputs!r}", "",
             "async def _random_case(dut, seed, cycles):",
             "    rng = random.Random(seed)",
             "    model = Model()"]
    if sync:
        lines.append("    model.reset()")
    lines += ["    current = {}",
              "    for cycle in range(cycles):",
              "        inputs = {}",
              "        for name, width in INPUTS:"]
    if sync:
        lines += [f"            if name == {reset!r}:",
                  "                inputs[name] = 0 if cycle == 0 or rng.random() < 0.01 else 1",
                  "                continue"]
    lines += ["            change = rng.random() < (0.3 if width == 1 else 0.5)",
              "            inputs[name] = rng.getrandbits(width) if change or name not in current else current[name]",
              "        current = dict(inputs)"]
    if sync:
        lines.append(f"        dut._id({clock!r}, extended=False).value = 0")
    lines += ["        for name, value in inputs.items():",
              "            dut._id(name, extended=False).value = value",
              "        await Timer(1, unit='ns')"]
    if sync:
        lines += [f"        dut._id({clock!r}, extended=False).value = 1", "        await Timer(1, unit='ns')"]
    lines += ["        await ReadOnly()",
              f"        predicted = model.{'step' if sync else 'evaluate'}(dict(inputs))",
              "        for name, width in OUTPUTS:",
              "            value = dut._id(name, extended=False).value",
              "            assert value.is_resolvable, 'DUT_OUTPUT_UNRESOLVED:%s cycle=%d' % (name, cycle)",
              "            assert int(value) == predicted[name], 'DUT_MODEL_MISMATCH:%s cycle=%d expected=%r got=%r' % (",
              "                name, cycle, predicted[name], int(value))",
              "        await Timer(1, unit='ns')"]
    if sync:
        lines += [f"        dut._id({clock!r}, extended=False).value = 0", "        await Timer(1, unit='ns')"]
    for index, seed in enumerate(SEEDS):
        lines += ["", "@cocotb.test()", f"async def test_random_{index:02d}(dut):",
                  f"    await _random_case(dut, {seed}, {CYCLES})"]
    source = "\n".join(lines) + "\n"
    _validate_test(source)  # Same source policy as model-authored tests.
    return source


async def run_case(sandbox, root: Path, label: str, sources: dict[str, str], test_source: str, top: str):
    case = root / label
    if case.exists():
        shutil.rmtree(case)
    (case / "input" / "src").mkdir(parents=True)
    (case / "input" / "test").mkdir()
    (case / "input" / "test" / f"{MODULE}.py").write_text(test_source)
    for name, text in sources.items():
        (case / "input" / "src" / name).write_text(text)
    result = await sim.run_tests(sandbox, case / "input", case / "output", top, MODULE)
    cases = result.get("cases") if isinstance(result.get("cases"), list) else []
    if not cases:
        return {"outcome": "invalid", "message": str(result.get("error", ""))[:160]}
    failed = [c for c in cases if c.get("ok") is False]
    if failed:
        message = str(failed[0].get("message", ""))
        kind = ("dut_mismatch" if "DUT_MODEL_MISMATCH" in message else
                "dut_unresolved" if "DUT_OUTPUT_UNRESOLVED" in message else "test_or_model_error")
        return {"outcome": "killed", "kind": kind, "message": message[:200]}
    return {"outcome": "survived" if result.get("ok") is True else "invalid", "message": ""}


async def probe(sandbox, scratch: Path, cohort: Path, trial: dict, prior: dict, gate):
    trial_dir = cohort / "trials" / trial["trial_id"]
    snapshot = selected_snapshot(trial_dir, trial["selected_run_tag"])
    precheck = next(trial_dir.glob("pipeline/*/work/.eda/reference_precheck_*/input"))
    contract = json.loads((precheck / "contract.json").read_text())
    test_source = compose_random((precheck / "model.py").read_text(), contract)
    top = json.loads((snapshot / "output" / "config.json").read_text())["DESIGN_NAME"]
    sources = {path.name: path.read_text() for path in sorted((snapshot / "input" / "src").glob("*.v"))}
    root = scratch / trial["trial_id"].replace("/", "__")
    async with gate:
        original = await run_case(sandbox, root, "original", sources, test_source, top)
        mutants = []
        for index, (name, start, end, replacement) in enumerate(mutation_sites(sources)):
            earlier = prior["mutants"][index]
            assert (earlier["file"], earlier["offset"], earlier["replacement"]) == (name, start, replacement)
            mutated = dict(sources)
            mutated[name] = sources[name][:start] + replacement + sources[name][end:]
            mutants.append({"earlier": earlier["outcomes"],
                            "random": await run_case(sandbox, root, f"mutant_{index:02d}", mutated, test_source, top)})
    return {"trial": trial["trial_id"], "tier": trial["tier"], "model_modules": prior["model_modules"],
            "original": original, "mutants": mutants}


def aggregate(rows):
    totals = {"designs": len(rows), "false_alarms_on_delivered_rtl": 0, "false_alarm_kinds": {},
              "valid_mutants": 0, "verify_kills": 0, "directed_reference_kills": 0, "random_kills": 0,
              "random_only_vs_verify": 0, "verify_only_vs_random": 0, "any_gate_kills": 0}
    for row in rows:
        if row["original"]["outcome"] != "survived":
            totals["false_alarms_on_delivered_rtl"] += 1
            kind = row["original"].get("kind", row["original"]["outcome"])
            totals["false_alarm_kinds"][kind] = totals["false_alarm_kinds"].get(kind, 0) + 1
            continue  # A probe that rejects correct RTL cannot score mutants.
        for mutant in row["mutants"]:
            earlier, random_outcome = mutant["earlier"], mutant["random"]["outcome"]
            if random_outcome == "invalid" or any(value == "invalid" for value in earlier.values()):
                continue
            verify = any(earlier[m] == "killed" for m in row["model_modules"])
            directed = earlier[REFERENCE] == "killed"
            random_kill = random_outcome == "killed"
            totals["valid_mutants"] += 1
            totals["verify_kills"] += verify
            totals["directed_reference_kills"] += directed
            totals["random_kills"] += random_kill
            totals["random_only_vs_verify"] += random_kill and not verify
            totals["verify_only_vs_random"] += verify and not random_kill
            totals["any_gate_kills"] += verify or directed or random_kill
    return totals


async def main():
    cohort, report_path, scratch = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    scratch.mkdir(parents=True, exist_ok=False)
    summary = {t["trial_id"]: t for t in json.loads((cohort / "summary.json").read_text())["trials"]}
    prior = [row for row in json.loads(report_path.read_text())["rows"] if row["status"] == "analyzed"]
    sandbox, gate = DockerSandbox(image=IMAGE), asyncio.Semaphore(CONCURRENCY)
    rows = await asyncio.gather(*(probe(sandbox, scratch, cohort, summary[row["trial"]], row, gate) for row in prior))
    report = {"schema_version": 1, "cohort": cohort.name, "seeds": SEEDS, "cycles_per_seed": CYCLES,
              "aggregate": aggregate(rows), "rows": rows}
    (scratch / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["aggregate"], indent=2))
    for row in rows:
        if row["original"]["outcome"] != "survived":
            print("FALSE ALARM", row["trial"], row["original"].get("kind"), row["original"]["message"][:160])


if __name__ == "__main__":
    asyncio.run(main())
