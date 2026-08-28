"""
FileFolio MCP server.

Exposes a running FileFolio instance's documents to MCP clients (e.g. other
Claude Code sessions) over stdio. All HTTP work lives in backend/client.py;
this module is only the MCP surface -- the docstrings below are what an MCP
client sees as each tool's description.

Runs in its own virtual environment (see requirements-mcp.txt): the `mcp`
SDK requires anyio/starlette versions incompatible with the backend's
pinned fastapi. backend/cli.py wraps the same client functions without
needing the SDK.
"""

from typing import Optional

from mcp.server import MCPServer

# Match the import idiom in backend/main.py: works both as `python
# backend/mcp_server.py` (the README's registration command, where sys.path[0]
# is backend/) and as an imported `backend.mcp_server` module.
try:
    from backend import client
except ModuleNotFoundError:
    import client

server = MCPServer("filefolio")


@server.tool()
async def filefolio_search(
    query: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """Search FileFolio documents by content/filename, category, tags, and date range."""
    return await client.search(
        query=query,
        category=category,
        tags=tags,
        date_from=date_from,
        date_to=date_to,
    )


@server.tool()
async def filefolio_get_document(doc_id: int) -> dict:
    """Get full metadata and text preview for a single FileFolio document."""
    return await client.get_document(doc_id)


@server.tool()
async def filefolio_download(doc_id: int, dest_path: str) -> str:
    """Download a FileFolio document's PDF to a local file path."""
    return await client.download(doc_id, dest_path)


@server.tool()
async def filefolio_upload(file_path: str) -> dict:
    """Upload a local PDF file into FileFolio for AI tagging and categorization."""
    return await client.upload(file_path)


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
    return await client.update(doc_id, filename=filename, tags=tags, category=category)


if __name__ == "__main__":
    server.run()
