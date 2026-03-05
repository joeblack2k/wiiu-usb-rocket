from pathlib import Path

from core.config import Settings
from core.services.download_service import DownloadService


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        otp_path=tmp_path / "otp.bin",
        seeprom_path=tmp_path / "seeprom.bin",
        download_timeout_seconds=10,
        download_max_threads=6,
    )


def test_split_ranges_covers_full_payload(tmp_path: Path) -> None:
    service = DownloadService(_build_settings(tmp_path))
    ranges = service._split_ranges(1000, 6)
    assert ranges[0][0] == 0
    assert ranges[-1][1] == 999
    total = sum((end - start + 1) for start, end in ranges)
    assert total == 1000


def test_large_file_prefers_parallel_path(monkeypatch, tmp_path: Path) -> None:
    service = DownloadService(_build_settings(tmp_path))
    dest = tmp_path / "payload.bin"

    called = {"parallel": False}

    def fake_parallel(url, path, total_size, workers, progress_callback=None, progress_meta=None):
        called["parallel"] = True
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * total_size)
        return total_size

    monkeypatch.setattr(service, "_download_parallel_ranges", fake_parallel)

    expected = 10 * 1024 * 1024
    size = service._download_with_resume("http://example.invalid/file", dest, expected_size=expected)

    assert called["parallel"] is True
    assert size == expected
    assert dest.stat().st_size == expected
