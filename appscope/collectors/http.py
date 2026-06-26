"""Shared HTTP helpers for collectors (throttling + graceful rate-limit handling).

Every collector throttles and treats rate-limit / quota errors as non-fatal so a
single failing source never crashes a scheduled run (FR7).
"""
from __future__ import annotations

import time
from typing import Any

import requests

DEFAULT_TIMEOUT = 15
DEFAULT_THROTTLE_SECONDS = 1.0
USER_AGENT = "AppScope/1.1 (+https://github.com/Ahad690/open-app-intel)"


class RateLimited(Exception):
    """Raised when a source signals rate-limiting/quota exhaustion."""


def polite_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    throttle: float = DEFAULT_THROTTLE_SECONDS,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """GET with a default UA, timeout and a post-request throttle.

    Raises :class:`RateLimited` on HTTP 429 so callers can catch it distinctly
    from other failures.
    """
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    resp = requests.get(url, params=params, timeout=timeout, headers=hdrs)
    if resp.status_code == 429:
        raise RateLimited(f"429 from {url}")
    resp.raise_for_status()
    if throttle:
        time.sleep(throttle)
    return resp
