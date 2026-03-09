# TODO

## Active

### Documentation
- [x] Show Ko-fi link in README.md in a prominent manner
  - Date added: 2026-03-07
  - Date completed: 2026-03-08
  - Priority: high
  - Notes: Added Ko-fi donation button to both README.md and web interface header

### Core functionality (MVP)
- [ ] Create organized folder structure for stored PDFs
  - Date added: 2025-10-27
  - Priority: medium
  - Notes: Group by category/year instead of flat uploads folder

### Enhancements

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

- [ ] Add custom tagging rules/templates
  - Date added: 2025-10-27
  - Priority: medium
  - Notes: Let users define patterns for automatic categorization

- [ ] Export functionality (CSV, JSON)
  - Date added: 2025-10-27
  - Priority: low
  - Notes: Export document metadata and organization

- [ ] Add statistics dashboard
  - Date added: 2025-10-27
  - Priority: low
  - Notes: Show document counts by category, upload trends, storage usage

- [ ] Support CLI usage for typical tasks
  - Date added: 2026-03-07
  - Priority: low
  - Notes: Command-line interface for common operations (upload, search, tag, etc.)

- [ ] Add visual filters for document previews
  - Date added: 2026-03-08
  - Priority: medium
  - Notes: Add options to apply visual filters (brightness, contrast, grayscale, sepia) to improve readability of scanned or low-quality documents in the preview modal

### Polish & Production
- [ ] Add error handling and validation improvements
  - Date added: 2025-10-27
  - Priority: medium
  - Notes: Better feedback for failed uploads, file size limits, corrupted PDFs

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

- [ ] Add backup/restore functionality
  - Date added: 2025-10-27
  - Priority: low
  - Notes: Export entire database and files for backup

## Blocked

## Done
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
