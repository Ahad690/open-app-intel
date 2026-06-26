"""Rule-based app-mention classifier (§9D, FR16).

The "missing middle layer": a transparent, rule-based scorer (no ML) that rates
how likely a piece of text is about a tracked app. Recall is partial by design;
precision is the gate (KPI K5 >= 0.8). Creator data is LOCAL ONLY (P8).
"""
from __future__ import annotations

import re

STORE_LINK = re.compile(r"(apps\.apple\.com|play\.google\.com/store/apps)")


def app_mention_score(
    text: str | None,
    app_name: str | None,
    package_id: str | None = None,
    brand_hashtags: tuple[str, ...] = (),
) -> float:
    """Score 0.0-1.0 that ``text`` is about the given app.

    Signals (additive, capped at 1.0): app name (0.5), package id (0.3), brand
    hashtag (0.2), an app-store link (0.4 — the strongest single signal).
    """
    t = (text or "").lower()
    score = 0.0
    if app_name and app_name.lower() in t:
        score += 0.5
    if package_id and package_id.lower() in t:
        score += 0.3
    if any(h.lower() in t for h in brand_hashtags):
        score += 0.2
    if STORE_LINK.search(t):
        score += 0.4  # strongest signal
    return min(round(score, 2), 1.0)


def classify_items(
    items: list[dict],
    app_name: str | None,
    package_id: str | None = None,
    brand_hashtags: tuple[str, ...] = (),
    min_confidence: float = 0.6,
) -> list[dict]:
    """Score a list of ``{text, ...}`` items, returning those above threshold
    with an added ``mention_confidence`` field."""
    out: list[dict] = []
    for it in items:
        conf = app_mention_score(
            it.get("text"), app_name, package_id, brand_hashtags
        )
        if conf >= min_confidence:
            enriched = dict(it)
            enriched["mention_confidence"] = conf
            out.append(enriched)
    return out
