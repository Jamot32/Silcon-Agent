"""Private worker control plane; the API is the sole owner of SQLite."""

import os
import secrets
from pathlib import PurePosixPath
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.models import Run
from app.storage import RunStore


def authorized(request: Request, authorization: str | None = Header(default=None)) -> None:
    token = os.getenv("WORKER_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "Worker control is not configured; run make setup")
    if authorization is None or not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(403, "Worker authorization required")
    request.app.state.worker_last_seen = monotonic()


router = APIRouter(prefix="/api/internal/worker", dependencies=[Depends(authorized)], include_in_schema=False)


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
def claim(database: RunStore = Depends(store)):
    return database.claim_pending()


@router.post("/recover")
def recover(database: RunStore = Depends(store)):
    database.recover_interrupted()
    return {}


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str, database: RunStore = Depends(store)):
    return require_run(database, run_id)


@router.post("/runs/{run_id}/events")
def emit(run_id: str, body: WorkerEvent, database: RunStore = Depends(store)):
    require_run(database, run_id)
    database.emit(run_id, body.type, body.payload)
    return {}


@router.post("/runs/{run_id}/finish")
def finish(run_id: str, body: Finish, database: RunStore = Depends(store)):
    from app.schemas import Outcome

    require_run(database, run_id)
    try:
        outcome = Outcome.model_validate(body.outcome)
    except ValueError:
        raise HTTPException(422, "Invalid worker outcome") from None
    database.finish(run_id, outcome)
    return {}


@router.post("/runs/{run_id}/fail")
def fail(run_id: str, body: Failure, database: RunStore = Depends(store)):
    require_run(database, run_id)
    database.fail(run_id, body.error, body.status)
    return {}


@router.post("/runs/{run_id}/artifacts")
def register(run_id: str, body: Registration, database: RunStore = Depends(store)):
    require_run(database, run_id)
    relative = PurePosixPath(body.path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in body.path or "\x00" in body.path:
        raise HTTPException(422, "Artifact path must be relative to its run")
    try:
        database.register_artifact(run_id, body.kind, database.root / run_id / body.path, body.run_tag)
    except (OSError, ValueError):
        raise HTTPException(422, "Artifact is missing or outside its run") from None
    return {}
