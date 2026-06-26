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


def test_assert_public_only_rejects_unexpected_field():
    # Defense in depth: a non-banned but non-whitelisted field also aborts.
    with pytest.raises(ValueError) as exc:
        assert_public_only([{"platform": "android", "rank": 1, "observed_downloads": 1,
                             "window_days": 30, "surprise_column": "x"}])
    assert "non-whitelisted" in str(exc.value)


def test_contribution_dedups_against_existing():
    from appscope.federation.contribute import dedup
    rec = {"platform": "android", "category": "all", "country": "us", "list_type": "top-free",
           "rank": 10, "observed_downloads": 336000, "window_days": 30, "captured_on": "2025-12-01"}
    # Same record already in the dataset -> nothing new to contribute.
    assert dedup([dict(rec)], existing=[dict(rec)]) == []
    # A different record survives.
    other = {**rec, "rank": 11}
    assert dedup([other], existing=[dict(rec)]) == [other]


def test_upload_filename_has_content_hash(monkeypatch):
    from appscope.federation import contribute as cb
    captured = {}

    class _Op:
        def __init__(self, path_in_repo, path_or_fileobj):
            self.path_in_repo = path_in_repo

    class _Api:
        def __init__(self, *a, **k):
            pass

        def create_commit(self, **kw):
            captured["path"] = kw["operations"][0].path_in_repo

            class I:
                pr_url = "http://pr"
            return I()

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "HfApi", _Api, raising=False)
    monkeypatch.setattr(huggingface_hub, "CommitOperationAdd", _Op, raising=False)
    rec = [{"platform": "android", "category": "all", "country": "us", "list_type": "top-free",
            "rank": 10, "observed_downloads": 336000, "window_days": 30, "captured_on": "2025-12-01"}]
    cb.upload_contribution(rec, "owner/repo", "tok", "alice")
    # contributions/alice-<10 hex chars>.json
    assert captured["path"].startswith("contributions/alice-")
    assert captured["path"].endswith(".json")
    digest = captured["path"].split("alice-", 1)[1][:-5]
    assert len(digest) == 10 and all(c in "0123456789abcdef" for c in digest)


def test_contribute_reminder_plain_and_color():
    from appscope.config import Config
    from appscope.reminders import contribute_reminder_text, print_contribute_reminder
    import io

    cfg = Config()
    plain = contribute_reminder_text(cfg.federation.dataset_repo, color=False)
    assert "contribute" in plain.lower() and "\033[" not in plain
    colored = contribute_reminder_text(cfg.federation.dataset_repo, color=True)
    assert "\033[" in colored

    # Disabled => prints nothing.
    cfg.federation.contribute_reminder = False
    buf = io.StringIO()
    print_contribute_reminder(cfg, stream=buf)
    assert buf.getvalue() == ""


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


def test_abuse_scan_clean_when_unremarkable():
    from appscope.federation.automerge_prs import abuse_scan
    rows = [_good(r) for r in (1, 5, 10, 20, 50)]
    assert abuse_scan(rows, reference_rows=[], cfg=None) == []


def test_abuse_scan_rank_ceiling():
    from appscope.federation.automerge_prs import abuse_scan
    rows = [{"platform": "android", "rank": 99999, "observed_downloads": 100,
             "window_days": 30, "category": "all", "country": "us", "list_type": "top-free"}]
    reasons = abuse_scan(rows, [], None)
    assert any("rank" in r and "ceiling" in r for r in reasons)


def test_abuse_scan_window_ceiling():
    from appscope.federation.automerge_prs import abuse_scan
    rows = [{"platform": "android", "rank": 5, "observed_downloads": 100,
             "window_days": 5000, "category": "all", "country": "us", "list_type": "top-free"}]
    reasons = abuse_scan(rows, [], None)
    assert any("window_days" in r for r in reasons)


def test_abuse_scan_monthly_downloads_ceiling():
    from appscope.federation.automerge_prs import abuse_scan
    # 9e9 over 30 days -> ~9e9 monthly, far over the 1e8 ceiling
    rows = [{"platform": "android", "rank": 1, "observed_downloads": 9_000_000_000,
             "window_days": 30, "category": "all", "country": "us", "list_type": "top-free"}]
    reasons = abuse_scan(rows, [], None)
    assert any("monthly downloads" in r for r in reasons)


def test_abuse_scan_duplicate_flooding():
    from appscope.federation.automerge_prs import abuse_scan
    dup = {"platform": "android", "rank": 5, "observed_downloads": 1000, "window_days": 30,
           "category": "all", "country": "us", "list_type": "top-free", "captured_on": "2026-01-01"}
    rows = [dict(dup) for _ in range(10)]  # all identical
    reasons = abuse_scan(rows, [], None)
    assert any("duplicate flooding" in r for r in reasons)


def test_abuse_scan_distribution_outlier_vs_reference():
    from appscope.federation.automerge_prs import abuse_scan
    seg = {"platform": "android", "category": "all", "country": "us", "list_type": "top-free", "window_days": 30}
    # Reference: ~100k/month at this segment (3 rows, enough to judge).
    reference = [{**seg, "rank": r, "observed_downloads": 100_000} for r in (3, 4, 6)]
    # PR: same segment but ~5,000,000/month (50x) -> outlier.
    pr_rows = [{**seg, "rank": r, "observed_downloads": 5_000_000} for r in (3, 4, 6)]
    reasons = abuse_scan(pr_rows, reference, None)
    assert any("outlier" in r for r in reasons)


def test_abuse_scan_outlier_silent_without_enough_reference():
    from appscope.federation.automerge_prs import abuse_scan
    seg = {"platform": "android", "category": "all", "country": "us", "list_type": "top-free", "window_days": 30}
    reference = [{**seg, "rank": 3, "observed_downloads": 100_000}]  # only 1 ref row < min_rows
    pr_rows = [{**seg, "rank": r, "observed_downloads": 5_000_000} for r in (3, 4, 6)]
    # Not enough reference rows in the segment -> outlier check stays silent.
    assert abuse_scan(pr_rows, reference, None) == []


def test_evaluate_pr_holds_suspicious(monkeypatch):
    import json as _json
    from appscope.federation import automerge_prs as am
    # A PR with an implausible monthly-downloads row -> suspicious HOLD.
    payload = _json.dumps({"anchors": [{"platform": "android", "rank": 1,
        "observed_downloads": 9_000_000_000, "window_days": 30, "category": "all",
        "country": "us", "list_type": "top-free"}]})
    api = _FakeApi(main_files={"README.md": "a"},
                   pr_files={"README.md": "a", "contributions/x.json": "newblob"},
                   pr_payloads={})

    def fake_dl(repo_id, filename, revision=None, repo_type=None, **kw):
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        return path

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_dl, raising=False)
    v = am.evaluate_pr(api, "repo/x", 1)
    assert not v["merge"] and v["reason"].startswith("suspicious:")


class _FakeSibling:
    def __init__(self, rfilename, blob_id):
        self.rfilename = rfilename
        self.blob_id = blob_id
        self.lfs = None


class _FakeInfo:
    def __init__(self, siblings):
        self.siblings = siblings


class _FakeApi:
    """Minimal stand-in for HfApi to exercise evaluate_pr guard layers offline."""

    def __init__(self, main_files, pr_files, pr_payloads):
        # *_files: dict path -> blob_id ; pr_payloads: path -> file content (str)
        self._main = main_files
        self._pr = pr_files
        self._payloads = pr_payloads

    def get_discussion_details(self, repo_id, num, repo_type=None):
        class D:
            git_reference = "refs/pr/1"
        return D()

    def repo_info(self, repo_id, repo_type=None, revision=None, files_metadata=True):
        files = self._pr if revision else self._main
        return _FakeInfo([_FakeSibling(p, b) for p, b in files.items()])


def _run_eval(monkeypatch, api, payloads):
    import appscope.federation.automerge_prs as am

    def fake_dl(repo_id, filename, revision=None, repo_type=None, **kw):
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payloads[filename])
        return path

    monkeypatch.setattr(am, "hf_hub_download", fake_dl, raising=False)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_dl, raising=False)
    return am.evaluate_pr(api, "repo/x", 1)


def test_automerge_rejects_file_deletion(monkeypatch):
    api = _FakeApi(
        main_files={"README.md": "a", "contributions/old.json": "b"},
        pr_files={"README.md": "a"},  # old.json removed
        pr_payloads={},
    )
    v = _run_eval(monkeypatch, api, {})
    assert not v["merge"] and "removes existing file" in v["reason"]


def test_automerge_rejects_file_modification(monkeypatch):
    api = _FakeApi(
        main_files={"README.md": "a"},
        pr_files={"README.md": "MODIFIED"},  # same path, different blob
        pr_payloads={},
    )
    v = _run_eval(monkeypatch, api, {})
    assert not v["merge"] and "modifies existing file" in v["reason"]


def test_automerge_rejects_addition_outside_contributions(monkeypatch):
    api = _FakeApi(
        main_files={"README.md": "a"},
        pr_files={"README.md": "a", "evil.py": "x"},
        pr_payloads={},
    )
    v = _run_eval(monkeypatch, api, {})
    assert not v["merge"] and "non-contribution file" in v["reason"]


def test_automerge_size_cap(monkeypatch):
    import json as _json
    payload = _json.dumps({"anchors": [_good(r % 1000 + 1) for r in range(50)]})
    api = _FakeApi(
        main_files={"README.md": "a"},
        pr_files={"README.md": "a", "contributions/big.json": "newblob"},
        pr_payloads={},
    )
    import appscope.federation.automerge_prs as am

    def fake_dl(repo_id, filename, revision=None, repo_type=None, **kw):
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        return path

    # evaluate_pr does a function-local `from huggingface_hub import hf_hub_download`,
    # so patch the source module symbol.
    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_dl, raising=False)
    v = am.evaluate_pr(api, "repo/x", 1, max_rows=10)
    assert not v["merge"] and "too_large" in v["reason"]


def test_automerge_accepts_clean_additive_pr(monkeypatch):
    import json as _json
    payload = _json.dumps({"anchors": [_good(1), _good(5)]})
    api = _FakeApi(
        main_files={"README.md": "a"},
        pr_files={"README.md": "a", "contributions/alice.json": "newblob"},
        pr_payloads={},
    )
    v = _run_eval(monkeypatch, api, {"contributions/alice.json": payload})
    assert v["merge"] and v["rows"] == 2


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
