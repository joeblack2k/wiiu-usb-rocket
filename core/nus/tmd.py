"""
Wii U Title Metadata (TMD) parser.

Vereisten (CHECK.md §5):
  - Content Count   : 2 bytes op offset 0x1DE, big-endian uint16 (struct ">H")
  - Content Records : starten op offset 0xB04
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_CONTENT_COUNT_OFFSET = 0x1DE
_CONTENT_RECORDS_OFFSET = 0xB04
_RECORD_SIZE_CANDIDATES = (0x30, 0x24)
_MAX_REASONABLE_CONTENT_SIZE = 256 * 1024 * 1024 * 1024


class TmdError(ValueError):
    pass


@dataclass(slots=True)
class ContentRecord:
    content_id: int
    content_id_hex: str
    index: bytes
    size: int
    content_hash: bytes = b""
    hash_algo: str = "sha1"


@dataclass(slots=True)
class TmdInfo:
    content_count: int
    contents: list[ContentRecord]
    record_size: int = 0x30


def parse_tmd(tmd_path: Path) -> TmdInfo:
    data = tmd_path.read_bytes()
    return _parse(data)


def parse_tmd_bytes(data: bytes) -> TmdInfo:
    return _parse(data)


def _parse(data: bytes) -> TmdInfo:
    min_header = _CONTENT_COUNT_OFFSET + 2
    if len(data) < min_header:
        raise TmdError(f"TMD te klein voor header: {len(data)} bytes (minimum {min_header})")

    (content_count,) = struct.unpack_from(">H", data, _CONTENT_COUNT_OFFSET)

    candidates: list[tuple[int, int, list[ContentRecord]]] = []
    for record_size in _RECORD_SIZE_CANDIDATES:
        required_size = _CONTENT_RECORDS_OFFSET + content_count * record_size
        if len(data) < required_size:
            continue
        records = _parse_records(data, content_count, record_size)
        score = _score_records(records)
        candidates.append((score, record_size, records))
        logger.debug(
            "TMD candidate parsed: count=%s record_size=0x%x score=%s",
            content_count,
            record_size,
            score,
        )

    if not candidates:
        min_required = _CONTENT_RECORDS_OFFSET + content_count * min(_RECORD_SIZE_CANDIDATES)
        raise TmdError(
            f"TMD te klein voor {content_count} content records: {len(data)} bytes beschikbaar, "
            f"minimaal {min_required} vereist"
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, record_size, contents = candidates[0]
    logger.debug(
        "TMD parse gekozen: content_count=%s record_size=0x%x first_content=%s",
        content_count,
        record_size,
        contents[0].content_id_hex if contents else "none",
    )

    return TmdInfo(content_count=content_count, contents=contents, record_size=record_size)


def _parse_records(data: bytes, content_count: int, record_size: int) -> list[ContentRecord]:
    contents: list[ContentRecord] = []
    for i in range(content_count):
        base = _CONTENT_RECORDS_OFFSET + i * record_size

        (content_id,) = struct.unpack_from(">I", data, base + 0x00)
        index = data[base + 0x04 : base + 0x06]
        (size,) = struct.unpack_from(">Q", data, base + 0x08)
        if record_size >= 0x30:
            content_hash = data[base + 0x10 : base + 0x30]
            hash_algo = "sha256"
        else:
            content_hash = data[base + 0x10 : base + 0x24]
            hash_algo = "sha1"

        contents.append(
            ContentRecord(
                content_id=content_id,
                content_id_hex=f"{content_id:08x}",
                index=index,
                size=size,
                content_hash=content_hash,
                hash_algo=hash_algo,
            )
        )
    return contents


def _score_records(contents: list[ContentRecord]) -> int:
    if not contents:
        return 0

    score = 0
    sample = contents[: min(12, len(contents))]
    for idx, record in enumerate(sample):
        index_value = int.from_bytes(record.index, "big")

        if index_value == idx:
            score += 4
        elif index_value < len(contents) + 16:
            score += 1
        else:
            score -= 3

        if record.size == 0:
            score += 1
        elif 0 < record.size <= _MAX_REASONABLE_CONTENT_SIZE:
            score += 2
        else:
            score -= 5

        if record.content_id <= 0x00FFFFFF:
            score += 1
        else:
            score -= 1

    return score
