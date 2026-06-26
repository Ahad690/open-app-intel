"""User-facing contribute call-to-action.

Lesson carried from fiverr-gig-optimizer: do NOT print per-run reminders to the
terminal/stderr. Whoever runs the collectors/refresh (a cron job, a VPS, or
Claude driving the scripts) is not necessarily the person who should see a
nudge, and a banner after every run just clogs the output.

Instead, surface the call-to-action on the artifact the user actually opens —
the local REST API landing page (`GET /`). It is HTML-escaped, links to the
configured dataset, and is toggleable via ``federation.contribute_reminder``
(default on).
"""
from __future__ import annotations

from html import escape


def contribution_enabled(cfg) -> bool:
    """Whether to show the contribute banner (config-toggleable, default on)."""
    return bool(getattr(cfg.federation, "contribute_reminder", True))


def contribution_html(dataset_repo: str) -> str:
    """A small green call-to-action banner (HTML, escaped) for the landing page."""
    repo = escape(dataset_repo or "")
    return (
        '<div style="margin:0 0 20px;padding:14px 18px;border-radius:10px;'
        'background:#e8f7ee;border:1px solid #2e9e5b;color:#11502c;'
        'font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif;">'
        '<strong>💚 Love this? Help the free app-intelligence dataset grow.</strong><br>'
        'Your captured install-bucket deltas become public calibration anchors '
        'that sharpen download estimates for everyone — only public app-store '
        'facts are shared, never ads, creators, or identity. '
        f'Contribute yours to <a href="{repo}" style="color:#0a7d36;font-weight:600;" '
        f'target="_blank" rel="noopener">the community dataset</a> with '
        '<code>python -m appscope.federation.contribute --contributor &lt;you&gt;</code>.'
        '</div>'
    )


def landing_html(cfg, version: str = "") -> str:
    """Full HTML landing page for the local REST API (the artifact users open)."""
    banner = contribution_html(cfg.federation.dataset_repo) if contribution_enabled(cfg) else ""
    ver = escape(version)
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>AppScope</title></head>"
        "<body style=\"max-width:760px;margin:40px auto;padding:0 20px;"
        "font:16px/1.6 system-ui,Segoe UI,Arial,sans-serif;color:#1b1f23;\">"
        f"<h1 style='margin-bottom:4px;'>AppScope <small style='color:#888;font-size:14px;'>v{ver}</small></h1>"
        "<p style='color:#555;margin-top:0;'>Self-hosted, federated open app-intelligence — "
        "honest, confidence-labeled estimates. Running locally.</p>"
        f"{banner}"
        "<h3>Endpoints</h3><ul>"
        "<li><code>GET /apps/{app_id}/estimate?country=us</code> — download/revenue estimate (ranges; never &gt; MEDIUM)</li>"
        "<li><code>GET /apps/{app_id}/ads</code> — ad intensity proxies (never USD)</li>"
        "<li><code>GET /apps/{app_id}/creators?min_confidence=0.6</code></li>"
        "<li><code>GET /apps/{app_id}/ranks?days=30</code></li>"
        "<li><code>GET /apps/{app_id}/reviews?days=30</code></li>"
        "</ul>"
        "<p><a href='/docs'>Interactive API docs →</a></p>"
        "</body></html>"
    )
