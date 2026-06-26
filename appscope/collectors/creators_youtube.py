"""YouTube creator-discovery collector (§9D, FR6; LOCAL ONLY, never federated P8).

YouTube Data API is the one fully-compliant organic-discovery route (P5). We
search for videos mentioning a tracked app and score each with the rule-based
classifier (§9D). Creator handles are personal data and never leave the machine.
"""
from __future__ import annotations

import datetime as dt
import logging

from ..creators.classify import app_mention_score
from .http import RateLimited, polite_get

log = logging.getLogger(__name__)

SEARCH = "https://www.googleapis.com/youtube/v3/search"


def youtube_search(api_key: str, query: str, max_results: int = 25) -> list[dict]:
    """Raw YouTube Data API search. Returns ``items`` or ``[]`` on error."""
    try:
        r = polite_get(
            SEARCH,
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max_results,
                "key": api_key,
            },
        )
        return r.json().get("items", [])
    except RateLimited:
        log.warning("youtube search rate-limited/quota for %r; skipping", query)
        return []
    except Exception as exc:
        log.warning("youtube search failed for %r: %s", query, exc)
        return []


def discover_creator_mentions(
    api_key: str | None,
    app_id: str,
    app_name: str | None,
    package_id: str | None = None,
    brand_hashtags: tuple[str, ...] = (),
    max_results: int = 25,
) -> list[dict]:
    """Discover + score YouTube videos mentioning the app.

    Returns ``creator_mentions`` rows (with ``mention_confidence``). Returns
    ``[]`` if no API key is configured.
    """
    if not api_key:
        log.info("YOUTUBE_API_KEY not set; skipping creator discovery for %s", app_id)
        return []

    query = app_name or package_id or app_id
    items = youtube_search(api_key, query, max_results=max_results)
    today = dt.date.today().isoformat()
    rows: list[dict] = []
    for it in items:
        snippet = it.get("snippet", {})
        text = " ".join(
            str(snippet.get(k, "")) for k in ("title", "description", "channelTitle")
        )
        conf = app_mention_score(text, app_name, package_id, brand_hashtags)
        video_id = (it.get("id") or {}).get("videoId")
        if not video_id:
            continue
        rows.append(
            {
                "app_id": app_id,
                "source": "youtube",
                "video_id": video_id,
                "channel": snippet.get("channelTitle"),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "mention_confidence": conf,
                "captured_on": today,
            }
        )
    return rows
