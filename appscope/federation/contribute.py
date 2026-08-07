"""Federated contribution — push public calibration anchors only (§9G, FR18/19/21).

Hard rule (P8): the ONLY data that ever leaves a machine is public app-store
calibration anchors (segment + rank + observed flow + bucket/metadata). Ads and
creator data are NEVER uploaded. ``assert_public_only`` aborts on any
ad/creator/identity field.

OFF by default: an actual upload requires BOTH dropping ``--dry-run`` AND an
``HF_TOKEN``. No background upload ever happens.
"""
from __future__ import annotations

import argparse
import json
import logging

from ..config import load_config
from ..db import Database

log = logging.getLogger(__name__)

# The whitelist of shareable fields (the §8 shared-anchor schema).
ANCHOR_KEEP = {
    "platform",
    "category",
    "country",
    "list_type",
    "rank",
    "observed_downloads",
    "window_days",
    "min_installs",
    "real_installs",
    "price_usd",
    "is_free",
    "rating_count",
    "captured_on",
}

# Fields that must NEVER appear in a contribution (ads/creator/identity).
BANNED = {
    "app_id",
    "channel",
    "creator",
    "handle",
    "advertiser",
    "ad_snapshot_url",
    "creative_id",
    "review_id",
    "video_id",
    "url",
    "name",
    "developer",
}


def strip_to_anchor_schema(row: dict) -> dict:
    """Keep only whitelisted anchor fields (defense in depth)."""
    return {k: row[k] for k in ANCHOR_KEEP if k in row}


def assert_public_only(records: list[dict]) -> None:
    """Hard guard (P8): abort before anything leaves the machine.

    Two layers (matching the fiverr-gig-optimizer PII guard):
      1. any explicitly banned ad/creator/identity field => abort,
      2. any field NOT on the public anchor whitelist => abort (defense in depth:
         even an unexpected/new column can't ride through).
    """
    for rec in records:
        bad = BANNED & set(rec)
        if bad:
            raise ValueError(f"refusing to upload non-public fields: {sorted(bad)}")
        unexpected = set(rec) - ANCHOR_KEEP
        if unexpected:
            raise ValueError(f"refusing to upload non-whitelisted fields: {sorted(unexpected)}")


def _record_key(r: dict) -> str:
    """Stable identity of an anchor record (post-strip) for dedup."""
    return json.dumps(strip_to_anchor_schema(r), sort_keys=True)


def dedup(records: list[dict], existing: list[dict] | None = None) -> list[dict]:
    """Drop exact-duplicate anchor records (stable order).

    ``existing`` (e.g. anchors already in the dataset) are pre-seeded so already-
    contributed rows are skipped — cross-file dedup, like fiver's ``--existing``.
    """
    seen: set[str] = {_record_key(r) for r in (existing or [])}
    out: list[dict] = []
    for r in records:
        key = _record_key(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def build_contribution(db: Database, existing: list[dict] | None = None) -> list[dict]:
    """Collect local anchors, strip to the anchor schema, guard, and dedup."""
    rows = db.fetch_shareable_anchors()
    records = [strip_to_anchor_schema(r) for r in rows]
    assert_public_only(records)  # must pass before any upload
    return dedup(records, existing=existing)


def _repo_id_from_url(dataset_repo: str) -> str:
    """Accept either a full HF URL or a bare ``owner/name`` repo id."""
    marker = "huggingface.co/datasets/"
    if marker in dataset_repo:
        return dataset_repo.split(marker, 1)[1].strip("/")
    return dataset_repo.strip("/")


def upload_contribution(
    records: list[dict], dataset_repo: str, hf_token: str, contributor: str
) -> str:
    """Open a PR on the HF dataset adding the contributor's anchor file.

    Returns the PR/commit URL. Re-asserts the guard immediately before upload.
    """
    assert_public_only(records)  # belt-and-suspenders right before network I/O
    import hashlib

    from huggingface_hub import CommitOperationAdd, HfApi

    repo_id = _repo_id_from_url(dataset_repo)
    api = HfApi(token=hf_token)
    payload = json.dumps({"anchors": records}, indent=2).encode("utf-8")
    safe_name = "".join(c for c in contributor if c.isalnum() or c in "-_") or "anon"
    # Content-hash suffix so repeat/parallel contributions never overwrite each
    # other (which would otherwise be a "modifies existing file" auto-merge hold);
    # identical data re-contributed maps to the same file (idempotent).
    digest = hashlib.sha256(payload).hexdigest()[:10]
    path_in_repo = f"contributions/{safe_name}-{digest}.json"
    info = api.create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        operations=[CommitOperationAdd(path_in_repo=path_in_repo, path_or_fileobj=payload)],
        commit_message=f"anchors contribution from {safe_name}",
        create_pr=True,
        token=hf_token,
    )
    return getattr(info, "pr_url", None) or str(info)


def append_contributor(name: str, path: str = "CONTRIBUTORS.md") -> None:
    """Append a contributor to CONTRIBUTORS.md (idempotent; non-fatal on error)."""
    line = f"| {name} | anchors |\n"
    try:
        from pathlib import Path

        p = Path(path)
        if p.exists() and line in p.read_text(encoding="utf-8"):
            return
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as exc:
        log.warning("could not update %s: %s", path, exc)


def _max_rows_from_config(path: str, default: int = 2000) -> int:
    """Rows-per-contribution cap, mirroring the receiver's anti-flood limit.

    Read straight from the JSON so the sending side cannot drift from
    ``federation.max_rows_per_pr`` — offering more than the receiver will accept
    guarantees a permanently held PR.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return int(json.load(fh).get("federation", {}).get("max_rows_per_pr", default))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Contribute public anchors to the HF dataset")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry-run", action="store_true", help="print cleaned records; upload nothing")
    ap.add_argument("--contributor", default=None, help="contributor name (required to upload)")
    ap.add_argument("--token", default=None,
                    help="HF write token; cached for reuse (else $HF_TOKEN / cached token)")
    ap.add_argument("--existing", default=None,
                    help="JSON of anchors already in the dataset, for cross-file dedup")
    ap.add_argument("--no-remote-dedup", action="store_true",
                    help="skip fetching the dataset's merged anchors for dedup "
                         "(offline; will re-offer rows already contributed)")
    ap.add_argument("--max-rows", type=int, default=None,
                    help="cap rows per contribution so a backlog drains over "
                         "successive runs instead of exceeding the receiver's "
                         "anti-flood cap (default: federation.max_rows_per_pr)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    db = Database(cfg.storage.path)
    db.bootstrap()

    existing = None
    if args.existing:
        try:
            with open(args.existing, encoding="utf-8") as fh:
                data = json.load(fh)
            existing = data.get("anchors", data) if isinstance(data, dict) else data
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[warn] could not read --existing {args.existing}: {exc}")

    # Dedup against what is ALREADY merged on the dataset. Without this every run
    # re-offers the entire local history, which grows without bound and — once it
    # passes the receiver's anti-flood cap — deadlocks: nothing merges, so the
    # backlog grows, so nothing merges. Best-effort; offline just means no
    # remote dedup, never a crash.
    if existing is None and not args.no_remote_dedup:
        try:
            from huggingface_hub import HfApi

            from .automerge_prs import load_main_reference

            repo_id = _repo_id_from_url(cfg.federation.dataset_repo)
            existing = load_main_reference(HfApi(), repo_id)
            print(f"# {len(existing)} anchors already on {repo_id}; deduping against them")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] remote dedup unavailable ({type(exc).__name__}: {exc}); "
                  "continuing without it")

    records = build_contribution(db, existing=existing)

    # Bound one contribution so a large backlog drains across runs rather than
    # tripping the receiver's cap forever.
    cap = args.max_rows if args.max_rows is not None else _max_rows_from_config(args.config)
    remaining = 0
    if cap and len(records) > cap:
        remaining = len(records) - cap
        records = records[:cap]
        print(f"# capped to {cap} row(s) this run; {remaining} still queued for the next run")

    print(f"# {len(records)} cleaned public anchor records (ads/creators excluded by guard):")
    print(json.dumps(records, indent=2))

    if args.dry_run:
        print("\n[dry-run] nothing uploaded.")
        return 0

    from .token_bootstrap import bootstrap_token

    if args.token:  # a freshly-pasted token: cache it so this is a one-time step
        try:
            from huggingface_hub import login

            login(token=args.token, add_to_git_credential=False)
        except Exception:
            pass
    # --token -> env HF_TOKEN -> cached token -> one-time guided setup (opens the page).
    hf_token = args.token or cfg.hf_token() or bootstrap_token(cfg.federation.dataset_repo)
    if not hf_token:
        print("\n[abort] no HF token; contribution is OFF by default. "
              "Create one via the link above (or set HF_TOKEN), then re-run.")
        return 1
    if not args.contributor:
        print("\n[abort] --contributor NAME required to open a PR.")
        return 1

    if not records:
        print("\nNothing new to contribute (all rows already present or empty).")
        return 0

    url = upload_contribution(records, cfg.federation.dataset_repo, hf_token, args.contributor)
    append_contributor(args.contributor)
    print(f"\n[uploaded] opened PR: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
