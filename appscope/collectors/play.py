"""Google Play metadata + install-bucket collector (§9A, FR2/FR3).

Uses the maintained Python ``google-play-scraper`` (JoMingyu), which exposes
``minInstalls`` and ``realInstalls`` — the anchor source for federated
calibration. Throttle: the library raises on rate-limiting; we catch it (FR7).
"""
from __future__ import annotations

import datetime as dt
import logging

log = logging.getLogger(__name__)

try:  # optional dependency; collector degrades to a clear error if absent
    from google_play_scraper import app as _gp_app
    from google_play_scraper.exceptions import (  # type: ignore
        NotFoundError,
    )

    _HAVE_GPS = True
except Exception:  # pragma: no cover - import guard
    _gp_app = None  # type: ignore
    NotFoundError = Exception  # type: ignore
    _HAVE_GPS = False


def fetch_play_app(package_id: str, country: str = "us", lang: str = "en") -> dict | None:
    """Fetch Play metadata + install buckets for one package. ``None`` on failure.

    The returned dict contains both the ``apps`` metadata fields and the
    ``install_buckets`` fields (min/real installs) for the caller to split.
    """
    if not _HAVE_GPS:
        log.error(
            "google-play-scraper not installed; cannot fetch Play data for %s",
            package_id,
        )
        return None
    try:
        d = _gp_app(package_id, lang=lang, country=country)
    except NotFoundError:
        log.warning("play app not found: %s", package_id)
        return None
    except Exception as exc:  # rate-limit / network — non-fatal (FR7)
        log.warning("play fetch failed for %s: %s (throttle and retry later)", package_id, exc)
        return None

    return {
        "app_id": package_id,
        "platform": "android",
        "name": d.get("title"),
        "developer": d.get("developer"),
        "category": d.get("genre"),
        "price_usd": (d.get("price") or 0.0),
        "is_free": 1 if d.get("free") else 0,
        "rating_count": d.get("ratings"),
        "min_installs": d.get("minInstalls"),
        "real_installs": d.get("realInstalls"),
        "country": country,
        "captured_on": dt.date.today().isoformat(),
    }
