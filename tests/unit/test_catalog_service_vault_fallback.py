from __future__ import annotations

import io
import tarfile
from pathlib import Path

import httpx

from core.config import Settings
from core.services.catalog_service import CatalogService


def create_vault_tar(path: Path) -> None:
    payload = (
        '['
        '{"titleID":"000500001010da00","name":"Minecraft: Wii U Edition","region":"EUR","ticket":"1"},'
        '{"titleID":"000500001010f300","name":"Family Party","region":"USA","ticket":"1"}'
        ']'
    ).encode("utf-8")

    with tarfile.open(path, "w:gz") as archive:
        json_member = tarfile.TarInfo(name="5.180.24.230/json")
        json_member.size = len(payload)
        archive.addfile(json_member, io.BytesIO(payload))


def test_catalog_service_uses_vault_when_upstream_fails(monkeypatch, tmp_path: Path) -> None:
    archive_path = tmp_path / "vault.tar.gz"
    create_vault_tar(archive_path)

    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        catalog_url="https://invalid.example/catalog",
        vault_archive_path=archive_path,
    )

    def failing_get(*args, **kwargs):
        raise httpx.RemoteProtocolError("upstream unavailable")

    monkeypatch.setattr(httpx, "get", failing_get)

    service = CatalogService(settings)
    payload = service.query(limit=50, offset=0)

    assert payload["total"] == 2
    assert payload["source"] == "vault"
    assert payload["source_status"] == "fallback"
    assert isinstance(payload["last_error"], str)

    extracted_json = settings.vault_extract_root / "vault" / "5.180.24.230" / "json"
    assert extracted_json.exists()
