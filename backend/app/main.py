import json
import os
from contextlib import asynccontextmanager
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


class Preset(BaseModel):
    id: str
    name: str
    spec_text: str


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
        "eda": Check(status="not_verified", detail="Run make eda-check to verify the golden design"),
        "llm": Check(
            status="not_verified" if os.getenv("META_API_KEY") else "not_configured",
            detail="Run the explicit LLM smoke test" if os.getenv("META_API_KEY") else "META_API_KEY is not set",
        ),
    }
    return Health(status="degraded", milestone="M0", checks=checks)


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
