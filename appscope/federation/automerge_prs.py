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
from typing import Any

log = logging.getLogger("automerge")

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


def validate_contribution_file(path: str) -> tuple[bool, str, int]:
    """Return ``(ok, reason, n_rows)`` for a downloaded contribution JSON file."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"unreadable_json: {exc}", 0
    anchors = _anchors_from_payload(data)
    if not anchors:
        return False, "no_anchor_rows", 0
    for i, row in enumerate(anchors):
        bad = BANNED & set(row)
        if bad:
            return False, f"row {i} carries banned field(s): {sorted(bad)}", len(anchors)
        if not validate_anchor(row):
            return False, f"row {i} is not a valid public anchor", len(anchors)
    return True, "ok", len(anchors)


def evaluate_pr(api, repo_id: str, num: int) -> dict:
    """Validate one PR's changes. Returns a verdict dict (no side effects)."""
    from huggingface_hub import hf_hub_download

    details = api.get_discussion_details(repo_id, num, repo_type="dataset")
    ref = details.git_reference  # "refs/pr/<num>"
    if not ref:
        return {"num": num, "merge": False, "reason": "no_git_reference"}

    files_at_pr = set(api.list_repo_files(repo_id, revision=ref, repo_type="dataset"))
    files_on_main = set(api.list_repo_files(repo_id, repo_type="dataset"))

    # Only auto-merge PRs that add files exclusively under contributions/.
    added_outside = {
        f for f in (files_at_pr - files_on_main) if not f.startswith("contributions/")
    }
    if added_outside:
        return {
            "num": num,
            "merge": False,
            "reason": f"adds non-contribution file(s): {sorted(added_outside)}",
        }

    contrib_files = [f for f in files_at_pr if f.startswith("contributions/") and f.endswith(".json")]
    if not contrib_files:
        return {"num": num, "merge": False, "reason": "no_contribution_files"}

    total_rows = 0
    for f in contrib_files:
        local = hf_hub_download(repo_id, f, revision=ref, repo_type="dataset")
        ok, reason, n = validate_contribution_file(local)
        if not ok:
            return {"num": num, "merge": False, "reason": f"{f}: {reason}"}
        total_rows += n
    return {"num": num, "merge": True, "reason": "all_public_anchors", "rows": total_rows}


def run(repo_id: str, token: str, dry_run: bool = False) -> list[dict]:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    discussions = api.get_repo_discussions(
        repo_id, repo_type="dataset", discussion_type="pull_request", discussion_status="open"
    )
    results: list[dict] = []
    for d in discussions:
        verdict = evaluate_pr(api, repo_id, d.num)
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
    args = ap.parse_args(argv)

    token = args.token or os.environ.get("HF_TOKEN")
    if not token:
        log.warning("no HF_TOKEN provided; nothing to do")
        return 0

    results = run(args.repo, token, dry_run=args.dry_run)
    merged = sum(1 for r in results if r["merge"])
    skipped = len(results) - merged
    print(json.dumps({"open_prs": len(results), "merged": merged, "skipped": skipped,
                      "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
