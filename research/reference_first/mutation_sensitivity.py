"""Model-free mutation sensitivity of the two verification gates on delivered RTL.

For each successful hardware trial whose selected flow snapshot contains the host
reference module, this replays the exact selected sources and tests in the pinned
simulator image, then applies deterministic single-point RTL mutations. A mutant
counts as killed by a gate only when that gate's real cocotb XML records a failed
case; a build failure, timeout or missing XML is an invalid mutant for every gate.
No model call is made. Mutants can be behaviorally equivalent, so absolute kill
rates are lower bounds; the comparison between gates uses the same mutants.

Run from the candidate checkout root:

    PYTHONPATH=backend uv run --offline --python 3.12.13 --with-requirements backend/requirements.txt \
      python -B research/reference_first/mutation_sensitivity.py <cohort-dir> <scratch-dir> [max-trials]
"""
import asyncio
import json
from pathlib import Path
import re
import shutil
import sys

from app.eda import sim
from app.eda.sandbox import DockerSandbox

IMAGE = "sha256:9b62eb4f8e873591f6925c3aaf1f7cf459e848e867809a9068d48d49025f3cc8"
REFERENCE = "test_reference_model"
MAX_MUTANTS = 12
CONCURRENCY = 4
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"", re.S)
_SIZED = re.compile(r"(\d+)'([bBdDhH])([0-9a-fA-F_]+)\b")
_PLAIN = re.compile(r"(?<![\w'.$])\d+(?![\w'.])")
_OPERATORS = (
    (re.compile(r"(?<![=!<>])==(?!=)"), "!="),
    (re.compile(r"!=(?!=)"), "=="),
    (re.compile(r"&&"), "||"),
    (re.compile(r"\|\|"), "&&"),
    (re.compile(r"(?<![&~])&(?![&])"), "|"),
    (re.compile(r"(?<![|~])\|(?![|])"), "&"),
    (re.compile(r"(?<![-=<>])>(?![>=])"), ">="),
    (re.compile(r">="), ">"),
    (re.compile(r"(?<![<])<(?![<=])"), "<="),
    (re.compile(r"(?<![~^])\^(?![~^])"), "|"),
    (re.compile(r"~(?![&|^])"), ""),
)
_BIT = re.compile(r"(?<=\[)(\d+)(?=\])")


def _masked(text: str) -> str:
    return _COMMENT.sub(lambda match: " " * len(match.group()), text)


def _binary_arithmetic(masked: str):
    for index, char in enumerate(masked):
        if char not in "+-" or masked[index + 1:index + 2] in {":", ">", "+", "-", "="}:
            continue
        previous = masked[:index].rstrip()[-1:]
        if previous and (previous.isalnum() or previous in "_)]'"):
            yield index, index + 1, "-" if char == "+" else "+"


def _plain_integers(masked: str):
    """Unsized decimal constants outside [] ranges, e.g. `count == 9` -> `count == 8`."""
    depth, depths = 0, []
    for char in masked:
        depth += char == "["
        depths.append(depth)
        depth -= char == "]"
    for match in _PLAIN.finditer(masked):
        if depths[match.start()] == 0:
            value = int(match.group())
            yield match.start(), match.end(), str(value - 1 if value > 0 else 1)


def _literal(match) -> str | None:
    width, base, digits = int(match.group(1)), match.group(2).lower(), match.group(3).replace("_", "")
    try:
        value = int(digits, {"b": 2, "d": 10, "h": 16}[base])
    except ValueError:
        return None
    if width < 1 or width > 64:
        return None
    changed = value + 1 if value + 1 < (1 << width) else value - 1
    if changed < 0:
        return None
    text = {"b": format(changed, "b"), "d": str(changed), "h": format(changed, "x")}[base]
    return f"{width}'{match.group(2)}{text}"


def mutation_sites(sources: dict[str, str]) -> list[tuple[str, int, int, str]]:
    """Deterministic single-point sites across RTL files, outside comments/strings."""
    sites = []
    for name in sorted(sources):
        text = sources[name]
        masked = _masked(text)
        body = masked.find(");")  # Skip the port header: widths there change the interface.
        for pattern, replacement in _OPERATORS:
            sites += [(name, m.start(), m.end(), replacement) for m in pattern.finditer(masked) if m.start() > body]
        sites += [(name, start, end, replacement) for start, end, replacement in _binary_arithmetic(masked) if start > body]
        sites += [(name, start, end, replacement) for start, end, replacement in _plain_integers(masked) if start > body]
        sites += [(name, m.start(), m.end(), str(int(m.group()) + 1 if m.group() == "0" else int(m.group()) - 1))
                  for m in _BIT.finditer(masked) if m.start() > body]
        for match in _SIZED.finditer(masked):
            replacement = _literal(match)
            if replacement is not None and match.start() > body:
                sites.append((name, match.start(), match.end(), replacement))
    sites.sort(key=lambda site: (site[0], site[1]))
    unique = list(dict.fromkeys(sites))
    if len(unique) <= MAX_MUTANTS:
        return unique
    step = len(unique) / MAX_MUTANTS
    return [unique[int(index * step)] for index in range(MAX_MUTANTS)]


def selected_snapshot(trial_dir: Path, run_tag: str) -> Path | None:
    for work in trial_dir.glob("pipeline/*/work"):
        for flow in work.glob(".eda/flow_*"):
            if (flow / "output" / "runs" / run_tag).is_dir():
                return flow
    return None


async def run_module(sandbox, root: Path, label: str, sources: dict[str, str], tests: Path, top: str, module: str):
    case = root / label / module
    if case.exists():
        shutil.rmtree(case)
    (case / "input" / "src").mkdir(parents=True)
    shutil.copytree(tests, case / "input" / "test")
    for name, text in sources.items():
        (case / "input" / "src" / name).write_text(text)
    result = await sim.run_tests(sandbox, case / "input", case / "output", top, module)
    if isinstance(result.get("cases"), list) and result["cases"]:
        return "killed" if type(result.get("failed")) is int and result["failed"] > 0 else (
            "survived" if result.get("ok") is True else "invalid")
    return "invalid"


async def analyze_trial(sandbox, scratch: Path, trial: dict, cohort: Path, gate: asyncio.Semaphore):
    trial_dir = cohort / "trials" / trial["trial_id"]
    snapshot = selected_snapshot(trial_dir, trial["selected_run_tag"])
    if snapshot is None:
        return {"trial": trial["trial_id"], "status": "no_selected_snapshot"}
    tests = snapshot / "input" / "test"
    if not (tests / f"{REFERENCE}.py").is_file():
        return {"trial": trial["trial_id"], "status": "no_reference_module"}
    top = json.loads((snapshot / "output" / "config.json").read_text())["DESIGN_NAME"]
    modules = sorted(path.stem for path in tests.glob("*.py"))
    sources = {path.name: path.read_text() for path in sorted((snapshot / "input" / "src").glob("*.v"))}
    root = scratch / trial["trial_id"].replace("/", "__")
    async with gate:
        baseline = {module: await run_module(sandbox, root, "original", sources, tests, top, module) for module in modules}
        if any(outcome != "survived" for outcome in baseline.values()):
            return {"trial": trial["trial_id"], "status": "baseline_not_passing", "baseline": baseline}
        mutants = []
        for index, (name, start, end, replacement) in enumerate(mutation_sites(sources)):
            mutated = dict(sources)
            mutated[name] = sources[name][:start] + replacement + sources[name][end:]
            outcomes = {module: await run_module(sandbox, root, f"mutant_{index:02d}", mutated, tests, top, module)
                        for module in modules}
            mutants.append({"file": name, "offset": start, "replacement": replacement, "outcomes": outcomes})
    return {"trial": trial["trial_id"], "tier": trial["tier"], "status": "analyzed",
            "model_modules": [m for m in modules if m != REFERENCE], "mutants": mutants}


def aggregate(rows: list[dict]) -> dict:
    valid = killed_model = killed_reference = killed_union = reference_only = model_only = 0
    for row in rows:
        for mutant in row.get("mutants", []):
            outcomes = mutant["outcomes"]
            if any(outcome == "invalid" for outcome in outcomes.values()):
                continue
            valid += 1
            model = any(outcomes[m] == "killed" for m in row["model_modules"])
            reference = outcomes[REFERENCE] == "killed"
            killed_model += model
            killed_reference += reference
            killed_union += model or reference
            reference_only += reference and not model
            model_only += model and not reference
    return {"designs_analyzed": sum(row["status"] == "analyzed" for row in rows),
            "skipped": {status: sum(row["status"] == status for row in rows)
                        for status in sorted({row["status"] for row in rows} - {"analyzed"})},
            "valid_mutants": valid, "killed_by_model_tests": killed_model,
            "killed_by_reference": killed_reference, "killed_by_either": killed_union,
            "reference_only_kills": reference_only, "model_only_kills": model_only}


async def main() -> None:
    cohort, scratch = Path(sys.argv[1]), Path(sys.argv[2])
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    scratch.mkdir(parents=True, exist_ok=False)
    summary = json.loads((cohort / "summary.json").read_text())
    trials = [t for t in summary["trials"] if t["tier"] < 4 and t["success"] and t.get("selected_run_tag")]
    trials = trials[:limit] if limit is not None else trials
    sandbox = DockerSandbox(image=IMAGE)
    gate = asyncio.Semaphore(CONCURRENCY)
    rows = await asyncio.gather(*(analyze_trial(sandbox, scratch, trial, cohort, gate) for trial in trials))
    report = {"schema_version": 1, "cohort": cohort.name, "image_id": IMAGE, "max_mutants_per_design": MAX_MUTANTS,
              "aggregate": aggregate(rows), "rows": rows}
    (scratch / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["aggregate"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
