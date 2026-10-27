"""Offline synthetic tamper controls plus previously closed neutral runs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

import clock_proof as proof

RESEARCH = Path(__file__).resolve().parent
if not os.environ.get("SA_CLOCK_EVIDENCE"):
    raise RuntimeError("Set SA_CLOCK_EVIDENCE to the completed qualification directory")
EVIDENCE = Path(os.environ["SA_CLOCK_EVIDENCE"]).resolve()
REPORT = json.loads((EVIDENCE / "report.json").read_text())
IMAGE = "sha256:9b62eb4f8e873591f6925c3aaf1f7cf459e848e867809a9068d48d49025f3cc8"


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one_file_digest(name, contents):
    return hashlib.sha256(name.encode() + b"\0" + contents + b"\0").hexdigest()


def identity(scenario):
    return {"top": "subject", "test_module": "test_clock", "image_id": IMAGE,
            "source_sha256": proof.flat_digest(RESEARCH, f"fixtures/{scenario}", ".v"),
            "tests_sha256": one_file_digest("test_clock.py", (RESEARCH / "test_clock.py").read_bytes()),
            "helper_sha256": file_sha(RESEARCH / "sa_clock.py")}


class RecordedRuns(unittest.TestCase):
    def test_actual_positive_and_mutants(self):
        for name in ("good", "missing_reset", "late_update"):
            with self.subTest(scenario=name):
                receipt = REPORT["scenarios"][name]["simulation"]
                if name == "good":
                    built = proof.capture(EVIDENCE / name, receipt, identity(name))
                    self.assertTrue(proof.validate(built, EVIDENCE / name, receipt, identity(name)))
                    self.assertEqual(built["counts"], {"passed": 4, "failed": 0, "skipped": 0})
                else:
                    with self.assertRaisesRegex(ValueError, "did not report a clean test pass"):
                        proof.capture(EVIDENCE / name, receipt, identity(name))


class TamperControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "neutral"
        shutil.copytree(EVIDENCE / "good", self.root)
        self.expected = identity("good")
        self.receipt = copy.deepcopy(REPORT["scenarios"]["good"]["simulation"])
        old = str(EVIDENCE / "good")
        self.receipt["argv"] = [arg.replace(old, str(self.root)) for arg in self.receipt["argv"]]
        self.original = proof.capture(self.root, self.receipt, self.expected)

    def tearDown(self):
        self.temporary.cleanup()

    def rejected(self):
        with self.assertRaises((ValueError, OSError)):
            proof.validate(self.original, self.root, self.receipt, self.expected)

    def test_receipt_exit_types_and_timeouts(self):
        for exit_value, timeout in ((False, False), (0.0, False), (None, False), (1, False), (0, True), (0, None)):
            with self.subTest(exit_code=exit_value, timeout=timeout):
                receipt = copy.deepcopy(self.receipt)
                receipt.update(exit_code=exit_value, timed_out=timeout)
                with self.assertRaises(ValueError):
                    proof.capture(self.root, receipt, self.expected)

    def test_changed_identities(self):
        for key, value in (("top", "other"), ("test_module", "other"),
                           ("image_id", "sha256:" + "0" * 64),
                           ("source_sha256", "0" * 64), ("tests_sha256", "0" * 64),
                           ("helper_sha256", "0" * 64)):
            with self.subTest(key=key):
                expected = dict(self.expected, **{key: value})
                with self.assertRaises(ValueError):
                    proof.validate(self.original, self.root, self.receipt, expected)

    def test_changed_source_test_helper_or_logs(self):
        for relative in ("input/src/subject.v", "input/test/test_clock.py", "input/trusted/sa_clock.py",
                         "simulation/stdout.log", "simulation/stderr.log"):
            with self.subTest(path=relative):
                path = self.root / relative
                old = path.read_bytes()
                path.write_bytes(old + b"\nchange")
                self.rejected()
                path.write_bytes(old)

    def test_untrusted_test_helper_shadow(self):
        (self.root / "input/test/sa_clock.py").write_text("# untrusted shadow\n")
        self.rejected()

    def test_missing_and_symlink_artifacts(self):
        for relative in ("output/test_results.xml", "output/result.json", "input/trusted/sa_clock.py"):
            with self.subTest(path=relative):
                path = self.root / relative
                old = path.read_bytes()
                path.unlink()
                self.rejected()
                path.write_bytes(old)
        helper = self.root / "input/trusted/sa_clock.py"
        helper.unlink()
        helper.symlink_to(RESEARCH / "sa_clock.py")
        self.rejected()

    def test_absolute_and_parent_paths_cannot_escape_evidence(self):
        # Resolve the temp parent first: on macOS /var itself is a symlink,
        # which otherwise masks the absolute-path escape under test.
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as name:
            outside = Path(name)
            (outside / "subject.v").write_text("module subject; endmodule\n")
            relative = os.path.relpath(outside, self.root)
            self.assertEqual((self.root / relative).resolve(), outside.resolve())
            for path in (str(outside / "subject.v"), str(Path(relative) / "subject.v")):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    proof.read_regular(self.root, path)
            for directory in (str(outside), relative):
                with self.subTest(directory=directory), self.assertRaises(ValueError):
                    proof.flat_digest(self.root, directory, ".v")

    def test_intermediate_symlink_is_rejected_before_directory_enumeration(self):
        outside = Path(self.temporary.name) / "outside"
        nested = outside / "nested"
        nested.mkdir(parents=True)
        (nested / "subject.v").write_text("module subject; endmodule\n")
        (self.root / "escape").symlink_to(outside, target_is_directory=True)
        with patch.object(Path, "iterdir", side_effect=AssertionError("unexpected enumeration")):
            with self.assertRaisesRegex(ValueError, "[Ss]ymlink"):
                proof.flat_digest(self.root, "escape/nested", ".v")

    def test_invalid_xml_and_counts(self):
        path = self.root / "output/test_results.xml"
        original = path.read_bytes()
        variants = [b"not xml", b"<!DOCTYPE x><testsuites />"]
        for action in ("failure", "error", "skipped", "short", "duplicate", "wrong_class"):
            tree = ET.fromstring(original)
            cases = tree.findall(".//testcase")
            if action in ("failure", "error", "skipped"):
                ET.SubElement(cases[0], action)
            elif action == "short":
                tree.find("testsuite").remove(cases[-1])
            elif action == "duplicate":
                cases[-1].set("name", cases[0].get("name"))
            else:
                cases[0].set("classname", "other")
            variants.append(ET.tostring(tree))
        for index, raw in enumerate(variants):
            with self.subTest(variant=index):
                path.write_bytes(raw)
                self.rejected()
        path.write_bytes(original)
        result_path = self.root / "output/result.json"
        result = json.loads(result_path.read_text())
        for updates in ({"passed": 3}, {"passed": 5}, {"passed": True}, {"failed": 1},
                        {"skipped": 1}, {"ok": False}, {"failures": [{"test": "fake"}]}):
            with self.subTest(result=updates):
                result_path.write_text(json.dumps(dict(result, **updates)))
                self.rejected()

    def test_proof_or_command_tampering(self):
        forged = copy.deepcopy(self.original)
        forged["counts"]["passed"] = 100
        with self.assertRaises(ValueError):
            proof.validate(forged, self.root, self.receipt, self.expected)
        for field in ("--top", "--test-module", "--mount", "--network"):
            with self.subTest(field=field):
                receipt = copy.deepcopy(self.receipt)
                receipt["argv"][receipt["argv"].index(field) + 1] = "bad"
                with self.assertRaises(ValueError):
                    proof.capture(self.root, receipt, self.expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
