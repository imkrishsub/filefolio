"""
Tests for the FileFolio command line in backend/cli.py.

The HTTP layer is covered by tests/test_client.py, so these tests stub the
backend.client functions and assert on argument parsing, output formatting,
and exit codes.
"""

import json

import pytest

import backend.cli as cli
import backend.client as client


def _stub(monkeypatch, name, result=None, error=None):
    """Replace a backend.client coroutine and record how it was called."""
    seen = {}

    async def fake(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(client, name, fake)
    return seen


DOC = {
    "id": 7,
    "filename": "2026-08-18_invoice.pdf",
    "category": "Invoice",
    "tags": ["finance", "rent"],
    "upload_date": "2026-08-18T10:00:00",
    "snippet": "Invoice #123 ...",
}


class TestSearchCommand:
    def test_search_prints_one_line_per_document(self, monkeypatch, capsys):
        _stub(monkeypatch, "search", result=[DOC])

        exit_code = cli.main(["search", "invoice"])

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "7" in out
        assert "2026-08-18_invoice.pdf" in out
        assert "Invoice" in out
        assert "finance, rent" in out

    def test_search_passes_query_and_filters_through(self, monkeypatch, capsys):
        seen = _stub(monkeypatch, "search", result=[])

        cli.main(
            [
                "search",
                "rent",
                "--category",
                "Invoice",
                "--tags",
                "finance",
                "--from",
                "2026-01-01",
                "--to",
                "2026-12-31",
            ]
        )

        assert seen["kwargs"] == {
            "query": "rent",
            "category": "Invoice",
            "tags": "finance",
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        }

    def test_search_without_query_is_allowed(self, monkeypatch, capsys):
        seen = _stub(monkeypatch, "search", result=[])

        assert cli.main(["search"]) == 0
        assert seen["kwargs"]["query"] is None

    def test_search_no_results_says_so_instead_of_printing_nothing(
        self, monkeypatch, capsys
    ):
        _stub(monkeypatch, "search", result=[])

        cli.main(["search", "nothing"])

        assert "No documents found" in capsys.readouterr().out

    def test_search_json_flag_emits_parseable_json(self, monkeypatch, capsys):
        _stub(monkeypatch, "search", result=[DOC])

        cli.main(["search", "invoice", "--json"])

        assert json.loads(capsys.readouterr().out) == [DOC]


class TestGetCommand:
    def test_get_prints_document_fields(self, monkeypatch, capsys):
        seen = _stub(
            monkeypatch,
            "get_document",
            result={
                "id": 7,
                "auto_filename": "2026-08-18_invoice.pdf",
                "category": "Invoice",
                "tags": ["finance"],
                "content_preview": "Invoice #123 ...",
            },
        )

        assert cli.main(["get", "7"]) == 0

        out = capsys.readouterr().out
        assert seen["args"] == (7,)
        assert "2026-08-18_invoice.pdf" in out
        assert "Invoice #123 ..." in out

    def test_get_rejects_non_integer_id(self, monkeypatch):
        # argparse exits 2 for a bad argument type; the CLI must not swallow it
        # into its own exit code 1, which means "the API call failed".
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["get", "seven"])

        assert excinfo.value.code == 2


class TestDownloadCommand:
    def test_download_reports_the_written_path(self, monkeypatch, capsys):
        seen = _stub(monkeypatch, "download", result="/tmp/out.pdf")

        assert cli.main(["download", "3", "/tmp/out.pdf"]) == 0
        assert seen["args"] == (3, "/tmp/out.pdf")
        assert "/tmp/out.pdf" in capsys.readouterr().out


class TestUploadCommand:
    def test_upload_reports_the_new_document(self, monkeypatch, capsys):
        seen = _stub(
            monkeypatch,
            "upload",
            result={
                "id": 5,
                "auto_filename": "2026-08-18_receipt.pdf",
                "category": "Receipt",
                "tags": ["shopping"],
            },
        )

        assert cli.main(["upload", "receipt.pdf"]) == 0

        out = capsys.readouterr().out
        assert seen["args"] == ("receipt.pdf",)
        assert "5" in out
        assert "Receipt" in out


class TestUpdateCommand:
    def test_update_splits_comma_separated_tags_into_a_list(self, monkeypatch, capsys):
        seen = _stub(monkeypatch, "update", result={"id": 4, "tags": ["a", "b"]})

        cli.main(["update", "4", "--tags", "a,b"])

        assert seen["kwargs"]["tags"] == ["a", "b"]

    def test_update_strips_whitespace_around_tags(self, monkeypatch, capsys):
        seen = _stub(monkeypatch, "update", result={"id": 4})

        cli.main(["update", "4", "--tags", "finance, rent "])

        assert seen["kwargs"]["tags"] == ["finance", "rent"]

    def test_update_omits_fields_that_were_not_passed(self, monkeypatch, capsys):
        seen = _stub(monkeypatch, "update", result={"id": 4})

        cli.main(["update", "4", "--category", "Tax"])

        assert seen["kwargs"] == {
            "filename": None,
            "tags": None,
            "category": "Tax",
        }


class TestPdfCommands:
    def test_merge_calls_client_and_prints_new_id(self, monkeypatch, capsys):
        seen = _stub(monkeypatch, "pdf_merge", result={"id": 12, "category": "Report", "tags": []})
        code = cli.main(["pdf", "merge", "3", "4", "5"])
        assert code == 0
        assert seen["args"][0] == [3, 4, 5]
        assert "12" in capsys.readouterr().out

    def test_merge_download_passes_path(self, monkeypatch, capsys, tmp_path):
        out = str(tmp_path / "m.pdf")
        seen = _stub(monkeypatch, "pdf_merge", result=out)
        cli.main(["pdf", "merge", "3", "4", "--download", out])
        assert seen["kwargs"]["download_to"] == out

    def test_split_passes_ranges(self, monkeypatch, capsys):
        seen = _stub(monkeypatch, "pdf_split", result=[{"id": 1}, {"id": 2}])
        cli.main(["pdf", "split", "7", "1-2,3-5"])
        assert seen["args"] == (7, "1-2,3-5")

    def test_rotate_requires_degrees(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["pdf", "rotate", "7"])

    def test_ocr_error_exits_1(self, monkeypatch, capsys):
        _stub(monkeypatch, "pdf_ocr", error=RuntimeError("ocrmypdf not installed"))
        code = cli.main(["pdf", "ocr", "7"])
        assert code == 1
        assert "ocrmypdf" in capsys.readouterr().err


class TestErrorHandling:
    def test_client_error_exits_1_and_writes_to_stderr(self, monkeypatch, capsys):
        _stub(
            monkeypatch,
            "search",
            error=RuntimeError("FileFolio not running at http://127.0.0.1:8000"),
        )

        exit_code = cli.main(["search", "invoice"])

        captured = capsys.readouterr()
        assert exit_code == 1
        assert "FileFolio not running" in captured.err
        # A failure must not print a half-formed result to stdout, or a shell
        # pipeline would consume it as if the command had succeeded.
        assert captured.out == ""

    def test_no_subcommand_prints_help_and_exits_nonzero(self, capsys):
        exit_code = cli.main([])

        assert exit_code == 2
        assert "usage:" in capsys.readouterr().out
