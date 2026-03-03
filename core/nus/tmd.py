"""
Wii U Title Metadata (TMD) parser.

Vereisten (CHECK.md §5):
  - Content Count   : 2 bytes op offset 0x1DE, big-endian uint16 (struct ">H")
  - Content Records : starten op offset 0xB04, elk precies 36 bytes (0x24)
      +0x00  Content ID : 4 bytes, big-endian uint32 (struct ">I")
                          → hex-string zonder '0x'-prefix (bv. "0000000a")
      +0x04  Index      : 2 bytes, raw (gebruikt als AES-IV prefix bij decryptie)
      +0x08  Size       : 8 bytes, big-endian uint64 (struct ">Q")
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

_CONTENT_COUNT_OFFSET = 0x1DE
_CONTENT_RECORDS_OFFSET = 0xB04
_CONTENT_RECORD_SIZE = 0x24  # 36 bytes


class TmdError(ValueError):
    pass


@dataclass(slots=True)
class ContentRecord:
    content_id: int         # uint32
    content_id_hex: str     # 8-char hex string, geen prefix (voor URL-gebruik)
    index: bytes            # raw 2 bytes — AES-IV prefix bij .app-decryptie
    size: int               # uint64, bestandsgrootte in bytes (na decryptie, vóór padding)
    sha1_hash: bytes = b""  # 20 bytes SHA1 van gedecrypteerde content (uit TMD record +0x10)


@dataclass(slots=True)
class TmdInfo:
    content_count: int
    contents: list[ContentRecord]


def parse_tmd(tmd_path: Path) -> TmdInfo:
    """
    Leest een lokaal TMD bestand en retourneert een TmdInfo met de volledige
    content lijst.

    Raises:
        TmdError: als het bestand te klein is of content records buiten
                  het bestand vallen.
    """
    data = tmd_path.read_bytes()
    return _parse(data)


def parse_tmd_bytes(data: bytes) -> TmdInfo:
    """Zelfde als parse_tmd() maar accepteert raw bytes in plaats van een pad."""
    return _parse(data)


def _parse(data: bytes) -> TmdInfo:
    min_header = _CONTENT_COUNT_OFFSET + 2
    if len(data) < min_header:
        raise TmdError(
            f"TMD te klein voor header: {len(data)} bytes (minimum {min_header})"
        )

    (content_count,) = struct.unpack_from(">H", data, _CONTENT_COUNT_OFFSET)

    required_size = _CONTENT_RECORDS_OFFSET + content_count * _CONTENT_RECORD_SIZE
    if len(data) < required_size:
        raise TmdError(
            f"TMD te klein voor {content_count} content records: "
            f"{len(data)} bytes beschikbaar, {required_size} vereist"
        )

    contents: list[ContentRecord] = []
    for i in range(content_count):
        base = _CONTENT_RECORDS_OFFSET + i * _CONTENT_RECORD_SIZE

        (content_id,) = struct.unpack_from(">I", data, base + 0x00)
        index: bytes = data[base + 0x04 : base + 0x06]
        (size,) = struct.unpack_from(">Q", data, base + 0x08)
        sha1_hash: bytes = data[base + 0x10 : base + 0x24]

        contents.append(
            ContentRecord(
                content_id=content_id,
                content_id_hex=f"{content_id:08x}",
                index=index,
                size=size,
                sha1_hash=sha1_hash,
            )
        )

    return TmdInfo(content_count=content_count, contents=contents)
