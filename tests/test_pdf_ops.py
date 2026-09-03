"""Unit tests for backend.pdf_ops — pure PDF operations, no HTTP, no DB."""

import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from backend import pdf_ops


class TestParsePageRanges:
    def test_single_page(self):
        assert pdf_ops.parse_page_ranges("3", 5) == [[3]]

    def test_range(self):
        assert pdf_ops.parse_page_ranges("2-4", 5) == [[2, 3, 4]]

    def test_open_ended_range_means_to_last(self):
        assert pdf_ops.parse_page_ranges("3-", 5) == [[3, 4, 5]]

    def test_comma_groups_stay_separate(self):
        assert pdf_ops.parse_page_ranges("1-2,4", 5) == [[1, 2], [4]]

    def test_whitespace_is_tolerated(self):
        assert pdf_ops.parse_page_ranges(" 1 - 2 , 4 ", 5) == [[1, 2], [4]]

    @pytest.mark.parametrize("bad", ["", "   ", "0", "abc", "3-1", "6", "1,7", "-3", "1--3"])
    def test_rejects_malformed_or_out_of_bounds(self, bad):
        with pytest.raises(ValueError):
            pdf_ops.parse_page_ranges(bad, 5)


class TestPageCount:
    def test_counts_pages(self, multipage_pdf_file):
        assert pdf_ops.page_count(multipage_pdf_file) == 5


class TestMerge:
    def test_concatenates_in_order(self, tmp_path, sample_pdf_file, multipage_pdf_file):
        dest = tmp_path / "merged.pdf"
        pdf_ops.merge([multipage_pdf_file, sample_pdf_file], dest)
        assert len(PdfReader(dest).pages) == 6

    def test_requires_at_least_two_sources(self, tmp_path, sample_pdf_file):
        with pytest.raises(ValueError):
            pdf_ops.merge([sample_pdf_file], tmp_path / "x.pdf")


class TestSplit:
    def test_one_output_per_group(self, tmp_path, multipage_pdf_file):
        out = pdf_ops.split(multipage_pdf_file, [[1, 2], [4]], tmp_path)
        assert [p.name for p in out] == ["multipage_part1.pdf", "multipage_part2.pdf"]
        assert len(PdfReader(out[0]).pages) == 2
        assert len(PdfReader(out[1]).pages) == 1


class TestExtractPages:
    def test_keeps_only_named_pages(self, tmp_path, multipage_pdf_file):
        dest = tmp_path / "e.pdf"
        pdf_ops.extract_pages(multipage_pdf_file, [2, 3], dest)
        assert len(PdfReader(dest).pages) == 2


class TestDeletePages:
    def test_removes_named_pages(self, tmp_path, multipage_pdf_file):
        dest = tmp_path / "d.pdf"
        pdf_ops.delete_pages(multipage_pdf_file, [1, 5], dest)
        assert len(PdfReader(dest).pages) == 3

    def test_refuses_to_delete_every_page(self, tmp_path, multipage_pdf_file):
        with pytest.raises(ValueError):
            pdf_ops.delete_pages(multipage_pdf_file, [1, 2, 3, 4, 5], tmp_path / "d.pdf")


class TestRotate:
    def test_rotates_all_pages(self, tmp_path, multipage_pdf_file):
        dest = tmp_path / "r.pdf"
        pdf_ops.rotate(multipage_pdf_file, dest, 90, None)
        assert PdfReader(dest).pages[0].get("/Rotate") == 90

    def test_rejects_bad_angle(self, tmp_path, multipage_pdf_file):
        with pytest.raises(ValueError):
            pdf_ops.rotate(multipage_pdf_file, tmp_path / "r.pdf", 45, None)


class TestOcr:
    def test_raises_runtimeerror_when_ocrmypdf_missing(self, tmp_path, sample_pdf_file, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError):
            pdf_ops.ocr(sample_pdf_file, tmp_path / "o.pdf")
