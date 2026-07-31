"""Unit tests for backend.storage — path rules, no HTTP and no app fixtures."""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from backend import storage


class TestCategoryFolder:
    def test_valid_category_is_used_as_is(self):
        assert storage.category_folder("Invoice") == "Invoice"

    def test_none_falls_back_to_other(self):
        assert storage.category_folder(None) == "Other"

    def test_empty_string_falls_back_to_other(self):
        assert storage.category_folder("   ") == "Other"

    def test_unknown_legacy_value_falls_back_to_other(self):
        assert storage.category_folder("Rechnung") == "Other"

    def test_surrounding_whitespace_is_stripped(self):
        assert storage.category_folder(" Receipt ") == "Receipt"


class TestYearFolder:
    def test_iso_timestamp(self):
        assert storage.year_folder("2026-07-31T10:15:00") == "2026"

    def test_datetime_object(self):
        assert storage.year_folder(datetime(2025, 1, 2)) == "2025"

    def test_unparseable_value_falls_back_to_current_year(self):
        assert storage.year_folder("not a date") == str(datetime.now().year)

    def test_none_falls_back_to_current_year(self):
        assert storage.year_folder(None) == str(datetime.now().year)


class TestRelativePathFor:
    def test_builds_category_year_filename(self):
        rel = storage.relative_path_for("Invoice", "2026-07-31T10:15:00", "20260731_101500_bill.pdf")
        assert rel == Path("Invoice") / "2026" / "20260731_101500_bill.pdf"

    def test_strips_directory_components_from_the_filename(self):
        rel = storage.relative_path_for("Invoice", "2026-07-31T10:15:00", "evil/../../bill.pdf")
        assert rel == Path("Invoice") / "2026" / "bill.pdf"


class TestResolve:
    def test_relative_value_is_joined_onto_upload_dir(self, tmp_path):
        assert storage.resolve("Invoice/2026/bill.pdf", tmp_path) == tmp_path / "Invoice" / "2026" / "bill.pdf"

    def test_legacy_absolute_value_is_returned_unchanged(self, tmp_path):
        legacy = tmp_path.parent / "elsewhere" / "old.pdf"
        assert storage.resolve(str(legacy), tmp_path) == legacy

    def test_traversal_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            storage.resolve("../../etc/passwd", tmp_path)


class TestStagingDir:
    def test_staging_lives_inside_the_upload_dir(self, tmp_path):
        assert storage.staging_dir(tmp_path) == tmp_path / ".staging"


class TestPlace:
    def test_moves_the_staged_file_into_category_and_year(self, tmp_path):
        staged = storage.staging_dir(tmp_path)
        staged.mkdir(parents=True)
        source = staged / "20260731_101500_bill.pdf"
        source.write_bytes(b"%PDF-1.4 test")

        final_path, final_name = storage.place(
            source, tmp_path, "Invoice", "2026-07-31T10:15:00", source.name
        )

        assert final_path == tmp_path / "Invoice" / "2026" / "20260731_101500_bill.pdf"
        assert final_name == "20260731_101500_bill.pdf"
        assert final_path.read_bytes() == b"%PDF-1.4 test"
        assert not source.exists()

    def test_uniquifies_when_the_destination_name_is_taken(self, tmp_path):
        existing = tmp_path / "Invoice" / "2026" / "20260731_101500_bill.pdf"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"%PDF-1.4 first")

        staged = storage.staging_dir(tmp_path)
        staged.mkdir(parents=True)
        source = staged / "20260731_101500_bill.pdf"
        source.write_bytes(b"%PDF-1.4 second")

        final_path, final_name = storage.place(
            source, tmp_path, "Invoice", "2026-07-31T10:15:00", source.name
        )

        assert final_name == "20260731_101500_bill_1.pdf"
        assert final_path.read_bytes() == b"%PDF-1.4 second"
        assert existing.read_bytes() == b"%PDF-1.4 first"

    def test_unknown_category_is_filed_under_other(self, tmp_path):
        staged = storage.staging_dir(tmp_path)
        staged.mkdir(parents=True)
        source = staged / "doc.pdf"
        source.write_bytes(b"%PDF-1.4")

        final_path, _ = storage.place(source, tmp_path, None, "2026-07-31T10:15:00", "doc.pdf")

        assert final_path == tmp_path / "Other" / "2026" / "doc.pdf"

    def test_reservation_prevents_overwriting_the_existing_file(self, tmp_path):
        existing = tmp_path / "Invoice" / "2026" / "20260731_101500_bill.pdf"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"%PDF-1.4 first")

        staged = storage.staging_dir(tmp_path)
        staged.mkdir(parents=True)
        source = staged / "20260731_101500_bill.pdf"
        source.write_bytes(b"%PDF-1.4 second")

        final_path, final_name = storage.place(
            source, tmp_path, "Invoice", "2026-07-31T10:15:00", source.name
        )

        assert final_name == "20260731_101500_bill_1.pdf"
        assert final_path.read_bytes() == b"%PDF-1.4 second"
        assert existing.read_bytes() == b"%PDF-1.4 first"

    def test_failed_move_does_not_leave_a_placeholder(self, tmp_path, monkeypatch):
        staged = storage.staging_dir(tmp_path)
        staged.mkdir(parents=True)
        source = staged / "doc.pdf"
        source.write_bytes(b"%PDF-1.4")

        def boom(*args, **kwargs):
            raise OSError("simulated failure")

        monkeypatch.setattr(storage.os, "replace", boom)
        monkeypatch.setattr(storage.shutil, "move", boom)

        with pytest.raises(OSError):
            storage.place(source, tmp_path, "Invoice", "2026-07-31T10:15:00", "doc.pdf")

        assert not (tmp_path / "Invoice" / "2026" / "doc.pdf").exists()


class TestMoveToCategory:
    def test_moves_to_the_new_category_keeping_the_original_year(self, tmp_path):
        current = tmp_path / "Invoice" / "2025" / "doc.pdf"
        current.parent.mkdir(parents=True)
        current.write_bytes(b"%PDF-1.4")

        new_rel = storage.move_to_category(
            "Invoice/2025/doc.pdf", tmp_path, "Receipt", "2025-11-02T09:00:00"
        )

        assert new_rel == "Receipt/2025/doc.pdf"
        assert (tmp_path / "Receipt" / "2025" / "doc.pdf").exists()
        assert not current.exists()

    def test_same_category_is_a_no_op(self, tmp_path):
        current = tmp_path / "Invoice" / "2025" / "doc.pdf"
        current.parent.mkdir(parents=True)
        current.write_bytes(b"%PDF-1.4")

        new_rel = storage.move_to_category(
            "Invoice/2025/doc.pdf", tmp_path, "Invoice", "2025-11-02T09:00:00"
        )

        assert new_rel == "Invoice/2025/doc.pdf"
        assert current.exists()

    def test_moves_a_legacy_absolute_path_into_the_structure(self, tmp_path):
        legacy = tmp_path / "doc.pdf"
        legacy.write_bytes(b"%PDF-1.4")

        new_rel = storage.move_to_category(
            str(legacy), tmp_path, "Tax", "2024-03-04T08:00:00"
        )

        assert new_rel == "Tax/2024/doc.pdf"
        assert (tmp_path / "Tax" / "2024" / "doc.pdf").exists()
        assert not legacy.exists()


def _migration_db(tmp_path):
    """Minimal documents table plus a factory returning fresh connections."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stored_filename TEXT,
            file_path TEXT,
            category TEXT,
            upload_date TEXT,
            thumbnail_path TEXT
        )
        """
    )
    conn.commit()
    conn.close()

    def factory():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    return db_path, factory


def _insert(factory, stored_filename, file_path, category, upload_date):
    conn = factory()
    conn.execute(
        "INSERT INTO documents (stored_filename, file_path, category, upload_date) VALUES (?, ?, ?, ?)",
        (stored_filename, file_path, category, upload_date),
    )
    conn.commit()
    conn.close()


def _file_paths(factory):
    conn = factory()
    rows = [row["file_path"] for row in conn.execute("SELECT file_path FROM documents ORDER BY id")]
    conn.close()
    return rows


class TestMigration:
    def test_moves_a_flat_absolute_row_into_category_and_year(self, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        flat = upload_dir / "20260731_101500_bill.pdf"
        flat.write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)
        _insert(factory, flat.name, str(flat), "Invoice", "2026-07-31T10:15:00")

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert stats == {"moved": 1, "skipped": 0, "failed": 0}
        assert _file_paths(factory) == ["Invoice/2026/20260731_101500_bill.pdf"]
        assert (upload_dir / "Invoice" / "2026" / "20260731_101500_bill.pdf").exists()
        assert not flat.exists()

    def test_is_idempotent(self, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        flat = upload_dir / "doc.pdf"
        flat.write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)
        _insert(factory, flat.name, str(flat), "Receipt", "2025-11-02T09:00:00")

        storage.migrate_uploads_to_category_folders(factory, upload_dir)
        second = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert second == {"moved": 0, "skipped": 1, "failed": 0}
        assert _file_paths(factory) == ["Receipt/2025/doc.pdf"]

    def test_recovers_a_row_whose_absolute_path_is_from_another_machine(self, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        flat = upload_dir / "restored.pdf"
        flat.write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)
        _insert(factory, "restored.pdf", "/old/machine/uploads/restored.pdf", "Tax", "2024-01-05T00:00:00")

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert stats == {"moved": 1, "skipped": 0, "failed": 0}
        assert _file_paths(factory) == ["Tax/2024/restored.pdf"]

    def test_row_with_no_file_on_disk_is_left_untouched(self, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()

        _, factory = _migration_db(tmp_path)
        _insert(factory, "gone.pdf", "/nowhere/gone.pdf", "Invoice", "2026-01-01T00:00:00")

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert stats == {"moved": 0, "skipped": 0, "failed": 1}
        assert _file_paths(factory) == ["/nowhere/gone.pdf"]

    def test_does_not_rename_stored_filename(self, tmp_path):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        flat = upload_dir / "doc.pdf"
        flat.write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)
        _insert(factory, "doc.pdf", str(flat), "Invoice", "2026-01-01T00:00:00")

        storage.migrate_uploads_to_category_folders(factory, upload_dir)

        conn = factory()
        stored = conn.execute("SELECT stored_filename FROM documents").fetchone()["stored_filename"]
        conn.close()
        assert stored == "doc.pdf"

    def test_ignores_files_still_in_staging(self, tmp_path):
        upload_dir = tmp_path / "uploads"
        staging = storage.staging_dir(upload_dir)
        staging.mkdir(parents=True)
        (staging / "half_written.pdf").write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert stats == {"moved": 0, "skipped": 0, "failed": 0}
        assert (staging / "half_written.pdf").exists()
