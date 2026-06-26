"""Local MCP server (§9F, FR23).

Each user runs this locally; their own Claude/Cursor connects to it. Exposes the
same data as the REST API as MCP tools. Estimates carry confidence + method +
provenance and are never above MEDIUM (P2); ad tools never return USD spend (P3).

Run: python -m appscope.mcp_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .ads.intensity import ad_intensity_proxies
from .config import load_config
from .db import Database
from .estimate import estimate_app

mcp = FastMCP("appscope")

_cfg = load_config()
_db = Database(_cfg.storage.path)
_db.bootstrap()


@mcp.tool()
def app_estimate(app_id: str, country: str = "us") -> dict:
    """Download/revenue estimate with confidence + method + provenance.

    Ranges only; confidence is never above MEDIUM. Free-app revenue is returned
    as not-estimable rather than fabricated.
    """
    return estimate_app(_db, app_id, country=country, config=_cfg)


@mcp.tool()
def ad_intensity(app_id: str) -> dict:
    """Ad creative/cadence intensity proxies. Never USD spend."""
    return ad_intensity_proxies(_db.get_ad_snapshots(app_id))


@mcp.tool()
def creator_mentions(app_id: str, min_confidence: float = 0.6) -> dict:
    """Creator mentions above a confidence threshold (partial recall; local only)."""
    mentions = _db.get_creator_mentions(app_id, min_confidence=min_confidence)
    return {
        "app_id": app_id,
        "min_confidence": min_confidence,
        "count": len(mentions),
        "mentions": mentions,
        "caveat": "partial recall; rule-based classifier; local only",
    }


@mcp.tool()
def rank_history(app_id: str, country: str = "us", days: int = 30) -> dict:
    """Recent chart-rank history for an app."""
    return {
        "app_id": app_id,
        "country": country,
        "days": days,
        "ranks": _db.get_ranks(app_id, country=country, days=days),
    }


if __name__ == "__main__":
    mcp.run()
