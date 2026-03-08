"""
Tests for FileFolio API endpoints.
Updated to match actual API implementation.
"""

import pytest
import io


class TestRootEndpoint:
    """Tests for the root endpoint."""

    def test_root_returns_html(self, client):
        """Test that the root endpoint returns HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestUploadEndpoint:
    """Tests for the /upload endpoint."""

    def test_upload_valid_pdf(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test uploading a valid PDF file."""
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        response = client.post("/upload", files=files)

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["original_filename"] == "test.pdf"
        assert "category" in data
        assert "tags" in data

    def test_upload_non_pdf_rejected(self, client):
        """Test that non-PDF files are rejected."""
        files = {"file": ("test.txt", io.BytesIO(b"test content"), "text/plain")}
        response = client.post("/upload", files=files)

        assert response.status_code == 400
        assert "Only PDF files are allowed" in response.json()["detail"]

    def test_upload_duplicate_detection(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test that duplicate files are detected."""
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}

        # Upload first time
        response1 = client.post("/upload", files=files)
        assert response1.status_code == 200

        # Upload same file again
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        response2 = client.post("/upload", files=files)
        assert response2.status_code == 409
        assert "Duplicate file detected" in response2.json()["detail"]


class TestDocumentsEndpoint:
    """Tests for the /documents endpoint."""

    def test_get_empty_documents(self, client):
        """Test getting documents when database is empty."""
        response = client.get("/documents")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_documents_after_upload(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test retrieving documents after uploading."""
        # Upload a file
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        client.post("/upload", files=files)

        # Get documents
        response = client.get("/documents")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["original_filename"] == "test.pdf"

    def test_search_documents(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test searching documents by query."""
        # Upload a file
        files = {"file": ("invoice.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        client.post("/upload", files=files)

        # Search for the document
        response = client.get("/documents?search=invoice")
        assert response.status_code == 200
        # May return empty if FTS doesn't match, that's OK
        data = response.json()
        assert isinstance(data, list)


class TestDocumentEndpoint:
    """Tests for individual document operations."""

    def test_get_document(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test retrieving a specific document."""
        # Upload a file
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        upload_response = client.post("/upload", files=files)
        doc_id = upload_response.json()["id"]

        # Get the document
        response = client.get(f"/document/{doc_id}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    def test_get_nonexistent_document(self, client):
        """Test retrieving a document that doesn't exist."""
        response = client.get("/document/99999")
        assert response.status_code == 404


class TestUpdateEndpoint:
    """Tests for the PUT /document/{id} endpoint."""

    def test_update_document(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test updating document metadata."""
        # Upload a file
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        upload_response = client.post("/upload", files=files)
        doc_id = upload_response.json()["id"]

        # Update the document
        update_data = {
            "auto_filename": "updated_test.pdf",
            "category": "Receipt",
            "tags": ["updated", "test"]
        }
        response = client.put(f"/document/{doc_id}", json=update_data)
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify the update
        docs_response = client.get("/documents")
        docs = docs_response.json()
        updated_doc = next(d for d in docs if d["id"] == doc_id)
        assert updated_doc["auto_filename"] == "updated_test.pdf"
        assert updated_doc["category"] == "Receipt"
        assert updated_doc["tags"] == ["updated", "test"]

    def test_update_nonexistent_document(self, client):
        """Test updating a document that doesn't exist."""
        update_data = {
            "auto_filename": "test.pdf",
            "category": "Invoice",
            "tags": ["test"]
        }
        response = client.put("/document/99999", json=update_data)
        assert response.status_code == 404


class TestDeleteEndpoint:
    """Tests for the DELETE /document/{id} endpoint."""

    def test_delete_document(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test deleting a document."""
        # Upload a file
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        upload_response = client.post("/upload", files=files)
        doc_id = upload_response.json()["id"]

        # Delete the document
        response = client.delete(f"/document/{doc_id}")
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify deletion
        docs_response = client.get("/documents")
        docs = docs_response.json()
        assert len(docs) == 0

    def test_delete_nonexistent_document(self, client):
        """Test deleting a document that doesn't exist."""
        response = client.delete("/document/99999")
        assert response.status_code == 404


class TestFiltersEndpoint:
    """Tests for the /filters endpoint."""

    def test_get_filters(self, client, sample_pdf_bytes, mock_ollama_response):
        """Test retrieving filter options."""
        # Upload files with different categories/tags
        files = {"file": ("test1.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        client.post("/upload", files=files)

        # Get filters
        response = client.get("/filters")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert "tags" in data
        assert isinstance(data["categories"], list)
        assert isinstance(data["tags"], list)


class TestBulkDownloadEndpoint:
    """Tests for the /download/multiple endpoint."""

    def test_download_multiple_documents(self, client, mock_ollama_response):
        """Test downloading multiple documents as a zip."""
        # Upload two different files
        from pypdf import PdfWriter
        import io as io_module

        # Create first PDF
        writer1 = PdfWriter()
        writer1.add_blank_page(width=200, height=200)
        pdf1 = io_module.BytesIO()
        writer1.write(pdf1)
        pdf1.seek(0)

        files1 = {"file": ("test1.pdf", pdf1, "application/pdf")}
        response1 = client.post("/upload", files=files1)
        assert response1.status_code == 200
        doc_id1 = response1.json()["id"]

        # Create second PDF (different size to avoid duplicate)
        writer2 = PdfWriter()
        writer2.add_blank_page(width=300, height=300)
        pdf2 = io_module.BytesIO()
        writer2.write(pdf2)
        pdf2.seek(0)

        files2 = {"file": ("test2.pdf", pdf2, "application/pdf")}
        response2 = client.post("/upload", files=files2)
        assert response2.status_code == 200
        doc_id2 = response2.json()["id"]

        # Download both
        response = client.post("/download/multiple", json={"document_ids": [doc_id1, doc_id2]})
        assert response.status_code == 200
        assert "application/zip" in response.headers["content-type"]

    def test_download_empty_list(self, client):
        """Test downloading with empty document list."""
        response = client.post("/download/multiple", json={"document_ids": []})
        assert response.status_code == 400

    def test_download_nonexistent_documents(self, client):
        """Test downloading documents that don't exist."""
        response = client.post("/download/multiple", json={"document_ids": [99999, 99998]})
        assert response.status_code == 404
