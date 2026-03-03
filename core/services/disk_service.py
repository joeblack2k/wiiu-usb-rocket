import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from core.config import Settings
from core.crypto import OTP_SIZE, SEEPROM_SIZE, load_key_file
from core.db import session_scope
from core.models.entities import DiskAttachment
from core.services.wfs_adapter import BaseWfsAdapter, WfsAdapterError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DiskService:
    def __init__(self, settings: Settings, wfs_adapter: BaseWfsAdapter):
        self._settings = settings
        self._wfs_adapter = wfs_adapter

    def _is_block_device(self, path: str) -> bool:
        try:
            mode = os.stat(path).st_mode
        except FileNotFoundError:
            return False
        return stat.S_ISBLK(mode)

    def _keys_ok(self) -> tuple[bool, str | None]:
        try:
            load_key_file(self._settings.otp_path, OTP_SIZE)
            load_key_file(self._settings.seeprom_path, SEEPROM_SIZE)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def _probe_wfs_signature(self, path: str) -> bool:
        try:
            with open(path, "rb") as handle:
                head = handle.read(4096)
        except Exception:
            return False
        if b"WFS" in head:
            return True
        return b"\x01\x01\x08\x00" in head

    def scan_devices(self) -> dict:
        devices = []
        keys_ok, keys_error = self._keys_ok()
        try:
            raw = subprocess.check_output(
                ["lsblk", "--json", "-o", "NAME,KNAME,PATH,SIZE,TYPE,MODEL,FSTYPE"], text=True
            )
            payload = json.loads(raw)
            blockdevices = payload.get("blockdevices", [])
            for node in blockdevices:
                if node.get("type") != "disk":
                    continue
                path = node.get("path") or f"/dev/{node.get('name')}"
                is_block = self._is_block_device(path)
                is_wfs = self._probe_wfs_signature(path) if is_block else False
                reason = None
                attachable = is_block and keys_ok and is_wfs
                if not is_block:
                    reason = "not_block_device"
                elif not keys_ok:
                    reason = "keys_invalid"
                elif not is_wfs:
                    reason = "wfs_header_not_detected"
                devices.append(
                    {
                        "path": path,
                        "size": node.get("size", ""),
                        "model": node.get("model", ""),
                        "is_block": is_block,
                        "is_wfs": is_wfs,
                        "attachable": attachable,
                        "reason": reason,
                    }
                )
        except Exception:
            for candidate in sorted(Path("/dev").glob("sd?")):
                path = str(candidate)
                is_block = self._is_block_device(path)
                is_wfs = self._probe_wfs_signature(path) if is_block else False
                devices.append(
                    {
                        "path": path,
                        "size": "unknown",
                        "model": "",
                        "is_block": is_block,
                        "is_wfs": is_wfs,
                        "attachable": bool(is_block and keys_ok and is_wfs),
                        "reason": None,
                    }
                )

        response = {"devices": devices}
        if keys_error:
            response["keys_error"] = keys_error
        return response

    def attach_device(self, device_path: str) -> dict:
        if self._wfs_adapter.backend_name != "simulated":
            if not device_path.startswith("/dev/"):
                raise WfsAdapterError("Only /dev/* block devices are accepted")
            if not self._is_block_device(device_path):
                raise WfsAdapterError("Target path is not a block device")

        keys_ok, keys_error = self._keys_ok()
        if not keys_ok:
            raise WfsAdapterError(f"Cannot attach disk: {keys_error}")

        attach_result = self._wfs_adapter.attach(device_path, self._settings.otp_path, self._settings.seeprom_path)
        if not attach_result.attached:
            raise WfsAdapterError("Native attach failed")

        with session_scope() as session:
            active_records = session.query(DiskAttachment).filter(DiskAttachment.active.is_(True)).all()
            for record in active_records:
                record.active = False
                record.detached_at = utcnow()

            new_record = DiskAttachment(
                device_path=device_path,
                wfs_fingerprint=attach_result.fingerprint,
                key_verified=attach_result.key_verified,
                wfs_verified=attach_result.wfs_verified,
                active=True,
            )
            session.add(new_record)

        return {
            "attached": True,
            "disk_id": attach_result.disk_id,
            "wfs_verified": attach_result.wfs_verified,
            "key_verified": attach_result.key_verified,
            "fingerprint": attach_result.fingerprint,
        }

    def detach_active(self) -> None:
        self._wfs_adapter.detach()
        with session_scope() as session:
            active_records = session.query(DiskAttachment).filter(DiskAttachment.active.is_(True)).all()
            for record in active_records:
                record.active = False
                record.detached_at = utcnow()

    def get_active_attachment(self) -> dict | None:
        with session_scope() as session:
            record = (
                session.query(DiskAttachment)
                .filter(DiskAttachment.active.is_(True))
                .order_by(DiskAttachment.id.desc())
                .first()
            )
            if record is None:
                return None
            return {
                "id": record.id,
                "device_path": record.device_path,
                "wfs_fingerprint": record.wfs_fingerprint,
                "key_verified": record.key_verified,
                "wfs_verified": record.wfs_verified,
                "active": record.active,
                "attached_at": record.attached_at.isoformat(),
            }

    @staticmethod
    def device_fingerprint(device_path: str) -> str:
        return hashlib.sha256(device_path.encode("utf-8")).hexdigest()[:24]

