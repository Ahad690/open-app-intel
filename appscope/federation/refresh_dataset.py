"""Federated refresh — pull community anchors, validate, merge, recalibrate (§9H).

Pulls public anchors from the shared HF dataset, validates each (schema + range
+ no banned fields), refuses corrupt-heavy files, no-ops below ``min_new``,
merges clean NEW rows into ``flow_anchors`` (source='community'), then refits
calibration. Deterministic afterwards (P7). Supports ``--dry-run``.
"""
from __future__ import annotations

import argparse
import json
import logging
from typing import Callable

from ..config import load_config
from ..db import Database
from .contribute import BANNED, _repo_id_from_url

log = logging.getLogger(__name__)


def validate_anchor(r: dict) -> bool:
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


def fetch_hf_dataset(
    dataset_repo: str, hf_token: str | None = None, revision: str | None = None
) -> list[dict]:
    """Download and concatenate anchor rows from every JSON file in the dataset.

    ``revision`` pins the pull to a specific commit SHA, tag, or branch. Pinning
    to a reviewed snapshot is the recovery layer: a bad auto-merge on ``main``
    can't reach a consumer pinned to a known-good revision. ``None`` => ``main``.

    Best-effort and network-dependent; returns ``[]`` on failure so a refresh
    never crashes a local install.
    """
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except Exception as exc:  # pragma: no cover
        log.error("huggingface_hub unavailable: %s", exc)
        return []

    repo_id = _repo_id_from_url(dataset_repo)
    rows: list[dict] = []
    try:
        api = HfApi(token=hf_token)
        files = [
            f
            for f in api.list_repo_files(repo_id, repo_type="dataset", revision=revision)
            if f.endswith(".json")
        ]
        for fname in files:
            path = hf_hub_download(
                repo_id, fname, repo_type="dataset", token=hf_token, revision=revision
            )
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            anchors = data.get("anchors", data) if isinstance(data, dict) else data
            if isinstance(anchors, list):
                rows.extend(a for a in anchors if isinstance(a, dict))
    except Exception as exc:
        log.warning("failed to fetch HF dataset %s@%s: %s", repo_id, revision or "main", exc)
        return []
    return rows


def refresh(
    db: Database,
    dataset_repo: str,
    min_new: int = 50,
    max_corrupt_ratio: float = 0.25,
    dry_run: bool = False,
    *,
    revision: str | None = None,
    hf_token: str | None = None,
    fetcher: Callable[[], list[dict]] | None = None,
) -> dict:
    """Pull, validate, gate, merge, and recalibrate.

    ``revision`` pins the pull to a reviewed commit/tag (recovery layer).
    ``fetcher`` overrides the default HF download (used in tests). Returns a
    status dict: ``refused`` / ``noop`` / ``preview`` / ``merged``.
    """
    incoming = (
        fetcher()
        if fetcher is not None
        else fetch_hf_dataset(dataset_repo, hf_token=hf_token, revision=revision)
    )
    clean = [r for r in incoming if validate_anchor(r)]
    corrupt = len(incoming) - len(clean)
    if incoming and corrupt / len(incoming) > max_corrupt_ratio:
        return {
            "status": "refused",
            "reason": "too_many_corrupt",
            "corrupt": corrupt,
            "total": len(incoming),
        }

    new = db.dedup_against_local(clean)
    if len(new) < min_new:
        return {"status": "noop", "new_rows": len(new), "min_new": min_new}

    if not dry_run:
        db.insert_flow_anchors(new, source="community")
        db.recalibrate_all_segments()

    return {"status": "preview" if dry_run else "merged", "new_rows": len(new)}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Refresh local calibration from the HF anchor dataset")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry-run", action="store_true", help="preview; merge nothing")
    ap.add_argument("--revision", default=None,
                    help="pin the pull to a commit SHA/tag/branch (overrides config.pinned_revision)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    db = Database(cfg.storage.path)
    db.bootstrap()

    revision = args.revision or cfg.federation.pinned_revision
    if revision:
        log.info("pinned pull: %s@%s", cfg.federation.dataset_repo, revision)

    result = refresh(
        db,
        cfg.federation.dataset_repo,
        min_new=cfg.federation.min_new_on_refresh,
        max_corrupt_ratio=cfg.federation.max_corrupt_ratio,
        dry_run=args.dry_run,
        revision=revision,
        hf_token=cfg.hf_token(),
    )
    print(json.dumps({**result, "revision": revision or "main"}, indent=2))
    if result["status"] in {"merged", "preview"}:
        print(json.dumps({"k6_coverage": db.calibration_coverage()}, indent=2))

    from ..reminders import print_contribute_reminder

    print_contribute_reminder(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
