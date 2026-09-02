"""
FileFolio command line.

A thin argparse wrapper over backend/client.py, so the terminal and the MCP
server (backend/mcp_server.py) share one HTTP layer, one set of error
messages, and one FILEFOLIO_URL. Needs a running FileFolio instance; set
FILEFOLIO_URL to point at a non-default one.

Usage: python backend/cli.py <command> [options]
"""

import argparse
import asyncio
import json
import sys
from typing import Optional

# Match the import idiom in backend/main.py: works both as `python
# backend/cli.py` (where sys.path[0] is backend/) and as an imported
# `backend.cli` module.
try:
    from backend import client
except ModuleNotFoundError:
    import client


def _split_tags(raw: Optional[str]) -> Optional[list[str]]:
    """Turn `--tags "finance, rent"` into ["finance", "rent"]."""
    if raw is None:
        return None
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def _print_json(payload) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _format_tags(tags) -> str:
    return ", ".join(tags) if tags else "-"


def _cmd_search(args) -> None:
    results = asyncio.run(
        client.search(
            query=args.query,
            category=args.category,
            tags=args.tags,
            date_from=args.date_from,
            date_to=args.date_to,
        )
    )

    if args.json:
        _print_json(results)
        return

    if not results:
        print("No documents found.")
        return

    width = max(len(str(doc["id"])) for doc in results)
    for doc in results:
        print(
            f"{str(doc['id']).rjust(width)}  {doc['filename']}\n"
            f"{' ' * width}  {doc.get('category') or '-'} | {_format_tags(doc.get('tags'))}"
        )


def _cmd_get(args) -> None:
    doc = asyncio.run(client.get_document(args.doc_id))

    if args.json:
        _print_json(doc)
        return

    print(f"id:       {doc.get('id')}")
    print(f"filename: {doc.get('auto_filename') or doc.get('original_filename')}")
    print(f"category: {doc.get('category') or '-'}")
    print(f"tags:     {_format_tags(doc.get('tags'))}")
    print(f"uploaded: {doc.get('upload_date') or '-'}")
    preview = doc.get("content_preview")
    if preview:
        print(f"\n{preview}")


def _cmd_download(args) -> None:
    path = asyncio.run(client.download(args.doc_id, args.dest))
    print(f"Saved to {path}")


def _cmd_upload(args) -> None:
    doc = asyncio.run(client.upload(args.file))

    if args.json:
        _print_json(doc)
        return

    print(
        f"Uploaded as id {doc.get('id')}: "
        f"{doc.get('auto_filename') or doc.get('original_filename')}"
    )
    print(f"category: {doc.get('category') or '-'}")
    print(f"tags:     {_format_tags(doc.get('tags'))}")


def _cmd_update(args) -> None:
    doc = asyncio.run(
        client.update(
            args.doc_id,
            filename=args.filename,
            tags=_split_tags(args.tags),
            category=args.category,
        )
    )

    if args.json:
        _print_json(doc)
        return

    print(f"Updated document {doc.get('id')}")
    print(f"filename: {doc.get('auto_filename') or doc.get('original_filename')}")
    print(f"category: {doc.get('category') or '-'}")
    print(f"tags:     {_format_tags(doc.get('tags'))}")


def _print_doc_line(doc) -> None:
    print(
        f"Filed as id {doc.get('id')}: {doc.get('category') or '-'} | "
        f"{_format_tags(doc.get('tags'))}"
    )


def _cmd_pdf_merge(args) -> None:
    result = asyncio.run(client.pdf_merge(args.doc_ids, download_to=args.download))
    if args.json:
        _print_json(result)
        return
    if args.download:
        print(f"Saved to {result}")
    else:
        _print_doc_line(result)


def _cmd_pdf_split(args) -> None:
    result = asyncio.run(
        client.pdf_split(args.doc_id, args.ranges, download_dir=args.download_dir)
    )
    if args.json:
        _print_json(result)
        return
    if args.download_dir:
        for path in result:
            print(f"Saved {path}")
    else:
        for doc in result:
            _print_doc_line(doc)


def _cmd_pdf_extract(args) -> None:
    _run_single_page_cmd(client.pdf_extract, args)


def _cmd_pdf_delete_pages(args) -> None:
    _run_single_page_cmd(client.pdf_delete_pages, args)


def _run_single_page_cmd(fn, args) -> None:
    result = asyncio.run(fn(args.doc_id, args.pages, download_to=args.download))
    if args.json:
        _print_json(result)
        return
    print(f"Saved to {result}") if args.download else _print_doc_line(result)


def _cmd_pdf_rotate(args) -> None:
    result = asyncio.run(client.pdf_rotate(args.doc_id, args.degrees, args.pages))
    _print_json(result) if args.json else print(f"Rotated document {result.get('id')}")


def _cmd_pdf_ocr(args) -> None:
    result = asyncio.run(client.pdf_ocr(args.doc_id))
    _print_json(result) if args.json else print(
        f"OCR added to document {result.get('id')}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filefolio",
        description="Search, read, and file documents in a running FileFolio instance.",
        epilog="Set FILEFOLIO_URL to point at a non-default instance.",
    )
    sub = parser.add_subparsers(dest="command")

    def _add_json_flag(p):
        p.add_argument(
            "--json", action="store_true", help="print the raw API JSON instead"
        )

    search = sub.add_parser("search", help="search documents")
    search.add_argument("query", nargs="?", help="text to look for")
    search.add_argument("--category", help="filter by category")
    search.add_argument("--tags", help="filter by tag")
    search.add_argument("--from", dest="date_from", help="earliest upload date")
    search.add_argument("--to", dest="date_to", help="latest upload date")
    _add_json_flag(search)
    search.set_defaults(func=_cmd_search)

    get = sub.add_parser("get", help="show one document")
    get.add_argument("doc_id", type=int, metavar="ID")
    _add_json_flag(get)
    get.set_defaults(func=_cmd_get)

    download = sub.add_parser("download", help="save a document's PDF")
    download.add_argument("doc_id", type=int, metavar="ID")
    download.add_argument("dest", help="destination file path")
    download.set_defaults(func=_cmd_download)

    upload = sub.add_parser("upload", help="add a PDF")
    upload.add_argument("file", help="path to a PDF")
    _add_json_flag(upload)
    upload.set_defaults(func=_cmd_upload)

    update = sub.add_parser("update", help="change filename, tags, or category")
    update.add_argument("doc_id", type=int, metavar="ID")
    update.add_argument("--filename", help="new filename")
    update.add_argument("--tags", help="comma-separated replacement tags")
    update.add_argument(
        "--category", choices=client.VALID_CATEGORIES, help="new category"
    )
    _add_json_flag(update)
    update.set_defaults(func=_cmd_update)

    pdf = sub.add_parser("pdf", help="merge, split, rotate, and OCR stored PDFs")
    pdf_sub = pdf.add_subparsers(dest="pdf_command")

    p_merge = pdf_sub.add_parser("merge", help="merge documents into one")
    p_merge.add_argument("doc_ids", nargs="+", type=int, metavar="ID")
    p_merge.add_argument("--download", metavar="OUT.pdf", help="save instead of filing")
    _add_json_flag(p_merge)
    p_merge.set_defaults(func=_cmd_pdf_merge)

    p_split = pdf_sub.add_parser("split", help="split one document by page ranges")
    p_split.add_argument("doc_id", type=int, metavar="ID")
    p_split.add_argument("ranges", help='e.g. "1-3,5,8-"')
    p_split.add_argument(
        "--download-dir", metavar="DIR", help="save parts instead of filing"
    )
    _add_json_flag(p_split)
    p_split.set_defaults(func=_cmd_pdf_split)

    for name, help_text in [
        ("extract", "keep only these pages"),
        ("delete-pages", "remove these pages"),
    ]:
        p = pdf_sub.add_parser(name, help=help_text)
        p.add_argument("doc_id", type=int, metavar="ID")
        p.add_argument("pages", help='e.g. "2-4"')
        p.add_argument(
            "--download", metavar="OUT.pdf", help="save instead of filing"
        )
        _add_json_flag(p)
        p.set_defaults(
            func=_cmd_pdf_extract if name == "extract" else _cmd_pdf_delete_pages
        )

    p_rot = pdf_sub.add_parser("rotate", help="rotate pages in place")
    p_rot.add_argument("doc_id", type=int, metavar="ID")
    p_rot.add_argument("--degrees", type=int, choices=[90, 180, 270], required=True)
    p_rot.add_argument("--pages", default="all", help='"all" or e.g. "1,3"')
    _add_json_flag(p_rot)
    p_rot.set_defaults(func=_cmd_pdf_rotate)

    p_ocr = pdf_sub.add_parser("ocr", help="add a searchable text layer in place")
    p_ocr.add_argument("doc_id", type=int, metavar="ID")
    _add_json_flag(p_ocr)
    p_ocr.set_defaults(func=_cmd_pdf_ocr)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 2

    if args.command == "pdf" and not getattr(args, "pdf_command", None):
        parser.error(
            "pdf needs a subcommand: merge, split, extract, delete-pages, rotate, ocr"
        )

    try:
        args.func(args)
    except RuntimeError as exc:
        # client.py raises RuntimeError for every expected failure (instance
        # down, timeout, 404, API error), so the message is already readable.
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
