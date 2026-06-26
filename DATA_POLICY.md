# Data Policy

AppScope is **local-first and federated** (design principle P8). This document
states exactly what stays on your machine and what — if you opt in — is shared.

## What stays local (always)

Everything, by default. Your local database (`appscope.db`) holds rankings,
metadata, install buckets, reviews, ad snapshots, creator mentions, derived
anchors, calibration, and estimates. None of it leaves your machine unless you
explicitly run the contribution tool.

**Ad data and creator data NEVER leave your machine — there is no opt-in for
sharing them.** Ad snapshots are time-sensitive; creator handles/channels are
personal data. They are excluded from federation by design and by an enforced
guard (`assert_public_only`).

## What is shared (opt-in only)

The single shared component is a Hugging Face dataset of **public app-store
calibration anchors**. A contribution row contains only:

```
platform, category, country, list_type, rank, observed_downloads,
window_days, min_installs, real_installs, price_usd, is_free,
rating_count, captured_on
```

These are public facts: a segment, a rank, an observed download flow (derived
from the public Google Play `realInstalls` delta), and public bucket/metadata.

**`app_id` is intentionally omitted** — anchors need only (segment, rank, flow),
never app identity. No personal data, no app identity, no ads, no creators.

The shared dataset is released under **CC-BY-4.0** (see `LICENSE-DATA`).

## How sharing is enforced

- `strip_to_anchor_schema` whitelists each row to the fields above.
- `assert_public_only` **aborts the entire contribution** if any banned field
  appears: `app_id, channel, creator, handle, advertiser, ad_snapshot_url,
  creative_id, review_id, video_id, url, name, developer`.
- Contribution is **OFF by default**. An actual upload requires BOTH dropping
  `--dry-run` AND setting an `HF_TOKEN`. There is no background upload.
- `refresh_dataset.py` validates every incoming row, refuses corrupt-heavy
  files, and re-checks for banned fields before merging.

`tests/test_anchor_guard.py` proves the guard raises when ad/creator/identity
fields are injected.

## Keys & secrets

API keys (Meta Ad Library, YouTube, Hugging Face) are read from environment
variables named in `config.json` and are never stored in the config file or the
database.

## Compliance

Defaults are compliant sources (Apple RSS, iTunes lookup, official Meta Ad
Library API, Google Ads Transparency public surface, YouTube Data API), used
within terms. Opt-in scrapers (Play HTML, TikTok, Instagram) are operator
responsibility under each platform's ToS. Estimates are **modeled, not
measured**, and the project warrants nothing about accuracy.
