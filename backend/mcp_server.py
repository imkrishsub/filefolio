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
from typing import Optional

import httpx
from mcp.server import MCPServer

FILEFOLIO_URL = os.environ.get("FILEFOLIO_URL", "http://127.0.0.1:8000")

server = MCPServer("filefolio")


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=FILEFOLIO_URL, timeout=30.0)


def _connection_error() -> RuntimeError:
    return RuntimeError(f"FileFolio not running at {FILEFOLIO_URL}")


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

    if resp.status_code == 404:
        raise RuntimeError(f"Document {doc_id} not found")
    if resp.status_code != 200:
        raise _api_error(resp)

    return resp.json()


if __name__ == "__main__":
    server.run()
