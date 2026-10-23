import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Run


class Targets(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    clock_mhz: float | None = Field(default=None, ge=1, le=1000)
    max_area_um2: float | None = Field(default=None, gt=0)
    fit: str | None = Field(default=None, pattern="^tt_1x1_tile$")


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    spec_text: str = Field(min_length=10, max_length=12000)
    preset_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    targets: Targets | None = None
    starter_id: Literal["uart_off_by_one"] | None = None

    @field_validator("spec_text")
    @classmethod
    def real_spec(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Describe the chip in at least ten characters")
        return value.strip()


class PublicRun(BaseModel):
    id: str
    spec_text: str
    design_spec: dict | None
    targets: dict
    preset_id: str | None
    status: str
    stage: str
    created_at: datetime
    cost_usd: float | None
    input_tokens: int
    output_tokens: int
    call_count: int
    llm_provider: str
    is_replay: bool
    summary: str | None
    error: str | None
    best_run_tag: str | None
    tapeout_ready: bool
    recording_id: str | None = None
    replay_speed: int | None = None
    starter_id: str | None = None

    @classmethod
    def from_run(cls, run: Run) -> "PublicRun":
        return cls(**run.model_dump(exclude={"design_spec_json", "targets_json", "cost_known", "cancel_requested", "cost_usd"}),
                   design_spec=json.loads(run.design_spec_json) if run.design_spec_json else None,
                   targets=json.loads(run.targets_json or "{}"), cost_usd=run.cost_usd if run.cost_known else None)


class CreateReplay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recording_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    speed: Literal[1, 4] = 4

    @field_validator("speed", mode="before")
    @classmethod
    def integer_speed(cls, value):
        if type(value) is not int:
            raise ValueError("Replay speed must be 1 or 4")
        return value
