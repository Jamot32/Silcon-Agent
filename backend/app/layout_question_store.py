"""Question queue transactions share the build queue's SQLite write lock."""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlmodel import Session, select

from app.models import LayoutQuestion, Run

QUESTION_ACTIVE = ("pending", "running")


class LayoutQuestionStore:
    def create_layout_question(self, run_id, *, question, region, images, evidence, provider, model):
        from app.storage import ACTIVE, BusyRunError, json_text

        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            if session.get(Run, run_id) is None:
                raise KeyError(run_id)
            if (session.exec(select(Run.id).where(Run.status.in_(ACTIVE))).first() or
                    session.exec(select(LayoutQuestion.id).where(LayoutQuestion.status.in_(QUESTION_ACTIVE))).first()):
                raise BusyRunError("A build or layout question is already active. Wait for it or cancel it first.")
            job = LayoutQuestion(run_id=run_id, question=question, region_json=json_text(region),
                                 images_json=json_text(images), evidence_json=json_text(evidence), provider=provider, model=model)
            session.add(job)
            session.commit()
            return job

    def get_layout_question(self, question_id):
        with Session(self.engine) as session:
            job = session.get(LayoutQuestion, question_id)
            if job is None:
                raise KeyError(question_id)
            return job

    def list_layout_questions(self, run_id):
        with Session(self.engine) as session:
            return list(session.exec(select(LayoutQuestion).where(LayoutQuestion.run_id == run_id)
                                     .order_by(LayoutQuestion.created_at.desc()).limit(20)).all())

    def get_layout_question_state(self, question_id):
        from app.layout_questions import QuestionState

        with Session(self.engine) as session:
            row = session.exec(select(LayoutQuestion.id, LayoutQuestion.status, LayoutQuestion.cancel_requested,
                                      LayoutQuestion.claimed_by).where(LayoutQuestion.id == question_id)).first()
            if row is None:
                raise KeyError(question_id)
            return QuestionState(id=row[0], status=row[1], cancel_requested=row[2], claimed_by=row[3])

    def claim_layout_question(self, worker_id=None):
        from app.storage import ACTIVE

        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            if (session.exec(select(Run.id).where(Run.status.in_(ACTIVE))).first() or
                    session.exec(select(LayoutQuestion.id).where(LayoutQuestion.status == "running")).first()):
                return None
            job = session.exec(select(LayoutQuestion).where(LayoutQuestion.status == "pending")
                               .order_by(LayoutQuestion.created_at)).first()
            if job is None:
                return None
            job.status, job.claimed_by = "running", worker_id
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
            return job

    def cancel_layout_question(self, question_id):
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            job = session.get(LayoutQuestion, question_id)
            if job is None:
                raise KeyError(question_id)
            if job.status in QUESTION_ACTIVE:
                job.cancel_requested = True
                job.updated_at = datetime.now(timezone.utc)
                if job.status == "pending":
                    job.status, job.error, job.images_json = "cancelled", "Question cancelled before execution.", None
                session.add(job)
                session.commit()
            return job

    def finish_layout_question(self, question_id, result, *, worker_id=None):
        from app.layout_questions import QuestionResult
        from app.storage import RunLeaseConflict

        values = QuestionResult.model_validate(result)
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            job = session.get(LayoutQuestion, question_id)
            if job is None:
                raise KeyError(question_id)
            if job.status != "running" or worker_id is not None and job.claimed_by != worker_id:
                raise RunLeaseConflict("This worker does not hold an active question claim")
            for field, value in values.model_dump().items():
                setattr(job, field, value)
            if job.cancel_requested:
                job.status, job.answer, job.error = "cancelled", None, "Question cancelled by the user."
            job.images_json = None  # Frozen pixels are needed only while the attempt is pending/running.
            job.claimed_by = None
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
            return job

    def recover_layout_questions(self, worker_id=None):
        with Session(self.engine) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            query = select(LayoutQuestion).where(LayoutQuestion.status == "running")
            if worker_id is not None:
                query = query.where((LayoutQuestion.claimed_by == worker_id) | LayoutQuestion.claimed_by.is_(None))
            for job in session.exec(query).all():
                job.status = "cancelled" if job.cancel_requested else "failed"
                job.error = "Worker stopped during this question. It was not automatically retried; usage may be incomplete."
                job.answer, job.images_json, job.claimed_by = None, None, None
                job.updated_at = datetime.now(timezone.utc)
                session.add(job)
            session.commit()
