---
license: cc-by-4.0
language:
  - en
pretty_name: App Rank Calibration Anchors
tags:
  - app-store
  - mobile
  - calibration
  - app-intelligence
  - appscope
size_categories:
  - n<1K
---

# App Rank Anchors

Community-federated **public app-store calibration anchors** for the
[AppScope](https://github.com/Ahad690/open-app-intel) open app-intelligence
stack.

Each row is a public fact — a **segment + rank + observed download flow** —
derived from the public Google Play `realInstalls` delta over a time window
paired with an app's chart rank in that window. Pooling these anchors across
self-hosting contributors lets the Garg–Telang download estimator calibrate
absolute scale (`scale_b`) per `(platform, category, country)` segment, and
graduates estimates from LOW to MEDIUM confidence as coverage grows.

## Row schema

| field | type | meaning |
| ----- | ---- | ------- |
| `platform` | str | `ios` or `android` |
| `category` | str | store category (or `all`) |
| `country` | str | ISO country code |
| `list_type` | str | `top-free` / `top-paid` / `top-grossing` |
| `rank` | int | chart rank (1-based) |
| `observed_downloads` | int | observed download flow over the window |
| `window_days` | int | length of the observation window |
| `min_installs` | int? | public Play install bucket (Android) |
| `real_installs` | int? | public Play cumulative installs (Android) |
| `price_usd` | float | app price (0 for free) |
| `is_free` | int | 1 if free |
| `rating_count` | int? | public rating count |
| `captured_on` | date | capture date |

## What is NOT here (by design)

No app identity (`app_id` is intentionally omitted), no personal data, **no ad
data, and no creator data**. AppScope's contribution tool whitelists rows to the
schema above and aborts (`assert_public_only`) if any ad/creator/identity field
appears. See the project's `DATA_POLICY.md`.

## License

Released under **CC-BY-4.0**. Estimates derived from this data are *modeled, not
measured*; no accuracy is warranted.

## Contributing

Self-host AppScope, then run `python -m appscope.federation.contribute
--contributor <you>` (requires an `HF_TOKEN`). Pull everyone's anchors back with
`python -m appscope.federation.refresh_dataset`.
