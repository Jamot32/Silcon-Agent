"""Public read-only visual questions; execution belongs to the authenticated host worker."""

import json
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.layout_region_types import LayoutRegionContext, LayoutRegionInput
from app.llm.types import ImageInput, LLMError
from app.models import LayoutQuestion
from app.request_guard import app_request
from app.storage import BusyRunError

router = APIRouter(prefix="/api/runs/{run_id}/layout-questions", tags=["layout questions"])


class AskLayoutQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    selection: LayoutRegionInput
    question: str = Field(min_length=1, max_length=2000)


class PublicLayoutQuestion(BaseModel):
    id: str
    run_id: str
    status: Literal["pending", "running", "done", "failed", "cancelled"]
    question: str
    region: LayoutRegionContext
    answer: str | None
    error: str | None
    provider: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_job(cls, job: LayoutQuestion):
        return cls(**job.model_dump(exclude={"region_json", "evidence_json", "images_json", "claimed_by"}),
                   region=json.loads(job.region_json))


class QuestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    status: Literal["done", "failed", "cancelled"]
    answer: str | None = Field(default=None, max_length=12000)
    error: str | None = Field(default=None, max_length=2000)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=200)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_terminal(self):
        if self.status == "done" and (not self.answer or not self.answer.strip() or self.error is not None):
            raise ValueError("A completed question needs an answer and no error")
        if self.status != "done" and (self.answer is not None or not self.error):
            raise ValueError("A stopped question needs an error and no answer")
        return self


class QuestionState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: Literal["pending", "running", "done", "failed", "cancelled"]
    cancel_requested: bool
    claimed_by: str | None


def _run(request, run_id):
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise HTTPException(404, "Run not found")
    try:
        return request.app.state.store.get_run(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found") from None


def _question(request, run_id, question_id):
    _run(request, run_id)
    if not re.fullmatch(r"[0-9a-f]{32}", question_id):
        raise HTTPException(404, "Layout question not found")
    try:
        job = request.app.state.store.get_layout_question(question_id)
    except KeyError:
        raise HTTPException(404, "Layout question not found") from None
    if job.run_id != run_id:
        raise HTTPException(404, "Layout question not found")
    return job


def question_evidence(database, run, region):
    from app.api_schemas import accepted_design_spec
    from app.flow_inspection import inspect_flow

    design = accepted_design_spec(run)
    evidence = {"run_id": run.id, "is_replay": run.is_replay, "selected_run_tag": run.best_run_tag,
                "region": region.model_dump(mode="json"), "design_contract": design}
    try:
        flow = inspect_flow(database, run, run_tag=region.run_tag).model_dump(mode="json")
        for report in flow["reports"].values():
            excerpt = report.get("excerpt")
            if excerpt and len(excerpt) > 1200:
                report["excerpt"], report["truncated"] = excerpt[:1200], True
        evidence["flow"] = flow
    except (KeyError, ValueError):
        evidence["flow"] = {"available": False, "warning": "No unambiguous flow attempt was recorded for this layout tag."}
    # Bound the whole transmitted text, including unusually large historical contracts.
    if len(json.dumps(evidence).encode()) > 48_000:
        evidence["design_contract"] = None
        evidence["design_contract_warning"] = "Recorded design contract exceeded the question context limit."
    if len(json.dumps(evidence).encode()) > 48_000:
        raise ValueError("Layout evidence exceeds the question context limit")
    return evidence


@router.post("", response_model=PublicLayoutQuestion, status_code=201, dependencies=[Depends(app_request)])
def ask(run_id: str, body: AskLayoutQuestion, request: Request):
    from app.layout_regions import prepare_layout_region
    from app.llm.factory import llm_settings

    run = _run(request, run_id)
    database = request.app.state.store
    try:
        prepared = prepare_layout_region(database, run, body.selection)
        evidence = question_evidence(database, run, prepared.region)
        images = [ImageInput.model_validate(image.model_dump()).model_dump(mode="json") for image in prepared.images]
        settings = llm_settings()
        job = database.create_layout_question(run_id, question=body.question, region=prepared.region.model_dump(mode="json"),
            images=images, evidence=evidence, provider=settings.provider, model=settings.model)
    except KeyError:
        raise HTTPException(404, "Registered layout not found") from None
    except BusyRunError as error:
        raise HTTPException(409, str(error)) from None
    except (ValueError, OSError):
        raise HTTPException(422, "Layout selection is invalid, unavailable, or exceeds image limits") from None
    except LLMError:
        raise HTTPException(503, "The selected model provider is not configured") from None
    return PublicLayoutQuestion.from_job(job)


@router.get("", response_model=list[PublicLayoutQuestion])
def history(run_id: str, request: Request):
    _run(request, run_id)
    return [PublicLayoutQuestion.from_job(job) for job in request.app.state.store.list_layout_questions(run_id)]


@router.get("/{question_id}", response_model=PublicLayoutQuestion)
def get(run_id: str, question_id: str, request: Request):
    return PublicLayoutQuestion.from_job(_question(request, run_id, question_id))


@router.post("/{question_id}/cancel", response_model=PublicLayoutQuestion, dependencies=[Depends(app_request)])
def cancel(run_id: str, question_id: str, request: Request):
    _question(request, run_id, question_id)
    return PublicLayoutQuestion.from_job(request.app.state.store.cancel_layout_question(question_id))
