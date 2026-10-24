"""Real evaluation commands. Frozen workers never receive oracle metadata."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from eval.contracts import EvalConfig, HiddenResult
from eval.corpus import corpus_digest, load_cases, private_tree, read_json
from eval.snapshot import freeze, snapshot_environment

ROOT = Path(__file__).resolve().parents[1]


def _oracle_sources() -> list[Path]:
    """Visit only the dedicated grader package, never a corpus/results tree."""
    base = ROOT / "eval"
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Evaluator sources must be a real directory")
    directory = base / "oracles"
    if directory.is_symlink():
        raise ValueError("Oracle sources cannot contain symlinks")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ValueError("Oracle sources must be a directory")
    sources = []
    for current, directories, files in os.walk(directory, followlinks=False):
        directories[:] = sorted(name for name in directories if name != "__pycache__")
        for name in [*directories, *files]:
            path = Path(current) / name
            if path.is_symlink():
                raise ValueError("Oracle sources cannot contain symlinks")
            if name in files and path.suffix == ".py":
                sources.append(path)
    return sources


def _source_fingerprint(paths: list[Path]) -> str:
    base = ROOT / "eval"
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base.resolve()):
            raise ValueError("Evaluator sources must be regular files within eval")
        digest.update(path.relative_to(base).as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def oracle_engine_sha256() -> str:
    return _source_fingerprint([ROOT / "eval/hidden.py", ROOT / "eval/contracts.py", *_oracle_sources()])


def harness_sha256() -> str:
    return _source_fingerprint([*(ROOT / "eval").glob("*.py"), *_oracle_sources()])


def admit_oracles(cases, image_id: str) -> None:
    from eval.hidden import validate_case

    build_cases = [case for case in cases if case.tier < 4]
    if not build_cases:
        return
    marker = ROOT / "eval/oracle_checks.json"
    if not marker.is_file():
        raise ValueError("Run the independent oracle selfchecks before evaluating designs")
    index = read_json(marker)
    if index.get("oracle_engine_sha256") != oracle_engine_sha256() or index.get("eda_image_id") != image_id:
        raise ValueError("Oracle engine or simulator image changed; rerun oracle selfchecks")
    for case in build_cases:
        check = index.get("cases", {}).get(case.id, {})
        if check.get("status") != "pass" or check.get("case_sha256") != validate_case(case):
            raise ValueError("A selected case lacks matching positive/negative oracle evidence")
        positive = HiddenResult.model_validate(check.get("positive"))
        negative = HiddenResult.model_validate(check.get("negative"))
        if (positive.status != "pass" or positive.skipped != 0
                or negative.status != "fail" or not negative.failed
                or not positive.source_snapshot_sha256 or not negative.source_snapshot_sha256
                or positive.source_snapshot_sha256 == negative.source_snapshot_sha256):
            raise ValueError("Oracle admission requires distinct, actually tested positive and negative designs")


async def selfcheck(split: str) -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from eval.hidden import selfcheck_case

    cases = load_cases(ROOT, split, {1, 2, 3, 4})
    image = os.getenv("EDA_IMAGE", "silicon-agent-eda:librelane-3.0.16-cocotb-2.0.1-tools1")
    image_id = run_command(["docker", "image", "inspect", "--format", "{{.Id}}", image])
    engine = oracle_engine_sha256()
    marker = ROOT / "eval/oracle_checks.json"
    previous = read_json(marker) if marker.exists() else {}
    checks = previous.get("cases", {}) if previous.get("oracle_engine_sha256") == engine and previous.get("eda_image_id") == image_id else {}
    output = make_output()
    passed = True
    for case in cases:
        answer = await selfcheck_case(case, output / case.id)
        checks[case.id] = answer
        passed &= answer["status"] == ("not_applicable" if case.tier == 4 else "pass")
        marker.write_text(json.dumps({"schema_version": 1, "oracle_engine_sha256": engine,
                                     "eda_image_id": image_id, "cases": checks}, indent=2) + "\n")
        marker.chmod(0o600)
        print(f"{case.id}: oracle={answer['status']}", flush=True)
    private_tree(output)
    print(f"Independent oracle checks {'PASS' if passed else 'FAIL'}; {len(cases)} cases; {output}", flush=True)
    return 0 if passed else 1


def tiers_arg(value: str) -> set[int]:
    try:
        tiers = {int(item) for item in value.split(",")}
    except ValueError:
        raise argparse.ArgumentTypeError("Tiers must be a comma-separated list from 1 through 4") from None
    if not tiers or not tiers <= {1, 2, 3, 4}:
        raise argparse.ArgumentTypeError("Tiers must be a comma-separated list from 1 through 4")
    return tiers


def result_directory(name: str) -> Path:
    base = (ROOT / "eval/results").resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError("Result IDs must stay inside eval/results")
    return path


def make_output() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    path = ROOT / "eval/results" / stamp
    path.mkdir(parents=True, mode=0o700)
    return path


def run_command(arguments: list[str], *, limit: int = 16_384) -> str:
    completed = subprocess.run(arguments, capture_output=True, text=True, check=True, timeout=20)
    return completed.stdout[:limit].strip()


def preflight() -> dict:
    image = os.getenv("EDA_IMAGE", "silicon-agent-eda:librelane-3.0.16-cocotb-2.0.1-tools1")
    image_id = run_command(["docker", "image", "inspect", "--format", "{{.Id}}", image])
    pdk = Path(os.getenv("EDA_PDK_DIR", str(ROOT / "runs/pdk/ciel/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71")))
    if not (pdk / "sky130A").is_dir():
        raise ValueError("Pinned sky130 PDK missing; run make eda-setup")
    provider = os.getenv("LLM_PROVIDER", "codex")
    if provider not in {"codex", "meta"}:
        raise ValueError("Real evaluations allow codex or meta only")
    if provider == "meta" and not os.getenv("META_API_KEY"):
        raise ValueError("META_API_KEY is not configured; provider will not be substituted")
    cli_version = run_command(["codex", "--version"]) if provider == "codex" else None
    if cli_version is not None and cli_version != "codex-cli 0.163.0":
        raise ValueError("The baseline requires pinned Codex CLI 0.163.0")
    # The real provider performs its own saved-login check without exposing tokens.
    return {"provider": provider, "model": os.getenv("CODEX_MODEL") or "gpt-6.1-sol" if provider == "codex" else os.getenv("META_MODEL", "muse-spark-1.3"),
            "cli_version": cli_version, "tool_versions": {"eda_image": image, "eda_image_id": image_id,
              "pdk_revision": pdk.name, "python": sys.version.split()[0],
              **{package: version(package) for package in ("openai", "pydantic", "sqlmodel")}},
            "cost_target_assessable": provider == "meta"}


async def execute(invocation: Path) -> int:
    # Imported only in the child with PYTHONPATH pointing to the frozen runtime.
    from eval.reporting import build_report, write_report
    from eval.runner import run_suite

    job = read_json(invocation)
    if job["provenance"]["harness_sha256"] != harness_sha256():
        raise ValueError("Evaluator changed after admission; refusing an uncontrolled measurement")
    config = EvalConfig.model_validate(job["config"])
    cases = load_cases(ROOT, job["split"], set(job["tiers"]))
    if corpus_digest(cases) != job["corpus_sha256"]:
        raise ValueError("Corpus changed after evaluation admission")
    admit_oracles(cases, job["provenance"]["tool_versions"]["eda_image_id"])
    try:
        results = await run_suite(cases, config, Path(job["output_root"]), provenance=job["provenance"])
    except BaseException as error:
        # Do not retry paid work. Only previously committed terminal observations
        # are eligible; started-but-unfinished trials remain missing in the plan.
        results, ignored = terminal_results(cases, config, Path(job["output_root"]), job["provenance"])
        report = build_report(cases, results, config)
        report.update(provenance=job["provenance"], corpus_sha256=job["corpus_sha256"],
                      aborted={"reason_type": type(error).__name__, "ignored_result_files": ignored})
        write_report(report, Path(job["output_root"]))
        print(f"Evaluation aborted: {type(error).__name__}; partial artifacts: {job['output_root']}", file=sys.stderr, flush=True)
        if isinstance(error, Exception):
            return 1
        raise
    report = build_report(cases, results, config)
    report["provenance"] = job["provenance"]
    report["corpus_sha256"] = job["corpus_sha256"]
    write_report(report, Path(job["output_root"]))
    print(f"Evaluation artifacts: {job['output_root']}", flush=True)
    # A measured design failure is a valid baseline observation, not a harness crash.
    return 0


def terminal_results(cases, config: EvalConfig, output: Path, provenance: dict) -> tuple[list, int]:
    """Recover evidence for planned identities only, without executing anything."""
    from eval.runner import _existing_trial, _trial_identity
    results, ignored = [], 0
    for case in cases:
        for repeat in range(config.repeats):
            path = output / "trials" / case.split / case.id / f"repeat-{repeat + 1:02d}"
            if not (path / "result.json").exists():
                continue
            try:
                trial_id = f"{case.split}/{case.id}/repeat-{repeat + 1:02d}"
                result = _existing_trial(path, trial_id, _trial_identity(case, repeat, config, provenance), config)
                if result is None or result.pipeline_status not in {"done", "failed", "cancelled"}:
                    raise ValueError("No terminal observation")
                if (result.case_id, result.split, result.tier, result.repeat_index) != (case.id, case.split, case.tier, repeat):
                    raise ValueError("Foreign trial observation")
                results.append(result)
            except (ValueError, OSError):
                ignored += 1
    return results, ignored


def start(args) -> int:
    cases = load_cases(ROOT, args.split, args.tiers)
    provenance = preflight()
    sys.path.insert(0, str(ROOT / "backend"))
    admit_oracles(cases, provenance["tool_versions"]["eda_image_id"])
    output = make_output()
    snapshot = output / "pipeline"
    manifest = freeze(ROOT, snapshot)
    provenance.update(snapshot_root=str(snapshot), pipeline_sha=manifest["pipeline_sha256"],
                      base_commit=manifest["base_commit"],
                      includes_uncommitted_runtime_changes=manifest["includes_uncommitted_runtime_changes"],
                      harness_sha256=harness_sha256())
    config = EvalConfig(repeats=args.repeats, concurrency=args.jobs, max_calls=args.max_calls,
                        max_tokens=args.max_tokens, max_usd=args.max_usd,
                        time_limit_seconds=args.timeout, snapshot_id=manifest["pipeline_sha256"])
    job = {"split": args.split, "tiers": sorted(args.tiers), "config": config.model_dump(mode="json"),
           "provenance": provenance, "corpus_sha256": corpus_digest(cases), "output_root": str(output)}
    invocation = output / "invocation.json"
    invocation.write_text(json.dumps(job, indent=2) + "\n")
    private_tree(output)
    env = snapshot_environment(ROOT, snapshot)
    env.update(LLM_MAX_CALLS=str(config.max_calls), LLM_MAX_TOKENS=str(config.max_tokens),
               RUN_BUDGET_USD=str(config.max_usd), PYTHONDONTWRITEBYTECODE="1")
    print(f"Starting {len(cases)} {args.split} cases × {config.repeats} repeats; jobs={config.concurrency}; snapshot={config.snapshot_id[:12]}", flush=True)
    print("Plan USD cost is unavailable; call/token/time caps remain enforced." if provenance["provider"] == "codex" else "Meta USD guard and call/token/time caps enabled.", flush=True)
    return subprocess.run([sys.executable, "-m", "eval", "_execute", str(invocation)], env=env, cwd=ROOT).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the real frozen pipeline with independent post-run tests")
    run.add_argument("--set", dest="split", choices=("dev", "heldout"), default="dev")
    run.add_argument("--tiers", type=tiers_arg, default={1, 2, 3, 4})
    run.add_argument("--repeat", dest="repeats", type=int, default=1)
    run.add_argument("--jobs", type=int, default=1)
    run.add_argument("--max-calls", type=int, default=32)
    run.add_argument("--max-tokens", type=int, default=300_000)
    run.add_argument("--max-usd", type=float, default=1.0)
    run.add_argument("--timeout", type=float, default=900.0)
    validate = commands.add_parser("validate", help="Validate corpus contracts; never invoke a model")
    validate.add_argument("--set", dest="split", choices=("dev", "heldout"), default="dev")
    oracle = commands.add_parser("selfcheck", help="Test independent references and deliberate mutants; no model calls")
    oracle.add_argument("--set", dest="split", choices=("dev", "heldout"), default="dev")
    compare = commands.add_parser("compare", help="Compare real reports with compatible provenance")
    compare.add_argument("a")
    compare.add_argument("b")
    compare.add_argument("--scope-bridge", help="Explicit audited scope-observer bridge artifact ID")
    bridge = commands.add_parser("scope-bridge", help="Reobserve all sealed source trials without model or EDA calls")
    bridge.add_argument("source")
    bridge.add_argument("--output-id")
    child = commands.add_parser("_execute", help=argparse.SUPPRESS)
    child.add_argument("invocation", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return start(args)
        if args.command == "_execute":
            return asyncio.run(execute(args.invocation))
        if args.command == "validate":
            cases = load_cases(ROOT, args.split, {1, 2, 3, 4})
            print(json.dumps({"split": args.split, "counts": dict(Counter(c.tier for c in cases)),
                              "corpus_sha256": corpus_digest(cases)}))
            return 0
        if args.command == "selfcheck":
            return asyncio.run(selfcheck(args.split))
        if args.command == "scope-bridge":
            from eval.scope_observation import create_bridge
            print(json.dumps(create_bridge(args.source, args.output_id, root=ROOT), indent=2))
            return 0
        if args.scope_bridge:
            from eval.scope_observation import compare_with_scope_bridge
            print(json.dumps(compare_with_scope_bridge(args.a, args.b, args.scope_bridge, root=ROOT), indent=2, allow_nan=False))
            return 0
        from eval.reporting import compare_reports
        result = compare_reports(read_json(result_directory(args.a) / "summary.json"),
                                 read_json(result_directory(args.b) / "summary.json"))
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Validation input values and subprocess arguments/stderr may contain
        # private corpus text or provider context. Keep CLI errors class-only.
        print(f"Evaluation did not start/complete: {type(error).__name__}. Check private artifacts and admission configuration.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
