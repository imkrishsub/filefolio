"""Where a stored PDF lives on disk.

Layout: ``<upload_dir>/<Category>/<Year>/<stored_filename>``

Every function takes ``upload_dir`` explicitly rather than reading a module global,
so callers (the app, the sync service, tests) stay in control of the location.
"""

from __future__ import annotations

import errno
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# The single source of truth for the category set. backend.main mirrors it as the
# ValidCategory Literal (a Literal cannot be built from this tuple without losing
# static checking); test_storage_categories_match_the_api_contract guards the two
# against drift. A value outside this set is filed under FALLBACK_CATEGORY rather
# than creating an unexpected directory.
VALID_CATEGORIES = (
    "Invoice",
    "Receipt",
    "Contract",
    "Letter",
    "Report",
    "Form",
    "Statement",
    "Legal",
    "Medical",
    "Tax",
    "Insurance",
    "Other",
)

FALLBACK_CATEGORY = "Other"

# Uploads land here while their category is still unknown. Inside upload_dir so the
# subsequent move is a same-filesystem rename.
STAGING_DIRNAME = ".staging"


def staging_dir(upload_dir: Path) -> Path:
    """Directory holding uploads that have not been categorised yet."""
    return Path(upload_dir) / STAGING_DIRNAME


def category_folder(category) -> str:
    """Folder name for a category, falling back to 'Other' for unknown values."""
    if isinstance(category, str) and category.strip() in VALID_CATEGORIES:
        return category.strip()
    return FALLBACK_CATEGORY


def year_folder(upload_date) -> str:
    """Four-digit year for an upload date, falling back to the current year."""
    if isinstance(upload_date, datetime):
        return str(upload_date.year)
    if isinstance(upload_date, str) and upload_date.strip():
        try:
            return str(datetime.fromisoformat(upload_date.strip()).year)
        except ValueError:
            pass
    return str(datetime.now().year)


def relative_path_for(category, upload_date, stored_filename) -> Path:
    """Path of a document relative to the upload directory."""
    return (
        Path(category_folder(category))
        / year_folder(upload_date)
        / Path(str(stored_filename).replace("\\", "/")).name
    )


def resolve(file_path: str, upload_dir: Path) -> Path:
    """Absolute path of a stored document.

    Accepts both the relative form written today and the absolute form written before
    the category folders existed, so a row that migration skipped still resolves --
    but an absolute value is only accepted when it resolves inside ``upload_dir``.

    Containment is enforced on both forms because the stored value is not trusted
    input: a restored third-party backup can carry any file_path it likes.

    Raises:
        ValueError: if the value escapes ``upload_dir`` once resolved.
    """
    upload_dir = Path(upload_dir)
    candidate = Path(str(file_path))
    destination = candidate if candidate.is_absolute() else upload_dir / candidate
    if not destination.resolve().is_relative_to(upload_dir.resolve()):
        raise ValueError(f"Stored path escapes the upload directory: {file_path!r}")
    return destination


def _reserve_destination(destination: Path) -> Path:
    """Atomically claim the first free name at or next to ``destination``.

    Tries ``name.pdf``, ``name_1.pdf``, ``name_2.pdf``, ... using an exclusive create
    (``O_CREAT | O_EXCL``) for each candidate, so two concurrent callers computing the
    same candidate cannot both observe it as free: only one ``os.open`` call succeeds
    per name, the other raises ``FileExistsError`` and moves on to the next candidate.

    The returned path exists on disk as a zero-byte placeholder that reserves the name;
    the caller is responsible for moving the real content onto it (see
    ``_move_into_place``) and for removing the placeholder if that move fails.
    """
    counter = 0
    while True:
        candidate = (
            destination
            if counter == 0
            else destination.parent
            / f"{destination.stem}_{counter}{destination.suffix}"
        )
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            counter += 1
            continue
        os.close(fd)
        return candidate


def _move_into_place(source: Path, reserved: Path) -> None:
    """Move ``source`` onto the placeholder at ``reserved``, replacing it atomically.

    ``os.replace`` is the primary mechanism: it overwrites the placeholder in one
    atomic step. It raises ``OSError`` with errno ``EXDEV`` when ``source`` and
    ``reserved`` are on different filesystems, and only that case falls back to
    ``shutil.move``, which copies when a same-filesystem rename is not possible.
    Every other ``OSError`` (a missing source, a permission problem) propagates
    directly rather than being retried pointlessly through ``shutil.move``.

    If the move fails for any reason, the placeholder created by
    ``_reserve_destination`` is removed before the exception propagates, so a failed
    placement does not leave a zero-byte file squatting the name.
    """
    try:
        try:
            os.replace(str(source), str(reserved))
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            shutil.move(str(source), str(reserved))
    except Exception:
        if reserved.exists():
            reserved.unlink()
        raise


def place(
    staging_path: Path,
    upload_dir: Path,
    category,
    upload_date,
    stored_filename,
) -> tuple[Path, str]:
    """Move a staged upload into its category folder.

    Returns:
        The final absolute path and the final filename, which differs from
        ``stored_filename`` when the name had to be uniquified.
    """
    upload_dir = Path(upload_dir)
    destination = upload_dir / relative_path_for(category, upload_date, stored_filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    reserved = _reserve_destination(destination)
    _move_into_place(Path(staging_path), reserved)
    return reserved, reserved.name


def move_to_category(
    file_path: str, upload_dir: Path, new_category, upload_date
) -> str:
    """Move an already-stored document to a different category folder.

    The year is taken from ``upload_date`` so a document does not drift into the
    current year when it is edited.

    Returns:
        The new path relative to ``upload_dir``, POSIX-style.
    """
    upload_dir = Path(upload_dir)
    current = resolve(file_path, upload_dir)
    destination = upload_dir / relative_path_for(
        new_category, upload_date, current.name
    )
    if destination == current:
        return destination.relative_to(upload_dir).as_posix()
    destination.parent.mkdir(parents=True, exist_ok=True)
    reserved = _reserve_destination(destination)
    _move_into_place(current, reserved)
    return reserved.relative_to(upload_dir).as_posix()


def restore_to(current_path: str, upload_dir: Path, original_file_path: str) -> None:
    """Move a file back to an exact previously-recorded location.

    Used to undo a placement when a later step fails. Unlike move_to_category, the
    destination is the caller's recorded original path, not a recomputed one, so a
    filename that was uniquified on the way out is restored under its original name.

    Raises:
        OSError: if the file cannot be restored, including when the original path is
            no longer free.
    """
    upload_dir = Path(upload_dir)
    current = resolve(current_path, upload_dir)
    destination = resolve(original_file_path, upload_dir)
    if destination == current:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(destination), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise OSError(
            f"Cannot restore to {destination}: the original path is occupied"
        ) from exc
    os.close(fd)
    _move_into_place(current, destination)


def replace_file(
    current_relpath: str,
    upload_dir: Path,
    new_pdf: Path,
    *,
    keep_backup: bool = False,
) -> Path | None:
    """Swap the file a document row points at with ``new_pdf``, keeping the name.

    Sidesteps the live file to ``<name>.bak`` first so a failure can put it back.
    On success: if ``keep_backup``, returns the backup ``Path`` (the caller must
    delete or restore it); otherwise the backup is removed and ``None`` returned.
    ``new_pdf`` no longer exists after success. On failure the original is
    restored in place and the exception propagates.

    ``new_pdf`` must sit on the same filesystem as ``upload_dir`` (callers stage
    it inside ``upload_dir``) so the rename cannot raise ``EXDEV``.

    Raises:
        ValueError: if ``current_relpath`` escapes ``upload_dir`` or has no file.
        OSError: on a filesystem failure moving ``new_pdf`` into place.
    """
    upload_dir = Path(upload_dir)
    current = resolve(current_relpath, upload_dir)
    if not current.is_file():
        raise ValueError(f"no file to replace at {current_relpath!r}")

    backup = current.with_name(current.name + ".bak")
    os.replace(str(current), str(backup))
    try:
        os.replace(str(new_pdf), str(current))
    except OSError:
        os.replace(str(backup), str(current))
        raise
    if keep_backup:
        return backup
    backup.unlink(missing_ok=True)
    return None


def _has_content(path: Path) -> bool:
    """True if ``path`` is a file with a non-zero size.

    Used to vet the weaker ``_locate_source`` fallbacks. ``_reserve_destination``
    creates a real zero-byte placeholder before ``_move_into_place`` overwrites it, so
    a process killed between the two leaves an orphan that nothing collects. Adopting
    that orphan would leave the row pointing at an empty PDF while the real content
    sits unreferenced -- silent data loss reported as a successful migration.
    """
    return path.is_file() and path.stat().st_size > 0


def _locate_source(row, upload_dir: Path, expected_destination=None):
    """Find the file belonging to a document row, or None.

    Tries the stored path, then the flat legacy location, then this row's own
    ``expected_destination`` (which recovers a row whose move succeeded but whose
    UPDATE did not), and only then a recursive search by name.

    The recursive search is a last resort and deliberately weak evidence: it matches
    on filename alone, so it can return a file belonging to a *different* row that
    happens to share a stored_filename. Checking ``expected_destination`` first keeps
    an already-migrated row from being adopted by a later namesake. Zero-byte matches
    are rejected because ``_reserve_destination`` creates a zero-byte placeholder: a
    process killed between reserving and moving leaves one behind, and adopting it
    would point the row at an empty PDF while the real content sits unreferenced.
    """
    stored_path = row["file_path"]
    if stored_path:
        # Via resolve(), so a stored path escaping upload_dir is refused here too.
        # The migration physically moves what it finds, and a restored third-party
        # backup can name any file it likes: honouring one would import that file
        # into the library, after which it is served and deleted like any other.
        try:
            candidate = resolve(stored_path, upload_dir)
        except ValueError:
            candidate = None
        if candidate is not None and candidate.is_file():
            return candidate

    name = row["stored_filename"]
    if not name:
        return None

    name = Path(str(name).replace("\\", "/")).name
    flat = upload_dir / name
    if flat.is_file():
        return flat

    if expected_destination is not None and _has_content(expected_destination):
        return expected_destination

    for found in upload_dir.rglob(name):
        if _has_content(found) and (
            STAGING_DIRNAME not in found.relative_to(upload_dir).parts
        ):
            return found
    return None


def _migrate_row(conn, row, upload_dir: Path) -> bool:
    """Organise one document row. Returns True if the file was relocated."""
    stored_path = row["file_path"]
    if stored_path:
        candidate = Path(str(stored_path))
        # A relative file_path is only ever written by place(), move_to_category(),
        # or this migration, always in the organised Category/Year/name form -- so a
        # file existing at that relative path is a safe proxy for "already organised".
        if not candidate.is_absolute() and (upload_dir / candidate).is_file():
            return False  # already organised

    # Computed before the source is located so _locate_source can prefer this row's
    # own destination over a same-named file belonging to some other row.
    name = row["stored_filename"]
    expected_destination = (
        upload_dir / relative_path_for(row["category"], row["upload_date"], name)
        if name
        else None
    )

    source = _locate_source(row, upload_dir, expected_destination)
    if source is None:
        raise FileNotFoundError(
            f"no file on disk for document {row['id']} ({row['stored_filename']!r})"
        )

    destination = expected_destination or (
        upload_dir / relative_path_for(row["category"], row["upload_date"], source.name)
    )

    # moved is conjunctive with the row actually being relocated: a row recovered by
    # _locate_source that already sits at its correct destination (the move happened,
    # only the UPDATE did not) must not be double-moved or counted as moved.
    moved = destination != source
    if moved:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = _reserve_destination(destination)
        _move_into_place(source, destination)

    # stored_filename is deliberately left alone: thumbnail_path was derived from it.
    conn.execute(
        "UPDATE documents SET file_path = ? WHERE id = ?",
        (destination.relative_to(upload_dir).as_posix(), row["id"]),
    )
    return moved


def migrate_uploads_to_category_folders(connection_factory, upload_dir: Path) -> dict:
    """Move every stored PDF into its category/year folder. Safe to run repeatedly.

    Args:
        connection_factory: Zero-argument callable returning a sqlite3.Connection
            with ``row_factory = sqlite3.Row``.
        upload_dir: Root of the upload directory.

    Returns:
        Counts of 'moved' (relocated), 'skipped' (already organised) and 'failed'
        (no file found, or the move raised — the row is left untouched).
    """
    upload_dir = Path(upload_dir)
    stats = {"moved": 0, "skipped": 0, "failed": 0}

    conn = connection_factory()
    try:
        rows = conn.execute(
            "SELECT id, stored_filename, file_path, category, upload_date FROM documents"
        ).fetchall()
        for row in rows:
            try:
                moved = _migrate_row(conn, row, upload_dir)
            except Exception as exc:
                stats["failed"] += 1
                logger.warning("Could not organise document %s: %s", row["id"], exc)
                continue

            # Commit immediately, per row: if the process is interrupted partway
            # through a long pass, rows already processed stay recorded rather than
            # reverting to their pre-move file_path (which would force them onto the
            # expensive rglob recovery path again at next boot).
            conn.commit()
            if moved:
                stats["moved"] += 1
            else:
                stats["skipped"] += 1
    finally:
        conn.close()

    if stats["moved"] or stats["failed"]:
        logger.info(
            "Upload folder migration: %s moved, %s skipped, %s failed",
            stats["moved"],
            stats["skipped"],
            stats["failed"],
        )
    return stats
