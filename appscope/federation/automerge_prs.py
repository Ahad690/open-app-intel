"""Auto-merge clean community contribution PRs on the HF anchor dataset.

Designed to run in CI (GitHub Actions, scheduled). It is intentionally
SELF-CONTAINED — its only third-party dependency is ``huggingface_hub`` — so the
CI job stays tiny and never has to install the full app stack.

The honesty guard runs on the RECEIVING side too: every anchor row in a PR is
validated, and the PR is merged ONLY if every row is a well-formed public anchor
with NO ad/creator/identity field. Anything else is left open with a comment for
human review. Supports ``--dry-run``.

Auth: reads a fine-grained HF write token from ``--token`` or the ``HF_TOKEN``
env var. Never prints the token.

    python -m appscope.federation.automerge_prs --repo Ahad690/app-rank-anchors --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
from typing import Any

log = logging.getLogger("automerge")

# Anti-flood: max anchor rows a single PR may add to be auto-mergeable (L2).
DEFAULT_MAX_ROWS = 2000

# L4 anti-abuse thresholds. These catch well-formed-but-suspicious submissions
# and route them to a human (HOLD), never an auto-reject. Overridable via
# config.json federation.abuse.
DEFAULT_ABUSE = {
    "max_rank": 2000,                 # implausible chart rank
    "max_window_days": 365,           # implausible observation window
    "max_monthly_downloads": 100_000_000,  # implausible per-month flow
    "min_unique_ratio": 0.5,          # duplicate-flooding floor
    "outlier_factor": 10,             # segment-median may differ at most this much
    "outlier_min_rows": 3,            # min rows (PR and reference) to judge outlier
}

# Mirror of appscope.federation.contribute.BANNED. Kept inline so this script has
# no intra-package imports (CI only installs huggingface_hub). A test
# (test_anchor_guard.py::test_automerge_banned_matches_canonical) asserts these
# stay in sync.
BANNED = {
    "app_id", "channel", "creator", "handle", "advertiser", "ad_snapshot_url",
    "creative_id", "review_id", "video_id", "url", "name", "developer",
}


def validate_anchor(r: Any) -> bool:
    """A row is valid only if it is a well-formed public anchor (no banned fields)."""
    return (
        isinstance(r, dict)
        and r.get("platform") in {"ios", "android"}
        and isinstance(r.get("rank"), int)
        and r.get("rank", 0) > 0
        and (r.get("observed_downloads") or 0) > 0
        and (r.get("window_days") or 0) > 0
        and not (BANNED & set(r))
    )


def _anchors_from_payload(data: Any) -> list[dict]:
    if isinstance(data, dict):
        anchors = data.get("anchors", [])
    elif isinstance(data, list):
        anchors = data
    else:
        anchors = []
    return [a for a in anchors if isinstance(a, dict)]


def read_anchor_file(path: str) -> tuple[list[dict] | None, str | None]:
    """Parse a contribution JSON file. Returns ``(rows, None)`` or ``(None, error)``."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable_json: {exc}"
    return _anchors_from_payload(data), None


def validate_contribution_file(path: str) -> tuple[bool, str, int]:
    """Return ``(ok, reason, n_rows)`` for a downloaded contribution JSON file."""
    anchors, err = read_anchor_file(path)
    if err:
        return False, err, 0
    if not anchors:
        return False, "no_anchor_rows", 0
    for i, row in enumerate(anchors):
        bad = BANNED & set(row)
        if bad:
            return False, f"row {i} carries banned field(s): {sorted(bad)}", len(anchors)
        if not validate_anchor(row):
            return False, f"row {i} is not a valid public anchor", len(anchors)
    return True, "ok", len(anchors)


# --- L4 anti-abuse heuristics (well-formed-but-suspicious -> HOLD) -----------

_DEDUP_KEYS = (
    "platform", "category", "country", "list_type", "rank",
    "observed_downloads", "window_days", "captured_on",
)


def _monthly_downloads(row: dict) -> float | None:
    """Normalize an anchor's observed flow to a monthly figure."""
    win = row.get("window_days") or 0
    obs = row.get("observed_downloads") or 0
    return obs * 30.0 / win if win > 0 else None


def _segment(row: dict) -> tuple:
    return (
        row.get("platform"),
        row.get("list_type", "top-free"),
        row.get("category", "all"),
        row.get("country", "us"),
    )


def _row_key(row: dict) -> str:
    return json.dumps({k: row.get(k) for k in _DEDUP_KEYS}, sort_keys=True)


def _segment_monthly_medians(rows: list[dict]) -> dict[tuple, tuple[float, int]]:
    """{segment -> (median monthly downloads, n)} over rows with a usable flow."""
    by: dict[tuple, list[float]] = {}
    for r in rows:
        m = _monthly_downloads(r)
        if m is not None:
            by.setdefault(_segment(r), []).append(m)
    return {seg: (statistics.median(v), len(v)) for seg, v in by.items() if v}


def abuse_scan(
    rows: list[dict], reference_rows: list[dict] | None, cfg: dict | None = None
) -> list[str]:
    """Stateless anti-abuse heuristics. Returns reasons ([] = clean).

    Schema/PII/range already covered by validate_anchor; these catch *plausible-
    looking but suspicious* data:
      1. absolute ceilings (rank / window / implied monthly downloads),
      2. duplicate flooding (low unique-row ratio),
      3. per-segment median that is a wild multiple of the reference distribution
         (the anchors already on main) — likely scale manipulation.
    The outlier check auto-activates only once a segment has enough reference
    rows, so it is silent on a fresh/empty dataset.
    """
    cfg = {**DEFAULT_ABUSE, **(cfg or {})}
    reasons: list[str] = []
    if not rows:
        return reasons

    # 1. Absolute ceilings (report the first hit to avoid spam).
    for r in rows:
        rk = r.get("rank")
        win = r.get("window_days")
        monthly = _monthly_downloads(r)
        if isinstance(rk, int) and rk > cfg["max_rank"]:
            reasons.append(f"rank {rk} exceeds ceiling {cfg['max_rank']}")
            break
        if isinstance(win, int) and win > cfg["max_window_days"]:
            reasons.append(f"window_days {win} exceeds ceiling {cfg['max_window_days']}")
            break
        if monthly is not None and monthly > cfg["max_monthly_downloads"]:
            reasons.append(
                f"implied monthly downloads {int(monthly)} exceeds ceiling "
                f"{cfg['max_monthly_downloads']}"
            )
            break

    # 2. Duplicate flooding.
    if len(rows) >= 5:
        uniq = len({_row_key(r) for r in rows})
        if uniq / len(rows) < cfg["min_unique_ratio"]:
            reasons.append(f"only {uniq}/{len(rows)} unique rows (duplicate flooding)")

    # 3. Per-segment median outlier vs the reference distribution (main).
    ref_med = _segment_monthly_medians(reference_rows or [])
    factor = cfg["outlier_factor"]
    min_rows = cfg["outlier_min_rows"]
    pr_by_seg: dict[tuple, list[float]] = {}
    for r in rows:
        m = _monthly_downloads(r)
        if m is not None:
            pr_by_seg.setdefault(_segment(r), []).append(m)
    for seg, vals in pr_by_seg.items():
        ref = ref_med.get(seg)
        if not ref:
            continue
        ref_median, ref_n = ref
        if ref_n < min_rows or len(vals) < min_rows or ref_median <= 0:
            continue
        ratio = statistics.median(vals) / ref_median
        if ratio > factor or ratio < 1 / factor:
            reasons.append(
                f"segment {seg} median {int(statistics.median(vals))} is "
                f"{ratio:.1f}x the reference {int(ref_median)} (outlier)"
            )
    return reasons


def load_main_reference(api, repo_id: str) -> list[dict]:
    """Concatenate all anchor rows currently on main — the reference distribution
    for the outlier check. Best-effort; returns ``[]`` on failure."""
    from huggingface_hub import hf_hub_download

    rows: list[dict] = []
    try:
        files = [
            f
            for f in api.list_repo_files(repo_id, repo_type="dataset")
            if f.startswith("contributions/") and f.endswith(".json")
        ]
        for f in files:
            local = hf_hub_download(repo_id, f, repo_type="dataset")
            anchors, err = read_anchor_file(local)
            if not err and anchors:
                rows.extend(anchors)
    except Exception as exc:  # network / parse — non-fatal
        log.warning("could not load reference from main: %s", exc)
    return rows


def _blob_map(api, repo_id: str, revision: str | None = None) -> dict[str, str | None]:
    """Map every file path -> its git blob id at ``revision`` (main if None).

    Identical content yields an identical blob id across refs, so comparing maps
    detects added / removed / modified files without downloading anything.
    """
    info = api.repo_info(
        repo_id, repo_type="dataset", revision=revision, files_metadata=True
    )
    out: dict[str, str | None] = {}
    for s in info.siblings or []:
        blob = getattr(s, "blob_id", None)
        if blob is None:
            lfs = getattr(s, "lfs", None)
            blob = getattr(lfs, "sha256", None) if lfs is not None else None
        out[s.rfilename] = blob
    return out


def evaluate_pr(
    api,
    repo_id: str,
    num: int,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    reference_rows: list[dict] | None = None,
    abuse_cfg: dict | None = None,
) -> dict:
    """Validate one PR's changes. Returns a verdict dict (no side effects).

    Guard stack (all must pass to merge):
      L1c  removes no existing file
      L1d  modifies no existing file (blob-id compare)
      L1a  adds only files under contributions/
      L1b  adds at least one contribution file
      L2   total added rows <= max_rows (anti-flood)
      L3   every added anchor row is a valid public anchor (no banned fields)
      L4   anti-abuse heuristics clean (ceilings / dup-flood / outlier)
    """
    from huggingface_hub import hf_hub_download

    details = api.get_discussion_details(repo_id, num, repo_type="dataset")
    ref = details.git_reference  # "refs/pr/<num>"
    if not ref:
        return {"num": num, "merge": False, "reason": "no_git_reference"}

    main_map = _blob_map(api, repo_id)            # main
    pr_map = _blob_map(api, repo_id, ref)         # PR branch

    # L1c — no deletions.
    removed = set(main_map) - set(pr_map)
    if removed:
        return {"num": num, "merge": False, "reason": f"removes existing file(s): {sorted(removed)}"}

    # L1d — no in-place modification of any existing file (incl. the dataset card).
    # Only flag when both blob ids are known, to avoid false positives on files
    # whose blob id can't be resolved (e.g. some LFS entries).
    modified = sorted(
        f
        for f in (set(main_map) & set(pr_map))
        if main_map[f] is not None and pr_map[f] is not None and main_map[f] != pr_map[f]
    )
    if modified:
        return {"num": num, "merge": False, "reason": f"modifies existing file(s): {modified}"}

    # L1a — additions must live exclusively under contributions/.
    added = set(pr_map) - set(main_map)
    added_outside = {f for f in added if not f.startswith("contributions/")}
    if added_outside:
        return {"num": num, "merge": False, "reason": f"adds non-contribution file(s): {sorted(added_outside)}"}

    # L1b — at least one new contribution file.
    added_contrib = [f for f in added if f.startswith("contributions/") and f.endswith(".json")]
    if not added_contrib:
        return {"num": num, "merge": False, "reason": "no_new_contribution_files"}

    # L3 + L2 — validate each added file's rows; collect them; enforce size cap.
    all_rows: list[dict] = []
    for f in added_contrib:
        local = hf_hub_download(repo_id, f, revision=ref, repo_type="dataset")
        rows, err = read_anchor_file(local)
        if err:
            return {"num": num, "merge": False, "reason": f"{f}: {err}"}
        if not rows:
            return {"num": num, "merge": False, "reason": f"{f}: no_anchor_rows"}
        for i, row in enumerate(rows):
            bad = BANNED & set(row)
            if bad:
                return {"num": num, "merge": False,
                        "reason": f"{f} row {i} carries banned field(s): {sorted(bad)}"}
            if not validate_anchor(row):
                return {"num": num, "merge": False,
                        "reason": f"{f} row {i} is not a valid public anchor"}
        all_rows.extend(rows)
        if len(all_rows) > max_rows:
            return {
                "num": num,
                "merge": False,
                "reason": f"too_large: {len(all_rows)} rows exceeds max_rows={max_rows}",
            }

    # L4 — anti-abuse heuristics.
    abuse = abuse_scan(all_rows, reference_rows, abuse_cfg)
    if abuse:
        return {"num": num, "merge": False, "reason": f"suspicious: {'; '.join(abuse)}"}

    return {"num": num, "merge": True, "reason": "all_public_anchors", "rows": len(all_rows)}


def run(
    repo_id: str,
    token: str,
    dry_run: bool = False,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    abuse_cfg: dict | None = None,
) -> list[dict]:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    # Reference distribution for the L4 outlier check = anchors already on main.
    reference_rows = load_main_reference(api, repo_id)
    discussions = api.get_repo_discussions(
        repo_id, repo_type="dataset", discussion_type="pull_request", discussion_status="open"
    )
    results: list[dict] = []
    for d in discussions:
        verdict = evaluate_pr(
            api, repo_id, d.num,
            max_rows=max_rows, reference_rows=reference_rows, abuse_cfg=abuse_cfg,
        )
        verdict["title"] = d.title
        if verdict["merge"]:
            if dry_run:
                log.info("[dry-run] would merge PR #%s (%s rows)", d.num, verdict.get("rows"))
            else:
                api.merge_pull_request(
                    repo_id, d.num, repo_type="dataset",
                    comment=f"Auto-merged: {verdict.get('rows')} validated public anchors. "
                            f"No ad/creator/identity fields present.",
                )
                log.info("merged PR #%s (%s rows)", d.num, verdict.get("rows"))
        else:
            log.warning("skipping PR #%s: %s", d.num, verdict["reason"])
            if not dry_run:
                api.comment_discussion(
                    repo_id, d.num, repo_type="dataset",
                    comment="Auto-merge skipped — left open for human review. "
                            f"Reason: {verdict['reason']}",
                )
        results.append(verdict)
    return results


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Auto-merge clean anchor PRs on the HF dataset")
    ap.add_argument("--repo", default="Ahad690/app-rank-anchors", help="HF dataset repo id")
    ap.add_argument("--token", default=None, help="HF write token (else $HF_TOKEN)")
    ap.add_argument("--dry-run", action="store_true", help="evaluate only; merge nothing")
    ap.add_argument("--max-rows", type=int, default=None,
                    help="reject PRs adding more than this many rows "
                         "(default: config federation.max_rows_per_pr, else 2000)")
    ap.add_argument("--config", default="config.json",
                    help="config file to read federation.max_rows_per_pr from")
    args = ap.parse_args(argv)

    token = args.token or os.environ.get("HF_TOKEN")
    if not token:
        log.warning("no HF_TOKEN provided; nothing to do")
        return 0

    # Resolve size cap + abuse thresholds: CLI > config.json > built-in default.
    # Read the JSON directly so this script stays self-contained (no package
    # import) in CI.
    max_rows = args.max_rows if args.max_rows is not None else DEFAULT_MAX_ROWS
    abuse_cfg = dict(DEFAULT_ABUSE)
    try:
        with open(args.config, encoding="utf-8") as fh:
            fed = json.load(fh).get("federation", {})
        if args.max_rows is None:
            max_rows = fed.get("max_rows_per_pr", DEFAULT_MAX_ROWS)
        abuse_cfg.update(fed.get("abuse", {}))
    except (OSError, json.JSONDecodeError):
        pass

    results = run(args.repo, token, dry_run=args.dry_run, max_rows=max_rows, abuse_cfg=abuse_cfg)
    merged = sum(1 for r in results if r["merge"])
    skipped = len(results) - merged
    print(json.dumps({"open_prs": len(results), "merged": merged, "skipped": skipped,
                      "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
