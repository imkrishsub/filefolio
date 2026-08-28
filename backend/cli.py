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

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 2

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
