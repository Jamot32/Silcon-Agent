"""CLI admission tests replace external processes; no model or EDA is invoked."""

from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from eval import cli


def test_failed_preflight_stops_before_snapshot_process_or_paid_work(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_cases", lambda *_: ["UNIT_ONLY_CASE"])

    def blocked():
        raise ValueError("UNIT_ONLY_PREFLIGHT_UNAVAILABLE")

    def forbidden(*_args, **_kwargs):
        pytest.fail("Failed admission must not create a snapshot or execute a child")

    monkeypatch.setattr(cli, "preflight", blocked)
    monkeypatch.setattr(cli, "make_output", forbidden)
    monkeypatch.setattr(cli, "freeze", forbidden)
    monkeypatch.setattr(cli.subprocess, "run", forbidden)
    assert cli.main(["run", "--set", "dev", "--tiers", "1"]) == 2
    output = capsys.readouterr().err
    assert "ValueError" in output and "UNIT_ONLY_PREFLIGHT_UNAVAILABLE" not in output


def test_meta_admission_does_not_silently_fall_back_when_key_is_absent(tmp_path, monkeypatch):
    pdk = tmp_path / "unit-pdk"
    (pdk / "sky130A").mkdir(parents=True)
    monkeypatch.setenv("EDA_PDK_DIR", str(pdk))
    monkeypatch.setenv("LLM_PROVIDER", "meta")
    monkeypatch.delenv("META_API_KEY", raising=False)
    commands = []

    def unit_command(arguments):
        commands.append(arguments)
        return "sha256:UNIT_ONLY_IMAGE_ID"

    monkeypatch.setattr(cli, "run_command", unit_command)
    with pytest.raises(ValueError, match="will not be substituted"):
        cli.preflight()
    assert len(commands) == 1 and commands[0][:3] == ["docker", "image", "inspect"]


def test_codex_plan_admission_keeps_usd_unassessable_without_a_paid_probe(tmp_path, monkeypatch):
    pdk = tmp_path / "unit-pdk"
    (pdk / "sky130A").mkdir(parents=True)
    monkeypatch.setenv("EDA_PDK_DIR", str(pdk))
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("CODEX_MODEL", "unit-only-selected-model")
    commands = []

    def unit_command(arguments):
        commands.append(arguments)
        return "codex-cli 0.163.0" if arguments[0] == "codex" else "sha256:UNIT_ONLY_IMAGE_ID"

    monkeypatch.setattr(cli, "run_command", unit_command)
    result = cli.preflight()
    assert result["provider"] == "codex" and result["cost_target_assessable"] is False
    assert result["model"] == "unit-only-selected-model"
    assert [command[0] for command in commands] == ["docker", "codex"]
    assert commands[-1] == ["codex", "--version"]
    assert result["tool_versions"]["python"] == cli.sys.version.split()[0]
    for package in ("openai", "pydantic", "sqlmodel"):
        assert result["tool_versions"][package] == cli.version(package)
        assert isinstance(result["tool_versions"][package], str)


@pytest.mark.parametrize("name", ["../outside", "/absolute", ".", "a/../.."])
def test_report_comparison_paths_stay_inside_results(tmp_path, monkeypatch, name):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="inside eval/results"):
        cli.result_directory(name)


def test_tier_selection_rejects_unknown_tiers_without_running_anything():
    assert cli.tiers_arg("1,3,4") == {1, 3, 4}
    for value in ("", "0", "5", "build"):
        with pytest.raises(cli.argparse.ArgumentTypeError):
            cli.tiers_arg(value)


@pytest.mark.parametrize("kind", ["missing", "stale_engine", "stale_case", "negative_only", "positive_only"])
def test_oracle_admission_blocks_missing_stale_or_incomplete_selfchecks_before_a_trial(tmp_path, monkeypatch, capsys, kind):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    from eval import hidden

    case = SimpleNamespace(id="unit-only-case", tier=1)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "load_cases", lambda *_: [case])
    monkeypatch.setattr(cli, "oracle_engine_sha256", lambda: "b" * 64)
    monkeypatch.setattr(hidden, "validate_case", lambda _: "a" * 64)
    monkeypatch.setattr(cli, "preflight", lambda: {"tool_versions": {"eda_image_id": "UNIT_ONLY_IMAGE"}})

    def forbidden(*_args, **_kwargs):
        pytest.fail("Invalid oracle admission must stop before a trial or paid work")

    monkeypatch.setattr(cli, "make_output", forbidden)
    monkeypatch.setattr(cli, "freeze", forbidden)
    monkeypatch.setattr(cli.subprocess, "run", forbidden)
    if kind != "missing":
        check = {"status": "pass", "case_sha256": "a" * 64,
                 "positive": {"status": "pass", "passed": 1, "failed": 0, "skipped": 0},
                 "negative": {"status": "fail", "passed": 0, "failed": 1, "skipped": 0}}
        marker = {"schema_version": 1, "oracle_engine_sha256": "b" * 64,
                  "eda_image_id": "UNIT_ONLY_IMAGE", "cases": {case.id: check}}
        if kind == "stale_engine":
            marker["oracle_engine_sha256"] = "c" * 64
        elif kind == "stale_case":
            check["case_sha256"] = "c" * 64
        elif kind == "negative_only":
            check["positive"] = None
        elif kind == "positive_only":
            check["negative"] = None
        (tmp_path / "eval").mkdir()
        (tmp_path / "eval/oracle_checks.json").write_text(json.dumps(marker))
    assert cli.main(["run", "--set", "dev", "--tiers", "1"]) == 2
    assert "Evaluation did not start/complete" in capsys.readouterr().err
