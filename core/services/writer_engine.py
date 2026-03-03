import hashlib
from pathlib import Path

from core.services.download_service import DownloadResult
from core.services.queue_service import QueueService
from core.services.settings_service import SettingsService
from core.services.wfs_adapter import BaseWfsAdapter, WfsAdapterError


class WriterEngine:
    def __init__(self, wfs_adapter: BaseWfsAdapter, queue_service: QueueService, settings_service: SettingsService):
        self._wfs_adapter = wfs_adapter
        self._queue_service = queue_service
        self._settings_service = settings_service

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _resume_written_paths(self, job_id: str) -> set[str]:
        events = self._queue_service.get_job_events(job_id, event_type="file_written")
        paths = set()
        for event in events:
            payload = event.get("payload", {})
            path = payload.get("target_path")
            if isinstance(path, str):
                paths.add(path)
        return paths

    def _target_path(self, title_id: str, artifact_target_path: str, fallback: bool, local_name: str) -> str:
        if fallback:
            return f"/install/{title_id}/{local_name}"
        if artifact_target_path.startswith("/"):
            return artifact_target_path
        return f"/usr/title/{title_id}/content/{local_name}"

    def write_download_result(self, job_id: str, result: DownloadResult, fallback: bool = False) -> dict:
        dry_run = self._settings_service.get_bool("dry_run", default=True)
        first_write_confirmed = self._settings_service.get_bool("first_write_confirmed", default=False)

        if not dry_run and not first_write_confirmed:
            raise WfsAdapterError("First-write confirmation is required before mutating WFS")

        already_written = self._resume_written_paths(job_id)
        written_files = 0
        written_bytes = 0

        for artifact in result.artifacts:
            target_path = self._target_path(
                result.title_id,
                artifact.target_path,
                fallback=fallback,
                local_name=artifact.relative_path,
            )
            parent_path = str(Path(target_path).parent).replace("\\", "/")

            if target_path in already_written:
                continue

            if dry_run:
                self._queue_service.add_job_event(
                    job_id,
                    "dry_run_file",
                    {
                        "target_path": target_path,
                        "size": artifact.size,
                        "sha256": artifact.sha256,
                    },
                )
                written_files += 1
                written_bytes += artifact.size
                continue

            self._wfs_adapter.mkdir(parent_path)
            self._wfs_adapter.create_file(target_path, artifact.size)

            data = artifact.local_path.read_bytes()
            offset = 0
            wrote = self._wfs_adapter.write_stream(target_path, data, offset)
            if wrote != len(data):
                raise WfsAdapterError(f"Short write for {target_path}: wrote {wrote}, expected {len(data)}")
            offset = wrote

            local_hash = self._sha256(artifact.local_path)
            if local_hash.lower() != artifact.sha256.lower():
                raise WfsAdapterError(f"Artifact hash drift detected for {artifact.relative_path}")

            self._queue_service.add_job_event(
                job_id,
                "file_written",
                {
                    "target_path": target_path,
                    "bytes": offset,
                    "sha256": local_hash,
                    "fallback": fallback,
                },
            )
            written_files += 1
            written_bytes += offset

        if not dry_run:
            self._wfs_adapter.flush()

        report = {
            "fallback": fallback,
            "written_files": written_files,
            "written_bytes": written_bytes,
            "dry_run": dry_run,
            "integrity": self._wfs_adapter.integrity_check("/"),
        }
        self._queue_service.add_job_event(job_id, "write_report", report)
        return report

    def staged_diagnostics(self, job_id: str) -> dict:
        events = self._queue_service.get_job_events(job_id)
        return {"events": events, "event_count": len(events)}
