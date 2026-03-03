from datetime import datetime, timezone
from pathlib import Path

from core.catalog.parser import CatalogItem
from core.config import Settings
from core.services.catalog_service import CatalogService


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        catalog_url="https://invalid.example/catalog",
    )


def _service_with_items(tmp_path: Path) -> CatalogService:
    service = CatalogService(_settings(tmp_path))
    service._items = [
        CatalogItem(title_id="0001", name="Alpha One", region="EUR", category="game"),
        CatalogItem(title_id="0002", name="Beta Two", region="USA", category="dlc"),
        CatalogItem(title_id="0003", name="1st Title", region="EUR", category="game"),
        CatalogItem(title_id="0004", name="Charlie", region="JPN", category="game"),
    ]
    service._last_refresh = datetime.now(timezone.utc)
    service._source = "cache"
    return service


def test_query_filters_by_starts_with_letter(tmp_path: Path) -> None:
    service = _service_with_items(tmp_path)
    payload = service.query(starts_with="A", limit=50, offset=0)

    assert payload["total"] == 1
    assert payload["items"][0]["name"] == "Alpha One"


def test_query_filters_by_starts_with_numeric_bucket(tmp_path: Path) -> None:
    service = _service_with_items(tmp_path)
    payload = service.query(starts_with="#", limit=50, offset=0)

    assert payload["total"] == 1
    assert payload["items"][0]["name"] == "1st Title"


def test_query_applies_offset_and_limit(tmp_path: Path) -> None:
    service = _service_with_items(tmp_path)
    payload = service.query(limit=2, offset=1)

    assert payload["total"] == 4
    assert len(payload["items"]) == 2
    assert payload["items"][0]["title_id"] == "0002"
    assert payload["items"][1]["title_id"] == "0003"
