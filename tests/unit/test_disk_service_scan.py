import json
from pathlib import Path

import pytest

from core.config import Settings
from core.crypto import OTP_SIZE, SEEPROM_SIZE
from core.db import init_db, init_engine
from core.services.disk_service import DiskService
from core.services.wfs_adapter import AttachResult, BaseWfsAdapter


class SimulatedAttachAdapter(BaseWfsAdapter):
    backend_name = "simulated"

    def attach(self, device_path: str, otp_path: Path, seeprom_path: Path) -> AttachResult:
        return AttachResult(
            attached=True,
            disk_id="sim-disk",
            wfs_verified=True,
            key_verified=True,
            fingerprint="fingerprint-1",
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
        raise NotImplementedError

    def integrity_check(self, scope: str = "/") -> dict:
        raise NotImplementedError

    def detach(self) -> None:
        raise NotImplementedError


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


def test_scan_marks_active_verified_disk_as_wfs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _init(tmp_path)
    service = DiskService(settings, SimulatedAttachAdapter())

    service.attach_device("/dev/sdb")

    lsblk_payload = {
        "blockdevices": [
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "size": "238G",
                "type": "disk",
                "model": "Storage Device",
                "fstype": None,
            }
        ]
    }

    monkeypatch.setattr(
        "core.services.disk_service.subprocess.check_output",
        lambda *args, **kwargs: json.dumps(lsblk_payload),
    )
    monkeypatch.setattr(service, "_is_block_device", lambda path: path == "/dev/sdb")
    monkeypatch.setattr(service, "_probe_wfs_signature", lambda _path: False)

    payload = service.scan_devices()

    assert len(payload["devices"]) == 1
    device = payload["devices"][0]
    assert device["path"] == "/dev/sdb"
    assert device["is_wfs"] is True
    assert device["attachable"] is True
    assert device["reason"] is None
