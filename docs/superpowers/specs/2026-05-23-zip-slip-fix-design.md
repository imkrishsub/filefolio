# Design: fix zip slip vulnerability in `/restore`

**Date:** 2026-05-23
**Status:** Approved

## Problem

The `/restore` endpoint accepts a ZIP upload and calls `zipfile.extract(entry_name, BASE_DIR)` for each file it restores (database, PDFs, thumbnails). The prefix filters (`startswith("uploads/")`, `startswith("thumbnails/")`) check only the raw string from the ZIP central directory — they do not resolve the path. A crafted entry name such as `uploads/../../../../etc/cron.d/evil` passes the filter and writes outside `BASE_DIR`.

Python 3.12 introduced `zipfile` `filter='data'` to handle this at the stdlib level, but the project targets Python 3.10, so that option is unavailable.

## Chosen approach

Add a `_safe_extract` helper that resolves the destination path before delegating to `zipfile.extract()`. Reject the entire archive (HTTP 400, no data written) if any entry resolves outside `BASE_DIR`.

## Helper: `_safe_extract`

```python
def _safe_extract(zip_file: zipfile.ZipFile, entry_name: str, base_dir: Path) -> None:
    dest = (base_dir / entry_name).resolve()
    if not dest.is_relative_to(base_dir.resolve()):
        raise ValueError(f"Unsafe path in archive: {entry_name!r}")
    zip_file.extract(entry_name, base_dir)
```

- Placed as a module-level helper in `backend/main.py`, above the `/restore` endpoint.
- Uses `Path.is_relative_to()` (available since Python 3.9).
- Raises `ValueError` on violation; the caller maps this to HTTP 400.

## Changes to `/restore`

Replace the three bare `zip_file.extract()` calls with `_safe_extract()`:

| Original | Replacement |
|---|---|
| `zip_file.extract("data/documents.db", BASE_DIR)` | `_safe_extract(zip_file, "data/documents.db", BASE_DIR)` |
| `zip_file.extract(pdf_file, BASE_DIR)` | `_safe_extract(zip_file, pdf_file, BASE_DIR)` |
| `zip_file.extract(thumb_file, BASE_DIR)` | `_safe_extract(zip_file, thumb_file, BASE_DIR)` |

Add a `ValueError` catch before the existing `zipfile.BadZipFile` catch:

```python
except ValueError as e:
    os.unlink(temp_backup_path)
    raise HTTPException(status_code=400, detail=str(e))
```

This catch must come before any data is written. Validation for a given entry happens inside `_safe_extract` immediately before that entry's `extract()` call. Since entries are extracted sequentially (database first, then PDFs, then thumbnails), a malicious entry in the PDFs or thumbnails list will be caught before its `extract()` runs. The database entry is extracted first — if that entry were malicious it would be caught before writing. This is fail-closed for each entry.

## Test

New test in `tests/test_api.py`: `test_restore_rejects_zip_slip`.

1. Build a ZIP in memory with two entries:
   - `data/documents.db` (minimal valid SQLite bytes, so the "missing database" check passes)
   - `uploads/../../../../tmp/filefolio_pwned.txt` (the malicious entry)
2. POST to `/restore`.
3. Assert response status is 400.
4. Assert `detail` contains "Unsafe path".
5. Assert `/tmp/filefolio_pwned.txt` does not exist on disk.

## Out of scope

- File size limits on `/restore` (tracked separately as a high-priority task).
- Other zip-related endpoints (`/backup` only writes, never reads untrusted zip content).
