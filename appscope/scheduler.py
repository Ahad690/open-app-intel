"""Daily collection scheduler (§13 Stage 1, FR1-FR7).

Orchestrates the compliant data spine: Apple RSS charts, iTunes metadata, Google
Play metadata + install buckets, and reviews. Writes into the local DB only.

Run once:        python -m appscope.scheduler --once
Run as a daemon: python -m appscope.scheduler         (daily at config hour, UTC)
"""
from __future__ import annotations

import argparse
import logging

from .collectors import apple_rss, itunes, play, reviews
from .config import Config, load_config
from .db import Database

log = logging.getLogger(__name__)


def is_ios_id(app_id: str) -> bool:
    """iOS track ids are numeric; Android package ids look like reverse-DNS."""
    return app_id.isdigit()


def _collect_ios_charts(db: Database, cfg: Config) -> int:
    """Capture Apple RSS charts for each configured country; upsert apps + ranks."""
    inserted = 0
    feeds = ["top-free", "top-paid", "top-grossing"]
    for country in cfg.tracking.countries:
        for feed in feeds:
            rows = apple_rss.fetch_apple_chart(country=country, feed=feed)
            for row in rows:
                db.upsert_app(row)
                db.insert_rank(row)
                inserted += 1
    return inserted


def _collect_app(db: Database, cfg: Config, app_id: str) -> None:
    """Collect metadata, install buckets (Android), and reviews for one tracked app."""
    for country in cfg.tracking.countries:
        if is_ios_id(app_id):
            meta = itunes.fetch_itunes_metadata(app_id, country=country)
            if meta:
                db.upsert_app(meta)
            db.insert_reviews(reviews.fetch_ios_reviews(app_id, country=country))
        else:
            meta = play.fetch_play_app(app_id, country=country)
            if meta:
                db.upsert_app(meta)
                db.insert_install_bucket(meta)  # min/real installs (FR3)
            db.insert_reviews(reviews.fetch_android_reviews(app_id, country=country))


def run_collection(db: Database, cfg: Config) -> dict:
    """One full collection pass. Per-source failures are logged, never fatal (FR7)."""
    summary = {"ranks": 0, "apps": 0, "errors": 0}
    try:
        summary["ranks"] = _collect_ios_charts(db, cfg)
    except Exception as exc:  # defensive: a source crash must not kill the run
        log.error("ios chart collection failed: %s", exc)
        summary["errors"] += 1

    for app_id in cfg.tracking.apps:
        try:
            _collect_app(db, cfg, app_id)
            summary["apps"] += 1
        except Exception as exc:
            log.error("collection failed for %s: %s", app_id, exc)
            summary["errors"] += 1
    log.info("collection complete: %s", summary)
    return summary


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description="AppScope daily collector")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--once", action="store_true", help="run a single pass and exit")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    db = Database(cfg.storage.path)
    db.bootstrap()

    from .reminders import print_contribute_reminder

    def collect_and_remind() -> None:
        run_collection(db, cfg)
        print_contribute_reminder(cfg)

    if args.once:
        collect_and_remind()
        return

    from apscheduler.schedulers.blocking import BlockingScheduler

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(
        collect_and_remind,
        "cron",
        hour=cfg.schedule.daily_hour_utc,
        id="daily_collection",
    )
    log.info("scheduler started; daily at %02d:00 UTC", cfg.schedule.daily_hour_utc)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopped")


if __name__ == "__main__":
    main()
