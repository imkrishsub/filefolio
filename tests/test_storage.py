"""Unit tests for backend.storage — path rules, no HTTP and no app fixtures."""

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
