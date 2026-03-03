from pathlib import Path

from core.config import Settings
from core.services.wfs_adapter import SimulatedWfsAdapter


def make_keys(tmp_path: Path) -> tuple[Path, Path]:
    otp_path = tmp_path / "otp.bin"
    seeprom_path = tmp_path / "seeprom.bin"
    otp_path.write_bytes(bytes([0x10] * 0x400))
    seeprom_path.write_bytes(bytes([0x20] * 0x200))
    return otp_path, seeprom_path


def test_simulated_wfs_create_write_delete(tmp_path: Path) -> None:
    otp_path, seeprom_path = make_keys(tmp_path)

    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        wfs_backend="simulated",
    )
    adapter = SimulatedWfsAdapter(settings)

    attach = adapter.attach("/dev/test0", otp_path, seeprom_path)
    assert attach.attached is True

    adapter.mkdir("/usr/title/0005000010101A00/content")
    adapter.create_file("/usr/title/0005000010101A00/content/content.bin", size_hint=16)
    wrote = adapter.write_stream("/usr/title/0005000010101A00/content/content.bin", b"hello world", 0)
    assert wrote == 11

    report = adapter.integrity_check("/usr")
    assert report["ok"] is True
    assert report["files"] >= 1

    adapter.delete("/usr/title/0005000010101A00/content/content.bin")
    report_after_delete = adapter.integrity_check("/usr")
    assert report_after_delete["ok"] is True

