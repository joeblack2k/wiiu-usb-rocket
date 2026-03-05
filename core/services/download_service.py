import hashlib
import json
import logging
import time
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from core.config import Settings
from core.nus.fake_ticket import generate_fake_cetk
from core.nus.tmd import TmdError, TmdInfo, parse_tmd_bytes

logger = logging.getLogger(__name__)

_MIN_TMD_DOWNLOAD_SIZE = 0xB04
_MIN_CETK_DOWNLOAD_SIZE = 0x1E4
_PARALLEL_RANGE_RETRIES = 3

ProgressCallback = Callable[[dict[str, Any]], None]


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
    fake_ticket: bool = False


class DownloadService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _extract_total_size(response: httpx.Response, append: bool, existing_size: int) -> int | None:
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            tail = content_range.rsplit("/", 1)[-1].strip()
            if tail and tail != "*":
                try:
                    return int(tail)
                except ValueError:
                    pass

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                raw_len = int(content_length)
                return existing_size + raw_len if append else raw_len
            except ValueError:
                return None
        return None

    @staticmethod
    def _split_ranges(total_size: int, parts: int) -> list[tuple[int, int]]:
        if total_size <= 0:
            return []
        parts = max(1, parts)
        base = total_size // parts
        extra = total_size % parts
        ranges: list[tuple[int, int]] = []
        offset = 0
        for index in range(parts):
            span = base + (1 if index < extra else 0)
            if span <= 0:
                continue
            start = offset
            end = start + span - 1
            ranges.append((start, end))
            offset = end + 1
        return ranges

    def _download_parallel_ranges(
        self,
        url: str,
        dest: Path,
        total_size: int,
        workers: int,
        progress_callback: ProgressCallback | None = None,
        progress_meta: dict[str, Any] | None = None,
    ) -> int:
        timeout = httpx.Timeout(float(self._settings.download_timeout_seconds))
        dest.parent.mkdir(parents=True, exist_ok=True)

        ranges = self._split_ranges(total_size, workers)
        part_paths = [dest.with_name(f"{dest.name}.part{index:02d}") for index in range(len(ranges))]
        for part in part_paths:
            try:
                if part.exists():
                    part.unlink()
            except OSError:
                pass

        lock = threading.Lock()
        progress = {index: 0 for index in range(len(ranges))}
        started = time.monotonic()
        last_emit = started

        def emit(done: bool = False) -> None:
            nonlocal last_emit
            if progress_callback is None:
                return

            now = time.monotonic()
            with lock:
                if not done and (now - last_emit) < 0.35:
                    return
                downloaded = sum(progress.values())
                last_emit = now

            elapsed = max(now - started, 1e-6)
            speed_bps = int(downloaded / elapsed)
            payload = dict(progress_meta or {})
            payload.update(
                {
                    "file_bytes_downloaded": downloaded,
                    "file_bytes_total": total_size,
                    "speed_bps": speed_bps,
                    "done": done,
                }
            )
            progress_callback(payload)

        def worker(index: int, byte_range: tuple[int, int]) -> None:
            start_byte, end_byte = byte_range
            expected_len = end_byte - start_byte + 1
            part_path = part_paths[index]
            headers = {"Range": f"bytes={start_byte}-{end_byte}"}

            last_error: Exception | None = None
            for attempt in range(1, _PARALLEL_RANGE_RETRIES + 1):
                local_written = 0
                try:
                    with lock:
                        progress[index] = 0
                    if part_path.exists():
                        part_path.unlink()

                    with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as response:
                        if response.status_code != 206:
                            raise RuntimeError(
                                f"Range request failed status={response.status_code} range={start_byte}-{end_byte}"
                            )

                        with part_path.open("wb") as handle:
                            for chunk in response.iter_bytes(1024 * 128):
                                if not chunk:
                                    continue
                                handle.write(chunk)
                                local_written += len(chunk)
                                with lock:
                                    progress[index] = local_written
                                emit(done=False)

                    if local_written != expected_len:
                        raise RuntimeError(
                            f"Range size mismatch for {start_byte}-{end_byte}: got={local_written} expected={expected_len}"
                        )

                    return
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    time.sleep(0.2 * attempt)

            raise RuntimeError(
                f"Parallel range worker failed for {start_byte}-{end_byte}: {last_error}"
            )

        try:
            emit(done=False)
            with ThreadPoolExecutor(max_workers=len(ranges)) as executor:
                futures = [executor.submit(worker, index, byte_range) for index, byte_range in enumerate(ranges)]
                for future in as_completed(futures):
                    future.result()

            with dest.open("wb") as output:
                for part_path in part_paths:
                    with part_path.open("rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            output.write(chunk)

            emit(done=True)
            return dest.stat().st_size
        finally:
            for part_path in part_paths:
                try:
                    if part_path.exists():
                        part_path.unlink()
                except OSError:
                    pass

    def _download_with_resume(
        self,
        url: str,
        dest: Path,
        progress_callback: ProgressCallback | None = None,
        progress_meta: dict[str, Any] | None = None,
        *,
        expected_size: int | None = None,
    ) -> int:
        timeout = httpx.Timeout(float(self._settings.download_timeout_seconds))
        dest.parent.mkdir(parents=True, exist_ok=True)

        existing_size = dest.stat().st_size if dest.exists() else 0
        can_parallel = (
            existing_size == 0
            and isinstance(expected_size, int)
            and expected_size >= int(self._settings.download_parallel_min_bytes)
            and int(self._settings.download_max_threads) > 1
        )

        if can_parallel:
            workers = min(
                int(self._settings.download_max_threads),
                max(2, int(expected_size // (8 * 1024 * 1024)) + 1),
            )
            workers = max(2, workers)
            try:
                logger.info(
                    "download.parallel.start url=%s workers=%s expected_size=%s",
                    url,
                    workers,
                    expected_size,
                )
                size = self._download_parallel_ranges(
                    url,
                    dest,
                    int(expected_size),
                    workers,
                    progress_callback=progress_callback,
                    progress_meta=progress_meta,
                )
                if size == int(expected_size):
                    logger.info("download.parallel.done url=%s bytes=%s", url, size)
                    return size
                logger.warning(
                    "download.parallel.size_mismatch url=%s got=%s expected=%s; fallback to single stream",
                    url,
                    size,
                    expected_size,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("download.parallel.fallback url=%s error=%s", url, exc)
                try:
                    if dest.exists():
                        dest.unlink()
                except OSError:
                    pass

        headers: dict[str, str] = {}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

        with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as response:
            if response.status_code == 416:
                if progress_callback is not None:
                    payload = dict(progress_meta or {})
                    payload.update(
                        {
                            "file_bytes_downloaded": existing_size,
                            "file_bytes_total": existing_size,
                            "speed_bps": 0,
                            "done": True,
                        }
                    )
                    progress_callback(payload)
                return existing_size

            response.raise_for_status()
            append = response.status_code == 206 and existing_size > 0
            if not append:
                existing_size = 0

            total_size = self._extract_total_size(response, append=append, existing_size=existing_size)
            mode = "ab" if append else "wb"
            start_ts = time.monotonic()
            bytes_this_session = 0
            last_emit_ts = start_ts

            def emit(done: bool = False) -> None:
                nonlocal last_emit_ts
                if progress_callback is None:
                    return
                now = time.monotonic()
                if not done and (now - last_emit_ts) < 0.35:
                    return

                elapsed = max(now - start_ts, 1e-6)
                file_downloaded = existing_size + bytes_this_session
                speed_bps = int(bytes_this_session / elapsed)

                payload = dict(progress_meta or {})
                payload.update(
                    {
                        "file_bytes_downloaded": file_downloaded,
                        "file_bytes_total": total_size,
                        "speed_bps": speed_bps,
                        "done": done,
                    }
                )
                progress_callback(payload)
                last_emit_ts = now

            emit(done=False)
            with dest.open(mode) as output:
                for chunk in response.iter_bytes(1024 * 128):
                    if not chunk:
                        continue
                    output.write(chunk)
                    bytes_this_session += len(chunk)
                    emit(done=False)

            emit(done=True)

        return dest.stat().st_size

    def _try_fetch_json(self, url: str) -> dict[str, Any] | None:
        timeout = httpx.Timeout(float(self._settings.download_timeout_seconds))
        try:
            response = httpx.get(url, timeout=timeout, follow_redirects=True)
            if response.status_code != 200:
                logger.debug("Manifest fetch non-200: url=%s status=%s", url, response.status_code)
                return None
            return response.json()
        except Exception as exc:
            logger.debug("Manifest fetch failed: url=%s error=%s", url, exc)
            return None

    def _try_fetch_binary(
        self,
        url: str,
        dest: Path,
        progress_callback: ProgressCallback | None = None,
        *,
        min_size_bytes: int = 1,
        artifact_kind: str = "binary",
    ) -> bool:
        try:
            size = self._download_with_resume(url, dest, progress_callback=progress_callback)
            if size < min_size_bytes:
                logger.warning(
                    "download.binary.too_small kind=%s url=%s path=%s size=%s minimum=%s",
                    artifact_kind,
                    url,
                    dest,
                    size,
                    min_size_bytes,
                )
                if dest.exists():
                    try:
                        dest.unlink()
                    except OSError as exc:
                        logger.debug("download.binary.cleanup_failed path=%s error=%s", dest, exc)
                return False
            return True
        except Exception as exc:
            logger.debug("Binary fetch failed: url=%s path=%s error=%s", url, dest, exc)
            return False

    @staticmethod
    def _artifact_names(artifact: DownloadedArtifact) -> set[str]:
        return {
            artifact.local_path.name.lower(),
            Path(artifact.relative_path).name.lower(),
            Path(artifact.target_path).name.lower(),
        }

    @classmethod
    def _derive_metadata_presence(cls, artifacts: list[DownloadedArtifact]) -> tuple[bool, bool]:
        tmd_present = False
        ticket_present = False
        for artifact in artifacts:
            kind = artifact.kind.lower()
            names = cls._artifact_names(artifact)

            if kind == "tmd" or "tmd" in names or any(name.endswith(".tmd") for name in names):
                tmd_present = True

            if kind == "ticket" or "cetk" in names or any(name.endswith(".tik") for name in names):
                ticket_present = True

        return tmd_present, ticket_present

    def _materialize_manifest(
        self,
        title_id: str,
        manifest: dict,
        work_dir: Path,
    ) -> list[DownloadedArtifact]:
        artifacts: list[DownloadedArtifact] = []
        files = manifest.get("files", [])
        for index, file_spec in enumerate(files):
            if not isinstance(file_spec, dict):
                continue
            relative_path = str(file_spec.get("path", f"content/{index:04x}.bin"))
            target_path = str(file_spec.get("target_path", f"/usr/title/{title_id}/{relative_path}"))
            kind = str(file_spec.get("kind", "content"))
            source_url = str(file_spec.get("url", "")).strip()

            if not source_url:
                raise RuntimeError(f"Manifest file entry missing url for {relative_path}")

            local_path = work_dir / relative_path
            expected_size = file_spec.get("size")
            if not isinstance(expected_size, int):
                expected_size = None
            self._download_with_resume(source_url, local_path, expected_size=expected_size)

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

    def download_title(
        self,
        title_id: str,
        region: str,
        allow_fake_tickets: bool = True,
        progress_callback: ProgressCallback | None = None,
    ) -> DownloadResult:
        title_id = title_id.lower()
        work_dir = self._settings.artifacts_dir / title_id
        work_dir.mkdir(parents=True, exist_ok=True)

        artifacts: list[DownloadedArtifact] = []
        tmd_present = False
        ticket_present = False
        tmd_info: TmdInfo | None = None
        cetk_bytes: bytes | None = None
        fake_ticket = False

        logger.info(
            "download.start title_id=%s region=%s base=%s allow_fake_tickets=%s",
            title_id,
            region,
            self._settings.nus_base_url,
            allow_fake_tickets,
        )

        def build_progress_handler(
            *,
            file_kind: str,
            current_file: str,
            phase_start: float,
            phase_span: float,
            content_id: str | None = None,
        ) -> ProgressCallback:
            def _handler(payload: dict[str, Any]) -> None:
                if progress_callback is None:
                    return

                file_downloaded = int(payload.get("file_bytes_downloaded") or 0)
                file_total_raw = payload.get("file_bytes_total")
                file_total = int(file_total_raw) if isinstance(file_total_raw, int | float) else None
                speed_bps = int(payload.get("speed_bps") or 0)
                done = bool(payload.get("done"))

                if file_total and file_total > 0:
                    file_progress = max(0.0, min(1.0, file_downloaded / file_total))
                else:
                    file_progress = 1.0 if done else 0.0

                overall_progress = max(0.0, min(1.0, phase_start + phase_span * file_progress))

                progress_callback(
                    {
                        "title_id": title_id,
                        "region": region,
                        "file_kind": file_kind,
                        "current_file": current_file,
                        "content_id": content_id,
                        "file_bytes_downloaded": file_downloaded,
                        "file_bytes_total": file_total,
                        "speed_bps": speed_bps,
                        "file_progress": file_progress,
                        "phase_progress": overall_progress,
                        "overall_progress": overall_progress,
                        "done": done,
                    }
                )

            return _handler

        if self._settings.nus_base_url:
            base = self._settings.nus_base_url.rstrip("/")
            manifest_url = f"{base}/{title_id}/manifest.json"
            manifest = self._try_fetch_json(manifest_url)
            if manifest is not None:
                logger.info("download.manifest.hit title_id=%s url=%s", title_id, manifest_url)
                manifest_artifacts = self._materialize_manifest(title_id, manifest, work_dir)
                artifacts.extend(manifest_artifacts)
                tmd_present, ticket_present = self._derive_metadata_presence(manifest_artifacts)

            if not artifacts:
                tmd_path = work_dir / "tmd"
                cetk_path = work_dir / "cetk"

                logger.info("download.tmd.start title_id=%s", title_id)
                tmd_present = self._try_fetch_binary(
                    f"{base}/{title_id}/tmd",
                    tmd_path,
                    progress_callback=build_progress_handler(
                        file_kind="tmd",
                        current_file="tmd",
                        phase_start=0.0,
                        phase_span=0.05,
                    ),
                    min_size_bytes=_MIN_TMD_DOWNLOAD_SIZE,
                    artifact_kind="tmd",
                )

                logger.info("download.ticket.start title_id=%s", title_id)
                ticket_present = self._try_fetch_binary(
                    f"{base}/{title_id}/cetk",
                    cetk_path,
                    progress_callback=build_progress_handler(
                        file_kind="ticket",
                        current_file="cetk",
                        phase_start=0.05,
                        phase_span=0.05,
                    ),
                    min_size_bytes=_MIN_CETK_DOWNLOAD_SIZE,
                    artifact_kind="ticket",
                )

                if tmd_present:
                    try:
                        tmd_info = parse_tmd_bytes(tmd_path.read_bytes())
                        logger.info(
                            "download.tmd.parsed title_id=%s content_count=%s record_size=0x%x",
                            title_id,
                            tmd_info.content_count,
                            tmd_info.record_size,
                        )
                    except (TmdError, OSError) as exc:
                        logger.exception("download.tmd.parse_failed title_id=%s error=%s", title_id, exc)
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
                elif allow_fake_tickets:
                    try:
                        cetk_bytes = generate_fake_cetk(title_id)
                        cetk_path.write_bytes(cetk_bytes)
                        ticket_present = True
                        fake_ticket = True
                        logger.warning("download.ticket.synthetic title_id=%s", title_id)
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
                    except Exception as exc:
                        logger.exception("download.ticket.synthetic_failed title_id=%s error=%s", title_id, exc)

                if tmd_info is not None and tmd_info.contents:
                    content_total = max(1, len(tmd_info.contents))
                    for content_index, record in enumerate(tmd_info.contents):
                        content_path = work_dir / f"{record.content_id_hex}.app"
                        content_url = f"{base}/{title_id}/{record.content_id_hex}"
                        phase_start = 0.10 + (0.90 * content_index / content_total)
                        phase_span = 0.90 / content_total

                        logger.info(
                            "download.content.start title_id=%s content=%s index=%s/%s",
                            title_id,
                            record.content_id_hex,
                            content_index + 1,
                            content_total,
                        )

                        try:
                            self._download_with_resume(
                                content_url,
                                content_path,
                                progress_callback=build_progress_handler(
                                    file_kind="content",
                                    current_file=f"{record.content_id_hex}.app",
                                    phase_start=phase_start,
                                    phase_span=phase_span,
                                    content_id=record.content_id_hex,
                                ),
                                expected_size=int(record.size),
                            )
                        except Exception:
                            logger.exception(
                                "download.content.failed title_id=%s content=%s url=%s",
                                title_id,
                                record.content_id_hex,
                                content_url,
                            )
                            raise

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

        total_bytes = sum(item.size for item in artifacts)
        logger.info(
            "download.done title_id=%s artifacts=%s bytes=%s tmd=%s ticket=%s fake_ticket=%s",
            title_id,
            len(artifacts),
            total_bytes,
            tmd_present,
            ticket_present,
            fake_ticket,
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
            fake_ticket=fake_ticket,
        )
