"""
Tests for FileFolio API endpoints.
Updated to match actual API implementation.
"""

import io
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pypdf
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

    def test_upload_empty_file_returns_400(self, client):
        """Uploading a 0-byte file should return 400, not 200."""
        empty_pdf = b""
        response = client.post(
            "/upload",
            files={"file": ("empty.pdf", io.BytesIO(empty_pdf), "application/pdf")},
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_upload_corrupted_pdf_returns_400(self, client):
        """A file with %PDF magic bytes but corrupt structure should return 400."""
        # Valid magic bytes, garbage body — pypdf cannot parse this
        corrupted = b"%PDF-1.4\n%%garbage_not_a_real_pdf_xref"
        response = client.post(
            "/upload",
            files={"file": ("corrupt.pdf", io.BytesIO(corrupted), "application/pdf")},
        )
        assert response.status_code == 400
        assert "corrupt" in response.json()["detail"].lower() or "invalid" in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        "evil_name",
        [
            "../../evil/secret.pdf",
            "..\\evil\\secret.pdf",
            "..\\evil/mixed\\secret.pdf",
        ],
    )
    def test_upload_strips_path_from_original_filename(
        self, client, sample_pdf_bytes, mock_ollama_response, evil_name
    ):
        """Filenames containing directory separators should be stored as basename only."""
        response = client.post(
            "/upload",
            files={"file": (evil_name, io.BytesIO(sample_pdf_bytes), "application/pdf")},
        )
        assert response.status_code == 200
        stored_name = response.json()["original_filename"]
        assert "/" not in stored_name
        assert "\\" not in stored_name
        assert stored_name == "secret.pdf"

    def test_upload_password_protected_pdf_returns_400(self, client, sample_pdf_bytes):
        """An encrypted PDF should be rejected with a 400 and a clear message."""
        with patch("backend.main.pypdf.PdfReader") as mock_reader:
            mock_reader.side_effect = pypdf.errors.FileNotDecryptedError
            response = client.post(
                "/upload",
                files={"file": ("locked.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")},
            )
        assert response.status_code == 400
        assert "password" in response.json()["detail"].lower()

    @pytest.mark.parametrize("bad_name", ["\x00.pdf", "legit\x00.pdf"])
    def test_upload_invalid_filename_returns_400(self, client, bad_name):
        """Filenames with null bytes should be rejected with 400."""
        response = client.post(
            "/upload",
            files={"file": (bad_name, io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert response.status_code == 400


class TestUploadStorageLayout:
    """Uploads land under uploads/<Category>/<Year>/ with a relative DB path."""

    def test_upload_is_filed_by_category_and_year(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], "Invoice")
        )
        monkeypatch.setattr(main, "generate_thumbnail", lambda path, name: None)

        response = client.post(
            "/upload",
            files={"file": ("layout.pdf", sample_pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 200

        conn = sqlite3.connect(test_db)
        file_path = conn.execute(
            "SELECT file_path FROM documents WHERE id = ?", (response.json()["id"],)
        ).fetchone()[0]
        conn.close()

        assert file_path.startswith("Invoice/")
        assert "/" in file_path and not Path(file_path).is_absolute()
        assert (main.UPLOAD_DIR / file_path).exists()

    def test_staging_directory_is_left_empty(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main
        from backend import storage

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], "Invoice")
        )
        monkeypatch.setattr(main, "generate_thumbnail", lambda path, name: None)

        client.post(
            "/upload",
            files={"file": ("staging.pdf", sample_pdf_bytes, "application/pdf")},
        )

        staging = storage.staging_dir(main.UPLOAD_DIR)
        assert not staging.exists() or not any(staging.iterdir())

    def test_uploaded_document_is_downloadable(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], "Receipt")
        )
        monkeypatch.setattr(main, "generate_thumbnail", lambda path, name: None)

        doc_id = client.post(
            "/upload",
            files={"file": ("round.pdf", sample_pdf_bytes, "application/pdf")},
        ).json()["id"]

        download = client.get(f"/download/{doc_id}")
        assert download.status_code == 200
        assert download.content[:4] == b"%PDF"


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
        """FTS search by filename returns the matching document."""
        files = {
            "file": ("invoice.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
        }
        client.post("/upload", files=files)

        response = client.get("/documents?search=invoice")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["original_filename"] == "invoice.pdf"

    def test_search_no_match_returns_empty(self, client, sample_pdf_bytes, mock_ollama_response):
        """FTS search with a non-matching term returns an empty list."""
        files = {"file": ("invoice.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        client.post("/upload", files=files)

        response = client.get("/documents?search=xyznotfound")
        assert response.status_code == 200
        assert response.json() == []

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


class TestDocumentMetadataEndpoint:
    """Tests for the GET /documents/{doc_id} JSON metadata endpoint."""

    def test_get_document_metadata_returns_full_preview(
        self, client, sample_pdf_bytes, mock_ollama_response, db_connection
    ):
        files = {
            "file": ("invoice.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
        }
        upload_response = client.post("/upload", files=files)
        doc_id = upload_response.json()["id"]

        # Create a content_preview longer than 200 chars to verify it's returned in full
        full_preview = "a" * 250  # 250 chars, definitely > 200
        db_connection.execute(
            "UPDATE documents SET content_preview = ? WHERE id = ?",
            (full_preview, doc_id),
        )
        db_connection.commit()

        response = client.get(f"/documents/{doc_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == doc_id
        assert data["original_filename"] == "invoice.pdf"
        assert data["category"] == "Invoice"
        assert data["tags"] == ["test", "sample"]
        # Verify the full preview is returned, not truncated to 200 chars
        assert data["content_preview"] == full_preview
        assert len(data["content_preview"]) == 250
        assert "thumbnail" in data

    def test_get_document_metadata_not_found(self, client):
        response = client.get("/documents/999999")
        assert response.status_code == 404
        assert response.json()["detail"] == "Document not found"


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

    def test_update_rejects_tags_as_integer(self, client, sample_pdf_bytes, mock_ollama_response):
        """PUT /document/{id} returns 422 when tags is sent as an integer, not a list."""
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        doc_id = client.post("/upload", files=files).json()["id"]

        response = client.put(f"/document/{doc_id}", json={"tags": 5})
        assert response.status_code == 422

    def test_update_rejects_invalid_category(self, client, sample_pdf_bytes, mock_ollama_response):
        """PUT /document/{id} returns 422 when category is not one of the valid enum values."""
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        doc_id = client.post("/upload", files=files).json()["id"]

        response = client.put(f"/document/{doc_id}", json={"category": "NotACategory"})
        assert response.status_code == 422

    def test_update_rejects_auto_filename_as_non_string(self, client, sample_pdf_bytes, mock_ollama_response):
        """PUT /document/{id} returns 422 when auto_filename is not a string."""
        files = {"file": ("test.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        doc_id = client.post("/upload", files=files).json()["id"]

        response = client.put(f"/document/{doc_id}", json={"auto_filename": 42})
        assert response.status_code == 422


def _failing_update_get_db_connection(real_get_db_connection):
    """A get_db_connection replacement whose UPDATE documents SET ... fails.

    Every other statement (the existence-check SELECT, direct verification queries,
    etc.) passes through to a real connection untouched, so this simulates a DB write
    failing (e.g. "database is locked") strictly at the point update_document commits.
    """

    class FailingCursor:
        def __init__(self, real_cursor):
            self._real_cursor = real_cursor

        def execute(self, query, params=None):
            if query.strip().startswith("UPDATE documents SET"):
                raise sqlite3.OperationalError("database is locked")
            if params is None:
                return self._real_cursor.execute(query)
            return self._real_cursor.execute(query, params)

        def __getattr__(self, name):
            return getattr(self._real_cursor, name)

    class FailingConnection:
        def __init__(self, real_conn):
            self._real_conn = real_conn

        def cursor(self):
            return FailingCursor(self._real_conn.cursor())

        def __getattr__(self, name):
            return getattr(self._real_conn, name)

    def fake_get_db_connection():
        return FailingConnection(real_get_db_connection())

    return fake_get_db_connection


class TestRecategoriseMovesFile:
    def _upload(self, client, sample_pdf_bytes, monkeypatch, category, name):
        import backend.main as main

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], category)
        )
        monkeypatch.setattr(main, "generate_thumbnail", lambda path, name_: None)
        return client.post(
            "/upload", files={"file": (name, sample_pdf_bytes, "application/pdf")}
        ).json()["id"]

    def test_changing_category_moves_the_pdf(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main

        doc_id = self._upload(client, sample_pdf_bytes, monkeypatch, "Invoice", "move.pdf")

        conn = sqlite3.connect(test_db)
        old_path = conn.execute(
            "SELECT file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[0]
        conn.close()
        assert old_path.startswith("Invoice/")

        response = client.put(f"/document/{doc_id}", json={"category": "Receipt"})
        assert response.status_code == 200

        conn = sqlite3.connect(test_db)
        new_path = conn.execute(
            "SELECT file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[0]
        conn.close()

        assert new_path.startswith("Receipt/")
        assert (main.UPLOAD_DIR / new_path).exists()
        assert not (main.UPLOAD_DIR / old_path).exists()

    def test_document_is_still_downloadable_after_recategorising(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        doc_id = self._upload(client, sample_pdf_bytes, monkeypatch, "Invoice", "still.pdf")
        client.put(f"/document/{doc_id}", json={"category": "Tax"})

        download = client.get(f"/download/{doc_id}")
        assert download.status_code == 200
        assert download.content[:4] == b"%PDF"

    def test_updating_only_tags_does_not_move_the_file(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        doc_id = self._upload(client, sample_pdf_bytes, monkeypatch, "Invoice", "tagsonly.pdf")

        conn = sqlite3.connect(test_db)
        before = conn.execute(
            "SELECT file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[0]
        conn.close()

        client.put(f"/document/{doc_id}", json={"tags": ["a", "b"]})

        conn = sqlite3.connect(test_db)
        after = conn.execute(
            "SELECT file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[0]
        conn.close()

        assert before == after

    def test_failed_move_leaves_the_row_and_file_untouched(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        """A disk-level failure during the move must not touch the database row."""
        import backend.main as main

        doc_id = self._upload(client, sample_pdf_bytes, monkeypatch, "Invoice", "failmove.pdf")

        conn = sqlite3.connect(test_db)
        old_category, old_path = conn.execute(
            "SELECT category, file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        conn.close()

        def raise_os_error(*args, **kwargs):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(main.storage, "move_to_category", raise_os_error)

        response = client.put(f"/document/{doc_id}", json={"category": "Receipt"})
        assert response.status_code == 500

        conn = sqlite3.connect(test_db)
        category_after, path_after = conn.execute(
            "SELECT category, file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        conn.close()

        assert category_after == old_category
        assert path_after == old_path
        assert (main.UPLOAD_DIR / old_path).exists()

    def test_failed_database_write_moves_the_file_back(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        """If the DB write fails after the file already moved, the move is undone."""
        import backend.main as main

        doc_id = self._upload(client, sample_pdf_bytes, monkeypatch, "Invoice", "rollback.pdf")

        conn = sqlite3.connect(test_db)
        old_category, old_path = conn.execute(
            "SELECT category, file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        conn.close()

        monkeypatch.setattr(
            main,
            "get_db_connection",
            _failing_update_get_db_connection(main.get_db_connection),
        )

        response = client.put(f"/document/{doc_id}", json={"category": "Receipt"})
        assert response.status_code == 500

        conn = sqlite3.connect(test_db)
        category_after, path_after = conn.execute(
            "SELECT category, file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        conn.close()

        assert category_after == old_category
        assert path_after == old_path
        assert (main.UPLOAD_DIR / old_path).exists()

    def test_failed_database_write_after_a_uniquified_move_restores_the_exact_original_path(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        """Reproduces the case where the forward move had to uniquify: the rollback
        must land the file back under its ORIGINAL name, not a recomputed one that
        collides with the name the forward move actually used."""
        import backend.main as main
        from pypdf import PdfWriter

        doc_a = self._upload(client, sample_pdf_bytes, monkeypatch, "Invoice", "collide.pdf")

        # A different page size gives distinct bytes/hash so the upload isn't rejected
        # as a duplicate of doc_a.
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        other_pdf_bytes = io.BytesIO()
        writer.write(other_pdf_bytes)
        other_pdf_bytes.seek(0)
        doc_b = self._upload(
            client, other_pdf_bytes.getvalue(), monkeypatch, "Receipt", "other.pdf"
        )

        conn = sqlite3.connect(test_db)
        a_path = conn.execute(
            "SELECT file_path FROM documents WHERE id = ?", (doc_a,)
        ).fetchone()[0]
        b_path = conn.execute(
            "SELECT file_path FROM documents WHERE id = ?", (doc_b,)
        ).fetchone()[0]
        conn.close()

        a_filename = Path(a_path).name
        # doc_b already lives under Receipt/<year>/; rename it (file and row) onto the
        # exact name doc_a's forward move would target, forcing that move to uniquify --
        # this is the collision the reviewer reproduced.
        collide_relative = f"{Path(b_path).parent.as_posix()}/{a_filename}"
        (main.UPLOAD_DIR / b_path).rename(main.UPLOAD_DIR / collide_relative)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "UPDATE documents SET file_path = ? WHERE id = ?", (collide_relative, doc_b)
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(
            main,
            "get_db_connection",
            _failing_update_get_db_connection(main.get_db_connection),
        )

        response = client.put(f"/document/{doc_a}", json={"category": "Receipt"})
        assert response.status_code == 500

        conn = sqlite3.connect(test_db)
        category_after, path_after = conn.execute(
            "SELECT category, file_path FROM documents WHERE id = ?", (doc_a,)
        ).fetchone()
        conn.close()

        assert category_after == "Invoice"
        assert path_after == a_path
        assert (main.UPLOAD_DIR / a_path).exists()
        assert (main.UPLOAD_DIR / a_path).read_bytes()[:4] == b"%PDF"
        # The uniquified name the forward move used is gone -- the rollback moved
        # that file back rather than leaving an orphan behind.
        a_stem, a_suffix = Path(a_filename).stem, Path(a_filename).suffix
        uniquified_relative = f"{Path(b_path).parent.as_posix()}/{a_stem}_1{a_suffix}"
        assert not (main.UPLOAD_DIR / uniquified_relative).exists()


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


class TestBackupRestoreEndpoints:
    """Tests for GET /backup and POST /restore endpoints."""

    def test_backup_returns_valid_zip(self, client):
        """GET /backup returns a ZIP containing the database and metadata."""
        response = client.get("/backup")
        assert response.status_code == 200
        assert "application/zip" in response.headers["content-type"]
        buf = io.BytesIO(response.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        assert "data/documents.db" in names
        assert "backup_metadata.json" in names

    def test_backup_metadata_fields(self, client):
        """backup_metadata.json inside the ZIP has the expected top-level keys."""
        response = client.get("/backup")
        assert response.status_code == 200
        buf = io.BytesIO(response.content)
        with zipfile.ZipFile(buf) as zf:
            metadata = json.loads(zf.read("backup_metadata.json"))
        assert "system" in metadata
        assert "version" in metadata
        assert "backup_date" in metadata

    def test_backup_database_is_valid_sqlite(self, client):
        """data/documents.db in the backup ZIP is a valid SQLite database (not a raw copy)."""
        response = client.get("/backup")
        assert response.status_code == 200
        buf = io.BytesIO(response.content)
        with zipfile.ZipFile(buf) as zf:
            db_bytes = zf.read("data/documents.db")
        # SQLite databases always start with the 16-byte magic string
        assert db_bytes[:16] == b"SQLite format 3\x00"
        # Verify it is a fully readable database by querying it in-memory
        import sqlite3 as _sqlite3
        import tempfile, os as _os
        fd, tmp = tempfile.mkstemp(suffix=".db")
        _os.close(fd)
        try:
            with open(tmp, "wb") as f:
                f.write(db_bytes)
            conn = _sqlite3.connect(tmp)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            conn.close()
        finally:
            _os.unlink(tmp)
        assert "documents" in tables

    def test_restore_happy_path(self, client, tmp_path, monkeypatch):
        """POST /restore with a valid backup ZIP returns success and correct stats."""
        import backend.main as main

        base_dir = tmp_path / "restore_base"
        (base_dir / "data").mkdir(parents=True)
        (base_dir / "uploads").mkdir()
        (base_dir / "thumbnails").mkdir()
        monkeypatch.setattr(main, "BASE_DIR", base_dir)
        monkeypatch.setattr(main, "DATA_DIR", base_dir / "data")
        monkeypatch.setattr(main, "DB_PATH", base_dir / "data" / "documents.db")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "data/documents.db",
                b"SQLite format 3\x00" + b"\x00" * 84,
            )
            zf.writestr(
                "backup_metadata.json",
                json.dumps({
                    "system": "FileFolio",
                    "version": "1.0",
                    "backup_date": "2026-01-01T00:00:00",
                }),
            )
        buf.seek(0)

        response = client.post(
            "/restore",
            files={"file": ("backup.zip", buf, "application/zip")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["stats"]["pdfs_restored"] == 0
        assert data["stats"]["thumbnails_restored"] == 0

    def test_restore_missing_database_entry(self, client):
        """POST /restore with a ZIP that lacks data/documents.db returns 400."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("backup_metadata.json", json.dumps({"system": "FileFolio"}))
        buf.seek(0)

        response = client.post(
            "/restore",
            files={"file": ("backup.zip", buf, "application/zip")},
        )
        assert response.status_code == 400
        assert "missing database" in response.json()["detail"].lower()

    def test_restore_non_zip_file(self, client):
        """POST /restore with a non-ZIP file returns 400."""
        response = client.post(
            "/restore",
            files={"file": ("notes.txt", io.BytesIO(b"not a zip"), "text/plain")},
        )
        assert response.status_code == 400


class TestBackupIncludesNestedFiles:
    def test_backup_preserves_the_category_tree(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        import zipfile
        import io

        import backend.main as main

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], "Invoice")
        )
        monkeypatch.setattr(main, "generate_thumbnail", lambda path, name: None)

        client.post(
            "/upload", files={"file": ("nested.pdf", sample_pdf_bytes, "application/pdf")}
        )

        response = client.get("/backup")
        assert response.status_code == 200

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            pdf_entries = [n for n in archive.namelist() if n.endswith(".pdf")]

        assert pdf_entries, "backup contained no PDFs"
        assert all(entry.startswith("uploads/") for entry in pdf_entries)
        assert any(entry.startswith("uploads/Invoice/") for entry in pdf_entries)

    def test_backup_excludes_staging(self, client, test_db, sample_pdf_bytes):
        import zipfile
        import io

        import backend.main as main
        from backend import storage

        staging = storage.staging_dir(main.UPLOAD_DIR)
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "half_written.pdf").write_bytes(sample_pdf_bytes)

        response = client.get("/backup")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()

        assert not any(storage.STAGING_DIRNAME in name for name in names)


class TestStoredPathContainment:
    """POST /restore accepts an arbitrary ZIP and trusts the restored database
    completely. A single row whose file_path points outside uploads/ must not give
    the app a handle on that file: storage.resolve is the one chokepoint, so the
    endpoints reading it have to refuse rather than serve or delete it."""

    def _seed(self, test_db, file_path):
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO documents (original_filename, stored_filename, file_path, "
            "category, upload_date) VALUES (?, ?, ?, ?, ?)",
            ("secret.pdf", "secret.pdf", str(file_path), "Invoice", "2026-01-01"),
        )
        doc_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return doc_id

    def test_document_outside_the_upload_dir_is_not_served(
        self, client, test_db, tmp_path, sample_pdf_bytes
    ):
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(sample_pdf_bytes)
        doc_id = self._seed(test_db, outside)

        assert client.get(f"/document/{doc_id}").status_code == 400
        assert client.get(f"/download/{doc_id}").status_code == 400
        assert outside.exists()

    def test_document_outside_the_upload_dir_is_not_deleted_from_disk(
        self, client, test_db, tmp_path, sample_pdf_bytes
    ):
        """DELETE removes the row either way, but must not unlink a file it was
        never entitled to touch."""
        outside = tmp_path / "outside_delete.pdf"
        outside.write_bytes(sample_pdf_bytes)
        doc_id = self._seed(test_db, outside)

        assert client.delete(f"/document/{doc_id}").status_code == 200
        assert outside.exists()

    def test_migration_does_not_pull_an_outside_file_into_the_library(
        self, test_db, tmp_path, sample_pdf_bytes
    ):
        """The migration physically moves files. A restored row pointing outside
        uploads/ must be reported failed and left alone, not imported."""
        import backend.main as main
        from backend import storage

        outside = tmp_path / "outside_migrate.pdf"
        outside.write_bytes(sample_pdf_bytes)
        self._seed(test_db, outside)

        stats = storage.migrate_uploads_to_category_folders(
            main.get_db_connection, main.UPLOAD_DIR
        )

        assert stats["moved"] == 0
        assert outside.exists()
        assert not (main.UPLOAD_DIR / "Invoice" / "2026" / "outside_migrate.pdf").exists()


class TestCategoryContract:
    """The twelve categories exist in two places -- storage.VALID_CATEGORIES, which
    decides the folder a PDF is filed under, and main.ValidCategory, which decides
    what PUT /document/{id} accepts. Drift between them is silent and moves files:
    a category accepted by the API but unknown to storage is written to the database
    while the PDF lands under Other/, and the migration's fast path then treats that
    row as organised forever."""

    def test_storage_categories_match_the_api_contract(self):
        from typing import get_args

        import backend.main as main
        from backend import storage

        assert set(storage.VALID_CATEGORIES) == set(get_args(main.ValidCategory))

    def test_process_document_accepts_every_contract_category(
        self, test_db, monkeypatch
    ):
        """process_document used to carry a third private copy of the list. It now
        reads storage.VALID_CATEGORIES; this asserts the behaviour that copy provided
        -- every contract category survives normalisation instead of silently
        degrading to Other."""
        import backend.main as main
        from backend import storage

        for category in storage.VALID_CATEGORIES:
            monkeypatch.setattr(
                main.ollama,
                "chat",
                lambda *a, _c=category, **k: {
                    "message": {
                        "content": '{"category": "%s", "tags": ["alpha bravo"]}' % _c
                    }
                },
            )
            _, resolved = main.process_document("some text", "doc.pdf")
            assert resolved == category

    def test_a_category_outside_the_contract_degrades_to_other(
        self, test_db, monkeypatch
    ):
        import backend.main as main

        monkeypatch.setattr(
            main.ollama,
            "chat",
            lambda *a, **k: {
                "message": {
                    "content": '{"category": "Rechnung", "tags": ["alpha bravo"]}'
                }
            },
        )
        _, resolved = main.process_document("some text", "doc.pdf")
        assert resolved == "Other"


class TestStagedUploadsAreNotLeaked:
    """uploads/.staging/ is hidden, excluded from backups and excluded from the
    migration's recovery search. A staged PDF that nothing removes is therefore
    invisible and unbounded, so every failure between writing it and a successful
    place() has to take it with it."""

    @staticmethod
    def _staged_files(upload_dir):
        from backend import storage

        staging = storage.staging_dir(upload_dir)
        return sorted(p.name for p in staging.iterdir()) if staging.exists() else []

    def test_upload_cleans_up_when_processing_raises(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main

        def boom(text, filename):
            raise RuntimeError("simulated tagging failure")

        monkeypatch.setattr(main, "process_document", boom)

        with pytest.raises(RuntimeError):
            client.post(
                "/upload",
                files={"file": ("leak.pdf", sample_pdf_bytes, "application/pdf")},
            )

        assert self._staged_files(main.UPLOAD_DIR) == []

    def test_upload_cleans_up_when_the_move_raises_shutil_error(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        """_move_into_place falls back to shutil.move, which raises shutil.Error.

        That subclasses OSError, so the call-site guard already covers it. What this
        test actually pins is the staging cleanup: however the move fails, the staged
        file must not be left behind."""
        import backend.main as main
        from backend import storage

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], "Invoice")
        )

        def boom(*args, **kwargs):
            raise shutil.Error("simulated cross-device failure")

        monkeypatch.setattr(storage, "place", boom)

        response = client.post(
            "/upload",
            files={"file": ("leak2.pdf", sample_pdf_bytes, "application/pdf")},
        )

        assert response.status_code == 500
        assert "Could not store the uploaded file" in response.json()["detail"]
        assert self._staged_files(main.UPLOAD_DIR) == []

    def test_sync_processing_cleans_up_when_processing_raises(
        self, test_db, tmp_path, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main

        def boom(text, filename):
            raise RuntimeError("simulated tagging failure")

        monkeypatch.setattr(main, "process_document", boom)

        source = tmp_path / "incoming.pdf"
        source.write_bytes(sample_pdf_bytes)

        assert main.sync_service._process_pdf(source, 1) is False
        assert self._staged_files(main.UPLOAD_DIR) == []

    def test_sync_processing_cleans_up_on_shutil_error(
        self, test_db, tmp_path, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main
        from backend import storage

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], "Invoice")
        )

        def boom(*args, **kwargs):
            raise shutil.Error("simulated cross-device failure")

        monkeypatch.setattr(storage, "place", boom)

        source = tmp_path / "incoming2.pdf"
        source.write_bytes(sample_pdf_bytes)

        assert main.sync_service._process_pdf(source, 1) is False
        assert self._staged_files(main.UPLOAD_DIR) == []


class TestStartupMigration:
    def test_startup_event_runs_the_migration(self, test_db, monkeypatch):
        """The migration must be wired into startup_event itself, not merely exist as
        a callable: deleting that one line would break the feature for every existing
        library with nothing else failing. Drives the real event handler rather than
        calling storage.migrate_uploads_to_category_folders directly."""
        import asyncio

        import backend.main as main

        # No watchdog threads: only the migration half of startup is under test.
        monkeypatch.setattr(main.sync_service, "start", lambda: None)

        flat = main.UPLOAD_DIR / "20240101_000000_startup.pdf"
        flat.write_bytes(b"%PDF-1.4 legacy")

        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO documents (original_filename, stored_filename, file_path, "
            "category, upload_date) VALUES (?, ?, ?, ?, ?)",
            ("startup.pdf", flat.name, str(flat), "Legal", "2024-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

        asyncio.run(main.startup_event())

        assert (main.UPLOAD_DIR / "Legal" / "2024" / flat.name).exists()
        assert not flat.exists()

    def test_flat_legacy_document_is_organised(self, test_db, temp_test_dir):
        import sqlite3

        import backend.main as main
        from backend import storage

        flat = main.UPLOAD_DIR / "20240101_000000_legacy.pdf"
        flat.write_bytes(b"%PDF-1.4 legacy")

        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO documents (original_filename, stored_filename, file_path, "
            "category, upload_date) VALUES (?, ?, ?, ?, ?)",
            ("legacy.pdf", flat.name, str(flat), "Legal", "2024-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

        stats = storage.migrate_uploads_to_category_folders(
            main.get_db_connection, main.UPLOAD_DIR
        )

        assert stats["moved"] == 1
        assert (main.UPLOAD_DIR / "Legal" / "2024" / flat.name).exists()
        assert not flat.exists()


class TestRestoreRunsMigration:
    """POST /restore must reorganise restored documents, and must not fail
    the restore when that reorganisation itself fails."""

    def test_restore_reorganises_legacy_documents(
        self, client, tmp_path, sample_pdf_bytes, monkeypatch
    ):
        """A restored row with a stale absolute file_path ends up organised
        into its category/year folder, proving the restore-time wiring (not
        just the migration function in isolation)."""
        import backend.main as main

        base_dir = tmp_path / "restore_migration_base"
        (base_dir / "data").mkdir(parents=True)
        (base_dir / "uploads").mkdir()
        (base_dir / "thumbnails").mkdir()
        monkeypatch.setattr(main, "BASE_DIR", base_dir)
        monkeypatch.setattr(main, "DATA_DIR", base_dir / "data")
        monkeypatch.setattr(main, "DB_PATH", base_dir / "data" / "documents.db")
        monkeypatch.setattr(main, "UPLOAD_DIR", base_dir / "uploads")

        # Build a real, minimal documents database with a legacy row whose
        # file_path is an absolute path from another machine.
        source_db_path = base_dir / "source.db"
        conn = sqlite3.connect(source_db_path)
        conn.execute(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT,
                stored_filename TEXT,
                file_path TEXT,
                category TEXT,
                upload_date TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO documents (original_filename, stored_filename, file_path, "
            "category, upload_date) VALUES (?, ?, ?, ?, ?)",
            (
                "legacy.pdf",
                "20240101_000000_legacy.pdf",
                "/some/other/machine/uploads/20240101_000000_legacy.pdf",
                "Legal",
                "2024-01-01T00:00:00",
            ),
        )
        conn.commit()
        conn.close()
        db_bytes = source_db_path.read_bytes()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data/documents.db", db_bytes)
            zf.writestr("uploads/20240101_000000_legacy.pdf", sample_pdf_bytes)
            zf.writestr(
                "backup_metadata.json",
                json.dumps(
                    {
                        "system": "FileFolio",
                        "version": "1.0",
                        "backup_date": "2026-01-01T00:00:00",
                    }
                ),
            )
        buf.seek(0)

        response = client.post(
            "/restore", files={"file": ("backup.zip", buf, "application/zip")}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["migration_warning"] is None
        assert (
            base_dir / "uploads" / "Legal" / "2024" / "20240101_000000_legacy.pdf"
        ).exists()

    def test_restore_reports_migration_failure_without_failing_the_restore(
        self, client, tmp_path, monkeypatch
    ):
        """If the post-restore migration pass raises, the restore itself
        still reports success, but migration_warning tells the caller."""
        import backend.main as main
        from backend import storage

        base_dir = tmp_path / "restore_migration_failure_base"
        (base_dir / "data").mkdir(parents=True)
        (base_dir / "uploads").mkdir()
        (base_dir / "thumbnails").mkdir()
        monkeypatch.setattr(main, "BASE_DIR", base_dir)
        monkeypatch.setattr(main, "DATA_DIR", base_dir / "data")
        monkeypatch.setattr(main, "DB_PATH", base_dir / "data" / "documents.db")

        def raise_migration(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            storage, "migrate_uploads_to_category_folders", raise_migration
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "data/documents.db",
                b"SQLite format 3\x00" + b"\x00" * 84,
            )
            zf.writestr(
                "backup_metadata.json",
                json.dumps(
                    {
                        "system": "FileFolio",
                        "version": "1.0",
                        "backup_date": "2026-01-01T00:00:00",
                    }
                ),
            )
        buf.seek(0)

        response = client.post(
            "/restore", files={"file": ("backup.zip", buf, "application/zip")}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["migration_warning"] is not None
        assert "boom" in data["migration_warning"]


class TestDuplicateDetectionRace:
    """
    T010: The pre-check SELECT and the INSERT are in separate transactions.
    A UNIQUE constraint on file_hash (with IntegrityError catch at INSERT) is
    the correct fix — the pre-check is a fast early-exit, not a safety net.
    """

    def test_file_hash_unique_constraint(self, db_connection):
        """Inserting two rows with the same non-null file_hash must raise IntegrityError."""
        now = "2026-01-01T00:00:00"
        db_connection.execute(
            "INSERT INTO documents "
            "(original_filename, stored_filename, file_path, upload_date, file_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            ("a.pdf", "a.pdf", "/a.pdf", now, "deadbeef1234"),
        )
        db_connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db_connection.execute(
                "INSERT INTO documents "
                "(original_filename, stored_filename, file_path, upload_date, file_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                ("b.pdf", "b.pdf", "/b.pdf", now, "deadbeef1234"),  # same hash
            )
            db_connection.commit()

    def test_null_file_hash_not_constrained(self, db_connection):
        """Two rows with NULL file_hash must not conflict (partial index semantics)."""
        now = "2026-01-01T00:00:00"
        db_connection.execute(
            "INSERT INTO documents "
            "(original_filename, stored_filename, file_path, upload_date, file_hash) "
            "VALUES (?, ?, ?, ?, NULL)",
            ("c.pdf", "c.pdf", "/c.pdf", now),
        )
        db_connection.execute(
            "INSERT INTO documents "
            "(original_filename, stored_filename, file_path, upload_date, file_hash) "
            "VALUES (?, ?, ?, ?, NULL)",
            ("d.pdf", "d.pdf", "/d.pdf", now),
        )
        db_connection.commit()  # must not raise

    def test_upload_race_condition_returns_409(
        self, client, sample_pdf_bytes, monkeypatch, mock_ollama_response
    ):
        """When the dedup pre-check is bypassed by a race, IntegrityError at INSERT
        must return 409, not 500."""
        import backend.main as main

        # First upload seeds the DB with the hash.
        files = {"file": ("race.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        r1 = client.post("/upload", files=files)
        assert r1.status_code == 200

        # Simulate the race window: the first call to get_db_connection (the pre-check)
        # returns a mock whose cursor.fetchone() reports no duplicate, so the upload
        # proceeds past the check and hits the UNIQUE constraint at INSERT.
        real_get_db = main.get_db_connection
        call_number = [0]

        def patched_get_db():
            call_number[0] += 1
            if call_number[0] == 1:
                mock_conn = MagicMock()
                mock_conn.cursor.return_value.fetchone.return_value = None
                return mock_conn
            return real_get_db()

        monkeypatch.setattr(main, "get_db_connection", patched_get_db)

        files = {"file": ("race.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")}
        r2 = client.post("/upload", files=files)
        assert r2.status_code == 409
        assert "Duplicate file detected" in r2.json()["detail"]


class TestReindexCrashSafe:
    """Verify that reindex_documents_content is transactional: a mid-operation crash
    must not leave the database without its FTS triggers."""

    _TRIGGER_NAMES = {"documents_ai", "documents_ad", "documents_au"}

    def _trigger_names_in_db(self, db_path):
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
            " AND name IN ('documents_ai', 'documents_ad', 'documents_au')"
        ).fetchall()
        conn.close()
        return {row[0] for row in rows}

    def test_triggers_survive_mid_reindex_crash(self, test_db, monkeypatch, sample_pdf_file):
        """KeyboardInterrupt during reindex must not destroy FTS triggers."""
        import backend.main as main
        import pypdf

        # A legacy-style absolute file_path, but inside UPLOAD_DIR: storage.resolve
        # rejects stored paths that escape it, so a row pointing outside would be
        # skipped before PdfReader is ever reached and the crash under test would
        # never happen.
        legacy_absolute = main.UPLOAD_DIR / "crash.pdf"
        legacy_absolute.write_bytes(sample_pdf_file.read_bytes())

        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO documents"
            " (original_filename, stored_filename, file_path, auto_filename, tags, category, content_preview, upload_date)"
            " VALUES ('crash.pdf', 'crash.pdf', ?, 'crash.pdf', '[]', 'Test', '', '2026-01-01')",
            (str(legacy_absolute),),
        )
        conn.commit()
        conn.close()

        def raise_interrupt(*args, **kwargs):
            raise KeyboardInterrupt("simulated crash")

        monkeypatch.setattr(pypdf, "PdfReader", raise_interrupt)

        with pytest.raises(KeyboardInterrupt):
            main.reindex_documents_content()

        assert self._trigger_names_in_db(test_db) == self._TRIGGER_NAMES, (
            "FTS triggers were lost after a mid-reindex crash — "
            "reindex_documents_content must roll back the transaction on failure"
        )

    def test_triggers_present_after_successful_reindex(self, test_db):
        """Happy path: all three FTS triggers exist after a clean reindex (empty DB)."""
        import backend.main as main

        main.reindex_documents_content()

        assert self._trigger_names_in_db(test_db) == self._TRIGGER_NAMES


class TestNestedFileLifecycle:
    """Delete, bulk download, and restore against the nested Category/Year layout."""

    def _upload(self, client, sample_pdf_bytes, monkeypatch, category, name):
        import backend.main as main

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], category)
        )
        monkeypatch.setattr(main, "generate_thumbnail", lambda path, name_: None)
        return client.post(
            "/upload", files={"file": (name, sample_pdf_bytes, "application/pdf")}
        ).json()["id"]

    def test_delete_removes_the_nested_file(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main

        doc_id = self._upload(client, sample_pdf_bytes, monkeypatch, "Invoice", "del.pdf")

        conn = sqlite3.connect(test_db)
        file_path = conn.execute(
            "SELECT file_path FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[0]
        conn.close()
        assert (main.UPLOAD_DIR / file_path).exists()

        assert client.delete(f"/document/{doc_id}").status_code == 200
        assert not (main.UPLOAD_DIR / file_path).exists()

    def test_bulk_download_spans_category_folders(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        from pypdf import PdfWriter

        first = self._upload(client, sample_pdf_bytes, monkeypatch, "Invoice", "one.pdf")

        # A second, distinct PDF so the two do not collide on the duplicate hash check.
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        other_bytes = io.BytesIO()
        writer.write(other_bytes)
        second = self._upload(
            client, other_bytes.getvalue(), monkeypatch, "Receipt", "two.pdf"
        )

        response = client.post(
            "/download/multiple", json={"document_ids": [first, second]}
        )
        assert response.status_code == 200

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert sorted(archive.namelist()) == ["one.pdf", "two.pdf"]

    def test_restoring_a_flat_backup_organises_the_library(
        self, client, tmp_path, sample_pdf_bytes, monkeypatch
    ):
        """A backup in the old flat format, holding documents in several
        categories, restores and is then filed by category/year.

        TestRestoreRunsMigration already covers a single legacy row with an
        absolute file_path resolving after restore. This covers what that one
        does not: several rows, in different categories, migrated in the same
        restore pass -- and it patches BASE_DIR/DATA_DIR to a scratch
        directory (as TestRestoreRunsMigration does) rather than relying on
        the test_db fixture alone, because /restore extracts backup contents
        relative to the real BASE_DIR, not UPLOAD_DIR -- using test_db/
        temp_test_dir here without that patch would write into this
        worktree's actual uploads/ and data/ directories.
        """
        import backend.main as main

        base_dir = tmp_path / "flat_backup_restore_base"
        (base_dir / "data").mkdir(parents=True)
        (base_dir / "uploads").mkdir()
        (base_dir / "thumbnails").mkdir()
        monkeypatch.setattr(main, "BASE_DIR", base_dir)
        monkeypatch.setattr(main, "DATA_DIR", base_dir / "data")
        monkeypatch.setattr(main, "DB_PATH", base_dir / "data" / "documents.db")
        monkeypatch.setattr(main, "UPLOAD_DIR", base_dir / "uploads")
        monkeypatch.setattr(main, "THUMBNAILS_DIR", base_dir / "thumbnails")

        # Build a flat-format backup by hand: uploads/<name>.pdf plus a database
        # whose rows carry pre-migration file_path values from two categories.
        legacy_db = tmp_path / "legacy.db"
        conn = sqlite3.connect(legacy_db)
        conn.execute(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                auto_filename TEXT,
                file_path TEXT NOT NULL,
                file_hash TEXT,
                tags TEXT,
                category TEXT,
                upload_date TEXT NOT NULL,
                content_preview TEXT,
                thumbnail_path TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO documents (original_filename, stored_filename, file_path, "
            "category, upload_date) VALUES (?, ?, ?, ?, ?)",
            (
                "old.pdf",
                "20230405_120000_old.pdf",
                "/other/machine/uploads/20230405_120000_old.pdf",
                "Medical",
                "2023-04-05T12:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO documents (original_filename, stored_filename, file_path, "
            "category, upload_date) VALUES (?, ?, ?, ?, ?)",
            (
                "receipt.pdf",
                "20220110_090000_receipt.pdf",
                "/other/machine/uploads/20220110_090000_receipt.pdf",
                "Receipt",
                "2022-01-10T09:00:00",
            ),
        )
        conn.commit()
        conn.close()

        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.write(legacy_db, "data/documents.db")
            archive.writestr("uploads/20230405_120000_old.pdf", sample_pdf_bytes)
            archive.writestr("uploads/20220110_090000_receipt.pdf", sample_pdf_bytes)
            archive.writestr("backup_metadata.json", '{"version": "1.0"}')
        archive_bytes.seek(0)

        response = client.post(
            "/restore",
            files={"file": ("backup.zip", archive_bytes.getvalue(), "application/zip")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["migration_warning"] is None

        assert (
            base_dir / "uploads" / "Medical" / "2023" / "20230405_120000_old.pdf"
        ).exists()
        assert (
            base_dir / "uploads" / "Receipt" / "2022" / "20220110_090000_receipt.pdf"
        ).exists()


class TestStagingIsCleanAfterRejectedUploads:
    """Every /upload rejection path must leave uploads/.staging/ empty."""

    def _staging_entries(self):
        import backend.main as main
        from backend import storage

        staging = storage.staging_dir(main.UPLOAD_DIR)
        return list(staging.iterdir()) if staging.exists() else []

    def test_empty_file_leaves_no_staged_file(self, client, test_db):
        response = client.post(
            "/upload", files={"file": ("empty.pdf", b"", "application/pdf")}
        )
        assert response.status_code == 400
        assert self._staging_entries() == []

    def test_bad_magic_bytes_leaves_no_staged_file(self, client, test_db):
        response = client.post(
            "/upload", files={"file": ("fake.pdf", b"NOTAPDF" * 10, "application/pdf")}
        )
        assert response.status_code == 400
        assert self._staging_entries() == []

    def test_corrupt_pdf_leaves_no_staged_file(self, client, test_db):
        response = client.post(
            "/upload",
            files={"file": ("corrupt.pdf", b"%PDF-1.4 truncated garbage", "application/pdf")},
        )
        assert response.status_code == 400
        assert self._staging_entries() == []

    def test_duplicate_upload_leaves_no_staged_file(
        self, client, test_db, sample_pdf_bytes, monkeypatch
    ):
        import backend.main as main

        monkeypatch.setattr(
            main, "process_document", lambda text, filename: (["test"], "Invoice")
        )
        monkeypatch.setattr(main, "generate_thumbnail", lambda path, name: None)

        first = client.post(
            "/upload", files={"file": ("dup.pdf", sample_pdf_bytes, "application/pdf")}
        )
        assert first.status_code == 200

        second = client.post(
            "/upload", files={"file": ("dup.pdf", sample_pdf_bytes, "application/pdf")}
        )
        assert second.status_code == 409
        assert self._staging_entries() == []
