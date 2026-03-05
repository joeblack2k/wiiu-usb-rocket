from pathlib import Path

import pytest

from core.config import Settings
from core.services.disk_service import DiskService
from core.services.wfs_adapter import AttachResult, BaseWfsAdapter, WfsAdapterError


class GuardAdapter(BaseWfsAdapter):
    backend_name = "native"

    def __init__(self) -> None:
        self.attach_called = False

    def attach(self, device_path: str, otp_path: Path, seeprom_path: Path) -> AttachResult:
        self.attach_called = True
        return AttachResult(
            attached=True,
            disk_id="dummy",
            wfs_verified=True,
            key_verified=True,
            fingerprint="dummy",
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


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        otp_path=tmp_path / "missing_otp.bin",
        seeprom_path=tmp_path / "missing_seeprom.bin",
    )


def test_attach_rejects_non_dev_path_before_key_check(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    adapter = GuardAdapter()
    service = DiskService(settings, adapter)

    with pytest.raises(WfsAdapterError, match=r"Only /dev/\* block devices are accepted"):
        service.attach_device("/etc/passwd")

    assert adapter.attach_called is False


def test_attach_rejects_non_block_dev_before_key_check(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    adapter = GuardAdapter()
    service = DiskService(settings, adapter)

    with pytest.raises(WfsAdapterError, match="Target path is not a block device"):
        service.attach_device("/dev/null")

    assert adapter.attach_called is False


def test_attach_checks_keys_after_basic_device_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = build_settings(tmp_path)
    adapter = GuardAdapter()
    service = DiskService(settings, adapter)

    monkeypatch.setattr(service, "_is_block_device", lambda _path: True)
    monkeypatch.setattr(service, "_is_usb_device", lambda _path: True)

    with pytest.raises(WfsAdapterError, match="Cannot attach disk"):
        service.attach_device("/dev/sdb")

    assert adapter.attach_called is False
