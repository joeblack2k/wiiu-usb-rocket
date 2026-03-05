import os
import tempfile
from pathlib import Path

from core.config import Settings
from core.services.disk_service import DiskService
from core.services.settings_service import SettingsService


class ReadinessService:
    def __init__(self, settings: Settings, settings_service: SettingsService, disk_service: DiskService):
        self._settings = settings
        self._settings_service = settings_service
        self._disk_service = disk_service

    @staticmethod
    def _check_writable_dir(path: Path) -> tuple[bool, str | None]:
        if not path.exists():
            return False, "missing"
        if not path.is_dir():
            return False, "not_a_directory"

        try:
            fd, candidate = tempfile.mkstemp(prefix=".readyz-", dir=str(path))
        except OSError as exc:
            return False, str(exc)

        os.close(fd)
        try:
            os.unlink(candidate)
        except OSError:
            pass
        return True, None

    @staticmethod
    def _format_dir_message(path: Path, ok: bool, error: str | None) -> str:
        if ok:
            return f"{path} is writable"
        if error:
            return f"{path} is not writable ({error})"
        return f"{path} is not writable"

    def evaluate(self) -> dict:
        runtime_settings = self._settings_service.get_runtime_settings()
        dry_run = bool(runtime_settings.get("dry_run", self._settings.dry_run))
        first_write_confirmed = bool(
            runtime_settings.get("first_write_confirmed", self._settings.first_write_confirmed)
        )

        checks: list[dict] = []

        def add_check(name: str, ok: bool, message: str, *, blocking: bool = True) -> None:
            checks.append(
                {
                    "name": name,
                    "ok": bool(ok),
                    "blocking": bool(blocking),
                    "message": message,
                }
            )

        keys_ok, keys_error = self._disk_service.keys_status()
        add_check(
            "keys_valid",
            keys_ok,
            "otp/seeprom keys are valid" if keys_ok else f"invalid key files ({keys_error or 'unknown error'})",
        )

        common_key_present = self._settings_service.common_key_present()
        common_key_source = self._settings_service.common_key_source()
        add_check(
            "common_key_present",
            common_key_present,
            (
                f"WIIU_COMMON_KEY is available ({common_key_source})"
                if common_key_present
                else "WIIU_COMMON_KEY is missing"
            ),
        )

        active_attachment = self._disk_service.get_active_attachment()
        if active_attachment is None:
            add_check("disk_attached_verified", False, "no active attached disk")
        else:
            key_verified = bool(active_attachment.get("key_verified"))
            wfs_verified = bool(active_attachment.get("wfs_verified"))
            path = str(active_attachment.get("device_path", "unknown"))
            add_check(
                "disk_attached_verified",
                key_verified and wfs_verified,
                (
                    f"active disk verified ({path})"
                    if key_verified and wfs_verified
                    else f"active disk not fully verified ({path})"
                ),
            )

        backend_name = self._disk_service.backend_name
        backend_ok = dry_run or backend_name != "simulated"
        add_check(
            "backend_not_simulated",
            backend_ok,
            (
                f"backend is {backend_name}"
                if backend_ok
                else "dry_run=false requires non-simulated backend"
            ),
            blocking=not dry_run,
        )

        first_write_ok = dry_run or first_write_confirmed
        add_check(
            "first_write_confirmed",
            first_write_ok,
            (
                f"first_write_confirmed={first_write_confirmed}"
                if first_write_ok
                else "dry_run=false requires first_write_confirmed=true"
            ),
            blocking=not dry_run,
        )

        data_dir_ok, data_dir_error = self._check_writable_dir(self._settings.data_dir)
        add_check(
            "data_dir_writable",
            data_dir_ok,
            self._format_dir_message(self._settings.data_dir, data_dir_ok, data_dir_error),
        )

        logs_dir_ok, logs_dir_error = self._check_writable_dir(self._settings.logs_dir)
        add_check(
            "logs_dir_writable",
            logs_dir_ok,
            self._format_dir_message(self._settings.logs_dir, logs_dir_ok, logs_dir_error),
        )

        blocking_failures = [check for check in checks if check["blocking"] and not check["ok"]]
        return {
            "ready": len(blocking_failures) == 0,
            "dry_run": dry_run,
            "checks": checks,
            "blocking_failures": blocking_failures,
        }
