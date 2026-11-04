"""Synthetic subprocess controls: these tests never launch Docker or EDA."""
import asyncio
import math
from types import SimpleNamespace

import pytest

from app.agent.evidence import MAX_LOG_BYTES
from app.eda import sandbox as sandbox_module
from app.eda.sandbox import CommandObservation, DockerSandbox, MAX_TOOL_LOG_BYTES, OUTPUT_LIMIT_ERROR, run_runtime


IMAGE = "sha256:" + "6" * 64  # Synthetic caller identity, never inspected.
COMMAND = ["python3", "/opt/silicon-agent/runtime.py", "lint", "--top", "unit"]


class SyntheticStream:
    """Pipe double: queued bytes, then EOF once the process has exited."""

    def __init__(self, process, data):
        self.process = process
        self.data = bytearray(data)

    async def read(self, size):
        self.process.started.set()
        if not self.data:
            await self.process.exited.wait()
        chunk = bytes(self.data[:size])
        del self.data[:size]
        return chunk


class EndlessStream:
    """A tool printing forever: output stops only when its process is killed."""

    def __init__(self, process):
        self.process = process
        self.streamed = 0

    async def read(self, size):
        self.process.started.set()
        await asyncio.sleep(0)
        if self.process.exited.is_set():
            return b""
        self.streamed += size
        return b"y" * size


class SyntheticProcess:
    def __init__(self, returncode=0, output=b"SYNTHETIC subprocess log\n"):
        self.returncode = returncode
        self.started = asyncio.Event()
        self.exited = asyncio.Event()
        if returncode is not None:
            self.exited.set()
        self.killed = False
        self.stdout = SyntheticStream(self, output)

    async def wait(self):
        self.started.set()
        await self.exited.wait()
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.exited.set()


def install_spawn(monkeypatch, process, *, launch_error=False, cleanup_error=False):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("docker", "run"):
            if launch_error:
                raise OSError("SYNTHETIC Docker launch failed")
            assert kwargs["stdout"] is asyncio.subprocess.PIPE
            assert kwargs["stderr"] is asyncio.subprocess.STDOUT
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
    assert args[args.index("--ulimit") + 1] == f"fsize={sandbox_module.MAX_CONTAINER_FILE_BYTES}"
    assert observations[0].command == tuple(COMMAND)  # No Docker/env discovery exposure.


def test_prelaunch_validation_does_not_fabricate_command_observation(tmp_path, monkeypatch):
    source, output = directories(tmp_path)
    calls = install_spawn(monkeypatch, SyntheticProcess())
    observations = []
    with pytest.raises(ValueError, match="Timeout must be positive"):
        asyncio.run(DockerSandbox(image=IMAGE, completion_callback=observations.append).run(
            COMMAND, input_dir=source, output_dir=output, timeout=0))
    assert calls == observations == []


def test_endless_output_is_capped_and_container_removed(tmp_path, monkeypatch):
    source, output = directories(tmp_path)
    process = SyntheticProcess(None)
    process.stdout = EndlessStream(process)
    calls = install_spawn(monkeypatch, process)
    observations = []
    payload = asyncio.run(run_runtime(DockerSandbox(image=IMAGE, completion_callback=observations.append),
                                      "lint", input_dir=source, output_dir=output, top="unit"))
    assert process.stdout.streamed > MAX_TOOL_LOG_BYTES
    assert calls[1] == ("docker", "rm", "-f", calls[0][calls[0].index("--name") + 1])
    assert len(calls) == 2 and process.killed
    log = (output / "tool.log").read_bytes()
    assert log == b"y" * MAX_TOOL_LOG_BYTES + f"\n[{OUTPUT_LIMIT_ERROR}]\n".encode()
    assert len(log) <= MAX_LOG_BYTES  # Still capturable as tool evidence.
    assert len(observations) == 1
    check_observation(observations[0], source, output, launched=True, timed_out=False, returncode=-9)
    assert observations[0].result.output_limit_exceeded is True and not observations[0].result.ok
    assert payload["ok"] is False and payload["timed_out"] is False
    assert payload["error"] == OUTPUT_LIMIT_ERROR and OUTPUT_LIMIT_ERROR in payload["log_tail"]


def test_container_removal_keeps_reading_the_client_pipe(tmp_path, monkeypatch):
    """Docker's attach stream stalls `rm -f` until the client's unread pipe is drained."""
    source, output = directories(tmp_path)
    process = SyntheticProcess(None)
    process.stdout = EndlessStream(process)
    install_spawn(monkeypatch, process)
    spawn = asyncio.create_subprocess_exec
    removal = SyntheticProcess(None)  # Finishes once the client pipe is read again, or when killed.

    async def spawn_stalled(*args, **kwargs):
        result = await spawn(*args, **kwargs)
        if args[:3] == ("docker", "rm", "-f"):
            return removal
        return result

    endless_read = process.stdout.read
    async def read(size):
        if removal.started.is_set() and not removal.exited.is_set():
            removal.returncode = 0
            removal.exited.set()
        return await endless_read(size)

    process.stdout.read = read
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn_stalled)
    result = asyncio.run(DockerSandbox(image=IMAGE).run(COMMAND, input_dir=source, output_dir=output))
    assert result.output_limit_exceeded and removal.returncode == 0 and process.killed
    assert b"cleanup timed out" not in result.log_path.read_bytes()


def test_output_exactly_at_cap_is_kept_whole(tmp_path, monkeypatch):
    source, output = directories(tmp_path)
    data = b"z" * MAX_TOOL_LOG_BYTES
    calls = install_spawn(monkeypatch, SyntheticProcess(0, data))
    result = asyncio.run(DockerSandbox(image=IMAGE).run(COMMAND, input_dir=source, output_dir=output))
    assert result.ok and not result.output_limit_exceeded and len(calls) == 1
    assert result.log_path.read_bytes() == data
