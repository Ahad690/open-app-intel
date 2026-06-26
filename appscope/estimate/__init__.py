"""Estimation engine package (§9B).

``estimate_app`` ties calibration + downloads + revenue + sanity bounds into the
single P1 envelope used by the REST API and MCP server.
"""
from __future__ import annotations

import datetime as dt

from .calibrate import calibrate_scale, derive_flow_anchor, relative_index, shape_a
from .downloads import (
    DownloadEstimate,
    enforce_install_bucket,
    estimate_downloads,
)
from .revenue import STORE_CUT, estimate_revenue

__all__ = [
    "calibrate_scale",
    "derive_flow_anchor",
    "relative_index",
    "shape_a",
    "DownloadEstimate",
    "enforce_install_bucket",
    "estimate_downloads",
    "STORE_CUT",
    "estimate_revenue",
    "estimate_app",
]


def estimate_app(db, app_id: str, country: str = "us", config=None) -> dict:
    """Produce the full P1 estimate envelope for one app.

    Returns ``{value, low, high, confidence, method, sources, flags, ...}``.
    Confidence is never HIGH (P2); free-app revenue is never fabricated (N4).
    """
    from ..config import Config

    cfg = config or Config()
    est_cfg = cfg.estimator

    app = db.get_app(app_id) or {}
    platform = app.get("platform") or ("ios" if app_id.isdigit() else "android")

    latest = db.get_latest_rank(app_id, country=country)
    sources: list[str] = []
    flags: list[str] = []

    if not latest or latest.get("rank") is None:
        return {
            "app_id": app_id,
            "country": country,
            "value": None,
            "low": None,
            "high": None,
            "revenue": None,
            "confidence": "NONE",
            "method": "uncalibrated",
            "sources": sources,
            "flags": ["no_rank_observed"],
        }

    rank = latest["rank"]
    list_type = latest.get("list_type") or "top-free"
    category = app.get("category") or latest.get("category") or "all"
    sources.append(f"rank_history:{latest.get('captured_on')}")

    calib = db.get_calibration(platform, list_type, category, country)
    scale_b = calib["scale_b"] if calib else None
    n_anchors = calib["n_anchors"] if calib else 0
    if calib:
        sources.append(f"calibration:{calib.get('updated_on')}")

    est = estimate_downloads(
        rank,
        platform,
        list_type,
        scale_b,
        n_anchors,
        min_anchors_for_medium=est_cfg.min_anchors_for_medium,
        band_factor_medium=est_cfg.band_factor_medium,
        band_factor_low=est_cfg.band_factor_low,
    )

    # Sanity-bound against the Android install bucket (P4).
    buckets = db.get_install_buckets(app_id)
    if buckets:
        real_installs = buckets[-1].get("real_installs")
        first_seen = app.get("first_seen")
        app_age_days = _age_days(first_seen)
        est = enforce_install_bucket(
            est, real_installs, app_age_days, bucket_tolerance=est_cfg.bucket_tolerance
        )
        sources.append(f"install_buckets:{buckets[-1].get('captured_on')}")

    flags.extend(est.flags)

    revenue, rev_flags = estimate_revenue(
        est.point,
        app.get("price_usd"),
        bool(app.get("is_free")),
        cut=est_cfg.store_cut,
    )
    flags.extend(rev_flags)

    return {
        "app_id": app_id,
        "country": country,
        "value": est.point,
        "low": est.low,
        "high": est.high,
        "revenue": revenue,
        "confidence": est.confidence,
        "method": est.method,
        "anchors_used": est.anchors_used,
        "sources": sources,
        "flags": flags,
    }


def _age_days(first_seen: str | None) -> float:
    if not first_seen:
        return 1.0
    try:
        d = dt.date.fromisoformat(str(first_seen))
    except ValueError:
        return 1.0
    return max((dt.date.today() - d).days, 1)
