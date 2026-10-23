"""Authoritative API-owned SQLite transactions and durable run projections."""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Artifact, Event, Iteration, Metric, Run

ACTIVE = ("pending", "running", "cancel_requested")
TERMINAL = ("done", "failed", "cancelled")


class BusyRunError(ValueError):
    pass


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class RunStore:
    def __init__(self, root: Path, database_url: str | None = None, *, engine: Engine | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._projection_lock = threading.RLock()
        self.engine = engine or create_engine(database_url or f"sqlite:///{self.root}/silicon-agent.db", connect_args={"check_same_thread": False, "timeout": 30})
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def configure_sqlite(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
            for attempt in range(6):
                try:
                    with self.engine.connect() as connection:
                        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
                    break
                except OperationalError:
                    if attempt == 5:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            SQLModel.metadata.create_all(connection)
            self._migrate_bootstrap(connection)
        # Rebuild from committed rows after a crash, including any missed append.
        with Session(self.engine) as session:
            run_ids = list(session.exec(select(Run.id)).all())
        for run_id in run_ids:
            self.project(run_id)

    def _migrate_bootstrap(self, connection) -> None:
        # Additive migration from the M0-M4 schema; no recorded run is discarded.
        additions = {
            "run": {
                "cost_known": "BOOLEAN NOT NULL DEFAULT 0", "input_tokens": "INTEGER NOT NULL DEFAULT 0",
                "output_tokens": "INTEGER NOT NULL DEFAULT 0", "call_count": "INTEGER NOT NULL DEFAULT 0",
                "llm_provider": "VARCHAR NOT NULL DEFAULT 'codex'", "targets_json": "VARCHAR",
                "preset_id": "VARCHAR", "summary": "VARCHAR", "error": "VARCHAR", "best_run_tag": "VARCHAR",
                "tapeout_ready": "BOOLEAN NOT NULL DEFAULT 0", "cancel_requested": "BOOLEAN NOT NULL DEFAULT 0",
                "recording_id": "VARCHAR", "replay_speed": "INTEGER", "starter_id": "VARCHAR",
            },
            "metric": {"flow_index": "INTEGER NOT NULL DEFAULT 0"},
        }
        if self.engine.dialect.name != "sqlite":
            return
        for table, columns in additions.items():
            existing = {row[1] for row in connection.exec_driver_sql(f'PRAGMA table_info("{table}")')}
            for name, definition in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')

    def create_run(self, spec_text: str, *, targets: dict[str, JsonValue] | None = None, preset_id: str | None = None, provider: str = "codex", starter_id: str | None = None,
                   recording_id: str | None = None, replay_speed: int | None = None) -> Run:
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            if session.exec(select(Run.id).where(Run.status.in_(ACTIVE))).first():
                raise BusyRunError("One chip build is already active. Wait for it or cancel it first.")
            run = Run(spec_text=spec_text, targets_json=json_text(targets or {}), preset_id=preset_id, llm_provider=provider,
                      starter_id=starter_id, is_replay=recording_id is not None, recording_id=recording_id, replay_speed=replay_speed)
            session.add(run)
            session.flush()
            (self.root / run.id / "work").mkdir(parents=True)
            session.add(Event(run_id=run.id, type="note", payload_json=json_text({"text": "Queued for the local worker."})))
            session.commit()
        self.project(run.id)
        return run

    def create_replay(self, recording_id: str, speed: int, source) -> Run:
        if type(speed) is not int or speed not in {1, 4}:
            raise ValueError("Replay speed must be 1 or 4")
        return self.create_run(source.spec_text, targets=source.targets, preset_id=source.preset_id,
                               provider=source.llm_provider, starter_id=source.starter_id,
                               recording_id=recording_id, replay_speed=speed)

    def project(self, run_id: str) -> None:
        """Rewrite bounded projections atomically; the database remains authoritative."""
        from app.api_schemas import PublicRun

        with self._projection_lock:
            with Session(self.engine) as session:
                run = session.get(Run, run_id)
                if run is None:
                    raise KeyError(run_id)
                events = session.exec(select(Event).where(Event.run_id == run_id).order_by(Event.id)).all()
                metrics = session.exec(select(Metric).where(Metric.run_id == run_id).order_by(Metric.flow_index)).all()
                values = {
                    "run.json": json_text(PublicRun.from_run(run).model_dump(mode="json")) + "\n",
                    "metrics.json": json_text([metric.model_dump(mode="json") for metric in metrics]) + "\n",
                    "events.jsonl": "".join(json_text({"id": event.id, "ts": event.ts.isoformat(), "type": event.type,
                                                     "payload": json.loads(event.payload_json)}) + "\n" for event in events),
                }
            directory = self.root / run_id
            if directory.is_symlink() or not directory.resolve().is_relative_to(self.root):
                raise ValueError("Unsafe run projection directory")
            directory.mkdir(exist_ok=True)
            for name, contents in values.items():
                if (directory / name).is_symlink():
                    raise ValueError("Unsafe run projection file")
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as temporary:
                    temporary.write(contents)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary.name, directory / name)

    def get_run(self, run_id: str) -> Run:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            return run

    def list_runs(self) -> list[Run]:
        with Session(self.engine) as session:
            return list(session.exec(select(Run).order_by(Run.created_at.desc()).limit(100)).all())

    def work_dir(self, run_id: str) -> Path:
        self.get_run(run_id)
        path = self.root / run_id / "work"
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise ValueError("Unsafe run directory")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def claim_pending(self) -> Run | None:
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.exec(select(Run).where(Run.status == "pending").order_by(Run.created_at)).first()
            if run is None:
                return None
            run.status = "running"
            session.add(run)
            session.commit()
        self.project(run.id)
        return run

    def emit(self, run_id: str, event_type: str, payload: dict[str, JsonValue]) -> None:
        encoded = json_text(payload)
        with Session(self.engine) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            current = session.exec(select(Iteration).where(Iteration.run_id == run_id, Iteration.ended_at.is_(None))).first()
            if event_type == "stage_changed":
                if current:
                    current.ended_at = datetime.now(timezone.utc)
                    prior_ok = payload.get("previous_ok")
                    current.ok = prior_ok if type(prior_ok) is bool else not (
                        payload.get("stage") in {"FAIL", "FAILED"}
                        or current.stage == "VERIFY" and payload.get("stage") == "RTL"
                    )
                    session.add(current)
                stage = str(payload["stage"])
                run.stage = stage
                if isinstance(payload.get("design_spec"), dict):
                    run.design_spec_json = json_text(payload["design_spec"])
                if stage not in {"DONE", "FAIL", "FAILED"}:
                    previous = session.exec(select(Iteration.index).where(Iteration.run_id == run_id).order_by(Iteration.index.desc())).first()
                    session.add(Iteration(run_id=run_id, stage=stage, index=(previous or 0) + 1))
            elif event_type == "cost_update":
                cost = payload.get("cost_usd")
                run.cost_known = cost is not None
                if type(cost) in (int, float):
                    run.cost_usd = float(cost)
                for field in ("input_tokens", "output_tokens", "call_count"):
                    value = payload.get(field, payload.get("calls") if field == "call_count" else None)
                    if type(value) is int:
                        setattr(run, field, value)
            elif event_type == "metric_recorded":
                values = payload.get("metrics")
                if isinstance(values, dict) and values and isinstance(payload.get("run_tag"), str):
                    if current is None:
                        current = Iteration(run_id=run_id, stage=run.stage, index=0)
                        session.add(current)
                        session.flush()
                    existing = session.exec(select(Metric).where(Metric.run_id == run_id, Metric.run_tag == payload["run_tag"])).first()
                    if existing is None:
                        raw = {key: value for key, value in values.items() if key in Metric.model_fields}
                        raw.update(id=uuid4().hex, run_id=run_id, iteration_id=current.id, run_tag=payload["run_tag"], flow_index=payload.get("flow_index", 0))
                        session.add(Metric.model_validate(raw))
            session.add(run)
            session.add(Event(run_id=run_id, type=event_type, payload_json=encoded))
            session.commit()
        self.project(run_id)

    def events(self, run_id: str, after: int = 0, limit: int = 100) -> list[Event]:
        with Session(self.engine) as session:
            return list(session.exec(select(Event).where(Event.run_id == run_id, Event.id > after).order_by(Event.id).limit(limit)).all())

    def metrics(self, run_id: str) -> list[Metric]:
        with Session(self.engine) as session:
            return list(session.exec(select(Metric).where(Metric.run_id == run_id).order_by(Metric.flow_index)).all())

    def cancel_requested(self, run_id: str) -> bool:
        return self.get_run(run_id).cancel_requested

    def request_cancel(self, run_id: str) -> Run:
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.status not in TERMINAL:
                run.cancel_requested = True
                if run.status == "pending":
                    run.status = "cancelled"
                    session.add(Event(run_id=run_id, type="run_finished", payload_json=json_text({"status": "cancelled", "summary": "Cancelled before execution."})))
                else:
                    run.status = "cancel_requested"
                session.add(run)
                session.commit()
        self.project(run_id)
        return run

    def finish(self, run_id: str, outcome) -> None:
        values = outcome.model_dump(mode="json") if hasattr(outcome, "model_dump") else dict(outcome)
        with Session(self.engine) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.cancel_requested and values.get("status") == "done":
                values.update(status="cancelled", summary="Run cancelled by the user before completion was committed.", error=None, tapeout_ready=False)
            for field in ("status", "summary", "error", "best_run_tag", "tapeout_ready"):
                if field in values:
                    setattr(run, field, values[field])
            if values.get("design_spec"):
                run.design_spec_json = json_text(values["design_spec"])
            session.add(run)
            for iteration in session.exec(select(Iteration).where(Iteration.run_id == run_id, Iteration.ended_at.is_(None))).all():
                iteration.ended_at = datetime.now(timezone.utc)
                iteration.ok = run.status == "done"
                session.add(iteration)
            session.add(Event(run_id=run_id, type="run_finished", payload_json=json_text({key: value for key, value in values.items() if key != "design_spec"})))
            session.commit()
        self.project(run_id)

    def fail(self, run_id: str, error: str, status: str = "failed") -> None:
        self.finish(run_id, {"status": status, "summary": error, "error": error, "tapeout_ready": False})

    def recover_interrupted(self) -> None:
        with Session(self.engine) as session:
            ids = list(session.exec(select(Run.id).where(Run.status.in_(("running", "cancel_requested")))).all())
        for run_id in ids:
            self.fail(run_id, "Worker stopped during this build. Partial files and logs were retained; start a new build to retry.")

    def register_artifact(self, run_id: str, kind: str, path: Path, run_tag: str | None = None) -> None:
        self.get_run(run_id)
        root = (self.root / run_id).resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("Artifact must be a file inside its run directory")
        with Session(self.engine) as session:
            artifact = session.exec(select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == kind, Artifact.run_tag == run_tag)).first()
            if artifact is None:
                artifact = Artifact(run_id=run_id, kind=kind, path=resolved.relative_to(root).as_posix(), run_tag=run_tag)
            else:
                artifact.path = resolved.relative_to(root).as_posix()
            session.add(artifact)
            session.commit()

    def artifact(self, run_id: str, kind: str, run_tag: str | None = None) -> Path:
        self.get_run(run_id)
        with Session(self.engine) as session:
            artifact = session.exec(select(Artifact).where(Artifact.run_id == run_id, Artifact.kind == kind, Artifact.run_tag == run_tag)).first()
            if artifact is None:
                raise KeyError(kind)
            root = (self.root / run_id).resolve()
            path = (root / artifact.path).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("Artifact is missing or outside its run directory")
            return path
