"""Stage 3 tests — ad intensity proxies; no-dollar hard gate (§14, K2, P3)."""
from __future__ import annotations

import datetime as dt

from appscope.ads.intensity import _DISCLAIMER, ad_intensity_proxies

# Any of these substrings in a key would signal a forbidden USD/spend field.
_FORBIDDEN_KEY_SUBSTRINGS = ("spend", "usd", "dollar", "cost", "cpm", "budget", "revenue")


def _has_forbidden_key(d: dict) -> bool:
    for k in d:
        kl = str(k).lower()
        # 'disclaimer' legitimately contains 'spend' in its *value*, not key.
        if any(sub in kl for sub in _FORBIDDEN_KEY_SUBSTRINGS):
            return True
    return False


def _snap(platform, first, last, active):
    return {
        "platform": platform,
        "first_seen": dt.date.fromisoformat(first),
        "last_seen": dt.date.fromisoformat(last),
        "still_active": active,
    }


def test_empty_snapshots_have_disclaimer_no_dollars():
    out = ad_intensity_proxies([])
    assert out["active_ad_count"] == 0
    assert out["disclaimer"] == _DISCLAIMER
    assert not _has_forbidden_key(out)


def test_intensity_always_has_disclaimer():
    snaps = [_snap("meta", "2025-01-01", "2025-01-20", 1)]
    out = ad_intensity_proxies(snaps)
    assert "disclaimer" in out
    assert out["disclaimer"] == _DISCLAIMER


def test_intensity_never_emits_usd_field():
    snaps = [
        _snap("meta", "2025-01-01", "2025-02-01", 1),
        _snap("google", "2025-01-10", "2025-01-15", 0),
        _snap("meta", "2025-01-05", "2025-01-25", 1),
    ]
    out = ad_intensity_proxies(snaps)
    assert not _has_forbidden_key(out), f"forbidden USD-like key in {list(out)}"


def test_intensity_tiers():
    high = [_snap("meta", "2025-01-01", "2025-01-02", 1) for _ in range(20)]
    assert ad_intensity_proxies(high)["intensity_tier"] == "HIGH"

    low = [_snap("meta", "2025-01-01", "2025-03-01", 0)]
    assert ad_intensity_proxies(low)["intensity_tier"] == "LOW"


def test_platform_mix_and_active_count():
    snaps = [
        _snap("meta", "2025-01-01", "2025-01-20", 1),
        _snap("google", "2025-01-01", "2025-01-10", 0),
        _snap("tiktok", "2025-01-01", "2025-01-05", 1),
    ]
    out = ad_intensity_proxies(snaps)
    assert out["active_ad_count"] == 2
    assert out["platform_mix"] == ["google", "meta", "tiktok"]
    assert out["total_creatives_seen"] == 3


def test_accepts_iso_string_dates():
    snaps = [{"platform": "meta", "first_seen": "2025-01-01", "last_seen": "2025-01-20", "still_active": 1}]
    out = ad_intensity_proxies(snaps)
    assert out["median_ad_longevity_days"] == 20
