"""Tests voor CatalogService.get_source_status() en catalog.lookup()."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import httpx

from core.config import Settings
from core.services.catalog_service import CatalogService


def _settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        **kwargs,
    )


def _create_vault(path: Path) -> None:
    payload = b'[{"titleID":"000500001010da00","name":"Minecraft","region":"EUR","ticket":"1"}]'
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(name="db/json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))


def test_get_source_status_no_vault(tmp_path: Path) -> None:
    settings = _settings(tmp_path, catalog_url="https://invalid.example/catalog")
    service = CatalogService(settings)
    status = service.get_source_status()

    assert status["archive_present"] is False
    assert status["archive_size"] == 0
    assert status["item_count"] == 0


def test_get_source_status_with_vault_after_fallback(monkeypatch, tmp_path: Path) -> None:
    vault_path = tmp_path / "vault.tar.gz"
    _create_vault(vault_path)

    settings = _settings(tmp_path, catalog_url="https://invalid.example/catalog", vault_archive_path=vault_path)

    def failing_get(*args, **kwargs):
        raise httpx.RemoteProtocolError("down")

    monkeypatch.setattr(httpx, "get", failing_get)

    service = CatalogService(settings)
    service.query()  # triggert refresh + vault fallback

    status = service.get_source_status()
    assert status["archive_present"] is True
    assert status["archive_size"] > 0
    assert status["item_count"] == 1
    assert status["status"] == "vault"


def test_lookup_returns_item_when_found(monkeypatch, tmp_path: Path) -> None:
    vault_path = tmp_path / "vault.tar.gz"
    _create_vault(vault_path)

    settings = _settings(tmp_path, catalog_url="https://invalid.example/catalog", vault_archive_path=vault_path)

    def failing_get(*args, **kwargs):
        raise httpx.RemoteProtocolError("down")

    monkeypatch.setattr(httpx, "get", failing_get)

    service = CatalogService(settings)
    service.query()

    item = service.lookup("000500001010da00")
    assert item is not None
    assert item.name == "Minecraft"


def test_lookup_returns_none_when_not_found(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    service = CatalogService(settings)
    assert service.lookup("0000000000000000") is None
