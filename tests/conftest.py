"""
Pytest configuration and shared fixtures for FileFolio tests.
"""

import pytest
import sqlite3
import io
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Create an isolated database and upload/thumbnail directories per test."""
    db_path = tmp_path / "documents.db"
    upload_dir = tmp_path / "uploads"
    thumbnails_dir = tmp_path / "thumbnails"

    upload_dir.mkdir(exist_ok=True)
    thumbnails_dir.mkdir(exist_ok=True)

    import backend.main as main
    monkeypatch.setattr(main, "DB_PATH", db_path)
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main, "THUMBNAILS_DIR", thumbnails_dir)

    main.init_db()

    from backend.sync_service import SyncFolderService
    main.sync_service = SyncFolderService(db_path, upload_dir, thumbnails_dir)

    yield db_path
    # tmp_path is cleaned up automatically by pytest after the test


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
def sample_pdf_file(tmp_path, sample_pdf_bytes):
    """Create a sample PDF file on disk."""
    pdf_path = tmp_path / "test_document.pdf"
    pdf_path.write_bytes(sample_pdf_bytes)
    return pdf_path  # tmp_path cleanup handles removal


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
