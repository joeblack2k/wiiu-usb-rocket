# Release and Rollback Runbook

## Safety gates before write

1. Start in dry-run mode:
   - `DRY_RUN=true`
2. Validate attach and key status:
   - `GET /api/disks/scan`
   - `POST /api/disks/attach`
3. Queue one known small title and run once.
4. Enable fallback only if explicitly desired:
   - `POST /api/settings/fallback`
5. Enable real writes only after confirmation:
   - set `DRY_RUN=false`
   - set `FIRST_WRITE_CONFIRMED=true`

## First-write confirmation policy

- Real writes are blocked when:
  - `DRY_RUN=false`
  - and `first_write_confirmed=false`
- This prevents accidental mutation on initial setup.

## Emergency stop

1. Pause worker:
   - `POST /api/queue/pause`
2. Stop container:
   - `docker compose stop`
3. Preserve logs and database:
   - `./logs`
   - `./data/app.db`

## Backup strategy

- Before first production write, take raw image backup of target disk:
  - `dd if=/dev/sdX of=/backup/wiiu-usb.img bs=4M status=progress`
- Keep checksum for backup file:
  - `sha256sum /backup/wiiu-usb.img > /backup/wiiu-usb.img.sha256`

## Restore strategy

- Restore disk image in maintenance window:
  - `dd if=/backup/wiiu-usb.img of=/dev/sdX bs=4M status=progress`
- Re-run `POST /api/disks/attach` and confirm integrity.

