"""
HTTP client for a running FileFolio instance.

Every call goes through the FastAPI backend's HTTP API -- never the database
or storage layer directly -- so storage layout and validation stay in one
place. Both entry points sit on top of this module: backend/mcp_server.py
(MCP tools, runs in venv-mcp/) and backend/cli.py (command line, runs in the
normal venv/). Nothing here imports the `mcp` SDK, so the CLI does not need
it installed.
"""

import os
from pathlib import Path
from typing import Optional

import httpx

FILEFOLIO_URL = os.environ.get("FILEFOLIO_URL", "http://127.0.0.1:8000")

# Mirrors ValidCategory in backend/main.py. Kept here so an invalid category is
# rejected with a readable message instead of a bare HTTP 422 from FastAPI.
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


def _make_client(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=FILEFOLIO_URL, timeout=timeout)


def _connection_error() -> RuntimeError:
    return RuntimeError(f"FileFolio not running at {FILEFOLIO_URL}")


def _timeout_error() -> RuntimeError:
    return RuntimeError(
        f"FileFolio at {FILEFOLIO_URL} did not respond in time -- a large or "
        "scanned PDF may still be processing"
    )


def _api_error(resp: httpx.Response) -> RuntimeError:
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    return RuntimeError(f"FileFolio API error ({resp.status_code}): {detail}")


async def search(
    query: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """Search documents by content/filename, category, tags, and date range."""
    params = {}
    if query:
        params["search"] = query
    if category:
        params["category"] = category
    if tags:
        params["tags"] = tags
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to

    async with _make_client() as client:
        try:
            resp = await client.get("/documents", params=params)
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()

    if resp.status_code != 200:
        raise _api_error(resp)

    return [
        {
            "id": d["id"],
            "filename": d.get("auto_filename") or d["original_filename"],
            "category": d.get("category"),
            "tags": d.get("tags", []),
            "upload_date": d.get("upload_date"),
            "snippet": d.get("preview", ""),
        }
        for d in resp.json()
    ]


async def get_document(doc_id: int) -> dict:
    """Get full metadata and text preview for a single document."""
    async with _make_client() as client:
        try:
            resp = await client.get(f"/documents/{doc_id}")
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()

    if resp.status_code == 404:
        raise RuntimeError(f"Document {doc_id} not found")
    if resp.status_code != 200:
        raise _api_error(resp)

    return resp.json()


async def download(doc_id: int, dest_path: str) -> str:
    """Download a document's PDF to a local file path."""
    dest = Path(dest_path)
    if not dest.parent.is_dir():
        raise RuntimeError(f"Destination directory does not exist: {dest.parent}")

    async with _make_client() as client:
        try:
            resp = await client.get(f"/download/{doc_id}")
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()

    if resp.status_code == 404:
        raise RuntimeError(f"Document {doc_id} not found")
    if resp.status_code != 200:
        raise _api_error(resp)

    dest.write_bytes(resp.content)
    return str(dest)


async def upload(file_path: str) -> dict:
    """Upload a local PDF for AI tagging and categorization."""
    src = Path(file_path)
    if not src.is_file():
        raise RuntimeError(f"File not found: {file_path}")
    if src.suffix.lower() != ".pdf":
        raise RuntimeError(f"Not a PDF file: {file_path}")

    # OCR + local LLM tagging on the backend routinely takes well over the
    # default 30s timeout for a multi-page or scanned PDF, so give this
    # specific call a much longer read timeout than the others.
    async with _make_client(timeout=300.0) as client:
        try:
            with src.open("rb") as f:
                resp = await client.post(
                    "/upload",
                    files={"file": (src.name, f, "application/pdf")},
                )
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()

    if resp.status_code != 200:
        raise _api_error(resp)

    return resp.json()


async def update(
    doc_id: int,
    filename: Optional[str] = None,
    tags: Optional[list[str]] = None,
    category: Optional[str] = None,
) -> dict:
    """Update a document's filename, tags, or category and return it."""
    payload: dict = {}
    if filename is not None:
        payload["auto_filename"] = filename
    if tags is not None:
        payload["tags"] = tags
    if category is not None:
        if category not in VALID_CATEGORIES:
            raise RuntimeError(
                f"Invalid category '{category}'. Valid categories: "
                + ", ".join(VALID_CATEGORIES)
            )
        payload["category"] = category

    if not payload:
        raise RuntimeError("Nothing to update: pass filename, tags, or category")

    async with _make_client() as client:
        try:
            resp = await client.put(f"/document/{doc_id}", json=payload)
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()

        if resp.status_code == 404:
            raise RuntimeError(f"Document {doc_id} not found")
        if resp.status_code != 200:
            raise _api_error(resp)

        # The update endpoint only returns {"success": true}, so re-read the
        # document to hand back the state the caller actually cares about.
        try:
            fetched = await client.get(f"/documents/{doc_id}")
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()

    if fetched.status_code != 200:
        raise _api_error(fetched)

    return fetched.json()


# --- Page-range parsing --------------------------------------------------------
#
# Copied from backend/pdf_ops.py, NOT imported: pdf_ops pulls in `pypdf`, which
# is absent from venv-mcp/ (httpx + mcp SDK only), and mcp_server.py imports this
# module. The only change is that `page_count` is optional here -- the server
# still does the authoritative bounds check; this is a fast client-side reject.


def parse_page_ranges(spec: str, page_count: Optional[int] = None) -> list[list[int]]:
    """Parse a print-dialog page spec into comma groups of 1-indexed pages.

    Grammar: ``1-3,5,8-`` -- 1-indexed, inclusive, ``N-`` meaning "N to the last
    page". When ``page_count`` is None the upper-bound check is skipped and an
    open-ended ``N-`` range raises ValueError (there is no last page to resolve).
    Raises ValueError on anything malformed.
    """
    if page_count is not None and page_count < 1:
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
            start_s, _sep, end_s = token.partition("-")
            start_s, end_s = start_s.strip(), end_s.strip()
            if not start_s:
                raise ValueError(f"range needs a start page: {token!r}")
            start = _one_based(start_s, page_count)
            if end_s == "":
                if page_count is None:
                    raise ValueError("open-ended range needs a page count")
                end = page_count
            else:
                end = _one_based(end_s, page_count)
            if end < start:
                raise ValueError(f"range end before start: {token!r}")
            groups.append(list(range(start, end + 1)))
        else:
            groups.append([_one_based(token, page_count)])
    return groups


def _one_based(value: str, page_count: Optional[int] = None) -> int:
    if not value.isdigit():
        raise ValueError(f"not a page number: {value!r}")
    page = int(value)
    if page < 1:
        raise ValueError(f"page {page} is outside 1-{page_count or '?'}")
    if page_count is not None and page > page_count:
        raise ValueError(f"page {page} is outside 1-{page_count}")
    return page


# --- PDF workbench operations -------------------------------------------------


async def pdf_merge(doc_ids, *, download_to=None):
    """Merge documents into one. Files the result, or writes it to download_to."""
    payload = {"document_ids": list(doc_ids), "file": download_to is None}
    async with _make_client(timeout=120.0) as http:
        try:
            resp = await http.post("/pdf/merge", json=payload)
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()
    if resp.status_code == 404:
        raise RuntimeError("One of the documents was not found")
    if resp.status_code != 200:
        raise _api_error(resp)
    if download_to is None:
        return resp.json()
    Path(download_to).write_bytes(resp.content)
    return str(download_to)


async def pdf_split(doc_id, ranges, *, download_dir=None):
    """Split a document by page ranges. Files each part, or unzips them into
    download_dir and returns the written paths."""
    payload = {"document_id": doc_id, "ranges": ranges, "file": download_dir is None}
    async with _make_client(timeout=300.0) as http:
        try:
            resp = await http.post("/pdf/split", json=payload)
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()
    if resp.status_code == 404:
        raise RuntimeError(f"Document {doc_id} not found")
    if resp.status_code != 200:
        raise _api_error(resp)
    if download_dir is None:
        return resp.json()
    import io as _io
    import zipfile as _zip

    written = []
    with _zip.ZipFile(_io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            target = Path(download_dir) / Path(name).name
            target.write_bytes(zf.read(name))
            written.append(str(target))
    return written


async def pdf_extract(doc_id, pages, *, download_to=None):
    """Extract the given pages into a new document, or write it to download_to."""
    payload = {"document_id": doc_id, "pages": pages, "file": download_to is None}
    async with _make_client(timeout=120.0) as http:
        try:
            resp = await http.post("/pdf/extract", json=payload)
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()
    if resp.status_code == 404:
        raise RuntimeError(f"Document {doc_id} not found")
    if resp.status_code != 200:
        raise _api_error(resp)
    if download_to is None:
        return resp.json()
    Path(download_to).write_bytes(resp.content)
    return str(download_to)


async def pdf_delete_pages(doc_id, pages, *, download_to=None):
    """Delete the given pages, filing the result or writing it to download_to."""
    payload = {"document_id": doc_id, "pages": pages, "file": download_to is None}
    async with _make_client(timeout=120.0) as http:
        try:
            resp = await http.post("/pdf/delete-pages", json=payload)
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()
    if resp.status_code == 404:
        raise RuntimeError(f"Document {doc_id} not found")
    if resp.status_code != 200:
        raise _api_error(resp)
    if download_to is None:
        return resp.json()
    Path(download_to).write_bytes(resp.content)
    return str(download_to)


async def pdf_rotate(doc_id, degrees, pages="all"):
    """Rotate pages by 90/180/270 degrees and return the ingested document."""
    payload = {"document_id": doc_id, "degrees": degrees, "pages": pages}
    async with _make_client() as http:
        try:
            resp = await http.post("/pdf/rotate", json=payload)
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()
    if resp.status_code == 404:
        raise RuntimeError(f"Document {doc_id} not found")
    if resp.status_code != 200:
        raise _api_error(resp)
    return resp.json()


async def pdf_ocr(doc_id):
    """Embed a searchable text layer and return the ingested document."""
    payload = {"document_id": doc_id}
    async with _make_client(timeout=300.0) as http:
        try:
            resp = await http.post("/pdf/ocr", json=payload)
        except httpx.ConnectError:
            raise _connection_error()
        except httpx.TimeoutException:
            raise _timeout_error()
    if resp.status_code == 404:
        raise RuntimeError(f"Document {doc_id} not found")
    if resp.status_code != 200:
        raise _api_error(resp)
    return resp.json()
