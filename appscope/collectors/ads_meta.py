"""Meta Ad Library collector (§9C, FR5; LOCAL ONLY, never federated P8).

Uses the OFFICIAL Meta Ad Library API (compliant default, P5). For commercial
app ads, Meta exposes creative + page name + ad_snapshot_url + platforms +
ad_delivery_start_time (spend/impressions only for EU/UK + political ads — which
we never request as dollars; P3). Snapshot daily to build first_seen/last_seen.

Requires a Meta Ad Library token in the env var named by config (META_AD_TOKEN);
no-ops cleanly without it.
"""
from __future__ import annotations

import datetime as dt
import logging

from .http import RateLimited, polite_get

log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v19.0/ads_archive"


def fetch_meta_ads(
    app_id: str,
    search_terms: str,
    access_token: str | None,
    country: str = "US",
    limit: int = 100,
) -> list[dict]:
    """Fetch ad-snapshot rows for ``app_id`` from the Meta Ad Library.

    Returns rows shaped for ``ad_snapshots``. No USD/spend field is ever emitted
    (P3). Returns ``[]`` (non-fatal) on missing token, rate-limit, or error.
    """
    if not access_token:
        log.info("META_AD_TOKEN not set; skipping Meta Ad Library for %s", app_id)
        return []

    today = dt.date.today().isoformat()
    params = {
        "search_terms": search_terms,
        "ad_reached_countries": f"['{country}']",
        "ad_active_status": "ALL",
        # Deliberately NOT requesting spend/impressions — proxies only (P3).
        "fields": "id,ad_snapshot_url,page_name,publisher_platforms,ad_delivery_start_time,ad_delivery_stop_time",
        "limit": limit,
        "access_token": access_token,
    }
    try:
        r = polite_get(GRAPH, params=params)
        data = r.json().get("data", [])
    except RateLimited:
        log.warning("meta ad library rate-limited for %s; skipping", app_id)
        return []
    except Exception as exc:
        log.warning("meta ad library fetch failed for %s: %s", app_id, exc)
        return []

    rows: list[dict] = []
    for ad in data:
        start = (ad.get("ad_delivery_start_time") or today)[:10]
        stop = ad.get("ad_delivery_stop_time")
        still_active = 0 if stop else 1
        rows.append(
            {
                "app_id": app_id,
                "platform": "meta",
                "creative_id": ad.get("id"),
                "ad_snapshot_url": ad.get("ad_snapshot_url"),
                "first_seen": start,
                "last_seen": (stop[:10] if stop else today),
                "still_active": still_active,
            }
        )
    return rows
