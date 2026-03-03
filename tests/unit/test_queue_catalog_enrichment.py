"""Test dat catalog_title ingevuld wordt bij toevoegen van queue-items."""
from pathlib import Path

from core.config import Settings
from core.db import init_db, init_engine
from core.services.queue_service import QueueService


def _init(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
    init_engine(settings)
    init_db()


def test_add_item_stores_catalog_title(tmp_path: Path) -> None:
    _init(tmp_path)
    service = QueueService()
    item = service.add_item("0005000010101a00", "EUR", catalog_title="Super Game")
    assert item["catalog_title"] == "Super Game"


def test_add_item_without_catalog_title_is_none(tmp_path: Path) -> None:
    _init(tmp_path)
    service = QueueService()
    item = service.add_item("0005000010101a01", "USA")
    assert item["catalog_title"] is None
