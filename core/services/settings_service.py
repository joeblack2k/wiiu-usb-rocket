import json

from core.config import Settings
from core.db import session_scope
from core.models.entities import Setting


class SettingsService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def bootstrap_defaults(self) -> None:
        self.set_bool("allow_fallback", self._settings.allow_fallback)
        self.set_bool("dry_run", self._settings.dry_run)
        self.set_bool("first_write_confirmed", self._settings.first_write_confirmed)
        self._set_default("enable_downloads", True)
        self._set_default("allow_fake_tickets", True)

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

    def get_runtime_settings(self) -> dict[str, bool]:
        return {
            "allow_fallback": self.get_bool("allow_fallback", self._settings.allow_fallback),
            "dry_run": self.get_bool("dry_run", self._settings.dry_run),
            "first_write_confirmed": self.get_bool("first_write_confirmed", self._settings.first_write_confirmed),
            "enable_downloads": self.get_bool("enable_downloads", True),
            "allow_fake_tickets": self.get_bool("allow_fake_tickets", True),
        }

