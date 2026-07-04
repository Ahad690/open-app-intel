#!/usr/bin/env python3
"""daily_anchor_run.py — the daily anchor-minting + federation loop.

Meant to run once per day (Task Scheduler / cron), from the repo root:

    python scripts/daily_anchor_run.py [--config config.json] [--no-contribute]

What it does, in order (all append-only; nothing is ever destroyed):
  1. Snapshot the DB (timestamped backup, never pruned).
  2. Capture the iOS top charts (fresh rank observations).
  3. Re-collect EVERY Android app that already has an install bucket — the
     self-maintaining anchor fleet: any newly collected app automatically
     joins tomorrow's run.
  4. Derive real flow anchors from multi-day bucket deltas
     (seed_flow_anchors_from_buckets) and recalibrate.
  5. If there are new local anchors, contribute them to the HF community
     dataset (announced, never silent). The token comes from the HF_TOKEN env
     var or the cached `hf auth login` token. --no-contribute skips step 5.

Every run prints a one-line summary suitable for an append-only log.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from appscope import scheduler  # noqa: E402
from appscope.config import load_config  # noqa: E402
from appscope.db import Database  # noqa: E402

CONTRIBUTOR = "Ahad690"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Daily anchor-minting + federation run.")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--no-contribute", action="store_true",
                    help="Collect + mint anchors but skip the HF upload step")
    args = ap.parse_args(argv)

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    cfg = load_config(args.config)
    db = Database(cfg.storage.path)
    db.bootstrap()

    # 1. Snapshot first — cheap insurance, never pruned.
    backup = db.backup("backups")

    # 2. Fresh chart ranks (per-source failures are logged, never fatal).
    try:
        chart_rows = scheduler._collect_ios_charts(db, cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] ios chart collection failed: {exc}")
        chart_rows = 0
    # Android charts are the RANK half of every anchor: top-N chart apps also
    # get their buckets captured, joining the fleet automatically.
    try:
        chart_rows += scheduler._collect_android_charts(db, cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] android chart collection failed: {exc}")

    # 3. Re-collect the anchor fleet: every Android app with a bucket on file.
    fleet = [r["app_id"] for r in db.conn.execute(
        "SELECT DISTINCT app_id FROM install_buckets ORDER BY app_id").fetchall()]
    ok = fail = 0
    for app_id in fleet:
        try:
            scheduler._collect_app(db, cfg, app_id)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {app_id}: {exc}")
            fail += 1

    # 4. Mint anchors from multi-day deltas + recalibrate.
    minted = db.seed_flow_anchors_from_buckets()
    try:
        db.recalibrate_all_segments()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] recalibration failed: {exc}")

    # 5. Contribute new local anchors (announced; token-gated).
    contributed = "skipped"
    if not args.no_contribute and minted > 0:
        env = dict(os.environ)
        token_env = cfg.keys.hf_token_env if hasattr(cfg, "keys") else "HF_TOKEN"
        if not env.get(token_env):
            try:  # bridge the cached `hf auth login` token into the env
                from huggingface_hub import get_token
                cached = get_token()
                if cached:
                    env[token_env] = cached
            except Exception:  # noqa: BLE001
                pass
        r = subprocess.run(
            [sys.executable, "-m", "appscope.federation.contribute",
             "--config", args.config, "--contributor", CONTRIBUTOR],
            env=env, cwd=ROOT, capture_output=True, text=True)
        print(r.stdout)
        if r.stderr.strip():
            print(r.stderr, file=sys.stderr)
        contributed = "pr_opened" if r.returncode == 0 else f"failed(rc={r.returncode})"
    elif minted == 0:
        contributed = "nothing_new_to_contribute"

    print(f"[{stamp}] charts={chart_rows} fleet={ok}ok/{fail}fail "
          f"anchors_minted={minted} contribute={contributed} backup={backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
