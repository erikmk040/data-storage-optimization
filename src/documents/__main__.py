"""Document registry CLI: python -m src.documents --help."""

import argparse
import json
import sqlite3
from pathlib import Path
from zipfile import BadZipFile

from pptx.exc import PythonPptxError

from .registry import Registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/documents.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="atomically import one local PDF or PPTX")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--owner")
    for field in ("revision", "document-number", "author", "document-date"):
        ingest.add_argument("--" + field)
    show = commands.add_parser("show", help="show a version, its copies, and slides")
    show.add_argument("doc_id")
    link = commands.add_parser("link-revisions", help="explicitly confirm a shared document family")
    link.add_argument("doc_id")
    link.add_argument("target_doc_id")
    link.add_argument("--confirmed-by", required=True)
    link.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        with Registry(args.db) as registry:
            if args.command == "ingest":
                metadata = {key: getattr(args, key) for key in
                            ("revision", "document_number", "author", "document_date")
                            if getattr(args, key) is not None}
                result = registry.ingest(args.path, owner_id=args.owner, metadata=metadata)
            elif args.command == "show":
                result = {"document": registry.document(args.doc_id),
                          "copies": registry.copies(args.doc_id), "slides": registry.slides(args.doc_id)}
            else:
                result = registry.link_revisions(args.doc_id, args.target_doc_id,
                                                confirmed_by=args.confirmed_by, reason=args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, sqlite3.Error, BadZipFile, PythonPptxError) as error:
        parser.exit(1, f"Error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
