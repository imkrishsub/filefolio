# Code improvements made during test implementation

## Critical bug fixed

### Issue: Wrong database column indices

**Severity:** CRITICAL - API was returning incorrect data

**Problem:**
The `/documents` endpoint was using hardcoded row indices that didn't account for all columns in the schema:
- Used `row[5]` for tags (actually `file_hash`)
- Used `row[6]` for category (actually `tags`)
- All subsequent fields were off by 2

**Impact:**
- Categories and tags were swapped in API responses
- Frontend was likely displaying wrong information
- Data integrity issues in the application

**Fix applied:**
1. Added `conn.row_factory = sqlite3.Row` to enable named column access
2. Replaced all index-based access (`row[0]`) with named access (`row['id']`)
3. Added proper error handling for JSON parsing with empty string checks

**Benefits:**
- ✅ Code is now maintainable - column names are self-documenting
- ✅ Resistant to schema changes - won't break if columns are added/reordered
- ✅ Correct data returned - tags and categories now match the actual data
- ✅ Better error handling - malformed JSON won't crash the API

## Code changes

### backend/main.py

```python
# Before (fragile, incorrect):
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

documents.append({
    "id": row[0],
    "tags": json.loads(row[5]) if row[5] else [],  # WRONG: row[5] is file_hash!
    "category": row[6],  # WRONG: row[6] is tags!
})

# After (robust, correct):
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row  # Enable named access
    return conn

# Proper JSON parsing with error handling
tags = []
tags_field = row['tags'] if 'tags' in row.keys() else None
if tags_field and tags_field.strip():
    try:
        tags = json.loads(tags_field)
    except (json.JSONDecodeError, ValueError):
        tags = []

documents.append({
    "id": row['id'],
    "original_filename": row['original_filename'],
    "stored_filename": row['stored_filename'],
    "auto_filename": row['auto_filename'],
    "tags": tags,
    "category": row['category'],
    "upload_date": row['upload_date'],
    "preview": row['content_preview'][:200] if row['content_preview'] else "",
    "thumbnail": row['thumbnail_path']
})
```

## Testing verified the fix

The comprehensive test suite (39 passing tests) validates:
- ✅ Correct data structure returned from API
- ✅ Tags are properly parsed as JSON arrays
- ✅ Categories match uploaded documents
- ✅ All CRUD operations work correctly
- ✅ No regressions introduced

## Recommendations for future

1. **Consider using an ORM** (SQLAlchemy, Tortoise ORM) for better database abstractions
2. **Add database migrations** (Alembic) for schema versioning
3. **Add input validation** using Pydantic models for all endpoints
4. **Add logging** to track JSON parsing errors
5. **Consider storing tags as a proper JSON column type** in SQLite (JSON1 extension)

## Tested and verified

- ✅ All 39 tests pass
- ✅ Live application tested - API returns correct data
- ✅ Frontend still works (verified by loading homepage and checking API response)
- ✅ Tags display correctly as arrays
- ✅ Categories match document content
