"""Revenue estimation (§9B, FR12).

Paid apps only: ``downloads x price x (1 - store cut)``. Free-app revenue is
never fabricated (N4) — it returns ``not_estimable`` unless the user supplies an
ARPU. IAP is explicitly excluded (flagged).
"""
from __future__ import annotations

STORE_CUT: dict[str, float] = {"standard": 0.30, "small_business": 0.15}


def estimate_revenue(
    downloads_point: float | None,
    price_usd: float | None,
    is_free: bool | int,
    cut: str = "small_business",
    user_arpu: float | None = None,
) -> tuple[float | None, list[str]]:
    """Return ``(revenue_point_or_None, flags)``.

    - Free app, no ARPU  -> ``(None, ['free_app_revenue_not_estimable'])``  (N4)
    - Free app, ARPU     -> ``(downloads*arpu, ['arpu_user_supplied'])``
    - Paid, no price     -> ``(None, ['no_price'])``
    - Paid, priced       -> ``(downloads*price*(1-cut), ['paid_app_excludes_iap'])``
    """
    if downloads_point is None:
        return None, ["no_downloads"]

    store_cut = STORE_CUT.get(cut, STORE_CUT["small_business"])

    if is_free:
        if user_arpu is None:
            return None, ["free_app_revenue_not_estimable"]
        return round(downloads_point * user_arpu), ["arpu_user_supplied"]

    if not price_usd or price_usd <= 0:
        return None, ["no_price"]
    return round(downloads_point * price_usd * (1 - store_cut)), ["paid_app_excludes_iap"]
