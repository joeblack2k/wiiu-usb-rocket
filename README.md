# WiiDownloader — Direct Wii U USB Installer

WiiDownloader is a web app that helps you queue Wii U titles, download content, and write installs to a Wii U USB disk.

It has two ways to run:
- **Docker mode** (good for Linux servers/NAS)
- **Single-command mode** (`python3 wiidownloader.py`) for local use

---

## 1) Very Important Safety Notes

- Use only your own legal dumps/backups.
- This tool writes directly to USB block devices. Choosing the wrong disk can destroy data.
- `otp.bin` and `seeprom.bin` are sensitive per-console key files. **Never share or upload them.**
- Nintendo-valid signatures cannot be generated locally from `otp.bin`/`seeprom.bin` alone.

---

## 2) What works on which OS?

| Platform | App UI / Queue | USB scan | Real Wii U disk write |
|---|---:|---:|---:|
| Linux | ✅ | ✅ | ✅ (recommended) |
| Windows | ✅ | ✅ via WSL/Linux backend | ✅ via WSL2 + USB passthrough |
| macOS | ✅ | ✅ via Linux VM backend | ✅ via Linux VM + USB passthrough |

### Practical meaning

- **For real USB installs, use a Linux runtime** (native Linux, WSL2 Linux distro, or Linux VM).
- Windows/macOS can still use the browser UI, but the low-level disk attach/install path is validated on Linux hosts.

---

## 3) Fastest start (non-technical)

### A. Download and start

```bash
git clone <repo-url>
cd wiiu
python3 wiidownloader.py
```

The launcher will:
- create `.venv`
- install Python dependencies
- try to build native `wfs_core`
- start web server at `http://<your-ip>:18180`
- open your browser automatically

If browser does not open, manually go to:
- `http://127.0.0.1:18180` (same machine)
- or `http://<LAN-IP>:18180` (from another device)

### B. Put key files in the right place

Place these files in the `keys/` folder:
- `keys/otp.bin` (1024 bytes)
- `keys/seeprom.bin` (512 bytes)
- optional `keys/vault.tar.gz` (user-supplied ticket vault)

You can verify sizes quickly:

```bash
ls -l keys/otp.bin keys/seeprom.bin
```

---

## 4) End-user workflow (scan USB + install games)

1. Open **Status** page.
2. Confirm:
   - Keys = OK
   - Backend = native
3. Click **Scan USB disks**.
4. Choose your Wii U disk and click **Attach**.
5. Open **Catalog** page:
   - Search by name
   - Filter Region
   - Filter Game / DLC
6. Add one or multiple titles to queue.
7. Open **Queue** page and click **Start Queue**.
8. Watch live progress per title.
9. Open **HDD** tab to inspect installed titles and space usage.

If a job fails, open job details and check `Diagnostics` + `Events`.

---

## 5) Docker setup (Linux host)

Use this when running on a Linux box/NAS.

### A. Prepare folders

```bash
mkdir -p keys data logs
```

Put your key files in `keys/`.

### B. Start

```bash
docker compose up --build -d
```

Default URL:
- `http://localhost:18080`

### C. Stop

```bash
docker compose down
```

---

## 6) Windows guide (recommended path)

For real USB writes on Windows, use **WSL2 + USB passthrough**.

1. Install WSL2 (Ubuntu).
2. Install Docker Desktop (optional) or run directly in WSL2.
3. Attach USB disk into WSL2 (using `usbipd-win` workflow).
4. Clone repo inside WSL and run:
   ```bash
   python3 wiidownloader.py
   ```
5. Open `http://localhost:18180` in Windows browser.

If USB is not visible in WSL, disk scan/attach cannot work.

---

## 7) macOS guide (recommended path)

For real USB writes on macOS, run a Linux VM (UTM/VMware/Parallels) and pass through the USB disk.

1. Create Linux VM.
2. Pass the Wii U USB disk to VM.
3. Clone repo in VM.
4. Run:
   ```bash
   python3 wiidownloader.py
   ```
5. Open VM IP on port `18180` from your Mac browser.

---

## 8) Required host dependencies (for native backend)

On Debian/Ubuntu Linux:

```bash
sudo apt-get update
sudo apt-get install -y \
  cmake ninja-build g++ make pkg-config \
  libboost-dev libcrypto++-dev pybind11-dev
```

Then verify launcher can build native module:

```bash
python3 wiidownloader.py --check --no-browser
```

You want to see:
- `backend=native`

---

## 9) Protect your keys (do this before pushing git)

This repo is configured to ignore secrets:
- `keys/`
- `vault.tar.gz`
- `vault/`

Still verify before any push:

```bash
git status --short
```

It should **not** list `keys/otp.bin` or `keys/seeprom.bin`.

If they ever show up accidentally:

```bash
git rm --cached -r keys
```

---

## 10) Common errors and fixes

### "No active disk attachment"
- Open Status/HDD page.
- Scan USB disks.
- Attach correct `/dev/sdX` disk.

### "Invalid WFS version"
- Usually wrong device path or damaged filesystem metadata.
- Re-scan and ensure it is the actual Wii U formatted USB disk.

### "metadata-only download is not a valid install payload"
- Title source has metadata but no installable content artifact.
- Pick alternate region/source for that title.

### "backend=simulated"
- Native module did not build.
- Install host dependencies and rerun `--check`.

---

## 11) Useful commands

```bash
# Start app without auto-opening browser
python3 wiidownloader.py --no-browser

# Bind custom host/port
python3 wiidownloader.py --host 0.0.0.0 --port 18180

# Validate setup only
python3 wiidownloader.py --check
```

---

## 12) Developer notes

- API: FastAPI backend + queue worker + SQLite store
- Native write path: integrated `wfslib`/`wfs-tools` sources via `wfs_core`
- Source tree:
  - `apps/` (API + worker)
  - `core/` (services, models, settings)
  - `native/wfs_core/` (C++ native module)
  - `third_party/` (vendored upstream libs)

