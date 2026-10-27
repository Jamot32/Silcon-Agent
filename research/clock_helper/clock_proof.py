"""Research-only simulator evidence binding, not correctness or attestation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
from xml.etree import ElementTree as ET

VERSION = 1
MODE = "clock_primitives_v1"
LIMIT = 2 * 1024 * 1024
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
IDENTITY_FIELDS = {"top", "test_module", "image_id", "source_sha256", "tests_sha256", "helper_sha256"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _relative_path(value):
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("Unsafe evidence path")
    return path


def read_regular(root, relative):
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Evidence root must be a real directory")
    path = root
    for part in _relative_path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Symlinks are not permitted")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Expected a regular evidence file")
    with path.open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("Evidence file exceeds limit")
    return raw


def flat_digest(root, directory, suffix):
    base = Path(root).absolute()
    directory = _relative_path(directory)
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Source directory missing or unsafe")
    target = base
    for part in directory.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("Symlinks are not permitted")
    if not target.is_dir():
        raise ValueError("Source directory missing or unsafe")
    paths = sorted(target.iterdir())
    if not paths:
        raise ValueError("Source directory empty")
    result = hashlib.sha256()
    for path in paths:
        if path.suffix != suffix or not IDENTIFIER.fullmatch(path.stem):
            raise ValueError("Unexpected source file")
        raw = read_regular(base, f"{directory}/{path.name}")
        result.update(path.name.encode() + b"\0" + raw + b"\0")
    return result.hexdigest()


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON key")
        result[name] = value
    return result


def _json(raw):
    def bad_constant(_):
        raise ValueError("Non-finite JSON")
    try:
        result = json.loads(raw, object_pairs_hook=_object, parse_constant=bad_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("Malformed JSON") from error
    if type(result) is not dict:
        raise ValueError("Expected JSON object")
    return result


def _identity(expected):
    if type(expected) is not dict or set(expected) != IDENTITY_FIELDS:
        raise ValueError("Expected independent complete input identity")
    if not all(type(expected[k]) is str and IDENTIFIER.fullmatch(expected[k]) for k in ("top", "test_module")):
        raise ValueError("Invalid top or test module")
    if type(expected["image_id"]) is not str or not IMAGE.fullmatch(expected["image_id"]):
        raise ValueError("Invalid immutable image identity")
    for key in ("source_sha256", "tests_sha256", "helper_sha256"):
        if type(expected[key]) is not str or not DIGEST.fullmatch(expected[key]):
            raise ValueError("Invalid content identity")


def _single(argv, flag, value):
    return argv.count(flag) == 1 and argv.index(flag) + 1 < len(argv) and argv[argv.index(flag) + 1] == value


def _check_receipt(root, receipt, expected):
    if type(receipt) is not dict or type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 0:
        raise ValueError("Host exit is not integer zero")
    if receipt.get("timed_out") is not False:
        raise ValueError("Host timeout is true or unknown")
    argv = receipt.get("argv")
    if type(argv) is not list or any(type(x) is not str for x in argv):
        raise ValueError("Host command missing or malformed")
    source = str(Path(root).absolute() / "input")
    output = str(Path(root).absolute() / "output")
    helper = source + "/trusted/sa_clock.py"
    mount = f"type=bind,source={helper},target=/opt/silicon-python/sa_clock.py,readonly"
    tail = [expected["image_id"], "python3", "/opt/silicon-agent/runtime.py", "sim",
            "--top", expected["top"], "--test-module", expected["test_module"]]
    if (argv[:2] != ["docker", "run"] or argv[-len(tail):] != tail
            or not _single(argv, "--network", "none") or argv.count("--read-only") != 1
            or not _single(argv, "--mount", mount)
            or argv.count(f"{source}:/input:ro") != 1 or argv.count(f"{output}:/output") != 1):
        raise ValueError("Host command does not bind the required inputs")
    for stream in ("stdout", "stderr"):
        raw = read_regular(root, f"simulation/{stream}.log")
        if receipt.get(f"{stream}_sha256") != digest(raw):
            raise ValueError("Host command log does not match receipt")


def capture(root, receipt, expected):
    """Validate retained inputs and results; expected identity must be host-owned."""
    _identity(expected)
    _check_receipt(root, receipt, expected)
    input_root = Path(root).absolute() / "input"
    observed = {
        "source_sha256": flat_digest(input_root, "src", ".v"),
        "tests_sha256": flat_digest(input_root, "test", ".py"),
        "helper_sha256": digest(read_regular(input_root, "trusted/sa_clock.py")),
    }
    if any(observed[k] != expected[k] for k in observed):
        raise ValueError("Simulator inputs differ from expected identity")
    if not (input_root / "test" / (expected["test_module"] + ".py")).is_file():
        raise ValueError("Selected test module is missing")
    if (input_root / "test/sa_clock.py").exists():
        raise ValueError("Test snapshot shadows trusted helper")

    result_raw = read_regular(root, "output/result.json")
    result = _json(result_raw)
    if result.get("ok") is not True or result.get("failures") != []:
        raise ValueError("Runtime did not report a clean test pass")
    if any(type(result.get(k)) is not int for k in ("passed", "failed", "skipped")):
        raise ValueError("Runtime counts must be integers")
    if result["passed"] < 4 or result["failed"] != 0 or result["skipped"] != 0:
        raise ValueError("Runtime test counts are insufficient or failing")
    xml_raw = read_regular(root, "output/test_results.xml")
    if b"<!DOCTYPE" in xml_raw.upper() or b"<!ENTITY" in xml_raw.upper():
        raise ValueError("XML declarations forbidden")
    try:
        xml = ET.fromstring(xml_raw)
    except ET.ParseError as error:
        raise ValueError("Malformed test XML") from error
    if xml.tag not in {"testsuite", "testsuites"}:
        raise ValueError("Unexpected test XML root")
    cases = xml.findall(".//testcase")
    if len(cases) < 4 or len(cases) > 1000:
        raise ValueError("XML test count outside allowed range")
    names = [(c.get("classname"), c.get("name")) for c in cases]
    if (len(set(names)) != len(names) or any(not name or cls != expected["test_module"] for cls, name in names)
            or any(c.find("failure") is not None or c.find("error") is not None or c.find("skipped") is not None for c in cases)):
        raise ValueError("XML contains missing, duplicate, nonmatching, failed, or skipped cases")
    if len(cases) != result["passed"]:
        raise ValueError("Runtime count and XML disagree")
    proof = {"schema_version": VERSION, "mode": MODE, "identity": dict(expected),
             "counts": {"passed": len(cases), "failed": 0, "skipped": 0},
             "receipt_sha256": digest(canonical(receipt)), "result_sha256": digest(result_raw),
             "xml_sha256": digest(xml_raw), "claim": "retained passing execution and input identity only"}
    proof["proof_sha256"] = digest(canonical(proof))
    return proof


def validate(proof, root, receipt, expected):
    """Rebuild against independent expected identity; never trust proof inputs alone."""
    if type(proof) is not dict or proof != capture(root, receipt, expected):
        raise ValueError("Proof differs from retained evidence")
    return True
