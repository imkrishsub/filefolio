# PDF Magic Byte Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `/upload` endpoint to (1) accept uppercase `.PDF` extensions and (2) reject files that lack the `%PDF` magic byte signature, checking on the first streaming chunk for fail-fast behaviour.

**Architecture:** Two surgical edits inside `upload_pdf` in `backend/main.py` — change `endswith(".pdf")` to `lower().endswith(".pdf")`, and add a one-time magic byte check on the first chunk of the streaming loop. Three new test cases in `tests/test_api.py`.

**Tech Stack:** Python 3, FastAPI, pytest

---

### Task 1: Set up worktree

**Files:**
- Worktree: `../filefolio-fix-pdf-magic-byte-validation`

- [ ] **Step 1: Create the branch and worktree**

```bash
cd /Users/krishna.subramanian/Code/priv/filefolio
git worktree add ../filefolio-fix-pdf-magic-byte-validation -b fix/pdf-magic-byte-validation
```

Expected: `Preparing worktree (new branch 'fix/pdf-magic-byte-validation')`

- [ ] **Step 2: Move into the worktree**

```bash
cd ../filefolio-fix-pdf-magic-byte-validation
```

All subsequent steps run inside this directory.

---

### Task 2: Write failing tests

**Files:**
- Modify: `tests/test_api.py` — add three test cases inside `TestUploadEndpoint`

- [ ] **Step 1: Add the three test cases**

Open `tests/test_api.py` and insert the following three methods inside the `TestUploadEndpoint` class, after `test_upload_non_pdf_rejected`:

```python
def test_upload_uppercase_extension_accepted(self, client, sample_pdf_bytes, mock_ollama_response):
    """Test that uppercase .PDF extension is accepted."""
    files = {"file": ("DOCUMENT.PDF", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    response = client.post("/upload", files=files)
    assert response.status_code == 200

def test_upload_invalid_magic_bytes_rejected(self, client):
    """Test that a file with a .pdf extension but invalid content is rejected."""
    zip_bytes = b"PK\x03\x04" + b"\x00" * 100  # ZIP magic bytes
    files = {"file": ("fake.pdf", io.BytesIO(zip_bytes), "application/pdf")}
    response = client.post("/upload", files=files)
    assert response.status_code == 400
    assert "not a valid PDF" in response.json()["detail"]

def test_upload_valid_magic_bytes_accepted(self, client, sample_pdf_bytes, mock_ollama_response):
    """Test that a file with correct %PDF magic bytes and .pdf extension is accepted."""
    files = {"file": ("valid2.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
    response = client.post("/upload", files=files)
    assert response.status_code == 200
```

- [ ] **Step 2: Run only the new tests to confirm they fail**

```bash
pytest tests/test_api.py::TestUploadEndpoint::test_upload_uppercase_extension_accepted \
       tests/test_api.py::TestUploadEndpoint::test_upload_invalid_magic_bytes_rejected \
       tests/test_api.py::TestUploadEndpoint::test_upload_valid_magic_bytes_accepted -v
```

Expected:
- `test_upload_uppercase_extension_accepted` — FAILED (400 returned, 200 expected)
- `test_upload_invalid_magic_bytes_rejected` — FAILED (200 returned, 400 expected)
- `test_upload_valid_magic_bytes_accepted` — PASSED (already works — that's fine)

---

### Task 3: Implement the fix

**Files:**
- Modify: `backend/main.py` — `upload_pdf` function, lines ~370 and ~381-391

- [ ] **Step 1: Fix case-insensitive extension check**

In `backend/main.py`, find:

```python
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
```

Replace with:

```python
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
```

- [ ] **Step 2: Add magic byte check on first streaming chunk**

Find the streaming loop (around line 381):

```python
    sha256_hash = hashlib.sha256()
    bytes_written = 0
    with file_path.open("wb") as buffer:
        while chunk := await file.read(8192):
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_SIZE:
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum upload size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.",
                )
            sha256_hash.update(chunk)
            buffer.write(chunk)
```

Replace with:

```python
    sha256_hash = hashlib.sha256()
    bytes_written = 0
    first_chunk = True
    with file_path.open("wb") as buffer:
        while chunk := await file.read(8192):
            if first_chunk:
                if chunk[:4] != b"%PDF":
                    file_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="File is not a valid PDF")
                first_chunk = False
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_SIZE:
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum upload size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.",
                )
            sha256_hash.update(chunk)
            buffer.write(chunk)
```

- [ ] **Step 3: Run the three new tests — all should pass**

```bash
pytest tests/test_api.py::TestUploadEndpoint::test_upload_uppercase_extension_accepted \
       tests/test_api.py::TestUploadEndpoint::test_upload_invalid_magic_bytes_rejected \
       tests/test_api.py::TestUploadEndpoint::test_upload_valid_magic_bytes_accepted -v
```

Expected: 3 passed.

---

### Task 4: Full test suite and lint

**Files:** None changed in this task.

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/test_api.py -v
```

Expected: All existing tests still pass plus the 3 new ones.

- [ ] **Step 2: Run linters**

```bash
black backend tests && isort backend tests && flake8 backend --max-line-length=127
```

Expected: No errors.

---

### Task 5: Commit and clean up

- [ ] **Step 1: Stage only the changed files**

```bash
git add backend/main.py tests/test_api.py docs/superpowers/specs/2026-05-23-pdf-magic-byte-validation-design.md docs/superpowers/plans/2026-05-23-pdf-magic-byte-validation.md
```

- [ ] **Step 2: Commit**

```bash
git commit -m "fix(upload): case-insensitive extension check and magic byte validation

- Accept uppercase .PDF extensions via case-insensitive endswith check
- Reject files whose first 4 bytes are not %PDF (checked on first
  streaming chunk for fail-fast behaviour)
- Add 3 new tests: uppercase extension, invalid magic bytes, valid PDF

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 3: Remove the worktree**

```bash
cd /Users/krishna.subramanian/Code/priv/filefolio
git worktree remove ../filefolio-fix-pdf-magic-byte-validation
```

Expected: Worktree directory removed; branch `fix/pdf-magic-byte-validation` persists.
