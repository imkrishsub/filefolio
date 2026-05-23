# FTS5 query sanitization implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inline two-liner FTS5 query builder in `list_documents` with a phrase-aware sanitizer that strips column filters, grouping operators, and uppercase boolean keywords.

**Architecture:** A new `_sanitize_fts_query(raw: str) -> str` helper splits input on double-quoted phrase tokens, sanitizes bare-word segments, and reassembles a safe FTS5 MATCH expression. The `list_documents` route calls the helper and falls back to the non-FTS query path if sanitization yields an empty string.

**Tech stack:** Python stdlib `re`, SQLite FTS5, pytest, FastAPI TestClient.

---

## File map

- Modify: `backend/main.py` — add `_sanitize_fts_query` before line 740; replace inline lines 770–774 with a call to it; add empty-string fallback.
- Modify: `tests/test_api.py` — add `TestSanitizeFtsQuery` class (unit tests) and extend `TestDocumentsEndpoint` with integration tests.

---

### Task 1: Write failing unit tests for `_sanitize_fts_query`

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add the test class to `tests/test_api.py`**

  Append this class at the end of `tests/test_api.py`, after the last existing class:

  ```python
  class TestSanitizeFtsQuery:
      """Unit tests for the _sanitize_fts_query helper."""

      def _fn(self):
          from backend.main import _sanitize_fts_query
          return _sanitize_fts_query

      def test_bare_word_gets_wildcard(self):
          fn = self._fn()
          assert fn("invoice") == "invoice*"

      def test_column_filter_colon_stripped(self):
          fn = self._fn()
          assert fn("original_filename:secret") == "original_filename secret*"

      def test_parens_stripped(self):
          fn = self._fn()
          assert fn("(invoice OR receipt)") == "invoice or receipt*"

      def test_uppercase_and_lowercased(self):
          fn = self._fn()
          assert fn("tax AND return") == "tax and return*"

      def test_uppercase_or_lowercased(self):
          fn = self._fn()
          assert fn("invoice OR receipt") == "invoice or receipt*"

      def test_uppercase_not_lowercased(self):
          fn = self._fn()
          assert fn("invoice NOT draft") == "invoice not draft*"

      def test_phrase_preserved(self):
          fn = self._fn()
          assert fn('"tax return"') == '"tax return"'

      def test_phrase_plus_bare_word(self):
          fn = self._fn()
          assert fn('"tax return" 2024') == '"tax return" 2024*'

      def test_all_operators_returns_empty(self):
          fn = self._fn()
          assert fn(":::") == ""

      def test_empty_string_returns_empty(self):
          fn = self._fn()
          assert fn("") == ""

      def test_whitespace_only_returns_empty(self):
          fn = self._fn()
          assert fn("   ") == ""
  ```

- [ ] **Step 2: Run the tests to confirm they fail**

  ```
  pytest tests/test_api.py::TestSanitizeFtsQuery -v
  ```

  Expected: all tests fail with `ImportError: cannot import name '_sanitize_fts_query'`.

---

### Task 2: Implement `_sanitize_fts_query` and pass unit tests

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add `_sanitize_fts_query` to `backend/main.py`**

  Insert the following function immediately before the `@app.get("/documents")` decorator (currently at line 740). The `re` module is already imported.

  ```python
  def _sanitize_fts_query(raw: str) -> str:
      if not raw or not raw.strip():
          return ""

      # Split on "..." quoted phrase tokens (capturing group keeps them in the list)
      parts = re.split(r'("(?:[^"]|"")*")', raw)

      sanitized = []
      last_is_bare = False

      for part in parts:
          if part.startswith('"') and part.endswith('"') and len(part) >= 2:
              sanitized.append(part)
              last_is_bare = False
          else:
              segment = part.replace(':', ' ').replace('(', ' ').replace(')', ' ')
              segment = re.sub(r'\b(AND|OR|NOT)\b', lambda m: m.group().lower(), segment)
              segment = ' '.join(segment.split())
              if segment:
                  sanitized.append(segment)
                  last_is_bare = True

      if not sanitized:
          return ""

      result = ' '.join(sanitized)
      if last_is_bare:
          result += '*'
      return result
  ```

- [ ] **Step 2: Run the unit tests to confirm they pass**

  ```
  pytest tests/test_api.py::TestSanitizeFtsQuery -v
  ```

  Expected: all 11 tests PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add backend/main.py tests/test_api.py
  git commit -m "feat(search): add _sanitize_fts_query helper with unit tests

  Strips FTS5 column filter syntax (:), grouping operators (()),
  and uppercase boolean keywords (AND/OR/NOT) from bare-word segments
  while preserving double-quoted phrase tokens.

  Co-authored-by: Claude <claude@anthropic.com>"
  ```

---

### Task 3: Write failing integration tests for the search endpoint

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add integration tests to `TestDocumentsEndpoint`**

  Add these test methods inside the existing `TestDocumentsEndpoint` class, after `test_search_documents`:

  ```python
  def test_search_column_filter_returns_200(self, client):
      response = client.get("/documents?search=original_filename%3Asecret")
      assert response.status_code == 200
      assert isinstance(response.json(), list)

  def test_search_parens_returns_200(self, client):
      response = client.get("/documents?search=%28invoice+OR+receipt%29")
      assert response.status_code == 200
      assert isinstance(response.json(), list)

  def test_search_boolean_keyword_returns_200(self, client):
      response = client.get("/documents?search=invoice+NOT+draft")
      assert response.status_code == 200
      assert isinstance(response.json(), list)

  def test_search_phrase_returns_200(self, client):
      response = client.get('/documents?search=%22tax+return%22')
      assert response.status_code == 200
      assert isinstance(response.json(), list)

  def test_search_mixed_phrase_and_bare_returns_200(self, client):
      response = client.get('/documents?search=%22tax+return%22+2024')
      assert response.status_code == 200
      assert isinstance(response.json(), list)

  def test_search_all_operators_falls_back_to_all_docs(self, client, sample_pdf_bytes, mock_ollama_response):
      files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
      client.post("/upload", files=files)
      response = client.get("/documents?search=:::")
      assert response.status_code == 200
      docs = response.json()
      assert isinstance(docs, list)
      assert len(docs) >= 1
  ```

- [ ] **Step 2: Run the integration tests to confirm current state**

  ```
  pytest tests/test_api.py::TestDocumentsEndpoint -v
  ```

  The five no-upload tests should pass (the endpoint likely returns 200 already for most inputs). The `test_search_all_operators_falls_back_to_all_docs` may fail because today an all-operator query would produce `:::*` which SQLite FTS5 may reject (500) or return empty results (causing the `len >= 1` assertion to fail). This confirms the fallback behaviour is not yet wired in.

---

### Task 4: Wire `_sanitize_fts_query` into `list_documents`

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Replace the inline FTS query builder in `list_documents`**

  In `backend/main.py`, find this block inside `list_documents` (around lines 767–774):

  ```python
      # Use FTS5 for search if search term provided
      if search:
          # Escape FTS5 special characters and prepare fuzzy query
          fts_query = search.replace('"', '""')

          # Add wildcard suffix for prefix matching (fuzzy search)
          # This allows "payro" to match "payroll"
          fts_query = fts_query + "*"

          # Build the query using FTS5
          query = """
              SELECT d.* FROM documents d
              INNER JOIN documents_fts fts ON d.id = fts.rowid
              WHERE documents_fts MATCH ?
          """
          params = [fts_query]
  ```

  Replace it with:

  ```python
      fts_query = _sanitize_fts_query(search) if search else ""

      # Use FTS5 for search if search term provided
      if fts_query:
          query = """
              SELECT d.* FROM documents d
              INNER JOIN documents_fts fts ON d.id = fts.rowid
              WHERE documents_fts MATCH ?
          """
          params = [fts_query]
  ```

  The block of code that follows — appending `AND d.category = ?`, `AND d.tags LIKE ?`, `AND d.upload_date >= ?`, `AND d.upload_date <= ?`, and `ORDER BY rank` — is still gated on what was previously `if search:`. That outer condition has now been removed (replaced by the `if fts_query:` block above), so these appends are now inside `if fts_query:` by virtue of being in the same block. No further changes needed. The `else:` branch beginning with `query = "SELECT * FROM documents WHERE 1=1"` stays unchanged.

- [ ] **Step 2: Run the full integration test suite**

  ```
  pytest tests/test_api.py -v
  ```

  Expected: all tests PASS, including `test_search_all_operators_falls_back_to_all_docs`.

- [ ] **Step 3: Run the full test suite to check for regressions**

  ```
  pytest -v
  ```

  Expected: all existing tests continue to PASS.

- [ ] **Step 4: Commit**

  ```bash
  git add backend/main.py tests/test_api.py
  git commit -m "feat(search): wire _sanitize_fts_query into list_documents

  Replaces the bare double-quote escape + wildcard append with a call
  to _sanitize_fts_query. Empty sanitized queries fall back to the
  non-FTS code path, returning all documents.

  Co-authored-by: Claude <claude@anthropic.com>"
  ```
