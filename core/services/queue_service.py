import json
from datetime import datetime, timezone

from sqlalchemy import asc

from core.db import session_scope
from core.models.entities import Job, JobEvent, QueueItem
from core.models.enums import JobState, QueueState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QueueService:
    def add_item(self, title_id: str, region: str, preferred_mode: str = "direct", catalog_title: str | None = None) -> dict:
        with session_scope() as session:
            queue_item = QueueItem(
                title_id=title_id.lower(),
                region=region.upper(),
                preferred_mode=preferred_mode,
                state=QueueState.QUEUED.value,
                progress=0.0,
                catalog_title=catalog_title,
            )
            session.add(queue_item)
            session.flush()
            return self.serialize_queue_item(queue_item)

    def list_items(self) -> list[dict]:
        with session_scope() as session:
            items = session.query(QueueItem).order_by(asc(QueueItem.created_at)).all()
            return [self.serialize_queue_item(item) for item in items]

    def get_item(self, queue_item_id: str) -> QueueItem | None:
        with session_scope() as session:
            return session.get(QueueItem, queue_item_id)

    def next_queued_item(self) -> QueueItem | None:
        with session_scope() as session:
            return (
                session.query(QueueItem)
                .filter(QueueItem.state == QueueState.QUEUED.value)
                .order_by(asc(QueueItem.created_at))
                .first()
            )

    def set_state(
        self,
        queue_item_id: str,
        state: QueueState,
        progress: float | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        with session_scope() as session:
            item = session.get(QueueItem, queue_item_id)
            if item is None:
                return
            item.state = state.value
            if progress is not None:
                item.progress = float(max(0.0, min(1.0, progress)))
            if error_code is not None:
                item.error_code = error_code
            if error_detail is not None:
                item.error_detail = error_detail
            item.updated_at = utcnow()

    def create_job(self, queue_item_id: str, phase: str = "queued", progress: float = 0.0) -> dict:
        with session_scope() as session:
            job = Job(
                queue_item_id=queue_item_id,
                phase=phase,
                progress=progress,
                state=JobState.RUNNING.value,
                started_at=utcnow(),
            )
            session.add(job)
            session.flush()
            return self.serialize_job(job)

    def update_job(
        self,
        job_id: str,
        *,
        phase: str | None = None,
        progress: float | None = None,
        state: JobState | None = None,
        message: str | None = None,
        diagnostics: dict | None = None,
    ) -> None:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            if phase is not None:
                job.phase = phase
            if progress is not None:
                job.progress = float(max(0.0, min(1.0, progress)))
            if state is not None:
                job.state = state.value
                if state in (JobState.DONE, JobState.FAILED):
                    job.finished_at = utcnow()
            if message is not None:
                job.message = message
            if diagnostics is not None:
                job.diagnostics_json = json.dumps(diagnostics)

    def get_job(self, job_id: str) -> dict | None:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None
            return self.serialize_job(job)

    def add_job_event(self, job_id: str, event_type: str, payload: dict, level: str = "INFO") -> None:
        with session_scope() as session:
            event = JobEvent(job_id=job_id, level=level, event_type=event_type, payload_json=json.dumps(payload))
            session.add(event)

    def get_job_events(self, job_id: str, event_type: str | None = None) -> list[dict]:
        with session_scope() as session:
            query = session.query(JobEvent).filter(JobEvent.job_id == job_id)
            if event_type:
                query = query.filter(JobEvent.event_type == event_type)
            events = query.order_by(asc(JobEvent.id)).all()
            parsed = []
            for event in events:
                parsed.append(
                    {
                        "id": event.id,
                        "job_id": event.job_id,
                        "level": event.level,
                        "event_type": event.event_type,
                        "payload": json.loads(event.payload_json),
                        "ts": event.ts.isoformat(),
                    }
                )
            return parsed

    @staticmethod
    def serialize_queue_item(item: QueueItem) -> dict:
        return {
            "id": item.id,
            "title_id": item.title_id,
            "region": item.region,
            "preferred_mode": item.preferred_mode,
            "state": item.state,
            "progress": item.progress,
            "error_code": item.error_code,
            "error_detail": item.error_detail,
            "catalog_title": item.catalog_title,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

    @staticmethod
    def serialize_job(job: Job) -> dict:
        diagnostics = None
        if job.diagnostics_json:
            try:
                diagnostics = json.loads(job.diagnostics_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                diagnostics = {"raw": job.diagnostics_json}

        return {
            "job_id": job.id,
            "queue_item_id": job.queue_item_id,
            "phase": job.phase,
            "progress": job.progress,
            "state": job.state,
            "message": job.message,
            "diagnostics": diagnostics,
            "started_at": job.started_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }

