# Upstream Patch Log

## Vendored sources

- `wfslib` pinned at commit `fafa996876a59beb5a5514ebad01c2fe45ed8f39`
- `wfs-tools` pinned at commit `98b5979d9652e6b51cd240e5a7dfa5289cbc9303`

## Local patches

### `wfslib`

1. `include/wfslib/errors.h`, `src/errors.cpp`
   - Added explicit mutation-related errors:
     - `kAlreadyExists`
     - `kInvalidArgument`
     - `kDirectoryNotEmpty`
     - `kOperationNotSupported`

2. `include/wfslib/directory.h`, `src/directory.cpp`
   - Added mutable directory primitives:
     - `CreateDirectory`
     - `CreateFile`
     - `DeleteEntry`
   - Added metadata construction helpers for new entries.

3. `CMakeLists.txt`
   - Relaxed compiler minimums for container portability.

### `wfs-tools`

- No direct source patch in this iteration; repository is vendored for reference/tools parity.

