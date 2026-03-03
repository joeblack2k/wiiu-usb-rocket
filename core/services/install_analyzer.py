from dataclasses import asdict, dataclass

from core.services.download_service import DownloadResult


@dataclass(slots=True)
class InstallAnalysis:
    direct_playable_possible: bool
    requires_fallback: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class InstallAnalyzer:
    def __init__(self, max_direct_file_bytes: int = 1024 * 1024):
        self._max_direct_file_bytes = max_direct_file_bytes

    def analyze(self, result: DownloadResult) -> InstallAnalysis:
        reasons: list[str] = []
        requires_fallback = False

        if not result.ticket_present:
            reasons.append("ticket_or_rights_data_not_detected")
            requires_fallback = True

        oversize = [artifact for artifact in result.artifacts if artifact.size > self._max_direct_file_bytes]
        if oversize:
            reasons.append(
                f"artifacts_exceed_direct_write_threshold:{len(oversize)}>{self._max_direct_file_bytes}"
            )

        direct_possible = len(reasons) == 0
        return InstallAnalysis(
            direct_playable_possible=direct_possible,
            requires_fallback=requires_fallback,
            reasons=reasons,
        )

