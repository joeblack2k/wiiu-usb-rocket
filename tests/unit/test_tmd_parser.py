"""
Tests voor core/nus/tmd.py.
"""

from __future__ import annotations

import struct

import pytest

from core.nus.tmd import TmdError, parse_tmd, parse_tmd_bytes

_CONTENT_COUNT_OFFSET = 0x1DE
_CONTENT_RECORDS_OFFSET = 0xB04


def _make_tmd(records: list[tuple[int, bytes, int]], record_size: int = 0x30) -> bytes:
    count = len(records)
    total = _CONTENT_RECORDS_OFFSET + count * record_size
    data = bytearray(total)

    struct.pack_into(">H", data, _CONTENT_COUNT_OFFSET, count)

    for i, (cid, idx, size) in enumerate(records):
        base = _CONTENT_RECORDS_OFFSET + i * record_size
        struct.pack_into(">I", data, base + 0x00, cid)
        data[base + 0x04 : base + 0x06] = idx
        struct.pack_into(">Q", data, base + 0x08, size)

    return bytes(data)


def test_parse_tmd_single_record() -> None:
    tmd = _make_tmd([(0x0000000A, b"\x00\x00", 1024)])
    info = parse_tmd_bytes(tmd)
    assert info.content_count == 1
    assert info.record_size == 0x30
    assert len(info.contents) == 1
    rec = info.contents[0]
    assert rec.content_id == 0x0000000A
    assert rec.content_id_hex == "0000000a"
    assert rec.index == b"\x00\x00"
    assert rec.size == 1024


def test_parse_tmd_multiple_records() -> None:
    records = [
        (0x00000000, b"\x00\x00", 4096),
        (0x00000001, b"\x00\x01", 8192),
        (0xDEADBEEF, b"\x00\x02", 999),
    ]
    tmd = _make_tmd(records)
    info = parse_tmd_bytes(tmd)
    assert info.content_count == 3
    assert info.contents[0].content_id_hex == "00000000"
    assert info.contents[1].content_id_hex == "00000001"
    assert info.contents[1].index == b"\x00\x01"
    assert info.contents[2].content_id_hex == "deadbeef"
    assert info.contents[2].size == 999


def test_parse_tmd_content_id_hex_no_prefix() -> None:
    tmd = _make_tmd([(0x0000000A, b"\x00\x00", 0)])
    info = parse_tmd_bytes(tmd)
    assert not info.contents[0].content_id_hex.startswith("0x")


def test_parse_tmd_zero_records() -> None:
    tmd = _make_tmd([])
    info = parse_tmd_bytes(tmd)
    assert info.content_count == 0
    assert info.contents == []


def test_parse_tmd_from_file(tmp_path) -> None:
    tmd_path = tmp_path / "title.tmd"
    tmd_path.write_bytes(_make_tmd([(0x00000001, b"\x00\x00", 512)]))
    info = parse_tmd(tmd_path)
    assert info.content_count == 1
    assert info.contents[0].size == 512


def test_parse_tmd_raises_when_too_small_for_header() -> None:
    with pytest.raises(TmdError, match="te klein"):
        parse_tmd_bytes(b"\x00" * 10)


def test_parse_tmd_raises_when_truncated_records() -> None:
    data = bytearray(_CONTENT_RECORDS_OFFSET + 0x30)
    struct.pack_into(">H", data, _CONTENT_COUNT_OFFSET, 5)
    with pytest.raises(TmdError, match="te klein"):
        parse_tmd_bytes(bytes(data))


def test_parse_tmd_index_is_raw_bytes() -> None:
    tmd = _make_tmd([(0x00000001, b"\x01\x02", 0)])
    info = parse_tmd_bytes(tmd)
    assert isinstance(info.contents[0].index, bytes)
    assert info.contents[0].index == b"\x01\x02"


def test_parse_tmd_supports_legacy_0x24_records() -> None:
    records = [
        (0x000000AA, b"\x00\x00", 1234),
        (0x000000BB, b"\x00\x01", 5678),
    ]
    tmd = _make_tmd(records, record_size=0x24)
    info = parse_tmd_bytes(tmd)

    assert info.record_size == 0x24
    assert info.content_count == 2
    assert info.contents[0].content_id_hex == "000000aa"
    assert info.contents[1].content_id_hex == "000000bb"


def test_parse_tmd_hash_algo_depends_on_record_size() -> None:
    modern = parse_tmd_bytes(_make_tmd([(0x00000001, b"\x00\x00", 1)], record_size=0x30))
    assert modern.contents[0].hash_algo == "sha256"
    assert len(modern.contents[0].content_hash) == 32

    legacy = parse_tmd_bytes(_make_tmd([(0x00000001, b"\x00\x00", 1)], record_size=0x24))
    assert legacy.contents[0].hash_algo == "sha1"
    assert len(legacy.contents[0].content_hash) == 20
