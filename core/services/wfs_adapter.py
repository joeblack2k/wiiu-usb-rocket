import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from core.config import Settings
from core.crypto import OTP_SIZE, SEEPROM_SIZE, derive_usb_key, load_key_file


class WfsAdapterError(RuntimeError):
    pass


@dataclass(slots=True)
class AttachResult:
    attached: bool
    disk_id: str
    wfs_verified: bool
    key_verified: bool
    fingerprint: str

    def to_dict(self) -> dict:
        return asdict(self)


class BaseWfsAdapter:
    backend_name = "base"

    def attach(self, device_path: str, otp_path: Path, seeprom_path: Path) -> AttachResult:
        raise NotImplementedError

    def mkdir(self, path: str) -> None:
        raise NotImplementedError

    def create_file(self, path: str, size_hint: int = 0) -> None:
        raise NotImplementedError

    def write_stream(self, path: str, data: bytes, offset: int = 0) -> int:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        raise NotImplementedError

    def integrity_check(self, scope: str = "/") -> dict:
        raise NotImplementedError

    def detach(self) -> None:
        raise NotImplementedError


class SimulatedWfsAdapter(BaseWfsAdapter):
    backend_name = "simulated"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._mounted = False
        self._root: Path | None = None
        self._fingerprint = ""
        self._device_path = ""

    @staticmethod
    def _sanitize_device(device_path: str) -> str:
        return device_path.strip("/").replace("/", "_").replace(".", "_")

    def _validate_keys(self, otp_path: Path, seeprom_path: Path) -> bytes:
        otp_data = load_key_file(otp_path, OTP_SIZE)
        seeprom_data = load_key_file(seeprom_path, SEEPROM_SIZE)
        return derive_usb_key(otp_data, seeprom_data)

    def attach(self, device_path: str, otp_path: Path, seeprom_path: Path) -> AttachResult:
        usb_key = self._validate_keys(otp_path, seeprom_path)
        disk_name = self._sanitize_device(device_path) or "unnamed"
        root = self._settings.simulated_wfs_root / disk_name
        root.mkdir(parents=True, exist_ok=True)
        fingerprint = hashlib.sha256((device_path + usb_key.hex()).encode("utf-8")).hexdigest()[:32]
        self._fingerprint = fingerprint
        self._root = root
        self._mounted = True
        self._device_path = device_path
        return AttachResult(
            attached=True,
            disk_id=f"sim-{disk_name}",
            wfs_verified=True,
            key_verified=True,
            fingerprint=fingerprint,
        )

    def _ensure_attached(self) -> Path:
        if not self._mounted or self._root is None:
            raise WfsAdapterError("No active WFS attachment")
        return self._root

    def _resolve(self, path: str) -> Path:
        root = self._ensure_attached()
        relative = path.strip()
        if not relative.startswith("/"):
            raise WfsAdapterError("WFS path must be absolute")
        full = (root / relative.lstrip("/")).resolve()
        if root.resolve() not in full.parents and full != root.resolve():
            raise WfsAdapterError("Path escapes mounted WFS root")
        return full

    def mkdir(self, path: str) -> None:
        target = self._resolve(path)
        target.mkdir(parents=True, exist_ok=True)

    def create_file(self, path: str, size_hint: int = 0) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb"):
            pass
        if size_hint > 0:
            with open(target, "r+b") as handle:
                handle.truncate(size_hint)

    def write_stream(self, path: str, data: bytes, offset: int = 0) -> int:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with open(target, "wb"):
                pass
        with open(target, "r+b") as handle:
            handle.seek(offset)
            written = handle.write(data)
        return written

    def delete(self, path: str) -> None:
        target = self._resolve(path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def flush(self) -> None:
        _ = self._ensure_attached()

    def integrity_check(self, scope: str = "/") -> dict:
        target = self._resolve(scope)
        if not target.exists():
            return {"ok": False, "reason": "scope_not_found", "files": 0, "bytes": 0}
        if target.is_file():
            return {"ok": True, "files": 1, "bytes": target.stat().st_size}

        files = 0
        total_bytes = 0
        for root, _, names in os.walk(target):
            root_path = Path(root)
            for name in names:
                file_path = root_path / name
                files += 1
                total_bytes += file_path.stat().st_size
        return {"ok": True, "files": files, "bytes": total_bytes}

    def detach(self) -> None:
        self._mounted = False
        self._root = None
        self._fingerprint = ""
        self._device_path = ""


class NativeWfsAdapter(BaseWfsAdapter):
    backend_name = "native"

    def __init__(self):
        try:
            import wfs_core_native  # type: ignore
        except ImportError as exc:
            raise WfsAdapterError("Native backend selected but wfs_core_native is unavailable") from exc

        self._module = wfs_core_native
        self._engine = wfs_core_native.WfsCore()

    def attach(self, device_path: str, otp_path: Path, seeprom_path: Path) -> AttachResult:
        payload = self._engine.attach(str(device_path), str(otp_path), str(seeprom_path))
        return AttachResult(
            attached=bool(payload.get("attached", False)),
            disk_id=str(payload.get("disk_id", "")),
            wfs_verified=bool(payload.get("wfs_verified", False)),
            key_verified=bool(payload.get("key_verified", False)),
            fingerprint=str(payload.get("fingerprint", "")),
        )

    def mkdir(self, path: str) -> None:
        self._engine.mkdir(path)

    def create_file(self, path: str, size_hint: int = 0) -> None:
        self._engine.create_file(path, int(size_hint))

    def write_stream(self, path: str, data: bytes, offset: int = 0) -> int:
        return int(self._engine.write_stream(path, data, int(offset)))

    def delete(self, path: str) -> None:
        self._engine.delete(path)

    def flush(self) -> None:
        self._engine.flush()

    def integrity_check(self, scope: str = "/") -> dict:
        raw = self._engine.integrity_check(scope)
        if isinstance(raw, str):
            return json.loads(raw)
        if isinstance(raw, dict):
            return raw
        raise WfsAdapterError("Unexpected integrity response from native backend")

    def detach(self) -> None:
        self._engine.detach()


def build_wfs_adapter(settings: Settings) -> BaseWfsAdapter:
    mode = settings.wfs_backend.lower()
    if mode == "simulated":
        return SimulatedWfsAdapter(settings)
    if mode == "native":
        return NativeWfsAdapter()
    if mode == "auto":
        try:
            return NativeWfsAdapter()
        except WfsAdapterError:
            if settings.dry_run:
                return SimulatedWfsAdapter(settings)
            raise
    raise WfsAdapterError(f"Unknown WFS backend mode: {settings.wfs_backend}")

