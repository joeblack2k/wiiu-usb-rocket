from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class AppDecryptError(ValueError):
    pass


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
    if len(title_key) != 16:
        raise AppDecryptError(f"title_key must be 16 bytes, got {len(title_key)}")
    if len(index) != 2:
        raise AppDecryptError(f"index must be 2 bytes, got {len(index)}")
    if block_size <= 0 or block_size % 16 != 0:
        raise AppDecryptError(f"block_size must be a positive multiple of 16, got {block_size}")

    try:
        src_size = src.stat().st_size
    except FileNotFoundError as exc:
        raise AppDecryptError(f"encrypted content not found: {src}") from exc

    if src_size % 16 != 0:
        raise AppDecryptError(
            f"encrypted content size must be a multiple of 16 bytes, got {src_size} bytes for {src}"
        )

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
            decrypted = decryptor.update(chunk)
            fout.write(decrypted)
            written += len(decrypted)

        final = decryptor.finalize()
        if final:
            fout.write(final)
            written += len(final)

    return written
