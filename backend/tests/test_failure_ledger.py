"""Authored pure boundary controls, not evidence of any hardware/tool run."""
import json
import unittest

from app.agent.ledger import Artifact, ExecutionReceipt, FailureLedger, MAX_HISTORY, MAX_PENDING, config_key_diagnostic, format_failure


SOURCE, INPUTS, OTHER_SOURCE, OTHER_INPUTS = "1"*64, "2"*64, "3"*64, "4"*64


def receipt(name="actual_1", tool="run_flow", source=SOURCE, inputs=INPUTS):
    # Deliberately synthetic pure-test records. No paths are read or executed.
    return ExecutionReceipt(name, tool, source, inputs, "sha256:"+"5"*64,
                            Artifact(f"synthetic/{name}/result.json", "6"*64),
                            (Artifact(f"synthetic/{name}/tool.log", "7"*64),), True)


def view(ledger, source=SOURCE, inputs=INPUTS, tools=("run_flow",), by_tool=None):
    return ledger.summary(source_revision=source, input_revision=inputs, relevant_tools=tools,
                          current_input_revisions_by_tool=by_tool)


def reject(ledger, name="rejected", tool="run_flow", source=SOURCE, inputs=INPUTS, **kwargs):
    ledger.record_rejection(call_id=name, tool=tool, source_revision=source, input_revision=inputs,
                            kind="schema_rejection", detail=config_key_diagnostic(["PL_TARGET_DENSITY"]), **kwargs)


class LedgerTests(unittest.TestCase):
    def test_rejected_config_keeps_actual_blocker_and_both_diagnostics(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"kind":"tool_error", "message":"Authored placement blocker control", "actual":0})
        reject(ledger, tool="write_file", relevant_to=("run_flow",))
        result = view(ledger)
        self.assertEqual(result["primary_blocker"]["receipt"]["execution_id"], "actual_1")
        self.assertEqual(result["primary_blocker"]["diagnostic"]["actual"], 0)
        self.assertFalse(result["latest_blocked_repair"]["executed"])
        text = format_failure(result)
        self.assertIn("Authored placement blocker control", text)
        self.assertIn("Rejected config keys: PL_TARGET_DENSITY", text)
        self.assertIn("PL_TARGET_DENSITY_PCT", text)
        self.assertIn("45 for 45%", text)
        self.assertIn("tool did not execute", text)
        self.assertIn("synthetic/actual_1/result.json", text)

    def test_ok_dictionary_is_never_an_execution_receipt(self):
        ledger = FailureLedger()
        for value in ({"ok":True}, {"ok":False,"log_path":"output/log"}, None):
            with self.assertRaises(ValueError):
                ledger.record_execution(value, "passed")
        with self.assertRaises(ValueError):
            ExecutionReceipt("id", "run_flow", SOURCE, INPUTS, "sha256:"+"5"*64,
                             Artifact("result.json", "6"*64), (Artifact("tool.log", "7"*64),), False)
        self.assertIsNone(view(ledger)["primary_blocker"])

    def test_only_exact_tool_and_revisions_resolve(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"message":"actual flow failure control"})
        for other in (receipt("other_tool",tool="run_tests"), receipt("other_source",source=OTHER_SOURCE), receipt("other_inputs",inputs=OTHER_INPUTS)):
            ledger.record_execution(other, "passed")
            self.assertEqual(view(ledger)["unresolved_count"], 1)
        reject(ledger)
        ledger.record_execution(receipt("matching_success"), "passed")
        result = view(ledger)
        self.assertIsNone(result["primary_blocker"])
        self.assertEqual(result["unresolved_count"], 0)
        self.assertEqual(result["latest_blocked_repair"]["superseded_by_success"], "matching_success")
        self.assertEqual(result["history"][-1]["resolved_execution_ids"], ["actual_1"])

    def test_old_rtl_failure_is_explicitly_historical(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"message":"old source failure control"})
        result = view(ledger, source=OTHER_SOURCE)
        self.assertEqual(result["primary_blocker"]["relationship"], "historical_source_revision")
        text = format_failure(result)
        self.assertIn("Historical blocker from earlier RTL revision", text)
        self.assertNotIn("Measured blocker for current snapshot", text)

    def test_changed_configuration_is_earlier_inputs_same_source(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"message":"old config failure control"})
        self.assertEqual(view(ledger, inputs=OTHER_INPUTS)["primary_blocker"]["relationship"], "earlier_inputs_same_source")

    def test_subsequent_lint_inputs_do_not_relabel_unchanged_flow(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt("flow"), "failed", {"message": "flow blocker"})
        ledger.record_execution(receipt("lint", tool="lint", inputs=OTHER_INPUTS), "passed")
        result = view(ledger, inputs=OTHER_INPUTS, tools=("lint", "run_flow"),
                      by_tool={"lint": OTHER_INPUTS, "run_flow": INPUTS})
        self.assertEqual(result["primary_blocker"]["receipt"]["execution_id"], "flow")
        self.assertEqual(result["primary_blocker"]["relationship"], "current_snapshot")
        self.assertEqual(result["unresolved_count"], 1)  # Reporting never resolves a failure.

    def test_current_tool_specific_failure_precedes_newer_changed_inputs(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt("current_flow"), "failed", {"message": "current flow blocker"})
        ledger.record_execution(receipt("old_lint", tool="lint"), "failed", {"message": "old lint blocker"})
        result = view(ledger, tools=("lint", "run_flow"),
                      by_tool={"lint": OTHER_INPUTS, "run_flow": INPUTS})
        self.assertEqual(result["primary_blocker"]["receipt"]["execution_id"], "current_flow")
        self.assertEqual(result["primary_blocker"]["relationship"], "current_snapshot")

    def test_changed_flow_config_uses_flow_hash_instead_of_lint_fallback(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt("old_config"), "failed", {"message": "old config blocker"})
        result = view(ledger, tools=("lint", "run_flow"),
                      by_tool={"lint": INPUTS, "run_flow": OTHER_INPUTS})
        self.assertEqual(result["primary_blocker"]["relationship"], "earlier_inputs_same_source")
        self.assertEqual(result["unresolved_count"], 1)

    def test_tool_specific_inputs_do_not_make_old_source_current(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"message": "old source blocker"})
        reject(ledger, tool="write_file", relevant_to=("run_flow",))
        result = view(ledger, source=OTHER_SOURCE, inputs=OTHER_INPUTS,
                      by_tool={"run_flow": INPUTS, "write_file": INPUTS})
        self.assertEqual(result["primary_blocker"]["relationship"], "historical_source_revision")
        self.assertEqual(result["latest_blocked_repair"]["relationship"], "historical_source_revision")

    def test_rejection_compares_its_own_tool_even_when_relevant_to_flow(self):
        ledger = FailureLedger()
        reject(ledger, tool="write_file", relevant_to=("run_flow",))
        current = view(ledger, inputs=OTHER_INPUTS,
                       by_tool={"run_flow": OTHER_INPUTS, "write_file": INPUTS})
        self.assertEqual(current["latest_blocked_repair"]["relationship"], "current_snapshot")
        changed = view(ledger, by_tool={"run_flow": INPUTS, "write_file": OTHER_INPUTS})
        self.assertEqual(changed["latest_blocked_repair"]["relationship"], "earlier_inputs_same_source")

    def test_tool_revision_map_is_bounded_validated_and_missing_keys_use_fallback(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"message": "unchanged blocker"})
        for mapping in ([], {"run_flow": "invalid"}, {"run_flow": True}, {"bad/tool": INPUTS},
                        {f"tool_{n}": INPUTS for n in range(33)}):
            with self.assertRaises(ValueError):
                view(ledger, by_tool=mapping)
        for mapping in ({}, {"lint": OTHER_INPUTS}):
            result = view(ledger, by_tool=mapping)
            self.assertEqual(result["primary_blocker"]["relationship"], "current_snapshot")

    def test_current_failure_preferred_to_more_recent_historical_failure(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt("current"), "failed", {"message":"current blocker"})
        ledger.record_execution(receipt("old",source=OTHER_SOURCE), "failed", {"message":"old blocker"})
        self.assertEqual(view(ledger)["primary_blocker"]["receipt"]["execution_id"], "current")

    def test_policy_spam_cannot_evict_actual_primary_blocker(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"message":"keep actual blocker"})
        for n in range(100):
            reject(ledger, name=f"denied_{n}")
        result = view(ledger)
        self.assertEqual(result["primary_blocker"]["receipt"]["execution_id"], "actual_1")
        self.assertEqual(result["latest_blocked_repair"]["call_id"], "denied_99")
        self.assertEqual(len(result["history"]), MAX_HISTORY)
        self.assertEqual(result["history_omitted_count"], 69)

    def test_unresolved_actual_records_are_bounded_and_omission_honest(self):
        ledger = FailureLedger()
        for n in range(50):
            ledger.record_execution(receipt(f"run_{n}"), "failed", {"message":"failed control"})
        result = view(ledger)
        self.assertEqual(result["unresolved_count"], MAX_PENDING)
        self.assertEqual(result["omitted_failure_records"], 34)
        self.assertEqual(result["primary_blocker"]["receipt"]["execution_id"], "run_49")
        self.assertIn("34 older failure records omitted", format_failure(result))
        ledger.record_execution(receipt("pass"), "passed")
        self.assertIsNone(view(ledger)["primary_blocker"])

    def test_artifact_identities_strict_and_safe(self):
        for path in ("/tmp/log", "../log", "out/../log", "out//log", "out/./log", "out\\log", "out/\x00log"):
            with self.assertRaises(ValueError): Artifact(path, "0"*64)
        with self.assertRaises(ValueError): Artifact("out/log", "bad_hash")
        with self.assertRaises(ValueError): receipt(source="unverified-label")

    def test_structured_zero_and_diagnostic_bounds_survive(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"kind":"functional_assertion", "message":"m"*20_000,
                                                        "phase":"after", "signal":"q", "cycle":0, "expected":0, "actual":"X"*20_000})
        result = view(ledger)
        d = result["primary_blocker"]["diagnostic"]
        self.assertEqual((d["cycle"], d["expected"]), (0,0))
        self.assertLessEqual(len(d["message"].encode()), 1200)
        self.assertLessEqual(len(d["actual"].encode()), 240)
        self.assertLessEqual(len(format_failure(result).encode()), 4200)

    def test_returned_summary_cannot_mutate_ledger(self):
        ledger = FailureLedger()
        ledger.record_execution(receipt(), "failed", {"message":"retain"})
        result = view(ledger); result["primary_blocker"]["diagnostic"]["message"] = "tampered"
        result["history"].clear()
        self.assertEqual(view(ledger)["primary_blocker"]["diagnostic"]["message"], "retain")
        self.assertEqual(len(view(ledger)["history"]), 1)

    def test_unrelated_stage_rejection_is_not_reported_as_flow_repair(self):
        ledger = FailureLedger()
        reject(ledger,tool="run_tests")
        self.assertIsNone(view(ledger)["latest_blocked_repair"])

    def test_config_key_formatter_exact_names_allowlist_units_and_limits(self):
        d = config_key_diagnostic(["FOO", "PL_TARGET_DENSITY", "FOO"])
        self.assertEqual(d["rejected_keys"], ["FOO", "PL_TARGET_DENSITY"])
        self.assertEqual(d["allowed_keys"], ["CLOCK_PERIOD", "DIE_AREA", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT", "SYNTH_STRATEGY"])
        self.assertIn("1 to 90", d["density_units"])
        self.assertLessEqual(len(json.dumps(config_key_diagnostic(["X"*200+str(n) for n in range(128)])).encode()), 4500)
        with self.assertRaises(ValueError): config_key_diagnostic(["PL_TARGET_DENSITY_PCT"])
        with self.assertRaises(ValueError): config_key_diagnostic([])


if __name__ == "__main__":
    unittest.main()
