"""Failure recovery on synthetic unit records; never starts model or EDA jobs."""
import asyncio
import json

import pytest

from eval import cli, runner
from eval.contracts import EvalCase, EvalConfig, TrialResult


def planned_cases(tmp_path):
    cases = []
    for tier, count in ((1, 8), (2, 10), (3, 6), (4, 6)):
        for index in range(count):
            name = f"unit-{tier}-{index}"
            path = tmp_path / "corpus" / name
            path.mkdir(parents=True)
            (path / "spec.md").write_text("Unit-only synthetic case, never executed.")
            cases.append(EvalCase(id=name, tier=tier, expected_outcome="decline" if tier == 4 else "build",
                                  behaviors=["Unit control test only"], case_dir=path, split="dev",
                                  spec_text=(path / "spec.md").read_text(), provenance=[] if tier == 4 else [{
                                      "source_url": "https://example.invalid/unit-only", "commit": "a" * 40,
                                      "path": "unit.v", "license": "Unit-only fixture", "sha256": "a" * 64}]))
    return cases


def persist_terminal(output, case, config, provenance):
    path = output / "trials" / case.split / case.id / "repeat-01"
    trial_id = f"{case.split}/{case.id}/repeat-01"
    result = TrialResult(trial_id=trial_id, case_id=case.id, split=case.split, tier=case.tier,
                         repeat_index=0, pipeline_sha=config.snapshot_id, attempted=True, pipeline_status="failed",
                         stage="VERIFY", error="Unit-only controlled failure", terminal_message_present=True)
    runner._write_json(path / "started.json", {"identity_sha256": runner._trial_identity(case, 0, config, provenance)})
    runner._write_json(path / "result.json", result.model_dump(mode="json"))
    return result, path


def test_child_failure_writes_planned_partial_summary_without_retry_or_exception_text(tmp_path, monkeypatch, capsys):
    cases = planned_cases(tmp_path)
    output = tmp_path / "output"
    config = EvalConfig(repeats=3, snapshot_id="d" * 64)
    provenance = {"harness_sha256": "b" * 64, "tool_versions": {"eda_image_id": "UNIT_ONLY_IMAGE"}}
    terminal, _ = persist_terminal(output, cases[0], config, provenance)
    started = output / "trials" / cases[1].split / cases[1].id / "repeat-01"
    runner._write_json(started / "started.json", {"identity_sha256": runner._trial_identity(cases[1], 0, config, provenance)})
    invocation = tmp_path / "invocation.json"
    runner._write_json(invocation, {"config": config.model_dump(mode="json"), "split": "dev", "tiers": [1, 2, 3, 4],
                                   "provenance": provenance, "corpus_sha256": "c" * 64, "output_root": str(output)})
    monkeypatch.setattr(cli, "harness_sha256", lambda: "b" * 64)
    monkeypatch.setattr(cli, "load_cases", lambda *_: cases)
    monkeypatch.setattr(cli, "corpus_digest", lambda _: "c" * 64)
    monkeypatch.setattr(cli, "admit_oracles", lambda *_: None)
    starts = []
    async def failed_suite(*args, **kwargs):
        starts.append(True)
        raise RuntimeError("PRIVATE_EXCEPTION_TEXT_MUST_NOT_APPEAR")
    monkeypatch.setattr(runner, "run_suite", failed_suite)
    assert asyncio.run(cli.execute(invocation)) == 1
    report = json.loads((output / "summary.json").read_text())
    assert report["totals"]["planned"] == len(cases) * config.repeats
    assert report["totals"]["recorded"] == report["totals"]["attempted"] == 1
    assert report["totals"]["missing"] == len(cases) * config.repeats - 1
    assert report["trials"][0]["trial_id"] == terminal.trial_id
    assert report["totals"]["measurements"]["calls"]["median"] == terminal.calls
    assert report["aborted"] == {"reason_type": "RuntimeError", "ignored_result_files": 0}
    assert all(target["status"] == "not_assessable" for target in report["target_assessment"]["targets"].values())
    assert "PRIVATE_EXCEPTION_TEXT" not in (output / "summary.json").read_text()
    assert "PRIVATE_EXCEPTION_TEXT" not in capsys.readouterr().err
    assert starts == [True]  # No recovery retries.


def test_partial_recovery_ignores_foreign_duplicate_and_nonterminal_rows(tmp_path):
    cases = planned_cases(tmp_path)
    config, provenance = EvalConfig(snapshot_id="d" * 64), {}
    result, path = persist_terminal(tmp_path, cases[0], config, provenance)
    # Copying a valid row to another planned slot never creates a second trial.
    target = tmp_path / "trials" / cases[1].split / cases[1].id / "repeat-01"
    runner._write_json(target / "started.json", {"identity_sha256": runner._trial_identity(cases[1], 0, config, provenance)})
    runner._write_json(target / "result.json", result.model_dump(mode="json"))
    # Pending/running rows are not terminal observations, even when valid JSON.
    _, pending = persist_terminal(tmp_path, cases[2], config, provenance)
    data = json.loads((pending / "result.json").read_text())
    data["pipeline_status"] = "running"
    runner._write_json(pending / "result.json", data)
    rows, ignored = cli.terminal_results(cases, config, tmp_path, provenance)
    assert rows == [result] and ignored == 2


def test_child_cancellation_writes_partial_summary_and_still_propagates(tmp_path, monkeypatch):
    cases = planned_cases(tmp_path)
    config, output = EvalConfig(snapshot_id="d" * 64), tmp_path / "output"
    provenance = {"harness_sha256": "b" * 64, "tool_versions": {"eda_image_id": "UNIT_ONLY_IMAGE"}}
    persist_terminal(output, cases[0], config, provenance)
    invocation = tmp_path / "invocation.json"
    runner._write_json(invocation, {"config": config.model_dump(mode="json"), "split": "dev", "tiers": [1, 2, 3, 4],
                                   "provenance": provenance, "corpus_sha256": "c" * 64, "output_root": str(output)})
    monkeypatch.setattr(cli, "harness_sha256", lambda: "b" * 64)
    monkeypatch.setattr(cli, "load_cases", lambda *_: cases)
    monkeypatch.setattr(cli, "corpus_digest", lambda _: "c" * 64)
    monkeypatch.setattr(cli, "admit_oracles", lambda *_: None)
    async def cancelled_suite(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(runner, "run_suite", cancelled_suite)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cli.execute(invocation))
    report = json.loads((output / "summary.json").read_text())
    assert report["aborted"]["reason_type"] == "CancelledError"
    assert report["totals"]["recorded"] == 1
    assert report["totals"]["missing"] == len(cases) * config.repeats - report["totals"]["recorded"]


def test_invalid_heldout_metadata_is_not_exposed_by_cli_error(monkeypatch, capsys):
    from eval.contracts import CaseDefinition
    secret = "PRIVATE_HELDOUT_SCOPE_SENTINEL"
    def invalid_case(*args, **kwargs):
        CaseDefinition.model_validate({"id": "opaque", "tier": 4, "expected_outcome": secret,
                                       "behaviors": ["Private synthetic unit metadata"]})
    monkeypatch.setattr(cli, "load_cases", invalid_case)
    assert cli.main(["validate", "--set", "heldout"]) == 2
    output = capsys.readouterr()
    assert "ValidationError" in output.err
    assert secret not in output.err + output.out


def test_subprocess_command_and_stderr_are_not_exposed_by_cli_error(monkeypatch, capsys):
    def failed_process():
        raise cli.subprocess.CalledProcessError(1, ["unit-command", "PRIVATE_ARGUMENT_SENTINEL"], stderr="PRIVATE_PROVIDER_SENTINEL")
    monkeypatch.setattr(cli, "load_cases", lambda *args: [])
    monkeypatch.setattr(cli, "preflight", failed_process)
    assert cli.main(["run"]) == 2
    output = capsys.readouterr()
    assert "CalledProcessError" in output.err
    assert "PRIVATE_ARGUMENT_SENTINEL" not in output.err + output.out
    assert "PRIVATE_PROVIDER_SENTINEL" not in output.err + output.out
