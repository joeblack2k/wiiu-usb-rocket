import json
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import httpx

from core.catalog.parser import CatalogItem, parse_catalog_feed
from core.catalog.vault_archive import VaultCatalogError, load_vault_catalog
from core.config import Settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CatalogService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = threading.Lock()
        self._items: list[CatalogItem] = []
        self._last_refresh: datetime | None = None
        self._last_error: str | None = None
        self._next_retry_at: datetime | None = None
        self._source: str = "cache"
        self._load_cache_from_disk()

    def _load_cache_from_disk(self) -> None:
        cache_path = self._settings.catalog_cache_path
        if not cache_path.exists():
            return
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            items = payload.get("items", [])
            loaded: list[CatalogItem] = []
            for item in items:
                loaded.append(
                    CatalogItem(
                        title_id=str(item.get("title_id", "")).lower(),
                        name=str(item.get("name", "")),
                        region=str(item.get("region", "ALL")),
                        category=str(item.get("category", "unknown")),
                    )
                )
            refreshed_at = payload.get("refreshed_at")
            self._items = loaded
            if isinstance(refreshed_at, str):
                self._last_refresh = datetime.fromisoformat(refreshed_at)
            self._source = str(payload.get("source", "cache"))
        except Exception:
            self._items = []
            self._last_refresh = None

    def _save_cache_to_disk(self) -> None:
        cache_path = self._settings.catalog_cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "refreshed_at": (self._last_refresh or utcnow()).isoformat(),
            "source": self._source,
            "items": [asdict(item) for item in self._items],
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def refresh_if_needed(self) -> None:
        with self._lock:
            now = utcnow()
            if self._next_retry_at is not None and now < self._next_retry_at:
                return

            if self._last_refresh is None:
                self._try_refresh_locked(now)
                return
            max_age = timedelta(minutes=self._settings.catalog_refresh_minutes)
            if now - self._last_refresh > max_age:
                self._try_refresh_locked(now)

    def _try_refresh_locked(self, now: datetime) -> None:
        try:
            self._refresh_locked()
            return
        except Exception as upstream_exc:
            upstream_error = f"{type(upstream_exc).__name__}: {upstream_exc}"

        try:
            vault_items = load_vault_catalog(self._settings.vault_archive_path, self._settings.vault_extract_root)
            self._items = vault_items
            self._last_refresh = now
            self._source = "vault"
            self._last_error = f"upstream_failed: {upstream_error}"
            self._next_retry_at = now + timedelta(minutes=5)
            self._save_cache_to_disk()
            return
        except FileNotFoundError:
            self._last_error = upstream_error
        except VaultCatalogError as vault_exc:
            self._last_error = f"upstream_failed: {upstream_error}; vault_failed: {vault_exc}"
        except Exception as vault_exc:  # pragma: no cover - defensive guard
            self._last_error = f"upstream_failed: {upstream_error}; vault_failed: {type(vault_exc).__name__}: {vault_exc}"

        # avoid hammering unstable endpoints and broken local archives
        self._next_retry_at = now + timedelta(minutes=5)

    def force_refresh(self) -> None:
        with self._lock:
            self._refresh_locked()

    def _refresh_locked(self) -> None:
        timeout = httpx.Timeout(30.0)
        response = httpx.get(self._settings.catalog_url, timeout=timeout)
        response.raise_for_status()
        items = parse_catalog_feed(response.text)
        self._items = items
        self._last_refresh = utcnow()
        self._last_error = None
        self._next_retry_at = None
        self._source = "remote"
        self._save_cache_to_disk()

    def query(
        self,
        search: str = "",
        region: str = "",
        category: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        self.refresh_if_needed()
        with self._lock:
            items = self._items
            if search:
                lowered = search.lower()
                items = [
                    item
                    for item in items
                    if lowered in item.name.lower() or lowered in item.title_id.lower() or lowered in item.category.lower()
                ]
            if region:
                items = [item for item in items if item.region.lower() == region.lower()]
            if category:
                items = [item for item in items if item.category.lower() == category.lower()]

            total = len(items)
            selected = items[offset : offset + limit]
            source_age_sec = 0
            if self._last_refresh is not None:
                source_age_sec = int((utcnow() - self._last_refresh).total_seconds())

            source_status = "ok"
            if self._last_error is not None:
                if self._source == "vault" and self._items:
                    source_status = "fallback"
                else:
                    source_status = "stale" if self._items else "degraded"

            return {
                "items": [item.to_dict() for item in selected],
                "total": total,
                "source": self._source,
                "source_age_sec": source_age_sec,
                "source_status": source_status,
                "last_error": self._last_error,
            }
