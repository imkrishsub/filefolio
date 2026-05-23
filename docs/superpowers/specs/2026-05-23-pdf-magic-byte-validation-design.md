# PDF Magic Byte Validation — Design

**Date:** 2026-05-23
**Status:** Approved

## Problem

The `/upload` endpoint has two validation weaknesses:

1. Extension check is case-sensitive: `file.filename.endswith(".pdf")` rejects `DOCUMENT.PDF`.
2. No content validation: any file renamed to `.pdf` (e.g., a ZIP or executable) passes.

## Solution

Two targeted changes to `upload_pdf` in `backend/main.py`.

### 1. Case-insensitive extension check

```python
# Before
if not file.filename.endswith(".pdf"):

# After
if not file.filename.lower().endswith(".pdf"):
```

### 2. Magic byte check on first streaming chunk

During the existing streaming loop, inspect bytes 0–4 of the first chunk for the PDF signature `%PDF` (`b"%PDF"`). On mismatch, delete the partial file and return HTTP 400.

```python
first_chunk = True
while chunk := await file.read(8192):
    if first_chunk:
        if not chunk[:4] == b"%PDF":
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="File is not a valid PDF")
        first_chunk = False
    bytes_written += len(chunk)
    ...
```

**Placement:** immediately after the size-limit guard inside the existing loop, before `sha256_hash.update(chunk)`.

**Error handling:** uses the same `file_path.unlink(missing_ok=True)` pattern as the size-limit check — consistent and leaves no partial files on disk.

## Tests

Three new test cases in `TestUploadEndpoint` (`tests/test_api.py`):

| Test | Input | Expected |
|---|---|---|
| `test_upload_uppercase_extension_accepted` | `DOCUMENT.PDF` with valid `%PDF-` content | 200 |
| `test_upload_invalid_magic_bytes_rejected` | `fake.pdf` with ZIP header (`PK\x03\x04`) | 400 |
| `test_upload_valid_magic_bytes_accepted` | `test2.pdf` with `%PDF-` content | 200 |

## Files Changed

- `backend/main.py` — `upload_pdf` function only
- `tests/test_api.py` — three new test cases in `TestUploadEndpoint`
