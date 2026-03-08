# FileFolio test suite

Comprehensive test suite for the FileFolio document organization system.

## Overview

This test suite covers:
- **API endpoints** - All FastAPI routes and responses
- **Integration tests** - Complete workflows from upload to retrieval
- **PDF processing** - Text extraction, OCR, and metadata handling
- **Search functionality** - Full-text search and filtering
- **Frontend logic** - JavaScript functionality tests

## Setup

### Install dependencies

```bash
pip install -r requirements.txt
```

This will install both the application dependencies and testing frameworks:
- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `pytest-cov` - Code coverage reporting
- `httpx` - HTTP client for testing FastAPI

### Prerequisites

For full test coverage, ensure you have:
- Python 3.8+
- Poppler (for PDF processing)
- Tesseract OCR (optional, for OCR tests)

## Running tests

### Run all tests

```bash
pytest
```

### Run specific test file

```bash
pytest tests/test_api.py
pytest tests/test_integration.py
pytest tests/test_pdf_processing.py
pytest tests/test_search.py
```

### Run specific test class or function

```bash
pytest tests/test_api.py::TestUploadEndpoint
pytest tests/test_api.py::TestUploadEndpoint::test_upload_valid_pdf
```

### Run with coverage report

```bash
pytest --cov=backend --cov-report=html
```

This generates an HTML coverage report in `htmlcov/index.html`.

### Run with verbose output

```bash
pytest -v
```

### Run in parallel (faster)

```bash
pip install pytest-xdist
pytest -n auto
```

## Test structure

```
tests/
├── __init__.py              # Test package initialization
├── conftest.py              # Shared fixtures and configuration
├── test_api.py              # API endpoint tests
├── test_integration.py      # End-to-end workflow tests
├── test_pdf_processing.py   # PDF and OCR functionality tests
├── test_search.py           # Search and filtering tests
├── test_frontend.js         # Frontend JavaScript tests
└── README.md                # This file
```

## Test fixtures

The test suite uses pytest fixtures defined in `conftest.py`:

- `temp_test_dir` - Temporary directory for test files
- `test_db` - Isolated test database
- `client` - FastAPI test client
- `sample_pdf_bytes` - Sample PDF file in memory
- `sample_pdf_file` - Sample PDF file on disk
- `mock_ollama_response` - Mocked AI responses (no Ollama required)
- `db_connection` - Direct database connection for testing

## Test coverage

### API endpoints (`test_api.py`)

- ✅ Root endpoint (HTML serving)
- ✅ Upload endpoint (file validation, duplicate detection)
- ✅ Documents listing (empty state, search)
- ✅ Individual document retrieval
- ✅ Document updates (metadata editing)
- ✅ Document deletion
- ✅ Tags aggregation
- ✅ Bulk download (zip generation)

### Integration tests (`test_integration.py`)

- ✅ Complete upload workflow (upload → store → retrieve → update → delete)
- ✅ Bulk upload and download
- ✅ Duplicate detection workflow
- ✅ Search workflows (by filename, category, tags)
- ✅ Tag aggregation
- ✅ Error handling (missing files, corrupted database)

### PDF processing (`test_pdf_processing.py`)

- ✅ Text extraction from PDFs
- ✅ Empty and multipage PDF handling
- ✅ Thumbnail generation
- ✅ File hashing (SHA-256)
- ✅ Duplicate detection via hash
- ✅ OCR functionality (requires tesseract)
- ✅ Filename sanitization
- ✅ Database FTS integration
- ✅ FTS triggers

### Search tests (`test_search.py`)

- ✅ Full-text search (filename, content, tags, category)
- ✅ Empty search (returns all)
- ✅ No results handling
- ✅ Case-insensitive search
- ✅ Tag filtering and uniqueness
- ✅ Document sorting
- ✅ Large result sets

### Frontend tests (`test_frontend.js`)

- ✅ File validation (PDF only)
- ✅ Search debouncing
- ✅ Dark mode toggle
- ✅ Tag parsing
- ✅ Progress bar updates
- ✅ Document sorting
- ✅ View mode switching
- ✅ Selection state management
- ✅ Filename escaping (XSS prevention)
- ✅ Date formatting

## Continuous Integration

### GitHub Actions

Create `.github/workflows/test.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'

    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y poppler-utils tesseract-ocr

    - name: Install Python dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name: Run tests
      run: |
        pytest --cov=backend --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

## Writing new tests

### Example: Testing a new API endpoint

```python
# tests/test_api.py

class TestNewEndpoint:
    """Tests for the /new-endpoint."""

    def test_new_endpoint_success(self, client):
        """Test successful request."""
        response = client.get("/new-endpoint")
        assert response.status_code == 200
        assert "expected_field" in response.json()

    def test_new_endpoint_validation(self, client):
        """Test input validation."""
        response = client.post("/new-endpoint", json={"invalid": "data"})
        assert response.status_code == 400
```

### Example: Testing database operations

```python
# tests/test_integration.py

def test_database_operation(db_connection):
    """Test direct database operation."""
    cursor = db_connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM documents")
    count = cursor.fetchone()[0]
    assert count >= 0
```

## Skipping tests

Some tests may require optional dependencies:

```python
@pytest.mark.skip(reason="Requires tesseract OCR")
def test_ocr_functionality():
    """Test OCR text extraction."""
    pass
```

Run only non-skipped tests:
```bash
pytest -v
```

## Debugging tests

### Run with print statements

```bash
pytest -s
```

### Drop into debugger on failure

```bash
pytest --pdb
```

### Run last failed tests only

```bash
pytest --lf
```

## Best practices

1. **Isolation** - Each test should be independent
2. **Fixtures** - Use fixtures for common setup
3. **Cleanup** - Tests clean up after themselves (temp files, database)
4. **Descriptive names** - Test names describe what they test
5. **Assertions** - Clear assertion messages
6. **Fast tests** - Use mocks to avoid slow operations (Ollama, OCR)
7. **Coverage** - Aim for >80% code coverage

## Troubleshooting

### Tests fail with "Database locked"

Increase timeout in `conftest.py`:
```python
conn = sqlite3.connect(test_db, timeout=30.0)
```

### OCR tests fail

Install tesseract:
```bash
# macOS
brew install tesseract

# Ubuntu
apt-get install tesseract-ocr

# Windows
# Download from https://github.com/UB-Mannheim/tesseract/wiki
```

### Import errors

Ensure you're running from project root:
```bash
cd /path/to/filefolio
pytest
```

## Contributing

When adding new features:
1. Write tests first (TDD)
2. Ensure all tests pass
3. Add new test cases for edge cases
4. Update this README if needed

## License

Same as FileFolio - MIT License
