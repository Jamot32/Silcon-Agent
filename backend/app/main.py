import asyncio
import json
import os
import re
import zlib
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Literal
from zipfile import BadZipFile, ZipFile

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, create_engine
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent.starters import load_starter
from app.api_schemas import CleanupResult, CleanupRuns, CreateReplay, CreateRun, MoveRuns, ParentContext, ParentMetrics, ProjectName, PublicProject, PublicRun, ReviewAnswer, UpdateRun, accepted_design_spec
from app.flow_inspection import FlowInspection, inspect_flow
from app.layout_regions import prepare_layout_region
from app.layout_questions import router as layout_questions_router
from app.models import Metric, Run
from app.llm.factory import LLMSettings, llm_settings
from app.llm.types import LLMError
from app.replay import RecordingMetadata, list_recordings, load_recording
from app.storage import BusyRunError, ProjectNameConflict, ProjectNotFoundError, RunCleanupError, RunStore, TERMINAL
from app.schemas import BuildConfig, DesignSpec
from app.workspace import SourceSnapshot, WorkspaceState, WorkspaceWrite, flow_sources
from app.worker_api import router as worker_router
from app.reliability.router import router as reliability_router
from app.connections_api import router as connections_router
from app.provider_credentials import effective_key
from app.request_guard import TRUSTED_HOSTS, app_request

RUNS_DIR = Path(os.getenv("RUNS_DIR", "runs"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{RUNS_DIR}/silicon-agent.db")
RECORDINGS_DIR = Path(os.getenv("RECORDINGS_DIR", "/demo_recordings"))
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
CURRENT_MILESTONE = "M11"
WORKER_HEARTBEAT_TTL = 15
CAPABILITIES = ["live_runs", "sse_resume", "real_eda_artifacts", "optimization", "bundle_download", "recorded_replay", "worker_recovery"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    app.state.store = RunStore(RUNS_DIR, engine=engine)
    app.state.worker_last_seen = None
    yield


app = FastAPI(title="Silicon Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)
app.include_router(worker_router)
app.include_router(reliability_router)
app.include_router(connections_router)
app.include_router(layout_questions_router)


class Check(BaseModel):
    status: Literal["ok", "not_verified", "not_configured", "error"]
    detail: str


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    milestone: str
    checks: dict[str, Check]
    llm_provider: str
    capabilities: list[str]


class Preset(BaseModel):
    id: str
    name: str
    spec_text: str


class GoldenChecks(BaseModel):
    drc_ok: Literal[True]
    lvs_ok: Literal[True]
    cocotb_tests: int


class GoldenCheck(BaseModel):
    status: Literal["passed"]
    checked_at: datetime
    librelane_version: str
    artifacts: dict[str, str]
    checks: GoldenChecks


class SmokeUsage(BaseModel):
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


class CodexSmoke(BaseModel):
    status: Literal["passed"]
    provider: Literal["codex"]
    checked_at: datetime
    model: str
    cli_version: Literal["0.163.0"]
    usage: SmokeUsage
    cost_usd: None


def llm_health() -> Check:
    provider = os.getenv("LLM_PROVIDER", "codex")
    if provider == "meta":
        try:
            configured = bool(effective_key(RUNS_DIR, "meta"))
        except OSError:
            return Check(status="error", detail="Meta key storage is unavailable")
        return Check(
            status="not_verified" if configured else "not_configured",
            detail="Run make meta-smoke" if configured else "Add a Meta key in Settings or set META_API_KEY",
        )
    if provider != "codex":
        return Check(status="error", detail="LLM_PROVIDER must be codex or meta")
    marker = RUNS_DIR / "llm-smoke-codex.json"
    if not marker.exists():
        return Check(status="not_verified", detail="Run make llm-smoke on the host using the Codex ChatGPT login")
    try:
        result = CodexSmoke.model_validate_json(marker.read_text())
        return Check(status="ok", detail=f"Cached Codex/ChatGPT-plan smoke passed at {result.checked_at.isoformat()}; USD cost unavailable")
    except (OSError, ValueError):
        return Check(status="error", detail="Codex smoke cache is invalid; rerun make llm-smoke")


def eda_health() -> Check:
    directory = (RUNS_DIR / "eda-check").resolve()
    marker = directory / "complete.json"
    if not marker.exists():
        return Check(status="not_verified", detail="Run make eda-check to verify the golden design")
    try:
        result = GoldenCheck.model_validate_json(marker.read_text())
        if result.checks.cocotb_tests < 4:
            raise ValueError("Incomplete golden tests")
        for kind in ("metrics", "gds", "layout", "lef", "netlist"):
            path = (directory / result.artifacts[kind]).resolve()
            if not path.is_relative_to(directory) or not path.is_file() or not path.stat().st_size:
                raise ValueError("Missing golden artifact")
        return Check(status="ok", detail=f"Cached golden check passed at {result.checked_at.isoformat()} (LibreLane {result.librelane_version}, DRC/LVS clean)")
    except (OSError, ValueError, KeyError, TypeError):
        return Check(status="error", detail="Golden-check cache is invalid or artifacts are missing; rerun make eda-check")


def worker_health() -> Check:
    last_seen = getattr(app.state, "worker_last_seen", None)
    if last_seen is None:
        return Check(status="not_verified", detail="No authenticated worker contact since API startup")
    age = max(0, monotonic() - last_seen)
    if age > WORKER_HEARTBEAT_TTL:
        return Check(status="error", detail=f"Authenticated worker contact is stale ({age:.1f}s ago)")
    return Check(status="ok", detail=f"Authenticated worker contact {age:.1f}s ago")


@app.get("/api/health", response_model=Health)
def health() -> Health:
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1")).one()
        database = Check(status="ok", detail="SQLite reachable")
    except Exception:
        database = Check(status="error", detail="Database check failed; see API logs")
    # Health never makes a billable model request or claims an unexecuted EDA check.
    checks = {
        "database": database,
        "eda": eda_health(),
        "llm": llm_health(),
        "worker": worker_health(),
    }
    return Health(status="ok" if all(check.status == "ok" for check in checks.values()) else "degraded", milestone=CURRENT_MILESTONE, capabilities=CAPABILITIES, checks=checks, llm_provider=os.getenv("LLM_PROVIDER", "codex"))


@app.get("/api/settings", response_model=LLMSettings)
def settings() -> LLMSettings:
    # Read-only: the API and host worker both load .env, so a change takes effect after make dev.
    try:
        return llm_settings()
    except (LLMError, ValueError) as error:
        raise HTTPException(500, f"Invalid model configuration in .env: {error}") from None


@app.get("/api/presets", response_model=list[Preset])
def presets() -> list[Preset]:
    path = Path(os.getenv("PRESETS_PATH", "/designs/presets.json"))
    return [Preset.model_validate(item) for item in json.loads(path.read_text())]


def store() -> RunStore:
    return app.state.store


def get_run(run_id: str):
    if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
        raise HTTPException(404, "Run not found")
    try:
        return store().get_run(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None


def design_sources(run: Run) -> tuple[str, dict[str, str]]:
    """The RTL a revision starts from, and where it came from."""
    # OPTIMIZE can leave a losing RTL edit in work/src; a finished run's design is its packaged selected snapshot.
    if run.status != "done":
        return "last source state", {path: text for path, text in run_files(run.id).items() if path.startswith("src/")}
    try:
        with ZipFile(store().artifact(run.id, "bundle")) as archive:
            return "selected flow snapshot", {info.filename: archive.read(info).decode() for info in archive.infolist()
                                              if re.fullmatch(r"src/[A-Za-z_][A-Za-z0-9_]*\.v", info.filename) and info.file_size <= 128 * 1024}
    except (KeyError, RuntimeError, NotImplementedError, EOFError, zlib.error) as error:
        raise ValueError("The selected design's bundle is unavailable or unreadable") from error


@app.post("/api/runs", status_code=202, dependencies=[Depends(app_request)])
def create_run(body: CreateRun) -> dict[str, str]:
    if body.preset_id is not None and body.preset_id not in {preset.id for preset in presets()}:
        raise HTTPException(422, "Unknown preset")
    carry_over = None
    spec_text = body.spec_text
    targets = body.targets.model_dump(exclude_unset=True) if body.targets else None
    build_config = body.build.model_dump(mode="json") if body.build is not None else None
    if body.parent_run_id is not None:
        try:
            parent = store().get_run(body.parent_run_id)
        except KeyError:
            raise HTTPException(422, "Unknown parent run") from None
        if parent.status not in TERMINAL:
            raise HTTPException(409, "Wait for the previous run to finish or cancel it before revising it")
        parent_spec = accepted_design_spec(parent)
        if body.manual_files is not None:
            if parent.review_requested and parent.review_json is None:
                raise HTTPException(422, "The previous design review was not accepted. Complete a design review before building edited files.")
            try:
                parent_spec = DesignSpec.model_validate(parent_spec).model_dump(mode="json")
            except ValueError:
                raise HTTPException(422, "This run has no accepted design specification. Complete or review a design before building edited files.") from None
            spec_text = parent.spec_text
            targets = parent_spec["targets"]
            if build_config is None:
                previous_build = json.loads(parent.review_json)["build"] if parent.review_json else json.loads(parent.build_json or "{}")
                # Re-enter normal agent limits even when the edited parent was a manual run.
                build_config = BuildConfig(initial_flow=previous_build.get("initial_flow", {})).model_dump(mode="json")
            if body.execution_mode == "manual":
                # Manual mode runs the submitted files once; it never enables model repair or optimization.
                build_config = BuildConfig(**{**(build_config or {}), "optimize": False, "max_flow_runs": 1, "max_repair_loops": 0}).model_dump(mode="json")
        if body.follow_up is not None:
            # The stored parent is authoritative; stale clients must not erase earlier changes.
            spec_text = f"{parent.spec_text}\n\nFollow-up ({body.revision_intent}):\n{body.follow_up}"
            if len(spec_text) > 12000:
                raise HTTPException(422, "The complete follow-up request exceeds 12000 characters. Use Full request to consolidate it before continuing.")
            targets = {**((parent_spec or {}).get("targets") or {}), **json.loads(parent.targets_json or "{}"), **(targets or {})}
        selected = next((metric for metric in store().metrics(parent.id) if metric.run_tag == parent.best_run_tag), None)
        context = ParentContext(
            status=parent.status, stage=parent.stage, summary=parent.summary[:2000] if parent.summary else None,
            error=parent.error[:2000] if parent.error else None, best_run_tag=parent.best_run_tag,
            selected_metrics=ParentMetrics.model_validate(selected.model_dump()) if selected is not None else None,
        )
        carry_over = {"parent_run_id": parent.id, "origin": "fresh implementation", "spec_text": parent.spec_text,
                      "design_spec": parent_spec, "files": {}, "follow_up": body.follow_up,
                      "revision_intent": body.revision_intent, "parent_context": context.model_dump(mode="json")}
        if body.layout_region is not None:
            try:
                focus = prepare_layout_region(store(), parent, body.layout_region)
            except (OSError, ValueError, KeyError):
                raise HTTPException(422, "The selected layout region is unavailable or has changed. Select it again from the parent layout.") from None
            carry_over["layout_focus"] = focus.model_dump(mode="json")
        if body.manual_files is not None:
            carry_over.update(origin="manual edits" if body.execution_mode == "manual" else "workspace edits", files=body.manual_files)
        if body.reuse_design:
            try:
                origin, files = design_sources(parent)
            except (OSError, ValueError, BadZipFile):
                raise HTTPException(422, "The previous run's design could not be read") from None
            if not files:
                raise HTTPException(422, "The previous run has no RTL to start from")
            carry_over.update(origin=origin, files=files)
    try:
        run = store().create_run(spec_text, preset_id=body.preset_id,
                                 targets=targets,
                                 provider="manual" if body.execution_mode == "manual" else os.getenv("LLM_PROVIDER", "codex"), starter_id=body.starter_id,
                                 parent_run_id=body.parent_run_id, carry_over=carry_over, review_requested=body.review,
                                 build=build_config, execution_mode=body.execution_mode)
    except BusyRunError as error:
        raise HTTPException(409, str(error)) from None
    return {"run_id": run.id}


@app.get("/api/runs", response_model=list[PublicRun])
def runs(include_all: bool = False) -> list[PublicRun]:
    return [PublicRun.from_run(run) for run in store().list_runs(limit=None if include_all else 100)]


@app.post("/api/runs/cleanup", response_model=CleanupResult, dependencies=[Depends(app_request)])
def cleanup_runs(body: CleanupRuns) -> CleanupResult:
    deleted_ids, skipped = store().delete_runs(body.run_ids, skip_protected=True)
    return CleanupResult(deleted_ids=deleted_ids, skipped=skipped)


@app.post("/api/runs/move", response_model=list[PublicRun], dependencies=[Depends(app_request)])
def move_runs(body: MoveRuns) -> list[PublicRun]:
    try:
        return [PublicRun.from_run(run) for run in store().move_runs(body.run_ids, body.project_id)]
    except ProjectNotFoundError:
        raise HTTPException(404, "Project not found") from None
    except KeyError:
        raise HTTPException(404, "Run not found") from None


def project_id_or_404(project_id: str) -> str:
    if re.fullmatch(r"[0-9a-f]{32}", project_id) is None:
        raise HTTPException(404, "Project not found")
    return project_id


@app.get("/api/projects", response_model=list[PublicProject])
def projects() -> list[PublicProject]:
    return [PublicProject.model_validate(project, from_attributes=True) for project in store().list_projects()]


@app.post("/api/projects", status_code=201, response_model=PublicProject, dependencies=[Depends(app_request)])
def create_project(body: ProjectName) -> PublicProject:
    try:
        return PublicProject.model_validate(store().create_project(body.name), from_attributes=True)
    except ProjectNameConflict as error:
        raise HTTPException(409, str(error)) from None


@app.patch("/api/projects/{project_id}", response_model=PublicProject, dependencies=[Depends(app_request)])
def rename_project(project_id: str, body: ProjectName) -> PublicProject:
    try:
        return PublicProject.model_validate(store().rename_project(project_id_or_404(project_id), body.name), from_attributes=True)
    except ProjectNotFoundError:
        raise HTTPException(404, "Project not found") from None
    except ProjectNameConflict as error:
        raise HTTPException(409, str(error)) from None


@app.delete("/api/projects/{project_id}", status_code=204, dependencies=[Depends(app_request)])
def delete_project(project_id: str) -> Response:
    try:
        store().delete_project(project_id_or_404(project_id))
    except ProjectNotFoundError:
        raise HTTPException(404, "Project not found") from None
    return Response(status_code=204)



@app.patch("/api/runs/{run_id}", response_model=PublicRun, dependencies=[Depends(app_request)])
def update_run(run_id: str, body: UpdateRun) -> PublicRun:
    get_run(run_id)
    try:
        return PublicRun.from_run(store().update_metadata(run_id, body.model_dump(exclude_unset=True)))
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    except BusyRunError as error:
        raise HTTPException(409, str(error)) from None


@app.delete("/api/runs/{run_id}", status_code=204, dependencies=[Depends(app_request)])
def delete_run(run_id: str) -> Response:
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        raise HTTPException(404, "Run not found")
    try:
        store().delete_runs([run_id])
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    except BusyRunError as error:
        raise HTTPException(409, str(error)) from None
    except ValueError:
        raise HTTPException(409, "Run files could not be safely removed.") from None
    except RunCleanupError as error:
        raise HTTPException(503, str(error)) from None
    return Response(status_code=204)


@app.get("/api/runs/{run_id}", response_model=PublicRun)
def run_detail(run_id: str) -> PublicRun:
    return PublicRun.from_run(get_run(run_id))


@app.get("/api/runs/{run_id}/workspace", response_model=WorkspaceState)
def run_workspace(run_id: str) -> WorkspaceState:
    get_run(run_id)
    try:
        return store().workspace(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None


@app.put("/api/runs/{run_id}/workspace", response_model=WorkspaceState, dependencies=[Depends(app_request)])
def save_run_workspace(run_id: str, body: WorkspaceWrite) -> WorkspaceState:
    get_run(run_id)
    try:
        return store().save_workspace(run_id, body.model_dump(mode="json"))
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    except BusyRunError as error:
        raise HTTPException(409, str(error)) from None


@app.delete("/api/runs/{run_id}/workspace", status_code=204, dependencies=[Depends(app_request)])
def discard_run_workspace(run_id: str, expected_revision: int = Query(ge=0)) -> Response:
    get_run(run_id)
    try:
        store().discard_workspace(run_id, expected_revision)
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    except BusyRunError as error:
        raise HTTPException(409, str(error)) from None
    return Response(status_code=204)


@app.get("/api/runs/{run_id}/sources", response_model=SourceSnapshot)
def run_source_snapshot(run_id: str, event_id: int | None = Query(default=None, ge=1),
                        run_tag: str | None = Query(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")) -> SourceSnapshot:
    run = get_run(run_id)
    if (event_id is None) == (run_tag is None):
        raise HTTPException(422, "Choose one physical-flow event or run tag")
    try:
        return flow_sources(store(), run, event_id=event_id, run_tag=run_tag)
    except KeyError:
        raise HTTPException(404, "Flow attempt not found") from None
    except ValueError:
        raise HTTPException(422, "Invalid or ambiguous flow selector") from None


@app.get("/api/runs/{run_id}/flow", response_model=FlowInspection)
def flow_inspection(run_id: str, event_id: int | None = Query(default=None, ge=1),
                    run_tag: str | None = Query(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")) -> FlowInspection:
    run = get_run(run_id)
    if (event_id is None) == (run_tag is None):
        raise HTTPException(422, "Select exactly one flow event or run tag")
    try:
        return inspect_flow(store(), run, event_id=event_id, run_tag=run_tag)
    except KeyError:
        raise HTTPException(404, "Flow attempt not found") from None
    except ValueError:
        raise HTTPException(422, "Invalid or ambiguous flow selector") from None


@app.get("/api/runs/{run_id}/metrics", response_model=list[Metric])
def run_metrics(run_id: str) -> list[Metric]:
    get_run(run_id)
    return store().metrics(run_id)


@app.get("/api/runs/{run_id}/files")
def run_files(run_id: str) -> dict[str, str]:
    get_run(run_id)
    try:
        root = store().work_dir(run_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "Run files are no longer available") from None
    files = {}
    for directory, extension in (("src", ".v"), ("test", ".py")):
        parent = root / directory
        if parent.is_symlink():
            continue
        for path in sorted(parent.glob(f"*{extension}")):
            try:
                if not path.is_symlink() and path.resolve().is_relative_to(root.resolve()) and path.is_file() and path.stat().st_size <= 128 * 1024:
                    files[f"{directory}/{path.name}"] = path.read_text()
            except FileNotFoundError:
                continue  # A terminal run can be deleted while an existing read completes.
    return files


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, last_event_id: str | None = Header(default=None), after: int = Query(default=0, ge=0, le=2**63 - 1)):
    await run_in_threadpool(get_run, run_id)
    if last_event_id is not None:
        if not last_event_id.isascii() or not last_event_id.isdigit() or len(last_event_id) > 18:
            raise HTTPException(400, "Last-Event-ID must be a nonnegative integer")
        after = int(last_event_id)

    async def stream():
        cursor = after
        last_ping = asyncio.get_running_loop().time()
        while not await request.is_disconnected():
            try:
                terminal = (await run_in_threadpool(store().get_run, run_id)).status in TERMINAL
            except KeyError:
                break  # A terminal run may have been deleted after this stream opened.
            batch = await run_in_threadpool(store().events, run_id, cursor)
            for event in batch:
                cursor = event.id
                data = ('{"id":' + str(event.id) + ',"ts":' + json.dumps(event.ts.isoformat())
                        + ',"type":' + json.dumps(event.type) + ',"payload":' + event.payload_json + '}')
                yield f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"
            # Only a terminal snapshot taken before this batch proves it includes the final event.
            if terminal and len(batch) < 100:
                break
            now = asyncio.get_running_loop().time()
            if now - last_ping >= 15:
                yield ": keep-alive\n\n"
                last_ping = now
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def artifact_response(run_id: str, kind: str, run_tag: str | None = None) -> FileResponse:
    get_run(run_id)
    try:
        path = store().artifact(run_id, kind, run_tag)
    except (KeyError, ValueError):
        raise HTTPException(404, "Artifact not available") from None
    return FileResponse(path, media_type="image/png" if kind == "layout" else "application/zip",
                        filename=f"silicon-agent-{run_id}.zip" if kind == "bundle" else None)


@app.get("/api/runs/{run_id}/layout/{run_tag}.png")
def layout(run_id: str, run_tag: str) -> FileResponse:
    return artifact_response(run_id, "layout", run_tag)


@app.get("/api/runs/{run_id}/bundle.zip")
def bundle(run_id: str) -> FileResponse:
    return artifact_response(run_id, "bundle")


@app.post("/api/runs/{run_id}/cancel", response_model=PublicRun, dependencies=[Depends(app_request)])
def cancel(run_id: str) -> PublicRun:
    get_run(run_id)
    return PublicRun.from_run(store().request_cancel(run_id))


@app.post("/api/runs/{run_id}/review", response_model=PublicRun, dependencies=[Depends(app_request)])
def submit_review(run_id: str, body: ReviewAnswer) -> PublicRun:
    run = get_run(run_id)
    if run.starter_id is not None:
        try:
            load_starter(run.starter_id).validate_spec(body.design_spec)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
    try:
        return PublicRun.from_run(store().submit_review(run_id, body.model_dump(mode="json")))
    except BusyRunError as error:
        raise HTTPException(409, str(error)) from None


@app.get("/api/recordings", response_model=list[RecordingMetadata])
def recordings() -> list[RecordingMetadata]:
    return list_recordings(RECORDINGS_DIR)


@app.post("/api/replays", status_code=202, dependencies=[Depends(app_request)])
def create_replay(body: CreateReplay) -> dict[str, str]:
    try:
        recording = load_recording(RECORDINGS_DIR, body.recording_id)
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(422, "Recording is missing or failed integrity validation") from None
    try:
        run = store().create_replay(body.recording_id, body.speed, recording.run)
    except BusyRunError as error:
        raise HTTPException(409, str(error)) from None
    return {"run_id": run.id}
