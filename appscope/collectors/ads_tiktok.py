"""TikTok ad collector (§9C, FR5; OPTIONAL, OFF by default; LOCAL ONLY P8).

TikTok's Commercial Content Library / ads are not available through a fully
open API for commercial use; any scraping path is ToS-risky and fragile. This
module is disabled unless ``ads.tiktok_enabled`` is true AND an operator-supplied
fetcher is provided (P5, N6). It never emits a USD/spend figure (P3).
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Callable

log = logging.getLogger(__name__)


def fetch_tiktok_ads(
    app_id: str,
    query: str,
    *,
    enabled: bool = False,
    fetcher: Callable[[str], list[dict]] | None = None,
) -> list[dict]:
    """Return ad-snapshot rows from TikTok. ``[]`` unless explicitly enabled and
    an operator fetcher is supplied."""
    if not enabled or fetcher is None:
        log.info("tiktok ads disabled or no fetcher; skipping %s", app_id)
        return []

    today = dt.date.today().isoformat()
    try:
        raw = fetcher(query)
    except Exception as exc:
        log.warning("tiktok ads fetch failed for %s: %s", app_id, exc)
        return []

    rows: list[dict] = []
    for c in raw:
        rows.append(
            {
                "app_id": app_id,
                "platform": "tiktok",
                "creative_id": c.get("creative_id") or c.get("id"),
                "ad_snapshot_url": c.get("url"),
                "first_seen": (c.get("first_shown") or today)[:10],
                "last_seen": (c.get("last_shown") or today)[:10],
                "still_active": 1 if c.get("still_active", True) else 0,
            }
        )
    return rows
