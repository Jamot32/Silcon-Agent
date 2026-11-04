import asyncio
from pathlib import Path

import pytest

from app.eda.flow import validate_flow_overrides
from app.eda.render import render_layout
from app.eda.sandbox import CommandResult, DockerSandbox, MAX_CONTAINER_FILE_BYTES, MAX_JSON_BYTES, log_tail, read_json_artifact, run_runtime, safe_artifact
from app.eda.service import EDA, validate_identifier


@pytest.mark.parametrize("overrides", [
    {"PDK": "other"}, {"CLOCK_PERIOD": True}, {"CLOCK_PERIOD": 0},
    {"CLOCK_PERIOD": float("inf")}, {"FP_CORE_UTIL": 99},
    {"PL_TARGET_DENSITY_PCT": "45"}, {"DIE_AREA": [0, 0, 10, 100]},
    {"DIE_AREA": [0, 0, 100, float("nan")]}, {"SYNTH_STRATEGY": "AREA 99"},
])
def test_config_rejects_unknown_and_unsafe_values(overrides):
    with pytest.raises(ValueError):
        validate_flow_overrides(overrides)


def test_config_allows_only_real_pinned_names():
    values = {"CLOCK_PERIOD": 20, "FP_CORE_UTIL": 40, "PL_TARGET_DENSITY_PCT": 45, "DIE_AREA": [0, 0, 100, 100], "SYNTH_STRATEGY": "AREA 0"}
    assert validate_flow_overrides(values) == values


@pytest.mark.parametrize("name", ["../counter", "counter; shell", "counter.v", "counter,other", "-bad"])
def test_identifiers_cannot_be_paths_or_command_fragments(name):
    with pytest.raises(ValueError):
        validate_identifier(name)


def test_output_links_must_stay_inside_output(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    original = root / "real.json"
    original.write_text("{}")
    (root / "internal.json").symlink_to(original)
    assert safe_artifact(root, root / "internal.json") == original
    outside = tmp_path / "private.txt"
    outside.write_text("private")
    (root / "escape.json").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        safe_artifact(root, root / "escape.json")


def test_log_tail_is_bounded_and_never_reads_escape(tmp_path):
    log = tmp_path / "tool.log"
    log.write_text("A" * 9000)
    tail = log_tail(tmp_path, log)
    assert tail.startswith("[truncated;")
    assert tail.count("A") == 8192
    log.unlink()
    log.symlink_to(tmp_path.parent / "outside")
    with pytest.raises(ValueError):
        log_tail(tmp_path, log)


def test_runtime_results_reject_container_created_symlink(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    outside = tmp_path / "private.json"
    outside.write_text('{"secret":"do not read"}')

    class MaliciousResult:
        async def run(self, *args, **kwargs):
            (output / "result.json").symlink_to(outside)
            return CommandResult(0, False, output / "tool.log", "")

    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(run_runtime(MaliciousResult(), "sim", input_dir=source, output_dir=output, top="counter"))


def test_structured_artifacts_are_bounded_before_parsing(tmp_path):
    path = tmp_path / "result.json"
    path.write_bytes(b" " * (MAX_JSON_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        read_json_artifact(tmp_path, path)


@pytest.mark.parametrize("number", ["Infinity", "NaN", "1e999"])
def test_runtime_json_rejects_nonfinite_numbers(tmp_path, number):
    path = tmp_path / "result.json"
    path.write_text('{"value":' + number + '}')
    with pytest.raises(ValueError, match="Non-finite"):
        read_json_artifact(tmp_path, path, finite=True)


def test_snapshot_rejects_source_symlink(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/counter.v").symlink_to(tmp_path.parent / "outside.v")
    with pytest.raises(ValueError):
        EDA(tmp_path)._snapshot("lint")


def test_render_rejects_symlink_before_read(tmp_path):
    path = tmp_path / "runs/flow_1/final/render/counter.png"
    path.parent.mkdir(parents=True)
    path.symlink_to(tmp_path.parent / "outside.png")
    with pytest.raises(ValueError):
        render_layout(tmp_path, "flow_1", "counter", "run")


def test_sandbox_timeout_kills_container_and_enforces_limits(tmp_path, monkeypatch):
    calls = []

    class Process:
        def __init__(self, returncode=None):
            self.returncode = returncode
            self.exited = asyncio.Event()
            self.stdout = self  # Pipe double: EOF only after the process exits.

        async def read(self, size):
            if self.returncode is None:
                await self.exited.wait()
            return b""

        async def wait(self):
            if self.returncode is None:
                await self.exited.wait()
            return self.returncode

        def kill(self):
            self.returncode = -9
            self.exited.set()

    process = Process()

    async def spawn(*args, **kwargs):
        calls.append(args)
        if args[1] == "run":
            return process
        return Process(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    source = tmp_path / "input"
    source.mkdir()
    result = asyncio.run(DockerSandbox().run(["sleep", "10"], input_dir=source, output_dir=tmp_path / "output", timeout=0.01))
    assert result.timed_out
    assert not result.ok
    command = calls[0]
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "6g"
    assert command[command.index("--cpus") + 1] == "4"
    assert command[command.index("--pids-limit") + 1] == "512"
    assert "--read-only" in command
    assert command[command.index("--ulimit") + 1] == f"fsize={MAX_CONTAINER_FILE_BYTES}"
    assert f"{source.resolve()}:/input:ro" in command
    assert calls[1][:4] == ("docker", "rm", "-f", command[command.index("--name") + 1])
