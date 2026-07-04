"""Offline tests for the Play top-charts collector (the Android rank source)
and the anchor path it unlocks: chart rank + bucket delta -> flow anchor."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from appscope.collectors import play_charts  # noqa: E402
from appscope.db import Database  # noqa: E402


def _fake_app(pkg: str, title: str, price: int = 0) -> list:
    """Build one app entry with fields at the ported JS paths."""
    app = [[None] * 20]
    app[0][0] = [pkg]                      # APP_ID_PATH [0,0,0]
    app[0][3] = title                      # TITLE_PATH  [0,3]
    app[0][14] = "Dev Inc"                 # DEVELOPER_PATH [0,14]
    app[0][8] = [None, [[price]]]          # PRICE_PATH [0,8,1,0,0]
    return app


def _fake_response(apps: list) -> str:
    # apps live at APPS_PATH [0,1,0,28,0] inside the inner payload:
    # inner[0][1][0][28][0] = apps
    lvl28 = [None] * 29
    lvl28[28] = [apps]
    inner = [[None, [lvl28]]]
    payload = [["wrb.fr", "vyAe2", json.dumps(inner)]]
    # emulate batchexecute framing: junk lines + the payload line
    return ")]}'\n\n123\n" + json.dumps(payload) + "\n"


class FakeResp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class TestPlayCharts(unittest.TestCase):
    def test_parses_ranked_rows(self):
        apps = [_fake_app("com.a.one", "App One"), _fake_app("com.b.two", "App Two", price=990000)]
        text = _fake_response(apps)
        orig_post = play_charts.requests.post
        play_charts.requests.post = lambda *a, **k: FakeResp(text)
        try:
            rows = play_charts.fetch_play_chart(country="us", num=2)
        finally:
            play_charts.requests.post = orig_post
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["app_id"], "com.a.one")
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[1]["rank"], 2)
        self.assertEqual(rows[0]["platform"], "android")
        self.assertEqual(rows[0]["category"], "all")  # chart segment, poolable
        self.assertAlmostEqual(rows[1]["price_usd"], 0.99)

    def test_failure_returns_empty_never_raises(self):
        orig_post = play_charts.requests.post
        play_charts.requests.post = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blocked"))
        try:
            rows = play_charts.fetch_play_chart(country="us")
        finally:
            play_charts.requests.post = orig_post
        self.assertEqual(rows, [])  # honest empty, no fabricated ranks

    def test_unknown_collection_returns_empty(self):
        self.assertEqual(play_charts.fetch_play_chart(collection="nope"), [])


class TestAnchorPathUnlocked(unittest.TestCase):
    """The end-to-end reason this collector exists: android chart rank rows +
    multi-day bucket deltas now mint a real flow anchor."""

    def test_chart_rank_plus_bucket_delta_mints_anchor(self):
        db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))
        db.bootstrap()
        db.upsert_app({"app_id": "com.a.one", "platform": "android", "name": "App One",
                       "developer": "Dev", "category": "EDUCATION", "country": "us",
                       "price_usd": 0, "is_free": 1, "captured_on": "2026-07-04"})
        # chart rank rows on both days (segment category "all")
        for day in ("2026-07-04", "2026-07-05"):
            db.insert_rank({"app_id": "com.a.one", "country": "us", "list_type": "top-free",
                            "category": "all", "rank": 7, "captured_on": day})
        # bucket delta across the days: +120k real installs
        db.insert_install_bucket({"app_id": "com.a.one", "min_installs": 1000000,
                                  "real_installs": 5_000_000, "captured_on": "2026-07-04"})
        db.insert_install_bucket({"app_id": "com.a.one", "min_installs": 1000000,
                                  "real_installs": 5_120_000, "captured_on": "2026-07-05"})
        minted = db.seed_flow_anchors_from_buckets()
        self.assertEqual(minted, 1)
        anchors = db.conn.execute(
            "SELECT rank, observed_downloads, window_days, category FROM flow_anchors").fetchall()
        self.assertEqual(tuple(anchors[0]), (7, 120_000, 1, "all"))
        # category pools in the chart segment, NOT the app's Play category


if __name__ == "__main__":
    unittest.main()
