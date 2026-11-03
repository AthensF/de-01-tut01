"""Explicit commands used by the course, CI, and production schedules."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from roadsafety.config import atomic_json, utc_now


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Road-safety engineering course and application")
    commands = result.add_subparsers(dest="command", required=True)
    names = ["verify-sources", "pipeline", "profile", "metadata", "data-product", "toolkit", "incident",
             "review", "platform-review", "serve", "publish", "restore-state", "save-operations",
             "investigate", "lesson", "record-incident"]
    for name in names:
        p = commands.add_parser(name)
        p.add_argument("--data-dir", type=Path, default=Path(os.environ.get("ROADSAFETY_DATA_DIR", "data")))
        if name == "pipeline":
            p.add_argument("--mode", choices=["fixture", "live"], default="fixture")
            p.add_argument("--as-of", type=date.fromisoformat)
            p.add_argument("--full-reconcile", action="store_true")
            p.add_argument("--input-dir", type=Path, help="Explicit synthetic JSON inputs only")
        if name == "verify-sources":
            p.add_argument("--accept-source-terms", action="store_true", help="Acknowledge the source terms you reviewed")
        if name == "serve":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
        if name == "investigate":
            p.add_argument("--enable-ai", action="store_true", help="Permit separately billed, budgeted API inference")
        if name == "review":
            p.add_argument("--diff", type=Path)
        if name == "lesson":
            p.add_argument("number", type=int, choices=range(1, 17))
            p.add_argument("--live", action="store_true")
        if name == "record-incident":
            p.add_argument("--summary", required=True)
            p.add_argument("--approve", action="store_true", required=True,
                           help="Explicitly record your reviewed decision; not AI approval")
    return result


def main(argv: list[str] | None = None):
    args = parser().parse_args(argv)
    try:
        if args.command == "pipeline":
            from roadsafety.pipeline import run_pipeline
            output = run_pipeline(args.data_dir, mode=args.mode, as_of=args.as_of,
                                  full_reconcile=args.full_reconcile, input_dir=args.input_dir)
        elif args.command == "verify-sources":
            from roadsafety.ingest import verify_sources
            output = verify_sources(args.data_dir)
            if args.accept_source_terms:
                if output["status"] != "verified":
                    raise ValueError("Source access/schema verification failed; cannot acknowledge an unverified source")
                output["terms_acknowledged"] = True
                output["terms_acknowledged_at"] = utc_now()
                atomic_json(args.data_dir / "source_verification.json", output)
            print(json.dumps(output, indent=2, default=str))
            if output["status"] != "verified":
                raise SystemExit(2)
            return output
        elif args.command == "serve":
            import uvicorn
            from roadsafety.api import create_app
            uvicorn.run(create_app(data_dir=args.data_dir), host=args.host, port=args.port)
            return
        elif args.command == "lesson":
            from roadsafety.lessons import run_lesson
            output = run_lesson(args.number, data_dir=args.data_dir, live=args.live)
        elif args.command in {"publish", "restore-state", "save-operations"}:
            from roadsafety.deploy import publish, restore_state, persist_operations
            output = {"publish": publish, "restore-state": restore_state,
                      "save-operations": persist_operations}[args.command](args.data_dir)
        elif args.command == "investigate":
            from roadsafety.investigation import investigate
            from roadsafety.deploy import persist_operations
            hosted = os.environ.get("GITHUB_ACTIONS") == "true"
            callback = (lambda: persist_operations(args.data_dir)) if hosted and args.enable_ai else None
            output = investigate(args.data_dir, enable_ai=args.enable_ai, persist_ledger=callback)
        elif args.command == "record-incident":
            path = args.data_dir / "incidents" / "reviewed.json"
            history = json.loads(path.read_text()) if path.exists() else []
            history.append({"reviewed_at": utc_now(), "summary": args.summary, "reviewer": "human",
                            "approval": "explicit record-incident command"})
            atomic_json(path, history)
            output = {"path": str(path), "records": len(history)}
        else:
            from roadsafety import reports
            functions = {"profile": reports.profile, "metadata": reports.metadata, "data-product": reports.data_product,
                         "toolkit": reports.toolkit, "incident": reports.incident, "review": reports.review,
                         "platform-review": reports.platform_review}
            function = functions[args.command]
            output = {"path": str(function(args.data_dir, diff_path=args.diff) if args.command == "review" else function(args.data_dir))}
        print(json.dumps(output, indent=2, default=str))
        return output
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc


def entrypoint() -> None:
    """Console launchers pass the return value to sys.exit; keep it empty."""
    main()


if __name__ == "__main__":
    main()
