from pathlib import Path

import pytest

from core.crypto import OTP_SIZE, SEEPROM_SIZE, derive_usb_key, load_key_file


def test_derive_usb_key_length() -> None:
    otp = bytes([0x11] * OTP_SIZE)
    seeprom = bytes([0x22] * SEEPROM_SIZE)
    usb_key = derive_usb_key(otp, seeprom)
    assert len(usb_key) == 16


def test_load_key_file_size_validation(tmp_path: Path) -> None:
    key_file = tmp_path / "otp.bin"
    key_file.write_bytes(b"short")
    with pytest.raises(ValueError):
        load_key_file(key_file, OTP_SIZE)

