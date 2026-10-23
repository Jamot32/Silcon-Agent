import asyncio
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

import pytest

from app.agent.tools import ToolRunner
from app.packaging import package_design, validate_bundle
from app.schemas import DesignSpec

FIXTURE = Path(__file__).parent / "fixtures/golden_counter"
GOLDEN = Path(__file__).resolve().parents[2] / "designs/golden/counter"


def design_spec() -> DesignSpec:
    return DesignSpec.model_validate({
        "top_module": "counter", "summary": "8-bit up/down counter",
        "ports": [{"name": "clk", "direction": "input", "description": "Clock"}, {"name": "rst_n", "direction": "input", "description": "Reset"}, {"name": "count", "direction": "output", "width": 8, "description": "Count"}],
        "behavior": ["Count up or down when enabled"], "targets": {"clock_mhz": 50.0},
        "test_plan": ["Reset", "Count up", "Count down", "Load and wrap"],
    })


def recorded_runner(tmp_path: Path) -> ToolRunner:
    work = tmp_path / "run/work"
    work.mkdir(parents=True)
    source, output = work / ".eda/recorded/input", work / ".eda/recorded/output"
    shutil.copytree(GOLDEN / "src", source / "src")
    shutil.copytree(GOLDEN / "test", source / "test")
    final = output / "runs/recorded/final"
    for folder, source_file, name in (("gds", "counter.gds", "counter.gds"), ("lef", "counter.lef", "counter.lef"), ("render", "counter.png", "counter.png")):
        (final / folder).mkdir(parents=True)
        shutil.copyfile(FIXTURE / source_file, final / folder / name)
    shutil.copyfile(FIXTURE / "metrics.json", final / "metrics.json")
    shutil.copyfile(FIXTURE / "resolved.json", final.parent / "resolved.json")
    (work / "design.log").write_text("Selected this real golden flow.\n")
    runner = ToolRunner(work, run_id="unit-real-fixture")
    runner.eda._flows["recorded"] = (source, output, "counter")
    return runner


def test_package_uses_selected_snapshot_and_real_outputs(tmp_path):
    runner = recorded_runner(tmp_path)
    (runner.work_dir / "src").mkdir()
    (runner.work_dir / "src/counter.v").write_text("latest unverified edited RTL")
    bundle = asyncio.run(package_design(runner, "recorded", design_spec()))
    validate_bundle(bundle)
    with ZipFile(bundle) as archive:
        assert archive.read("src/counter.v") == (GOLDEN / "src/counter.v").read_bytes()
        assert archive.read("layout/design.gds") == (FIXTURE / "counter.gds").read_bytes()
        assert archive.read("layout/design.lef") == (FIXTURE / "counter.lef").read_bytes()
        assert archive.read("raw_metrics.json") == (FIXTURE / "metrics.json").read_bytes()
        assert "flow_index" not in json.loads(archive.read("metrics.json"))
        metrics = json.loads(archive.read("metrics.json"))
        assert metrics["run_tag"] == "recorded" and metrics["area_um2"] == 1097.3
        assert metrics["drc_ok"] is True and metrics["lvs_ok"] is True
        assert "wrapper" in archive.read("integration_notes.md").decode()
        info = archive.read("info.yaml").decode()
        assert "yaml_version: 6" in info and 'top_module: "counter"' in info
        assert info.count(']": ""') == 24
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["tiny_tapeout_ready"] is False
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


def test_real_lef_fixture_matches_original_provenance():
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    lef = provenance["files"]["counter.lef"]
    data = (FIXTURE / "counter.lef").read_bytes()
    assert lef["bytes"] == len(data)
    assert lef["sha256"] == hashlib.sha256(data).hexdigest()


def test_missing_real_artifact_does_not_produce_a_bundle(tmp_path):
    runner = recorded_runner(tmp_path)
    runner.eda.flow_artifacts("recorded")["gds"].unlink()
    with pytest.raises((KeyError, ValueError)):
        asyncio.run(package_design(runner, "recorded", design_spec()))
    assert not (tmp_path / "run/bundle.zip").exists()


def test_output_symlink_outside_run_rejected(tmp_path):
    runner = recorded_runner(tmp_path)
    path = runner.eda.flow_artifacts("recorded")["gds"]
    path.unlink()
    path.symlink_to(FIXTURE / "counter.gds")
    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(package_design(runner, "recorded", design_spec()))


def test_package_rejects_a_different_design_top(tmp_path):
    runner = recorded_runner(tmp_path)
    mismatched = design_spec().model_copy(update={"top_module": "different_top"})
    with pytest.raises(ValueError, match="does not match"):
        asyncio.run(package_design(runner, "recorded", mismatched))


def test_bundle_identity_must_match_the_selected_run_and_spec(tmp_path):
    runner = recorded_runner(tmp_path)
    original = design_spec()
    bundle = asyncio.run(package_design(runner, "recorded", original))
    validate_bundle(bundle, expected_run_tag="recorded", expected_spec=original)
    with pytest.raises(ValueError, match="selected flow run"):
        validate_bundle(bundle, expected_run_tag="other_flow", expected_spec=original)
    with pytest.raises(ValueError, match="validated design spec"):
        validate_bundle(bundle, expected_run_tag="recorded", expected_spec=original.model_copy(update={"summary": "A different request"}))


@pytest.mark.parametrize("bad_member", ["../outside", "/absolute", "src\\outside"])
def test_bundle_validation_rejects_unsafe_zip_paths(tmp_path, bad_member):
    path = tmp_path / "invalid.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(bad_member, "invalid")
    with pytest.raises(ValueError, match="unsafe"):
        validate_bundle(path)


def test_empty_zip_is_not_a_completed_package(tmp_path):
    path = tmp_path / "empty.zip"
    with ZipFile(path, "w"):
        pass
    with pytest.raises(ValueError, match="missing"):
        validate_bundle(path)
