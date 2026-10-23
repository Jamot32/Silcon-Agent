import ast
import asyncio
import difflib
import hashlib
import json
import os
import re
import stat
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.eda.flow import validate_flow_overrides
from app.eda.service import EDA
from app.llm.types import ToolCall, ToolDefinition

MAX_WRITE_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 8 * 1024
TOOL_TIMEOUT_SECONDS = 60
FLOW_TIMEOUT_SECONDS = 900
_FLOW_SEMAPHORE = asyncio.Semaphore(3)
_IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]*$"
_RUN_TAG = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class _Write(_Args):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=MAX_WRITE_BYTES)


class _Read(_Args):
    path: str = Field(min_length=1, max_length=1024)


class _Top(_Args):
    top: str = Field(pattern=_IDENTIFIER, max_length=128)


class _Tests(_Top):
    test_module: str = Field(pattern=_IDENTIFIER, max_length=128)


class _Flow(_Top):
    config_overrides: dict[str, JsonValue] = Field(default_factory=dict)


class _Report(_Args):
    run_tag: str = Field(pattern=_RUN_TAG)
    kind: Literal["timing", "area", "power", "drc"]


class _Render(_Args):
    run_tag: str = Field(pattern=_RUN_TAG)


class _Note(_Args):
    text: str = Field(min_length=1, max_length=MAX_OUTPUT_BYTES)


class _Finish(_Args):
    summary: str = Field(min_length=1, max_length=MAX_OUTPUT_BYTES)
    best_run_tag: str | None = Field(default=None, pattern=_RUN_TAG)


_TOOLS: dict[str, tuple[type[_Args], str]] = {
    "write_file": (_Write, "Write src/*.v, test/*.py, or allowlisted flow overrides in config.json."),
    "read_file": (_Read, "Read a file inside the run working directory; long output is truncated."),
    "list_files": (_Args, "List files inside the run working directory."),
    "lint": (_Top, "Lint synthesizable Verilog using Verilator."),
    "run_tests": (_Tests, "Run cocotb tests with the real simulator."),
    "synth_stats": (_Top, "Run Yosys synthesis and return real cell and area statistics."),
    "run_flow": (_Flow, "Run the real sky130 physical-design flow; at most six attempts per run."),
    "read_report": (_Report, "Read an existing physical-design report."),
    "render_layout": (_Render, "Render an existing real GDS layout."),
    "record_note": (_Note, "Append a design hypothesis or observation to the run log."),
    "finish": (_Finish, "Propose a final summary and an existing best flow tag; the orchestrator decides completion."),
}


def tool_definitions(names: set[str] | None = None) -> list[ToolDefinition]:
    if names is not None and names - _TOOLS.keys():
        raise ValueError("Unknown tool requested")
    return [ToolDefinition(name=name, description=description, parameters=model.model_json_schema())
            for name, (model, description) in _TOOLS.items() if names is None or name in names]


def _tail(text: str, limit: int = MAX_OUTPUT_BYTES) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return f"[truncated {len(raw)} bytes; showing tail]\n" + raw[-limit:].decode("utf-8", errors="replace")


def _bounded_result(result: dict[str, JsonValue]) -> dict[str, JsonValue]:
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) <= MAX_OUTPUT_BYTES:
        return result
    compact: dict[str, JsonValue] = {
        key: result[key] for key in (
            "ok", "bytes", "passed", "failed", "cell_count", "area_estimate",
            "run_tag", "drc_ok", "lvs_ok", "image_url", "best_run_tag", "metrics",
            "log_path", "results_path", "stats_path",
        ) if key in result
    }
    compact["summary"] = "Output truncated; full EDA logs remain on disk."
    for key in ("error", "content", "diff", "text", "log_tail"):
        if isinstance(result.get(key), str):
            compact[key] = _tail(str(result[key]), 4 * 1024)
            break
    else:
        compact["log_tail"] = _tail(encoded, 4 * 1024)
    for key in ("errors", "failures"):
        values = result.get(key)
        if isinstance(values, list) and values:
            compact["first_error"] = _tail(json.dumps(values[0], ensure_ascii=False), 512)
            break
    # Metrics are normally a small numeric mapping. Bound even unexpected output.
    if len(json.dumps(compact, ensure_ascii=False).encode()) > MAX_OUTPUT_BYTES:
        return {"ok": result.get("ok", False), "summary": compact["summary"], "log_tail": _tail(encoded, 4 * 1024)}
    return compact


def _validate_rtl(content: str) -> None:
    tokens = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', " ", content, flags=re.S)
    forbidden = re.search(
        r"\b(initial|always_ff|always_comb|always_latch|logic|bit|byte|shortint|int|longint|"
        r"typedef|enum|struct|union|interface|package|import|export|class|modport|program|"
        r"final|assert|property|sequence|covergroup|foreach|unique|priority|timeunit|timeprecision)\b",
        tokens,
    )
    if forbidden:
        raise ValueError(f"RTL must be synthesizable Verilog-2005; forbidden token: {forbidden.group()}")
    if re.search(r"#\s*\d", tokens):
        raise ValueError("RTL delays are not allowed")
    for task in re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*", tokens):
        if task not in {"$clog2", "$signed", "$unsigned"}:
            raise ValueError(f"RTL system task/function is not allowed: {task}")


_DANGEROUS_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "hasattr", "dir", "breakpoint", "help",
}
_DANGEROUS_IMPORTS = {"os", "sys", "subprocess", "pathlib", "shutil", "builtins", "importlib", "ctypes", "socket", "pickle"}
_DANGEROUS_ATTRIBUTES = {
    "system", "popen", "open", "fdopen", "fork", "forkpty", "kill", "killpg",
    "environ", "getenv", "putenv", "unsetenv", "mro", "load_module", "find_spec",
    "f_globals", "f_locals", "f_back", "f_code", "gi_frame", "cr_frame", "tb_frame",
    "read_text", "read_bytes", "write_text", "write_bytes", "settrace", "setprofile",
}


def _validate_test(content: str) -> None:
    # Conservative source checks catch obvious escapes. Docker is the isolation
    # boundary; this AST check is not a complete sandbox for arbitrary Python.
    try:
        tree = ast.parse(content)
    except SyntaxError as error:
        raise ValueError(f"Invalid Python test: {error.msg}") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if isinstance(node, ast.ImportFrom) and node.level:
                raise ValueError("Relative test imports are not allowed")
            for module in modules:
                if module not in {"random", "math", "cocotb"} and not module.startswith("cocotb."):
                    raise ValueError(f"Test import is not allowed: {module}")
                if any(part.startswith("_") or part in _DANGEROUS_IMPORTS for part in module.split(".")):
                    raise ValueError("Private test imports are not allowed")
            if any(alias.name.startswith("_") or alias.name == "*" or alias.name in _DANGEROUS_IMPORTS
                   for alias in node.names):
                raise ValueError("Private or wildcard test imports are not allowed")
        if isinstance(node, ast.Name) and node.id in _DANGEROUS_NAMES:
            raise ValueError(f"Test builtin is not allowed: {node.id}")
        if isinstance(node, ast.Attribute):
            if ((node.attr.startswith("_") and node.attr not in {"_log", "_id"})
                    or node.attr in _DANGEROUS_ATTRIBUTES
                    or node.attr.startswith(("exec", "spawn", "posix_spawn"))):
                raise ValueError(f"Test attribute is not allowed: {node.attr}")


class ToolRunner:
    def __init__(
        self, work_dir: Path, run_id: str, eda: EDA | None = None,
        event_callback: Callable[[str, dict[str, JsonValue]], Awaitable[None]] | None = None,
    ):
        self.work_dir = work_dir.resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.eda = eda if eda is not None else EDA(self.work_dir, run_id=run_id)
        self.event_callback = event_callback
        self.flow_runs = 0
        self.verified_revision: str | None = None
        self._verified_tests_digest: str | None = None
        self._verified_top: str | None = None
        self._test_lock = asyncio.Lock()

    def _source_digest(self, directory: str, extension: str) -> str:
        self._relative(directory)
        paths = sorted((self.work_dir / directory).glob(f"*{extension}"))
        if not paths:
            raise ValueError(f"No {directory} source files found")
        digest = hashlib.sha256()
        for path in paths:
            with self._file(f"{directory}/{path.name}") as descriptor:
                content = os.read(descriptor, MAX_WRITE_BYTES + 1)
            if len(content) > MAX_WRITE_BYTES:
                raise ValueError("Source file exceeds 128 KB")
            digest.update(path.name.encode() + b"\0" + content + b"\0")
        return digest.hexdigest()

    def rtl_digest(self) -> str:
        return self._source_digest("src", ".v")

    def _require_verified(self, top: str) -> None:
        if (self.verified_revision is None or self.verified_revision != self.rtl_digest()
                or self._verified_tests_digest != self._source_digest("test", ".py")
                or self._verified_top != top or self._test_lock.locked()):
            raise ValueError("Current RTL and tests must pass at least 4 tests before a flow run")

    def _relative(self, path: str) -> PurePosixPath:
        if "\\" in path or "\x00" in path or any(part in {"", ".", ".."} for part in path.split("/")):
            raise ValueError("Path traversal and backslashes are not allowed")
        relative = PurePosixPath(path)
        if relative.is_absolute():
            raise ValueError("Absolute paths are not allowed")
        candidate = self.work_dir
        for part in relative.parts:
            candidate /= part
            if candidate.is_symlink():
                raise ValueError("Symlink paths are not allowed")
        if not candidate.resolve().is_relative_to(self.work_dir):
            raise ValueError("Path escapes the working directory")
        return relative

    @contextmanager
    def _file(self, path: str, *, write: bool = False) -> Iterator[int]:
        relative = self._relative(path)
        directory = os.open(self.work_dir, os.O_RDONLY | os.O_DIRECTORY)
        descriptor: int | None = None
        try:
            for part in relative.parts[:-1]:
                if write:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=directory)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            flags = os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_RDWR | os.O_CREAT if write else os.O_RDONLY)
            descriptor = os.open(relative.name, flags, 0o600, dir_fd=directory)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Only regular files are allowed")
            yield descriptor
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory)

    async def _emit(self, event_type: str, payload: dict[str, JsonValue]) -> None:
        if self.event_callback:
            await self.event_callback(event_type, payload)

    async def execute(self, call: ToolCall, allowed_tools: set[str] | None = None) -> dict[str, JsonValue]:
        await self._emit("tool_started", {"tool": call.name, "tool_call_id": call.id})
        try:
            if call.name not in _TOOLS or (allowed_tools is not None and call.name not in allowed_tools):
                raise ValueError("Tool is not allowed in this stage")
            arguments = _TOOLS[call.name][0].model_validate(call.arguments)
            result = await asyncio.wait_for(
                self._dispatch(call.name, arguments),
                timeout=FLOW_TIMEOUT_SECONDS if call.name == "run_flow" else TOOL_TIMEOUT_SECONDS,
            )
            result = _bounded_result(result)
        except TimeoutError:
            result = {"ok": False, "error": "Tool command timed out"}
        except Exception as error:
            message = "Invalid tool arguments" if isinstance(error, ValidationError) else str(error)
            result = {"ok": False, "error": _tail(f"{type(error).__name__}: {message}", 4 * 1024)}
        await self._emit("tool_finished", {"tool": call.name, "tool_call_id": call.id, "result": result})
        return result

    async def _dispatch(self, name: str, arguments: _Args) -> dict[str, JsonValue]:
        if isinstance(arguments, _Write):
            return await self._write(arguments)
        if isinstance(arguments, _Read):
            with self._file(arguments.path) as descriptor:
                size = os.fstat(descriptor).st_size
                os.lseek(descriptor, max(0, size - MAX_OUTPUT_BYTES), os.SEEK_SET)
                content = os.read(descriptor, MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")
            return {"content": content, "truncated": size > MAX_OUTPUT_BYTES}
        if name == "list_files":
            files: list[JsonValue] = []
            for directory, subdirs, names in os.walk(self.work_dir, followlinks=False):
                subdirs[:] = sorted(part for part in subdirs
                                    if part != ".eda" and not (Path(directory) / part).is_symlink())
                for filename in sorted(names):
                    path = Path(directory) / filename
                    if not path.is_symlink():
                        files.append(path.relative_to(self.work_dir).as_posix())
                    if len(files) >= 1000:
                        return {"files": files, "truncated": True}
            return {"files": files, "tool_outputs": ".eda/ (omitted from source listing)"}
        if isinstance(arguments, _Note):
            text = arguments.text.encode("utf-8")
            if len(text) > MAX_OUTPUT_BYTES:
                raise ValueError("Note exceeds 8 KB")
            with self._file("design.log", write=True) as descriptor:
                os.lseek(descriptor, 0, os.SEEK_END)
                os.write(descriptor, text + b"\n")
            await self._emit("note", {"text": arguments.text})
            return {"ok": True}
        if isinstance(arguments, _Finish):
            if arguments.best_run_tag is not None:
                self.eda.flow_artifacts(arguments.best_run_tag)
            return {"ok": True, "summary": arguments.summary, "best_run_tag": arguments.best_run_tag}
        if name == "lint" and isinstance(arguments, _Top):
            return await self.eda.lint(arguments.top)
        if isinstance(arguments, _Tests):
            async with self._test_lock:
                before = self.rtl_digest()
                tests_before = self._source_digest("test", ".py")
                self.verified_revision = None
                self._verified_tests_digest = None
                self._verified_top = None
                result = await self.eda.run_tests(arguments.top, arguments.test_module)
                if before != self.rtl_digest() or tests_before != self._source_digest("test", ".py"):
                    result.update(ok=False, error="Sources changed while tests were running; verify again")
                elif (result.get("ok") is True and type(result.get("passed")) is int
                      and int(result["passed"]) >= 4 and type(result.get("failed")) is int
                      and result["failed"] == 0):
                    self.verified_revision = before
                    self._verified_tests_digest = tests_before
                    self._verified_top = arguments.top
                await self._emit("test_result", _bounded_result(result))
            return result
        if name == "synth_stats" and isinstance(arguments, _Top):
            return await self.eda.synth_stats(arguments.top)
        if isinstance(arguments, _Flow):
            overrides = validate_flow_overrides(arguments.config_overrides)
            self._require_verified(arguments.top)
            if self.flow_runs >= 6:
                raise ValueError("Flow budget exhausted: at most 6 attempts per run")
            self.flow_runs += 1
            async with _FLOW_SEMAPHORE:
                self._require_verified(arguments.top)
                result = await self.eda.run_flow(arguments.top, overrides)
            if isinstance(result.get("metrics"), dict):
                await self._emit("metric_recorded", {"run_tag": result.get("run_tag"), "metrics": result["metrics"]})
            return result
        if isinstance(arguments, _Report):
            return await self.eda.read_report(arguments.run_tag, arguments.kind)
        if isinstance(arguments, _Render):
            result = await self.eda.render_layout(arguments.run_tag)
            if result.get("image_url"):
                await self._emit("layout_rendered", {"run_tag": arguments.run_tag, **_bounded_result(result)})
            return result
        raise ValueError("Unsupported tool arguments")

    async def _write(self, arguments: _Write) -> dict[str, JsonValue]:
        path = self._relative(arguments.path)
        allowed = (len(path.parts) == 2 and (
            (path.parts[0] == "src" and path.suffix == ".v")
            or (path.parts[0] == "test" and path.suffix == ".py")
        )) or path.as_posix() == "config.json"
        if not allowed:
            raise ValueError("Writes are allowed only to src/*.v, test/*.py, and config.json")
        if path.suffix in {".v", ".py"} and not re.fullmatch(_IDENTIFIER, path.stem):
            raise ValueError("Source filenames must use a plain identifier")
        content = arguments.content.encode("utf-8")
        if len(content) > MAX_WRITE_BYTES:
            raise ValueError("File exceeds 128 KB")
        if path.suffix == ".v":
            _validate_rtl(arguments.content)
        elif path.suffix == ".py":
            _validate_test(arguments.content)
        else:
            validate_flow_overrides(json.loads(arguments.content))
        with self._file(arguments.path, write=True) as descriptor:
            previous = os.read(descriptor, MAX_WRITE_BYTES + 1)
            if len(previous) > MAX_WRITE_BYTES:
                raise ValueError("Existing source exceeds 128 KB")
            old_text = previous.decode("utf-8")
            diff = "".join(difflib.unified_diff(
                old_text.splitlines(keepends=True), arguments.content.splitlines(keepends=True),
                fromfile=arguments.path, tofile=arguments.path,
            ))
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            remaining = memoryview(content)
            while remaining:
                remaining = remaining[os.write(descriptor, remaining):]
        event: dict[str, JsonValue] = {"path": arguments.path, "bytes": len(content), "diff": _tail(diff)}
        event["content"] = arguments.content
        if len(json.dumps(event, ensure_ascii=False).encode()) > MAX_WRITE_BYTES:
            del event["content"]
            event["content_omitted"] = True
        await self._emit("file_written", event)
        if path.suffix in {".v", ".py"}:
            self.verified_revision = None
            self._verified_tests_digest = None
            self._verified_top = None
        return {"ok": True, "bytes": len(content), "diff": _tail(diff)}
