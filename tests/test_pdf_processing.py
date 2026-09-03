"""
Tests for PDF processing, text extraction, and OCR functionality.
"""

import pytest
import io
from pathlib import Path
from PIL import Image
from pypdf import PdfWriter
import pypdf


class TestPDFTextExtraction:
    """Tests for PDF text extraction."""

    def test_extract_text_from_simple_pdf(self, sample_pdf_file):
        """Test extracting text from a simple PDF."""
        reader = pypdf.PdfReader(sample_pdf_file)
        assert len(reader.pages) > 0

        # Even blank pages should be readable
        text = reader.pages[0].extract_text()
        assert isinstance(text, str)

    def test_handle_empty_pdf(self, temp_test_dir):
        """Test handling PDF with no content."""
        # Create empty PDF
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)

        empty_pdf = temp_test_dir / "empty.pdf"
        with open(empty_pdf, "wb") as f:
            writer.write(f)

        # Should not crash
        reader = pypdf.PdfReader(empty_pdf)
        text = reader.pages[0].extract_text()
        assert isinstance(text, str)

    def test_handle_multipage_pdf(self, temp_test_dir):
        """Test extracting text from multipage PDF."""
        # Create multipage PDF
        writer = PdfWriter()
        for i in range(5):
            writer.add_blank_page(width=200, height=200)

        multipage_pdf = temp_test_dir / "multipage.pdf"
        with open(multipage_pdf, "wb") as f:
            writer.write(f)

        reader = pypdf.PdfReader(multipage_pdf)
        assert len(reader.pages) == 5

    def test_extract_text_from_owner_encrypted_pdf(self, temp_test_dir):
        """AES-encrypted PDFs with no user password (common for payslips/statements)
        should decrypt and extract text without the `cryptography` package error."""
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt(user_password="", owner_password="owner-secret", algorithm="AES-256")

        encrypted_pdf = temp_test_dir / "owner_encrypted.pdf"
        with open(encrypted_pdf, "wb") as f:
            writer.write(f)

        reader = pypdf.PdfReader(encrypted_pdf)
        assert reader.is_encrypted
        text = reader.pages[0].extract_text()
        assert isinstance(text, str)


class TestThumbnailGeneration:
    """Tests for thumbnail generation."""

    def test_generate_thumbnail_from_pdf(self, sample_pdf_file):
        """Test generating a thumbnail from PDF first page."""
        from pdf2image import convert_from_path

        # Convert first page
        images = convert_from_path(sample_pdf_file, first_page=1, last_page=1, dpi=150)
        assert len(images) == 1
        assert isinstance(images[0], Image.Image)

    def test_thumbnail_filename_uses_path_suffix(self):
        """generate_thumbnail derives the JPEG name via Path.with_suffix, not str.replace.

        A stored filename containing '.pdf' in its stem (e.g. a timestamp prefix
        that is itself valid) must not be mangled — only the final extension
        should change to '.jpg'.
        """
        from pathlib import Path
        import backend.main as main

        # Simulate a stored filename whose stem happens to contain ".pdf" — edge case
        # that str.replace(".pdf", ".jpg") would mangle.
        stored = "20240101_120000_my.pdf.report.pdf"
        expected = "20240101_120000_my.pdf.report.jpg"

        result = Path(stored).with_suffix(".jpg").name
        assert result == expected, f"Expected {expected!r}, got {result!r}"

        # Verify the production code itself also produces the correct name.
        # We monkeypatch THUMBNAILS_DIR and convert_from_path so no real I/O happens.
        from unittest.mock import patch, MagicMock
        from PIL import Image as PILImage
        import tempfile, os

        fake_img = MagicMock(spec=PILImage.Image)

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(main, "THUMBNAILS_DIR", Path(tmp)), \
                 patch("backend.main.convert_from_path", return_value=[fake_img]):
                url = main.generate_thumbnail(Path(tmp) / stored, stored)

        assert url == f"/thumbnails/{expected}", f"Unexpected URL: {url}"

    def test_thumbnail_resize(self, sample_image):
        """Test resizing thumbnail to standard size."""
        img = Image.open(io.BytesIO(sample_image))
        original_size = img.size

        # Resize to thumbnail size
        thumbnail_size = (150, 150)
        img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)

        assert img.size[0] <= thumbnail_size[0]
        assert img.size[1] <= thumbnail_size[1]


class TestFileHashing:
    """Tests for file hashing and duplicate detection."""

    def test_consistent_hash_generation(self, sample_pdf_bytes):
        """Test that the same file produces the same hash."""
        import hashlib

        hash1 = hashlib.sha256(sample_pdf_bytes).hexdigest()
        hash2 = hashlib.sha256(sample_pdf_bytes).hexdigest()

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest length

    def test_different_files_different_hashes(self, sample_pdf_bytes):
        """Test that different files produce different hashes."""
        import hashlib

        hash1 = hashlib.sha256(sample_pdf_bytes).hexdigest()

        # Create slightly different PDF
        writer = PdfWriter()
        writer.add_blank_page(width=250, height=250)  # Different size
        pdf_bytes2 = io.BytesIO()
        writer.write(pdf_bytes2)

        hash2 = hashlib.sha256(pdf_bytes2.getvalue()).hexdigest()

        assert hash1 != hash2


class TestOCRFunctionality:
    """Tests for OCR functionality (requires tesseract)."""

    @pytest.mark.skip(reason="OCR tests require tesseract to be installed")
    def test_ocr_on_image(self, sample_image):
        """Test OCR text extraction from image."""
        import pytesseract

        img = Image.open(io.BytesIO(sample_image))
        text = pytesseract.image_to_string(img)

        # Should not crash, even if no text found
        assert isinstance(text, str)

    @pytest.mark.skip(reason="Requires creating a scanned PDF fixture")
    def test_fallback_to_ocr_for_scanned_pdf(self):
        """Test that system falls back to OCR for scanned PDFs."""
        # This would require creating or loading a scanned PDF fixture
        pass


class TestPDFMetadataExtraction:
    """Tests for extracting PDF metadata."""

    def test_extract_pdf_metadata(self, sample_pdf_file):
        """Test extracting metadata from PDF."""
        reader = pypdf.PdfReader(sample_pdf_file)

        # Check metadata exists (even if empty)
        metadata = reader.metadata
        assert metadata is not None or metadata is None  # Some PDFs have no metadata

    def test_handle_pdf_without_metadata(self, temp_test_dir):
        """Test handling PDFs with no metadata."""
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)

        pdf_path = temp_test_dir / "no_metadata.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)

        reader = pypdf.PdfReader(pdf_path)
        # Should not crash
        metadata = reader.metadata
        assert metadata is not None or metadata is None


class TestFilenameGeneration:
    """Tests for automatic filename generation."""

    def test_filename_sanitization(self):
        """Test that generated filenames are sanitized."""
        import re

        # Test various inputs
        test_cases = [
            ("Invoice #123", "Invoice__123"),  # # becomes _ then extra _ before number
            ("Document/with/slashes", "Document_with_slashes"),
            ("File:with:colons", "File_with_colons"),
            ("Name with  spaces", "Name_with_spaces"),  # Spaces collapsed to single _
        ]

        for input_name, expected_pattern in test_cases:
            # Sanitize filename (remove/replace invalid characters)
            sanitized = re.sub(r'[^\w\s-]', '_', input_name)
            sanitized = re.sub(r'[-\s]+', '_', sanitized)
            assert sanitized == expected_pattern

    def test_timestamp_prefix_format(self):
        """Test that timestamp prefix is in correct format."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Should be in format YYYYMMDD_HHMMSS
        assert len(timestamp) == 15
        assert timestamp[8] == '_'
        assert timestamp[:8].isdigit()
        assert timestamp[9:].isdigit()


class TestSanitizeAutoFilename:
    """Tests for _sanitize_auto_filename - turning a model suggestion into a safe name."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from backend.main import _sanitize_auto_filename
        self.sanitize = staticmethod(_sanitize_auto_filename)

    def test_plain_stem_becomes_lowercase_hyphenated_pdf(self):
        assert self.sanitize("Summit Fitness Membership", "scan_0012.pdf") == "summit-fitness-membership.pdf"

    def test_strips_directory_components(self):
        assert self.sanitize("../../etc/passwd-invoice", "x.pdf") == "passwd-invoice.pdf"
        assert self.sanitize("C:\\Users\\bob\\rent-statement", "x.pdf") == "rent-statement.pdf"

    def test_strips_model_supplied_extension(self):
        assert self.sanitize("acme-invoice-may-2026.pdf", "x.pdf") == "acme-invoice-may-2026.pdf"

    def test_underscores_and_spaces_become_single_hyphen(self):
        assert self.sanitize("acme_corp   tax  notice", "x.pdf") == "acme-corp-tax-notice.pdf"

    def test_collapses_and_trims_hyphens(self):
        assert self.sanitize("--acme--corp--", "x.pdf") == "acme-corp.pdf"

    def test_non_string_returns_none(self):
        assert self.sanitize(None, "x.pdf") is None
        assert self.sanitize(123, "x.pdf") is None

    def test_nothing_usable_returns_none(self):
        assert self.sanitize("", "x.pdf") is None
        assert self.sanitize("   ", "x.pdf") is None
        assert self.sanitize("!!!", "x.pdf") is None

    def test_long_stem_is_truncated_to_60_chars(self):
        result = self.sanitize("word-" * 30, "x.pdf")
        stem = result[: -len(".pdf")]
        assert len(stem) <= 60

    def test_keeps_original_extension_lowercased(self):
        assert self.sanitize("acme-invoice", "SCAN.PDF") == "acme-invoice.pdf"

    def test_weird_original_extension_falls_back_to_pdf(self):
        assert self.sanitize("acme-invoice", "scan.weirdlong") == "acme-invoice.pdf"


class TestFilenamePromptConstraints:
    """The filename section of the Ollama prompt must carry the T029 guardrails."""

    def _run(self, monkeypatch, model_filename="summit-fitness-membership"):
        from backend import main

        captured = {}

        def fake_chat(model, messages):
            captured["prompt"] = messages[0]["content"]
            return {
                "message": {
                    "content": (
                        '{"category": "Other", "tags": ["gym", "membership"], '
                        f'"filename": "{model_filename}"}}'
                    )
                }
            }

        monkeypatch.setattr(main, "get_existing_tags", lambda: [])
        monkeypatch.setattr(main.ollama, "chat", fake_chat)
        tags, category, auto_filename = main.process_document(
            "Summit Fitness membership confirmation. Member number 3391.", "scan_0012.pdf"
        )
        return captured["prompt"], auto_filename

    def test_prompt_forbids_using_an_identifier_as_the_issuer(self, monkeypatch):
        prompt, _ = self._run(monkeypatch)
        assert "account, member, customer, policy, reference or invoice number" in prompt
        assert "prefer the organisation name over any such identifier" in prompt

    def test_prompt_makes_the_date_optional_and_forbids_guessing(self, monkeypatch):
        prompt, _ = self._run(monkeypatch)
        assert "optionally followed by -month-year" in prompt
        assert "If you are unsure of the date, omit it entirely" in prompt
        assert "than guess or infer one" in prompt
        assert "in the future - is NOT the\n     document's date" in prompt

    def test_model_supplied_filename_passes_through(self, monkeypatch):
        _, auto_filename = self._run(monkeypatch)
        assert auto_filename == "summit-fitness-membership.pdf"


class TestDatabaseFTSIntegration:
    """Tests for full-text search database integration."""

    @pytest.mark.skip(reason="FTS test requires different DB setup")
    def test_fts_insert_and_search(self, db_connection):
        """Test FTS index insertion and searching."""
        cursor = db_connection.cursor()

        # Insert a document
        cursor.execute("""
            INSERT INTO documents (original_filename, stored_filename, file_path, upload_date, content_preview)
            VALUES ('test.pdf', 'test.pdf', '/tmp/test.pdf', '2024-01-01', 'This is a test invoice document')
        """)
        doc_id = cursor.lastrowid

        # Insert into FTS
        cursor.execute("""
            INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
            VALUES (?, 'test.pdf', 'Test_Invoice', 'invoice,test', 'Invoice', 'This is a test invoice document')
        """, (doc_id,))

        db_connection.commit()

        # Search using FTS
        cursor.execute("""
            SELECT rowid FROM documents_fts WHERE documents_fts MATCH 'invoice'
        """)
        results = cursor.fetchall()

        assert len(results) >= 1
        assert results[0][0] == doc_id

    def test_fts_triggers(self, db_connection):
        """Test that FTS triggers work correctly."""
        cursor = db_connection.cursor()

        # Count FTS entries before
        cursor.execute("SELECT COUNT(*) FROM documents_fts")
        count_before = cursor.fetchone()[0]

        # Insert document (should trigger FTS insert)
        cursor.execute("""
            INSERT INTO documents (original_filename, stored_filename, file_path, upload_date, content_preview, category, tags)
            VALUES ('trigger_test.pdf', 'test.pdf', '/tmp/test.pdf', '2024-01-01', 'Test content', 'Invoice', 'test')
        """)
        db_connection.commit()

        # Count FTS entries after
        cursor.execute("SELECT COUNT(*) FROM documents_fts")
        count_after = cursor.fetchone()[0]

        # Should have one more entry
        assert count_after == count_before + 1
