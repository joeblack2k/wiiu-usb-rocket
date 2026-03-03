# Direct Wii U USB Installer

Dockerized FastAPI + worker application that manages a web queue, fetches catalog data, downloads title artifacts, and writes to Wii U WFS targets through an integrated native `wfs_core` module built from vendored `wfslib`/`wfs-tools` source.

## Features

- REST API v1 for catalog, queue, jobs, disk scanning/attach, install execution, and fallback settings.
- Server-rendered Web GUI with queue and status pages.
- SQLite-backed queue/job state machine.
- Catalog parser/cache for NUSspli C-array feed format.
- Safe attach flow with key checks and disk guardrails.
- Worker pipeline with explicit fallback behavior and diagnostics.
- Vendored `wfslib` + patch scaffold for mutation primitives in native layer.

## Quick start

1. Put keys in `./keys`:
   - `keys/otp.bin` (0x400 bytes)
   - `keys/seeprom.bin` (0x200 bytes)
2. Start with Docker Compose:

```bash
docker compose up --build
```

3. Open:
   - API docs: `http://localhost:8080/docs`
   - Web UI: `http://localhost:8080/`

## Environment

- `WIIU_DISK=/dev/sdX` optional default target.
- `ALLOW_FALLBACK=true|false` default `false`.
- `WFS_BACKEND=auto|native|simulated` default `auto`.
- `DRY_RUN=true|false` default `true`.
- `FIRST_WRITE_CONFIRMED=true|false` default `false`.

## Development (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest
uvicorn apps.api.main:app --reload

# optional native build
./scripts/build_native.sh
```

## Operations

- Release/rollback runbook: `docs/release-rollback.md`
