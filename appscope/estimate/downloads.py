"""Download estimation (§9B, FR10/FR11/FR13).

Produces a *range* with explicit confidence, method and the anchor count behind
it. Confidence is capped at MEDIUM forever (P2): HIGH is reserved for directly
observed facts, never for a modeled estimate. Install-bucket sanity bounds are
enforced (P4).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .calibrate import relative_index, shape_a

METHOD = "garg_telang_powerlaw"

# Defaults mirror config.json (§12); callers may override for determinism (P7).
DEFAULT_MIN_ANCHORS_FOR_MEDIUM = 5
DEFAULT_BAND_FACTOR_MEDIUM = 1.8
DEFAULT_BAND_FACTOR_LOW = 3.0
DEFAULT_BUCKET_TOLERANCE = 1.25


@dataclass
class DownloadEstimate:
    """Estimate envelope for downloads (a subset of the P1 envelope)."""

    point: float | None
    low: float | None
    high: float | None
    confidence: str
    method: str
    anchors_used: int
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "point": self.point,
            "low": self.low,
            "high": self.high,
            "confidence": self.confidence,
            "method": self.method,
            "anchors_used": self.anchors_used,
            "flags": list(self.flags),
        }


def estimate_downloads(
    rank: int,
    platform: str,
    list_type: str,
    scale_b: float | None,
    n_anchors: int,
    *,
    min_anchors_for_medium: int = DEFAULT_MIN_ANCHORS_FOR_MEDIUM,
    band_factor_medium: float = DEFAULT_BAND_FACTOR_MEDIUM,
    band_factor_low: float = DEFAULT_BAND_FACTOR_LOW,
) -> DownloadEstimate:
    """Estimate monthly downloads at ``rank`` for a calibrated segment.

    Uncalibrated segments return ``NONE`` confidence with a ``no_anchor`` flag.
    Confidence is never HIGH (P2): MEDIUM when anchors are sufficient, else LOW.
    """
    a = shape_a(platform, list_type)
    if scale_b is None or n_anchors == 0:
        return DownloadEstimate(None, None, None, "NONE", "uncalibrated", 0, ["no_anchor"])

    point = scale_b * relative_index(rank, a)
    if n_anchors >= min_anchors_for_medium:
        factor, conf = band_factor_medium, "MEDIUM"
    else:
        factor, conf = band_factor_low, "LOW"  # never HIGH (P2)
    return DownloadEstimate(
        round(point),
        round(point / factor),
        round(point * factor),
        conf,
        METHOD,
        n_anchors,
        [],
    )


def enforce_install_bucket(
    est: DownloadEstimate,
    real_installs: int | None,
    app_age_days: int | float,
    *,
    bucket_tolerance: float = DEFAULT_BUCKET_TOLERANCE,
) -> DownloadEstimate:
    """Sanity-bound a cumulative estimate against the Google install bucket (P4).

    If the implied cumulative downloads exceed the observed real-installs bucket
    beyond tolerance, flag it and downgrade confidence to LOW (never silently
    emit a bucket-violating number).
    """
    if est.point is None or not real_installs:
        return est
    implied_cumulative = est.point * max(app_age_days / 30.0, 1)
    if implied_cumulative > real_installs * bucket_tolerance:
        if "exceeds_install_bucket" not in est.flags:
            est.flags.append("exceeds_install_bucket")
        est.confidence = "LOW"
    return est
