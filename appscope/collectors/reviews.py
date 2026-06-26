"""Reviews collector across both stores (§9A, FR4).

iOS: public Apple RSS customer-reviews feed.
Android: ``google-play-scraper`` reviews (when installed).
Returns deduped review rows (id, rating, date); dedup at the DB layer by
(app_id, source, review_id).
"""
from __future__ import annotations

import datetime as dt
import logging

from .http import RateLimited, polite_get

log = logging.getLogger(__name__)

IOS_REVIEWS = (
    "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortby=mostrecent/json"
)

try:
    from google_play_scraper import Sort
    from google_play_scraper import reviews as _gp_reviews

    _HAVE_GPS = True
except Exception:  # pragma: no cover
    _gp_reviews = None  # type: ignore
    Sort = None  # type: ignore
    _HAVE_GPS = False


def fetch_ios_reviews(app_id: str, country: str = "us") -> list[dict]:
    """Fetch recent iOS reviews via the public Apple RSS reviews feed."""
    url = IOS_REVIEWS.format(country=country, app_id=app_id)
    today = dt.date.today().isoformat()
    try:
        r = polite_get(url)
        entries = r.json().get("feed", {}).get("entry", [])
    except RateLimited:
        log.warning("ios reviews rate-limited for %s; skipping", app_id)
        return []
    except Exception as exc:
        log.warning("ios reviews fetch failed for %s: %s", app_id, exc)
        return []

    # The first entry is the app summary, not a review; skip dict-typed app entry.
    rows: list[dict] = []
    for e in entries:
        rid = (e.get("id") or {}).get("label")
        rating = (e.get("im:rating") or {}).get("label")
        if not rid or rating is None:
            continue
        try:
            rating_int = int(rating)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "app_id": str(app_id),
                "source": "ios",
                "review_id": rid,
                "rating": rating_int,
                "captured_on": today,
            }
        )
    return rows


def fetch_android_reviews(
    package_id: str, country: str = "us", lang: str = "en", count: int = 100
) -> list[dict]:
    """Fetch recent Android reviews via google-play-scraper (when installed)."""
    if not _HAVE_GPS:
        log.error("google-play-scraper not installed; cannot fetch Android reviews")
        return []
    today = dt.date.today().isoformat()
    try:
        result, _ = _gp_reviews(
            package_id, lang=lang, country=country, sort=Sort.NEWEST, count=count
        )
    except Exception as exc:  # rate-limit / network — non-fatal (FR7)
        log.warning("android reviews fetch failed for %s: %s", package_id, exc)
        return []

    rows: list[dict] = []
    for rv in result:
        rid = rv.get("reviewId")
        if not rid:
            continue
        rows.append(
            {
                "app_id": package_id,
                "source": "android",
                "review_id": rid,
                "rating": rv.get("score"),
                "captured_on": today,
            }
        )
    return rows
