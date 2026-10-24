"""Strict records for evaluations; case expectations are never model input."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

CheckStatus = Literal["pass", "fail", "not_run", "unknown"]
HiddenStatus = Literal["pass", "fail", "error", "not_applicable", "not_run", "unknown"]
ExpectedOutcome = Literal["build", "decline", "ask_clarify", "scope_down"]
ScopeDecision = Literal["decline", "ask_clarify", "scope_down"]
Split = Literal["dev", "heldout"]


class StrictRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class Provenance(StrictRecord):
    source_url: str = Field(min_length=1, max_length=2048)
    commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    path: str = Field(min_length=1, max_length=512)
    license: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_url")
    @classmethod
    def explicit_source_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Provenance requires an explicit upstream source URL")
        return value

    @field_validator("path")
    @classmethod
    def canonical_source_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or str(path) != value or ".." in path.parts or "\\" in value or "\x00" in value:
            raise ValueError("Provenance path must be canonical and relative")
        return value

    @field_validator("license")
    @classmethod
    def nonempty_license(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reference license must be explicit")
        return value


def _finite_json(value: JsonValue) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite JSON number")
    if isinstance(value, dict):
        for item in value.values():
            _finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _finite_json(item)
    return value


class CaseDefinition(StrictRecord):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    tier: int = Field(ge=1, le=4)
    expected_outcome: ExpectedOutcome
    behaviors: list[str] = Field(min_length=1)
    targets: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)
    oracle_kind: Literal["differential", "python_reference", "decision_only"] | None = None
    evaluation_scope: Literal["general_contract", "implementation_compatibility"] = "general_contract"

    @field_validator("behaviors")
    @classmethod
    def nonempty_behaviors(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("Behavior requirements must be nonempty")
        return value

    @field_validator("targets")
    @classmethod
    def finite_targets(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _finite_json(value)
        return value

    @model_validator(mode="after")
    def coherent_tier(self) -> CaseDefinition:
        if (self.tier == 4) == (self.expected_outcome == "build"):
            raise ValueError("Tiers 1–3 build; tier 4 requires an explicit scope decision")
        if self.tier < 4 and not self.provenance:
            raise ValueError("Build references require pinned provenance")
        return self

    @property
    def case_id(self) -> str:
        return self.id


class EvalCase(CaseDefinition):
    case_dir: Path
    split: Split
    spec_text: str = Field(min_length=1)
    top_module: str | None = None


class EvalConfig(StrictRecord):
    repeats: int = Field(default=3, ge=1, le=100)
    concurrency: int = Field(default=1, ge=1, le=4)
    max_calls: int = Field(default=32, ge=1)
    max_tokens: int = Field(default=300_000, ge=1)
    max_usd: float = Field(default=1.0, ge=0)
    time_limit_seconds: float = Field(default=900.0, gt=0)
    snapshot_id: str = "unrecorded"


class StageChecks(StrictRecord):
    rtl_generated: CheckStatus = "not_run"
    lint: CheckStatus = "not_run"
    self_tests: CheckStatus = "not_run"
    synthesis: CheckStatus = "not_run"
    flow: CheckStatus = "not_run"
    drc: CheckStatus = "not_run"
    lvs: CheckStatus = "not_run"
    package: CheckStatus = "not_run"


class HiddenResult(StrictRecord):
    status: HiddenStatus = "not_run"
    passed: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    skipped: int | None = Field(default=None, ge=0)
    source_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    log_paths: list[str] = Field(default_factory=list)
    error_kind: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def coherent_pass(self) -> HiddenResult:
        if self.status == "pass" and (self.passed is None or self.passed < 1 or self.failed != 0):
            raise ValueError("Hidden pass requires actual positive pass counts and zero failures")
        return self


class TrialResult(StrictRecord):
    trial_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    split: Split
    tier: int = Field(ge=1, le=4)
    repeat_index: int = Field(ge=0)
    run_id: str | None = None
    attempted: bool = False
    status: Literal["completed", "blocked", "error"] = "completed"
    pipeline_status: Literal["not_run", "pending", "running", "done", "failed", "cancelled"] = "not_run"
    stage: str = "NOT_STARTED"
    observed_stages: list[str] = Field(default_factory=list)
    executed_tools: list[str] = Field(default_factory=list)
    stage_checks: StageChecks = Field(default_factory=StageChecks)
    hidden: HiddenResult = Field(default_factory=HiddenResult)
    selected_source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_kind: Literal["selected_flow", "current_rtl", "none"] = "none"
    selected_run_tag: str | None = None
    metrics: dict[str, JsonValue] = Field(default_factory=dict)
    drc_ok: bool | None = None
    lvs_ok: bool | None = None
    fix_loops: int = Field(default=0, ge=0)
    flow_attempts: int = Field(default=0, ge=0)
    iterations_per_stage: dict[str, int] = Field(default_factory=dict)
    llm_calls_per_stage: dict[str, int] = Field(default_factory=dict)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    calls: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    cost_known: bool = False
    elapsed_seconds: float = Field(default=0.0, ge=0)
    timed_out: bool = False
    error: str | None = None
    harness_error: str | None = None
    terminal_message_present: bool | None = None
    worker_exception_type: str | None = None
    failure_explanation_clarity: Literal["clear", "unclear", "unreviewed", "not_applicable"] = "unreviewed"
    failure_class: str | None = None
    provider: str | None = None
    model: str | None = None
    cli_version: str | None = None
    pipeline_sha: str | None = None
    tool_versions: dict[str, str] = Field(default_factory=dict)
    scope_decision: ScopeDecision | None = None
    scope_reason: str | None = None
    success: bool = False

    @field_validator("metrics")
    @classmethod
    def finite_metrics(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _finite_json(value)
        return value

    @field_validator("iterations_per_stage", "llm_calls_per_stage")
    @classmethod
    def positive_stage_iterations(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("Stage iteration counts must be nonnegative")
        return value

    @model_validator(mode="after")
    def coherent_cost(self) -> TrialResult:
        if self.cost_known != (self.cost_usd is not None):
            raise ValueError("Known cost requires a number; unknown cost must remain null")
        return self


def source_snapshot_sha256(root: Path) -> str:
    """Hash the selected flow's flat RTL snapshot using ToolRunner's byte recipe."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Source snapshot must be a real directory")
    paths = sorted(root.iterdir())
    if not paths:
        raise ValueError("Source snapshot contains no RTL files")
    digest = hashlib.sha256()
    for path in paths:
        if (path.is_symlink() or not path.is_file() or path.suffix != ".v"
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", path.stem)):
            raise ValueError("Source snapshot must contain only flat, regular *.v files")
        if path.stat().st_size > 128 * 1024:
            raise ValueError("Source snapshot file exceeds 128 KiB")
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()
