"""Tests voor vault archive limieten en gestructureerde foutcodes."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from core.catalog.vault_archive import VaultCatalogError, _MAX_FILE_BYTES, load_vault_catalog


def _make_archive(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_vault_not_found_raises_with_error_code(tmp_path: Path) -> None:
    archive_path = tmp_path / "missing.tar.gz"
    with pytest.raises(VaultCatalogError) as exc_info:
        load_vault_catalog(archive_path, tmp_path / "out")
    assert exc_info.value.error_code == "vault_not_found"


def test_vault_too_large_raises_with_error_code(tmp_path: Path, monkeypatch) -> None:
    import core.catalog.vault_archive as vault_mod

    archive_path = tmp_path / "vault.tar.gz"
    archive_path.write_bytes(b"not a real archive but big enough for this test")

    # Verlaag de limiet tijdelijk zodat de bestaande file er overheen gaat
    monkeypatch.setattr(vault_mod, "_MAX_ARCHIVE_BYTES", 10)

    with pytest.raises(VaultCatalogError) as exc_info:
        load_vault_catalog(archive_path, tmp_path / "out")
    assert exc_info.value.error_code == "vault_too_large"


def test_vault_file_too_large_raises(tmp_path: Path) -> None:
    archive_path = tmp_path / "vault.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo(name="bigfile.json")
        info.size = _MAX_FILE_BYTES + 1
        # We schrijven minder data dan de header claimt — tarfile checkt size van de header
        archive.addfile(info, io.BytesIO(b"x" * (_MAX_FILE_BYTES + 1)))

    with pytest.raises(VaultCatalogError) as exc_info:
        load_vault_catalog(archive_path, tmp_path / "out")
    assert exc_info.value.error_code == "vault_too_large"


def test_vault_no_json_raises(tmp_path: Path) -> None:
    archive_path = tmp_path / "vault.tar.gz"
    _make_archive(archive_path, [("readme.txt", b"geen json hier")])

    with pytest.raises(VaultCatalogError) as exc_info:
        load_vault_catalog(archive_path, tmp_path / "out")
    assert exc_info.value.error_code == "vault_no_json_payload"


def test_vault_empty_json_raises(tmp_path: Path) -> None:
    archive_path = tmp_path / "vault.tar.gz"
    _make_archive(archive_path, [("data.json", b"[]")])

    with pytest.raises(VaultCatalogError) as exc_info:
        load_vault_catalog(archive_path, tmp_path / "out")
    assert exc_info.value.error_code == "vault_no_json_payload"


def test_vault_invalid_json_raises(tmp_path: Path) -> None:
    archive_path = tmp_path / "vault.tar.gz"
    _make_archive(archive_path, [("data.json", b"{dit is geen json!!!")])

    with pytest.raises(VaultCatalogError) as exc_info:
        load_vault_catalog(archive_path, tmp_path / "out")
    assert exc_info.value.error_code == "vault_json_parse_error"
