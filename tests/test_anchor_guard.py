"""Stage 4 tests — federation guard + refresh gating (§14, FR18/19/20, P8).

The core proof: ``assert_public_only`` raises when any ad/creator/identity field
is injected, and a stripped contribution carries ONLY public anchor fields.
"""
from __future__ import annotations

import pytest

from appscope.db import Database
from appscope.federation.contribute import (
    ANCHOR_KEEP,
    BANNED,
    assert_public_only,
    build_contribution,
    strip_to_anchor_schema,
)
from appscope.federation.refresh_dataset import refresh, validate_anchor


# --- the guard must abort on each banned field -------------------------------

@pytest.mark.parametrize("banned_field", sorted(BANNED))
def test_assert_public_only_raises_on_each_banned_field(banned_field):
    record = {
        "platform": "android",
        "category": "all",
        "country": "us",
        "list_type": "top-free",
        "rank": 10,
        "observed_downloads": 100000,
        "window_days": 30,
        banned_field: "LEAK",
    }
    with pytest.raises(ValueError) as exc:
        assert_public_only([record])
    assert banned_field in str(exc.value)


def test_assert_public_only_passes_on_clean_records():
    clean = [{
        "platform": "android", "category": "all", "country": "us",
        "list_type": "top-free", "rank": 10, "observed_downloads": 100000,
        "window_days": 30, "captured_on": "2025-12-01",
    }]
    assert_public_only(clean)  # must not raise


def test_strip_removes_banned_and_keeps_only_whitelist():
    dirty = {
        "platform": "android", "rank": 5, "observed_downloads": 1, "window_days": 30,
        "app_id": "com.secret.app", "ad_snapshot_url": "http://x", "channel": "@creator",
        "developer": "ACME", "name": "Secret",
    }
    stripped = strip_to_anchor_schema(dirty)
    assert set(stripped) <= ANCHOR_KEEP
    assert not (BANNED & set(stripped))
    # And the stripped record passes the guard.
    assert_public_only([stripped])


def test_build_contribution_excludes_identity(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.bootstrap()
    db.insert_flow_anchors(
        [{"platform": "android", "category": "all", "country": "us",
          "list_type": "top-free", "rank": 10, "observed_downloads": 336000,
          "window_days": 30, "captured_on": "2025-12-01"}],
        source="local",
    )
    records = build_contribution(db)
    assert records
    for r in records:
        assert "app_id" not in r
        assert not (BANNED & set(r))
        assert set(r) <= ANCHOR_KEEP


# --- validate_anchor rejects malformed / banned-carrying rows ----------------

def test_validate_anchor_accepts_good_row():
    assert validate_anchor({
        "platform": "android", "rank": 10, "observed_downloads": 100, "window_days": 30,
    })


@pytest.mark.parametrize("bad", [
    {"platform": "windows", "rank": 1, "observed_downloads": 1, "window_days": 1},
    {"platform": "android", "rank": 0, "observed_downloads": 1, "window_days": 1},
    {"platform": "android", "rank": "10", "observed_downloads": 1, "window_days": 1},
    {"platform": "android", "rank": 1, "observed_downloads": 0, "window_days": 1},
    {"platform": "android", "rank": 1, "observed_downloads": 1, "window_days": 0},
    {"platform": "android", "rank": 1, "observed_downloads": 1, "window_days": 1, "app_id": "x"},
])
def test_validate_anchor_rejects_bad_rows(bad):
    assert not validate_anchor(bad)


# --- refresh gating: refused / noop / preview / merged -----------------------

def _good(rank, captured="2026-01-01"):
    return {"platform": "android", "category": "all", "country": "us",
            "list_type": "top-free", "rank": rank, "observed_downloads": 100000 + rank,
            "window_days": 30, "captured_on": captured}


def test_refresh_refuses_corrupt_heavy(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.bootstrap()
    incoming = [_good(1)] + [{"platform": "bad"} for _ in range(9)]  # 90% corrupt
    out = refresh(db, "repo", min_new=1, max_corrupt_ratio=0.25, fetcher=lambda: incoming)
    assert out["status"] == "refused"
    assert out["reason"] == "too_many_corrupt"


def test_refresh_noop_below_min_new(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.bootstrap()
    incoming = [_good(r) for r in range(1, 4)]  # 3 clean rows
    out = refresh(db, "repo", min_new=50, max_corrupt_ratio=0.25, fetcher=lambda: incoming)
    assert out["status"] == "noop"
    assert out["new_rows"] == 3


def test_refresh_dry_run_previews_without_merge(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.bootstrap()
    incoming = [_good(r, captured="2026-01-%02d" % (r + 1)) for r in range(1, 11)]
    out = refresh(db, "repo", min_new=5, max_corrupt_ratio=0.25, dry_run=True,
                  fetcher=lambda: incoming)
    assert out["status"] == "preview"
    assert out["new_rows"] == 10
    # nothing merged
    assert db.conn.execute("SELECT COUNT(*) c FROM flow_anchors").fetchone()["c"] == 0


def test_automerge_banned_matches_canonical():
    # The CI auto-merge script inlines BANNED for dependency isolation; it must
    # never drift from the canonical guard in contribute.py.
    from appscope.federation import automerge_prs
    assert automerge_prs.BANNED == BANNED


def test_automerge_validate_contribution_file(tmp_path):
    import json as _json
    from appscope.federation import automerge_prs

    good = tmp_path / "good.json"
    good.write_text(_json.dumps({"anchors": [_good(10)]}), encoding="utf-8")
    ok, reason, n = automerge_prs.validate_contribution_file(str(good))
    assert ok and n == 1

    leaky = tmp_path / "leaky.json"
    leaky.write_text(_json.dumps({"anchors": [{**_good(10), "app_id": "com.x"}]}), encoding="utf-8")
    ok, reason, _ = automerge_prs.validate_contribution_file(str(leaky))
    assert not ok and "banned" in reason

    empty = tmp_path / "empty.json"
    empty.write_text(_json.dumps({"anchors": []}), encoding="utf-8")
    ok, reason, _ = automerge_prs.validate_contribution_file(str(empty))
    assert not ok and reason == "no_anchor_rows"

    malformed = tmp_path / "bad.json"
    malformed.write_text("{not json", encoding="utf-8")
    ok, reason, _ = automerge_prs.validate_contribution_file(str(malformed))
    assert not ok and "unreadable_json" in reason


def test_refresh_merges_and_recalibrates(tmp_path):
    db = Database(str(tmp_path / "t.db")); db.bootstrap()
    incoming = [_good(r, captured="2026-01-%02d" % (r + 1)) for r in range(1, 11)]
    out = refresh(db, "repo", min_new=5, max_corrupt_ratio=0.25, fetcher=lambda: incoming)
    assert out["status"] == "merged"
    assert out["new_rows"] == 10
    n = db.conn.execute("SELECT COUNT(*) c FROM flow_anchors WHERE source='community'").fetchone()["c"]
    assert n == 10
    # calibration was refit for the merged segment
    calib = db.get_calibration("android", "top-free", "all", "us")
    assert calib is not None and calib["n_anchors"] == 10
