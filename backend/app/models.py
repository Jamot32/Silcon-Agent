from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel


class Run(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    spec_text: str
    design_spec_json: str | None = None
    status: str = "pending"
    stage: str = "SPEC"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cost_usd: float = 0
    # A plan-backed completion has no known USD price; expose None in the API.
    cost_known: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0
    llm_provider: str = "codex"
    targets_json: str | None = None
    preset_id: str | None = None
    summary: str | None = None
    error: str | None = None
    best_run_tag: str | None = None
    tapeout_ready: bool = False
    cancel_requested: bool = False
    is_replay: bool = False
    recording_id: str | None = None
    replay_speed: int | None = None
    starter_id: str | None = None


class Iteration(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    stage: str
    index: int = Field(ge=0)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    ok: bool | None = None


class Metric(SQLModel, table=True):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)

    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    iteration_id: str = Field(foreign_key="iteration.id", index=True)
    run_tag: str
    flow_index: int = Field(default=0, ge=0)
    # Configured target frequency; this is not a measured maximum frequency.
    clock_mhz: float = Field(gt=0)
    area_um2: float = Field(ge=0)
    wns_ns: float
    tns_ns: float
    power_mw: float = Field(ge=0)
    cell_count: int = Field(ge=0)
    drc_ok: bool | None = None
    lvs_ok: bool | None = None


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: str
    payload_json: str


class Artifact(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    kind: str
    path: str
    run_tag: str | None = None
