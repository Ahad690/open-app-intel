"""Stage 2 tests — anchor derivation, calibration, download estimates (§14)."""
from __future__ import annotations

import datetime as dt

import pytest

from appscope.estimate.calibrate import (
    calibrate_scale,
    derive_flow_anchor,
    shape_a,
)
from appscope.estimate.downloads import (
    DownloadEstimate,
    enforce_install_bucket,
    estimate_downloads,
)


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def test_derive_flow_anchor_from_increasing_buckets():
    buckets = [
        {"real_installs": 1_000_000, "captured_on": _d("2025-01-01")},
        {"real_installs": 1_300_000, "captured_on": _d("2025-01-31")},
    ]
    ranks = [{"rank": 12, "captured_on": _d("2025-01-15")}]
    anchor = derive_flow_anchor(buckets, ranks)
    assert anchor is not None
    assert anchor["platform"] == "android"
    assert anchor["observed_downloads"] == 300_000
    assert anchor["window_days"] == 30
    assert anchor["rank"] == 12


def test_derive_flow_anchor_none_on_nonpositive_growth():
    buckets = [
        {"real_installs": 1_300_000, "captured_on": _d("2025-01-01")},
        {"real_installs": 1_300_000, "captured_on": _d("2025-01-31")},  # zero growth
    ]
    ranks = [{"rank": 12, "captured_on": _d("2025-01-15")}]
    assert derive_flow_anchor(buckets, ranks) is None


def test_derive_flow_anchor_none_without_two_buckets():
    assert derive_flow_anchor([{"real_installs": 1, "captured_on": _d("2025-01-01")}], []) is None


def test_derive_flow_anchor_none_without_ranks():
    buckets = [
        {"real_installs": 1_000_000, "captured_on": _d("2025-01-01")},
        {"real_installs": 1_300_000, "captured_on": _d("2025-01-31")},
    ]
    assert derive_flow_anchor(buckets, []) is None


def test_derive_flow_anchor_accepts_iso_strings():
    buckets = [
        {"real_installs": 1_000_000, "captured_on": "2025-01-01"},
        {"real_installs": 1_300_000, "captured_on": "2025-01-31"},
    ]
    ranks = [{"rank": 5, "captured_on": "2025-01-10"}]
    anchor = derive_flow_anchor(buckets, ranks)
    assert anchor and anchor["window_days"] == 30


def test_calibrate_scale_recovers_known_scale():
    # Build anchors exactly on d(rank)=b*rank^-a with b=3,000,000, monthly window.
    a = shape_a("android", "top-free")
    b = 3_000_000.0
    anchors = [
        {"rank": r, "observed_downloads": round(b * r ** (-a)), "window_days": 30}
        for r in (1, 5, 10, 20, 50)
    ]
    scale_b, n = calibrate_scale(anchors, a)
    assert n == 5
    assert scale_b == pytest.approx(b, rel=0.02)


def test_calibrate_scale_empty():
    assert calibrate_scale([], 0.95) == (None, 0)


def test_estimate_medium_confidence_with_enough_anchors():
    est = estimate_downloads(
        rank=10, platform="android", list_type="top-free", scale_b=3_000_000.0, n_anchors=6
    )
    assert est.confidence == "MEDIUM"
    assert est.method == "garg_telang_powerlaw"
    assert est.low < est.point < est.high
    assert est.anchors_used == 6


def test_estimate_low_confidence_with_few_anchors():
    est = estimate_downloads(
        rank=10, platform="android", list_type="top-free", scale_b=3_000_000.0, n_anchors=3
    )
    assert est.confidence == "LOW"
    # LOW bands are wider than MEDIUM bands.
    assert est.high / est.point == pytest.approx(3.0, rel=1e-6)


def test_estimate_none_without_anchors():
    est = estimate_downloads(
        rank=10, platform="android", list_type="top-free", scale_b=None, n_anchors=0
    )
    assert est.confidence == "NONE"
    assert est.flags == ["no_anchor"]
    assert est.point is None


def test_estimate_never_high():
    # Even with a huge anchor count, confidence is capped at MEDIUM (P2).
    for n in (5, 50, 5000):
        est = estimate_downloads(
            rank=1, platform="ios", list_type="top-free", scale_b=2_000_000.0, n_anchors=n
        )
        assert est.confidence in {"LOW", "MEDIUM", "NONE"}
        assert est.confidence != "HIGH"


def test_enforce_install_bucket_flags_violation():
    est = DownloadEstimate(
        point=1_000_000, low=500_000, high=2_000_000,
        confidence="MEDIUM", method="garg_telang_powerlaw", anchors_used=6,
    )
    # implied cumulative over 30 days = 1,000,000 > 100,000*1.25 -> violation
    out = enforce_install_bucket(est, real_installs=100_000, app_age_days=30)
    assert "exceeds_install_bucket" in out.flags
    assert out.confidence == "LOW"


def test_enforce_install_bucket_ok_when_within_bound():
    est = DownloadEstimate(
        point=100_000, low=50_000, high=200_000,
        confidence="MEDIUM", method="garg_telang_powerlaw", anchors_used=6,
    )
    out = enforce_install_bucket(est, real_installs=10_000_000, app_age_days=30)
    assert "exceeds_install_bucket" not in out.flags
    assert out.confidence == "MEDIUM"
