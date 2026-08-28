"""
Tests for the MCP surface in backend/mcp_server.py.

The HTTP behaviour these tools expose is covered by tests/test_client.py; what
is left to prove here is that every tool is registered and delegates to the
matching backend.client function.

Run inside venv-mcp/ (this file imports backend.mcp_server, which imports the
`mcp` SDK -- incompatible with the backend's own venv/, see requirements-mcp.txt).
Run with: venv-mcp/bin/python -m pytest --noconftest tests/test_mcp_server.py
(--noconftest is required because tests/conftest.py imports fastapi at module
scope, which is not installed in venv-mcp/).
"""

import pytest

pytest.importorskip(
    "mcp",
    reason="mcp SDK only installed in venv-mcp/ -- see requirements-mcp.txt",
)

import backend.client as client
import backend.mcp_server as mcp_server


class TestToolDelegation:
    @pytest.mark.asyncio
    async def test_search_delegates_with_all_arguments(self, monkeypatch):
        seen = {}

        async def fake_search(**kwargs):
            seen.update(kwargs)
            return [{"id": 1}]

        monkeypatch.setattr(client, "search", fake_search)

        result = await mcp_server.filefolio_search(
            query="rent",
            category="Invoice",
            tags="finance",
            date_from="2026-01-01",
            date_to="2026-12-31",
        )

        assert seen == {
            "query": "rent",
            "category": "Invoice",
            "tags": "finance",
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        }
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_get_document_delegates(self, monkeypatch):
        seen = {}

        async def fake_get(doc_id):
            seen["doc_id"] = doc_id
            return {"id": doc_id}

        monkeypatch.setattr(client, "get_document", fake_get)

        assert await mcp_server.filefolio_get_document(7) == {"id": 7}
        assert seen == {"doc_id": 7}

    @pytest.mark.asyncio
    async def test_download_delegates(self, monkeypatch):
        seen = {}

        async def fake_download(doc_id, dest_path):
            seen.update(doc_id=doc_id, dest_path=dest_path)
            return dest_path

        monkeypatch.setattr(client, "download", fake_download)

        assert await mcp_server.filefolio_download(3, "/tmp/out.pdf") == "/tmp/out.pdf"
        assert seen == {"doc_id": 3, "dest_path": "/tmp/out.pdf"}

    @pytest.mark.asyncio
    async def test_upload_delegates(self, monkeypatch):
        seen = {}

        async def fake_upload(file_path):
            seen["file_path"] = file_path
            return {"id": 5}

        monkeypatch.setattr(client, "upload", fake_upload)

        assert await mcp_server.filefolio_upload("/tmp/receipt.pdf") == {"id": 5}
        assert seen == {"file_path": "/tmp/receipt.pdf"}

    @pytest.mark.asyncio
    async def test_update_delegates_with_keyword_arguments(self, monkeypatch):
        seen = {}

        async def fake_update(doc_id, filename=None, tags=None, category=None):
            seen.update(doc_id=doc_id, filename=filename, tags=tags, category=category)
            return {"id": doc_id, "category": category}

        monkeypatch.setattr(client, "update", fake_update)

        result = await mcp_server.filefolio_update(
            4, filename="rent.pdf", tags=["home"], category="Invoice"
        )

        assert seen == {
            "doc_id": 4,
            "filename": "rent.pdf",
            "tags": ["home"],
            "category": "Invoice",
        }
        assert result == {"id": 4, "category": "Invoice"}

    def test_every_client_call_is_exposed_as_a_tool(self):
        """A new client function should not be silently missing from MCP."""
        for name in ("search", "get_document", "download", "upload", "update"):
            assert hasattr(mcp_server, f"filefolio_{name}")
