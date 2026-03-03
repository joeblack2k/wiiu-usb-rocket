from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


OTP_SIZE = 0x400
SEEPROM_SIZE = 0x200


def load_key_file(path: Path, expected_size: int) -> bytes:
    data = path.read_bytes()
    if len(data) != expected_size:
        raise ValueError(f"Unexpected key file size for {path}: expected {expected_size}, got {len(data)}")
    return data


def derive_usb_key(otp_data: bytes, seeprom_data: bytes) -> bytes:
    if len(otp_data) != OTP_SIZE:
        raise ValueError("Invalid OTP length")
    if len(seeprom_data) != SEEPROM_SIZE:
        raise ValueError("Invalid SEEPROM length")

    usb_seed_key = otp_data[0x130:0x140]
    usb_key_seed = seeprom_data[0xB0:0xC0]
    cipher = Cipher(algorithms.AES(usb_seed_key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(usb_key_seed) + encryptor.finalize()

