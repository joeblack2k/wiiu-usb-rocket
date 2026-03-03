import json
import re
from dataclasses import asdict, dataclass


ENTRY_RE = re.compile(
    r'\{\s*"(?P<title_id>[0-9A-Fa-f]{8,16})"\s*,\s*"(?P<name>(?:\\.|[^"\\])*)"\s*,\s*"(?P<region>(?:\\.|[^"\\])*)"\s*,\s*"(?P<category>(?:\\.|[^"\\])*)"(?:\s*,\s*"(?P<extra>(?:\\.|[^"\\])*)")?\s*\}'
)


@dataclass(slots=True)
class CatalogItem:
    title_id: str
    name: str
    region: str
    category: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _decode_c_string(value: str) -> str:
    return bytes(value, "utf-8").decode("unicode_escape")


def parse_catalog_feed(payload: str) -> list[CatalogItem]:
    payload = payload.strip()
    if not payload:
        return []

    if payload.startswith("["):
        data = json.loads(payload)
        items: list[CatalogItem] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue

            title_id = entry.get("title_id") or entry.get("titleID") or entry.get("titleid")
            if title_id is None:
                continue

            category = entry.get("category")
            if category is None:
                ticket_flag = str(entry.get("ticket", "")).strip().lower()
                category = "ticket" if ticket_flag in {"1", "true", "yes"} else "unknown"

            items.append(
                CatalogItem(
                    title_id=str(title_id).lower(),
                    name=str(entry.get("name", "")),
                    region=str(entry.get("region", "ALL")),
                    category=str(category),
                )
            )
        return items

    items = []
    for match in ENTRY_RE.finditer(payload):
        title_id = match.group("title_id").lower()
        name = _decode_c_string(match.group("name"))
        region = _decode_c_string(match.group("region"))
        category = _decode_c_string(match.group("category"))
        items.append(CatalogItem(title_id=title_id, name=name, region=region, category=category))
    return items

