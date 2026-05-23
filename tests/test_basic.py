"""
Basic tests for FileFolio to verify core functionality.
These tests match the actual API implementation.
"""

import pytest
import io


class TestBasicAPI:
    """Basic API endpoint tests."""

    def test_root_endpoint(self, client):
        """Test that the root endpoint returns HTML."""
        response = client.get("/")
        assert response.status_code == 200

    def test_upload_pdf(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test uploading a PDF file."""
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        response = client.post("/upload", files=files)

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["original_filename"] == "test.pdf"

    def test_upload_non_pdf_rejected(self, client):
        """Test that non-PDF files are rejected."""
        files = {"file": ("test.txt", io.BytesIO(b"test content"), "text/plain")}
        response = client.post("/upload", files=files)

        assert response.status_code == 400

    def test_list_documents(self, client):
        """Test listing documents."""
        response = client.get("/documents")
        assert response.status_code == 200

    def test_get_filters(self, client):
        """Test getting filter options."""
        response = client.get("/filters")
        assert response.status_code == 200


class TestDocumentOperations:
    """Test document CRUD operations."""

    def test_upload_and_retrieve(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test uploading and then retrieving a document."""
        # Upload
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        upload_response = client.post("/upload", files=files)
        assert upload_response.status_code == 200
        doc_id = upload_response.json()["id"]

        # Retrieve
        get_response = client.get(f"/document/{doc_id}")
        assert get_response.status_code == 200

    def test_update_document(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test updating document metadata."""
        # Upload
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        upload_response = client.post("/upload", files=files)
        doc_id = upload_response.json()["id"]

        # Update
        update_data = {
            "filename": "updated.pdf",
            "category": "Invoice",
            "tags": ["test", "updated"]
        }
        update_response = client.put(f"/document/{doc_id}", json=update_data)
        assert update_response.status_code == 200

    def test_delete_document(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test deleting a document."""
        # Upload
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        upload_response = client.post("/upload", files=files)
        doc_id = upload_response.json()["id"]

        # Delete
        delete_response = client.delete(f"/document/{doc_id}")
        assert delete_response.status_code == 200

        # Verify deletion
        get_response = client.get(f"/document/{doc_id}")
        assert get_response.status_code == 404


class TestDuplicateDetection:
    """Test duplicate file detection."""

    def test_duplicate_upload_rejected(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test that duplicate files are detected and rejected."""
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}

        # First upload should succeed
        response1 = client.post("/upload", files=files)
        assert response1.status_code == 200

        # Second upload of same file should fail
        files2 = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        response2 = client.post("/upload", files=files2)
        assert response2.status_code == 409  # Conflict


class TestDownloadSingle:
    """Test GET /download/{doc_id}."""

    def test_download_single_returns_pdf(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test that a valid document can be downloaded."""
        files = {"file": ("report.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        doc_id = client.post("/upload", files=files).json()["id"]

        response = client.get(f"/download/{doc_id}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    def test_download_single_content_disposition_quoted(self, client, sample_pdf_bytes, mock_ollama_response):
        """Content-Disposition filename must be percent-encoded (RFC 6266)."""
        files = {"file": ("report.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        doc_id = client.post("/upload", files=files).json()["id"]

        response = client.get(f"/download/{doc_id}")
        disposition = response.headers.get("content-disposition", "")
        # Value must use filename*= (RFC 5987) — not a bare unquoted filename=
        assert "filename*=UTF-8''" in disposition

    def test_download_single_injection_filename_is_safe(
        self, client, db_connection, temp_test_dir, sample_pdf_bytes
    ):
        """A filename with header metacharacters must be percent-encoded, not passed raw."""
        # Seed the DB directly to avoid multipart MIME pre-encoding the filename
        injection_name = 'invoice"; type=text/html.pdf'
        pdf_path = temp_test_dir / "uploads" / "injection_test.pdf"
        pdf_path.write_bytes(sample_pdf_bytes)

        cursor = db_connection.cursor()
        cursor.execute(
            """INSERT INTO documents
               (original_filename, stored_filename, file_path, upload_date)
               VALUES (?, ?, ?, ?)""",
            (injection_name, "injection_test.pdf", str(pdf_path), "2026-05-23"),
        )
        db_connection.commit()
        doc_id = cursor.lastrowid

        response = client.get(f"/download/{doc_id}")
        assert response.status_code == 200
        disposition = response.headers.get("content-disposition", "")
        # Raw double-quote and semicolon must not appear unencoded in the header
        assert '"; type=text/html' not in disposition
        # Both characters should be percent-encoded
        assert "%22" in disposition
        assert "%3B" in disposition or "%3b" in disposition

    def test_download_single_not_found(self, client):
        """Non-existent document should return 404."""
        response = client.get("/download/999999")
        assert response.status_code == 404


class TestBulkOperations:
    """Test bulk document operations."""

    def test_download_multiple(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test downloading multiple documents as zip."""
        # Upload two documents
        doc_ids = []
        for i in range(2):
            files = {"file": (f"test{i}.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
            response = client.post("/upload", files=files)
            if response.status_code == 200:
                doc_ids.append(response.json()["id"])

        # Download as zip
        if doc_ids:
            download_response = client.post("/download/multiple", json={"document_ids": doc_ids})
            assert download_response.status_code == 200
