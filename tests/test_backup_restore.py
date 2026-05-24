"""
Tests for the /backup and /restore endpoints.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.getvalue()


def _make_backup_zip(
    *,
    include_db: bool = True,
    pdfs: dict[str, bytes] | None = None,
    thumbs: dict[str, bytes] | None = None,
    metadata: dict | None = None,
) -> bytes:
    """Build an in-memory backup ZIP matching the expected structure."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if include_db:
            zf.writestr("data/documents.db", b"SQLite format 3\x00")
        for name, data in (pdfs or {}).items():
            zf.writestr(f"uploads/{name}", data)
        for name, data in (thumbs or {}).items():
            zf.writestr(f"thumbnails/{name}", data)
        meta = metadata if metadata is not None else {
            "backup_date": "2026-01-01T00:00:00",
            "version": "1.0",
            "system": "FileFolio",
        }
        zf.writestr("backup_metadata.json", json.dumps(meta))
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Backup tests
# ---------------------------------------------------------------------------

class TestBackupEndpoint:
    """Tests for GET /backup."""

    def test_backup_returns_200(self, client):
        response = client.get("/backup")
        assert response.status_code == 200

    def test_backup_content_type_is_zip(self, client):
        response = client.get("/backup")
        assert "application/zip" in response.headers["content-type"]

    def test_backup_body_is_valid_zip(self, client):
        response = client.get("/backup")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert zf.testzip() is None

    def test_backup_contains_metadata_json(self, client):
        response = client.get("/backup")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert "backup_metadata.json" in zf.namelist()
            meta = json.loads(zf.read("backup_metadata.json"))
            assert meta["system"] == "FileFolio"
            assert "backup_date" in meta
            assert "version" in meta

    def test_backup_contains_database(self, client, test_db):
        """Backup includes data/documents.db when the database exists."""
        response = client.get("/backup")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert "data/documents.db" in zf.namelist()

    def test_backup_contains_uploaded_pdfs(self, client, test_db):
        """Backup includes any .pdf files present in UPLOAD_DIR."""
        import backend.main as main

        dummy = main.UPLOAD_DIR / "backup_test.pdf"
        dummy.write_bytes(b"%PDF-1.4 dummy")
        try:
            response = client.get("/backup")
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                assert "uploads/backup_test.pdf" in zf.namelist()
        finally:
            dummy.unlink(missing_ok=True)

    def test_backup_succeeds_with_empty_dirs(self, client, test_db):
        """GET /backup succeeds even when there are no PDFs or thumbnails."""
        response = client.get("/backup")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert "backup_metadata.json" in zf.namelist()


# ---------------------------------------------------------------------------
# Restore tests
# ---------------------------------------------------------------------------

class TestRestoreEndpoint:
    """Tests for POST /restore."""

    @pytest.fixture(autouse=True)
    def _redirect_base_dir(self, tmp_path, monkeypatch):
        """Patch BASE_DIR and DATA_DIR so restore extracts into an isolated temp dir."""
        import backend.main as main

        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "uploads").mkdir(exist_ok=True)
        (tmp_path / "thumbnails").mkdir(exist_ok=True)

        monkeypatch.setattr(main, "BASE_DIR", tmp_path)
        monkeypatch.setattr(main, "DATA_DIR", tmp_path / "data")
        self._base = tmp_path

    def _post_restore(self, client, zip_bytes: bytes, filename: str = "backup.zip"):
        return client.post(
            "/restore",
            files={"file": (filename, io.BytesIO(zip_bytes), "application/zip")},
        )

    # --- validation ---

    def test_non_zip_filename_rejected(self, client):
        """Files without a .zip extension are rejected with 400."""
        response = client.post(
            "/restore",
            files={"file": ("backup.tar.gz", io.BytesIO(b"data"), "application/gzip")},
        )
        assert response.status_code == 400
        assert "ZIP" in response.json()["detail"]

    def test_corrupt_zip_rejected(self, client):
        """Bytes that are not a valid ZIP return 400."""
        response = self._post_restore(client, b"this is not a zip file")
        assert response.status_code == 400
        assert "Invalid ZIP" in response.json()["detail"]

    def test_zip_without_database_rejected(self, client):
        """A ZIP that has no data/documents.db entry is rejected with 400."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other_file.txt", "no database here")
        buf.seek(0)

        response = self._post_restore(client, buf.getvalue())
        assert response.status_code == 400
        assert "missing database" in response.json()["detail"]

    # --- happy path ---

    def test_valid_backup_returns_success(self, client):
        zip_bytes = _make_backup_zip()
        response = self._post_restore(client, zip_bytes)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Backup restored successfully"

    def test_stats_reflect_zip_contents(self, client):
        """pdfs_restored and thumbnails_restored match what was in the ZIP."""
        pdf = _make_pdf_bytes()
        zip_bytes = _make_backup_zip(
            pdfs={"doc1.pdf": pdf, "doc2.pdf": pdf},
            thumbs={"t1.jpg": b"JPG", "t2.jpg": b"JPG"},
        )
        response = self._post_restore(client, zip_bytes)
        assert response.status_code == 200
        stats = response.json()["stats"]
        assert stats["pdfs_restored"] == 2
        assert stats["thumbnails_restored"] == 2

    def test_metadata_echoed_in_response(self, client):
        """Backup metadata from the ZIP is returned in the response."""
        meta = {"backup_date": "2026-05-24T12:00:00", "version": "1.0", "system": "FileFolio"}
        zip_bytes = _make_backup_zip(metadata=meta)
        response = self._post_restore(client, zip_bytes)
        assert response.status_code == 200
        assert response.json()["metadata"]["system"] == "FileFolio"
        assert response.json()["metadata"]["version"] == "1.0"

    def test_backup_without_metadata_still_succeeds(self, client):
        """A ZIP with no backup_metadata.json is still accepted."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data/documents.db", b"SQLite")
        buf.seek(0)

        response = self._post_restore(client, buf.getvalue())
        assert response.status_code == 200

    # --- zip slip security ---

    def test_zip_slip_path_traversal_does_not_write_outside_base_dir(self, client):
        """
        A ZIP entry that starts with 'uploads/' but uses '../' to escape the
        extraction root must NOT result in a file being written outside BASE_DIR.

        This guards against the classic zip slip attack:
            uploads/../../../tmp/evil.pdf
        which, if not mitigated, would resolve to /tmp/evil.pdf after extraction.
        """
        evil_filename = "zipslip_filefolio_sentinel.pdf"
        evil_entry = f"uploads/../../../tmp/{evil_filename}"
        evil_target = Path("/tmp") / evil_filename

        # Guarantee a clean slate before the test.
        evil_target.unlink(missing_ok=True)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data/documents.db", b"SQLite")
            zf.writestr(evil_entry, b"malicious payload")
            zf.writestr("backup_metadata.json", json.dumps({}))
        buf.seek(0)

        self._post_restore(client, buf.getvalue())

        assert not evil_target.exists(), (
            "Zip slip vulnerability: path traversal entry was extracted outside BASE_DIR. "
            f"File found at {evil_target}"
        )
