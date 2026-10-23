import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Run

RUNS_DIR = Path(os.getenv("RUNS_DIR", "runs"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{RUNS_DIR}/silicon-agent.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@asynccontextmanager
async def lifespan(_: FastAPI):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Silicon Agent", version="0.1.0", lifespan=lifespan)


class Check(BaseModel):
    status: Literal["ok", "not_verified", "not_configured", "error"]
    detail: str


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    milestone: str
    checks: dict[str, Check]
    llm_provider: str


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
        return Check(
            status="not_verified" if os.getenv("META_API_KEY") else "not_configured",
            detail="Run make meta-smoke" if os.getenv("META_API_KEY") else "META_API_KEY is not set",
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
    }
    return Health(status="ok" if all(check.status == "ok" for check in checks.values()) else "degraded", milestone="M3" if checks["llm"].status == "ok" else "M1" if checks["eda"].status == "ok" else "M0", checks=checks, llm_provider=os.getenv("LLM_PROVIDER", "codex"))


@app.get("/api/presets", response_model=list[Preset])
def presets() -> list[Preset]:
    path = Path(os.getenv("PRESETS_PATH", "/designs/presets.json"))
    return [Preset.model_validate(item) for item in json.loads(path.read_text())]


@app.get("/api/runs", response_model=list[Run])
def runs() -> list[Run]:
    with Session(engine) as session:
        return list(session.exec(select(Run).order_by(Run.created_at.desc())).all())


@app.get("/api/recordings", response_model=list[str])
def recordings() -> list[str]:
    # Real recordings are added in M10. There is deliberately no synthetic fallback.
    return []
