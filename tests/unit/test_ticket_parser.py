"""
Tests voor core/nus/ticket.py.

Synthetische .tik bestanden worden gebouwd op de exact juiste byte-offsets
zoals gedefinieerd in CHECK.md §3 + §4.

Testvectoren zijn zelf berekend en onafhankelijk verifieerbaar:
  common_key  = b"\\x00" * 16  (all-zero AES-128 key)
  title_id    = 0x0005000010101a00  → bytes 00 05 00 00 10 10 1a 00
  IV          = title_id_bytes + b"\\x00" * 8
  enc_key     = AES-128-CBC(key=00*16, iv=IV).encrypt(b"\\x00" * 16)
              → bereken met: python3 -c "
                  from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
                  iv = bytes.fromhex('000500001010 1a00') + b'\\x00'*8
                  c = Cipher(algorithms.AES(b'\\x00'*16), modes.CBC(iv))
                  e = c.encryptor()
                  print((e.update(b'\\x00'*16)+e.finalize()).hex())"
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from core.nus.ticket import TicketError, parse_ticket, parse_ticket_bytes

# --- testvectoren -----------------------------------------------------------

_COMMON_KEY = b"\x00" * 16
_COMMON_KEY_HEX = _COMMON_KEY.hex()  # "00" * 16

_TITLE_ID_INT = 0x0005000010101A00
_TITLE_ID_BYTES = struct.pack(">Q", _TITLE_ID_INT)
_TITLE_ID_STR = f"{_TITLE_ID_INT:016x}"

# Bereken de encrypted title key zodat decryptie van b"\x00"*16 oplevert
_PLAINTEXT_TITLE_KEY = b"\x00" * 16
_IV = _TITLE_ID_BYTES + b"\x00" * 8

def _compute_encrypted_key(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    enc = cipher.encryptor()
    return enc.update(plaintext) + enc.finalize()

_ENCRYPTED_TITLE_KEY = _compute_encrypted_key(_PLAINTEXT_TITLE_KEY, _COMMON_KEY, _IV)


def _make_ticket(
    title_id_bytes: bytes = _TITLE_ID_BYTES,
    encrypted_key: bytes = _ENCRYPTED_TITLE_KEY,
    total_size: int = 0x200,
) -> bytes:
    """Bouw een minimaal synthetisch ticket met data op de juiste offsets."""
    data = bytearray(total_size)
    data[0x1BF : 0x1BF + 16] = encrypted_key
    data[0x1DC : 0x1DC + 8] = title_id_bytes
    return bytes(data)


# --- tests ------------------------------------------------------------------

def test_parse_ticket_extracts_title_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIIU_COMMON_KEY", _COMMON_KEY_HEX)
    data = _make_ticket()
    info = parse_ticket_bytes(data)
    assert info.title_id == _TITLE_ID_STR


def test_parse_ticket_decrypts_title_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIIU_COMMON_KEY", _COMMON_KEY_HEX)
    data = _make_ticket()
    info = parse_ticket_bytes(data)
    assert info.title_key == _PLAINTEXT_TITLE_KEY


def test_parse_ticket_encrypted_key_stored_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIIU_COMMON_KEY", _COMMON_KEY_HEX)
    data = _make_ticket()
    info = parse_ticket_bytes(data)
    assert info.encrypted_title_key == _ENCRYPTED_TITLE_KEY


def test_parse_ticket_title_id_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIIU_COMMON_KEY", _COMMON_KEY_HEX)
    data = _make_ticket()
    info = parse_ticket_bytes(data)
    assert info.title_id_bytes == _TITLE_ID_BYTES


def test_parse_ticket_from_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WIIU_COMMON_KEY", _COMMON_KEY_HEX)
    tik_path = tmp_path / "title.tik"
    tik_path.write_bytes(_make_ticket())
    info = parse_ticket(tik_path)
    assert info.title_id == _TITLE_ID_STR
    assert info.title_key == _PLAINTEXT_TITLE_KEY


def test_parse_ticket_raises_when_too_small(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIIU_COMMON_KEY", _COMMON_KEY_HEX)
    with pytest.raises(TicketError, match="te klein"):
        parse_ticket_bytes(b"\x00" * 10)


def test_parse_ticket_raises_without_common_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIIU_COMMON_KEY", raising=False)
    data = _make_ticket()
    with pytest.raises(TicketError, match="WIIU_COMMON_KEY"):
        parse_ticket_bytes(data)


def test_parse_ticket_raises_with_invalid_common_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIIU_COMMON_KEY", "niet-hex-data!")
    data = _make_ticket()
    with pytest.raises(TicketError, match="ongeldige hex"):
        parse_ticket_bytes(data)


def test_parse_ticket_raises_with_wrong_key_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIIU_COMMON_KEY", "aabbcc")  # 3 bytes, te kort
    data = _make_ticket()
    with pytest.raises(TicketError, match="16 bytes"):
        parse_ticket_bytes(data)
