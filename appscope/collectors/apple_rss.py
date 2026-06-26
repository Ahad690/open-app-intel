"""Apple RSS top-charts collector (§9A, FR1).

Compliant-by-default source (P5): the public Apple Marketing Tools RSS feed.
One row per (app, country, list, category, date).
"""
from __future__ import annotations

import datetime as dt
import logging

from .http import RateLimited, polite_get

log = logging.getLogger(__name__)

RSS = "https://rss.applemarketingtools.com/api/v2/{country}/apps/{feed}/{limit}/apps.json"

# Apple feed slugs we support mapped to our canonical list_type names.
FEEDS = {
    "top-free": "top-free",
    "top-paid": "top-paid",
    "top-grossing": "top-grossing",
}


def fetch_apple_chart(
    country: str = "us", feed: str = "top-free", limit: int = 100
) -> list[dict]:
    """Fetch one Apple RSS chart. Returns rank rows; ``[]`` on rate-limit/error.

    Each row carries metadata fields too (name/developer) so the caller can
    upsert ``apps`` and insert ``rank_history`` from a single fetch.
    """
    url = RSS.format(country=country, feed=feed, limit=limit)
    today = dt.date.today().isoformat()
    try:
        r = polite_get(url)
        results = r.json()["feed"]["results"]
    except RateLimited:
        log.warning("apple_rss rate-limited for %s/%s; skipping", country, feed)
        return []
    except Exception as exc:  # network / JSON / schema drift — non-fatal (FR7)
        log.warning("apple_rss fetch failed for %s/%s: %s", country, feed, exc)
        return []

    rows: list[dict] = []
    for i, a in enumerate(results):
        rows.append(
            {
                "app_id": a["id"],
                "platform": "ios",
                "name": a.get("name"),
                "developer": a.get("artistName"),
                "category": (a.get("genres") or [{}])[0].get("name", "all")
                if a.get("genres")
                else "all",
                "rank": i + 1,
                "list_type": feed,
                "country": country,
                "captured_on": today,
            }
        )
    return rows
