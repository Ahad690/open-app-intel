"""Anchor derivation + pooled scale calibration (§9B, FR8/FR9).

The Garg-Telang power law is ``d(rank) = b * rank^(-a)``. The shape ``a`` comes
from public list priors; the scale ``b`` is calibrated from *observed* download
flows. An observed flow is the delta between two Android ``realInstalls``
captures over a window, paired with the app's rank in that window — a real
download flow at a known rank.

Federation closes the weak link: pooling these anchors across self-hosters
(local + community) lets ``scale_b`` reach >=5 anchors per segment and graduate
estimates from LOW to MEDIUM (KPI K6). The dataset pools *observations*, never
fabricated numbers.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Iterable

# Shape priors per (platform, list_type) — §9B / §17.
SHAPE_A: dict[tuple[str, str], float] = {
    ("ios", "top-paid"): 0.944,
    ("ios", "top-free"): 0.90,
    ("ios", "top-grossing"): 0.92,
    ("android", "top-paid"): 0.985,
    ("android", "top-free"): 0.95,
    ("android", "top-grossing"): 0.96,
}
DEFAULT_A = 0.95


def shape_a(platform: str, list_type: str) -> float:
    return SHAPE_A.get((platform, list_type), DEFAULT_A)


def relative_index(rank: int | float, a: float) -> float:
    """The unit-scale relative demand at a rank: ``rank^(-a)``."""
    return rank ** (-a)


def _as_date(value: object) -> dt.date:
    """Coerce a date / ISO-string into a ``date`` (anchors may come from the DB)."""
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    raise TypeError(f"unsupported date value: {value!r}")


# A ``realInstalls`` figure is a *worldwide cumulative* counter Google refreshes in
# lumpy steps, not a live per-day meter. Left unguarded, two artifacts masquerade as
# huge download flows and (over short windows) blow past every sanity ceiling:
#   1. a refresh that lands as the app crosses a ``minInstalls`` bucket boundary
#      (1M/5M/10M/50M/100M...), and
#   2. any jump so large it implies a mature app more than replacing its install
#      base in a month.
# Both are refresh noise, not observed flow — so we refuse to mint them as anchors
# (honesty over a fabricated number). The automerge L4 ceiling is the receiving-side
# backstop; this is the sending-side root fix.
MAX_MONTHLY_GROWTH_RATIO = 1.0  # implied monthly flow may not exceed the base install count


def derive_flow_anchor(
    bucket_rows: list[dict], rank_rows: list[dict]
) -> dict | None:
    """Derive a real observed download-flow anchor from >=2 install-bucket captures.

    ``bucket_rows``: ``[{real_installs, min_installs?, captured_on}...]`` sorted by
    date. ``rank_rows``: ``[{rank, captured_on}...]`` over the same window.
    Returns ``{platform:'android', rank, observed_downloads, window_days}`` or
    ``None`` when there is no valid positive-growth anchor, or when the delta is a
    counter-refresh artifact (bucket-boundary crossing / implausible growth) rather
    than a genuine download flow.
    """
    if len(bucket_rows) < 2:
        return None
    b0, b1 = bucket_rows[0], bucket_rows[-1]
    if not (b0.get("real_installs") and b1.get("real_installs")):
        return None
    delta = b1["real_installs"] - b0["real_installs"]
    window_days = (_as_date(b1["captured_on"]) - _as_date(b0["captured_on"])).days
    ranks = sorted(r["rank"] for r in rank_rows if r.get("rank"))
    if delta <= 0 or window_days <= 0 or not ranks:
        return None  # not an anchor

    # Guard 1 — bucket-boundary crossing. Different ``minInstalls`` buckets between
    # the two captures => the ``realInstalls`` delta is contaminated by a boundary
    # counter refresh, not a real flow.
    m0, m1 = b0.get("min_installs"), b1.get("min_installs")
    if m0 is not None and m1 is not None and m0 != m1:
        return None

    # Guard 2 — implausible growth. A cumulative counter gaining more than its own
    # base in a month is a refresh artifact, not organic installs.
    monthly = delta * 30.0 / window_days
    if monthly > b0["real_installs"] * MAX_MONTHLY_GROWTH_RATIO:
        return None

    return {
        "platform": "android",
        "rank": ranks[len(ranks) // 2],
        "observed_downloads": delta,
        "window_days": window_days,
    }


def calibrate_scale(
    anchors: Iterable[dict], a: float
) -> tuple[float | None, int]:
    """Fit ``scale_b`` from pooled anchors (local + community).

    Each anchor is normalized to a monthly figure; ``scale_b`` is the geometric
    mean in log space (robust to outliers). Returns ``(scale_b, n)`` or
    ``(None, 0)`` if no usable anchors.
    """
    logs: list[float] = []
    for an in anchors:
        rank = an.get("rank")
        obs = an.get("observed_downloads")
        win = an.get("window_days")
        if rank and obs and win and rank > 0 and obs > 0 and win > 0:
            monthly = obs * 30.0 / win
            logs.append(math.log(monthly / relative_index(rank, a)))
    if not logs:
        return None, 0
    return math.exp(sum(logs) / len(logs)), len(logs)
