"""Pure PDF operations for the FileFolio workbench.

No database, no FastAPI, no knowledge of where documents are stored. Every
function works on caller-supplied paths, so each is unit-testable on its own.
Callers (backend/main.py) own staging, atomic moves, and re-ingestion.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter

_ROTATIONS = (90, 180, 270)


def page_count(source: Path) -> int:
    return len(PdfReader(str(source)).pages)


def parse_page_ranges(spec: str, page_count: int) -> list[list[int]]:
    """Parse a print-dialog page spec into comma groups of 1-indexed pages.

    Grammar: ``1-3,5,8-`` — 1-indexed, inclusive, ``N-`` meaning "N to the last
    page". Raises ValueError on anything malformed or out of bounds.
    """
    if page_count < 1:
        raise ValueError("document has no pages")
    text = (spec or "").strip()
    if not text:
        raise ValueError("no pages given")

    groups: list[list[int]] = []
    for raw_group in text.split(","):
        token = raw_group.strip()
        if not token:
            raise ValueError(f"empty range in {spec!r}")
        if "-" in token:
            start_s, sep, end_s = token.partition("-")
            start_s, end_s = start_s.strip(), end_s.strip()
            if not start_s:
                raise ValueError(f"range needs a start page: {token!r}")
            start = _one_based(start_s, page_count)
            end = page_count if end_s == "" else _one_based(end_s, page_count)
            if end < start:
                raise ValueError(f"range end before start: {token!r}")
            groups.append(list(range(start, end + 1)))
        else:
            groups.append([_one_based(token, page_count)])
    return groups


def _one_based(value: str, page_count: int) -> int:
    if not value.isdigit():
        raise ValueError(f"not a page number: {value!r}")
    page = int(value)
    if page < 1 or page > page_count:
        raise ValueError(f"page {page} is outside 1-{page_count}")
    return page


def merge(sources: list[Path], dest: Path) -> None:
    if len(sources) < 2:
        raise ValueError("merge needs at least two documents")
    writer = PdfWriter()
    for src in sources:
        for page in PdfReader(str(src)).pages:
            writer.add_page(page)
    with open(dest, "wb") as fh:
        writer.write(fh)


def split(source: Path, groups: list[list[int]], out_dir: Path) -> list[Path]:
    reader = PdfReader(str(source))
    written: list[Path] = []
    stem = Path(source).stem
    for index, group in enumerate(groups, start=1):
        writer = PdfWriter()
        for page in group:
            writer.add_page(reader.pages[page - 1])
        target = Path(out_dir) / f"{stem}_part{index}.pdf"
        with open(target, "wb") as fh:
            writer.write(fh)
        written.append(target)
    return written


def extract_pages(source: Path, pages: list[int], dest: Path) -> None:
    reader = PdfReader(str(source))
    writer = PdfWriter()
    for page in pages:
        writer.add_page(reader.pages[page - 1])
    with open(dest, "wb") as fh:
        writer.write(fh)


def delete_pages(source: Path, pages: list[int], dest: Path) -> None:
    reader = PdfReader(str(source))
    keep = [n for n in range(1, len(reader.pages) + 1) if n not in set(pages)]
    if not keep:
        raise ValueError("that would delete every page")
    writer = PdfWriter()
    for page in keep:
        writer.add_page(reader.pages[page - 1])
    with open(dest, "wb") as fh:
        writer.write(fh)


def rotate(source: Path, dest: Path, degrees: int, pages: list[int] | None = None) -> None:
    if degrees not in _ROTATIONS:
        raise ValueError(f"rotation must be one of {_ROTATIONS}")
    reader = PdfReader(str(source))
    target = set(pages) if pages else set(range(1, len(reader.pages) + 1))
    writer = PdfWriter()
    for number, page in enumerate(reader.pages, start=1):
        if number in target:
            page.rotate(degrees)
        writer.add_page(page)
    with open(dest, "wb") as fh:
        writer.write(fh)


def ocr(source: Path, dest: Path) -> None:
    """Embed a searchable text layer with ocrmypdf. No-op on pages already text."""
    if shutil.which("ocrmypdf") is None:
        raise RuntimeError(
            "ocrmypdf is not installed. Install it (and ghostscript) to use OCR."
        )
    result = subprocess.run(
        ["ocrmypdf", "--skip-text", "--quiet", str(source), str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ocrmypdf failed: {result.stderr.strip() or result.stdout.strip()}")
