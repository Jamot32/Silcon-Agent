import copy

import pytest
from pydantic import ValidationError

from app.schemas import DesignSpec


def spec_data():
    return {
        "top_module": "counter", "summary": "8-bit counter",
        "ports": [
            {"name": "clk", "direction": "input", "description": "Clock"},
            {"name": "rst_n", "direction": "input", "description": "Synchronous reset"},
            {"name": "count", "direction": "output", "width": 8, "description": "Count"},
        ],
        "behavior": ["Reset to zero synchronously", "Increment when enabled"],
        "targets": {"clock_mhz": 50, "max_area_um2": None, "fit": "tt_1x1_tile"},
        "test_plan": ["Reset", "Normal operation", "Disabled hold", "Overflow"],
    }


def test_sequential_spec_and_explicit_combinational_exception():
    assert DesignSpec.model_validate(spec_data()).ports[2].width == 8
    data = spec_data()
    data["ports"] = data["ports"][2:]
    with pytest.raises(ValidationError, match="require clk"):
        DesignSpec.model_validate(data)
    data["purely_combinational"] = True
    assert DesignSpec.model_validate(data).purely_combinational is True


@pytest.mark.parametrize("name", ["BadTop", "1counter", "a;command", "module", "repeat", "real", "time", "force", "specify"])
def test_invalid_or_reserved_top_is_rejected(name):
    data = spec_data()
    data["top_module"] = name
    with pytest.raises(ValidationError):
        DesignSpec.model_validate(data)


@pytest.mark.parametrize("change", ["duplicate", "clock_output", "reset_bus", "zero_width", "bool_width", "keyword"])
def test_invalid_ports_are_rejected(change):
    data = spec_data()
    if change == "duplicate":
        data["ports"].append(copy.deepcopy(data["ports"][0]))
    elif change == "clock_output":
        data["ports"][0]["direction"] = "output"
    elif change == "reset_bus":
        data["ports"][1]["width"] = 2
    elif change == "keyword":
        data["ports"][2]["name"] = "repeat"
    else:
        data["ports"][2]["width"] = 0 if change == "zero_width" else True
    with pytest.raises(ValidationError):
        DesignSpec.model_validate(data)


@pytest.mark.parametrize("targets", [
    {"clock_mhz": 0.5}, {"clock_mhz": True}, {"clock_mhz": float("nan")},
    {"max_area_um2": 0}, {"max_area_um2": float("inf")}, {"unknown": 1},
    {"fit": "proven_from_stdcell_area"},
])
def test_invalid_targets_are_rejected(targets):
    data = spec_data()
    data["targets"] = targets
    with pytest.raises(ValidationError):
        DesignSpec.model_validate(data)


def test_four_test_plan_entries_are_structural_not_a_coverage_claim():
    data = spec_data()
    data["test_plan"] = ["Reset", "Normal", "Edge"]
    with pytest.raises(ValidationError):
        DesignSpec.model_validate(data)
    data["test_plan"] = ["", "Normal", "Edge", "Overflow"]
    with pytest.raises(ValidationError):
        DesignSpec.model_validate(data)
