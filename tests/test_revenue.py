"""Stage 2 tests — revenue estimation honesty rules (§14, FR12, N4)."""
from __future__ import annotations

from appscope.estimate.revenue import STORE_CUT, estimate_revenue


def test_free_app_without_arpu_not_estimable():
    rev, flags = estimate_revenue(1_000_000, price_usd=0.0, is_free=True, user_arpu=None)
    assert rev is None
    assert flags == ["free_app_revenue_not_estimable"]


def test_free_app_with_arpu():
    rev, flags = estimate_revenue(1_000_000, price_usd=0.0, is_free=True, user_arpu=0.05)
    assert rev == 50_000
    assert flags == ["arpu_user_supplied"]


def test_paid_app_small_business_cut():
    rev, flags = estimate_revenue(10_000, price_usd=4.99, is_free=False, cut="small_business")
    assert rev == round(10_000 * 4.99 * (1 - 0.15))
    assert flags == ["paid_app_excludes_iap"]


def test_paid_app_standard_cut():
    rev, flags = estimate_revenue(10_000, price_usd=4.99, is_free=False, cut="standard")
    assert rev == round(10_000 * 4.99 * (1 - 0.30))


def test_paid_app_no_price():
    rev, flags = estimate_revenue(10_000, price_usd=0.0, is_free=False)
    assert rev is None
    assert flags == ["no_price"]


def test_no_downloads_point():
    rev, flags = estimate_revenue(None, price_usd=4.99, is_free=False)
    assert rev is None
    assert flags == ["no_downloads"]


def test_store_cut_table():
    assert STORE_CUT["standard"] == 0.30
    assert STORE_CUT["small_business"] == 0.15
