from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def decrypt_app(
    src: Path,
    dest: Path,
    title_key: bytes,
    index: bytes,
    block_size: int = 65536,
) -> int:
    """
    Decrypteert een NUS .app bestand (AES-128-CBC).

    IV = index (2 bytes) + 14 nul-bytes.
    block_size moet een veelvoud van 16 zijn.
    Retourneert het aantal bytes geschreven naar dest.
    """
    iv = index + b"\x00" * 14
    cipher = Cipher(algorithms.AES(title_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    written = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as fin, dest.open("wb") as fout:
        while True:
            chunk = fin.read(block_size)
            if not chunk:
                break
            if len(chunk) % 16 != 0:
                chunk += b"\x00" * (16 - len(chunk) % 16)
            decrypted = decryptor.update(chunk)
            fout.write(decrypted)
            written += len(decrypted)
        final = decryptor.finalize()
        if final:
            fout.write(final)
            written += len(final)
    return written
