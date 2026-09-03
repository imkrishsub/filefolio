"""
Pytest configuration and shared fixtures for FileFolio tests.
"""

import pytest
import sqlite3
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image
import io
from pypdf import PdfWriter


@pytest.fixture(scope="session")
def temp_test_dir():
    """Create a temporary directory for all tests."""
    temp_dir = Path(tempfile.mkdtemp(prefix="filefolio_test_"))
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def test_db(temp_test_dir, monkeypatch):
    """Create a temporary test database."""
    db_path = temp_test_dir / "test_documents.db"

    # Patch the database path in the main module
    import backend.main as main
    monkeypatch.setattr(main, "DB_PATH", db_path)
    monkeypatch.setattr(main, "UPLOAD_DIR", temp_test_dir / "uploads")
    monkeypatch.setattr(main, "THUMBNAILS_DIR", temp_test_dir / "thumbnails")

    # Create directories
    (temp_test_dir / "uploads").mkdir(exist_ok=True)
    (temp_test_dir / "thumbnails").mkdir(exist_ok=True)

    # Initialize database
    main.init_db()

    # Reinitialize sync service with test paths
    from backend.sync_service import SyncFolderService
    main.sync_service = SyncFolderService(
        db_path,
        temp_test_dir / "uploads",
        temp_test_dir / "thumbnails"
    )

    yield db_path

    # Cleanup
    if db_path.exists():
        db_path.unlink()
    for d in [temp_test_dir / "uploads", temp_test_dir / "thumbnails"]:
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(exist_ok=True)


@pytest.fixture
def client(test_db):
    """Create a test client for the FastAPI app."""
    from backend.main import app
    return TestClient(app)


@pytest.fixture
def sample_pdf_bytes():
    """Create a simple PDF file in memory for testing."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)

    pdf_bytes = io.BytesIO()
    writer.write(pdf_bytes)
    pdf_bytes.seek(0)

    return pdf_bytes.getvalue()


@pytest.fixture
def sample_pdf_file(temp_test_dir, sample_pdf_bytes):
    """Create a sample PDF file on disk."""
    pdf_path = temp_test_dir / "test_document.pdf"
    pdf_path.write_bytes(sample_pdf_bytes)
    yield pdf_path
    if pdf_path.exists():
        pdf_path.unlink()


@pytest.fixture
def multipage_pdf_bytes():
    """A 5-page PDF; each page a distinct size so pages can be told apart."""
    writer = PdfWriter()
    for i in range(5):
        writer.add_blank_page(width=200 + i, height=300)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture
def multipage_pdf_file(temp_test_dir, multipage_pdf_bytes):
    pdf_path = temp_test_dir / "multipage.pdf"
    pdf_path.write_bytes(multipage_pdf_bytes)
    yield pdf_path
    if pdf_path.exists():
        pdf_path.unlink()


@pytest.fixture
def sample_image():
    """Create a sample image for thumbnail testing."""
    img = Image.new('RGB', (200, 200), color='white')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes.getvalue()


@pytest.fixture
def mock_ollama_response(monkeypatch):
    """Mock Ollama responses to avoid requiring a running Ollama instance."""
    def mock_chat(*args, **kwargs):
        return {
            'message': {
                'content': '{"category": "Invoice", "tags": ["test", "sample"]}'
            }
        }

    import backend.main as main
    if hasattr(main, 'ollama'):
        monkeypatch.setattr(main.ollama, "chat", mock_chat)

    return mock_chat


@pytest.fixture
def db_connection(test_db):
    """Provide a database connection for direct database testing."""
    conn = sqlite3.connect(test_db)
    yield conn
    conn.close()
