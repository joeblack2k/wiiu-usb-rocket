import json
import os

from core.config import Settings
from core.db import session_scope
from core.models.entities import Setting


class SettingsService:
    def __init__(self, settings: Settings):
        self._settings = settings

    @staticmethod
    def _normalize_common_key(value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            return ""
        try:
            raw = bytes.fromhex(normalized)
        except ValueError as exc:
            raise ValueError(f"Common key must be valid hex: {exc}") from exc
        if len(raw) != 16:
            raise ValueError(f"Common key must be exactly 32 hex chars (16 bytes), got {len(raw)} bytes")
        return normalized

    def bootstrap_defaults(self) -> None:
        self.set_bool("allow_fallback", self._settings.allow_fallback)
        self.set_bool("dry_run", self._settings.dry_run)
        self.set_bool("first_write_confirmed", self._settings.first_write_confirmed)
        self._set_default("enable_downloads", True)
        self._set_default("allow_fake_tickets", False)

    def bootstrap_common_key_env(self) -> bool:
        existing = os.environ.get("WIIU_COMMON_KEY", "").strip()
        if existing:
            try:
                os.environ["WIIU_COMMON_KEY"] = self._normalize_common_key(existing)
                return True
            except ValueError:
                return False

        stored = self.get_string("wiiu_common_key", "")
        if not stored:
            return False

        try:
            normalized = self._normalize_common_key(stored)
        except ValueError:
            return False

        os.environ["WIIU_COMMON_KEY"] = normalized
        return True

    def common_key_source(self) -> str:
        env_value = os.environ.get("WIIU_COMMON_KEY", "").strip()
        if env_value:
            try:
                self._normalize_common_key(env_value)
                return "env"
            except ValueError:
                pass

        stored = self.get_string("wiiu_common_key", "")
        if stored:
            try:
                self._normalize_common_key(stored)
                return "stored"
            except ValueError:
                return "invalid"

        return "missing"

    def common_key_present(self) -> bool:
        return self.common_key_source() in {"env", "stored"}

    def set_common_key(self, value: str) -> str:
        normalized = self._normalize_common_key(value)
        self.set_string("wiiu_common_key", normalized)
        os.environ["WIIU_COMMON_KEY"] = normalized
        return normalized

    def clear_common_key(self) -> None:
        self.set_string("wiiu_common_key", "")
        os.environ.pop("WIIU_COMMON_KEY", None)

    def get_stored_common_key(self) -> str:
        value = self.get_string("wiiu_common_key", "")
        if not value:
            return ""
        try:
            return self._normalize_common_key(value)
        except ValueError:
            return ""

    def _set_default(self, key: str, value: bool) -> None:
        with session_scope() as session:
            if session.get(Setting, key) is None:
                session.add(Setting(key=key, value_json=json.dumps(value)))

    def get_bool(self, key: str, default: bool = False) -> bool:
        with session_scope() as session:
            record = session.get(Setting, key)
            if record is None:
                return default
            try:
                return bool(json.loads(record.value_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                return default

    def set_bool(self, key: str, value: bool) -> bool:
        with session_scope() as session:
            record = session.get(Setting, key)
            if record is None:
                record = Setting(key=key, value_json=json.dumps(bool(value)))
                session.add(record)
            else:
                record.value_json = json.dumps(bool(value))
        return value

    def get_string(self, key: str, default: str = "") -> str:
        with session_scope() as session:
            record = session.get(Setting, key)
            if record is None:
                return default
            try:
                value = json.loads(record.value_json)
            except (TypeError, ValueError, json.JSONDecodeError):
                return default
            if value is None:
                return default
            return str(value)

    def set_string(self, key: str, value: str) -> str:
        with session_scope() as session:
            record = session.get(Setting, key)
            encoded = json.dumps(str(value))
            if record is None:
                record = Setting(key=key, value_json=encoded)
                session.add(record)
            else:
                record.value_json = encoded
        return value

    def get_runtime_settings(self) -> dict[str, bool | str]:
        return {
            "allow_fallback": self.get_bool("allow_fallback", self._settings.allow_fallback),
            "dry_run": self.get_bool("dry_run", self._settings.dry_run),
            "first_write_confirmed": self.get_bool("first_write_confirmed", self._settings.first_write_confirmed),
            "enable_downloads": self.get_bool("enable_downloads", True),
            "allow_fake_tickets": self.get_bool("allow_fake_tickets", False),
            "common_key_present": self.common_key_present(),
            "common_key_source": self.common_key_source(),
        }
