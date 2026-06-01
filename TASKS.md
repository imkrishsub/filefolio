# TODO

## Active

### Marketing & distribution
- [x] Add Paperless-ngx comparison to README Why section
  - ID: T001
  - Date added: 2026-05-30
  - Date completed: 2026-05-30
  - Priority: high
  - Notes: Added "## FileFolio vs Paperless-ngx" section with a 6-row color-coded comparison table (🟢/🔴) immediately after the Why section. Covers AI tagging, setup, resource footprint, multi-user, feature scope, and best-for audience.

- [x] Add GitHub repository topics
  - ID: T002
  - Date added: 2026-05-30
  - Date completed: 2026-05-30
  - Priority: high
  - Notes: Added via `gh repo edit --add-topic`. Topics set: pdf, document-management, ollama, local-ai, self-hosted, privacy, fastapi, python (plus sqlite which was already present).

- [ ] Post "Show HN" on Hacker News
  - ID: T003
  - Date added: 2026-05-30
  - Priority: high
  - Notes: Single highest-leverage action. Craft the post around the privacy + local LLM angle. One good Show HN can generate 50–200 stars overnight. Post on a weekday morning US Eastern time.

- [ ] Post to r/selfhosted
  - ID: T004
  - Date added: 2026-05-30
  - Priority: high
  - Notes: ~500k members, exactly the target audience. Post with a short demo GIF or screenshot. Highlight the Ollama/AI-tagging differentiator vs Paperless-ngx.

- [ ] Submit PR to Awesome Self-Hosted list on GitHub
  - ID: T005
  - Date added: 2026-05-30
  - Priority: medium
  - Notes: Permanent passive discovery channel. The project fits under Document Management. See https://github.com/awesome-selfhosted/awesome-selfhosted for submission criteria.

- [ ] Post to r/privacy
  - ID: T006
  - Date added: 2026-05-30
  - Priority: medium
  - Notes: Privacy-focused audience that values no-cloud solutions. Frame around not uploading sensitive documents to Adobe, Google, etc.

- [x] Add Docker support
  - ID: T007
  - Date added: 2026-05-30
  - Date completed: 2026-05-30
  - Priority: medium
  - Notes: Added Dockerfile (Python 3.11-slim, Poppler, Tesseract), docker-compose.yml, and .dockerignore. Ollama runs on the host; container connects via OLLAMA_HOST (defaults to host.docker.internal:11434). HOST env var added so uvicorn binds to 0.0.0.0 inside the container. README updated with Docker quick-start.

- [x] Remove dark mode and multi-language from README features list
  - ID: T008
  - Date added: 2026-05-30
  - Date completed: 2026-05-31
  - Priority: medium
  - Notes: Removed dark mode and multi-language bullets. Rewrote the four keepers with benefit-led copy, one concrete technical anchor each. Merged to master.

### Correctness fixes
- [x] Fix `asyncio.run()` calls from watchdog thread in sync service
  - ID: T009
  - Date added: 2026-05-23
  - Date completed: 2026-05-31
  - Priority: high
  - Notes: Made _process_pdf and _process_file plain def (all I/O was synchronous). Removed asyncio.run() at both call sites and dropped the unused import. Added 3 tests verifying neither function is a coroutine.

- [x] Fix race condition in duplicate detection
  - ID: T010
  - Date added: 2026-05-23
  - Date completed: 2026-06-01
  - Priority: medium
  - Notes: Replaced non-unique idx_file_hash with a partial UNIQUE index (WHERE file_hash IS NOT NULL). Both upload_pdf and _process_pdf now catch IntegrityError at INSERT, clean up orphaned file and thumbnail, and return 409/False. Pre-check SELECT kept as fast early-exit.

- [x] Make `reindex_documents_content` crash-safe
  - ID: T011
  - Date added: 2026-05-23
  - Date completed: 2026-06-01
  - Priority: medium
  - Notes: Set isolation_level=None and wrapped the entire function in an explicit BEGIN/COMMIT/ROLLBACK. On BaseException, ROLLBACK restores the dropped triggers. Two tests added: one verifies triggers survive a KeyboardInterrupt mid-reindex, one verifies the happy path.

- [x] Use SQLite backup API in `/backup`
  - ID: T012
  - Date added: 2026-05-23
  - Date completed: 2026-06-01
  - Priority: medium
  - Notes: Replaced `zip_file.write(DB_PATH)` with `sqlite3.connect().backup()` for a consistent online snapshot safe under WAL. Added test_backup_database_is_valid_sqlite verifying the ZIP entry is a readable SQLite file with the expected schema.

- [x] Fix thumbnail filename derivation
  - ID: T013
  - Date added: 2026-05-23
  - Date completed: 2026-06-01
  - Priority: low
  - Notes: Replaced `stored_filename.replace(".pdf", ".jpg")` with `Path(stored_filename).with_suffix(".jpg").name`. Added test_thumbnail_filename_uses_path_suffix which reproduces the stem-mangling bug and verifies the fix.

- [ ] Add typed Pydantic model for `update_document` request body
  - ID: T014
  - Date added: 2026-05-23
  - Priority: low
  - Notes: `updates: dict` skips schema validation; `tags` could be sent as an integer and stored as `json.dumps(5)`, breaking downstream parsing. Replace with a typed `UpdateRequest` model.

### Test gaps
- [x] Add test for `GET /download/{doc_id}`
  - ID: T015
  - Date added: 2026-05-23
  - Date completed: 2026-05-31
  - Priority: low
  - Notes: TestDownloadSingle class added to tests/test_basic.py during the Content-Disposition security fix. Four tests: happy path, RFC 6266 encoding, injection safety, 404.

- [x] Fix vacuous FTS search assertion in `test_search_documents`
  - ID: T016
  - Date added: 2026-05-23
  - Date completed: 2026-05-31
  - Priority: low
  - Notes: Replaced isinstance(data, list) with len(data)==1 and filename check. Added test_search_no_match_returns_empty to verify FTS returns empty for non-matching terms.

- [x] Fix `test_download_multiple` in `test_basic.py`
  - ID: T017
  - Date added: 2026-05-23
  - Date completed: 2026-05-31
  - Priority: low
  - Notes: Deleted TestBulkOperations class from test_basic.py. Coverage is provided by TestBulkDownloadEndpoint in test_api.py, which uses two distinct PDFs and verifies zip content-type, 400 on empty list, and 404 on missing docs.

### Polish & Production
- [ ] Add error handling and validation improvements
  - ID: T018
  - Date added: 2025-10-27
  - Priority: medium
  - Notes: Better feedback for failed uploads, file size limits, corrupted PDFs

### Enhancements
- [ ] Add custom tagging rules/templates
  - ID: T019
  - Date added: 2025-10-27
  - Priority: medium
  - Notes: Let users define patterns for automatic categorization

- [ ] Add visual filters for document previews
  - ID: T020
  - Date added: 2026-03-08
  - Priority: medium
  - Notes: Add options to apply visual filters (brightness, contrast, grayscale, sepia) to improve readability of scanned or low-quality documents in the preview modal

- [ ] Create organized folder structure for stored PDFs
  - ID: T021
  - Date added: 2025-10-27
  - Priority: low
  - Notes: Group by category/year instead of flat uploads folder

- [ ] Export functionality (CSV, JSON)
  - ID: T022
  - Date added: 2025-10-27
  - Priority: low
  - Notes: Export document metadata and organization (will be included as part of backup/restore feature)

- [ ] Add statistics dashboard
  - ID: T023
  - Date added: 2025-10-27
  - Priority: low
  - Notes: Show document counts by category, upload trends, storage usage

- [ ] Support CLI usage for typical tasks
  - ID: T024
  - Date added: 2026-03-07
  - Priority: low
  - Notes: Command-line interface for common operations (upload, search, tag, etc.)

## Blocked

## Done
### Security fixes
- [x] Fix zip slip vulnerability in `/restore` endpoint
  - Date added: 2026-05-23
  - Date completed: 2026-05-23
  - Priority: critical
  - Notes: Added `_safe_extract` helper that resolves each entry's destination path and rejects path traversal and symlink entries. Replaced all three bare `zipfile.extract()` calls. Added `ValueError` handler returning HTTP 400. Two new tests cover path traversal and symlink cases.

- [x] Fix `Content-Disposition` header injection in `/download/{doc_id}`
  - Date added: 2026-05-23
  - Date completed: 2026-05-23
  - Priority: high
  - Notes: Replaced bare `filename=` with `filename*=UTF-8''<percent-encoded>` per RFC 6266/5987. Added `urllib.parse.quote` and removed `filename=` kwarg from `FileResponse`. Four new tests in `TestDownloadSingle` cover happy path, RFC 6266 encoding, injection safety, and 404.

- [x] Sanitize FTS5 search query beyond double-quote escaping
  - Date added: 2026-05-23
  - Date completed: 2026-05-23
  - Priority: high
  - Notes: Added `_sanitize_fts_query` helper that strips `:`, `(`, `)`, `"`, `*`, `-`, `,` from bare-word segments and lowercases AND/OR/NOT. Preserves double-quoted phrase tokens. Empty result falls back to non-FTS query path. Defence-in-depth OperationalError guard on the MATCH execute call. 13 unit tests + 6 integration tests including parametrized crash-vector coverage.

- [x] Add file size limits to `/upload` and `/restore`
  - Date added: 2026-05-23
  - Date completed: 2026-05-23
  - Priority: high
  - Notes: Added MAX_UPLOAD_SIZE (100 MB) and MAX_RESTORE_SIZE (2 GB) constants. /upload counts bytes in the existing streaming loop and returns HTTP 413 on overflow, deleting the partial file. /restore replaces await file.read() with the same streaming pattern. Added except HTTPException: raise guard so 413 is not swallowed by the generic 500 handler. 3 new tests cover all cases.

- [x] Fix PDF magic byte validation in `/upload`
  - Date added: 2026-05-23
  - Date completed: 2026-05-23
  - Priority: medium
  - Notes: Fixed case-sensitive extension check (`endswith` → `lower().endswith`). Added `%PDF` magic byte check on the first streaming chunk — fail-fast, no extra I/O. Deletes partial file and returns HTTP 400 on mismatch. Three new tests cover uppercase extension, invalid magic bytes, and valid content.

### Test gaps
- [x] Add tests for sync folder endpoints
  - Date added: 2026-05-23
  - Date completed: 2026-05-24
  - Priority: medium
  - Notes: No coverage for `/sync-folders` CRUD or `/sync-folders/{id}/scan`.

- [x] Add tests for `/backup` and `/restore` endpoints
  - Date added: 2026-05-23
  - Date completed: 2026-05-24
  - Priority: medium
  - Notes: No coverage for backup creation or restore, including the zip slip edge case.

- [x] Fix test isolation — uploaded files leak between tests
  - Date added: 2026-05-23
  - Date completed: 2026-05-24
  - Priority: medium
  - Notes: `test_db` is function-scoped but `temp_test_dir` is session-scoped; PDF files from one test accumulate across the session since only the DB is cleaned per test.

### Core functionality (MVP)
- [x] Show Ko-fi link in README.md in a prominent manner
  - Date added: 2026-03-07
  - Date completed: 2026-03-08
  - Priority: high
  - Notes: Added Ko-fi donation button to both README.md and web interface header

- [x] Support syncing from/to a folder
  - Date added: 2026-03-07
  - Date completed: 2026-03-08
  - Priority: medium
  - Notes: Implemented file system watching with watchdog library. Features: watch multiple source folders, auto-process PDFs using existing AI pipeline, optional file moving after processing, manual folder scanning, enable/disable per folder, settings UI with i18n support, comprehensive test coverage

- [x] Add language support
  - Date added: 2026-03-07
  - Date completed: 2026-03-08
  - Priority: medium
  - Notes: Implemented i18n with 5 languages (English, Spanish, French, German, Chinese), language selector with auto-detection, and full UI translation coverage

- [x] Implement loading states and animations
  - Date added: 2025-10-27
  - Date completed: 2026-03-08
  - Priority: low
  - Notes: Implemented page load fade-in, skeleton loaders, document card animations, thumbnail lazy loading, search loading indicator, and button loading states

- [x] Create automated tests
  - Date added: 2025-10-27
  - Date completed: 2026-03-07
  - Priority: medium
  - Notes: Comprehensive test suite with unit tests, integration tests, PDF processing tests, search tests, and frontend tests. Includes pytest configuration and GitHub Actions CI/CD setup

- [x] Add backup/restore functionality
  - Date added: 2025-10-27
  - Date completed: 2026-03-09
  - Priority: medium
  - Notes: Complete system backup including database, PDFs, and thumbnails as compressed archive. Supports restore to new location or disaster recovery. Features: full backup/restore via ZIP archive, UI integration in settings modal, comprehensive i18n support for all languages, automatic cleanup of temporary files, safety backup before restore

- [x] Create initial project structure
  - Date added: 2025-10-27
  - Date completed: 2025-10-27

- [x] Implement FastAPI backend with PDF upload
  - Date added: 2025-10-27
  - Date completed: 2025-10-27

- [x] Create drag & drop web interface
  - Date added: 2025-10-27
  - Date completed: 2025-10-27

- [x] Add basic text extraction from PDFs
  - Date added: 2025-10-27
  - Date completed: 2025-10-27

- [x] Implement SQLite database for metadata
  - Date added: 2025-10-27
  - Date completed: 2025-10-27

- [x] Add rule-based categorization
  - Date added: 2025-10-27
  - Date completed: 2025-10-27

- [x] Setup Git repository
  - Date added: 2025-10-27
  - Date completed: 2025-10-27

- [x] Integrate Ollama for AI-powered document tagging and naming
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Implemented with llama3.2 model, graceful fallback to rule-based processing

- [x] Fix tag generation to use English and reuse existing tags
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Ensure tags are always generated in English and check existing tags before creating new ones to avoid duplicates

- [x] Implement search and filtering
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Search by filename, tags, category, content, date range

- [x] Add document editing capabilities (rename, retag, recategorize)
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Allow users to manually adjust AI suggestions

- [x] Support custom tagging
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Allow users to create and manage custom tags for document organization

- [x] Add document preview in browser
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Implemented using iframe with browser's native PDF viewer

- [x] Implement bulk upload and processing
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Handle multiple files with progress indicators

- [x] Add dark mode support
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Implemented CSS variables for theming, toggle button with localStorage persistence

- [x] Add OCR support for scanned PDFs
  - Date added: 2025-10-27
  - Date completed: 2025-10-27
  - Notes: Implemented pytesseract with fallback for PDFs with minimal text, supports English and German
