"""Where a stored PDF lives on disk.

Layout: ``<upload_dir>/<Category>/<Year>/<stored_filename>``

Every function takes ``upload_dir`` explicitly rather than reading a module global,
so callers (the app, the sync service, tests) stay in control of the location.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Kept in step with ValidCategory in backend.main; a value outside this set is filed
# under FALLBACK_CATEGORY rather than creating an unexpected directory.
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
    the category folders existed, so a row that migration skipped still resolves.

    Raises:
        ValueError: if a relative value escapes ``upload_dir``.
    """
    upload_dir = Path(upload_dir)
    candidate = Path(str(file_path))
    if candidate.is_absolute():
        return candidate
    destination = upload_dir / candidate
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
            else destination.parent / f"{destination.stem}_{counter}{destination.suffix}"
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
    atomic step. It raises ``OSError`` when ``source`` and ``reserved`` are on
    different filesystems (errno ``EXDEV``), in which case ``shutil.move`` is used
    instead, which falls back to a copy when a same-filesystem rename is not possible.

    If the move fails for any reason, the placeholder created by
    ``_reserve_destination`` is removed before the exception propagates, so a failed
    placement does not leave a zero-byte file squatting the name.
    """
    try:
        try:
            os.replace(str(source), str(reserved))
        except OSError:
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


def move_to_category(file_path: str, upload_dir: Path, new_category, upload_date) -> str:
    """Move an already-stored document to a different category folder.

    The year is taken from ``upload_date`` so a document does not drift into the
    current year when it is edited.

    Returns:
        The new path relative to ``upload_dir``, POSIX-style.
    """
    upload_dir = Path(upload_dir)
    current = resolve(file_path, upload_dir)
    destination = upload_dir / relative_path_for(new_category, upload_date, current.name)
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


def _locate_source(row, upload_dir: Path):
    """Find the file belonging to a document row, or None.

    Tries the stored path, then the flat legacy location, then a recursive search by
    name (which recovers a row whose move succeeded but whose UPDATE did not).
    """
    stored_path = row["file_path"]
    if stored_path:
        candidate = Path(str(stored_path))
        if not candidate.is_absolute():
            candidate = upload_dir / candidate
        if candidate.is_file():
            return candidate

    name = row["stored_filename"]
    if not name:
        return None

    name = Path(str(name).replace("\\", "/")).name
    flat = upload_dir / name
    if flat.is_file():
        return flat

    for found in upload_dir.rglob(name):
        if found.is_file() and STAGING_DIRNAME not in found.relative_to(upload_dir).parts:
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

    source = _locate_source(row, upload_dir)
    if source is None:
        raise FileNotFoundError(
            f"no file on disk for document {row['id']} ({row['stored_filename']!r})"
        )

    destination = upload_dir / relative_path_for(
        row["category"], row["upload_date"], row["stored_filename"] or source.name
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
