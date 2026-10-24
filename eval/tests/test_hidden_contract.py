"""Synthetic pointer fixtures only; these tests never run the hidden simulator."""

import hashlib
import json
from pathlib import Path
import sys

import pytest

# Test-only import path: real evaluation children select their frozen app instead.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from eval.contracts import EvalCase
from eval.hidden import candidate_binding, namespaced_reference, validate_case


@pytest.fixture
def unit_reference(tmp_path):
    case_dir = tmp_path / "unit-reference"
    golden = case_dir / "golden"
    golden.mkdir(parents=True)
    source = b"module upstream_unit(input wire a, output wire y); assign y = a; endmodule\n"
    digest = hashlib.sha256(source).hexdigest()
    (golden / "ref.v").write_bytes(source)
    (golden / "test_hidden.py").write_text("# UNIT ONLY: never executed.\n")
    (case_dir / "spec.md").write_text("Unit-only public passthrough contract.")
    (case_dir / "ports.yaml").write_text(json.dumps({
        "top_module": "chip", "ports": [{"name": "a", "direction": "input", "width": 1},
                                             {"name": "y", "direction": "output", "width": 1}],
    }))
    config = {"reference_files": ["golden/ref.v"], "reference_top": "upstream_unit",
              "reference_hashes": {"golden/ref.v": digest},
              "reference_origins": {"golden/ref.v": "unit/upstream.v"}}
    (golden / "oracle.json").write_text(json.dumps(config))
    case = EvalCase(
        id="unit-reference", tier=1, expected_outcome="build", behaviors=["Unit-only behavior."],
        case_dir=case_dir, split="dev", spec_text="Unit-only public passthrough contract.", oracle_kind="differential",
        provenance=[{"source_url": "https://example.invalid/unit-only", "commit": "a" * 40,
                     "path": "unit/upstream.v", "license": "Unit test double", "sha256": digest}],
    )
    return case, config, source


def save_config(case, config):
    (case.case_dir / "golden/oracle.json").write_text(json.dumps(config))


def test_exact_raw_pointer_provenance_is_validated_without_altering_upstream_bytes(unit_reference):
    case, _, source = unit_reference
    files, modules = namespaced_reference(case, "unit_namespace_")
    assert modules == {"upstream_unit": "unit_namespace_upstream_unit"}
    assert "unit_namespace_upstream_unit" in next(iter(files.values()))
    assert (case.case_dir / "golden/ref.v").read_bytes() == source
    assert len(validate_case(case)) == 64


@pytest.mark.parametrize("change", ["raw_bytes", "declared_hash", "missing_origin", "wrong_origin"])
def test_reference_must_match_its_exact_declared_origin_and_hash(unit_reference, change):
    case, config, _ = unit_reference
    if change == "raw_bytes":
        (case.case_dir / "golden/ref.v").write_text("module wrong_unit; endmodule\n")
    elif change == "declared_hash":
        config["reference_hashes"]["golden/ref.v"] = "b" * 64
    elif change == "missing_origin":
        config["reference_origins"] = {}
    else:
        config["reference_origins"]["golden/ref.v"] = "unit/not-the-declared-source.v"
    save_config(case, config)
    with pytest.raises(ValueError, match="provenance"):
        validate_case(case)


@pytest.mark.parametrize("field", ["reference_hashes", "reference_origins"])
def test_unused_pointer_entries_cannot_hide_a_stale_reference_manifest(unit_reference, field):
    case, config, _ = unit_reference
    config[field]["golden/unlisted.v"] = "b" * 64 if field == "reference_hashes" else "unit/unlisted.v"
    save_config(case, config)
    with pytest.raises(ValueError):
        validate_case(case)


def test_reference_symlink_cannot_read_an_external_file(unit_reference, tmp_path):
    case, _, source = unit_reference
    external = tmp_path / "unit-outside.v"
    external.write_bytes(source)
    reference = case.case_dir / "golden/ref.v"
    reference.unlink()
    reference.symlink_to(external)
    with pytest.raises(ValueError, match="Unsafe oracle asset"):
        validate_case(case)


def test_candidate_aliases_are_explicit_and_do_not_change_direction_or_width():
    interface = {"top_module": "canonical_chip", "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "data", "direction": "input", "width": 4},
        {"name": "count", "direction": "output", "width": 4},
    ], "aliases": {"data": ["data_in"], "count": ["q"]}, "allow_top_rename": True}
    actual = {"top_module": "unit_actual_top", "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "data_in", "direction": "input", "width": 4},
        {"name": "q", "direction": "output", "width": 4},
    ]}
    top, names, widths = candidate_binding(interface, actual)
    assert top == "unit_actual_top" and names == {"clk": "clk", "data": "data_in", "count": "q"}
    assert widths == {"clk": 1, "data": 4, "count": 4}
    for bad in ({"name": "q", "direction": "input", "width": 4},
                {"name": "q", "direction": "output", "width": 8}):
        with pytest.raises(ValueError):
            candidate_binding(interface, {**actual, "ports": [*actual["ports"][:2], bad]})


def test_unique_interface_inference_is_opt_in_and_ambiguous_roles_are_never_guessed():
    interface = {"top_module": "chip", "ports": [{"name": "count", "direction": "output", "width": 4}]}
    actual = {"top_module": "unit_actual", "ports": [{"name": "q", "direction": "output", "width": 4}]}
    with pytest.raises(ValueError):
        candidate_binding(interface, actual)
    top, names, _ = candidate_binding({**interface, "infer_unique": True}, actual)
    assert top == "unit_actual" and names == {"count": "q"}
    ambiguous = {**actual, "ports": [*actual["ports"], {"name": "other_q", "direction": "output", "width": 4}]}
    with pytest.raises(ValueError, match="ambiguous"):
        candidate_binding({**interface, "infer_unique": True}, ambiguous)


def test_exact_canonical_port_names_take_precedence_over_aliases():
    interface = {"top_module": "chip", "ports": [
        {"name": "count", "direction": "output", "width": 4},
        {"name": "other", "direction": "output", "width": 4},
    ], "aliases": {"count": ["other"]}, "infer_unique": True}
    actual = {"top_module": "unit_actual", "ports": [
        {"name": "count", "direction": "output", "width": 4},
        {"name": "other", "direction": "output", "width": 4},
    ]}
    _, names, _ = candidate_binding(interface, actual)
    assert names == {"count": "count", "other": "other"}


def test_wider_output_permission_does_not_permit_a_narrower_output():
    interface = {"top_module": "chip", "ports": [{"name": "count", "direction": "output", "width": 4}],
                 "allow_wider_outputs": ["count"]}
    actual = {"top_module": "chip", "ports": [{"name": "count", "direction": "output", "width": 8}]}
    assert candidate_binding(interface, actual)[2] == {"count": 8}
    actual["ports"][0]["width"] = 2
    with pytest.raises(ValueError):
        candidate_binding(interface, actual)


def test_reference_selfcheck_uses_the_canonical_interface_without_candidate_guessing():
    interface = {"top_module": "chip", "ports": [{"name": "q", "direction": "output", "width": 4}]}
    assert candidate_binding(interface, None) == ("chip", {"q": "q"}, {"q": 4})


def test_boolean_port_widths_are_not_valid_integer_metadata(unit_reference):
    case, _, _ = unit_reference
    interface = json.loads((case.case_dir / "ports.yaml").read_text())
    interface["ports"][0]["width"] = True
    (case.case_dir / "ports.yaml").write_text(json.dumps(interface))
    with pytest.raises(ValueError, match="port"):
        validate_case(case)


def test_explicit_public_top_name_is_required_without_rename_permission():
    interface = {"top_module": "chip", "ports": [{"name": "q", "direction": "output", "width": 4}]}
    actual = {"top_module": "different_chip", "ports": interface["ports"]}
    with pytest.raises(ValueError, match="top"):
        candidate_binding(interface, actual)
    assert candidate_binding({**interface, "allow_top_rename": True}, actual)[0] == "different_chip"


def test_actual_boolean_width_is_not_accepted_as_width_one():
    interface = {"top_module": "chip", "ports": [{"name": "q", "direction": "output", "width": 1}]}
    actual = {"top_module": "chip", "ports": [{"name": "q", "direction": "output", "width": True}]}
    with pytest.raises(ValueError, match="interface|port"):
        candidate_binding(interface, actual)


def test_module_words_inside_comments_do_not_become_reference_declarations(unit_reference):
    case, config, source = unit_reference
    source = b"// module imaginary_unit;\n/* module another_imaginary; */\n" + source
    digest = hashlib.sha256(source).hexdigest()
    (case.case_dir / "golden/ref.v").write_bytes(source)
    config["reference_hashes"]["golden/ref.v"] = digest
    case.provenance[0].sha256 = digest
    save_config(case, config)
    _, modules = namespaced_reference(case, "unit_namespace_")
    assert modules == {"upstream_unit": "unit_namespace_upstream_unit"}
