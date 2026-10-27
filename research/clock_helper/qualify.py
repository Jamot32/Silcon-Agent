"""Run later, after the provider probe; invokes real pinned-image simulations."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
IMAGE = "sha256:9b62eb4f8e873591f6925c3aaf1f7cf459e848e867809a9068d48d49025f3cc8"
FILES = ["sa_clock.py", "test_clock.py", "fixtures/good/subject.v",
         "fixtures/missing_reset/subject.v", "fixtures/late_update/subject.v"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, output, *, cwd=None):
    started = datetime.now(timezone.utc).isoformat()
    cleanup = None
    try:
        completed = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=60, check=False)
        rc, timed_out = completed.returncode, False
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as error:
        rc, timed_out = None, True
        stdout, stderr = error.stdout or b"", error.stderr or b""
        if "--name" in command:
            name = command[command.index("--name") + 1]
            try:
                stopped = subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, timeout=10, check=False)
                cleanup = {"exit_code": stopped.returncode, "timed_out": False}
            except subprocess.TimeoutExpired:
                cleanup = {"exit_code": None, "timed_out": True}
    (output / "stdout.log").write_bytes(stdout)
    (output / "stderr.log").write_bytes(stderr)
    return {"argv": command, "started_at": started,
            "ended_at": datetime.now(timezone.utc).isoformat(), "exit_code": rc,
            "timed_out": timed_out, "cleanup": cleanup, "stdout_sha256": sha(output / "stdout.log"),
            "stderr_sha256": sha(output / "stderr.log")}


def docker_args(input_dir, output_dir):
    return ["docker", "run", "--rm", "--init", "--name", "sa-clock-research-" + uuid4().hex,
            "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--cpus", "4",
            "--memory", "6g", "--pids-limit", "512", "--user", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/output/home", "-e", "TMPDIR=/output/tmp",
            "-e", "XDG_CACHE_HOME=/output/cache", "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-v", f"{input_dir}:/input:ro", "-v", f"{output_dir}:/output",
            "--mount", f"type=bind,source={input_dir / 'trusted/sa_clock.py'},target=/opt/silicon-python/sa_clock.py,readonly",
            "-w", "/output", IMAGE]


def main():
    if len(sys.argv) != 1 or not os.environ.get("SA_CLOCK_EVIDENCE"):
        raise SystemExit("Set SA_CLOCK_EVIDENCE to a new absolute evidence directory")
    requested = Path(os.environ["SA_CLOCK_EVIDENCE"])
    if not requested.is_absolute():
        raise SystemExit("SA_CLOCK_EVIDENCE must be absolute")
    evidence = requested.resolve()
    if any(character in str(evidence) for character in (",", ":")):
        raise SystemExit("Evidence path cannot contain a comma or colon")
    evidence.mkdir(mode=0o700, parents=False, exist_ok=False)
    manifest = {name: sha(ROOT / name) for name in FILES}
    inspect_dir = evidence / "image_inspect"
    inspect_dir.mkdir()
    inspect = run(["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE], inspect_dir)
    actual_image = (inspect_dir / "stdout.log").read_text().strip()
    if inspect["exit_code"] != 0 or inspect["timed_out"] or actual_image != IMAGE:
        raise SystemExit("Pinned local image absent or image inspection failed; see evidence")
    scenarios = {}
    for name in ("good", "missing_reset", "late_update"):
        root = evidence / name
        source, output = root / "input", root / "output"
        for child in ("src", "test", "trusted"):
            (source / child).mkdir(parents=True, exist_ok=True)
        for child in ("home", "tmp", "cache"):
            (output / child).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / f"fixtures/{name}/subject.v", source / "src/subject.v")
        shutil.copyfile(ROOT / "test_clock.py", source / "test/test_clock.py")
        shutil.copyfile(ROOT / "sa_clock.py", source / "trusted/sa_clock.py")
        prefix = docker_args(source, output)
        probe_dir = root / "origin_probe"
        probe_dir.mkdir()
        probe_code = """import hashlib,importlib.util,json,sys
from pathlib import Path
sys.path.insert(0, '/input/test')
p=Path('/opt/silicon-python/sa_clock.py')
data=p.read_bytes()
try:
    p.write_bytes(b'blocked')
except OSError as error:
    denied=error.errno in (13,30)
else:
    denied=False
print(json.dumps({'origin':importlib.util.find_spec('sa_clock').origin,
                  'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                  'readonly':denied and p.read_bytes()==data}))
"""
        probe = run(prefix + ["python3", "-c", probe_code], probe_dir)
        if probe["exit_code"] != 0 or probe["timed_out"]:
            raise SystemExit(f"{name}: origin probe failed; see evidence")
        origin = json.loads((probe_dir / "stdout.log").read_text())
        if origin != {"origin": "/opt/silicon-python/sa_clock.py", "sha256": manifest["sa_clock.py"], "readonly": True}:
            raise SystemExit(f"{name}: helper origin or bytes mismatch")
        result_dir = root / "simulation"
        result_dir.mkdir()
        invocation = run(prefix + ["python3", "/opt/silicon-agent/runtime.py", "sim", "--top",
                                   "subject", "--test-module", "test_clock"], result_dir)
        if invocation["exit_code"] != 0 or invocation["timed_out"]:
            raise SystemExit(f"{name}: simulator launch or timeout; see evidence")
        actual = json.loads((output / "result.json").read_text())
        xml_path = output / "test_results.xml"
        cases = ET.parse(xml_path).getroot().findall(".//testcase")
        failures = [case.get("name") for case in cases
                    if case.find("failure") is not None or case.find("error") is not None]
        skipped = [case.get("name") for case in cases if case.find("skipped") is not None]
        expected_pass = name == "good"
        if len(cases) != 4 or skipped or actual.get("ok") is not expected_pass:
            raise SystemExit(f"{name}: unexpected test count, skip, or outcome")
        if actual.get("failed") != len(failures) or actual.get("passed") != len(cases) - len(failures):
            raise SystemExit(f"{name}: result JSON and simulator XML disagree")
        if not expected_pass and "test_initial_reset_and_nba_settle" not in failures:
            raise SystemExit(f"{name}: required functional assertion did not reject mutant")
        scenarios[name] = {"origin_probe": probe, "simulation": invocation,
                           "result": actual, "xml_sha256": sha(xml_path),
                           "case_count": len(cases), "failure_cases": failures}
    report = {"image": actual_image, "inputs_sha256": manifest, "inspect": inspect,
              "scenarios": scenarios, "qualification_passed": True,
              "note": "Research fixture only; no pipeline adoption or eval measurement."}
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"qualification_passed": True, "evidence": str(evidence),
                      "report_sha256": sha(evidence / "report.json")}))


if __name__ == "__main__":
    main()
