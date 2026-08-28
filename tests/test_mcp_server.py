"""
Tests for the FileFolio MCP server tools in backend/mcp_server.py.

Run inside venv-mcp/ (this file imports backend.mcp_server, which imports the
`mcp` SDK -- incompatible with the backend's own venv/, see requirements-mcp.txt).
Run with: venv-mcp/bin/python -m pytest --noconftest tests/test_mcp_server.py
(--noconftest is required because tests/conftest.py imports fastapi at module
scope, which is not installed in venv-mcp/).
"""

import json

import httpx
import pytest

pytest.importorskip(
    "mcp",
    reason="mcp SDK only installed in venv-mcp/ -- see requirements-mcp.txt",
)

import backend.mcp_server as mcp_server


def _client_with_handler(handler):
    """Build a _make_client() replacement backed by an httpx.MockTransport."""

    def _make_client(timeout: float = 30.0):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://testserver",
            timeout=timeout,
        )

    return _make_client


class TestFilefolioSearch:
    @pytest.mark.asyncio
    async def test_search_returns_reshaped_documents(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/documents"
            assert request.url.params["search"] == "invoice"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "original_filename": "invoice.pdf",
                        "auto_filename": "2026-08-18_invoice.pdf",
                        "tags": ["finance"],
                        "category": "Invoice",
                        "upload_date": "2026-08-18T10:00:00",
                        "preview": "Invoice #123 ...",
                    }
                ],
            )

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        results = await mcp_server.filefolio_search(query="invoice")

        assert results == [
            {
                "id": 1,
                "filename": "2026-08-18_invoice.pdf",
                "category": "Invoice",
                "tags": ["finance"],
                "upload_date": "2026-08-18T10:00:00",
                "snippet": "Invoice #123 ...",
            }
        ]

    @pytest.mark.asyncio
    async def test_search_no_params_sends_no_query_params(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert dict(request.url.params) == {}
            return httpx.Response(200, json=[])

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        results = await mcp_server.filefolio_search()

        assert results == []

    @pytest.mark.asyncio
    async def test_search_connection_error_raises_clear_message(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="FileFolio not running"):
            await mcp_server.filefolio_search()

    @pytest.mark.asyncio
    async def test_search_timeout_raises_clear_message(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        # httpx.TimeoutException must be caught explicitly -- it does NOT
        # inherit from httpx.ConnectError, so this proves the timeout guard
        # is in place and a raw httpx exception does not leak through.
        with pytest.raises(RuntimeError, match="did not respond in time"):
            await mcp_server.filefolio_search()


class TestFilefolioGetDocument:
    @pytest.mark.asyncio
    async def test_get_document_returns_metadata(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/documents/7"
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "original_filename": "invoice.pdf",
                    "stored_filename": "20260818_invoice.pdf",
                    "auto_filename": "2026-08-18_invoice.pdf",
                    "tags": ["finance"],
                    "category": "Invoice",
                    "upload_date": "2026-08-18T10:00:00",
                    "content_preview": "Invoice #123 ...",
                    "thumbnail": "thumbnails/7.jpg",
                },
            )

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        result = await mcp_server.filefolio_get_document(7)

        assert result["id"] == 7
        assert result["content_preview"] == "Invoice #123 ..."

    @pytest.mark.asyncio
    async def test_get_document_not_found_raises(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Document not found"})

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Document 999 not found"):
            await mcp_server.filefolio_get_document(999)


class TestFilefolioDownload:
    @pytest.mark.asyncio
    async def test_download_writes_pdf_to_dest_path(self, monkeypatch, tmp_path):
        pdf_bytes = b"%PDF-1.4 fake content"

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/download/3"
            return httpx.Response(200, content=pdf_bytes)

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        dest = tmp_path / "out.pdf"
        result = await mcp_server.filefolio_download(3, str(dest))

        assert result == str(dest)
        assert dest.read_bytes() == pdf_bytes

    @pytest.mark.asyncio
    async def test_download_not_found_raises(self, monkeypatch, tmp_path):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Document not found"})

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Document 999 not found"):
            await mcp_server.filefolio_download(999, str(tmp_path / "out.pdf"))

    @pytest.mark.asyncio
    async def test_download_missing_parent_dir_raises(self, tmp_path):
        missing_dir_dest = tmp_path / "nope" / "out.pdf"

        with pytest.raises(RuntimeError, match="does not exist"):
            await mcp_server.filefolio_download(1, str(missing_dir_dest))


class TestFilefolioUpload:
    @pytest.mark.asyncio
    async def test_upload_sends_file_and_returns_metadata(self, monkeypatch, tmp_path):
        pdf_path = tmp_path / "receipt.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content")

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/upload"
            # Verify multipart request body is correctly formed
            assert request.headers["content-type"].startswith("multipart/form-data")
            body_str = request.content.decode(errors="replace")
            assert 'name="file"' in body_str
            assert 'filename="receipt.pdf"' in body_str
            assert "Content-Type: application/pdf" in body_str
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "original_filename": "receipt.pdf",
                    "auto_filename": "2026-08-18_receipt.pdf",
                    "category": "Receipt",
                    "tags": ["shopping"],
                },
            )

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        result = await mcp_server.filefolio_upload(str(pdf_path))

        assert result["id"] == 5
        assert result["category"] == "Receipt"

    @pytest.mark.asyncio
    async def test_upload_uses_longer_timeout_than_default(self, monkeypatch, tmp_path):
        """filefolio_upload must request a read timeout longer than the 30s
        default used by the other three tools, since OCR + local LLM tagging
        on the backend routinely takes well over 30s for a scanned PDF."""
        pdf_path = tmp_path / "receipt.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content")

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": 5,
                    "original_filename": "receipt.pdf",
                    "auto_filename": "2026-08-18_receipt.pdf",
                    "category": "Receipt",
                    "tags": ["shopping"],
                },
            )

        base_make_client = _client_with_handler(handler)
        captured_timeouts = []

        def _recording_make_client(timeout: float = 30.0):
            captured_timeouts.append(timeout)
            return base_make_client(timeout=timeout)

        monkeypatch.setattr(mcp_server, "_make_client", _recording_make_client)

        await mcp_server.filefolio_upload(str(pdf_path))

        assert captured_timeouts == [300.0]
        assert captured_timeouts[0] > 30.0

    @pytest.mark.asyncio
    async def test_upload_missing_file_raises(self, tmp_path):
        missing = tmp_path / "nope.pdf"

        with pytest.raises(RuntimeError, match="File not found"):
            await mcp_server.filefolio_upload(str(missing))

    @pytest.mark.asyncio
    async def test_upload_non_pdf_extension_raises(self, tmp_path):
        txt_path = tmp_path / "notes.txt"
        txt_path.write_text("hello")

        with pytest.raises(RuntimeError, match="Not a PDF file"):
            await mcp_server.filefolio_upload(str(txt_path))


class TestFilefolioUpdate:
    @pytest.mark.asyncio
    async def test_update_sends_only_provided_fields_and_returns_document(
        self, monkeypatch
    ):
        seen = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "PUT":
                assert request.url.path == "/document/7"
                seen["body"] = json.loads(request.content)
                return httpx.Response(
                    200, json={"success": True, "message": "Document updated"}
                )
            assert request.url.path == "/documents/7"
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "auto_filename": "2026-08-18_invoice.pdf",
                    "category": "Tax",
                    "tags": ["finance", "2026"],
                },
            )

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        result = await mcp_server.filefolio_update(
            7, tags=["finance", "2026"], category="Tax"
        )

        # filename was not passed, so it must be absent from the body -- sending
        # auto_filename=None would be indistinguishable from "leave unchanged"
        # only by luck; the backend treats a missing key as "leave unchanged".
        assert seen["body"] == {"tags": ["finance", "2026"], "category": "Tax"}
        assert result["category"] == "Tax"
        assert result["tags"] == ["finance", "2026"]

    @pytest.mark.asyncio
    async def test_update_maps_filename_to_auto_filename(self, monkeypatch):
        seen = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "PUT":
                seen["body"] = json.loads(request.content)
                return httpx.Response(200, json={"success": True})
            return httpx.Response(200, json={"id": 3, "auto_filename": "renamed.pdf"})

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        await mcp_server.filefolio_update(3, filename="renamed.pdf")

        assert seen["body"] == {"auto_filename": "renamed.pdf"}

    @pytest.mark.asyncio
    async def test_update_with_no_fields_raises_without_calling_api(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no HTTP request should be made")

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Nothing to update"):
            await mcp_server.filefolio_update(1)

    @pytest.mark.asyncio
    async def test_update_invalid_category_raises_without_calling_api(
        self, monkeypatch
    ):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no HTTP request should be made")

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Invalid category 'Groceries'"):
            await mcp_server.filefolio_update(1, category="Groceries")

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Document not found"})

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Document 999 not found"):
            await mcp_server.filefolio_update(999, category="Tax")

    @pytest.mark.asyncio
    async def test_update_api_error_surfaces_detail(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500, json={"detail": "Could not move the document file"}
            )

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Could not move the document file"):
            await mcp_server.filefolio_update(4, category="Tax")

    @pytest.mark.asyncio
    async def test_update_connection_error_raises_clear_message(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        monkeypatch.setattr(mcp_server, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="FileFolio not running"):
            await mcp_server.filefolio_update(1, category="Tax")
