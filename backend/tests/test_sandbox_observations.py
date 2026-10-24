"""Synthetic subprocess controls: these tests never launch Docker or EDA."""
import asyncio
import math
from types import SimpleNamespace

import pytest

from app.eda import sandbox as sandbox_module
from app.eda.sandbox import CommandObservation, DockerSandbox


IMAGE = "sha256:" + "6" * 64  # Synthetic caller identity, never inspected.
COMMAND = ["python3", "/opt/silicon-agent/runtime.py", "lint", "--top", "unit"]


class SyntheticProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.started = asyncio.Event()
        self.killed = False

    async def wait(self):
        self.started.set()
        if self.returncode is None:
            await asyncio.Event().wait()
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def install_spawn(monkeypatch, process, *, launch_error=False, cleanup_error=False):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("docker", "run"):
            if launch_error:
                raise OSError("SYNTHETIC Docker launch failed")
            kwargs["stdout"].write(b"SYNTHETIC subprocess log\n")
            kwargs["stdout"].flush()
            return process
        assert args[:3] == ("docker", "rm", "-f")
        if cleanup_error:
            raise OSError("SYNTHETIC cleanup launch failed")
        return SyntheticProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls


def directories(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    source.mkdir()
    return source, output


def check_observation(observation, source, output, *, launched, timed_out, returncode):
    assert type(observation) is CommandObservation
    assert observation.command == tuple(COMMAND)
    assert observation.input_dir == source.resolve()
    assert observation.output_dir == output.resolve()
    assert observation.process_launched is launched
    assert observation.result.timed_out is timed_out
    assert observation.result.returncode == returncode
    assert observation.result.log_path == output.resolve() / "tool.log"
    assert math.isfinite(observation.duration_seconds)
    assert observation.duration_seconds >= 0


@pytest.mark.parametrize("returncode", [0, 2])
def test_completion_observes_real_returncode_and_saved_log(tmp_path, monkeypatch, returncode):
    source, output = directories(tmp_path)
    process = SyntheticProcess(returncode)
    calls = install_spawn(monkeypatch, process)
    observations = []
    result = asyncio.run(DockerSandbox(image=IMAGE, completion_callback=observations.append).run(
        COMMAND, input_dir=source, output_dir=output))
    assert len(calls) == len(observations) == 1
    assert observations[0].result is result
    check_observation(observations[0], source, output, launched=True,
                      timed_out=False, returncode=returncode)
    assert result.log_path.read_text() == result.log_tail == "SYNTHETIC subprocess log\n"
    assert result.ok is (returncode == 0)


def test_failed_launch_is_observed_without_claiming_execution(tmp_path, monkeypatch):
    source, output = directories(tmp_path)
    calls = install_spawn(monkeypatch, SyntheticProcess(), launch_error=True)
    observations = []
    result = asyncio.run(DockerSandbox(image=IMAGE, completion_callback=observations.append).run(
        COMMAND, input_dir=source, output_dir=output))
    assert len(calls) == len(observations) == 1
    check_observation(observations[0], source, output, launched=False,
                      timed_out=False, returncode=127)
    assert not result.ok
    assert "Cannot launch Docker: SYNTHETIC Docker launch failed" in result.log_tail
    assert result.log_tail == result.log_path.read_text()


@pytest.mark.parametrize("cleanup_error", [False, True])
def test_timeout_retains_one_launched_observation_even_if_cleanup_cannot_launch(
        tmp_path, monkeypatch, cleanup_error):
    source, output = directories(tmp_path)
    process = SyntheticProcess(None)
    calls = install_spawn(monkeypatch, process, cleanup_error=cleanup_error)
    observations = []
    result = asyncio.run(DockerSandbox(image=IMAGE, completion_callback=observations.append).run(
        COMMAND, input_dir=source, output_dir=output, timeout=0.001))
    assert len(calls) == 2
    assert calls[1][:3] == ("docker", "rm", "-f")
    assert len(observations) == 1  # Cleanup is not a second EDA command.
    assert process.killed
    check_observation(observations[0], source, output, launched=True,
                      timed_out=True, returncode=-9)
    assert not result.ok
    if cleanup_error:
        assert "Docker cleanup could not launch" in result.log_tail


@pytest.mark.parametrize("cleanup_error", [False, True])
def test_cancellation_observes_launched_process_before_reraising(
        tmp_path, monkeypatch, cleanup_error):
    source, output = directories(tmp_path)
    process = SyntheticProcess(None)
    calls = install_spawn(monkeypatch, process, cleanup_error=cleanup_error)
    observations = []

    async def exercise():
        task = asyncio.create_task(DockerSandbox(image=IMAGE, completion_callback=observations.append).run(
            COMMAND, input_dir=source, output_dir=output))
        await process.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert len(calls) == 2
    assert len(observations) == 1
    assert process.killed
    check_observation(observations[0], source, output, launched=True,
                      timed_out=True, returncode=-9)
    assert "SYNTHETIC subprocess log" in observations[0].result.log_tail
    if cleanup_error:
        assert "Docker cleanup could not launch" in observations[0].result.log_tail


def test_optional_callback_preserves_default_docker_argv(tmp_path, monkeypatch):
    source, output = directories(tmp_path)
    calls = install_spawn(monkeypatch, SyntheticProcess())
    monkeypatch.setattr(sandbox_module, "uuid4", lambda: SimpleNamespace(hex="fixed-test-name"))
    observations = []

    async def exercise():
        for callback in (None, observations.append):
            await DockerSandbox(image=IMAGE, user="123:456", completion_callback=callback).run(
                COMMAND, input_dir=source, output_dir=output)

    asyncio.run(exercise())
    assert len(observations) == 1
    assert calls[0] == calls[1]
    args = calls[0]
    assert args[:6] == ("docker", "run", "--rm", "--init", "--name", "silicon-eda-fixed-test-name")
    assert args[-len(COMMAND) - 1:] == (IMAGE, *COMMAND)
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--user") + 1] == "123:456"
    assert "--read-only" in args
    assert f"{source.resolve()}:/input:ro" in args
    assert f"{output.resolve()}:/output" in args
    assert "--mount" not in args
    assert observations[0].command == tuple(COMMAND)  # No Docker/env discovery exposure.


def test_prelaunch_validation_does_not_fabricate_command_observation(tmp_path, monkeypatch):
    source, output = directories(tmp_path)
    calls = install_spawn(monkeypatch, SyntheticProcess())
    observations = []
    with pytest.raises(ValueError, match="Timeout must be positive"):
        asyncio.run(DockerSandbox(image=IMAGE, completion_callback=observations.append).run(
            COMMAND, input_dir=source, output_dir=output, timeout=0))
    assert calls == observations == []
