"""Google Ads Transparency collector (§9C, FR5; LOCAL ONLY, never federated P8).

The Google Ads Transparency Center exposes advertiser creatives and run dates
publicly, but there is no official JSON API; access requires the public
endpoint or a third-party provider (e.g. SerpApi). This collector is therefore
opt-in and operator-responsibility (P5, N6): it returns ``[]`` unless a fetcher
is wired up, and never emits a USD/spend figure (P3).
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Callable

log = logging.getLogger(__name__)

# Public Transparency Center surface (HTML/region-specific JSON); operator wires
# an actual fetcher to respect the relevant ToS in their jurisdiction.
TRANSPARENCY_BASE = "https://adstransparency.google.com"


def fetch_google_ads(
    app_id: str,
    advertiser_query: str,
    *,
    fetcher: Callable[[str], list[dict]] | None = None,
    country: str = "US",
) -> list[dict]:
    """Return ad-snapshot rows from the Google Ads Transparency Center.

    ``fetcher`` is an operator-supplied callable that performs the actual lookup
    (e.g. a SerpApi client) and returns raw creative dicts with at least
    ``creative_id``, ``first_shown``/``last_shown``. Without it, returns ``[]``.
    """
    if fetcher is None:
        log.info(
            "google ads transparency fetcher not configured; skipping %s "
            "(opt-in, operator responsibility)",
            app_id,
        )
        return []

    today = dt.date.today().isoformat()
    try:
        raw = fetcher(advertiser_query)
    except Exception as exc:
        log.warning("google ads transparency fetch failed for %s: %s", app_id, exc)
        return []

    rows: list[dict] = []
    for c in raw:
        rows.append(
            {
                "app_id": app_id,
                "platform": "google",
                "creative_id": c.get("creative_id") or c.get("id"),
                "ad_snapshot_url": c.get("url") or c.get("ad_snapshot_url"),
                "first_seen": (c.get("first_shown") or today)[:10],
                "last_seen": (c.get("last_shown") or today)[:10],
                "still_active": 1 if c.get("still_active", True) else 0,
            }
        )
    return rows
