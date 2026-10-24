"""Synthetic host-boundary records only: no command, model or EDA is run."""
import asyncio
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest

from app.agent.evidence import MAX_COMMANDS, MAX_RESULT_BYTES, ToolEvidence
from app.agent.ledger import config_key_diagnostic
from app.eda.sandbox import CommandObservation, CommandResult


SOURCE, INPUTS, OTHER_SOURCE, OTHER_INPUTS = "1" * 64, "2" * 64, "3" * 64, "4" * 64
IMAGE = "sha256:" + "5" * 64  # Explicitly synthetic identity, never inspected/run.


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.evidence = ToolEvidence(self.root, IMAGE)

    def tearDown(self):
        self.temp.cleanup()

    def observation(self, name="one", *, rc=0, launched=True, timeout=False, text="SYNTHETIC UNIT LOG\n"):
        source = self.root / "synthetic-input" / name
        output = self.root / "synthetic-output" / name
        source.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        log = output / "tool.log"
        log.write_text(text)
        return CommandObservation(("synthetic-unit-command", "/input/src/unit.v"), source, output,
                                  CommandResult(rc, timeout, log, text), 0.125, launched)

    def begin(self, tool="run_flow", source=SOURCE, inputs=INPUTS, call_id="synthetic_call"):
        return self.evidence.begin(call_id, tool, source, inputs)

    def view(self, source=SOURCE, inputs=INPUTS):
        return self.evidence.ledger.summary(source_revision=source, input_revision=inputs, relevant_tools=("run_flow",))

    def failed(self):
        context = self.begin()
        self.evidence.observe(self.observation("physical-failure", rc=1, text="ERROR: synthetic placement blocker\n"))
        return self.evidence.finish(context, {"ok": False, "first_diagnostic": {
            "kind": "tool_error", "message": "synthetic placement blocker", "signal": "q", "cycle": 0,
            "expected": 0, "actual": "X"}})["tool_evidence"]

    def test_observed_failure_has_private_result_and_real_fixture_hashes(self):
        metadata = self.failed()
        self.assertTrue(metadata["executed"])
        receipt = metadata["execution_receipt"]
        self.assertEqual(receipt["image_id"], IMAGE)
        for artifact in [metadata["receipt"], receipt["result"], *receipt["artifacts"]]:
            path = self.root / artifact["path"]
            self.assertFalse(Path(artifact["path"]).is_absolute())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        saved_receipt = json.loads((self.root / metadata["receipt"]["path"]).read_text())
        self.assertEqual(saved_receipt, receipt)
        saved = json.loads((self.root / receipt["result"]["path"]).read_text())
        self.assertEqual(saved["commands"][0]["returncode"], 1)
        self.assertEqual(saved["commands"][0]["duration_seconds"], 0.125)
        self.assertEqual(saved["source_revision"], SOURCE)
        primary = self.view()["primary_blocker"]
        self.assertEqual(primary["diagnostic"]["expected"], 0)
        self.assertEqual(primary["diagnostic"]["cycle"], 0)

    def test_schema_rejection_preserves_measured_blocker_and_config_guidance(self):
        original = self.failed()
        context = self.begin()
        metadata = self.evidence.finish(context, {"ok": False, "error": "bad config key"},
            rejection_kind="schema_rejection", rejection_detail=config_key_diagnostic(["PL_TARGET_DENSITY"]))["tool_evidence"]
        self.assertFalse(metadata["executed"])
        self.assertNotIn("execution_receipt", metadata)
        self.assertEqual(self.view()["primary_blocker"]["receipt"]["execution_id"], original["execution_id"])
        repair = self.view()["latest_blocked_repair"]
        self.assertEqual(repair["event"], "schema_rejection")
        self.assertEqual(repair["config_guidance"]["rejected_keys"], ["PL_TARGET_DENSITY"])
        self.assertIn("45 for 45%", repair["config_guidance"]["density_units"])
        self.assertEqual(json.loads((self.root / metadata["result"]["path"]).read_text())["diagnostic"]["code"], "CONFIG_KEYS_NOT_ALLOWED")

    def test_failed_launch_is_infrastructure_attempt_without_executed_receipt(self):
        context = self.begin()
        self.evidence.observe(self.observation(rc=127, launched=False, text="Cannot launch Docker: synthetic unit failure\n"))
        result = self.evidence.finish(context, {"ok": False, "error": "Cannot launch Docker"})
        metadata = result["tool_evidence"]
        self.assertEqual(metadata["event"], "launch_failure")
        self.assertFalse(metadata["executed"])
        self.assertNotIn("execution_receipt", metadata)
        self.assertEqual(metadata["commands"][0]["returncode"], 127)
        self.assertEqual(result["error_kind"], "infrastructure_error")
        self.assertEqual(self.view()["latest_blocked_repair"]["event"], "launch_failure")

    def test_partial_launch_failure_retains_prior_physical_blocker_and_both_logs(self):
        prior = self.failed()
        context = self.begin()
        self.evidence.observe(self.observation("mapped-success"))
        self.evidence.observe(self.observation("flow-not-launched", rc=127, launched=False))
        metadata = self.evidence.finish(context, {"ok": False, "error": "synthetic launch failure"})["tool_evidence"]
        self.assertEqual(metadata["event"], "launch_failure")
        self.assertTrue(metadata["executed"])
        self.assertEqual(len(metadata["execution_receipt"]["artifacts"]), 2)
        self.assertEqual(self.view()["primary_blocker"]["receipt"]["execution_id"], prior["execution_id"])
        self.assertTrue(self.view()["latest_blocked_repair"]["executed"])

    def test_ok_alone_does_not_attest_execution_or_clear_failure(self):
        prior = self.failed()
        metadata = self.evidence.finish(self.begin(), {"ok": True, "bytes": 10})["tool_evidence"]
        self.assertEqual(metadata["event"], "no_execution")
        self.assertNotIn("execution_receipt", metadata)
        self.assertEqual(self.view()["primary_blocker"]["receipt"]["execution_id"], prior["execution_id"])

    def test_real_returncode_overrides_erroneous_ok_and_timeout_is_executed(self):
        context = self.begin()
        self.evidence.observe(self.observation(rc=7, text="ERROR: synthetic observed failure\n"))
        result = self.evidence.finish(context, {"ok": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["tool_evidence"]["outcome"], "failed")
        self.assertIn("synthetic observed failure", result["first_diagnostic"]["message"])
        context = self.begin()
        self.evidence.observe(self.observation("timeout", rc=-9, timeout=True))
        metadata = self.evidence.finish(context, {"ok": False, "error": "Tool timed out"})["tool_evidence"]
        self.assertTrue(metadata["executed"])
        self.assertTrue(metadata["commands"][0]["timed_out"])
        self.assertIn("execution_receipt", metadata)

    def test_zero_exit_with_failed_host_checks_is_an_executed_failure(self):
        context = self.begin("run_tests")
        self.evidence.observe(self.observation("synthetic-xml-failure"))
        metadata = self.evidence.finish(context, {"ok": False, "passed": 3, "failed": 1,
            "first_diagnostic": {"kind": "functional_assertion", "message": "synthetic completed check failed",
                                 "signal": "valid", "expected": 0, "actual": 1}})["tool_evidence"]
        self.assertEqual(metadata["outcome"], "failed")
        self.assertTrue(metadata["executed"])
        self.assertEqual(metadata["commands"][0]["returncode"], 0)
        self.assertIn("execution_receipt", metadata)

    def test_success_only_resolves_matching_tool_source_and_inputs(self):
        self.failed()
        for tool, source, inputs in [("run_tests", SOURCE, INPUTS), ("run_flow", OTHER_SOURCE, INPUTS), ("run_flow", SOURCE, OTHER_INPUTS)]:
            context = self.begin(tool, source, inputs)
            self.evidence.observe(self.observation(tool + source[:1] + inputs[:1]))
            self.evidence.finish(context, {"ok": True})
            self.assertIsNotNone(self.view()["primary_blocker"])
        self.assertEqual(self.view(source=OTHER_SOURCE)["primary_blocker"]["relationship"], "historical_source_revision")
        context = self.begin()
        self.evidence.observe(self.observation("matching-pass"))
        self.evidence.finish(context, {"ok": True})
        self.assertIsNone(self.view()["primary_blocker"])

    def test_interleaved_async_calls_use_separate_contexts(self):
        async def exercise():
            ready = asyncio.Event()
            entered = 0
            async def call(name):
                nonlocal entered
                context = self.begin(call_id=name)
                entered += 1
                if entered == 2:
                    ready.set()
                await ready.wait()
                self.evidence.observe(self.observation(name))
                await asyncio.sleep(0)
                return self.evidence.finish(context, {"ok": True})["tool_evidence"]
            return await asyncio.gather(call("alpha"), call("beta"))
        records = asyncio.run(exercise())
        self.assertNotEqual(records[0]["execution_id"], records[1]["execution_id"])
        for name, record in zip(("alpha", "beta"), records):
            self.assertEqual(record["observed_command_count"], 1)
            self.assertIn(name, record["commands"][0]["original_log_path"])

    def test_reused_original_log_is_copied_at_each_completion(self):
        context = self.begin()
        self.evidence.observe(self.observation("same-output", text="SYNTHETIC first command\n"))
        self.evidence.observe(self.observation("same-output", text="SYNTHETIC second command\n"))
        metadata = self.evidence.finish(context, {"ok": True})["tool_evidence"]
        self.assertEqual(len(metadata["execution_receipt"]["artifacts"]), 2)
        logs = [(self.root / a["path"]).read_text() for a in metadata["execution_receipt"]["artifacts"]]
        self.assertEqual(logs, ["SYNTHETIC first command\n", "SYNTHETIC second command\n"])

    def test_relative_observed_paths_remain_scoped_in_receipt(self):
        context = self.begin(call_id="../../outside")
        observed = self.observation("relative")
        observed.result.log_path = observed.result.log_path.relative_to(self.root)
        relative = CommandObservation(observed.command, observed.input_dir.relative_to(self.root),
                                      observed.output_dir.relative_to(self.root), observed.result,
                                      observed.duration_seconds, observed.process_launched)
        self.evidence.observe(relative)
        metadata = self.evidence.finish(context, {"ok": True})["tool_evidence"]
        self.assertEqual(metadata["outcome"], "passed")
        self.assertEqual(metadata["commands"][0]["output_dir"], "synthetic-output/relative")
        self.assertNotIn("outside", metadata["result"]["path"])

    def test_tampered_host_copy_is_not_a_receipt_and_does_not_clear_prior(self):
        prior = self.failed()
        context = self.begin()
        self.evidence.observe(self.observation("copy-tampered"))
        (self.root / context.commands[0]["log"]["path"]).write_text("TAMPERED synthetic unit bytes")
        metadata = self.evidence.finish(context, {"ok": True})["tool_evidence"]
        self.assertEqual(metadata["event"], "evidence_error")
        self.assertNotIn("execution_receipt", metadata)
        self.assertEqual(self.view()["primary_blocker"]["receipt"]["execution_id"], prior["execution_id"])
        self.assertTrue((self.root / metadata["result"]["path"]).is_file())

    def test_no_symlink_log_or_result_and_no_overwrite(self):
        outside = self.root / "outside-secret"
        outside.write_text("SYNTHETIC outside bytes")
        context = self.begin()
        observation = self.observation("symlink-log")
        observation.result.log_path.unlink()
        observation.result.log_path.symlink_to(outside)
        self.evidence.observe(observation)
        result = self.evidence.finish(context, {"ok": True})
        self.assertEqual(result["tool_evidence"]["event"], "evidence_error")
        self.assertNotIn("execution_receipt", result["tool_evidence"])
        context = self.begin()
        target = self.root / ".evidence/tools" / context.execution_id / "result.json"
        target.symlink_to(outside)
        result = self.evidence.finish(context, {"ok": True})
        self.assertEqual(result["tool_evidence"]["event"], "evidence_error")
        self.assertEqual(outside.read_text(), "SYNTHETIC outside bytes")
        context = self.begin()
        result = self.evidence.finish(context, {"ok": True})
        with self.assertRaises(ValueError):
            self.evidence.finish(context, {"ok": True})

    def test_path_escape_and_directory_symlink_are_rejected(self):
        context = self.begin()
        observation = self.observation("escape")
        observation.result.log_path = self.root.parent / "outside.log"
        self.evidence.observe(observation)
        self.assertEqual(self.evidence.finish(context, {"ok": True})["tool_evidence"]["event"], "evidence_error")
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory)
            (other / ".evidence").symlink_to(self.root)
            with self.assertRaises(OSError):
                ToolEvidence(other, IMAGE).begin("id", "run_flow", SOURCE, INPUTS)

    def test_preexisting_regular_result_is_never_overwritten_and_context_resets(self):
        context = self.begin()
        path = self.root / ".evidence/tools" / context.execution_id / "result.json"
        path.write_text("PREEXISTING SYNTHETIC BYTES")
        metadata = self.evidence.finish(context, {"ok": True})["tool_evidence"]
        self.assertEqual(metadata["event"], "evidence_error")
        self.assertEqual(path.read_text(), "PREEXISTING SYNTHETIC BYTES")
        following = self.begin()
        metadata = self.evidence.finish(following, {"ok": True})["tool_evidence"]
        self.assertEqual(metadata["observed_command_count"], 0)
        self.assertEqual(metadata["event"], "no_execution")

    def test_receipt_collision_fails_closed_without_resolving_prior_blocker(self):
        prior = self.failed()
        context = self.begin()
        self.evidence.observe(self.observation("receipt-collision"))
        path = self.root / ".evidence/tools" / context.execution_id / "receipt.json"
        path.write_text("PREEXISTING SYNTHETIC RECEIPT")
        metadata = self.evidence.finish(context, {"ok": True})["tool_evidence"]
        self.assertEqual(metadata["event"], "evidence_error")
        self.assertNotIn("receipt", metadata)
        self.assertNotIn("execution_receipt", metadata)
        self.assertEqual(path.read_text(), "PREEXISTING SYNTHETIC RECEIPT")
        self.assertEqual(self.view()["primary_blocker"]["receipt"]["execution_id"], prior["execution_id"])

    def test_arbitrary_call_id_never_enters_path_and_oversized_result_is_bounded(self):
        context = self.begin(call_id="../../" + "x" * 10000)
        self.evidence.observe(self.observation("large"))
        metadata = self.evidence.finish(context, {"ok": False, "log_tail": "bulk" * 100000,
            "first_diagnostic": {"kind": "functional_assertion", "message": "preserve synthetic mismatch",
                                 "signal": "valid", "cycle": 0, "expected": 0, "actual": "X"}})["tool_evidence"]
        path = self.root / metadata["result"]["path"]
        saved = json.loads(path.read_text())
        self.assertLessEqual(path.stat().st_size, MAX_RESULT_BYTES)
        self.assertTrue(saved["call_id"].startswith("id-sha256:"))
        self.assertEqual(saved["result"]["first_diagnostic"]["expected"], 0)
        self.assertEqual(saved["result"]["first_diagnostic"]["cycle"], 0)

    def test_command_overflow_fails_closed_without_subset_receipt(self):
        context = self.begin()
        for index in range(MAX_COMMANDS + 1):
            self.evidence.observe(self.observation(str(index)))
        metadata = self.evidence.finish(context, {"ok": True})["tool_evidence"]
        self.assertEqual(metadata["observed_command_count"], MAX_COMMANDS + 1)
        self.assertEqual(metadata["event"], "evidence_error")
        self.assertNotIn("execution_receipt", metadata)

    def test_observation_without_context_ignored_and_callback_failure_is_bounded(self):
        self.evidence.observe(self.observation("outside-context"))
        self.assertFalse((self.root / ".evidence").exists())
        def callback(_metadata):
            raise RuntimeError("synthetic trace callback failure")
        self.evidence = ToolEvidence(self.root, IMAGE, callback)
        context = self.begin()
        self.evidence.observe(self.observation("callback"))
        metadata = self.evidence.finish(context, {"ok": True})["tool_evidence"]
        self.assertEqual(metadata["outcome"], "passed")
        self.assertTrue(metadata["trace_callback_failed"])


if __name__ == "__main__":
    unittest.main()
