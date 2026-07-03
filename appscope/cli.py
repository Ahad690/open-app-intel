"""cli.py — the JSON command-line surface the Claude Code skill drives.

One command per question, JSON on stdout, no server required. This is what
makes AppScope usable as a conversation-first skill: Claude runs
``python -m appscope.cli <cmd>`` with the user's answers as flags and surfaces
the returned envelopes verbatim (P1: value/low/high/confidence/method/sources/
flags — estimates never exceed MEDIUM, and missing data is said, not faked).

Commands:
    collect  --app <id> [--charts]      collect one app (and/or the iOS charts)
    estimate --app <id> [--country us]  download/revenue estimate envelope
    summary  --app <id> [--country us]  metadata + latest rank + reviews + bucket
    report   --app <id> [--out FILE]    render the HTML deliverable
    backup                              timestamped snapshot of the local DB

All writes are append-only (observations are never overwritten) and `backup`
never prunes old snapshots — the no-data-destroyed policy.
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import load_config
from .db import Database
from .estimate import estimate_app


def _open_db(config_path: str | None):
    cfg = load_config(config_path or "config.json")
    db = Database(cfg.storage.path)
    db.bootstrap()
    return db, cfg


def cmd_collect(args) -> dict:
    from . import scheduler

    db, cfg = _open_db(args.config)
    out: dict = {"collected": []}
    if args.charts:
        out["chart_rows"] = scheduler._collect_ios_charts(db, cfg)
        out["collected"].append("ios_charts")
    if args.app:
        scheduler._collect_app(db, cfg, args.app)
        out["collected"].append(args.app)
        out["app"] = db.get_app(args.app)
    if not out["collected"]:
        raise SystemExit("collect: pass --app <id> and/or --charts")
    return out


def cmd_estimate(args) -> dict:
    db, cfg = _open_db(args.config)
    return estimate_app(db, args.app, country=args.country, config=cfg)


def cmd_summary(args) -> dict:
    db, _cfg = _open_db(args.config)
    app = db.get_app(args.app)
    if not app:
        return {"app_id": args.app, "found": False,
                "note": "not collected yet — run: python -m appscope.cli collect --app " + args.app}
    latest = db.get_latest_rank(args.app, country=args.country)
    reviews = db.get_reviews(args.app, days=args.days)
    buckets = db.get_install_buckets(args.app)
    return {
        "found": True,
        "app": app,
        "latest_rank": latest,
        "reviews_last_days": {"days": args.days, "count": len(reviews)},
        "install_buckets": buckets[-3:],  # most recent snapshots
        "sources": ["local_db"],
        "confidence": "HIGH",  # observed facts from the local capture
        "method": "local_observed",
    }


def cmd_report(args) -> dict:
    from .report import build_report

    db, cfg = _open_db(args.config)
    path = build_report(db, cfg, args.app, country=args.country, out_path=args.out)
    return {"written": path, "app_id": args.app}


def cmd_backup(args) -> dict:
    db, _cfg = _open_db(args.config)
    return {"backup": db.backup(args.dest)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="appscope", description="AppScope skill CLI (JSON out).")
    ap.add_argument("--config", default=None, help="Path to config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("collect", help="Collect one app and/or the iOS charts into the local DB.")
    p.add_argument("--app", help="iOS numeric id or Android package id")
    p.add_argument("--charts", action="store_true", help="Also capture the Apple RSS top charts")
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("estimate", help="Download/revenue estimate envelope for an app.")
    p.add_argument("--app", required=True)
    p.add_argument("--country", default="us")
    p.set_defaults(fn=cmd_estimate)

    p = sub.add_parser("summary", help="Observed facts for an app from the local DB.")
    p.add_argument("--app", required=True)
    p.add_argument("--country", default="us")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("report", help="Render the app-intel HTML deliverable.")
    p.add_argument("--app", required=True)
    p.add_argument("--country", default="us")
    p.add_argument("--out", default="app-intel-report.html")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("backup", help="Timestamped snapshot of the local DB (never pruned).")
    p.add_argument("--dest", default="backups")
    p.set_defaults(fn=cmd_backup)

    args = ap.parse_args(argv)
    result = args.fn(args)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
