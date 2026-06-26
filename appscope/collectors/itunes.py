"""iTunes lookup collector (§9A, FR2).

Compliant-by-default metadata source for iOS apps: the public iTunes lookup
endpoint. Returns name, developer, category, price, free/paid and rating count.
"""
from __future__ import annotations

import datetime as dt
import logging

from .http import RateLimited, polite_get

log = logging.getLogger(__name__)

LOOKUP = "https://itunes.apple.com/lookup"


def fetch_itunes_metadata(app_id: str, country: str = "us") -> dict | None:
    """Look up iOS app metadata by numeric track id. ``None`` on failure."""
    try:
        r = polite_get(LOOKUP, params={"id": app_id, "country": country})
        data = r.json()
        results = data.get("results") or []
    except RateLimited:
        log.warning("itunes lookup rate-limited for %s; skipping", app_id)
        return None
    except Exception as exc:
        log.warning("itunes lookup failed for %s: %s", app_id, exc)
        return None

    if not results:
        return None
    d = results[0]
    price = d.get("price")
    if price is None:
        price = d.get("formattedPrice")
        price = 0.0 if (isinstance(price, str) and price.lower() in {"free", ""}) else price
    try:
        price_usd = float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        price_usd = 0.0
    return {
        "app_id": str(app_id),
        "platform": "ios",
        "name": d.get("trackName"),
        "developer": d.get("artistName"),
        "category": d.get("primaryGenreName"),
        "price_usd": price_usd,
        "is_free": 1 if price_usd <= 0 else 0,
        "rating_count": d.get("userRatingCount"),
        "country": country,
        "captured_on": dt.date.today().isoformat(),
    }
