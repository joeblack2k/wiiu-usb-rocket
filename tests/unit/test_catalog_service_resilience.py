from pathlib import Path

import httpx

from core.config import Settings
from core.services.catalog_service import CatalogService


def test_catalog_query_does_not_raise_when_upstream_unavailable(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        catalog_url="https://invalid.example/catalog",
    )

    def failing_get(*args, **kwargs):
        raise httpx.RemoteProtocolError("upstream unavailable")

    monkeypatch.setattr(httpx, "get", failing_get)

    service = CatalogService(settings)
    payload = service.query(limit=10, offset=0)

    assert payload["total"] == 0
    assert payload["items"] == []
    assert payload["source_status"] == "degraded"
    assert isinstance(payload["last_error"], str)

