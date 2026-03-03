import dataclasses
import hashlib
import json
import threading
import time

from core.models.enums import JobState, QueueState
from core.nus.app_decryptor import decrypt_app
from core.nus.ticket import parse_ticket_bytes
from core.services.download_service import DownloadService
from core.services.install_analyzer import InstallAnalyzer
from core.services.queue_service import QueueService
from core.services.settings_service import SettingsService
from core.services.writer_engine import WriterEngine


class QueueWorker:
    def __init__(
        self,
        queue_service: QueueService,
        download_service: DownloadService,
        analyzer: InstallAnalyzer,
        writer_engine: WriterEngine,
        settings_service: SettingsService,
    ):
        self._queue_service = queue_service
        self._download_service = download_service
        self._analyzer = analyzer
        self._writer_engine = writer_engine
        self._settings_service = settings_service

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self) -> None:
        self._running = True
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def pause(self) -> None:
        self._running = False

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def is_running(self) -> bool:
        return self._running

    def execute_queue_item(self, queue_item_id: str) -> dict:
        items = self._queue_service.list_items()
        queue_item = next((item for item in items if item["id"] == queue_item_id), None)
        if queue_item is None:
            raise RuntimeError(f"Queue item {queue_item_id} was not found")
        return self._process_queue_item(queue_item)

    def process_next(self) -> dict | None:
        queue_item = self._queue_service.next_queued_item()
        if queue_item is None:
            return None
        queue_payload = self._queue_service.serialize_queue_item(queue_item)
        return self._process_queue_item(queue_payload)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._running:
                time.sleep(0.5)
                continue
            result = self.process_next()
            if result is None:
                time.sleep(1.0)

    def _process_queue_item(self, queue_item: dict) -> dict:
        queue_item_id = queue_item["id"]
        title_id = queue_item["title_id"]
        region = queue_item["region"]

        job = self._queue_service.create_job(queue_item_id, phase="queued", progress=0.0)
        job_id = job["job_id"]

        try:
            self._queue_service.set_state(queue_item_id, QueueState.DOWNLOADING, progress=0.1)
            self._queue_service.update_job(job_id, phase="downloading", progress=0.1)
            self._queue_service.add_job_event(job_id, "phase", {"phase": "downloading"})

            allow_fake_tickets = self._settings_service.get_bool("allow_fake_tickets", True)
            t_download_start = time.monotonic()
            download_result = self._download_service.download_title(
                title_id=title_id, region=region, allow_fake_tickets=allow_fake_tickets
            )
            elapsed_download = time.monotonic() - t_download_start
            total_dl_bytes = sum(a.size for a in download_result.artifacts)
            speed_bps = int(total_dl_bytes / elapsed_download) if elapsed_download > 0 else 0
            self._queue_service.add_job_event(
                job_id,
                "download_stats",
                {"bytes": total_dl_bytes, "elapsed_sec": round(elapsed_download, 2), "speed_bps": speed_bps},
            )

            self._queue_service.set_state(queue_item_id, QueueState.DOWNLOADED, progress=0.35)
            self._queue_service.update_job(job_id, phase="downloaded", progress=0.35)

            self._queue_service.set_state(queue_item_id, QueueState.DECRYPTING, progress=0.5)
            self._queue_service.update_job(job_id, phase="decrypting", progress=0.5)

            if download_result.cetk_bytes and download_result.tmd_info is not None:
                ticket_info = parse_ticket_bytes(download_result.cetk_bytes)
                decrypted_artifacts = []
                for artifact in download_result.artifacts:
                    if artifact.kind != "content":
                        decrypted_artifacts.append(artifact)
                        continue
                    content_record = next(
                        (r for r in download_result.tmd_info.contents
                         if r.content_id_hex == artifact.local_path.stem),
                        None,
                    )
                    if content_record is None:
                        decrypted_artifacts.append(artifact)
                        continue
                    dec_path = artifact.local_path.with_suffix(".dec")
                    written = decrypt_app(
                        artifact.local_path, dec_path, ticket_info.title_key, content_record.index
                    )
                    # Truncate AES padding to actual content size from TMD
                    if content_record.size < written:
                        with dec_path.open("r+b") as fh:
                            fh.truncate(content_record.size)
                        written = content_record.size
                    # SHA1 integrity check against TMD record hash
                    # Overgeslagen bij nep-ticket: content op custom mirror kan andere hash hebben
                    if len(content_record.sha1_hash) == 20 and not download_result.fake_ticket:
                        digest = hashlib.sha1()
                        with dec_path.open("rb") as fh:
                            for chunk in iter(lambda: fh.read(65536), b""):
                                digest.update(chunk)
                        if digest.digest() != content_record.sha1_hash:
                            raise RuntimeError(
                                f"SHA1 mismatch for content {content_record.content_id_hex}: "
                                f"expected {content_record.sha1_hash.hex()}, got {digest.hexdigest()}"
                            )
                    decrypted_artifacts.append(dataclasses.replace(artifact, local_path=dec_path, size=written))
                download_result = dataclasses.replace(download_result, artifacts=decrypted_artifacts)
                self._queue_service.add_job_event(
                    job_id,
                    "decrypt",
                    {"mode": "aes_cbc", "artifacts": len(decrypted_artifacts)},
                )
            else:
                self._queue_service.add_job_event(
                    job_id,
                    "decrypt",
                    {"mode": "passthrough", "artifacts": len(download_result.artifacts)},
                )

            analysis = self._analyzer.analyze(download_result)
            self._queue_service.add_job_event(job_id, "analysis", analysis.to_dict())

            allow_fallback = self._settings_service.get_bool("allow_fallback", False)
            diagnostics = {
                "analysis": analysis.to_dict(),
                "allow_fallback": allow_fallback,
                "download": {
                    "title_id": download_result.title_id,
                    "region": download_result.region,
                    "artifacts": len(download_result.artifacts),
                    "ticket_present": download_result.ticket_present,
                    "tmd_present": download_result.tmd_present,
                    "fake_ticket": download_result.fake_ticket,
                },
            }

            if analysis.direct_playable_possible:
                self._queue_service.set_state(queue_item_id, QueueState.WRITING_WFS, progress=0.65)
                self._queue_service.update_job(job_id, phase="writing_wfs", progress=0.65)
                report = self._writer_engine.write_download_result(job_id, download_result, fallback=False)
                diagnostics["write_report"] = report

                self._queue_service.set_state(queue_item_id, QueueState.VERIFYING, progress=0.9)
                self._queue_service.update_job(job_id, phase="verifying", progress=0.9)

                self._queue_service.set_state(queue_item_id, QueueState.DONE, progress=1.0)
                self._queue_service.update_job(
                    job_id,
                    phase="done",
                    progress=1.0,
                    state=JobState.DONE,
                    message="Install completed",
                    diagnostics=diagnostics,
                )
                return {"job_id": job_id, "state": QueueState.DONE.value}

            if allow_fallback:
                self._queue_service.set_state(queue_item_id, QueueState.FALLBACK_STAGED, progress=0.75)
                self._queue_service.update_job(job_id, phase="fallback_staged", progress=0.75)
                report = self._writer_engine.write_download_result(job_id, download_result, fallback=True)
                diagnostics["write_report"] = report

                self._queue_service.set_state(queue_item_id, QueueState.DONE, progress=1.0)
                self._queue_service.update_job(
                    job_id,
                    phase="done",
                    progress=1.0,
                    state=JobState.DONE,
                    message="Fallback staged install completed",
                    diagnostics=diagnostics,
                )
                return {"job_id": job_id, "state": QueueState.DONE.value}

            diagnostics["error"] = "USB_ONLY_IMPOSSIBLE"
            self._queue_service.set_state(
                queue_item_id,
                QueueState.FAILED,
                progress=1.0,
                error_code="USB_ONLY_IMPOSSIBLE",
                error_detail=json.dumps(analysis.to_dict()),
            )
            self._queue_service.update_job(
                job_id,
                phase="failed",
                progress=1.0,
                state=JobState.FAILED,
                message="Direct playable install is impossible on USB-only path",
                diagnostics=diagnostics,
            )
            return {"job_id": job_id, "state": QueueState.FAILED.value}
        except Exception as exc:
            self._queue_service.set_state(
                queue_item_id,
                QueueState.FAILED,
                progress=1.0,
                error_code="INSTALL_FAILED",
                error_detail=str(exc),
            )
            self._queue_service.update_job(
                job_id,
                phase="failed",
                progress=1.0,
                state=JobState.FAILED,
                message=str(exc),
                diagnostics={"error": str(exc)},
            )
            self._queue_service.add_job_event(job_id, "error", {"message": str(exc)}, level="ERROR")
            return {"job_id": job_id, "state": QueueState.FAILED.value, "error": str(exc)}
