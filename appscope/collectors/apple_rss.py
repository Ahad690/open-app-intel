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
                # The CHART segment, not the app's genre. These feeds are the
                # overall top-free/top-paid charts, so the segment is "all" — the
                # same convention play_charts uses for Play's APPLICATION chart.
                #
                # This field previously carried a.genres[0].name, i.e. the app's
                # own genre *in the country's language*. That conflated "which
                # chart this rank came from" with "what genre this app is", and
                # localization shattered one real genre into many segments:
                # Education / Éducation / Bildung / Educação / 教育 counted as
                # five. Widening to 7 countries turned 2 iOS category values into
                # 99, which would fragment any pooling keyed on the segment.
                # The app's genre is owned by the metadata collector
                # (itunes.primaryGenreName), which is where it belongs.
                "category": "all",
                "rank": i + 1,
                "list_type": feed,
                "country": country,
                "captured_on": today,
            }
        )
    return rows
