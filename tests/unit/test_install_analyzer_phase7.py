from pathlib import Path

from core.nus.tmd import ContentRecord, TmdInfo
from core.services.download_service import DownloadResult, DownloadedArtifact
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
