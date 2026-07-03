"""Tests for the Claude Code skill surface: the JSON CLI, the append-only
(no-data-destroyed) DB semantics, the backup snapshot, and the HTML report
deliverable. Offline; uses a temp DB, never the user's appscope.db."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from appscope.db import Database  # noqa: E402

RANK = {"app_id": "x1", "country": "us", "list_type": "top-free",
        "category": "all", "rank": 5, "captured_on": "2026-07-04"}


def _tmp_db() -> Database:
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db = Database(path)
    db.bootstrap()
    return db


class TestAppendOnlyObservations(unittest.TestCase):
    """No data loss: captured observations are never overwritten."""

    def test_rank_first_observation_wins(self):
        db = _tmp_db()
        db.insert_rank(RANK)
        db.insert_rank({**RANK, "rank": 99})  # same-day re-collect
        rows = db.conn.execute("SELECT rank FROM rank_history").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 5)  # NOT replaced by 99

    def test_rank_new_day_appends(self):
        db = _tmp_db()
        db.insert_rank(RANK)
        db.insert_rank({**RANK, "rank": 7, "captured_on": "2026-07-05"})
        rows = db.conn.execute("SELECT COUNT(*) FROM rank_history").fetchone()
        self.assertEqual(rows[0], 2)  # history accumulates

    def test_install_bucket_first_observation_wins(self):
        db = _tmp_db()
        bucket = {"app_id": "x1", "min_installs": 1000, "real_installs": 1234,
                  "captured_on": "2026-07-04"}
        db.insert_install_bucket(bucket)
        db.insert_install_bucket({**bucket, "real_installs": 1})
        got = db.get_install_buckets("x1")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["real_installs"], 1234)

    def test_backup_creates_snapshot_and_keeps_old_ones(self):
        db = _tmp_db()
        db.insert_rank(RANK)
        dest = tempfile.mkdtemp()
        first = db.backup(dest)
        second = db.backup(dest)
        self.assertTrue(os.path.exists(first))   # older snapshot never pruned
        self.assertTrue(os.path.exists(second) or first == second)
        import sqlite3
        snap = sqlite3.connect(first)
        self.assertEqual(snap.execute("SELECT COUNT(*) FROM rank_history").fetchone()[0], 1)
        snap.close()


class TestCli(unittest.TestCase):
    """The JSON CLI the skill drives."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        cfg = {"storage": {"backend": "sqlite", "path": os.path.join(self.dir, "t.db")},
               "tracking": {"countries": ["us"], "categories": ["all"], "apps": []}}
        self.cfg_path = os.path.join(self.dir, "config.json")
        with open(self.cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        db = Database(cfg["storage"]["path"])
        db.bootstrap()
        db.upsert_app({"app_id": "x1", "platform": "ios", "name": "TestApp",
                       "developer": "Dev", "category": "all", "country": "us",
                       "price_usd": 0, "is_free": 1, "captured_on": "2026-07-04"})
        db.insert_rank(RANK)
        db.close()

    def _run(self, *args):
        r = subprocess.run([sys.executable, "-m", "appscope.cli",
                            "--config", self.cfg_path, *args],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_summary_observed_facts(self):
        d = self._run("summary", "--app", "x1")
        self.assertTrue(d["found"])
        self.assertEqual(d["app"]["name"], "TestApp")
        self.assertEqual(d["latest_rank"]["rank"], 5)
        self.assertEqual(d["confidence"], "HIGH")

    def test_summary_missing_app_is_honest(self):
        d = self._run("summary", "--app", "nope")
        self.assertFalse(d["found"])
        self.assertIn("not collected", d["note"])

    def test_estimate_uncalibrated_returns_none_not_fabricated(self):
        d = self._run("estimate", "--app", "x1")
        # no anchors in this fresh DB -> must refuse, never invent
        self.assertIsNone(d["value"])
        self.assertEqual(d["confidence"], "NONE")

    def test_report_renders_deliverable(self):
        out = os.path.join(self.dir, "report.html")
        d = self._run("report", "--app", "x1", "--out", out)
        self.assertEqual(d["written"], out)
        html = open(out, encoding="utf-8").read()
        self.assertIn("TestApp", html)
        self.assertIn("no data", html)          # uncalibrated estimate said honestly
        self.assertIn("conf-HIGH", html)        # observed rank
        self.assertIn("never modeled", html)    # honesty footer

    def test_backup_via_cli(self):
        dest = os.path.join(self.dir, "backups")
        d = self._run("backup", "--dest", dest)
        self.assertTrue(os.path.exists(d["backup"]))


if __name__ == "__main__":
    unittest.main()
