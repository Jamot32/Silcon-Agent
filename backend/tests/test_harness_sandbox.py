"""Offline process controls for the optional trusted-helper sandbox route."""
import asyncio
import csv
from datetime import datetime
import io
from pathlib import Path

import pytest

from app.eda import sandbox as module


IMAGE_ID = "sha256:" + "a" * 64


class Process:
    def __init__(self, *, stdout=b"", returncode=0, blocked=False):
        self.stdout = stdout
        self.returncode = None if blocked else returncode
        self.started = asyncio.Event()
        self.done = asyncio.Event()
        self.kills = 0
        self.waits = 0
        self.communications = 0

    async def wait(self):
        self.waits += 1
        self.started.set()
        if self.returncode is None:
            await self.done.wait()
        return self.returncode

    async def communicate(self):
        self.communications += 1
        self.started.set()
        if self.returncode is None:
            await self.done.wait()
        return self.stdout, None

    def kill(self):
        self.kills += 1
        self.returncode = -9
        self.done.set()


def inputs(tmp_path):
    source = tmp_path / "input"
    source.mkdir(parents=True)
    trusted = source / "trusted"
    trusted.mkdir()
    helper = trusted / "sa_tb.py"
    helper.write_text("# controlled helper snapshot\n")
    return source, tmp_path / "output", helper


def prohibit_spawn(monkeypatch):
    async def spawn(*args, **kwargs):
        pytest.fail("Rejected inputs must not create any process")
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)


def accelerate_timeouts(monkeypatch):
    real_wait_for = asyncio.wait_for
    async def bounded(awaitable, timeout):
        return await real_wait_for(awaitable, min(timeout, 0.005))
    monkeypatch.setattr(module.asyncio, "wait_for", bounded)


def test_legacy_route_has_no_helper_mount_or_pythonpath_change(tmp_path, monkeypatch):
    source, output, _ = inputs(tmp_path)
    calls = []
    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process()
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    sandbox = module.DockerSandbox(image="local:legacy", pdk_dir=tmp_path / "pdk", user="123:456")
    result = asyncio.run(sandbox.run(["python3", "trusted-command.py"], input_dir=source, output_dir=output))
    assert result.ok and len(calls) == 1
    argv = calls[0]
    assert "--mount" not in argv
    assert not any("PYTHONPATH" in part or "/opt/silicon-python/sa_tb.py" in part for part in argv)
    assert f"{source}:/input:ro" in argv and f"{output}:/output" in argv
    assert argv[-3:] == ("local:legacy", "python3", "trusted-command.py")
    assert argv[argv.index("--user") + 1] == "123:456"


def test_optional_helper_mount_preserves_a_source_path_with_commas(tmp_path, monkeypatch):
    source, output, helper = inputs(tmp_path / "project,with,commas")
    calls = []
    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process()
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    result = asyncio.run(module.DockerSandbox().run(["true"], input_dir=source, output_dir=output, trusted_test_helper=helper))
    assert result.ok
    argv = calls[0]
    fields = next(csv.reader(io.StringIO(argv[argv.index("--mount") + 1])))
    assert set(fields) == {"type=bind", f"source={helper}", "target=/opt/silicon-python/sa_tb.py", "readonly"}
    assert not any("PYTHONPATH" in part for part in argv)


@pytest.mark.parametrize("invalid", ["wrong_name", "missing", "file_symlink", "parent_symlink", "directory", "traversal"])
def test_helper_must_be_exact_regular_snapshot_before_process_spawn(tmp_path, monkeypatch, invalid):
    source, output, helper = inputs(tmp_path)
    if invalid == "wrong_name":
        helper = source / "trusted" / "other.py"
        helper.write_text("# wrong route\n")
    elif invalid == "missing":
        helper.unlink()
    elif invalid == "file_symlink":
        helper.unlink()
        target = tmp_path / "outside.py"
        target.write_text("# outside\n")
        helper.symlink_to(target)
    elif invalid == "parent_symlink":
        helper.unlink()
        helper.parent.rmdir()
        target = tmp_path / "outside"
        target.mkdir()
        (target / helper.name).write_text("# outside\n")
        helper.parent.symlink_to(target, target_is_directory=True)
    elif invalid == "directory":
        helper.unlink()
        helper.mkdir()
    else:
        helper = source / "trusted" / ".." / "trusted" / "sa_tb.py"
    prohibit_spawn(monkeypatch)
    with pytest.raises(ValueError, match="regular input/trusted/sa_tb.py"):
        asyncio.run(module.DockerSandbox().run(["true"], input_dir=source, output_dir=output, trusted_test_helper=helper))


@pytest.mark.parametrize("overlap", ["identical", "output_inside_input", "input_inside_output", "output_symlink_alias"])
def test_helper_rejects_input_output_alias_or_overlap_before_spawn(tmp_path, monkeypatch, overlap):
    source, output, helper = inputs(tmp_path)
    if overlap == "identical":
        output = source
    elif overlap == "output_inside_input":
        output = source / "writable"
    elif overlap == "input_inside_output":
        output = tmp_path
    else:
        output.symlink_to(source, target_is_directory=True)
    prohibit_spawn(monkeypatch)
    with pytest.raises(ValueError, match="must not overlap"):
        asyncio.run(module.DockerSandbox().run(["true"], input_dir=source, output_dir=output, trusted_test_helper=helper))


def test_pinning_observes_local_id_without_mutating_legacy_sandbox(tmp_path, monkeypatch):
    calls = []
    process = Process(stdout=(IMAGE_ID + "\n").encode())
    async def spawn(*args, **kwargs):
        calls.append(args)
        return process
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    legacy = module.DockerSandbox(image="local:mutable", pdk_dir=tmp_path / "same-pdk", user="987:654")
    pinned, identity = asyncio.run(module.pin_sandbox_image(legacy))
    assert pinned is not legacy and legacy.image == "local:mutable"
    assert pinned.image == IMAGE_ID and pinned.user == legacy.user and pinned.pdk_dir == legacy.pdk_dir
    assert calls == [("docker", "image", "inspect", "--format", "{{.Id}}", "local:mutable")]
    assert identity["reference"] == legacy.image and identity["image_id"] == IMAGE_ID
    assert identity["authority"] == "docker_image_inspect"
    assert datetime.fromisoformat(identity["observed_at"]).utcoffset().total_seconds() == 0
    assert process.kills == 0 and process.communications == 1


@pytest.mark.parametrize("reference", ["-option", "x" * 501])
def test_invalid_image_reference_never_spawns(reference, tmp_path, monkeypatch):
    prohibit_spawn(monkeypatch)
    with pytest.raises(ValueError, match="Invalid EDA image reference"):
        asyncio.run(module.pin_sandbox_image(module.DockerSandbox(image=reference, pdk_dir=tmp_path)))


@pytest.mark.parametrize("stdout,returncode", [(b"", 0), (b"sha256:abc", 0), (("sha256:" + "A" * 64).encode(), 0), ((IMAGE_ID + " extra").encode(), 0), (b"\xff", 0), (IMAGE_ID.encode(), 1)])
def test_inspector_rejects_malformed_or_failed_result(stdout, returncode, tmp_path, monkeypatch):
    process = Process(stdout=stdout, returncode=returncode)
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ValueError, match="immutable EDA image ID"):
        asyncio.run(module.pin_sandbox_image(module.DockerSandbox(pdk_dir=tmp_path)))
    assert process.kills == 0


def test_inspector_launch_failure_has_clear_sanitized_error(tmp_path, monkeypatch):
    async def spawn(*args, **kwargs):
        raise FileNotFoundError("controlled private launch detail")
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ValueError, match="Cannot inspect the local EDA image") as caught:
        asyncio.run(module.pin_sandbox_image(module.DockerSandbox(pdk_dir=tmp_path)))
    assert "private launch detail" not in str(caught.value)


def test_inspector_timeout_kills_and_reaps_child(tmp_path, monkeypatch):
    process = Process(blocked=True)
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    accelerate_timeouts(monkeypatch)
    with pytest.raises(TimeoutError):
        asyncio.run(module.pin_sandbox_image(module.DockerSandbox(pdk_dir=tmp_path)))
    assert process.kills == 1 and process.waits == 1


def test_inspector_cancellation_kills_and_reaps_child(tmp_path, monkeypatch):
    process = Process(blocked=True)
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    async def exercise():
        task = asyncio.create_task(module.pin_sandbox_image(module.DockerSandbox(pdk_dir=tmp_path)))
        await process.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    assert process.kills == 1 and process.waits == 1


@pytest.mark.parametrize("cancel,cleanup_blocked", [(False, False), (False, True), (True, False)])
def test_helper_command_timeout_or_cancel_removes_only_owned_container_and_reaps(tmp_path, monkeypatch, cancel, cleanup_blocked):
    source, output, helper = inputs(tmp_path)
    command = Process(blocked=True)
    cleanup = Process(blocked=cleanup_blocked)
    calls = []
    async def spawn(*args, **kwargs):
        calls.append(args)
        return command if args[1] == "run" else cleanup
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    if not cancel:
        accelerate_timeouts(monkeypatch)
    async def exercise():
        task = asyncio.create_task(module.DockerSandbox().run(["true"], input_dir=source, output_dir=output, trusted_test_helper=helper))
        if cancel:
            await command.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result.timed_out and not result.ok
            if cleanup_blocked:
                assert "cleanup timed out" in result.log_tail
    asyncio.run(exercise())
    container_name = calls[0][calls[0].index("--name") + 1]
    assert calls[1] == ("docker", "rm", "-f", container_name)
    assert len(calls) == 2 and command.kills == 1 and command.waits == 2
    assert cleanup.kills == int(cleanup_blocked)
    assert cleanup.waits == (2 if cleanup_blocked else 1)


def test_cleanup_spawn_failure_still_kills_and_reaps_command(tmp_path, monkeypatch):
    source, output, helper = inputs(tmp_path)
    command = Process(blocked=True)
    async def spawn(*args, **kwargs):
        if args[1] == "run":
            return command
        raise OSError("controlled cleanup launch failure")
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    accelerate_timeouts(monkeypatch)
    result = asyncio.run(module.DockerSandbox().run(["true"], input_dir=source, output_dir=output, trusted_test_helper=helper))
    assert result.timed_out is True and result.ok is False
    assert "cleanup launch failure" in result.log_tail
    assert command.kills == 1 and command.waits == 2
