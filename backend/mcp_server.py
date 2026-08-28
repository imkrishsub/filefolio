"""
FileFolio MCP server.

Exposes a running FileFolio instance's documents to MCP clients (e.g. other
Claude Code sessions) over stdio. Talks to the FastAPI backend exclusively
over its HTTP API -- never touches the database or storage layer directly.
Runs in its own virtual environment (see requirements-mcp.txt): the `mcp`
SDK requires anyio/starlette versions incompatible with the backend's
pinned fastapi.
"""

import os
from pathlib import Path
from typing import Optional

import httpx
from mcp.server import MCPServer

FILEFOLIO_URL = os.environ.get("FILEFOLIO_URL", "http://127.0.0.1:8000")

server = MCPServer("filefolio")


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


@server.tool()
async def filefolio_search(
    query: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """Search FileFolio documents by content/filename, category, tags, and date range."""
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


@server.tool()
async def filefolio_get_document(doc_id: int) -> dict:
    """Get full metadata and text preview for a single FileFolio document."""
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


@server.tool()
async def filefolio_download(doc_id: int, dest_path: str) -> str:
    """Download a FileFolio document's PDF to a local file path."""
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


@server.tool()
async def filefolio_upload(file_path: str) -> dict:
    """Upload a local PDF file into FileFolio for AI tagging and categorization."""
    src = Path(file_path)
    if not src.is_file():
        raise RuntimeError(f"File not found: {file_path}")
    if src.suffix.lower() != ".pdf":
        raise RuntimeError(f"Not a PDF file: {file_path}")

    # OCR + local LLM tagging on the backend routinely takes well over the
    # default 30s timeout for a multi-page or scanned PDF, so give this
    # specific tool a much longer read timeout than the other three.
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


@server.tool()
async def filefolio_update(
    doc_id: int,
    filename: Optional[str] = None,
    tags: Optional[list[str]] = None,
    category: Optional[str] = None,
) -> dict:
    """Update a FileFolio document's filename, tags, or category.

    Only the fields you pass are changed. Changing the category also moves the
    stored PDF into that category's folder. Returns the updated document.
    """
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


if __name__ == "__main__":
    server.run()
