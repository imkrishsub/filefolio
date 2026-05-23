# FTS5 search query sanitization

**Date:** 2026-05-23
**Status:** Approved

## Problem

The current search handler in `backend/main.py` escapes double quotes in the user input but passes everything else directly to the SQLite FTS5 `MATCH` clause. This allows:

- Column filter injection: `original_filename:secret` targets a specific FTS5 column.
- Boolean operator injection: `OR NOT invoice` manipulates query logic.
- Grouping injection: `(hidden OR visible)` uses FTS5 grouping syntax.

## Goals

- Neutralise `:`, `(`, `)`, and uppercase `AND`/`OR`/`NOT` in user input.
- Preserve double-quoted phrase search (e.g. `"tax return"`).
- Fall back gracefully when sanitization produces an empty query.
- Add tests covering each sanitization rule.

## Out of scope

- Supporting user-controlled boolean operators.
- Supporting column-scoped search from the UI.

## Design

### Sanitization helper

A new function `_sanitize_fts_query(raw: str) -> str` in `backend/main.py` replaces the current inline two-liner at line 770.

**Algorithm:**

1. Split the input on `"..."` quoted substrings using a regex. This produces alternating unquoted segments and quoted phrase tokens.
2. For unquoted segments:
   - Remove `:`, `(`, `)`.
   - Replace standalone `AND`, `OR`, `NOT` (case-insensitive, whole-word match) with their lowercase equivalents — FTS5 only treats the uppercase forms as boolean operators.
   - Normalize whitespace.
3. For quoted substrings: double any internal `"` characters (existing FTS5 escaping rule). Pass through otherwise.
4. Reassemble all parts. If the result is empty or blank, return empty string.
5. Append `*` to the last bare token for prefix matching. Do not append `*` immediately after a closing `"` (invalid FTS5 syntax).

**Call site:** `get_documents` replaces the two-line inline block with:
```python
fts_query = _sanitize_fts_query(search)
if not fts_query:
    search = None  # fall through to non-FTS query path
```

### Error handling

If sanitization yields an empty string, the endpoint falls back to the unfiltered document list (same as omitting the `search` param). No HTTP error is returned.

The `MATCH` clause already uses a parameterised `?` placeholder, so there is no SQL injection risk — sanitization is solely about preventing malformed FTS5 syntax from raising `sqlite3.OperationalError`.

## Tests

New unit tests for `_sanitize_fts_query` directly:

| Input | Expected output |
|---|---|
| `original_filename:secret` | `original_filename secret*` |
| `(invoice OR receipt)` | `invoice or receipt*` |
| `invoice NOT draft` | `invoice not draft*` |
| `"tax return"` | `"tax return"` |
| `"tax return" 2024` | `"tax return" 2024*` |
| `:::` | `` (empty → fallback) |

New integration tests in `tests/test_api.py`:

- `test_search_strips_column_filter` — does not crash, returns 200.
- `test_search_strips_parens` — does not crash, returns 200.
- `test_search_boolean_keywords_treated_as_words` — does not crash, returns 200.
- `test_search_preserves_phrase_query` — phrase search still works.
- `test_search_mixed_phrase_and_bare` — phrase + bare word works.
- `test_search_empty_after_sanitization` — all-operator input falls back gracefully, returns 200.
