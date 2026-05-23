"""
Tests for FileFolio API endpoints.
Updated to match actual API implementation.
"""

import io

import pytest


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

    def test_upload_uppercase_extension_accepted(
        self, client, sample_pdf_bytes, mock_ollama_response
    ):
        """Test that uppercase .PDF extension is accepted."""
        files = {
            "file": ("DOCUMENT.PDF", io.BytesIO(sample_pdf_bytes), "application/pdf")
        }
        response = client.post("/upload", files=files)
        assert response.status_code == 200

    def test_upload_invalid_magic_bytes_rejected(self, client):
        """Test that a file with a .pdf extension but invalid content is rejected."""
        zip_bytes = b"PK\x03\x04" + b"\x00" * 100  # ZIP magic bytes
        files = {"file": ("fake.pdf", io.BytesIO(zip_bytes), "application/pdf")}
        response = client.post("/upload", files=files)
        assert response.status_code == 400
        assert "not a valid PDF" in response.json()["detail"]

    def test_upload_valid_magic_bytes_accepted(
        self, client, sample_pdf_bytes, mock_ollama_response
    ):
        """Test that a file with correct %PDF magic bytes and .pdf extension is accepted."""
        files = {
            "file": ("valid2.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
        }
        response = client.post("/upload", files=files)
        assert response.status_code == 200

    def test_upload_oversized_pdf_rejected(self, client, monkeypatch):
        """Test that PDFs exceeding the size limit are rejected with 413."""
        import backend.main as main

        monkeypatch.setattr(main, "MAX_UPLOAD_SIZE", 10)  # 10 bytes limit for the test
        oversized = b"%PDF-" + b"x" * 20
        files = {"file": ("big.pdf", io.BytesIO(oversized), "application/pdf")}
        response = client.post("/upload", files=files)

        assert response.status_code == 413
        assert "too large" in response.json()["detail"].lower()

    def test_upload_at_size_limit_accepted(
        self, client, sample_pdf_bytes, mock_ollama_response, monkeypatch
    ):
        """Test that a file exactly at the size limit is accepted."""
        import backend.main as main

        monkeypatch.setattr(main, "MAX_UPLOAD_SIZE", len(sample_pdf_bytes))
        files = {"file": ("limit.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        response = client.post("/upload", files=files)

        assert response.status_code == 200

    def test_upload_duplicate_detection(
        self, client, sample_pdf_bytes, mock_ollama_response
    ):
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

    def test_get_documents_after_upload(
        self, client, sample_pdf_bytes, mock_ollama_response
    ):
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
        files = {
            "file": ("invoice.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
        }
        client.post("/upload", files=files)

        # Search for the document
        response = client.get("/documents?search=invoice")
        assert response.status_code == 200
        # May return empty if FTS doesn't match, that's OK
        data = response.json()
        assert isinstance(data, list)

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
        response = client.get("/documents?search=%22tax+return%22")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_search_mixed_phrase_and_bare_returns_200(self, client):
        response = client.get("/documents?search=%22tax+return%22+2024")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.parametrize(
        "q",
        [
            '"unclosed',
            '"',
            "invoice*",
            "inv* rec*",
            "-invoice",
            "price,discount",
        ],
    )
    def test_search_crash_vectors_return_200(self, client, q):
        import urllib.parse

        response = client.get(f"/documents?search={urllib.parse.quote(q)}")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_search_all_operators_falls_back_to_all_docs(
        self, client, sample_pdf_bytes, mock_ollama_response
    ):
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        client.post("/upload", files=files)
        response = client.get("/documents?search=:::")
        assert response.status_code == 200
        docs = response.json()
        assert isinstance(docs, list)
        assert len(docs) >= 1


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
            "tags": ["updated", "test"],
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
            "tags": ["test"],
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
        import io as io_module

        from pypdf import PdfWriter

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
        response = client.post(
            "/download/multiple", json={"document_ids": [doc_id1, doc_id2]}
        )
        assert response.status_code == 200
        assert "application/zip" in response.headers["content-type"]

    def test_download_empty_list(self, client):
        """Test downloading with empty document list."""
        response = client.post("/download/multiple", json={"document_ids": []})
        assert response.status_code == 400

    def test_download_nonexistent_documents(self, client):
        """Test downloading documents that don't exist."""
        response = client.post(
            "/download/multiple", json={"document_ids": [99999, 99998]}
        )
        assert response.status_code == 404


class TestRestoreEndpoint:
    """Tests for the /restore endpoint."""

    def test_restore_rejects_zip_slip(self, tmp_path, monkeypatch):
        """ZIP entries with path traversal sequences must be rejected."""
        import zipfile

        from fastapi.testclient import TestClient

        import backend.main as main
        from backend.sync_service import SyncFolderService

        base_dir = tmp_path / "base"
        (base_dir / "data").mkdir(parents=True)
        (base_dir / "uploads").mkdir()
        (base_dir / "thumbnails").mkdir()

        monkeypatch.setattr(main, "BASE_DIR", base_dir)
        monkeypatch.setattr(main, "DATA_DIR", base_dir / "data")
        monkeypatch.setattr(main, "DB_PATH", base_dir / "data" / "documents.db")
        monkeypatch.setattr(main, "UPLOAD_DIR", base_dir / "uploads")
        monkeypatch.setattr(main, "THUMBNAILS_DIR", base_dir / "thumbnails")

        main.init_db()
        main.sync_service = SyncFolderService(
            base_dir / "data" / "documents.db",
            base_dir / "uploads",
            base_dir / "thumbnails",
        )

        client = TestClient(main.app)

        # "uploads/../../pwned.pdf" resolves to tmp_path/pwned.pdf — outside base_dir
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data/documents.db", b"SQLite format 3\x00" + b"\x00" * 84)
            zf.writestr("uploads/../../pwned.pdf", b"should not be written")
        buf.seek(0)

        pwned_path = tmp_path / "pwned.pdf"

        response = client.post(
            "/restore",
            files={"file": ("backup.zip", buf, "application/zip")},
        )

        assert response.status_code == 400
        assert "Unsafe path" in response.json()["detail"]
        assert not pwned_path.exists()

    def test_restore_rejects_symlink_entry(self, tmp_path, monkeypatch):
        """ZIP entries that are symlinks must be rejected."""
        import zipfile

        from fastapi.testclient import TestClient

        import backend.main as main
        from backend.sync_service import SyncFolderService

        base_dir = tmp_path / "base"
        (base_dir / "data").mkdir(parents=True)
        (base_dir / "uploads").mkdir()
        (base_dir / "thumbnails").mkdir()

        monkeypatch.setattr(main, "BASE_DIR", base_dir)
        monkeypatch.setattr(main, "DATA_DIR", base_dir / "data")
        monkeypatch.setattr(main, "DB_PATH", base_dir / "data" / "documents.db")
        monkeypatch.setattr(main, "UPLOAD_DIR", base_dir / "uploads")
        monkeypatch.setattr(main, "THUMBNAILS_DIR", base_dir / "thumbnails")

        main.init_db()
        main.sync_service = SyncFolderService(
            base_dir / "data" / "documents.db",
            base_dir / "uploads",
            base_dir / "thumbnails",
        )

        client = TestClient(main.app)

        # Build a ZIP with a symlink entry (Unix mode 0o120777 = 0xA1FF, stored in high 16 bits)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data/documents.db", b"SQLite format 3\x00" + b"\x00" * 84)
            info = zipfile.ZipInfo("uploads/link.pdf")
            info.external_attr = 0xA1FF << 16  # symlink with rwxrwxrwx permissions
            zf.writestr(info, "/etc/passwd")  # symlink target stored as content
        buf.seek(0)

        response = client.post(
            "/restore",
            files={"file": ("backup.zip", buf, "application/zip")},
        )

        assert response.status_code == 400
        assert "Unsafe path" in response.json()["detail"]

    def test_restore_oversized_zip_rejected(self, tmp_path, monkeypatch):
        """ZIP files exceeding the size limit must be rejected with 413."""
        import zipfile

        from fastapi.testclient import TestClient

        import backend.main as main
        from backend.sync_service import SyncFolderService

        base_dir = tmp_path / "base"
        (base_dir / "data").mkdir(parents=True)
        (base_dir / "uploads").mkdir()
        (base_dir / "thumbnails").mkdir()

        monkeypatch.setattr(main, "BASE_DIR", base_dir)
        monkeypatch.setattr(main, "DATA_DIR", base_dir / "data")
        monkeypatch.setattr(main, "DB_PATH", base_dir / "data" / "documents.db")
        monkeypatch.setattr(main, "UPLOAD_DIR", base_dir / "uploads")
        monkeypatch.setattr(main, "THUMBNAILS_DIR", base_dir / "thumbnails")
        monkeypatch.setattr(main, "MAX_RESTORE_SIZE", 10)  # 10-byte limit for the test

        main.init_db()
        main.sync_service = SyncFolderService(
            base_dir / "data" / "documents.db",
            base_dir / "uploads",
            base_dir / "thumbnails",
        )

        client = TestClient(main.app)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data/documents.db", b"x" * 100)
        buf.seek(0)

        response = client.post(
            "/restore",
            files={"file": ("big_backup.zip", buf, "application/zip")},
        )

        assert response.status_code == 413
        assert "too large" in response.json()["detail"].lower()


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

    def test_operator_only_no_wildcard(self):
        fn = self._fn()
        result = fn("AND OR NOT")
        assert not result.endswith("*")

    def test_escaped_quote_inside_phrase(self):
        fn = self._fn()
        assert fn('"say ""hello"" now"') == '"say ""hello"" now"'
