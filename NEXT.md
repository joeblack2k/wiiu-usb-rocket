# NEXT.md — Technische implementatiefases: download + WFS-installatie

## Huidige staat (referentie)

| Module | Status |
|---|---|
| `core/nus/ticket.py` | Gereed — parse + AES-128-CBC title key decryptie |
| `core/nus/tmd.py` | Gereed — parse + content lijst |
| `core/services/download_service.py` | Stub — downloadt geen echte NUS content |
| `apps/worker/runner.py` DECRYPTING-fase | Passthrough — doet geen echte decryptie |
| `core/services/writer_engine.py` | Gereed — schrijft naar WFS via adapter |
| `core/services/wfs_adapter.py` | Gereed — SimulatedWfsAdapter + NativeWfsAdapter |

---

## Fase 1 — Settings uitbreiden

**Bestand:** `core/config.py`

Wijzig `nus_base_url` in `Settings`:

```python
nus_base_url: str = Field(
    default="http://nus.cdn.wup.shop.nintendo.net/ccs/download",
    alias="LINK",
)
```

Prioriteit: als `LINK` gezet is in ENV, wordt die waarde gebruikt. Zonder `LINK` geldt de Nintendo CDN-URL als fallback.

Gedrag:

```
LINK niet gezet  →  http://nus.cdn.wup.shop.nintendo.net/ccs/download
LINK=http://nus.cdn.wup.shop.eigendomein.net/ccs/download  →  die URL
```

`NusClient` (Fase 2) krijgt `settings.nus_base_url` mee — geen verdere aanpassing nodig in de client zelf. De URL-structuur `{base_url}/{title_id}/{resource}` blijft identiek ongeacht welke base URL actief is.

Validatie in `startup()` in `apps/api/main.py`:

```python
logger.info("NUS base URL: %s", settings.nus_base_url)
```

---

## Fase 1b — WIIU_COMMON_KEY validatie tegen otp.bin

**Bestand:** `core/nus/key_validator.py` (nieuw)

```python
_OTP_COMMON_KEY_OFFSET = 0xE0
_OTP_COMMON_KEY_LENGTH = 16

def validate_common_key_against_otp(common_key_hex: str, otp_path: Path) -> None:
    """
    Leest 16 bytes op offset 0xE0 uit otp.bin en vergelijkt met common_key_hex.
    Logt een waarschuwing als ze niet overeenkomen. Gooit geen exception.
    """
```

Logica:

```
1. Lees otp_path als binaire data.
2. Extraheer otp_key = data[0xE0 : 0xE0 + 16].
3. Als WIIU_COMMON_KEY niet gezet is in ENV:
       os.environ["WIIU_COMMON_KEY"] = otp_key.hex()
       # Programma start door met otp_key als actieve common key. Geen waarschuwing.
4. Anders:
       Converteer common_key_hex naar bytes via bytes.fromhex().
       Als otp_key != common_key_bytes:
           logger.warning(
               'Waarschuwing de key komt niet overeen met de otp.bin. '
               'key opgegeven in ENV="%s" key in otp.bin="%s"',
               common_key_hex,
               otp_key.hex(),
           )
           os.environ["WIIU_COMMON_KEY"] = otp_key.hex()
           # Programma start door met otp_key als actieve common key.
5. Retourneert de actieve common key als bytes.
6. Als otp.bin niet bestaat of te klein is en ENV ook leeg is: raise TicketError("WIIU_COMMON_KEY is niet gezet en otp.bin is niet beschikbaar").
7. Als otp.bin niet bestaat maar ENV wel gezet is: ENV-waarde gebruiken, geen validatie, geen waarschuwing.
```

Signatuur wordt:

```python
def resolve_common_key(otp_path: Path) -> bytes:
    """
    Bepaalt de actieve common key op basis van ENV en/of otp.bin.
    Schrijft de actieve key altijd terug naar os.environ["WIIU_COMMON_KEY"].
    """
```

**Bestand:** `apps/api/main.py`, functie `startup()`

Vervang het vorige blok door:

```python
from core.nus.key_validator import resolve_common_key

resolve_common_key(settings.otp_path)
# Na deze aanroep staat WIIU_COMMON_KEY in os.environ gegarandeerd op de actieve key.
```

Import `os` bovenaan `main.py` toevoegen als nog niet aanwezig.

---

## Fase 2 — NUS HTTP-client

**Bestand:** `core/nus/nus_client.py` (nieuw)

```
NusClient(base_url: str, timeout: float, work_dir: Path)
    .fetch_tmd(title_id: str) -> bytes
    .fetch_cetk(title_id: str) -> bytes
    .fetch_content(title_id: str, content_id_hex: str, dest: Path) -> Path
```

- `fetch_tmd` / `fetch_cetk`: `GET {base_url}/{title_id}/tmd` en `.../cetk` — retourneert raw bytes in-memory.
- `fetch_content`: `GET {base_url}/{title_id}/{content_id_hex}` — streamt naar `dest` via `httpx.stream()` in chunks van 131072 bytes. Ondersteunt resume via `Range: bytes={existing_size}-` als `dest` al bestaat. Retourneert `dest`.
- Gebruikt bestaand `httpx` (geen nieuwe dependency).
- Raises `httpx.HTTPStatusError` bij non-2xx.

---

## Fase 3 — `.app` decryptie module

**Bestand:** `core/nus/app_decryptor.py` (nieuw)

```
decrypt_app(
    src: Path,
    dest: Path,
    title_key: bytes,       # 16 bytes — uit TicketInfo.title_key
    index: bytes,           # 2 bytes — uit ContentRecord.index
    block_size: int = 65536
) -> int                    # bytes geschreven
```

- IV = `index + b"\x00" * 14` (totaal 16 bytes).
- AES-128-CBC via `cryptography.hazmat.primitives.ciphers`.
- Leest `src` in blokken van `block_size` bytes. `block_size` moet een veelvoud zijn van 16.
- Laatste blok: geen extra padding verwijderen — NUS `.app` bestanden zijn al uitgelijnd op AES-blokgrootte.
- Schrijft gedecrypteerde data naar `dest`.
- Retourneert het aantal bytes dat naar `dest` is geschreven.

---

## Fase 4 — `DownloadService.download_title()` vervangen

**Bestand:** `core/services/download_service.py`

Vervang de huidige implementatie van `download_title()`. De nieuwe flow:

```
1. NusClient.fetch_tmd(title_id)          → tmd_bytes: bytes
2. parse_tmd_bytes(tmd_bytes)             → TmdInfo
3. Schrijf tmd_bytes naar work_dir/tmd
4. NusClient.fetch_cetk(title_id)         → cetk_bytes: bytes
5. Schrijf cetk_bytes naar work_dir/cetk
6. Voor elk ContentRecord in TmdInfo.contents:
       NusClient.fetch_content(title_id, record.content_id_hex, work_dir/{record.content_id_hex}.app)
7. Stel tmd_present = True, ticket_present = True
8. Bouw artifacts lijst:
       - kind="tmd",    local_path=work_dir/tmd,    target_path=/usr/title/{title_id}/meta/tmd
       - kind="cetk",   local_path=work_dir/cetk,   target_path=/usr/title/{title_id}/meta/cetk
       - kind="content", local_path=work_dir/{cid}.app, target_path=/usr/title/{title_id}/content/{cid}.app
         (voor elk ContentRecord)
9. Retourneer DownloadResult
```

Voeg toe aan `DownloadResult`:

```python
tmd_info: TmdInfo | None = None
cetk_bytes: bytes | None = None
```

`cetk_bytes` wordt in Fase 5 gebruikt voor de decryptie zonder opnieuw van schijf te lezen.

---

## Fase 5 — Decryptiefase in worker activeren

**Bestand:** `apps/worker/runner.py`

Vervang in `_process_queue_item()` het DECRYPTING-blok:

```python
# huidig:
self._queue_service.add_job_event(job_id, "decrypt", {"mode": "passthrough", ...})

# nieuw:
ticket_info = parse_ticket_bytes(download_result.cetk_bytes)
decrypted_artifacts = []
for artifact in download_result.artifacts:
    if artifact.kind != "content":
        decrypted_artifacts.append(artifact)
        continue
    dec_path = artifact.local_path.with_suffix(".dec")
    content_record = next(
        r for r in download_result.tmd_info.contents
        if r.content_id_hex == artifact.local_path.stem
    )
    written = decrypt_app(artifact.local_path, dec_path, ticket_info.title_key, content_record.index)
    decrypted_artifacts.append(dataclasses.replace(artifact, local_path=dec_path, size=written))
download_result = dataclasses.replace(download_result, artifacts=decrypted_artifacts)
```

Imports die toegevoegd moeten worden aan `runner.py`:

```python
import dataclasses
from core.nus.ticket import parse_ticket_bytes
from core.nus.app_decryptor import decrypt_app
```

---

## Fase 6 — WFS-padmapping aanpassen

**Bestand:** `core/services/writer_engine.py`, methode `_target_path()`

Huidige logica valt terug op `/usr/title/{title_id}/content/{local_name}` als `artifact_target_path` niet absoluut is. Na Fase 4 zijn alle `target_path` waarden al absoluut ingesteld in `DownloadResult`. Geen wijziging nodig als Fase 4 correct is geïmplementeerd.

Controleer wel dat `WriterEngine.write_download_result()` de juiste WFS-directoryboom aanmaakt vóór schrijven:

```
/usr/title/{title_id}/
/usr/title/{title_id}/meta/
/usr/title/{title_id}/content/
```

`wfs_adapter.mkdir()` wordt al aangeroepen per artifact — dit is correct.

---

## Fase 7 — `InstallAnalyzer` aanpassen

**Bestand:** `core/services/install_analyzer.py`

Huidige check: `requires_fallback = True` als `ticket_present == False`.

Na Fase 4 is `ticket_present` altijd `True` als de NUS-download is geslaagd. De `oversize`-check blijft relevant: als een enkel `.app` bestand groter is dan `max_direct_file_bytes`, wordt fallback gesuggereerd.

Voeg toe: check of `tmd_info` aanwezig is op `DownloadResult`. Als `tmd_info is None`: voeg reason `tmd_not_parsed` toe en zet `requires_fallback = True`.

---

## Fase 8 — `DRY_RUN` en `FIRST_WRITE_CONFIRMED` flow

**Bestand:** `core/services/writer_engine.py`

Geen structurele wijziging. Bestaande guards zijn correct:

```python
if not dry_run and not first_write_confirmed:
    raise WfsAdapterError("First-write confirmation is required before mutating WFS")
```

Voor productie-installatie: zet `DRY_RUN=false` en `FIRST_WRITE_CONFIRMED=true` in omgeving of `.env`.

---

## Fase 9 — `NativeWfsAdapter` bouwen en laden

**Bestand:** `native/wfs_core/CMakeLists.txt`, `scripts/build_native.sh`, `deploy/docker/Dockerfile`

De native module (`wfs_core_native`) moet gebouwd zijn voor de `NativeWfsAdapter` te laden. `build_wfs_adapter()` in `core/services/wfs_adapter.py` probeert dit al via `WFS_BACKEND=auto`.

Vereisten voor productie:

- `WFS_BACKEND=native` of `WFS_BACKEND=auto`
- `WIIU_DISK=/dev/sdX` — blokdevice van de Wii U schijf
- `keys/otp.bin` en `keys/seeprom.bin` aanwezig
- Docker: `privileged: true` (al ingesteld in `docker-compose.yml`)
- De `attach`-flow via `POST /api/disks/attach` moet succesvol zijn vóór installatie

---

## Fase 10 — End-to-end activatie

Volgorde van API-aanroepen voor een volledige installatie na implementatie van Fase 1–9:

```
POST /api/disks/attach           {"device_path": "/dev/sdX"}
POST /api/queue/items            {"title_id": "0005000010101a00", "region": "EUR", "preferred_mode": "direct"}
POST /api/queue/start
GET  /api/jobs/{job_id}          → poll tot state == "DONE"
```

ENV-variabelen vereist:

```
WIIU_COMMON_KEY=<32 hex chars>
WIIU_DISK=/dev/sdX
WFS_BACKEND=native
DRY_RUN=false
FIRST_WRITE_CONFIRMED=true
ALLOW_FALLBACK=false
```
