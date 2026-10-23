from datetime import datetime, timezone
from uuid import uuid4

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
