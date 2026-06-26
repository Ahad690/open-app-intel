"""Ad creative & cadence intensity proxies (§9C, FR14/FR15).

This module computes *intensity proxies* and a mandatory disclaimer. It MUST
NEVER output a USD spend figure (P3, KPI K2 hard gate): dollar ad spend is not
derivable from public data. This data is LOCAL ONLY and never federated (P8).
"""
from __future__ import annotations

import datetime as dt

_DISCLAIMER = (
    "spend-intensity proxy, NOT USD spend; dollar ad spend is not "
    "derivable from public data and is never estimated here"
)


def _as_date(value: object) -> dt.date:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise TypeError(f"unsupported date value: {value!r}")


def ad_intensity_proxies(snapshots: list[dict]) -> dict:
    """Compute intensity proxies from ad snapshots.

    Each snapshot: ``{platform, first_seen, last_seen, still_active}``.
    Always includes ``disclaimer``; never includes any USD/spend field.
    """
    if not snapshots:
        return {"active_ad_count": 0, "total_creatives_seen": 0, "disclaimer": _DISCLAIMER}

    longevities = sorted(
        (_as_date(s["last_seen"]) - _as_date(s["first_seen"])).days + 1 for s in snapshots
    )
    span = max(longevities) or 1
    refresh = len(snapshots) / max(span / 7.0, 1)
    active = sum(1 for s in snapshots if s.get("still_active"))
    return {
        "active_ad_count": active,
        "total_creatives_seen": len(snapshots),
        "median_ad_longevity_days": longevities[len(longevities) // 2],
        "platform_mix": sorted({s["platform"] for s in snapshots}),
        "creative_refresh_per_week": round(refresh, 2),
        "intensity_tier": (
            "HIGH"
            if active >= 20 or refresh >= 5
            else "MEDIUM"
            if active >= 5 or refresh >= 1
            else "LOW"
        ),
        "disclaimer": _DISCLAIMER,
    }
