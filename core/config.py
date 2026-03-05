from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8080

    data_dir: Path = Path("/data")
    logs_dir: Path = Path("/logs")

    db_url: str = "sqlite:////data/app.db"

    keys_dir: Path = Path("/keys")
    otp_path: Path = Path("/keys/otp.bin")
    seeprom_path: Path = Path("/keys/seeprom.bin")
    vault_archive_path: Path = Path("/keys/vault.tar.gz")

    wiiu_disk: str | None = Field(default=None, alias="WIIU_DISK")
    allow_fallback: bool = Field(default=False, alias="ALLOW_FALLBACK")

    catalog_url: str = "https://napi.v10lator.de/db?t=c"
    catalog_refresh_minutes: int = 60

    nus_base_url: str = Field(
        default="http://nus.cdn.wup.shop.nintendo.net/ccs/download",
        alias="LINK",
    )
    compatibility_mode: bool = True

    wfs_backend: str = "auto"
    dry_run: bool = True
    first_write_confirmed: bool = False

    max_parallel_installs: int = 1
    download_timeout_seconds: int = 120
    download_max_threads: int = Field(default=6, alias="DOWNLOAD_MAX_THREADS")
    download_parallel_min_bytes: int = Field(default=8 * 1024 * 1024, alias="DOWNLOAD_PARALLEL_MIN_BYTES")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def catalog_cache_path(self) -> Path:
        return self.data_dir / "catalog_cache.json"

    @property
    def simulated_wfs_root(self) -> Path:
        return self.data_dir / "simulated_wfs"

    @property
    def vault_extract_root(self) -> Path:
        return self.data_dir / "vault_cache"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
