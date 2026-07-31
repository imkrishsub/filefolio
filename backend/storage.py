"""Where a stored PDF lives on disk.

Layout: ``<upload_dir>/<Category>/<Year>/<stored_filename>``

Every function takes ``upload_dir`` explicitly rather than reading a module global,
so callers (the app, the sync service, tests) stay in control of the location.
"""

from __future__ import annotations

import logging
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
