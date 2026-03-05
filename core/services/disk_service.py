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

    @property
    def backend_name(self) -> str:
        return self._wfs_adapter.backend_name

    def keys_status(self) -> tuple[bool, str | None]:
        return self._keys_ok()

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

    def _transport_for_device(self, path: str) -> str:
        try:
            raw = subprocess.check_output(["lsblk", "-dn", "-o", "TRAN", path], text=True).strip()
        except Exception:
            raw = ""

        transport = raw.splitlines()[0].strip().lower() if raw else ""
        if transport:
            return transport

        block_name = Path(path).name
        uevent_path = Path("/sys/block") / block_name / "device" / "uevent"
        if uevent_path.exists():
            try:
                payload = uevent_path.read_text(encoding="utf-8", errors="ignore").lower()
                if "usb" in payload:
                    return "usb"
            except Exception:
                pass
        return ""

    def _is_usb_device(self, path: str) -> bool:
        return self._transport_for_device(path) == "usb"

    def _probe_wfs_signature(self, path: str) -> bool:
        try:
            with open(path, "rb") as handle:
                head = handle.read(64 * 1024)
        except Exception:
            return False
        if b"WFS" in head:
            return True
        return b"\x01\x01\x08\x00" in head

    def _device_payload(
        self,
        *,
        path: str,
        size: str,
        model: str,
        transport: str,
        is_block: bool,
        keys_ok: bool,
        active_path: str | None,
        active_wfs_verified: bool,
    ) -> dict:
        is_usb = transport == "usb"

        if self._wfs_adapter.backend_name == "native":
            # Wii U WFS headers are encrypted on real media. Plain signature scanning is unreliable.
            # For native backend, treat USB block devices with valid keys as attachable and let
            # native attach perform authoritative verification.
            is_wfs = bool(is_block and keys_ok and is_usb)
            if active_path == path and active_wfs_verified:
                is_wfs = True
            attachable = bool(is_block and keys_ok and is_usb)
            reason = None
            if not is_usb:
                reason = "not_usb_device"
            elif not is_block:
                reason = "not_block_device"
            elif not keys_ok:
                reason = "keys_invalid"
        else:
            is_wfs = self._probe_wfs_signature(path) if is_block else False
            if active_path == path and active_wfs_verified:
                is_wfs = True

            attachable = bool(is_block and keys_ok and is_usb and is_wfs)
            reason = None
            if not is_usb:
                reason = "not_usb_device"
            elif not is_block:
                reason = "not_block_device"
            elif not keys_ok:
                reason = "keys_invalid"
            elif not is_wfs:
                reason = "wfs_header_not_detected"

        return {
            "path": path,
            "size": size,
            "model": model,
            "transport": transport,
            "is_usb": is_usb,
            "is_block": is_block,
            "is_wfs": is_wfs,
            "attachable": attachable,
            "reason": reason,
        }

    def scan_devices(self) -> dict:
        devices = []
        keys_ok, keys_error = self._keys_ok()

        active = self.get_active_attachment()
        active_path = active.get("device_path") if active else None
        active_wfs_verified = bool(active and active.get("wfs_verified"))

        try:
            raw = subprocess.check_output(
                ["lsblk", "--json", "-o", "NAME,KNAME,PATH,SIZE,TYPE,MODEL,FSTYPE,TRAN"], text=True
            )
            payload = json.loads(raw)
            blockdevices = payload.get("blockdevices", [])
            for node in blockdevices:
                if node.get("type") != "disk":
                    continue
                path = node.get("path") or f"/dev/{node.get('name')}"
                transport = str(node.get("tran") or "").strip().lower()
                if transport != "usb":
                    continue
                is_block = self._is_block_device(path)
                devices.append(
                    self._device_payload(
                        path=path,
                        size=node.get("size", ""),
                        model=node.get("model", ""),
                        transport=transport,
                        is_block=is_block,
                        keys_ok=keys_ok,
                        active_path=active_path,
                        active_wfs_verified=active_wfs_verified,
                    )
                )
        except Exception:
            for candidate in sorted(Path("/dev").glob("sd?")):
                path = str(candidate)
                transport = self._transport_for_device(path)
                if transport != "usb":
                    continue
                is_block = self._is_block_device(path)
                devices.append(
                    self._device_payload(
                        path=path,
                        size="unknown",
                        model="",
                        transport=transport,
                        is_block=is_block,
                        keys_ok=keys_ok,
                        active_path=active_path,
                        active_wfs_verified=active_wfs_verified,
                    )
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
            if not self._is_usb_device(device_path):
                raise WfsAdapterError("Target device is not USB")

        keys_ok, keys_error = self._keys_ok()
        if not keys_ok:
            raise WfsAdapterError(f"Cannot attach disk: {keys_error}")

        attach_result = self._wfs_adapter.attach(device_path, self._settings.otp_path, self._settings.seeprom_path)
        if not attach_result.attached:
            raise WfsAdapterError("Native attach failed")
        if not attach_result.key_verified:
            self._wfs_adapter.detach()
            raise WfsAdapterError("Attached disk key verification failed")
        if not attach_result.wfs_verified:
            self._wfs_adapter.detach()
            raise WfsAdapterError("Attached disk WFS verification failed")

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

    def runtime_attachment_status(self) -> tuple[bool, str | None]:
        try:
            self._wfs_adapter.flush()
            return True, None
        except Exception as exc:
            return False, str(exc)

    def restore_runtime_attachment(self) -> tuple[bool, str | None]:
        active = self.get_active_attachment()
        if active is None:
            return False, "no_active_attachment"

        device_path = str(active.get("device_path") or "").strip()
        if not device_path:
            return False, "active_attachment_missing_device_path"

        try:
            self.attach_device(device_path)
            return True, None
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def device_fingerprint(device_path: str) -> str:
        return hashlib.sha256(device_path.encode("utf-8")).hexdigest()[:24]
