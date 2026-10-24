"""Immutable acknowledgement of one committed terminal-state transaction."""
from dataclasses import asdict, dataclass
import re
from typing import Literal


class TerminalAcknowledgementUnavailable(RuntimeError):
    """A terminal transaction committed, but its acknowledgement is unavailable."""


@dataclass(frozen=True, slots=True)
class TerminalAcknowledgement:
    run_id: str
    status: Literal["done", "failed", "cancelled"]
    failure_class: str | None

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", self.run_id):
            raise ValueError("Terminal acknowledgement requires the exact host run ID")
        if type(self.status) is not str or self.status not in {"done", "failed", "cancelled"}:
            raise ValueError("Terminal acknowledgement requires a committed terminal status")
        if self.failure_class is not None and (type(self.failure_class) is not str or
                not re.fullmatch(r"[a-z_]{1,64}", self.failure_class)):
            raise ValueError("Terminal failure class must be a bounded label or null")

    def plain(self) -> dict:
        return asdict(self)

    @classmethod
    def from_wire(cls, value: object, *, run_id: str) -> "TerminalAcknowledgement":
        if type(value) is not dict or set(value) != {"run_id", "status", "failure_class"}:
            raise ValueError("Exact terminal acknowledgement schema required")
        acknowledgement = cls(**value)
        if acknowledgement.run_id != run_id:
            raise ValueError("Terminal acknowledgement belongs to a different run")
        return acknowledgement
