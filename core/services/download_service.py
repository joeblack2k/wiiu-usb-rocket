import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from core.config import Settings
from core.nus.tmd import TmdError, TmdInfo, parse_tmd_bytes


@dataclass(slots=True)
class DownloadedArtifact:
    kind: str
    local_path: Path
    relative_path: str
    target_path: str
    size: int
    sha256: str


@dataclass(slots=True)
class DownloadResult:
    title_id: str
    region: str
    work_dir: Path
    artifacts: list[DownloadedArtifact]
    tmd_present: bool
    ticket_present: bool
    tmd_info: TmdInfo | None = None
    cetk_bytes: bytes | None = None


class DownloadService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _download_with_resume(self, url: str, dest: Path) -> None:
        timeout = httpx.Timeout(float(self._settings.download_timeout_seconds))
        dest.parent.mkdir(parents=True, exist_ok=True)

        existing_size = dest.stat().st_size if dest.exists() else 0
        headers = {}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

        with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as response:
            if response.status_code == 416:
                return
            response.raise_for_status()
            append = response.status_code == 206 and existing_size > 0
            mode = "ab" if append else "wb"
            with dest.open(mode) as output:
                for chunk in response.iter_bytes(1024 * 128):
                    if chunk:
                        output.write(chunk)

    def _try_fetch_json(self, url: str) -> dict[str, Any] | None:
        timeout = httpx.Timeout(float(self._settings.download_timeout_seconds))
        try:
            response = httpx.get(url, timeout=timeout)
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            return None

    def _try_fetch_binary(self, url: str, dest: Path) -> bool:
        try:
            self._download_with_resume(url, dest)
            return dest.exists() and dest.stat().st_size > 0
        except Exception:
            return False

    def _materialize_manifest(self, title_id: str, manifest: dict, work_dir: Path) -> list[DownloadedArtifact]:
        artifacts: list[DownloadedArtifact] = []
        files = manifest.get("files", [])
        for index, file_spec in enumerate(files):
            if not isinstance(file_spec, dict):
                continue
            source_url = str(file_spec.get("url", ""))
            relative_path = str(file_spec.get("path", f"content/{index:04x}.bin"))
            target_path = str(file_spec.get("target_path", f"/usr/title/{title_id}/{relative_path}"))
            kind = str(file_spec.get("kind", "content"))

            local_path = work_dir / relative_path
            if source_url:
                self._download_with_resume(source_url, local_path)
            else:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(b"")

            size = local_path.stat().st_size
            sha256 = self._hash_file(local_path)
            expected_hash = file_spec.get("sha256")
            if expected_hash and expected_hash.lower() != sha256.lower():
                raise RuntimeError(f"Checksum mismatch for {relative_path}")

            artifacts.append(
                DownloadedArtifact(
                    kind=kind,
                    local_path=local_path,
                    relative_path=relative_path,
                    target_path=target_path,
                    size=size,
                    sha256=sha256,
                )
            )
        return artifacts

    def download_title(self, title_id: str, region: str) -> DownloadResult:
        title_id = title_id.lower()
        work_dir = self._settings.artifacts_dir / title_id
        work_dir.mkdir(parents=True, exist_ok=True)

        artifacts: list[DownloadedArtifact] = []
        tmd_present = False
        ticket_present = False
        tmd_info: TmdInfo | None = None
        cetk_bytes: bytes | None = None

        if self._settings.nus_base_url:
            base = self._settings.nus_base_url.rstrip("/")
            manifest_url = f"{base}/{title_id}/manifest.json"
            manifest = self._try_fetch_json(manifest_url)
            if manifest is not None:
                artifacts.extend(self._materialize_manifest(title_id, manifest, work_dir))
                tmd_present = bool(manifest.get("tmd_present", False))
                ticket_present = bool(manifest.get("ticket_present", False))

            if not artifacts:
                tmd_path = work_dir / "tmd"
                cetk_path = work_dir / "cetk"
                tmd_present = self._try_fetch_binary(f"{base}/{title_id}/tmd", tmd_path)
                ticket_present = self._try_fetch_binary(f"{base}/{title_id}/cetk", cetk_path)

                if tmd_present:
                    try:
                        tmd_info = parse_tmd_bytes(tmd_path.read_bytes())
                    except (TmdError, OSError):
                        tmd_info = None
                    artifacts.append(
                        DownloadedArtifact(
                            kind="tmd",
                            local_path=tmd_path,
                            relative_path="tmd",
                            target_path=f"/usr/title/{title_id}/meta/tmd",
                            size=tmd_path.stat().st_size,
                            sha256=self._hash_file(tmd_path),
                        )
                    )
                if ticket_present:
                    cetk_bytes = cetk_path.read_bytes()
                    artifacts.append(
                        DownloadedArtifact(
                            kind="ticket",
                            local_path=cetk_path,
                            relative_path="cetk",
                            target_path=f"/usr/title/{title_id}/meta/cetk",
                            size=cetk_path.stat().st_size,
                            sha256=self._hash_file(cetk_path),
                        )
                    )

                if tmd_info is not None:
                    for record in tmd_info.contents:
                        content_path = work_dir / f"{record.content_id_hex}.app"
                        self._download_with_resume(
                            f"{base}/{title_id}/{record.content_id_hex}",
                            content_path,
                        )
                        artifacts.append(
                            DownloadedArtifact(
                                kind="content",
                                local_path=content_path,
                                relative_path=f"content/{record.content_id_hex}.app",
                                target_path=f"/usr/title/{title_id}/content/{record.content_id_hex}.app",
                                size=content_path.stat().st_size,
                                sha256=self._hash_file(content_path),
                            )
                        )

        if not artifacts:
            content = work_dir / "content.bin"
            payload = json.dumps(
                {
                    "title_id": title_id,
                    "region": region,
                    "mode": "compatibility",
                },
                sort_keys=True,
            ).encode("utf-8")
            content.write_bytes(payload)
            artifacts.append(
                DownloadedArtifact(
                    kind="content",
                    local_path=content,
                    relative_path="content.bin",
                    target_path=f"/usr/title/{title_id}/content/content.bin",
                    size=content.stat().st_size,
                    sha256=self._hash_file(content),
                )
            )

        return DownloadResult(
            title_id=title_id,
            region=region,
            work_dir=work_dir,
            artifacts=artifacts,
            tmd_present=tmd_present,
            ticket_present=ticket_present,
            tmd_info=tmd_info,
            cetk_bytes=cetk_bytes,
        )

