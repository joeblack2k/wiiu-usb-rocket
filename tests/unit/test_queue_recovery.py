from pathlib import Path

from core.config import Settings
from core.db import init_db, init_engine, session_scope
from core.models.entities import Job, JobEvent, QueueItem
from core.models.enums import QueueState
from core.services.queue_service import QueueService


def _init(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        otp_path=tmp_path / "otp.bin",
        seeprom_path=tmp_path / "seeprom.bin",
    )
    init_engine(settings)
    init_db()


def test_recover_incomplete_jobs_marks_running_as_failed(tmp_path: Path) -> None:
    _init(tmp_path)
    queue = QueueService()

    item = queue.add_item("00050000101b0400", "USA")
    job = queue.create_job(item["id"], phase="downloading", progress=0.25)
    queue.set_state(item["id"], QueueState.DOWNLOADING, progress=0.25)

    recovered = queue.recover_incomplete_jobs(reason="test")
    assert recovered == 1

    with session_scope() as session:
        row_item = session.get(QueueItem, item["id"])
        row_job = session.get(Job, job["job_id"])
        events = session.query(JobEvent).filter(JobEvent.job_id == job["job_id"]).all()

        assert row_item is not None
        assert row_job is not None

        assert row_item.state == QueueState.FAILED.value
        assert row_item.error_code == "INTERRUPTED"
        assert row_job.state == "FAILED"
        assert row_job.phase == "failed"
        assert row_job.finished_at is not None
        assert any(evt.event_type == "recovered" for evt in events)
