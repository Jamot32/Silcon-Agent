"""Authentic artifact parsers and mocked transport; no mocked EDA qualifies silicon."""

import asyncio
from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from app.eda import physics
from app.eda.sandbox import CommandResult, MAX_JSON_BYTES
from app.eda.service import EDA

FIXTURE = Path(__file__).parent / "fixtures/mapped_synthesis"
PROVENANCE = json.loads((FIXTURE / "provenance.json").read_text())
CONFIG = json.loads((FIXTURE / "resolved.json").read_text())


def encoded(value):
    return json.dumps(value).encode()


def parse(*, synthesis=None, checker=None, config=None, **expected):
    args = dict(source_sha256=PROVENANCE["source_sha256"], expected_top="chip", expected_sources=["/input/src/chip.v"],
                expected_clock_port="clk", expected_clock_period=40, expected_strategy="AREA 0")
    args.update(expected)
    return physics.parse_mapped_area(synthesis or (FIXTURE / "synthesis_state.json").read_bytes(),
                                     checker or (FIXTURE / "checker_state.json").read_bytes(),
                                     config or (FIXTURE / "resolved.json").read_bytes(), **args)


def geometry():
    lefs = {path: (FIXTURE / name).read_bytes() for path, name in PROVENANCE["tech_lef_fixture_paths"].items()}
    return physics.site_geometry((FIXTURE / "resolved.json").read_bytes(), lefs)


def test_untouched_qualified_state_and_corner_fixtures_retain_their_hashes():
    for name, origin in PROVENANCE["files"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == origin["sha256"]
    mapped = parse()
    assert mapped.area_um2 == Decimal("5245.0304")
    assert mapped.cell_count == 488
    assert mapped.source_sha256 == PROVENANCE["source_sha256"]
    assert mapped.clock_period_ns == 40
    assert mapped.checker_state_sha256 == PROVENANCE["files"]["checker_state.json"]["sha256"]


@pytest.mark.parametrize("key,value", [("design__instance_unmapped__count", 1), ("synthesis__check_error__count", None),
                                      ("synthesis__check_error__count", True), ("design__inferred_latch__count", 1),
                                      ("design__instance__count", 0), ("design__instance__count", 488.0),
                                      ("design__instance__area", "5245.0304"), ("design__instance__area", 0),
                                      ("design__instance__area", True), ("design__instance__area", float("nan"))])
def test_final_checker_requires_positive_mapped_measurements_and_explicit_zero_checks(key, value):
    state = json.loads((FIXTURE / "checker_state.json").read_text())
    if value is None:
        del state["metrics"][key]
    else:
        state["metrics"][key] = value
    with pytest.raises(ValueError):
        parse(checker=encoded(state))


def test_synthesis_state_cannot_be_substituted_for_a_matching_final_checker():
    state = json.loads((FIXTURE / "synthesis_state.json").read_text())
    state["metrics"]["design__instance__area"] += 1
    with pytest.raises(ValueError, match="disagree"):
        parse(synthesis=encoded(state))


@pytest.mark.parametrize("key,value", [("DESIGN_NAME", "other"), ("PDK", "other"), ("STD_CELL_LIBRARY", "other"),
                                      ("VERILOG_FILES", ["/output/model.v"]), ("CLOCK_PORT", None),
                                      ("CLOCK_PERIOD", 41), ("CLOCK_PERIOD", "40"),
                                      ("SYNTH_STRATEGY", "AREA 1"), ("SYNTH_STRATEGY", {})])
def test_resolved_configuration_is_bound_to_requested_top_sources_clock_and_strategy(key, value):
    config = deepcopy(CONFIG)
    config[key] = value
    with pytest.raises(ValueError):
        parse(config=encoded(config))


def test_virtual_clock_is_explicit_and_cannot_match_a_real_port_accidentally():
    config = deepcopy(CONFIG)
    config["CLOCK_PORT"] = None
    assert parse(config=encoded(config), expected_clock_port=None).clock_period_ns == 40
    with pytest.raises(ValueError):
        parse(config=encoded(config))
    with pytest.raises(ValueError, match="plain identifier"):
        parse(expected_clock_port=False)


def test_json_boundary_rejects_duplicate_keys_nonfinite_and_oversized_artifacts():
    for raw in (b'{"x":1,"x":2}', b'{"x":Infinity}', b'{"x":NaN}', b"[]", b" " * (MAX_JSON_BYTES + 1)):
        with pytest.raises(ValueError):
            physics.structured(raw)


def test_all_technology_corners_and_margin_configuration_determine_real_site_geometry():
    site = geometry()
    assert (site.width_um, site.height_um) == (Decimal("0.460"), Decimal("2.720"))
    assert (site.left_sites, site.right_sites, site.bottom_rows, site.top_rows) == (12, 12, 4, 4)
    lefs = {path: (FIXTURE / name).read_bytes() for path, name in PROVENANCE["tech_lef_fixture_paths"].items()}
    with pytest.raises(ValueError, match="Every resolved"):
        physics.site_geometry((FIXTURE / "resolved.json").read_bytes(), dict(list(lefs.items())[:-1]))
    path = next(iter(lefs))
    lefs[path] = lefs[path].replace(b"0.46 BY 2.72", b"0.92 BY 2.72")
    with pytest.raises(ValueError, match="disagrees"):
        physics.site_geometry((FIXTURE / "resolved.json").read_bytes(), lefs)


def test_ambiguous_or_incomplete_site_geometry_is_not_guessed():
    for raw in (b"SITE unithd SIZE 0.46 BY 2.72 ;", b"SITE unithd END unithd",
                b"SITE unithd SIZE 0.46 BY 2.72 ; END unithd SITE unithd SIZE 0.46 BY 2.72 ; END unithd"):
        with pytest.raises(ValueError):
            physics.site_size(raw, "unithd")
    config = deepcopy(CONFIG)
    config["LEFT_MARGIN_MULT"] = True
    lefs = {path: (FIXTURE / name).read_bytes() for path, name in PROVENANCE["tech_lef_fixture_paths"].items()}
    with pytest.raises(ValueError, match="margin"):
        physics.site_geometry(encoded(config), lefs)


def test_actual_mapped_area_reproduces_qualified_plan_without_a_measured_fit_claim():
    with localcontext() as context:
        context.prec = 3
        plan = physics.size_from_mapped_area(parse().area_um2, geometry())
    assert plan.die_area == (0, 0, Decimal("119.140"), Decimal("130.560"))
    assert plan.planned_core_area_um2 >= Decimal("5245.0304") * 100 / 45
    assert plan.planned_utilization_pct <= 45
    assert plan.fits_estimate is True
    assert plan.measured is plan.signoff_clean is plan.tiny_tapeout_ready is False


def test_fixed_footprint_remains_exact_even_when_it_fails_capacity_or_pdn_minimum():
    for die in ([0, 0, 100, 100], [0, 0, 50, 50]):
        plan = physics.size_from_mapped_area(Decimal("5245.0304"), geometry(), fixed_die_area=die)
        assert list(plan.die_area) == die
        assert plan.fits_estimate is False
        assert plan.fixed_footprint is True
        assert plan.recommended_action == "reduce_design_or_request_larger_footprint"


def test_dynamic_plan_is_bounded_and_refuses_excess_capacity_without_faked_pass():
    plan = physics.size_from_mapped_area(1_000_000, geometry())
    assert plan.fits_estimate is False
    assert plan.recommended_action == "reduce_design"
    assert plan.die_area[2] <= 500 and plan.die_area[3] <= 500
    for options in ({"min_die_um": 50}, {"max_die_um": 501}, {"utilization_pct": True}, {"utilization_pct": 0}):
        with pytest.raises(ValueError):
            physics.size_from_mapped_area(100, geometry(), **options)


def prepare_pdk(root):
    for container, name in PROVENANCE["tech_lef_fixture_paths"].items():
        path = root / Path(container).relative_to("/pdk")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE / name, path)


def test_pdk_mapping_rejects_arbitrary_paths_traversal_and_escaping_symlinks(tmp_path):
    pdk = tmp_path / "pdk"
    prepare_pdk(pdk)
    assert len(physics.read_technology_lefs(pdk, (FIXTURE / "resolved.json").read_bytes())) == 3
    for path in ("/etc/passwd", "/pdk/sky130A/libs.ref/sky130_fd_sc_hd/techlef/../../secret.tlef"):
        config = deepcopy(CONFIG)
        config["TECH_LEFS"] = {"nom_*": path}
        with pytest.raises(ValueError, match="authorized"):
            physics.read_technology_lefs(pdk, encoded(config))
    outside = tmp_path / "outside.tlef"
    outside.write_text("not authorized")
    configured = next(iter(CONFIG["TECH_LEFS"].values()))
    path = pdk / Path(configured).relative_to("/pdk")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        physics.read_technology_lefs(pdk, (FIXTURE / "resolved.json").read_bytes())


def test_source_hash_binds_exact_filenames_bytes_and_rejects_symlinks(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    file = source / "generic.v"
    file.write_text("module generic(); endmodule\n")
    first = physics.source_digest(source)
    file.rename(source / "renamed.v")
    assert physics.source_digest(source) != first
    (source / "link.v").symlink_to(source / "renamed.v")
    with pytest.raises(ValueError, match="Unsafe"):
        physics.source_digest(source)


class RecordedMappingTransport:
    """Replays real state formats for host-boundary tests, never real qualification."""
    def __init__(self, pdk_dir, *, status="ok", mutate=None):
        self.pdk_dir = pdk_dir
        self.image = PROVENANCE["image_identity"]["image_id"]
        self.status, self.mutate, self.calls = status, mutate, []

    async def run(self, command, *, input_dir, output_dir, timeout, require_pdk):
        self.calls.append((command, input_dir, output_dir, timeout, require_pdk))
        log = output_dir / "tool.log"
        log.write_text("ERROR: mapping transport control failed\n" if self.status != "ok" else "recorded state transport only\n")
        if self.status == "long_error":
            log.write_text("ERROR: first mapped failure before truncated tail\n" + "later context\n" * 2000)
        if self.status == "cancel":
            raise asyncio.CancelledError
        if self.status != "ok":
            return CommandResult(1, self.status == "timeout", log, log.read_text()[-8192:])
        tag = command[command.index("--run-tag") + 1]
        root = output_dir / "runs" / tag
        request = json.loads((output_dir / "config.json").read_text())
        config = {**CONFIG, **request}
        root.mkdir(parents=True)
        (root / "resolved.json").write_text(json.dumps(config))
        for fixture, directory in [("synthesis_state.json", "06-yosys-synthesis"), ("checker_state.json", "08-checker-yosyssynthchecks")]:
            state = json.loads((FIXTURE / fixture).read_text())
            for key in ("nl", "json_h"):
                state[key] = state[key].replace("map_fceb704c524d4544", tag)
                path = output_dir / Path(state[key]).relative_to("/output")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unit-test transport placeholder; not a measured design\n")
            path = root / directory / "state_out.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(state))
        if self.mutate:
            self.mutate(root, input_dir)
        return CommandResult(0, False, log, log.read_text())


def service(tmp_path, **transport_options):
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src/chip.v").write_text("module chip(input clk, input rst_n, output q); assign q = clk & rst_n; endmodule\n")
    pdk = tmp_path / "pdk"
    prepare_pdk(pdk)
    transport = RecordedMappingTransport(pdk, **transport_options)
    return EDA(work, sandbox=transport), transport


def test_additive_route_binds_snapshot_configuration_timeout_and_artifact_paths(tmp_path):
    eda, transport = service(tmp_path)
    (eda.work_dir / "config.json").write_text(json.dumps({"CLOCK_PERIOD": 40}))
    result = asyncio.run(eda.mapped_synth_stats("chip"))
    assert result["ok"] is True
    assert result["source_sha256"] == physics.source_digest(eda.work_dir / "src")
    assert result["clock_period_ns"] == 40
    command, source, _, timeout, pdk = transport.calls[0]
    assert command[command.index("--to") + 1] == "Checker.YosysSynthChecks"
    assert timeout == 60 and pdk is True and source != eda.work_dir
    assert result["area_estimate"] == 5245.0304 and result["cell_count"] == 488
    assert result["sizing_plan"]["measured"] is False and result["tiny_tapeout_ready"] is False
    restored = physics.SiteGeometry(**result["geometry_observation"])
    assert (restored.width_um, restored.height_um) == (Decimal("0.46"), Decimal("2.72"))
    assert restored.provenance == result["geometry_provenance"]
    assert restored.provenance["config_sha256"] == result["mapped_provenance"]["config_sha256"]
    for key in ("log_path", "stats_path", "results_path"):
        assert not Path(result[key]).is_absolute()
        assert (eda.work_dir / result[key]).is_file()
    assert json.loads((eda.work_dir / result["results_path"]).read_text()) == result


def test_fixed_route_returns_actionable_estimate_failure_without_growth_overrides(tmp_path):
    eda, _ = service(tmp_path)
    result = asyncio.run(eda.mapped_synth_stats("chip", fixed_footprint=True))
    assert result["ok"] is True and result["sizing_plan"]["fits_estimate"] is False
    assert result["sizing_plan"]["die_area"] == [0, 0, 100, 100]
    assert result["planned_config_overrides"] == {}


@pytest.mark.parametrize("status", ["exit", "timeout"])
def test_real_command_failures_have_truthful_json_and_retained_logs(tmp_path, status):
    eda, _ = service(tmp_path, status=status)
    result = asyncio.run(eda.mapped_synth_stats("chip"))
    assert result["ok"] is False and result["area_estimate"] is None
    assert result["timed_out"] is (status == "timeout")
    assert (eda.work_dir / result["log_path"]).is_file()
    assert (eda.work_dir / result["results_path"]).is_file()


def test_corrupt_checker_and_changed_snapshot_are_not_accepted_as_mapping(tmp_path):
    def corrupt(root, source):
        (source / "src/chip.v").write_text("changed during mapping")
    eda, _ = service(tmp_path, mutate=corrupt)
    result = asyncio.run(eda.mapped_synth_stats("chip"))
    assert result["ok"] is False and "changed" in result["error"]
    assert (eda.work_dir / result["stats_path"]).is_file()


def test_failure_preserves_the_first_fatal_line_before_truncated_log_context(tmp_path):
    eda, _ = service(tmp_path, status="long_error")
    result = asyncio.run(eda.mapped_synth_stats("chip"))
    assert result["ok"] is False
    assert result["first_error"] == "ERROR: first mapped failure before truncated tail"
    assert len(result["log_tail"]) <= 2048


def test_mutable_image_and_unknown_overrides_never_spawn_a_command(tmp_path):
    eda, transport = service(tmp_path)
    transport.image = "mutable:tag"
    result = asyncio.run(eda.mapped_synth_stats("chip"))
    assert result["ok"] is False and "immutable" in result["error"]
    assert transport.calls == []
    with pytest.raises(ValueError, match="Only clock period"):
        asyncio.run(eda.mapped_synth_stats("chip", {"TECH_LEFS": "/etc/passwd"}))
    with pytest.raises(ValueError, match="Only clock period"):
        asyncio.run(eda.mapped_synth_stats("chip", []))
    assert transport.calls == []


def test_malformed_final_checker_returns_failure_with_its_actual_artifact_path(tmp_path):
    def corrupt(root, source):
        path = next(root.glob("*-checker-yosyssynthchecks/state_out.json"))
        state = json.loads(path.read_text())
        state["metrics"]["synthesis__check_error__count"] = 1
        path.write_text(json.dumps(state))
    eda, _ = service(tmp_path, mutate=corrupt)
    result = asyncio.run(eda.mapped_synth_stats("chip"))
    assert result["ok"] is False and "synthesis__check_error__count" in result["error"]
    assert (eda.work_dir / result["stats_path"]).is_file()
    assert result["area_estimate"] is None


def test_output_view_escape_cannot_become_a_successful_sizing_result(tmp_path):
    def corrupt(root, source):
        for path in root.glob("*/state_out.json"):
            state = json.loads(path.read_text())
            state["nl"] = "/output/../../secret.v"
            path.write_text(json.dumps(state))
    eda, _ = service(tmp_path, mutate=corrupt)
    result = asyncio.run(eda.mapped_synth_stats("chip"))
    assert result["ok"] is False
    assert "incomplete" in result["error"] or "escapes" in result["error"]


def test_virtual_clock_route_and_cancellation_preserve_the_shared_sandbox(tmp_path):
    eda, transport = service(tmp_path)
    eda.clock_port = None
    result = asyncio.run(eda.mapped_synth_stats("chip"))
    assert result["ok"] is True and result["clock_port"] is None
    assert eda.sandbox is transport
    transport.status = "cancel"
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(eda.mapped_synth_stats("chip"))
