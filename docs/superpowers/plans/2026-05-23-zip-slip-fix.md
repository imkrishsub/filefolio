# Zip slip fix implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent path traversal (zip slip) attacks in the `/restore` endpoint by validating each ZIP entry's resolved destination path before extraction.

**Architecture:** Add a module-level `_safe_extract` helper to `backend/main.py` that resolves the destination path and raises `ValueError` if it escapes `BASE_DIR`. Replace the three bare `zip_file.extract()` calls in `/restore` with calls to this helper. Add a `ValueError` exception handler that returns HTTP 400.

**Tech Stack:** Python 3.10, FastAPI, `pathlib.Path`, `zipfile` (stdlib)

---

## Files

- Modify: `backend/main.py` — add `_safe_extract` helper above `/restore`, replace 3 extract calls, add `ValueError` catch
- Modify: `tests/test_api.py` — add `test_restore_rejects_zip_slip`

---

## Task 1: Write the failing test

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add the failing test to `tests/test_api.py`**

  Append the following class at the end of the file:

  ```python
  class TestRestoreEndpoint:
      """Tests for the /restore endpoint."""

      def test_restore_rejects_zip_slip(self, tmp_path, monkeypatch):
          """ZIP entries with path traversal sequences must be rejected."""
          import zipfile
          import backend.main as main
          from fastapi.testclient import TestClient
          from backend.sync_service import SyncFolderService

          base_dir = tmp_path / "base"
          (base_dir / "data").mkdir(parents=True)
          (base_dir / "uploads").mkdir()
          (base_dir / "thumbnails").mkdir()

          monkeypatch.setattr(main, "BASE_DIR", base_dir)
          monkeypatch.setattr(main, "DATA_DIR", base_dir / "data")
          monkeypatch.setattr(main, "DB_PATH", base_dir / "data" / "documents.db")
          monkeypatch.setattr(main, "UPLOAD_DIR", base_dir / "uploads")
          monkeypatch.setattr(main, "THUMBNAILS_DIR", base_dir / "thumbnails")

          main.init_db()
          main.sync_service = SyncFolderService(
              base_dir / "data" / "documents.db",
              base_dir / "uploads",
              base_dir / "thumbnails",
          )

          client = TestClient(main.app)

          # "uploads/../../pwned.pdf" resolves to tmp_path/pwned.pdf — outside base_dir
          buf = io.BytesIO()
          with zipfile.ZipFile(buf, "w") as zf:
              zf.writestr("data/documents.db", b"SQLite format 3\x00" + b"\x00" * 84)
              zf.writestr("uploads/../../pwned.pdf", b"should not be written")
          buf.seek(0)

          pwned_path = tmp_path / "pwned.pdf"

          response = client.post(
              "/restore",
              files={"file": ("backup.zip", buf, "application/zip")},
          )

          assert response.status_code == 400
          assert "Unsafe path" in response.json()["detail"]
          assert not pwned_path.exists()
  ```

- [ ] **Step 2: Run the test to confirm it fails**

  ```bash
  cd /Users/krishna.subramanian/Code/priv/filefolio
  source venv/bin/activate
  pytest tests/test_api.py::TestRestoreEndpoint::test_restore_rejects_zip_slip -v
  ```

  Expected: FAIL — the endpoint currently returns 500 (caught by `except Exception`) instead of 400, and the path traversal is not blocked.

---

## Task 2: Implement `_safe_extract` and update `/restore`

**Files:**
- Modify: `backend/main.py:1298` (insert helper before `/restore`)
- Modify: `backend/main.py:1351,1358,1367` (replace bare `extract()` calls)
- Modify: `backend/main.py:1391` (add `ValueError` catch)

- [ ] **Step 1: Insert `_safe_extract` helper before the `/restore` endpoint (after line 1297)**

  In `backend/main.py`, insert the following between the `/backup` endpoint and the `/restore` endpoint (between the blank line at 1298 and `@app.post("/restore")` at 1299):

  ```python
  def _safe_extract(zip_file: zipfile.ZipFile, entry_name: str, base_dir: Path) -> None:
      dest = (base_dir / entry_name).resolve()
      if not dest.is_relative_to(base_dir.resolve()):
          raise ValueError(f"Unsafe path in archive: {entry_name!r}")
      zip_file.extract(entry_name, base_dir)
  ```

- [ ] **Step 2: Replace the database extraction call (line 1351)**

  Change:
  ```python
              zip_file.extract("data/documents.db", BASE_DIR)
  ```
  To:
  ```python
              _safe_extract(zip_file, "data/documents.db", BASE_DIR)
  ```

- [ ] **Step 3: Replace the PDF extraction call (line 1358)**

  Change:
  ```python
                  zip_file.extract(pdf_file, BASE_DIR)
  ```
  To:
  ```python
                  _safe_extract(zip_file, pdf_file, BASE_DIR)
  ```

- [ ] **Step 4: Replace the thumbnail extraction call (line 1367)**

  Change:
  ```python
                  zip_file.extract(thumb_file, BASE_DIR)
  ```
  To:
  ```python
                  _safe_extract(zip_file, thumb_file, BASE_DIR)
  ```

- [ ] **Step 5: Add `ValueError` catch before `zipfile.BadZipFile` (around line 1391)**

  The existing except block starts with:
  ```python
      except zipfile.BadZipFile:
  ```

  Insert the following immediately before it:
  ```python
      except ValueError as e:
          try:
              os.unlink(temp_backup_path)
          except OSError:
              pass
          try:
              sync_service.start()
          except Exception:
              pass
          raise HTTPException(status_code=400, detail=str(e))
  ```

- [ ] **Step 6: Run the test to confirm it passes**

  ```bash
  pytest tests/test_api.py::TestRestoreEndpoint::test_restore_rejects_zip_slip -v
  ```

  Expected: PASS

- [ ] **Step 7: Run the full test suite to check for regressions**

  ```bash
  pytest tests/ -v
  ```

  Expected: all previously passing tests continue to pass.

---

## Task 3: Commit

- [ ] **Step 1: Stage and commit**

  ```bash
  git add backend/main.py tests/test_api.py
  git commit -m "fix(security): block zip slip in /restore via path resolution check

  Add _safe_extract helper that resolves each ZIP entry's destination
  path and raises ValueError if it escapes BASE_DIR. Replace all three
  bare zipfile.extract() calls in /restore. Add test covering a crafted
  entry with path traversal sequences.

  Co-authored-by: Claude <claude@anthropic.com>"
  ```
