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
    is_replay: bool = False


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
    # Configured target frequency; this is not a measured maximum frequency.
    clock_mhz: float = Field(gt=0)
    area_um2: float = Field(ge=0)
    wns_ns: float
    tns_ns: float
    power_mw: float = Field(ge=0)
    cell_count: int = Field(ge=0)
    drc_ok: bool | None = None
    lvs_ok: bool | None = None
