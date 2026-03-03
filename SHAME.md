# SHAME.md

## Scope audit against NEXT.md

| Phase | Status | Current state in codebase |
|---|---|---|
| Fase 1 | PARTIAL | `LINK` alias for `nus_base_url` exists; startup NUS base URL log added. |
| Fase 1b | NOT_IMPLEMENTED | `core/nus/key_validator.py` absent; `resolve_common_key()` not called in startup. |
| Fase 2 | NOT_IMPLEMENTED | `core/nus/nus_client.py` absent. |
| Fase 3 | NOT_IMPLEMENTED | `core/nus/app_decryptor.py` absent. |
| Fase 4 | PARTIAL | `DownloadResult` now has `tmd_info` and `cetk_bytes`; `download_title()` still does not perform full per-content (`.app`) acquisition flow from `TmdInfo.contents`. |
| Fase 5 | NOT_IMPLEMENTED | Worker DECRYPTING stage remains passthrough job event; no artifact decrypt replacement logic. |
| Fase 6 | ALREADY_SATISFIED | Writer path logic and `mkdir` behavior match stated requirement. |
| Fase 7 | IMPLEMENTED | `InstallAnalyzer` now enforces `tmd_not_parsed` fallback reason when `tmd_info is None`. |

## Missing functions/modules (explicit)

- `core/nus/key_validator.py`
  - missing: `_OTP_COMMON_KEY_OFFSET`, `_OTP_COMMON_KEY_LENGTH`
  - missing: `validate_common_key_against_otp(common_key_hex: str, otp_path: Path) -> None`
  - missing: `resolve_common_key(otp_path: Path) -> bytes`

- `core/nus/nus_client.py`
  - missing: `class NusClient`
  - missing: `fetch_tmd(title_id: str) -> bytes`
  - missing: `fetch_cetk(title_id: str) -> bytes`
  - missing: `fetch_content(title_id: str, content_id_hex: str, dest: Path) -> Path`

- `core/nus/app_decryptor.py`
  - missing: `decrypt_app(src: Path, dest: Path, title_key: bytes, index: bytes, block_size: int = 65536) -> int`

- `apps/worker/runner.py`
  - missing in DECRYPTING phase:
    - `parse_ticket_bytes(download_result.cetk_bytes)` step
    - per-content decrypt loop
    - replacement of content artifacts with decrypted paths/sizes

- `core/services/download_service.py`
  - missing in `download_title()`:
    - full `for record in tmd_info.contents` content acquisition loop
    - content artifacts generation from parsed content records for all contents
