from pathlib import Path

import pytest

from core.config import Settings
from core.nus.tmd import ContentRecord, TmdInfo
from core.services.download_service import DownloadResult, DownloadService, DownloadedArtifact
from core.services.install_analyzer import InstallAnalyzer


def _artifact(tmp_path: Path, size: int = 32) -> DownloadedArtifact:
    p = tmp_path / "content.app"
    p.write_bytes(b"a" * size)
    return DownloadedArtifact(
        kind="content",
        local_path=p,
        relative_path="00000000.app",
        target_path="/usr/title/0005000010101a00/content/00000000.app",
        size=size,
        sha256="deadbeef",
    )


def _settings(tmp_path: Path, nus_base_url: str = "https://mirror.invalid") -> Settings:
    otp_path = tmp_path / "otp.bin"
    seeprom_path = tmp_path / "seeprom.bin"
    otp_path.write_bytes(bytes([0x42] * 0x400))
    seeprom_path.write_bytes(bytes([0x24] * 0x200))

    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'app.db'}",
        otp_path=otp_path,
        seeprom_path=seeprom_path,
        nus_base_url=nus_base_url,
        dry_run=True,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    return settings


def test_analyzer_requires_fallback_when_tmd_not_parsed(tmp_path: Path) -> None:
    analyzer = InstallAnalyzer(max_direct_file_bytes=1024 * 1024)
    result = DownloadResult(
        title_id="0005000010101a00",
        region="EUR",
        work_dir=tmp_path,
        artifacts=[_artifact(tmp_path)],
        tmd_present=True,
        ticket_present=True,
        tmd_info=None,
        cetk_bytes=b"dummy",
    )

    analysis = analyzer.analyze(result)

    assert analysis.requires_fallback is True
    assert "tmd_not_parsed" in analysis.reasons
    assert analysis.direct_playable_possible is False


def test_analyzer_allows_direct_when_ticket_and_tmd_present(tmp_path: Path) -> None:
    analyzer = InstallAnalyzer(max_direct_file_bytes=1024 * 1024)
    tmd_info = TmdInfo(
        content_count=1,
        contents=[
            ContentRecord(content_id=0, content_id_hex="00000000", index=b"\x00\x00", size=32),
        ],
    )
    result = DownloadResult(
        title_id="0005000010101a00",
        region="EUR",
        work_dir=tmp_path,
        artifacts=[_artifact(tmp_path)],
        tmd_present=True,
        ticket_present=True,
        tmd_info=tmd_info,
        cetk_bytes=b"dummy",
    )

    analysis = analyzer.analyze(result)

    assert analysis.requires_fallback is False
    assert analysis.direct_playable_possible is True
    assert "tmd_not_parsed" not in analysis.reasons


def test_download_rejects_tiny_tmd_and_ticket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    service = DownloadService(settings)

    monkeypatch.setattr(service, "_try_fetch_json", lambda _url: None)

    def fake_download(_url: str, dest: Path, progress_callback=None, progress_meta=None) -> int:
        del progress_callback, progress_meta
        if dest.name in {"tmd", "cetk"}:
            payload = b"x" * 64
        else:
            payload = b"content"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return len(payload)

    monkeypatch.setattr(service, "_download_with_resume", fake_download)

    result = service.download_title("0005000010101a00", "EUR", allow_fake_tickets=False)

    assert result.tmd_present is False
    assert result.ticket_present is False
    assert [artifact.kind for artifact in result.artifacts] == ["content"]
    assert (result.work_dir / "tmd").exists() is False
    assert (result.work_dir / "cetk").exists() is False


def test_download_manifest_missing_url_is_hard_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    service = DownloadService(settings)

    manifest = {
        "files": [
            {
                "path": "content/00000000.app",
                "kind": "content",
            }
        ]
    }
    monkeypatch.setattr(service, "_try_fetch_json", lambda _url: manifest)

    with pytest.raises(RuntimeError, match="missing url"):
        service.download_title("0005000010101a00", "EUR", allow_fake_tickets=False)


def test_download_manifest_presence_comes_from_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    service = DownloadService(settings)

    manifest = {
        "tmd_present": False,
        "ticket_present": False,
        "files": [
            {
                "url": "https://mirror.invalid/tmd",
                "path": "meta/title.tmd",
                "kind": "content",
            },
            {
                "url": "https://mirror.invalid/cetk",
                "path": "meta/cetk",
                "kind": "content",
            },
            {
                "url": "https://mirror.invalid/content",
                "path": "content/00000000.app",
                "kind": "content",
            },
        ],
    }
    monkeypatch.setattr(service, "_try_fetch_json", lambda _url: manifest)

    def fake_download(url: str, dest: Path, progress_callback=None, progress_meta=None) -> int:
        del progress_callback, progress_meta
        if url.endswith("/tmd"):
            payload = b"t" * 0xB04
        elif url.endswith("/cetk"):
            payload = b"c" * 0x1E4
        else:
            payload = b"payload"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return len(payload)

    monkeypatch.setattr(service, "_download_with_resume", fake_download)

    result = service.download_title("0005000010101a00", "EUR", allow_fake_tickets=False)

    assert result.tmd_present is True
    assert result.ticket_present is True
    assert {artifact.relative_path for artifact in result.artifacts} == {
        "meta/title.tmd",
        "meta/cetk",
        "content/00000000.app",
    }


def test_download_manifest_flags_do_not_override_missing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    service = DownloadService(settings)

    manifest = {
        "tmd_present": True,
        "ticket_present": True,
        "files": [
            {
                "url": "https://mirror.invalid/content",
                "path": "content/00000000.app",
                "kind": "content",
            }
        ],
    }
    monkeypatch.setattr(service, "_try_fetch_json", lambda _url: manifest)

    def fake_download(_url: str, dest: Path, progress_callback=None, progress_meta=None) -> int:
        del progress_callback, progress_meta
        payload = b"payload"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return len(payload)

    monkeypatch.setattr(service, "_download_with_resume", fake_download)

    result = service.download_title("0005000010101a00", "EUR", allow_fake_tickets=False)

    assert result.tmd_present is False
    assert result.ticket_present is False
