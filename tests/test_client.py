"""
Tests for the FileFolio HTTP client in backend/client.py.

client.py imports no `mcp` SDK, so unlike tests/test_mcp_server.py these run
in the normal venv/ as part of the main suite.
"""

import json
from pathlib import Path

import httpx
import pytest

import backend.client as client


def _client_with_handler(handler):
    """Build a _make_client() replacement backed by an httpx.MockTransport."""

    def _make_client(timeout: float = 30.0):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://testserver",
            timeout=timeout,
        )

    return _make_client


class TestSearch:
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

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        results = await client.search(query="invoice")

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

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        results = await client.search()

        assert results == []

    @pytest.mark.asyncio
    async def test_search_connection_error_raises_clear_message(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="FileFolio not running"):
            await client.search()

    @pytest.mark.asyncio
    async def test_search_timeout_raises_clear_message(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        # httpx.TimeoutException must be caught explicitly -- it does NOT
        # inherit from httpx.ConnectError, so this proves the timeout guard
        # is in place and a raw httpx exception does not leak through.
        with pytest.raises(RuntimeError, match="did not respond in time"):
            await client.search()


class TestGetDocument:
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

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        result = await client.get_document(7)

        assert result["id"] == 7
        assert result["content_preview"] == "Invoice #123 ..."

    @pytest.mark.asyncio
    async def test_get_document_not_found_raises(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Document not found"})

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Document 999 not found"):
            await client.get_document(999)


class TestDownload:
    @pytest.mark.asyncio
    async def test_download_writes_pdf_to_dest_path(self, monkeypatch, tmp_path):
        pdf_bytes = b"%PDF-1.4 fake content"

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/download/3"
            return httpx.Response(200, content=pdf_bytes)

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        dest = tmp_path / "out.pdf"
        result = await client.download(3, str(dest))

        assert result == str(dest)
        assert dest.read_bytes() == pdf_bytes

    @pytest.mark.asyncio
    async def test_download_not_found_raises(self, monkeypatch, tmp_path):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Document not found"})

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Document 999 not found"):
            await client.download(999, str(tmp_path / "out.pdf"))

    @pytest.mark.asyncio
    async def test_download_missing_parent_dir_raises(self, tmp_path):
        missing_dir_dest = tmp_path / "nope" / "out.pdf"

        with pytest.raises(RuntimeError, match="does not exist"):
            await client.download(1, str(missing_dir_dest))


class TestUpload:
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

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        result = await client.upload(str(pdf_path))

        assert result["id"] == 5
        assert result["category"] == "Receipt"

    @pytest.mark.asyncio
    async def test_upload_uses_longer_timeout_than_default(self, monkeypatch, tmp_path):
        """client.upload must request a read timeout longer than the 30s
        default used by the other calls, since OCR + local LLM tagging
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

        monkeypatch.setattr(client, "_make_client", _recording_make_client)

        await client.upload(str(pdf_path))

        assert captured_timeouts == [300.0]
        assert captured_timeouts[0] > 30.0

    @pytest.mark.asyncio
    async def test_upload_missing_file_raises(self, tmp_path):
        missing = tmp_path / "nope.pdf"

        with pytest.raises(RuntimeError, match="File not found"):
            await client.upload(str(missing))

    @pytest.mark.asyncio
    async def test_upload_non_pdf_extension_raises(self, tmp_path):
        txt_path = tmp_path / "notes.txt"
        txt_path.write_text("hello")

        with pytest.raises(RuntimeError, match="Not a PDF file"):
            await client.upload(str(txt_path))


class TestUpdate:
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

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        result = await client.update(7, tags=["finance", "2026"], category="Tax")

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

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        await client.update(3, filename="renamed.pdf")

        assert seen["body"] == {"auto_filename": "renamed.pdf"}

    @pytest.mark.asyncio
    async def test_update_with_no_fields_raises_without_calling_api(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no HTTP request should be made")

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Nothing to update"):
            await client.update(1)

    @pytest.mark.asyncio
    async def test_update_invalid_category_raises_without_calling_api(
        self, monkeypatch
    ):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no HTTP request should be made")

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Invalid category 'Groceries'"):
            await client.update(1, category="Groceries")

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Document not found"})

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Document 999 not found"):
            await client.update(999, category="Tax")

    @pytest.mark.asyncio
    async def test_update_api_error_surfaces_detail(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500, json={"detail": "Could not move the document file"}
            )

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="Could not move the document file"):
            await client.update(4, category="Tax")

    @pytest.mark.asyncio
    async def test_update_connection_error_raises_clear_message(self, monkeypatch):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))

        with pytest.raises(RuntimeError, match="FileFolio not running"):
            await client.update(1, category="Tax")


class TestPdfOperations:
    @pytest.mark.asyncio
    async def test_merge_files_and_returns_metadata(self, monkeypatch):
        async def handler(request):
            assert request.url.path == "/pdf/merge"
            assert json.loads(request.content) == {"document_ids": [1, 2], "file": True}
            return httpx.Response(200, json={"id": 9, "category": "Report"})
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        assert await client.pdf_merge([1, 2]) == {"id": 9, "category": "Report"}

    @pytest.mark.asyncio
    async def test_merge_download_writes_file(self, monkeypatch, tmp_path):
        async def handler(request):
            assert json.loads(request.content)["file"] is False
            return httpx.Response(200, content=b"%PDF-1.7 x", headers={"content-type": "application/pdf"})
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        out = tmp_path / "m.pdf"
        result = await client.pdf_merge([1, 2], download_to=str(out))
        assert result == str(out) and out.read_bytes().startswith(b"%PDF")

    @pytest.mark.asyncio
    async def test_split_download_dir_unpacks_zip(self, monkeypatch, tmp_path):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("m_part1.pdf", b"%PDF-a")
            zf.writestr("m_part2.pdf", b"%PDF-b")
        buf.seek(0)
        async def handler(request):
            return httpx.Response(200, content=buf.read(), headers={"content-type": "application/zip"})
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        paths = await client.pdf_split(1, "1,2", download_dir=str(tmp_path))
        assert sorted(Path(p).name for p in paths) == ["m_part1.pdf", "m_part2.pdf"]

    @pytest.mark.asyncio
    async def test_rotate_sends_degrees_and_pages(self, monkeypatch):
        async def handler(request):
            assert request.url.path == "/pdf/rotate"
            assert json.loads(request.content) == {"document_id": 3, "degrees": 90, "pages": "all"}
            return httpx.Response(200, json={"id": 3})
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        assert await client.pdf_rotate(3, 90) == {"id": 3}

    @pytest.mark.asyncio
    async def test_ocr_404_raises_runtimeerror(self, monkeypatch):
        async def handler(request):
            return httpx.Response(404, json={"detail": "Document 5 not found"})
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        with pytest.raises(RuntimeError):
            await client.pdf_ocr(5)

    @pytest.mark.asyncio
    async def test_merge_download_to_missing_dir_raises_without_calling_api(
        self, monkeypatch
    ):
        async def handler(request):
            raise AssertionError("no HTTP request should be made")
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        with pytest.raises(RuntimeError, match="Destination directory does not exist"):
            await client.pdf_merge([1, 2], download_to="/no/such/dir/x.pdf")

    @pytest.mark.asyncio
    async def test_extract_download_to_missing_dir_raises_without_calling_api(
        self, monkeypatch
    ):
        async def handler(request):
            raise AssertionError("no HTTP request should be made")
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        with pytest.raises(RuntimeError, match="Destination directory does not exist"):
            await client.pdf_extract(1, "1", download_to="/no/such/dir/x.pdf")

    @pytest.mark.asyncio
    async def test_delete_pages_download_to_missing_dir_raises_without_calling_api(
        self, monkeypatch
    ):
        async def handler(request):
            raise AssertionError("no HTTP request should be made")
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        with pytest.raises(RuntimeError, match="Destination directory does not exist"):
            await client.pdf_delete_pages(1, "1", download_to="/no/such/dir/x.pdf")

    @pytest.mark.asyncio
    async def test_split_download_dir_missing_raises_without_calling_api(
        self, monkeypatch
    ):
        async def handler(request):
            raise AssertionError("no HTTP request should be made")
        monkeypatch.setattr(client, "_make_client", _client_with_handler(handler))
        with pytest.raises(RuntimeError, match="Destination directory does not exist"):
            await client.pdf_split(1, "1,2", download_dir="/no/such/dir")

    def test_parse_page_ranges_without_count(self):
        assert client.parse_page_ranges("1-3,5") == [[1, 2, 3], [5]]
        with pytest.raises(ValueError):
            client.parse_page_ranges("abc")


class TestValidCategories:
    def test_categories_match_the_storage_layer(self):
        """client.VALID_CATEGORIES rejects a bad category before the API sees
        it, so it must not drift from the tuple that decides the storage
        folder -- the same guard test_api.py applies to backend/main.py."""
        from backend import storage

        assert client.VALID_CATEGORIES == storage.VALID_CATEGORIES
