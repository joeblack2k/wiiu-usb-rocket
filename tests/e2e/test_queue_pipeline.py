import hashlib
from pathlib import Path

from apps.worker.runner import QueueWorker
from core.config import Settings
from core.db import init_db, init_engine
from core.nus.tmd import ContentRecord, TmdInfo
from core.services.download_service import DownloadResult, DownloadService, DownloadedArtifact
from core.services.install_analyzer import InstallAnalyzer
from core.services.queue_service import QueueService
from core.services.settings_service import SettingsService
from core.services.wfs_adapter import SimulatedWfsAdapter
from core.services.writer_engine import WriterEngine


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_keys(tmp_path: Path) -> tuple[Path, Path]:
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    otp_path = keys_dir / "otp.bin"
    seeprom_path = keys_dir / "seeprom.bin"
    otp_path.write_bytes(bytes([0x42] * 0x400))
    seeprom_path.write_bytes(bytes([0x24] * 0x200))
    return otp_path, seeprom_path


def test_queue_pipeline_completes_done_with_direct_mode(tmp_path: Path) -> None:
    otp_path, seeprom_path = write_keys(tmp_path)
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'app.db'}",
        otp_path=otp_path,
        seeprom_path=seeprom_path,
        wfs_backend="simulated",
        dry_run=True,
        allow_fallback=False,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.simulated_wfs_root.mkdir(parents=True, exist_ok=True)

    init_engine(settings)
    init_db()

    settings_service = SettingsService(settings)
    settings_service.bootstrap_defaults()

    queue_service = QueueService()
    download_service = DownloadService(settings)

    def fake_download(title_id: str, region: str) -> DownloadResult:
        work_dir = settings.artifacts_dir / title_id
        work_dir.mkdir(parents=True, exist_ok=True)
        content = b"test-content"
        local_path = work_dir / "content.bin"
        local_path.write_bytes(content)
        artifact = DownloadedArtifact(
            kind="content",
            local_path=local_path,
            relative_path="content.bin",
            target_path=f"/usr/title/{title_id}/content/content.bin",
            size=len(content),
            sha256=sha256(content),
        )
        tmd_info = TmdInfo(
            content_count=1,
            contents=[
                ContentRecord(
                    content_id=0,
                    content_id_hex="00000000",
                    index=b"\x00\x00",
                    size=len(content),
                )
            ],
        )
        return DownloadResult(
            title_id=title_id,
            region=region,
            work_dir=work_dir,
            artifacts=[artifact],
            tmd_present=True,
            ticket_present=True,
            tmd_info=tmd_info,
            cetk_bytes=b"",
        )

    download_service.download_title = fake_download  # type: ignore[method-assign]

    adapter = SimulatedWfsAdapter(settings)
    adapter.attach("/dev/sim0", otp_path, seeprom_path)
    writer = WriterEngine(adapter, queue_service, settings_service)
    analyzer = InstallAnalyzer(max_direct_file_bytes=1024 * 1024)
    worker = QueueWorker(queue_service, download_service, analyzer, writer, settings_service)

    queue_item = queue_service.add_item("0005000010101A00", "EUR", "direct")
    result = worker.execute_queue_item(queue_item["id"])

    assert result["state"] == "DONE"
    current_queue = queue_service.list_items()
    assert current_queue[0]["state"] == "DONE"

    job = queue_service.get_job(result["job_id"])
    assert job is not None
    assert job["state"] == "DONE"

