"""Unit tests for backend.storage — path rules, no HTTP and no app fixtures."""

import os
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

    def test_legacy_absolute_value_inside_the_upload_dir_is_returned_unchanged(
        self, tmp_path
    ):
        """The pre-migration form -- an absolute path into the upload directory --
        still resolves, so a row the migration skipped keeps working."""
        legacy = tmp_path / "old.pdf"
        assert storage.resolve(str(legacy), tmp_path) == legacy

    def test_absolute_value_outside_the_upload_dir_is_rejected(self, tmp_path):
        """A stored path is not trusted input: a restored third-party backup can
        carry any absolute file_path it likes, and honouring one outside the upload
        directory would let the migration move, serve and delete arbitrary files."""
        outside = tmp_path.parent / "elsewhere" / "old.pdf"
        with pytest.raises(ValueError):
            storage.resolve(str(outside), tmp_path)

    def test_traversal_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            storage.resolve("../../etc/passwd", tmp_path)

    def test_absolute_traversal_back_inside_is_accepted(self, tmp_path):
        """Containment is decided after resolution, not by string prefix."""
        inside = tmp_path / "Invoice" / ".." / "Invoice" / "2026" / "bill.pdf"
        assert storage.resolve(str(inside), tmp_path) == inside


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


class TestRestoreTo:
    def test_round_trips_a_move_that_had_to_uniquify(self, tmp_path):
        original = tmp_path / "Invoice" / "2026" / "doc.pdf"
        original.parent.mkdir(parents=True)
        original.write_bytes(b"%PDF-1.4 original")

        # Occupy the natural destination name so the forward move must uniquify.
        taken = tmp_path / "Receipt" / "2026" / "doc.pdf"
        taken.parent.mkdir(parents=True)
        taken.write_bytes(b"%PDF-1.4 someone else")

        new_rel = storage.move_to_category(
            "Invoice/2026/doc.pdf", tmp_path, "Receipt", "2026-01-01T00:00:00"
        )
        assert new_rel == "Receipt/2026/doc_1.pdf"
        assert not original.exists()

        storage.restore_to(new_rel, tmp_path, "Invoice/2026/doc.pdf")

        assert original.exists()
        assert original.read_bytes() == b"%PDF-1.4 original"
        assert not (tmp_path / new_rel).exists()
        # The file that was already occupying the uniquified name's sibling is
        # untouched.
        assert taken.read_bytes() == b"%PDF-1.4 someone else"

    def test_same_path_is_a_no_op(self, tmp_path):
        current = tmp_path / "Invoice" / "2026" / "doc.pdf"
        current.parent.mkdir(parents=True)
        current.write_bytes(b"%PDF-1.4")

        storage.restore_to("Invoice/2026/doc.pdf", tmp_path, "Invoice/2026/doc.pdf")

        assert current.exists()
        assert current.read_bytes() == b"%PDF-1.4"

    def test_raises_instead_of_relocating_when_original_path_is_occupied(self, tmp_path):
        current = tmp_path / "Receipt" / "2026" / "doc_1.pdf"
        current.parent.mkdir(parents=True)
        current.write_bytes(b"%PDF-1.4 current")

        occupied = tmp_path / "Invoice" / "2026" / "doc.pdf"
        occupied.parent.mkdir(parents=True)
        occupied.write_bytes(b"%PDF-1.4 occupant")

        with pytest.raises(OSError):
            storage.restore_to(
                "Receipt/2026/doc_1.pdf", tmp_path, "Invoice/2026/doc.pdf"
            )

        # Neither file moved: no silent relocation to a different name.
        assert current.exists()
        assert current.read_bytes() == b"%PDF-1.4 current"
        assert occupied.read_bytes() == b"%PDF-1.4 occupant"


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


def _pin_rglob_order(monkeypatch):
    """Make the recursive search in _locate_source return matches in sorted order.

    Real filesystem order is arbitrary, so a test that relies on a particular match
    coming back first is otherwise flaky in both directions. Pinning it makes the
    decoy deterministically the first match.
    """
    original_rglob = Path.rglob
    monkeypatch.setattr(
        Path,
        "rglob",
        lambda self, pattern: iter(sorted(original_rglob(self, pattern))),
    )


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
        """A document row whose only matching file lives under .staging/ must not be
        adopted by the recursive rglob search in _locate_source: it is left failed
        and untouched, not silently treated as found."""
        upload_dir = tmp_path / "uploads"
        staging = storage.staging_dir(upload_dir)
        staging.mkdir(parents=True)
        (staging / "half_written.pdf").write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)
        _insert(
            factory,
            "half_written.pdf",
            "/nowhere/half_written.pdf",
            "Invoice",
            "2026-01-01T00:00:00",
        )

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert stats == {"moved": 0, "skipped": 0, "failed": 1}
        assert _file_paths(factory) == ["/nowhere/half_written.pdf"]
        assert (staging / "half_written.pdf").exists()

    def test_recovers_a_row_via_recursive_search_when_the_move_succeeded_but_the_update_did_not(
        self, tmp_path
    ):
        """Exercises the rglob fallback branch in _locate_source specifically: the file
        already sits nested at <upload_dir>/Category/Year/name.pdf (not flat under
        upload_dir, so the earlier flat-location check in _locate_source cannot find
        it), while the row's file_path is still the stale pre-move value. This is the
        documented "move succeeded, UPDATE did not" recovery case."""
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        organised = upload_dir / "Invoice" / "2026" / "doc.pdf"
        organised.parent.mkdir(parents=True)
        organised.write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)
        _insert(
            factory, "doc.pdf", str(upload_dir / "doc.pdf"), "Invoice", "2026-01-01T00:00:00"
        )

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        # Recovered via rglob and the row corrected; but since the file already sat at
        # its final destination nothing was physically relocated, so this is "skipped"
        # under the conjunctive moved = relocated AND rewritten definition, not "moved".
        assert stats == {"moved": 0, "skipped": 1, "failed": 0}
        assert _file_paths(factory) == ["Invoice/2026/doc.pdf"]
        assert organised.exists()
        assert not (upload_dir / "Invoice" / "2026" / "doc_1.pdf").exists()

    def test_absolute_path_already_at_destination_is_skipped_and_normalised(self, tmp_path):
        """An absolute file_path that already points directly at the correctly
        organised destination (found by the first check in _locate_source, not the
        rglob fallback) must not be re-moved -- only normalised to the relative form
        -- and counted skipped rather than moved."""
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        organised = upload_dir / "Invoice" / "2026" / "doc.pdf"
        organised.parent.mkdir(parents=True)
        organised.write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)
        _insert(factory, "doc.pdf", str(organised), "Invoice", "2026-01-01T00:00:00")

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert stats == {"moved": 0, "skipped": 1, "failed": 0}
        assert _file_paths(factory) == ["Invoice/2026/doc.pdf"]
        assert organised.exists()

    def test_a_row_sharing_a_stored_filename_does_not_steal_another_rows_file(
        self, tmp_path, monkeypatch
    ):
        """Two rows can carry the same stored_filename (restored backups, a manual DB
        edit). The rglob fallback matches on filename alone, so without a check that
        the match belongs to *this* row, migrating the second row walks into the first
        row's already-migrated folder and takes its file -- reported as a clean
        success while the first row is left dangling."""
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()

        # Row 1: already organised, correctly recorded, and not to be touched.
        row_one = upload_dir / "Invoice" / "2026" / "doc.pdf"
        row_one.parent.mkdir(parents=True)
        row_one.write_bytes(b"%PDF-1.4 row one")

        # Row 2 shares the stored_filename. Its file already sits at its own
        # destination but the UPDATE never landed, so file_path is still stale and
        # the recursive fallback is what has to find it.
        row_two = upload_dir / "Receipt" / "2026" / "doc.pdf"
        row_two.parent.mkdir(parents=True)
        row_two.write_bytes(b"%PDF-1.4 row two")

        _, factory = _migration_db(tmp_path)
        _insert(
            factory, "doc.pdf", "Invoice/2026/doc.pdf", "Invoice", "2026-01-01T00:00:00"
        )
        _insert(
            factory, "doc.pdf", "/old/machine/doc.pdf", "Receipt", "2026-01-01T00:00:00"
        )

        # "Invoice/..." sorts before "Receipt/...", so row 1's file is always the
        # first recursive match. The point of the fix is that it must not matter.
        _pin_rglob_order(monkeypatch)

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert stats == {"moved": 0, "skipped": 2, "failed": 0}
        assert row_one.read_bytes() == b"%PDF-1.4 row one"
        assert row_two.read_bytes() == b"%PDF-1.4 row two"
        assert _file_paths(factory) == [
            "Invoice/2026/doc.pdf",
            "Receipt/2026/doc.pdf",
        ]

    def test_a_zero_byte_placeholder_is_not_adopted_as_the_source(
        self, tmp_path, monkeypatch
    ):
        """_reserve_destination creates a real zero-byte placeholder before
        _move_into_place overwrites it; a hard kill between the two leaves an orphan
        that nothing cleans up. The next pass must not adopt that empty file as the
        row's content while the real PDF sits elsewhere unreferenced."""
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()

        # The orphaned placeholder left behind by an interrupted previous pass.
        orphan = upload_dir / "Invoice" / "2026" / "doc.pdf"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"")

        # The real content, still flat, under a different name so the flat-location
        # check in _locate_source cannot find it and the rglob fallback is used.
        real = upload_dir / "Legal" / "doc.pdf"
        real.parent.mkdir(parents=True)
        real.write_bytes(b"%PDF-1.4 the real content")

        _, factory = _migration_db(tmp_path)
        _insert(
            factory, "doc.pdf", "/old/machine/doc.pdf", "Invoice", "2026-01-01T00:00:00"
        )

        # "Invoice/..." sorts before "Legal/...", so the empty placeholder is always
        # the first recursive match and has to be rejected on its own merits.
        _pin_rglob_order(monkeypatch)

        stats = storage.migrate_uploads_to_category_folders(factory, upload_dir)

        assert stats == {"moved": 1, "skipped": 0, "failed": 0}
        # The row points at the real content, not at the empty placeholder.
        final = upload_dir / _file_paths(factory)[0]
        assert final.read_bytes() == b"%PDF-1.4 the real content"
        assert not real.exists()

    def test_commits_progress_per_row_so_an_interruption_does_not_lose_it(
        self, tmp_path, monkeypatch
    ):
        """If the process is interrupted partway through a multi-row pass, rows already
        processed before the interruption must already be committed -- not rolled back
        by a single end-of-pass commit that never runs."""
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        first = upload_dir / "first.pdf"
        first.write_bytes(b"%PDF-1.4")
        second = upload_dir / "second.pdf"
        second.write_bytes(b"%PDF-1.4")

        _, factory = _migration_db(tmp_path)
        _insert(factory, first.name, str(first), "Invoice", "2026-01-01T00:00:00")
        _insert(factory, second.name, str(second), "Invoice", "2026-01-01T00:00:00")

        original_locate_source = storage._locate_source

        def interrupt_on_second_row(row, upload_dir, expected_destination=None):
            if row["stored_filename"] == "second.pdf":
                raise KeyboardInterrupt("simulated interruption")
            return original_locate_source(row, upload_dir, expected_destination)

        monkeypatch.setattr(storage, "_locate_source", interrupt_on_second_row)

        with pytest.raises(KeyboardInterrupt):
            storage.migrate_uploads_to_category_folders(factory, upload_dir)

        # First row's move and file_path update were committed before the interruption;
        # the second row was never reached, so its stale absolute file_path is intact.
        assert _file_paths(factory) == ["Invoice/2026/first.pdf", str(second)]
        assert (upload_dir / "Invoice" / "2026" / "first.pdf").exists()


class TestReplaceFile:
    def _seed(self, tmp_path):
        upload = tmp_path / "uploads"
        (upload / "Invoice" / "2026").mkdir(parents=True)
        current = upload / "Invoice" / "2026" / "doc.pdf"
        current.write_bytes(b"%PDF-old")
        return upload, current

    def test_swaps_contents_keeps_name(self, tmp_path):
        upload, current = self._seed(tmp_path)
        new_pdf = tmp_path / "new.pdf"
        new_pdf.write_bytes(b"%PDF-new")

        storage.replace_file("Invoice/2026/doc.pdf", upload, new_pdf)

        assert current.read_bytes() == b"%PDF-new"
        assert not new_pdf.exists()
        assert not (current.parent / "doc.pdf.bak").exists()

    def test_rejects_path_escape(self, tmp_path):
        upload, _ = self._seed(tmp_path)
        with pytest.raises(ValueError):
            storage.replace_file("../evil.pdf", upload, tmp_path / "new.pdf")

    def test_missing_current_file_raises(self, tmp_path):
        upload, current = self._seed(tmp_path)
        current.unlink()
        new_pdf = tmp_path / "new.pdf"
        new_pdf.write_bytes(b"%PDF-new")
        with pytest.raises(ValueError):
            storage.replace_file("Invoice/2026/doc.pdf", upload, new_pdf)

    def test_original_restored_when_swap_fails(self, tmp_path, monkeypatch):
        upload, current = self._seed(tmp_path)
        new_pdf = tmp_path / "new.pdf"
        new_pdf.write_bytes(b"%PDF-new")

        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:  # the new-file-into-place step
                raise OSError("boom")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", flaky_replace)

        with pytest.raises(OSError):
            storage.replace_file("Invoice/2026/doc.pdf", upload, new_pdf)

        assert current.read_bytes() == b"%PDF-old"
        assert not (current.parent / "doc.pdf.bak").exists()

    def test_keep_backup_returns_backup_path(self, tmp_path):
        upload, current = self._seed(tmp_path)
        new_pdf = tmp_path / "new.pdf"
        new_pdf.write_bytes(b"%PDF-new")

        backup = storage.replace_file("Invoice/2026/doc.pdf", upload, new_pdf, keep_backup=True)

        assert backup == current.parent / "doc.pdf.bak"
        assert backup.read_bytes() == b"%PDF-old"
        assert current.read_bytes() == b"%PDF-new"
        assert not new_pdf.exists()
