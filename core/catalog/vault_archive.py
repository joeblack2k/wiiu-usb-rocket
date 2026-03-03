from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

from core.catalog.parser import CatalogItem, parse_catalog_feed


class VaultCatalogError(RuntimeError):
    pass


def _archive_fingerprint(archive_path: Path) -> str:
    stat = archive_path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _member_destination(base_dir: Path, member_name: str) -> Path:
    relative = Path(member_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise VaultCatalogError(f"Unsafe member path in vault archive: {member_name}")

    destination = (base_dir / relative).resolve()
    base_resolved = base_dir.resolve()
    if destination != base_resolved and base_resolved not in destination.parents:
        raise VaultCatalogError(f"Member escapes extraction root: {member_name}")
    return destination


def _extract_vault_archive(archive_path: Path, extract_dir: Path) -> None:
    fingerprint = _archive_fingerprint(archive_path)
    stamp_path = extract_dir / ".vault_stamp"

    if stamp_path.exists() and stamp_path.read_text(encoding="utf-8").strip() == fingerprint:
        return

    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.islnk() or member.issym():
                continue

            destination = _member_destination(extract_dir, member.name)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            with extracted, destination.open("wb") as output:
                shutil.copyfileobj(extracted, output)

    stamp_path.write_text(fingerprint, encoding="utf-8")


def _find_json_payload(extract_dir: Path) -> Path:
    candidates = [
        path
        for path in extract_dir.rglob("*")
        if path.is_file() and (path.name == "json" or path.suffix.lower() == ".json")
    ]
    if not candidates:
        raise VaultCatalogError("No JSON payload found inside vault.tar.gz")
    return max(candidates, key=lambda path: path.stat().st_size)


def _dedupe_items(items: list[CatalogItem]) -> list[CatalogItem]:
    seen: set[tuple[str, str]] = set()
    deduped: list[CatalogItem] = []
    for item in items:
        key = (item.title_id.lower(), item.region.upper())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    deduped.sort(key=lambda item: (item.name.lower(), item.title_id.lower()))
    return deduped


def load_vault_catalog(archive_path: Path, extract_root: Path) -> list[CatalogItem]:
    if not archive_path.exists():
        raise FileNotFoundError(archive_path)

    extract_dir = extract_root / "vault"
    _extract_vault_archive(archive_path, extract_dir)

    payload_path = _find_json_payload(extract_dir)
    payload = payload_path.read_text(encoding="utf-8")
    items = parse_catalog_feed(payload)
    if not items:
        raise VaultCatalogError("Vault JSON payload did not contain catalog entries")

    return _dedupe_items(items)
