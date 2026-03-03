from pathlib import Path

from core.config import Settings
from core.db import init_db, init_engine
from core.services.queue_service import QueueService


def _init(tmp_path: Path) -> QueueService:
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
    init_engine(settings)
    init_db()
    return QueueService()


def test_latest_job_and_event_lookup(tmp_path: Path) -> None:
    queue = _init(tmp_path)

    item = queue.add_item("0005000010101a00", "EUR")
    job = queue.create_job(item["id"], phase="downloading", progress=0.1)

    queue.add_job_event(job["job_id"], "download_progress", {"overall_progress": 0.25, "speed_bps": 2048})
    queue.add_job_event(job["job_id"], "download_progress", {"overall_progress": 0.5, "speed_bps": 4096})

    latest_job = queue.get_latest_job_for_queue_item(item["id"])
    assert latest_job is not None
    assert latest_job["job_id"] == job["job_id"]

    latest_event = queue.get_latest_event(job["job_id"], "download_progress")
    assert latest_event is not None
    assert latest_event["payload"]["overall_progress"] == 0.5
    assert latest_event["payload"]["speed_bps"] == 4096
