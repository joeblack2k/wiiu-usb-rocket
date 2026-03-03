from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from core.nus.app_decryptor import AppDecryptError, decrypt_app


def _encrypt_app(plain: bytes, title_key: bytes, index: bytes) -> bytes:
    iv = index + b"\x00" * 14
    cipher = Cipher(algorithms.AES(title_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    return encryptor.update(plain) + encryptor.finalize()


def test_decrypt_app_roundtrip_aligned(tmp_path: Path) -> None:
    title_key = bytes.fromhex("00112233445566778899aabbccddeeff")
    index = b"\x00\x05"
    plain = (b"ABCD" * 16) + (b"WXYZ" * 16)  # 128 bytes, 16-byte aligned
    encrypted = _encrypt_app(plain, title_key, index)

    src = tmp_path / "00000001.app"
    dst = tmp_path / "00000001.dec"
    src.write_bytes(encrypted)

    written = decrypt_app(src, dst, title_key, index)

    assert written == len(plain)
    assert dst.read_bytes() == plain


def test_decrypt_app_rejects_non_aligned_ciphertext(tmp_path: Path) -> None:
    title_key = bytes.fromhex("00112233445566778899aabbccddeeff")
    index = b"\x00\x01"

    src = tmp_path / "bad.app"
    dst = tmp_path / "bad.dec"
    src.write_bytes(b"\x00" * 17)

    with pytest.raises(AppDecryptError, match="multiple of 16"):
        decrypt_app(src, dst, title_key, index)


def test_decrypt_app_rejects_invalid_block_size(tmp_path: Path) -> None:
    title_key = bytes.fromhex("00112233445566778899aabbccddeeff")
    index = b"\x00\x01"

    src = tmp_path / "ok.app"
    dst = tmp_path / "ok.dec"
    src.write_bytes(b"\x00" * 16)

    with pytest.raises(AppDecryptError, match="block_size"):
        decrypt_app(src, dst, title_key, index, block_size=15)
