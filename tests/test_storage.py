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
