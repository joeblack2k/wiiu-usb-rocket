#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _current_python_is_venv(root: Path) -> bool:
    return Path(sys.prefix).resolve() == (root / ".venv").resolve()


def _bootstrap_venv_if_needed(root: Path, args: list[str]) -> None:
    if os.environ.get("_WIIDOWNLOADER_VENV_READY") == "1":
        return

    if _current_python_is_venv(root):
        os.environ["_WIIDOWNLOADER_VENV_READY"] = "1"
        return

    venv_python = _venv_python(root)
    if not venv_python.exists():
        _run([sys.executable, "-m", "venv", str(root / ".venv")], cwd=root)

    stamp_path = root / ".venv" / ".wiidownloader_stamp"
    pyproject = root / "pyproject.toml"
    stamp_value = str(pyproject.stat().st_mtime_ns) if pyproject.exists() else "0"

    install_needed = True
    if stamp_path.exists() and stamp_path.read_text(encoding="utf-8") == stamp_value:
        install_needed = False

    if install_needed:
        _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], cwd=root)
        _run([str(venv_python), "-m", "pip", "install", "-e", str(root)], cwd=root)
        stamp_path.write_text(stamp_value, encoding="utf-8")

    env = os.environ.copy()
    env["_WIIDOWNLOADER_VENV_READY"] = "1"
    os.execve(str(venv_python), [str(venv_python), str(root / "wiidownloader.py"), *args], env)


def _set_default_env(root: Path, host: str, port: int) -> None:
    data_dir = root / "data"
    logs_dir = root / "logs"
    keys_dir = root / "keys"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("APP_HOST", host)
    os.environ.setdefault("APP_PORT", str(port))

    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault("LOGS_DIR", str(logs_dir))
    os.environ.setdefault("KEYS_DIR", str(keys_dir))
    os.environ.setdefault("OTP_PATH", str(keys_dir / "otp.bin"))
    os.environ.setdefault("SEEPROM_PATH", str(keys_dir / "seeprom.bin"))

    db_path = data_dir / "app.db"
    os.environ.setdefault("DB_URL", f"sqlite:///{db_path}")

    os.environ.setdefault("ALLOW_FALLBACK", "false")
    os.environ.setdefault("DRY_RUN", "false")
    os.environ.setdefault("FIRST_WRITE_CONFIRMED", "true")
    os.environ.setdefault("PURGE_ARTIFACTS_ON_SUCCESS", "false")
    os.environ.setdefault("WFS_BACKEND", "native")


def _require_native() -> bool:
    value = os.environ.get("WIIDOWNLOADER_REQUIRE_NATIVE", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _set_simulated_fallback(reason: str) -> None:
    if _require_native():
        raise RuntimeError(reason)
    os.environ["WFS_BACKEND"] = "simulated"
    print(f"[wiidownloader] native unavailable, fallback to simulated backend: {reason}")


def _build_native(root: Path, build_dir: Path) -> None:
    source_dir = root / "native" / "wfs_core"
    configure_cmd = ["cmake", "-S", str(source_dir), "-B", str(build_dir)]

    if shutil.which("ninja") is not None or shutil.which("ninja-build") is not None:
        configure_cmd.extend(["-G", "Ninja"])

    _run(configure_cmd, cwd=root)
    _run(["cmake", "--build", str(build_dir)], cwd=root)


def _ensure_native_module(root: Path) -> None:
    try:
        import wfs_core_native  # type: ignore  # noqa: F401

        return
    except Exception:
        pass

    build_dir = root / "native" / "wfs_core" / "build"
    candidates = sorted(build_dir.glob("**/wfs_core_native*.so"))
    if candidates:
        sys.path.insert(0, str(candidates[0].parent))
        try:
            import wfs_core_native  # type: ignore  # noqa: F401

            return
        except Exception:
            pass

    if shutil.which("cmake") is None:
        _set_simulated_fallback("cmake is not installed")
        return

    try:
        _build_native(root, build_dir)
    except Exception as exc:
        _set_simulated_fallback(f"native build failed: {exc}")
        return

    candidates = sorted(build_dir.glob("**/wfs_core_native*.so"))
    if not candidates:
        _set_simulated_fallback("native build produced no module")
        return

    sys.path.insert(0, str(candidates[0].parent))
    try:
        import wfs_core_native  # type: ignore  # noqa: F401
    except Exception as exc:
        _set_simulated_fallback(f"native module import failed: {exc}")


def _detect_public_host() -> str:
    forced = os.environ.get("WIIDOWNLOADER_PUBLIC_HOST", "").strip()
    if forced:
        return forced

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        value = sock.getsockname()[0]
        sock.close()
        if value:
            return value
    except Exception:
        pass

    return "127.0.0.1"


def _open_browser_delayed(url: str) -> None:
    time.sleep(1.25)
    try:
        webbrowser.open(url, new=1)
    except Exception:
        pass


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Wii U downloader web app without Docker")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=18180, help="Bind port (default: 18180)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    parser.add_argument("--check", action="store_true", help="Validate setup and exit")
    parser.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="Skip automatic .venv/dependency bootstrap",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    root = _project_root()
    args = _parse_args(argv)

    if not args.no_bootstrap:
        _bootstrap_venv_if_needed(root, argv)

    _set_default_env(root, args.host, args.port)
    _ensure_native_module(root)

    public_host = _detect_public_host()
    url = f"http://{public_host}:{args.port}"

    print(f"[wiidownloader] root={root}")
    print(f"[wiidownloader] serving={url}")
    print(f"[wiidownloader] keys={os.environ.get('KEYS_DIR')}")
    print(f"[wiidownloader] backend={os.environ.get('WFS_BACKEND')}")

    if not sys.platform.startswith("linux"):
        print(
            "[wiidownloader] note: full USB attach/install is validated on Linux hosts. "
            "On macOS/Windows, use a Linux VM/WSL or a Linux NAS for real disk writes."
        )

    if args.check:
        return 0

    if not args.no_browser:
        threading.Thread(target=_open_browser_delayed, args=(url,), daemon=True).start()

    import uvicorn

    uvicorn.run("apps.api.main:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
