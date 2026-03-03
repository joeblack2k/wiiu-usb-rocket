"""
Nep-cetk generator voor gebruik met een eigen NUS mirror (LINK= ingesteld).

Een nep-cetk heeft title key = b"\\x00" * 16 (nul-sleutel).
Dit werkt alleen als de content op de mirror versleuteld is met diezelfde nul-sleutel.
Op de officiële Nintendo NUS wordt dit nooit geactiveerd.
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from core.nus.ticket import load_common_key

_FAKE_CETK_SIZE = 0x2C4          # 708 bytes — standaard Wii U ticket formaat
_ENCRYPTED_TITLE_KEY_OFFSET = 0x1BF
_TITLE_ID_OFFSET = 0x1DC
_ZERO_TITLE_KEY = b"\x00" * 16


def generate_fake_cetk(title_id: str) -> bytes:
    """
    Genereert een minimale nep-cetk voor een custom mirror.

    title_id: 16-char lowercase hex string (bijv. "0005000010101a00")

    Title key wordt op nul gezet. De encrypted title key is:
        AES-128-CBC(common_key, IV=title_id_bytes + 0x00*8, plaintext=0x00*16)

    Retourneert de raw cetk bytes (708 bytes).
    """
    title_id_bytes = bytes.fromhex(title_id.zfill(16))

    buf = bytearray(_FAKE_CETK_SIZE)

    buf[_TITLE_ID_OFFSET : _TITLE_ID_OFFSET + 8] = title_id_bytes

    iv = title_id_bytes + b"\x00" * 8
    common_key = load_common_key()
    cipher = Cipher(algorithms.AES(common_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted_title_key = encryptor.update(_ZERO_TITLE_KEY) + encryptor.finalize()

    buf[_ENCRYPTED_TITLE_KEY_OFFSET : _ENCRYPTED_TITLE_KEY_OFFSET + 16] = encrypted_title_key

    return bytes(buf)
