"""Local REST API (§9E, FR22).

Each user runs this on their own machine. Every estimate is returned in the P1
envelope (``value/low/high/confidence/method/sources/flags``). No USD ad spend
is ever returned; free-app revenue is never fabricated.

Run: uvicorn appscope.api:app --reload   (or python -m appscope.api)
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .ads.intensity import ad_intensity_proxies
from .config import load_config
from .db import Database
from .estimate import estimate_app
from .reminders import landing_html

app = FastAPI(title="AppScope", version="1.1.0")

_cfg = load_config()
_db = Database(_cfg.storage.path)
_db.bootstrap()


def get_db() -> Database:
    return _db


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    """Human-facing landing page — carries the (toggleable) contribute banner.

    The call-to-action lives here, on the artifact a user opens in a browser,
    not in per-run terminal output (which only clogs whoever runs the scripts).
    """
    return landing_html(_cfg, version=app.version)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/apps/{app_id}/estimate")
def get_estimate(app_id: str, country: str = "us") -> dict:
    """Download/revenue estimate in the P1 envelope (ranges; never > MEDIUM)."""
    env = estimate_app(get_db(), app_id, country=country, config=_cfg)
    return env


@app.get("/apps/{app_id}/ads")
def get_ads(app_id: str) -> dict:
    """Ad creative/cadence intensity proxies. Never USD spend (P3)."""
    snapshots = get_db().get_ad_snapshots(app_id)
    return ad_intensity_proxies(snapshots)


@app.get("/apps/{app_id}/creators")
def get_creators(app_id: str, min_confidence: float = 0.6) -> dict:
    """Creator mentions above a confidence threshold (partial recall; local)."""
    mentions = get_db().get_creator_mentions(app_id, min_confidence=min_confidence)
    return {
        "app_id": app_id,
        "min_confidence": min_confidence,
        "count": len(mentions),
        "mentions": mentions,
        "caveat": "partial recall; rule-based classifier; YouTube-first. Local only.",
    }


@app.get("/apps/{app_id}/ranks")
def get_ranks(app_id: str, country: str = "us", days: int = 30) -> dict:
    ranks = get_db().get_ranks(app_id, country=country, days=days)
    return {"app_id": app_id, "country": country, "days": days, "ranks": ranks}


@app.get("/apps/{app_id}/reviews")
def get_reviews(app_id: str, days: int = 30) -> dict:
    reviews = get_db().get_reviews(app_id, days=days)
    return {"app_id": app_id, "days": days, "count": len(reviews), "reviews": reviews}


@app.get("/apps/{app_id}")
def get_app(app_id: str) -> dict:
    a = get_db().get_app(app_id)
    if not a:
        raise HTTPException(status_code=404, detail="app not tracked")
    return a


def main() -> None:
    import uvicorn

    uvicorn.run("appscope.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
