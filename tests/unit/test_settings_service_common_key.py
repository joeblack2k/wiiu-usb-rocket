import os
from pathlib import Path

import pytest

from core.config import Settings
from core.db import init_db, init_engine
from core.services.settings_service import SettingsService

VALID_KEY = "d7b00402659ba2abd2cb0db27fa2b656"


def _init(tmp_path: Path) -> SettingsService:
    settings = Settings(
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        db_url=f"sqlite:///{tmp_path / 'settings.db'}",
        otp_path=tmp_path / "otp.bin",
        seeprom_path=tmp_path / "seeprom.bin",
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    init_engine(settings)
    init_db()
    service = SettingsService(settings)
    service.bootstrap_defaults()
    return service


def test_common_key_roundtrip_and_bootstrap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = _init(tmp_path)

    monkeypatch.delenv("WIIU_COMMON_KEY", raising=False)
    assert service.common_key_present() is False

    service.set_common_key(VALID_KEY.upper())
    assert os.environ.get("WIIU_COMMON_KEY") == VALID_KEY
    assert service.get_stored_common_key() == VALID_KEY
    assert service.common_key_source() == "env"

    monkeypatch.delenv("WIIU_COMMON_KEY", raising=False)
    assert service.common_key_source() == "stored"

    loaded = service.bootstrap_common_key_env()
    assert loaded is True
    assert os.environ.get("WIIU_COMMON_KEY") == VALID_KEY
    assert service.common_key_source() == "env"


def test_common_key_invalid_value_rejected(tmp_path: Path) -> None:
    service = _init(tmp_path)

    with pytest.raises(ValueError, match="Common key must be valid hex"):
        service.set_common_key("zz-not-hex")

    with pytest.raises(ValueError, match="32 hex chars"):
        service.set_common_key("0011")


def test_clear_common_key_clears_env_and_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = _init(tmp_path)

    service.set_common_key(VALID_KEY)
    assert service.common_key_present() is True

    service.clear_common_key()
    monkeypatch.delenv("WIIU_COMMON_KEY", raising=False)

    assert service.get_stored_common_key() == ""
    assert service.common_key_present() is False
    assert service.common_key_source() == "missing"
