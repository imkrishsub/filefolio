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
