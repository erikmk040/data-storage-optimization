"""Document registry CLI: python -m src.documents --help."""

import argparse
import json
import sqlite3
import subprocess
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
    ingest.add_argument("--render", choices=("auto", "required", "none"), default="auto")
    ingest.add_argument("--rendered-pdf", type=Path)
    ingest.add_argument("--render-evidence")
    show = commands.add_parser("show", help="show a version, its copies, and slides")
    show.add_argument("doc_id")
    link = commands.add_parser("link-revisions", help="explicitly confirm a shared document family")
    link.add_argument("doc_id")
    link.add_argument("target_doc_id")
    link.add_argument("--confirmed-by", required=True)
    link.add_argument("--reason", required=True)
    commands.add_parser("profiles", help="list registered rendering/hashing profiles")
    commands.add_parser("shared", help="list exact nonempty slide text shared across versions")
    compare = commands.add_parser("compare", help="compare slides by content, including moved slides")
    compare.add_argument("left_doc_id")
    compare.add_argument("right_doc_id")
    compare.add_argument("--calibration")
    compare.add_argument("--text-similarity", type=float, default=0.85)
    calibrate_parser = commands.add_parser("calibrate", help="calibrate against labeled demo image pairs")
    calibrate_parser.add_argument("profile_id")
    calibrate_parser.add_argument("pairs", type=Path, help="JSON array: left, right, same_slide")
    offboarding = commands.add_parser("offboarding", help="report remaining-copy evidence; never delete files")
    offboarding.add_argument("copy_id")
    offboarding.add_argument("--verified-by", required=True)
    offboarding.add_argument("--remaining-copy")
    offboarding.add_argument("--access-confirmations", type=Path,
                            help="JSON object mapping remaining copy IDs to continued-team-access evidence")
    args = parser.parse_args(argv)
    try:
        with Registry(args.db) as registry:
            if args.command == "ingest":
                metadata = {key: getattr(args, key) for key in
                            ("revision", "document_number", "author", "document_date")
                            if getattr(args, key) is not None}
                result = registry.ingest(args.path, owner_id=args.owner, metadata=metadata,
                                         render=args.render, rendered_pdf=args.rendered_pdf,
                                         render_evidence=args.render_evidence)
            elif args.command == "show":
                result = {"document": registry.document(args.doc_id),
                          "copies": registry.copies(args.doc_id), "slides": registry.slides(args.doc_id)}
            elif args.command == "link-revisions":
                result = registry.link_revisions(args.doc_id, args.target_doc_id,
                                                confirmed_by=args.confirmed_by, reason=args.reason)
            elif args.command == "profiles":
                result = [{"profile_id": row[0], "definition": json.loads(row[1])}
                          for row in registry.connection.execute("SELECT * FROM phash_profiles ORDER BY profile_id")]
            elif args.command == "shared":
                from .revisions import shared_slides
                result = shared_slides(registry)
            elif args.command == "compare":
                from .revisions import compare_versions
                result = compare_versions(registry, args.left_doc_id, args.right_doc_id,
                                           calibration_id=args.calibration,
                                           text_similarity=args.text_similarity)
            elif args.command == "calibrate":
                from .visuals import calibrate
                pairs = json.loads(args.pairs.read_text(encoding="utf-8"))
                if not isinstance(pairs, list) or any(not isinstance(pair, dict) for pair in pairs):
                    raise ValueError("Calibration input must be an array of labeled image pairs")
                for pair in pairs:
                    for key in ("left", "right"):
                        if not isinstance(pair.get(key), str):
                            raise ValueError("Calibration paths must be strings")
                        pair[key] = str(args.pairs.resolve().parent / pair[key])
                result = calibrate(registry, args.profile_id, pairs)
            elif args.command == "offboarding":
                from .offboarding import offboarding_report
                confirmations = (json.loads(args.access_confirmations.read_text(encoding="utf-8"))
                                 if args.access_confirmations else None)
                result = offboarding_report(registry, args.copy_id, verified_by=args.verified_by,
                                             access_confirmations=confirmations,
                                             remaining_copy_id=args.remaining_copy)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error, BadZipFile,
            PythonPptxError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
