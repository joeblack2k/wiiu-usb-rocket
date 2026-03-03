"""
Wii U ticket (.tik / cetk) parser en title key decryptor.

Vereisten (CHECK.md §3 + §4):
  - Encrypted Title Key : 16 bytes op offset 0x1BF
  - Title ID            : 8 bytes op offset 0x1DC, big-endian uint64 (struct ">Q")
  - Decryptie           : AES-128-CBC
      key = WIIU_COMMON_KEY (ENV, 32 hex chars = 16 bytes)
      IV  = title_id_bytes (8 bytes) + b"\\x00" * 8
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_ENCRYPTED_TITLE_KEY_OFFSET = 0x1BF
_TITLE_ID_OFFSET = 0x1DC
_MIN_TICKET_SIZE = _TITLE_ID_OFFSET + 8  # 0x1E4 = 484


class TicketError(ValueError):
    pass


@dataclass(slots=True)
class TicketInfo:
    title_id: str           # 16-char lowercase hex string
    title_id_bytes: bytes   # raw 8 bytes (big-endian)
    encrypted_title_key: bytes  # 16 bytes, as read from ticket
    title_key: bytes        # 16 bytes, na decryptie


def _load_common_key() -> bytes:
    raw = os.environ.get("WIIU_COMMON_KEY", "").strip()
    if not raw:
        raise TicketError("WIIU_COMMON_KEY is niet gezet in de omgeving")
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise TicketError(f"WIIU_COMMON_KEY bevat ongeldige hex-data: {exc}") from exc
    if len(key) != 16:
        raise TicketError(
            f"WIIU_COMMON_KEY moet precies 16 bytes zijn (32 hex-tekens), got {len(key)}"
        )
    return key


def parse_ticket(tik_path: Path) -> TicketInfo:
    """
    Leest een lokaal .tik/.cetk bestand en retourneert een TicketInfo met
    de gedecrypte title key.

    Raises:
        TicketError: als het bestand te klein is, offsets ongeldig zijn,
                     of WIIU_COMMON_KEY ontbreekt / ongeldig is.
    """
    data = tik_path.read_bytes()

    if len(data) < _MIN_TICKET_SIZE:
        raise TicketError(
            f"Ticket bestand te klein: {len(data)} bytes (minimum {_MIN_TICKET_SIZE})"
        )

    encrypted_title_key: bytes = data[_ENCRYPTED_TITLE_KEY_OFFSET : _ENCRYPTED_TITLE_KEY_OFFSET + 16]
    title_id_bytes: bytes = data[_TITLE_ID_OFFSET : _TITLE_ID_OFFSET + 8]

    (title_id_int,) = struct.unpack_from(">Q", title_id_bytes)
    title_id = f"{title_id_int:016x}"

    # IV = Title ID (8 bytes) gevolgd door 8 nul-bytes
    iv: bytes = title_id_bytes + b"\x00" * 8

    common_key = _load_common_key()
    cipher = Cipher(algorithms.AES(common_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    title_key: bytes = decryptor.update(encrypted_title_key) + decryptor.finalize()

    return TicketInfo(
        title_id=title_id,
        title_id_bytes=title_id_bytes,
        encrypted_title_key=encrypted_title_key,
        title_key=title_key,
    )


def parse_ticket_bytes(data: bytes) -> TicketInfo:
    """Zelfde als parse_ticket() maar accepteert raw bytes in plaats van een pad."""
    if len(data) < _MIN_TICKET_SIZE:
        raise TicketError(
            f"Ticket data te klein: {len(data)} bytes (minimum {_MIN_TICKET_SIZE})"
        )

    encrypted_title_key = data[_ENCRYPTED_TITLE_KEY_OFFSET : _ENCRYPTED_TITLE_KEY_OFFSET + 16]
    title_id_bytes = data[_TITLE_ID_OFFSET : _TITLE_ID_OFFSET + 8]

    (title_id_int,) = struct.unpack_from(">Q", title_id_bytes)
    title_id = f"{title_id_int:016x}"

    iv = title_id_bytes + b"\x00" * 8
    common_key = _load_common_key()
    cipher = Cipher(algorithms.AES(common_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    title_key = decryptor.update(encrypted_title_key) + decryptor.finalize()

    return TicketInfo(
        title_id=title_id,
        title_id_bytes=title_id_bytes,
        encrypted_title_key=encrypted_title_key,
        title_key=title_key,
    )
