"""Authoritative API-owned SQLite transactions and durable run projections."""

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import delete, event, func, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Artifact, Event, Iteration, LayoutQuestion, Metric, Project, Run, RunDeletion
from app.layout_question_store import LayoutQuestionStore, QUESTION_ACTIVE
from app.schemas import BuildConfig, REVIEW_TIMEOUT_SECONDS
from app.terminal import TerminalAcknowledgement, TerminalAcknowledgementUnavailable

if TYPE_CHECKING:
    from app.workspace import WorkspaceState

ACTIVE = ("pending", "running", "cancel_requested")
LEASED = ("running", "cancel_requested")
TERMINAL = ("done", "failed", "cancelled")
logger = logging.getLogger(__name__)


class BusyRunError(ValueError):
    pass


class RunLeaseConflict(RuntimeError):
    """A mutation for a run that is terminal or not currently claimed by the calling worker."""


class ProjectNotFoundError(LookupError):
    pass


class ProjectNameConflict(ValueError):
    pass


class RunCleanupError(RuntimeError):
    """The database deletion committed, but its durable file-cleanup intent remains."""


def require_lease(run: Run, worker_id: str | None) -> None:
    # worker_id None is the API/evaluator process itself (cancel paths, in-process workers, tests).
    if worker_id is not None and (run.claimed_by != worker_id or run.status not in LEASED):
        raise RunLeaseConflict("This worker does not hold an active claim on the run")


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class RunStore(LayoutQuestionStore):
    def __init__(self, root: Path, database_url: str | None = None, *, engine: Engine | None = None):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._projection_lock = threading.RLock()
        self._projection_cursors: dict[str, tuple[int, int, int]] = {}
        self._deletion_lock = threading.Lock()
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
        self._recover_deleted_runs()
        # Rebuild from committed rows after a crash, including any missed append.
        with Session(self.engine) as session:
            run_ids = list(session.exec(select(Run.id)).all())
        for run_id in run_ids:
            try:
                self.project(run_id)
            except Exception:
                logger.exception("Run %s projection recovery failed", run_id)

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
                "parent_run_id": "VARCHAR", "carry_over_json": "VARCHAR", "build_json": "VARCHAR",
                "display_name": "VARCHAR", "pinned": "BOOLEAN NOT NULL DEFAULT 0", "archived": "BOOLEAN NOT NULL DEFAULT 0",
                "execution_mode": "VARCHAR NOT NULL DEFAULT 'agent'", "workspace_json": "VARCHAR", "workspace_revision": "INTEGER NOT NULL DEFAULT 0",
                "review_requested": "BOOLEAN NOT NULL DEFAULT 0", "review_json": "VARCHAR", "claimed_by": "VARCHAR",
                "project_id": "VARCHAR",
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
                   recording_id: str | None = None, replay_speed: int | None = None,
                   parent_run_id: str | None = None, carry_over: dict[str, JsonValue] | None = None,
                   review_requested: bool = False, build: dict[str, JsonValue] | None = None, execution_mode: str = "agent") -> Run:
        # New real runs record explicit defaults; old recordings retain unknown configuration.
        build_config = BuildConfig.model_validate(build if build is not None else {}).model_dump(mode="json") if build is not None or recording_id is None else None
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            if session.exec(select(Run.id).where(Run.status.in_(ACTIVE))).first():
                raise BusyRunError("One chip build is already active. Wait for it or cancel it first.")
            if session.exec(select(LayoutQuestion.id).where(LayoutQuestion.status.in_(QUESTION_ACTIVE))).first():
                raise BusyRunError("A layout question is already active. Wait for it or cancel it first.")
            if parent_run_id is not None:
                parent = session.get(Run, parent_run_id)
                if parent is None or parent.status not in TERMINAL:
                    raise BusyRunError("The previous run is no longer available to revise. Refresh run history.")
            run = Run(spec_text=spec_text, targets_json=json_text(targets or {}), preset_id=preset_id, llm_provider=provider,
                      starter_id=starter_id, is_replay=recording_id is not None, recording_id=recording_id, replay_speed=replay_speed,
                      parent_run_id=parent_run_id, carry_over_json=json_text(carry_over) if carry_over is not None else None,
                      review_requested=review_requested, build_json=json_text(build_config) if build_config is not None else None,
                      execution_mode=execution_mode,
                      design_spec_json=json_text(carry_over["design_spec"]) if carry_over is not None and carry_over.get("origin") in {"manual edits", "workspace edits"} else None)
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
                               recording_id=recording_id, replay_speed=speed,
                               build=source.build_config.model_dump(mode="json") if source.build_config is not None else None)

    @staticmethod
    def _write_projection(path: Path, contents: str) -> None:
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
                temporary_name = temporary.name
                temporary.write(contents)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    def _projected_event_id(self, path: Path) -> int | None:
        """Read the final complete line once; a torn append requires a full rebuild."""
        if not path.exists():
            return 0
        stat = path.stat()
        size = stat.st_size
        cached = self._projection_cursors.get(path.parent.name)
        if cached is not None and cached[:2] == (size, stat.st_mtime_ns):
            return cached[2]
        if not size:
            return 0
        with path.open("rb") as stream:
            length = min(size, 4096)
            while True:
                stream.seek(size - length)
                tail = stream.read()
                if not tail.endswith(b"\n"):
                    return None
                # Include the preceding newline, even when the last event is large.
                if length == size or b"\n" in tail[:-1]:
                    break
                length = min(size, length * 2)
        try:
            value = json.loads(tail.splitlines()[-1])
            event_id = value["id"]
            return event_id if type(event_id) is int and event_id > 0 else None
        except (ValueError, KeyError, TypeError):
            return None

    def project(self, run_id: str) -> None:
        """Append committed events and replace only changed summary projections."""
        from app.api_schemas import PublicRun

        with self._projection_lock:
            directory = self.root / run_id
            if directory.is_symlink() or not directory.resolve().is_relative_to(self.root):
                raise ValueError("Unsafe run projection directory")
            for name in ("run.json", "metrics.json", "events.jsonl"):
                if (directory / name).is_symlink():
                    raise ValueError("Unsafe run projection file")
            event_path = directory / "events.jsonl"
            cursor = self._projected_event_id(event_path)
            with Session(self.engine) as session:
                run = session.get(Run, run_id)
                if run is None:
                    raise KeyError(run_id)
                events = session.exec(select(Event).where(Event.run_id == run_id, Event.id > (cursor or 0)).order_by(Event.id)).all()
                metrics = session.exec(select(Metric).where(Metric.run_id == run_id).order_by(Metric.flow_index)).all()
                values = {
                    "run.json": json_text(PublicRun.from_run(run).model_dump(mode="json")) + "\n",
                    "metrics.json": json_text([metric.model_dump(mode="json") for metric in metrics]) + "\n",
                }
            directory.mkdir(exist_ok=True)
            for name, contents in values.items():
                path = directory / name
                if not path.exists() or path.read_text(encoding="utf-8") != contents:
                    self._write_projection(path, contents)
            contents = "".join(
                '{"id":' + str(event.id) + ',"ts":' + json_text(event.ts.isoformat())
                + ',"type":' + json_text(event.type) + ',"payload":' + event.payload_json + '}\n'
                for event in events
            )
            try:
                if cursor is None:
                    self._write_projection(event_path, contents)
                elif contents or not event_path.exists():
                    with event_path.open("a", encoding="utf-8") as stream:
                        stream.write(contents)
                        stream.flush()
                        os.fsync(stream.fileno())
                last_id = events[-1].id if events else (cursor or 0)
                stat = event_path.stat()
                self._projection_cursors[run_id] = (stat.st_size, stat.st_mtime_ns, last_id)
            except Exception:
                self._projection_cursors.pop(run_id, None)
                raise

    def _project_committed(self, run_id: str, operation: str) -> None:
        """A projection failure cannot undo the authoritative transaction."""
        try:
            self.project(run_id)
        except Exception:
            logger.exception("Run %s %s committed but projection failed", run_id, operation)

    def submit_review(self, run_id: str, answer: dict[str, JsonValue]) -> Run:
        """Accept one review answer, only while the orchestrator is waiting at REVIEW."""
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if not run.review_requested or run.status != "running" or run.stage != "REVIEW" or run.review_json is not None:
                raise BusyRunError("This run is not waiting for a review.")
            waiting = session.exec(select(Iteration).where(Iteration.run_id == run_id, Iteration.stage == "REVIEW", Iteration.ended_at.is_(None))).first()
            started = waiting.started_at if waiting else None
            if started is not None and datetime.now(timezone.utc) - started.replace(tzinfo=started.tzinfo or timezone.utc) > timedelta(seconds=REVIEW_TIMEOUT_SECONDS):
                raise BusyRunError(f"The {REVIEW_TIMEOUT_SECONDS // 60}-minute review window has closed.")
            run.review_json = json_text(answer)
            # The reviewed targets are now the request: result pages, Revise and replays read targets_json.
            targets = answer["design_spec"]["targets"] if isinstance(answer.get("design_spec"), dict) else {}
            run.targets_json = json_text({key: value for key, value in targets.items() if value is not None})
            session.add(run)
            session.commit()
        self.project(run_id)
        return run

    def get_run(self, run_id: str) -> Run:
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            return run

    def list_runs(self, *, limit: int | None = 100) -> list[Run]:
        with Session(self.engine) as session:
            query = select(Run).order_by(Run.created_at.desc())
            if limit is not None:
                query = query.limit(limit)
            return list(session.exec(query).all())

    def workspace(self, run_id: str) -> "WorkspaceState":
        from app.workspace import workspace_state

        return workspace_state(self.get_run(run_id))

    def save_workspace(self, run_id: str, values: dict[str, JsonValue]) -> "WorkspaceState":
        from app.workspace import WorkspaceWrite, workspace_state

        body = WorkspaceWrite.model_validate(values)
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if body.expected_revision != run.workspace_revision:
                raise BusyRunError("This draft was changed in another tab. Reload the saved draft before saving again.")
            run.workspace_revision += 1
            run.workspace_json = json_text({"files": body.files, "base_source": body.base_source.model_dump() if body.base_source else None,
                                            "updated_at": datetime.now(timezone.utc).isoformat()})
            session.add(run)
            session.commit()
        return workspace_state(run)

    def discard_workspace(self, run_id: str, expected_revision: int) -> None:
        with Session(self.engine) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if expected_revision != run.workspace_revision:
                raise BusyRunError("This draft was changed in another tab. Reload the saved draft before discarding it.")
            run.workspace_json = None
            run.workspace_revision += 1
            session.add(run)
            session.commit()

    def update_metadata(self, run_id: str, changes: dict[str, JsonValue]) -> Run:
        from app.api_schemas import UpdateRun

        values = UpdateRun.model_validate(changes).model_dump(exclude_unset=True)
        with self._projection_lock:
            with Session(self.engine, expire_on_commit=False) as session:
                session.exec(text("BEGIN IMMEDIATE"))
                run = session.get(Run, run_id)
                if run is None:
                    raise KeyError(run_id)
                if values.get("archived") is True and run.status not in TERMINAL:
                    raise BusyRunError("Wait for this run to finish or stop before archiving it.")
                for field, value in values.items():
                    setattr(run, field, value)
                session.add(run)
                session.commit()
            self.project(run_id)
            return run

    def list_projects(self) -> list[Project]:
        with Session(self.engine) as session:
            return list(session.exec(select(Project).order_by(Project.created_at)).all())

    @staticmethod
    def _require_unique_name(session: Session, name: str, project_id: str | None = None) -> None:
        query = select(Project.id).where(func.lower(Project.name) == name.lower())
        if project_id is not None:
            query = query.where(Project.id != project_id)
        if session.exec(query).first() is not None:
            raise ProjectNameConflict("A project with this name already exists.")

    def create_project(self, name: str) -> Project:
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            self._require_unique_name(session, name)
            project = Project(name=name)
            session.add(project)
            session.commit()
            return project

    def rename_project(self, project_id: str, name: str) -> Project:
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            project = session.get(Project, project_id)
            if project is None:
                raise ProjectNotFoundError(project_id)
            self._require_unique_name(session, name, project_id)
            project.name = name
            session.add(project)
            session.commit()
            return project

    def delete_project(self, project_id: str) -> list[str]:
        """Delete only the folder; its runs and files stay in unfiled history."""
        with self._projection_lock:
            with Session(self.engine) as session:
                session.exec(text("BEGIN IMMEDIATE"))
                project = session.get(Project, project_id)
                if project is None:
                    raise ProjectNotFoundError(project_id)
                released = list(session.exec(select(Run).where(Run.project_id == project_id)).all())
                for run in released:
                    run.project_id = None
                    session.add(run)
                session.delete(project)
                session.commit()
                released_ids = [run.id for run in released]
        for run_id in released_ids:
            self._project_committed(run_id, "folder deletion")
        return released_ids

    def move_runs(self, run_ids: list[str], project_id: str | None) -> list[Run]:
        """Move every listed run atomically; one missing run or project changes nothing."""
        ids = list(dict.fromkeys(run_ids))
        with self._projection_lock:
            with Session(self.engine, expire_on_commit=False) as session:
                session.exec(text("BEGIN IMMEDIATE"))
                if project_id is not None and session.get(Project, project_id) is None:
                    raise ProjectNotFoundError(project_id)
                runs = list(session.exec(select(Run).where(Run.id.in_(ids))).all())
                missing = set(ids) - {run.id for run in runs}
                if missing:
                    raise KeyError(sorted(missing)[0])
                for run in runs:
                    run.project_id = project_id
                    session.add(run)
                session.commit()
        for run in runs:
            self._project_committed(run.id, "folder move")
        return runs

    def _deletion_directory(self, run_id: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
            raise ValueError("Unsafe run directory")
        directory = self.root / run_id
        if directory.is_symlink() or directory.resolve() != directory:
            raise ValueError("Unsafe run directory")
        if directory.exists() and not directory.is_dir():
            raise ValueError("Run directory is not a directory")
        return directory

    def _purge_deleted_run(self, run_id: str) -> None:
        """Remove only a tombstoned run; never follow its directory or nested symlinks."""
        with self._deletion_lock:
            with Session(self.engine) as session:
                if session.get(RunDeletion, run_id) is None:
                    return
                if session.get(Run, run_id) is not None:
                    raise ValueError("A run with pending cleanup is still present")
            # The row is gone, so project/work_dir cannot recreate this directory.
            # Disk cleanup holds neither a database write transaction nor the projection lock.
            directory = self._deletion_directory(run_id)
            try:
                shutil.rmtree(directory)
            except FileNotFoundError:
                if directory.exists():
                    raise  # A disappearing child must not discard cleanup for its remaining parent.
            with Session(self.engine) as session:
                session.exec(text("BEGIN IMMEDIATE"))
                deletion = session.get(RunDeletion, run_id)
                if deletion is not None:
                    session.delete(deletion)
                session.commit()

    def _recover_deleted_runs(self) -> None:
        with Session(self.engine) as session:
            pending = list(session.exec(select(RunDeletion.run_id)).all())
        for run_id in pending:
            try:
                self._purge_deleted_run(run_id)
            except (OSError, ValueError):
                logger.warning("Run %s file cleanup remains pending", run_id)

    def delete_runs(self, run_ids: list[str], *, skip_protected: bool = False) -> tuple[list[str], list[dict[str, str]]]:
        """Delete eligible rows atomically, then purge owned files with durable recovery."""
        ids = list(dict.fromkeys(run_ids))
        deleted: list[str] = []
        skipped: list[dict[str, str]] = []
        children: list[str] = []
        with self._projection_lock:
            with Session(self.engine) as session:
                session.exec(text("BEGIN IMMEDIATE"))
                for run_id in ids:
                    run = session.get(Run, run_id)
                    pending = session.get(RunDeletion, run_id)
                    reason = None
                    if run is None and pending is None:
                        reason = "Run not found."
                    elif run is not None and run.pinned:
                        reason = "Unpin this run before deleting it."
                    elif run is not None and run.status not in TERMINAL:
                        reason = "Wait for this run to finish or stop before deleting it."
                    elif session.exec(select(LayoutQuestion.id).where(LayoutQuestion.run_id == run_id,
                            LayoutQuestion.status.in_(QUESTION_ACTIVE))).first():
                        reason = "Wait for this run's layout question to finish or cancel it before deleting it."
                    if reason is not None:
                        if skip_protected:
                            skipped.append({"id": run_id, "reason": reason})
                            continue
                        if run is None:
                            raise KeyError(run_id)
                        raise BusyRunError(reason)
                    try:
                        self._deletion_directory(run_id)
                    except ValueError:
                        if not skip_protected:
                            raise
                        skipped.append({"id": run_id, "reason": "Run files could not be safely removed."})
                        continue
                    deleted.append(run_id)
                if deleted:
                    for child in session.exec(select(Run).where(Run.parent_run_id.in_(deleted), Run.id.not_in(deleted))).all():
                        parent_id = child.parent_run_id
                        child.parent_run_id = None
                        session.add(child)
                        session.add(Event(run_id=child.id, type="note", payload_json=json_text({
                            "text": f"Previous run {parent_id} was deleted. This revision retains its saved requirements, historical context, and any copied source.",
                            "deleted_parent_run_id": parent_id,
                        })))
                        children.append(child.id)
                    for model in (Artifact, Event, Metric, Iteration, LayoutQuestion):
                        session.exec(delete(model).where(model.run_id.in_(deleted)))
                    session.exec(delete(Run).where(Run.id.in_(deleted)))
                    for run_id in deleted:
                        if session.get(RunDeletion, run_id) is None:
                            session.add(RunDeletion(run_id=run_id))
                    session.commit()
        for child_id in children:
            self._project_committed(child_id, "parent deletion")
        purged: list[str] = []
        for run_id in deleted:
            try:
                self._purge_deleted_run(run_id)
                purged.append(run_id)
            except (OSError, ValueError) as error:
                message = "Run removed from history; file cleanup is pending. Retry deletion or restart the API to retry cleanup."
                if not skip_protected:
                    raise RunCleanupError(message) from error
                skipped.append({"id": run_id, "reason": message})
        return purged, skipped

    def work_dir(self, run_id: str) -> Path:
        with self._projection_lock:
            self.get_run(run_id)
            path = self.root / run_id / "work"
            if not path.resolve().is_relative_to(self.root) or path.is_symlink():
                raise ValueError("Unsafe run directory")
            path.mkdir(parents=True, exist_ok=True)
            return path

    def claim_pending(self, worker_id: str | None = None) -> Run | None:
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            if session.exec(select(LayoutQuestion.id).where(LayoutQuestion.status.in_(QUESTION_ACTIVE))).first():
                return None
            run = session.exec(select(Run).where(Run.status == "pending").order_by(Run.created_at)).first()
            if run is None:
                return None
            run.status = "running"
            run.claimed_by = worker_id
            session.add(run)
            session.commit()
        self.project(run.id)
        return run

    def emit(self, run_id: str, event_type: str, payload: dict[str, JsonValue], *, worker_id: str | None = None) -> None:
        encoded = json_text(payload)
        with Session(self.engine) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            require_lease(run, worker_id)
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
        self._project_committed(run_id, "event")

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

    def finish(self, run_id: str, outcome, *, worker_id: str | None = None) -> TerminalAcknowledgement:
        values = outcome.model_dump(mode="json") if hasattr(outcome, "model_dump") else dict(outcome)
        with Session(self.engine) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            # A committed terminal decision is never overwritten, whoever asks.
            if run.status in TERMINAL:
                raise RunLeaseConflict("The run already has a terminal state")
            require_lease(run, worker_id)
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
            acknowledgement = TerminalAcknowledgement(run.id, run.status, values.get("failure_class"))
            session.commit()
        try:
            self.project(run_id)
        except Exception as error:
            if isinstance(error, KeyError):
                with Session(self.engine) as session:
                    if session.get(Run, run_id) is None:
                        # Deletion after the terminal commit cannot invalidate its acknowledgement.
                        return acknowledgement
            raise TerminalAcknowledgementUnavailable("Terminal transaction committed but projection acknowledgement is unavailable") from None
        return acknowledgement

    def fail(self, run_id: str, error: str, status: str = "failed", *, worker_id: str | None = None) -> TerminalAcknowledgement:
        return self.finish(run_id, {"status": status, "summary": error, "error": error, "tapeout_ready": False}, worker_id=worker_id)

    def recover_interrupted(self, worker_id: str | None = None) -> None:
        self.recover_layout_questions(worker_id)
        query = select(Run.id, Run.claimed_by).where(Run.status.in_(LEASED))
        if worker_id is not None:
            # Only the worker router claims API runs and always records an owner, so NULL rows predate leases and no live worker holds them.
            query = query.where((Run.claimed_by == worker_id) | Run.claimed_by.is_(None))
        with Session(self.engine) as session:
            rows = list(session.exec(query).all())
        for run_id, owner in rows:
            try:
                self.fail(run_id, "Worker stopped during this build. Partial files and logs were retained; start a new build to retry.",
                          worker_id=owner if worker_id is not None else None)
            except RunLeaseConflict:
                continue  # Settled by its owner after the scan; that decision stands.

    def register_artifact(self, run_id: str, kind: str, path: Path, run_tag: str | None = None, *, worker_id: str | None = None) -> None:
        root = (self.root / run_id).resolve()
        resolved = path.resolve()
        with Session(self.engine) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            require_lease(run, worker_id)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise ValueError("Artifact must be a file inside its run directory")
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
