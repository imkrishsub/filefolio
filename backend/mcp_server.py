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


@server.tool()
async def filefolio_pdf_merge(document_ids: list[int]) -> dict:
    """Merge several FileFolio documents into one new filed document (AI-tagged)."""
    return await client.pdf_merge(document_ids)


@server.tool()
async def filefolio_pdf_split(document_id: int, ranges: str, dest_dir: Optional[str] = None) -> list:
    """Split one document by page ranges (e.g. "1-3,5,8-").

    Files each part as a new document, or writes them to dest_dir if given.
    """
    return await client.pdf_split(document_id, ranges, download_dir=dest_dir)


@server.tool()
async def filefolio_pdf_extract(document_id: int, pages: str, dest_path: Optional[str] = None) -> dict:
    """Keep only the given pages (e.g. "2-4") as a new filed document, or write to dest_path."""
    return await client.pdf_extract(document_id, pages, download_to=dest_path)


@server.tool()
async def filefolio_pdf_delete_pages(document_id: int, pages: str, dest_path: Optional[str] = None) -> dict:
    """Remove the given pages (e.g. "1,7") and file the rest as a new document, or write to dest_path."""
    return await client.pdf_delete_pages(document_id, pages, download_to=dest_path)


@server.tool()
async def filefolio_pdf_rotate(document_id: int, degrees: int, pages: str = "all") -> dict:
    """Rotate pages by 90, 180 or 270 degrees. Edits the document in place; keeps its id and metadata."""
    return await client.pdf_rotate(document_id, degrees, pages)


@server.tool()
async def filefolio_pdf_ocr(document_id: int) -> dict:
    """Add a searchable text layer to a scanned document. Edits in place; no-op if already text."""
    return await client.pdf_ocr(document_id)


if __name__ == "__main__":
    server.run()
