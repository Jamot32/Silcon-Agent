"""Private worker control plane; the API is the sole owner of SQLite."""

import os
import re
import secrets
from pathlib import PurePosixPath
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.models import LayoutQuestion, Run
from app.storage import RunLeaseConflict, RunStore

WORKER_ID = re.compile(r"[0-9a-f]{32}\Z")


def authorized(request: Request, authorization: str | None = Header(default=None)) -> None:
    token = os.getenv("WORKER_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "Worker control is not configured; run make setup")
    if authorization is None or not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(403, "Worker authorization required")
    request.app.state.worker_last_seen = monotonic()


def worker_identity(x_worker_id: str | None = Header(default=None)) -> str:
    if x_worker_id is None or not WORKER_ID.match(x_worker_id):
        raise HTTPException(400, "A 32-character lowercase hexadecimal X-Worker-Id is required")
    return x_worker_id


# Authorization runs first so an unauthenticated caller learns nothing about the identity header.
router = APIRouter(prefix="/api/internal/worker", dependencies=[Depends(authorized), Depends(worker_identity)], include_in_schema=False)


def store(request: Request) -> RunStore:
    return request.app.state.store


def require_run(database: RunStore, run_id: str) -> Run:
    if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
        raise HTTPException(404, "Run not found")
    try:
        return database.get_run(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class WorkerEvent(_Body):
    type: Literal["stage_changed", "tool_started", "tool_finished", "file_written", "test_result", "metric_recorded", "layout_rendered", "note", "cost_update", "run_finished", "error"]
    payload: dict[str, JsonValue]


class Finish(_Body):
    outcome: dict[str, JsonValue]


class Failure(_Body):
    error: str = Field(min_length=1, max_length=4000)
    status: Literal["failed", "cancelled"] = "failed"


class Registration(_Body):
    kind: Literal["gds", "lef", "netlist", "metrics", "layout", "config", "bundle"]
    path: str = Field(min_length=1, max_length=2048)
    run_tag: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")


@router.get("/heartbeat")
def heartbeat():
    return {}


@router.post("/claim", response_model=Run | None)
def claim(database: RunStore = Depends(store), worker_id: str = Depends(worker_identity)):
    return database.claim_pending(worker_id)


@router.post("/layout-questions/claim", response_model=LayoutQuestion | None)
def claim_question(database: RunStore = Depends(store), worker_id: str = Depends(worker_identity)):
    return database.claim_layout_question(worker_id)


def require_question(database, question_id):
    if not WORKER_ID.fullmatch(question_id):
        raise HTTPException(404, "Layout question not found")
    try:
        return database.get_layout_question(question_id)
    except KeyError:
        raise HTTPException(404, "Layout question not found") from None


@router.get("/layout-questions/{question_id}", response_model=LayoutQuestion)
def get_question(question_id: str, database: RunStore = Depends(store)):
    return require_question(database, question_id)


from app.layout_questions import QuestionResult, QuestionState


@router.get("/layout-questions/{question_id}/state", response_model=QuestionState)
def question_state(question_id: str, database: RunStore = Depends(store)):
    if not WORKER_ID.fullmatch(question_id):
        raise HTTPException(404, "Layout question not found")
    try:
        return database.get_layout_question_state(question_id)
    except KeyError:
        raise HTTPException(404, "Layout question not found") from None


@router.post("/layout-questions/{question_id}/finish", response_model=LayoutQuestion)
def finish_question(question_id: str, body: QuestionResult, database: RunStore = Depends(store), worker_id: str = Depends(worker_identity)):
    require_question(database, question_id)
    try:
        return database.finish_layout_question(question_id, body.model_dump(), worker_id=worker_id)
    except RunLeaseConflict:
        raise HTTPException(409, "This worker does not hold an active claim on the question") from None


@router.post("/recover")
def recover(database: RunStore = Depends(store), worker_id: str = Depends(worker_identity)):
    database.recover_interrupted(worker_id)
    return {}


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str, database: RunStore = Depends(store)):
    return require_run(database, run_id)


def _conflict() -> HTTPException:
    return HTTPException(409, "This worker does not hold an active claim on the run")


@router.post("/runs/{run_id}/events")
def emit(run_id: str, body: WorkerEvent, database: RunStore = Depends(store), worker_id: str = Depends(worker_identity)):
    require_run(database, run_id)
    try:
        database.emit(run_id, body.type, body.payload, worker_id=worker_id)
    except RunLeaseConflict:
        raise _conflict() from None
    return {}


@router.post("/runs/{run_id}/finish")
def finish(run_id: str, body: Finish, database: RunStore = Depends(store), worker_id: str = Depends(worker_identity)):
    from app.schemas import Outcome

    require_run(database, run_id)
    try:
        outcome = Outcome.model_validate(body.outcome)
    except ValueError:
        raise HTTPException(422, "Invalid worker outcome") from None
    try:
        return database.finish(run_id, outcome, worker_id=worker_id).plain()
    except RunLeaseConflict:
        raise _conflict() from None


@router.post("/runs/{run_id}/fail")
def fail(run_id: str, body: Failure, database: RunStore = Depends(store), worker_id: str = Depends(worker_identity)):
    require_run(database, run_id)
    try:
        return database.fail(run_id, body.error, body.status, worker_id=worker_id).plain()
    except RunLeaseConflict:
        raise _conflict() from None


@router.post("/runs/{run_id}/artifacts")
def register(run_id: str, body: Registration, database: RunStore = Depends(store), worker_id: str = Depends(worker_identity)):
    require_run(database, run_id)
    relative = PurePosixPath(body.path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in body.path or "\x00" in body.path:
        raise HTTPException(422, "Artifact path must be relative to its run")
    try:
        database.register_artifact(run_id, body.kind, database.root / run_id / body.path, body.run_tag, worker_id=worker_id)
    except RunLeaseConflict:
        raise _conflict() from None
    except (OSError, ValueError):
        raise HTTPException(422, "Artifact is missing or outside its run") from None
    return {}
