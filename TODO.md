# TODO — Handover & Next Steps (Beginner-Friendly)

Dit document beschrijft:
1. Wat al gebouwd is.
2. Wat nog ontbreekt.
3. Welke concrete taken nog openstaan.
4. Exacte stappen om veilig verder te bouwen.

## 1) Huidige status (al geïmplementeerd)

- FastAPI + worker + SQLite queue werkt.
- Native `wfs_core` module bouwt en laadt in Docker (`wfs_core_native`).
- Disk attach-guardrails werken:
  - alleen `/dev/*`
  - block-device check
  - key-validatie
  - nette foutmeldingen
- Catalog-service is resilient (geen 500 bij upstream-fouten).
- Nieuwe vault-fallback toegevoegd:
  - app zoekt standaard `keys/vault.tar.gz`
  - archive wordt veilig uitgepakt in `data/vault_cache/vault`
  - grootste `json` payload wordt geparsed naar catalog-items
  - `GET /api/catalog` geeft `source` en `source_status` terug

## 2) Scope van deze TODO

Dit document bevat alleen:
- concrete engineering-taken voor deze codebase,
- operationele verbeteringen,
- test- en observability-werk.

## 3) Technische TODO’s die direct kunnen

### A. Vault UX afronden

**Doel:** gebruiker ziet meteen of `vault.tar.gz` geldig is.

- Voeg endpoint toe: `GET /api/catalog/source`
  - retourneer: `archive_present`, `archive_size`, `last_extract_time`, `item_count`, `status`, `last_error`.
- Voeg UI-block op `/status` toe met:
  - vault aanwezig/afwezig
  - datum laatste extractie
  - aantal items

**Acceptatiecriteria**
- Zonder vault: API retourneert `archive_present=false` zonder exceptions.
- Met vault: API toont `item_count>0` als JSON geldig is.

### B. Vault import robuuster maken

**Doel:** import blijft stabiel bij vreemde archieven.

- Voeg limieten toe in `core/catalog/vault_archive.py`:
  - max archive grootte (bijv. 256 MB)
  - max individuele file grootte (bijv. 64 MB)
  - max file count (bijv. 10.000)
- Voeg expliciete foutcodes toe:
  - `vault_not_found`
  - `vault_too_large`
  - `vault_no_json_payload`
  - `vault_json_parse_error`

**Acceptatiecriteria**
- Elke foutcode is reproduceerbaar in unit-tests.
- `GET /api/catalog` blijft altijd HTTP 200 met degraded/fallback status.

### C. Catalog normalisatie uitbreiden

**Doel:** consistente records voor zoek/filter.

- Voeg normalisatie toe voor:
  - `name` trim/newline normalisatie
  - `region` whitelist (`EUR`, `USA`, `JPN`, `ALL`, `UNK`)
  - lege velden fallbacken
- Dedupe-strategie documenteren in code (`title_id + region`).

**Acceptatiecriteria**
- Parser-tests dekken mixed-case keys en ontbrekende velden.

### D. Queue integratie verbeteren met catalog-metadata

**Doel:** queue-items tonen nette titelnaam i.p.v. alleen title_id.

- Bij toevoegen queue-item:
  - zoek item in current catalog
  - set `catalog_title` in DB
- Bij lijstweergave queue:
  - toon naam + regio + category.

**Acceptatiecriteria**
- `POST /api/queue/items` zet `catalog_title` wanneer beschikbaar.

### E. Operationele hardening

**Doel:** beheer eenvoudiger maken op productiehost.

- Voeg startup-check toe die waarschuwt als:
  - `keys/otp.bin` ontbreekt
  - `keys/seeprom.bin` ontbreekt
- Voeg `/healthz/details` endpoint toe met:
  - native module loaded
  - disk attached
  - keys present
  - vault present

**Acceptatiecriteria**
- Geen crash bij ontbrekende onderdelen; alleen duidelijke statusvelden.

## 4) Beginner-runbook: hoe je dit oppakt

1. **Start lokaal tests**
   - `pytest -q`
   - `ruff check .`
2. **Werk per TODO in kleine PR’s**
   - 1 feature = 1 PR
   - voeg minimaal 1 unit-test toe per nieuw codepad
3. **Deploy pas na green tests**
   - push naar `main`
   - wacht GHCR workflow success
   - pull + restart container
4. **Verifieer live**
   - `/healthz`
   - `/api/catalog?limit=5`
   - `/status`

## 5) Minimaal implementatieplan voor nieuwe engineer

- Stap 1: Endpoint `GET /api/catalog/source` toevoegen.
- Stap 2: UI statuskaart voor vault toevoegen.
- Stap 3: Vault limieten + foutcodes implementeren.
- Stap 4: Catalog normalisatie + tests uitbreiden.
- Stap 5: Queue metadata enrichment implementeren.
- Stap 6: Health details endpoint + docs.

## 6) Definition of done (projectfase)

Deze fase is klaar als:

- app nooit meer 500 geeft bij catalog-problemen,
- vault-import volledig observeerbaar is,
- queue bruikbare catalog-metadata toont,
- health endpoints alle kritieke dependencies rapporteren,
- test-suite groen blijft op CI.
