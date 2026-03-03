from __future__ import annotations

import io
import tarfile
from pathlib import Path

from core.catalog.vault_archive import load_vault_catalog


def create_vault_tar(path: Path) -> None:
    payload = (
        '['
        '{"titleID":"000500001010da00","name":"Minecraft: Wii U Edition","region":"EUR","ticket":"1"},'
        '{"titleID":"000500001010f300","name":"Family Party","region":"USA","ticket":"1"}'
        ']'
    )

    with tarfile.open(path, "w:gz") as archive:
        data = "".join(payload).encode("utf-8")

        json_member = tarfile.TarInfo(name="5.180.24.230/json")
        json_member.size = len(data)
        archive.addfile(json_member, io.BytesIO(data))

        ticket_data = b"dummy-ticket"
        ticket_member = tarfile.TarInfo(name="5.180.24.230/ticket/000500001010da00.tik")
        ticket_member.size = len(ticket_data)
        archive.addfile(ticket_member, io.BytesIO(ticket_data))


def test_load_vault_catalog_extracts_and_parses(tmp_path: Path) -> None:
    archive_path = tmp_path / "vault.tar.gz"
    extract_root = tmp_path / "vault_cache"
    create_vault_tar(archive_path)

    items = load_vault_catalog(archive_path, extract_root)

    assert len(items) == 2
    assert items[0].title_id in {"000500001010da00", "000500001010f300"}

    extracted_json = extract_root / "vault" / "5.180.24.230" / "json"
    assert extracted_json.exists()
