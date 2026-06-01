# FileFolio — Copilot Instructions

## Commands

```bash
# Run the app
python backend/main.py              # Starts server at http://127.0.0.1:8000
PORT=8080 python backend/main.py    # Custom port

# Tests
pytest                              # Full suite
pytest tests/test_api.py            # Single test file
pytest tests/test_api.py::TestUploadEndpoint::test_upload_valid_pdf  # Single test
pytest --cov=backend --cov-report=term  # With coverage

# Linting (must all pass before committing)
black backend
isort backend
flake8 backend --max-line-length=127

# CI note: rumps is macOS-only — it's excluded during CI runs via grep -v "rumps"
```

## Architecture

The app is a **local-first PDF organizer** with no cloud dependencies.

```
backend/main.py        — Single FastAPI app: all routes, DB init, PDF pipeline
backend/sync_service.py — Folder watcher (watchdog); monitors configured paths for new PDFs
frontend/static/app.js  — Vanilla JS SPA (no framework)
frontend/static/i18n.json — All UI strings (multi-language support)
frontend/templates/index.html — Single HTML template served by FastAPI
```

### Document processing pipeline (upload or sync)

1. SHA-256 hash → reject duplicate (HTTP 409)
2. PyPDF text extraction → OCR fallback via pytesseract (`eng+deu`) if text < 50 chars
3. `generate_thumbnail()` — pdf2image, first page, 300×400px JPEG
4. `process_document()` — calls Ollama (`llama3.2`) with a structured prompt; falls back to rule-based extraction if Ollama is unavailable
5. INSERT into `documents` table → FTS5 triggers keep `documents_fts` in sync automatically

### Database

SQLite at `data/documents.db`. Two main tables:

- `documents` — stores all metadata; `tags` column is a **JSON array string** (`json.dumps(list)`)
- `documents_fts` — FTS5 virtual table; kept in sync via INSERT/UPDATE/DELETE triggers
- `sync_folders` — paths registered for automatic watching

`get_db_connection()` in `main.py` is the only DB entry point: it sets `row_factory = sqlite3.Row` (column access by name) and a 30s busy timeout.

### SyncFolderService

`SyncFolderService` (in `sync_service.py`) manages watchdog `Observer` instances, one per enabled sync folder. It re-uses the same processing pipeline as the upload endpoint. Import pattern inside `sync_service.py`:

```python
try:
    from backend.main import process_document, ...
except ModuleNotFoundError:
    from main import process_document, ...
```

This dual-import is intentional: the module may be run directly or as part of a package.

## Key conventions

- **All routes are in `main.py`** — there is no router splitting. Keep it that way unless the file grows significantly.
- **tags are stored as JSON strings**, not arrays. Always use `json.dumps(list)` on write and `json.loads(str)` on read. Handle `json.JSONDecodeError` defensively.
- **Valid categories are a fixed enum**: `Invoice, Receipt, Contract, Letter, Report, Form, Statement, Legal, Medical, Tax, Insurance, Other`. Any new LLM prompt must use this exact list.
- **Stored filenames** are prefixed with `YYYYMMDD_HHMMSS_` to avoid collisions. Never rely on original filename for filesystem paths.
- **Text extraction limit**: only first 20 pages are processed for performance. OCR runs at 300 DPI.
- **Ollama model**: `llama3.2` (not vision variant). The prompt enforces English-only tags regardless of document language.

## Testing

`tests/conftest.py` provides shared fixtures:

- `client` — FastAPI `TestClient` with a temp DB and directories
- `mock_ollama_response` — monkeypatches `ollama.chat` to avoid needing a running instance
- `sample_pdf_bytes` / `sample_pdf_file` — minimal valid PDF via `pypdf.PdfWriter`

Tests that need Ollama/Tesseract are marked with `@pytest.mark.requires_ollama` / `@pytest.mark.requires_tesseract`. Skip them in CI with `-m "not requires_ollama"`.
