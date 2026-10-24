"""Offline planner seams; synthetic receipts never qualify an EDA measurement."""

import asyncio
from copy import deepcopy
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from app.agent import physical
from app.eda.physics import source_digest
from app.schemas import DesignSpec


IMAGE = "sha256:" + "a" * 64
OTHER_IMAGE = "sha256:" + "b" * 64
SOURCE = "module probe(input clk, input rst_n, input d, output reg q);\n" \
         "always @(posedge clk) if (!rst_n) q <= 1'b0; else q <= d;\nendmodule\n"


def design_spec(*, fit=None, combinational=False):
    return DesignSpec(
        top_module="probe", summary="Generic registered bit for planner controls",
        ports=[{"name": name, "direction": direction, "description": name}
               for name, direction in [("clk", "input"), ("rst_n", "input"),
                                       ("d", "input"), ("q", "output")]],
        behavior=["Capture d on each rising edge; synchronously clear q when rst_n is low."],
        test_plan=["Reset", "Zero", "One", "Alternation"],
        targets={"clock_mhz": 50, "fit": fit}, purely_combinational=combinational,
    )


class MappingControl:
    """Pure fake transport to control cache races and failures; no Docker or PDK."""

    def __init__(self, work_dir, *, area=1000, mutate=None, failure=None):
        self.work_dir = work_dir
        self.clock_port = "clk"
        self.sandbox = SimpleNamespace(image=IMAGE)
        self.area, self.mutate, self.failure = area, mutate, failure
        self.calls = []

    async def mapped_synth_stats(self, top, overrides):
        self.calls.append((top, deepcopy(overrides)))
        await asyncio.sleep(0)
        if self.failure is not None:
            return deepcopy(self.failure)
        receipt = {
            "ok": True, "source_sha256": source_digest(self.work_dir / "src"),
            "clock_port": self.clock_port, "clock_period_ns": overrides["CLOCK_PERIOD"],
            "synthesis_strategy": overrides["SYNTH_STRATEGY"],
            "image_identity": {"image_id": self.sandbox.image},
            "area_estimate": self.area, "cell_count": 10,
            "geometry_observation": {
                "width_um": "0.46", "height_um": "2.72", "left_sites": 12,
                "right_sites": 12, "bottom_rows": 4, "top_rows": 4,
                "provenance": {"unit_test_only": "handwritten arithmetic control, not measured"},
            },
            "stats_path": ".eda/control/checker/state_out.json",
            "log_path": ".eda/control/tool.log", "results_path": ".eda/control/mapped_synth.json",
            "tiny_tapeout_ready": False, "physical_signoff": False,
        }
        if self.mutate:
            self.mutate(receipt)
        return receipt


def planner(tmp_path, *, fit=None, area=1000, mutate=None, failure=None, initialized=True):
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src/probe.v").write_text(SOURCE)
    eda = MappingControl(work, area=area, mutate=mutate, failure=failure)
    value = physical.PhysicalPlanner(design_spec(fit=fit), eda)
    if initialized:
        value.image_identity = {"image_id": IMAGE}
    return value, eda


def test_placement_only_variants_reuse_measurement_and_recalculate_the_plan(tmp_path):
    value, eda = planner(tmp_path, area=5245.0304)

    async def scenario():
        initial = await value.prepare("probe", {})
        utilization = await value.prepare("probe", {"FP_CORE_UTIL": 60})
        density = await value.prepare("probe", {"PL_TARGET_DENSITY_PCT": 70})
        fixed = await value.prepare("probe", {"DIE_AREA": [0, 0, 200, 220]})
        assert len(eda.calls) == 1
        assert initial["mapping_reused"] is False
        assert all(item["mapping_reused"] for item in (utilization, density, fixed))
        assert initial["mapping_cache_key"] == fixed["mapping_cache_key"]
        assert utilization["sizing_plan"]["target_utilization_pct"] == "60"
        assert utilization["sizing_plan"]["die_area"] != initial["sizing_plan"]["die_area"]
        assert density["planned_config_overrides"]["PL_TARGET_DENSITY_PCT"] == 70
        assert fixed["planned_config_overrides"]["DIE_AREA"] == [0, 0, 200, 220]

    asyncio.run(scenario())


def test_equal_numeric_clock_periods_share_the_mapping_cache(tmp_path):
    value, eda = planner(tmp_path)

    async def scenario():
        integer = await value.prepare("probe", {"CLOCK_PERIOD": 20})
        floating = await value.prepare("probe", {"CLOCK_PERIOD": 20.0})
        assert floating["mapping_reused"] is True
        assert integer["mapping_cache_key"] == floating["mapping_cache_key"]
        assert len(eda.calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["source", "clock_period", "clock_port", "strategy", "image"])
def test_measurement_inputs_invalidate_cache(tmp_path, change):
    value, eda = planner(tmp_path)

    async def scenario():
        initial = await value.prepare("probe", {})
        requested = {}
        if change == "source":
            (eda.work_dir / "src/probe.v").write_text(SOURCE + "// changed exact source\n")
        elif change == "clock_period":
            requested = {"CLOCK_PERIOD": 10}
        elif change == "clock_port":
            eda.clock_port = None  # Explicit virtual clock, never inferred from a falsey port.
        elif change == "strategy":
            requested = {"SYNTH_STRATEGY": "DELAY 1"}
        else:
            eda.sandbox.image = OTHER_IMAGE
            value.image_identity = {"image_id": OTHER_IMAGE}
        changed = await value.prepare("probe", requested)
        assert changed["mapping_reused"] is False
        assert changed["mapping_cache_key"] != initial["mapping_cache_key"]
        assert len(eda.calls) == 2
        if change == "clock_port":
            assert changed["clock_port"] is None

    asyncio.run(scenario())


@pytest.mark.parametrize("field,bad", [
    ("source_sha256", "0" * 64), ("clock_port", None), ("clock_period_ns", 21),
    ("synthesis_strategy", "AREA 1"), ("image_identity", {"image_id": OTHER_IMAGE}),
])
def test_successful_mapping_receipt_must_match_frozen_request(tmp_path, field, bad):
    value, eda = planner(tmp_path, mutate=lambda receipt: receipt.update({field: bad}))
    with pytest.raises(ValueError, match="receipt differs"):
        asyncio.run(value.prepare("probe", {}))
    assert not value._cache
    assert len(eda.calls) == 1


def test_sandbox_cannot_change_under_an_existing_image_identity(tmp_path):
    value, eda = planner(tmp_path)

    async def scenario():
        await value.prepare("probe", {})
        eda.sandbox.image = OTHER_IMAGE
        with pytest.raises(ValueError, match="image changed"):
            await value.prepare("probe", {})
        assert len(eda.calls) == 1

    asyncio.run(scenario())


def test_queued_cache_hit_rechecks_source_after_waiting_for_lock(tmp_path):
    value, eda = planner(tmp_path)

    async def scenario():
        cached = await value.prepare("probe", {})
        lock = value._locks[cached["mapping_cache_key"]]
        await lock.acquire()
        queued = asyncio.create_task(value.prepare("probe", {}))
        await asyncio.sleep(0)  # Caller has hashed its revision and is waiting on the populated key.
        (eda.work_dir / "src/probe.v").write_text(SOURCE + "// concurrent model edit\n")
        lock.release()
        with pytest.raises(ValueError, match="RTL changed"):
            await queued
        assert len(eda.calls) == 1

    asyncio.run(scenario())


def test_same_revision_concurrent_placement_variants_coalesce_mapping(tmp_path):
    value, eda = planner(tmp_path)

    async def scenario():
        results = await asyncio.gather(*[
            value.prepare("probe", {"FP_CORE_UTIL": util}) for util in (40, 50, 60)
        ])
        assert len(eda.calls) == 1
        assert sum(result["mapping_reused"] is False for result in results) == 1
        assert {result["sizing_plan"]["target_utilization_pct"] for result in results} == {"40", "50", "60"}

    asyncio.run(scenario())


def test_returned_receipt_mutation_does_not_poison_shared_cache(tmp_path):
    value, eda = planner(tmp_path)

    async def scenario():
        first = await value.prepare("probe", {})
        first["geometry_observation"]["width_um"] = "999"
        first["image_identity"]["image_id"] = OTHER_IMAGE
        first["planned_config_overrides"]["DIE_AREA"][2] = 1
        second = await value.prepare("probe", {})
        assert second["geometry_observation"]["width_um"] == "0.46"
        assert second["image_identity"]["image_id"] == IMAGE
        assert second["planned_config_overrides"]["DIE_AREA"][2] >= 100
        assert len(eda.calls) == 1

    asyncio.run(scenario())


def test_real_tool_failure_fields_are_retained_and_failure_is_not_cached(tmp_path):
    failure = {"ok": False, "error": "Mapped synthesis checker failed",
               "first_error": "ERROR: unmapped cell remains", "error_kind": "mapped_synthesis",
               "log_path": ".eda/control/tool.log", "stats_path": ".eda/control/state_out.json",
               "results_path": ".eda/control/mapped_synth.json", "returncode": 1,
               "timed_out": False, "log_tail": "ERROR: unmapped cell remains\n"}
    value, eda = planner(tmp_path, failure=failure)

    async def scenario():
        result = await value.prepare("probe", {})
        assert result == {**failure, "physical_flow_started": False}
        assert not value._cache
        eda.failure = None
        retry = await value.prepare("probe", {})
        assert retry["ok"] is True and retry["mapping_reused"] is False
        assert len(eda.calls) == 2

    asyncio.run(scenario())


def test_fixed_tile_uses_exact_boundary_and_never_claims_tapeout_fit(tmp_path):
    value, eda = planner(tmp_path, fit="tt_1x1_tile", area=5245.0304)
    result = asyncio.run(value.prepare("probe", {}))
    assert result["planned_config_overrides"]["DIE_AREA"] == [0, 0, 161.0, 111.52]
    assert result["footprint_policy"] == "fixed_1x1_boundary_only"
    assert result["sizing_plan"]["fixed_footprint"] is True
    assert result["sizing_plan"]["fits_estimate"] is True
    assert result["tiny_tapeout_ready"] is False
    assert result["footprint_boundary_verified"] is False
    assert result["physical_flow_started"] is False
    assert result["sizing_plan"]["measured"] is False
    assert len(eda.calls) == 1


def test_explicit_inner_tile_rectangle_is_preserved_and_outside_is_rejected(tmp_path):
    value, _ = planner(tmp_path, fit="tt_1x1_tile")

    async def scenario():
        rectangle = [1, 1, 151, 111]
        result = await value.prepare("probe", {"DIE_AREA": rectangle})
        assert result["planned_config_overrides"]["DIE_AREA"] == rectangle
        assert [Decimal(item) for item in result["sizing_plan"]["die_area"]] == rectangle
        for outside in ([0, 0, 162, 111], [0, 0, 161, 112]):
            with pytest.raises(ValueError, match="exceeds the fixed"):
                await value.prepare("probe", {"DIE_AREA": outside})

    asyncio.run(scenario())


def test_capacity_failure_does_not_silently_grow_fixed_tile(tmp_path):
    value, _ = planner(tmp_path, fit="tt_1x1_tile", area=10_000)
    result = asyncio.run(value.prepare("probe", {}))
    assert result["ok"] is False
    assert result["error_kind"] == "sizing_preflight"
    assert result["planned_config_overrides"] == {}
    assert [Decimal(item) for item in result["sizing_plan"]["die_area"]] == [0, 0, 161, Decimal("111.52")]
    assert result["suggested_action"] == "reduce_design_or_request_larger_footprint"
    assert result["physical_flow_started"] is False


@pytest.mark.parametrize("overrides", [
    {"DIE_AREA": [0, 0, 501, 220]}, {"CLOCK_PERIOD": True},
    {"SYNTH_STRATEGY": "custom command"}, {"TECH_LEFS": "/model/chosen/file"},
])
def test_invalid_or_out_of_bounds_overrides_fail_before_mapping(tmp_path, overrides):
    value, eda = planner(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(value.prepare("probe", overrides))
    assert not eda.calls


def test_stored_valid_overrides_merge_without_changing_frozen_logical_contract(tmp_path):
    value, eda = planner(tmp_path)
    (eda.work_dir / "config.json").write_text(json.dumps({"CLOCK_PERIOD": 25, "FP_CORE_UTIL": 40}))
    result = asyncio.run(value.prepare("probe", {"FP_CORE_UTIL": 50}))
    assert eda.calls[0][1]["CLOCK_PERIOD"] == 25
    assert result["planned_config_overrides"]["FP_CORE_UTIL"] == 50
    assert value.spec.targets["clock_mhz"] == 50


def test_uninitialized_or_different_top_cannot_start_measurement(tmp_path):
    value, eda = planner(tmp_path, initialized=False)
    with pytest.raises(ValueError, match="not initialized"):
        asyncio.run(value.prepare("probe", {}))
    value.image_identity = {"image_id": IMAGE}
    with pytest.raises(ValueError, match="frozen logical top"):
        asyncio.run(value.prepare("different", {}))
    assert not eda.calls


def test_initialize_pins_before_measurement_without_running_a_tool(tmp_path, monkeypatch):
    value, eda = planner(tmp_path, initialized=False)
    previous = eda.sandbox
    pinned = SimpleNamespace(image=OTHER_IMAGE)
    calls = []

    async def pin(sandbox):
        calls.append(sandbox)
        return pinned, {"image_id": OTHER_IMAGE, "reference": "test-only:original"}

    monkeypatch.setattr(physical, "pin_sandbox_image", pin)
    asyncio.run(value.initialize())
    assert calls == [previous]
    assert eda.sandbox is pinned
    assert value.image_identity["image_id"] == OTHER_IMAGE
    assert not eda.calls
