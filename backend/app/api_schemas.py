import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import Run
from app.layout_region_types import LayoutRegionInput, LayoutRegionContext
from app.schemas import BuildConfig, DesignSpec
from app.workspace import validate_files


def accepted_design_spec(run: Run) -> dict | None:
    # A review can be accepted just before cancellation, before the worker publishes its next stage.
    # Completed runs retain the final contract published with their selected result.
    if run.status != "done" and run.review_json is not None:
        return json.loads(run.review_json)["design_spec"]
    return json.loads(run.design_spec_json) if run.design_spec_json else None


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
    # A revision links to the run it follows; reuse_design also starts from that run's RTL.
    parent_run_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    reuse_design: bool = False
    follow_up: str | None = Field(default=None, min_length=10, max_length=4000)
    revision_intent: Literal["feature", "fix", "optimize"] | None = None
    # Expert mode: stop after the drafted DesignSpec and wait for the user's review.
    review: bool = False
    build: BuildConfig | None = None
    layout_region: LayoutRegionInput | None = None
    execution_mode: Literal["agent", "manual"] = "agent"
    manual_files: dict[str, str] | None = None

    @field_validator("manual_files")
    @classmethod
    def valid_manual_files(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return validate_files(value) if value is not None else None

    @field_validator("spec_text")
    @classmethod
    def real_spec(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Describe the chip in at least ten characters")
        return value.strip()

    @field_validator("follow_up")
    @classmethod
    def real_follow_up(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) < 10:
            raise ValueError("Describe the change in at least ten characters")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def revision(self) -> "CreateRun":
        if self.layout_region is not None and (self.parent_run_id is None or self.execution_mode != "agent"):
            raise ValueError("A layout region requires an agent revision of a parent run")
        if self.manual_files is not None:
            if self.parent_run_id is None or not any(name.startswith("src/") for name in self.manual_files):
                raise ValueError("Building edited files requires a parent run and at least one RTL file")
            if self.reuse_design or self.starter_id is not None or self.follow_up is not None or self.revision_intent is not None or self.review or self.targets is not None:
                raise ValueError("Building edited files keeps the parent's accepted requirements and starts from the supplied RTL")
            if self.execution_mode == "manual":
                validate_files(self.manual_files, build=True)
        elif self.execution_mode == "manual":
            raise ValueError("A manual build requires edited RTL and tests")
        if (self.follow_up is None) != (self.revision_intent is None):
            raise ValueError("A follow-up requires both follow_up and revision_intent")
        if self.follow_up is not None:
            if self.parent_run_id is None:
                raise ValueError("A follow-up requires parent_run_id")
            if self.starter_id is not None:
                raise ValueError("A follow-up continues the previous request, not a supplied starter")
        if self.reuse_design and self.parent_run_id is None:
            raise ValueError("Starting from a previous design requires parent_run_id")
        if self.reuse_design and self.starter_id is not None:
            raise ValueError("A revision starts from the previous design, not a supplied starter")
        return self


class ParentMetrics(BaseModel):
    """Selected historical measurements, without database identities or artifact paths."""
    run_tag: str
    clock_mhz: float
    area_um2: float
    wns_ns: float
    tns_ns: float
    power_mw: float
    cell_count: int
    drc_ok: bool | None
    lvs_ok: bool | None


class UpdateRun(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    display_name: str | None = Field(default=None, max_length=120)
    pinned: bool = False
    archived: bool = False

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value

    @model_validator(mode="after")
    def has_changes(self) -> "UpdateRun":
        if not self.model_fields_set:
            raise ValueError("Provide a name, pinned status, or archived status")
        return self


class CleanupRuns(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    run_ids: list[Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]] = Field(min_length=1, max_length=100)


class CleanupSkipped(BaseModel):
    id: str
    reason: str


class CleanupResult(BaseModel):
    deleted_ids: list[str]
    skipped: list[CleanupSkipped]


RunId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class ProjectName(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=80)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PublicProject(BaseModel):
    id: str
    name: str
    created_at: datetime


class MoveRuns(BaseModel):
    """Move explicit runs into one project, or back to unfiled history with null."""
    model_config = ConfigDict(extra="forbid", strict=True)

    run_ids: list[RunId] = Field(min_length=1, max_length=100)
    project_id: RunId | None


class ParentContext(BaseModel):
    status: str
    stage: str
    summary: str | None = Field(max_length=2000)
    error: str | None = Field(max_length=2000)
    best_run_tag: str | None
    selected_metrics: ParentMetrics | None


class PublicRun(BaseModel):
    id: str
    display_name: str | None = None
    pinned: bool = False
    archived: bool = False
    project_id: str | None = None
    execution_mode: Literal["agent", "manual"] = "agent"
    has_manual_edits: bool = False
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
    parent_run_id: str | None = None
    carried_files: list[str] = []
    follow_up: str | None = None
    revision_intent: Literal["feature", "fix", "optimize"] | None = None
    parent_context: ParentContext | None = None
    review_requested: bool = False
    review_submitted: bool = False
    requested_build: BuildConfig | None = None
    build_config: BuildConfig | None = None
    layout_region: LayoutRegionContext | None = None

    @classmethod
    def from_run(cls, run: Run) -> "PublicRun":
        carried = json.loads(run.carry_over_json) if run.carry_over_json else {}
        requested_build = json.loads(run.build_json) if run.build_json else None
        effective_build = json.loads(run.review_json)["build"] if run.review_json else requested_build
        return cls(**run.model_dump(exclude={"design_spec_json", "targets_json", "cost_known", "cancel_requested", "cost_usd", "carry_over_json", "review_json", "build_json", "workspace_json", "workspace_revision"}),
                   review_submitted=run.review_json is not None,
                   requested_build=None if run.is_replay else requested_build, build_config=effective_build,
                   layout_region=(carried.get("layout_focus") or {}).get("region"),
                   carried_files=sorted(carried.get("files", {})),
                   has_manual_edits=carried.get("origin") in {"workspace edits", "manual edits"},
                   follow_up=carried.get("follow_up"), revision_intent=carried.get("revision_intent"),
                   parent_context=carried.get("parent_context"),
                   design_spec=accepted_design_spec(run),
                   targets=json.loads(run.targets_json or "{}"), cost_usd=run.cost_usd if run.cost_known else None)


class ReviewAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    design_spec: DesignSpec
    build: BuildConfig


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
