import json
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import httpx

from core.catalog.parser import CatalogItem, parse_catalog_feed
from core.config import Settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CatalogService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = threading.Lock()
        self._items: list[CatalogItem] = []
        self._last_refresh: datetime | None = None
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
        except Exception:
            self._items = []
            self._last_refresh = None

    def _save_cache_to_disk(self) -> None:
        cache_path = self._settings.catalog_cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "refreshed_at": (self._last_refresh or utcnow()).isoformat(),
            "items": [asdict(item) for item in self._items],
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def refresh_if_needed(self) -> None:
        with self._lock:
            if self._last_refresh is None:
                self._refresh_locked()
                return
            max_age = timedelta(minutes=self._settings.catalog_refresh_minutes)
            if utcnow() - self._last_refresh > max_age:
                self._refresh_locked()

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

            return {
                "items": [item.to_dict() for item in selected],
                "total": total,
                "source_age_sec": source_age_sec,
            }

