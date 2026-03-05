from pathlib import Path

from core.config import Settings
from core.crypto import OTP_SIZE, SEEPROM_SIZE
from core.db import init_db, init_engine
from core.services.disk_service import DiskService
from core.services.wfs_adapter import AttachResult, BaseWfsAdapter, WfsAdapterError


class RuntimeAdapter(BaseWfsAdapter):
    backend_name = "simulated"

    def __init__(self) -> None:
        self.attached = False
        self.attach_calls: list[str] = []

    def attach(self, device_path: str, otp_path: Path, seeprom_path: Path) -> AttachResult:
        self.attached = True
        self.attach_calls.append(device_path)
        return AttachResult(
            attached=True,
            disk_id="sim-disk",
            wfs_verified=True,
            key_verified=True,
            fingerprint=f"fp-{len(self.attach_calls)}",
        )

    def mkdir(self, path: str) -> None:
        raise NotImplementedError

    def create_file(self, path: str, size_hint: int = 0) -> None:
        raise NotImplementedError

    def write_stream(self, path: str, data: bytes, offset: int = 0) -> int:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        if not self.attached:
            raise WfsAdapterError("wfs_core is not attached")

    def integrity_check(self, scope: str = "/") -> dict:
        return {"ok": self.attached}

    def detach(self) -> None:
        self.attached = False


def _init(tmp_path: Path) -> Settings:
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        otp_path=tmp_path / "otp.bin",
        seeprom_path=tmp_path / "seeprom.bin",
    )
    settings.otp_path.write_bytes(b"\x00" * OTP_SIZE)
    settings.seeprom_path.write_bytes(b"\x00" * SEEPROM_SIZE)
    init_engine(settings)
    init_db()
    return settings


def test_runtime_attachment_status_reports_false_when_adapter_detached(tmp_path: Path) -> None:
    settings = _init(tmp_path)
    adapter = RuntimeAdapter()
    service = DiskService(settings, adapter)

    service.attach_device("/dev/sdb")
    adapter.detach()

    ok, error = service.runtime_attachment_status()
    assert ok is False
    assert "not attached" in (error or "")


def test_restore_runtime_attachment_reattaches_last_active_disk(tmp_path: Path) -> None:
    settings = _init(tmp_path)
    adapter = RuntimeAdapter()
    service = DiskService(settings, adapter)

    service.attach_device("/dev/sdb")
    adapter.detach()

    restored, error = service.restore_runtime_attachment()

    assert restored is True
    assert error is None
    assert adapter.attach_calls[-1] == "/dev/sdb"

    ok, status_error = service.runtime_attachment_status()
    assert ok is True
    assert status_error is None
