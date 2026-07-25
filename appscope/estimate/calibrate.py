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
# Absolute plausibility ceiling, mirrored from the receiving side's anti-abuse
# config (``automerge_prs.DEFAULT_ABUSE['max_monthly_downloads']``). The relative
# guard above is not sufficient on its own: a billion-install app can gain less
# than its own base and still imply an absurd monthly flow, which the receiving
# side would hold. Keeping both sides consistent means we never mint an anchor we
# know would be rejected.
MAX_MONTHLY_DOWNLOADS = 100_000_000
# Lower bound, same failure mode from the other direction: between refreshes the
# counter barely moves, so a top-chart app can appear to have gained ~10 installs
# in three days. We cannot distinguish "genuinely gained 10" from "counter has not
# refreshed yet", so such a delta is *under-resolved*, not observed — and minting
# it poisons calibration (and the shared reference distribution) far worse than
# minting nothing. Expressed relative to the app's own base so it scales.
MIN_MONTHLY_GROWTH_RATIO = 1e-4  # 0.01% of the install base per month


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

    # Guard 3 — absolute ceiling, same figure the receiving side enforces.
    if monthly > MAX_MONTHLY_DOWNLOADS:
        return None

    # Guard 4 — under-resolved delta (counter had not refreshed). Refusing beats
    # minting a number we cannot tell apart from measurement lag.
    if monthly < b0["real_installs"] * MIN_MONTHLY_GROWTH_RATIO:
        return None

    return {
        "platform": "android",
        "rank": ranks[len(ranks) // 2],
        "observed_downloads": delta,
        "window_days": window_days,
    }


def _refresh_points(bucket_rows: list[dict]) -> list[dict]:
    """The captures where the published counter actually changed.

    ``realInstalls`` is republished in lumps (measured: 59% of daily captures show
    no change; median 2 days between refreshes), so only a capture whose value
    *differs* from the previous one marks a publication event. Those are the only
    defensible window endpoints: pairing two publication points lets their shared
    staleness largely cancel, whereas pairing a publication point with a frozen
    reading measures Google's lag instead of the app's downloads.
    """
    pts: list[dict] = []
    prev: int | None = None
    for r in bucket_rows:
        ri = r.get("real_installs")
        if not ri:
            continue
        if prev is None or ri != prev:
            pts.append(r)
            prev = ri
    return pts


def _ranks_within(rank_rows: list[dict], start: object, end: object) -> list[dict]:
    """Rank observations captured inside ``[start, end]`` (best-effort on dates)."""
    out = []
    try:
        s, e = _as_date(start), _as_date(end)
    except (TypeError, ValueError):
        return out
    for r in rank_rows:
        try:
            d = _as_date(r.get("captured_on"))
        except (TypeError, ValueError):
            continue
        if s <= d <= e:
            out.append(r)
    return out


def derive_flow_anchors(
    bucket_rows: list[dict], rank_rows: list[dict]
) -> list[dict]:
    """Derive EVERY well-resolved flow anchor from one app's capture series.

    ``derive_flow_anchor`` collapses a whole series into a single first-to-last
    anchor, which throws away nearly all of it: a series holding a dozen counter
    refreshes yields one anchor. Each consecutive pair of refresh points is itself
    a real observation — a download flow over a known window at a known rank — so
    pairing them recovers the full signal from captures already on disk, with no
    additional requests.

    Every candidate still goes through ``derive_flow_anchor``, so all four guards
    (bucket-boundary, growth ratio, absolute ceiling, under-resolved) apply
    unchanged; each anchor is stamped with the ``captured_on`` of its window end.
    """
    anchors: list[dict] = []
    points = _refresh_points(bucket_rows)
    for start, end in zip(points, points[1:]):
        # Prefer ranks observed inside this window; fall back to the app's whole
        # rank history rather than dropping an otherwise valid anchor.
        window_ranks = _ranks_within(rank_rows, start.get("captured_on"),
                                     end.get("captured_on")) or rank_rows
        anchor = derive_flow_anchor([start, end], window_ranks)
        if anchor:
            anchor["captured_on"] = end.get("captured_on")
            anchor["_window_ranks"] = window_ranks  # segment attribution by caller
            anchors.append(anchor)
    return anchors


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
