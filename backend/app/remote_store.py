"""Authenticated worker RPC; the API process is the sole SQLite owner."""

import os
from pathlib import Path
import re
import secrets
import tempfile
from typing import Literal

import httpx
from pydantic import JsonValue, ValidationError

from app.models import LayoutQuestion, Run
from app.schemas import Outcome
from app.terminal import TerminalAcknowledgement

# Run IDs and worker identities share one shape: 32 lowercase hexadecimal characters.
RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
RPC_TIMEOUT = 5


class RemoteStoreError(RuntimeError):
    """A worker API failure without response bodies or authentication details."""


class RunClaimConflict(RemoteStoreError):
    """The API refused a run mutation: the run is terminal or claimed by another worker."""


def load_worker_id(root: Path) -> str:
    """Return this runs directory's stable worker identity, creating it once with owner-only access."""
    path = root / "worker.id"
    def existing() -> str:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r", encoding="ascii", errors="replace") as handle:
            value = handle.read(64)
        if not RUN_ID.match(value):
            raise ValueError(f"{path} must contain exactly 32 lowercase hexadecimal characters") from None
        return value
    try:
        return existing()
    except FileNotFoundError:
        pass
    value = secrets.token_hex(16)
    descriptor, temporary = tempfile.mkstemp(prefix=".worker-id-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Publish complete bytes without replacing a concurrent worker's ID.
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            return existing()
        return value
    finally:
        os.unlink(temporary)


class HTTPRunStore:
    def __init__(self, root: Path, *, base_url: str | None = None, token: str | None = None, client: httpx.Client | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.token = token if token is not None else os.getenv("WORKER_TOKEN", "")
        if not self.token.strip():
            raise ValueError("WORKER_TOKEN is required for the host worker")
        try:
            url = httpx.URL(base_url or os.getenv("WORKER_API_URL") or "http://localhost:8000")
        except httpx.InvalidURL:
            raise ValueError("WORKER_API_URL must be an HTTP or HTTPS base URL") from None
        if url.scheme not in {"http", "https"} or not url.host or url.username or url.password or url.query or url.fragment:
            raise ValueError("WORKER_API_URL must be an HTTP or HTTPS base URL without credentials, query, or fragment")
        self.base_url = str(url).rstrip("/")
        self.worker_id = load_worker_id(self.root)
        # Redirects and proxy environment variables must not forward the worker token.
        # The default transport makes one attempt; mutation retries are never added.
        self.client = client if client is not None else httpx.Client(timeout=RPC_TIMEOUT, follow_redirects=False, trust_env=False)

    @staticmethod
    def _id(run_id: str) -> str:
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("Expected a 32-character lowercase hexadecimal run id")
        return run_id

    def _request(self, method: str, path: str, body: dict[str, JsonValue] | None = None) -> JsonValue:
        try:
            response = self.client.request(
                method, f"{self.base_url}/api/internal/worker/{path}",
                json=body, headers={"Authorization": f"Bearer {self.token}", "X-Worker-Id": self.worker_id},
                # These local control-plane operations only update SQLite or
                # register paths. Bound ambiguous requests and shutdown latency.
                timeout=RPC_TIMEOUT, follow_redirects=False,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 409:
                raise RunClaimConflict("Worker API returned HTTP 409: this worker does not hold an active claim on the run") from None
            raise RemoteStoreError(f"Worker API returned HTTP {error.response.status_code}") from None
        except httpx.HTTPError:
            raise RemoteStoreError("Worker API is unavailable") from None
        try:
            return response.json()
        except ValueError:
            raise RemoteStoreError("Worker API returned invalid JSON") from None

    def _run(self, value: JsonValue, expected_id: str | None = None) -> Run:
        try:
            if not isinstance(value, dict) or not {"id", "spec_text", "status"} <= value.keys():
                raise ValueError("Expected run object")
            run = Run.model_validate(value)
            self._id(run.id)
            if expected_id is not None and run.id != expected_id:
                raise ValueError("Run id mismatch")
            return run
        except (ValueError, ValidationError):
            raise RemoteStoreError("Worker API returned an invalid run") from None

    def claim_pending(self) -> Run | None:
        value = self._request("POST", "claim", {})
        return None if value is None else self._run(value)

    def _question(self, value, expected_id=None):
        try:
            if not isinstance(value, dict) or not {"id", "run_id", "status", "question", "region_json", "evidence_json"} <= value.keys():
                raise ValueError("Expected question object")
            question = LayoutQuestion.model_validate(value)
            self._id(question.id)
            self._id(question.run_id)
            if expected_id is not None and question.id != expected_id:
                raise ValueError("Question id mismatch")
            return question
        except (ValueError, ValidationError):
            raise RemoteStoreError("Worker API returned an invalid layout question") from None

    def claim_layout_question(self):
        value = self._request("POST", "layout-questions/claim", {})
        return None if value is None else self._question(value)

    def get_layout_question(self, question_id):
        question_id = self._id(question_id)
        return self._question(self._request("GET", f"layout-questions/{question_id}"), question_id)

    def get_layout_question_state(self, question_id):
        from app.layout_questions import QuestionState

        question_id = self._id(question_id)
        try:
            value = QuestionState.model_validate(self._request("GET", f"layout-questions/{question_id}/state"))
            if value.id != question_id:
                raise ValueError("Question id mismatch")
            return value
        except (ValueError, ValidationError):
            raise RemoteStoreError("Worker API returned an invalid layout question state") from None

    def finish_layout_question(self, question_id, result):
        question_id = self._id(question_id)
        return self._question(self._request("POST", f"layout-questions/{question_id}/finish", result), question_id)

    def get_run(self, run_id: str) -> Run:
        run_id = self._id(run_id)
        return self._run(self._request("GET", f"runs/{run_id}"), run_id)

    def recover_interrupted(self) -> None:
        self._request("POST", "recover", {})

    def heartbeat(self) -> None:
        self._request("GET", "heartbeat")

    def emit(self, run_id: str, event_type: str, payload: dict[str, JsonValue]) -> None:
        run_id = self._id(run_id)
        self._request("POST", f"runs/{run_id}/events", {"type": event_type, "payload": payload})

    def _terminal_acknowledgement(self, value, run_id: str) -> TerminalAcknowledgement:
        try:
            return TerminalAcknowledgement.from_wire(value, run_id=run_id)
        except (TypeError, ValueError):
            # The mutation may have committed. Never retry it or substitute the
            # submitted outcome for an invalid/missing transaction response.
            raise RemoteStoreError("Worker API returned an invalid terminal acknowledgement") from None

    def finish(self, run_id: str, outcome: Outcome | dict[str, JsonValue]) -> TerminalAcknowledgement:
        run_id = self._id(run_id)
        values = outcome.model_dump(mode="json") if isinstance(outcome, Outcome) else outcome
        value = self._request("POST", f"runs/{run_id}/finish", {"outcome": values})
        return self._terminal_acknowledgement(value, run_id)

    def fail(self, run_id: str, error: str, status: Literal["failed", "cancelled"] = "failed") -> TerminalAcknowledgement:
        run_id = self._id(run_id)
        value = self._request("POST", f"runs/{run_id}/fail", {"error": error, "status": status})
        return self._terminal_acknowledgement(value, run_id)

    def cancel_requested(self, run_id: str) -> bool:
        return self.get_run(run_id).cancel_requested

    def _run_root(self, run_id: str) -> Path:
        path = self.root / self._id(run_id)
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Unsafe host run directory")
        return path

    def work_dir(self, run_id: str) -> Path:
        path = self._run_root(run_id) / "work"
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Unsafe host working directory")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def register_artifact(self, run_id: str, kind: str, path: Path, run_tag: str | None = None) -> None:
        root = self._run_root(run_id).resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("Artifact must be a file inside its host run directory")
        self._request("POST", f"runs/{run_id}/artifacts", {"kind": kind, "path": resolved.relative_to(root).as_posix(), "run_tag": run_tag})

    def close(self) -> None:
        self.client.close()
