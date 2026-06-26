# AppScope — Open App Intelligence Stack

A **self-hosted, federated** open-source app market-intelligence tool + MCP
server. An honest OSS take on the reproducible ~60% of tools like AppKittie /
Sensor Tower / AppTweak.

> Every number is produced by a documented model on real, locally-captured data,
> always with a **confidence label, a method tag, and the data behind it**. The
> system refuses to fabricate the two figures vendors model from private panels
> (dollar ad spend, panel-grade installs).

---

## There is no central server

**Each user self-hosts.** You clone the repo, supply your own keys, and run the
collectors, estimator, REST API and MCP server **on your own machine** (or your
own cheap VPS). Your captured data lives in a **local** SQLite database. Your own
Claude/Cursor connects to **your own** local MCP server.

There is no shared API endpoint, no central bill, no shared uptime obligation,
no central scraping-ToS exposure. If your machine is down, only *your* instance
is affected.

The **only** shared component is an opt-in Hugging Face dataset of **public
app-store calibration anchors** that everyone pulls back to sharpen their
estimates (see [Federation](#federation)).

> 📖 For a full how-it-works walkthrough (the estimator math, the data model, and
> the CI auto-merge setup), read **[USER_MANUAL.md](USER_MANUAL.md)**.

---

## What it does

| Capability | How | Honesty |
| ---------- | --- | ------- |
| Rankings + metadata | Apple RSS top charts, iTunes lookup, Google Play | Fully reproducible (HIGH = observed fact) |
| Install buckets (Android) | `google-play-scraper` `minInstalls`/`realInstalls` | Observed fact; the anchor source |
| Download/revenue **estimates** | Garg–Telang rank→download power law, scale calibrated from pooled anchors | Ranges, **capped at MEDIUM**, with method + provenance |
| Ad creative & cadence | Meta Ad Library (official API), Google Ads Transparency, optional TikTok | **Spend-intensity proxies, never dollars.** Local only |
| Creator attribution | YouTube Data API + rule-based mention classifier | Partial recall, precision-gated. Local only |
| Reviews | Apple RSS + Play | Observed counts |
| REST API + MCP | FastAPI + FastMCP | Local |
| Federation | `contribute.py` / `refresh_dataset.py` → HF dataset | Public anchors only |

---

## The honesty rules (enforced)

- **P1 — Every number carries confidence + method + provenance.** Envelope:
  `{value, low, high, confidence, method, sources, flags}`.
- **P2 — Estimates are ranges, capped at MEDIUM.** HIGH is reserved for directly
  observed facts (a captured rank, a real install bucket, a real review count).
  A modeled estimate is **never** HIGH.
- **P3 — Proxies, not dollars, for ads.** The ad module emits intensity proxies
  and a mandatory disclaimer; it **never** outputs USD spend.
- **P4 — Sanity bounds.** A cumulative download estimate must respect the Google
  install bucket; violations are flagged and downgraded, never silently emitted.
- **N4 — Free-app revenue is never invented.** Returns *not estimable* unless you
  supply an ARPU.
- **P8 — Local-first; federate only public anchors.** Ads and creator data
  **never** leave your machine. A guard (`assert_public_only`) aborts any
  contribution carrying ad/creator/identity fields.

---

## The three known gaps (stated plainly)

1. **Downloads / revenue — partially solvable, and improves with the shared
   dataset.** Calibrating absolute scale is the hard part; federation pools
   install-bucket-derived anchors so segments reach ≥5 anchors and graduate
   LOW → MEDIUM. Never panel-grade.
2. **Ad spend — a hard gap; proxies only.** Spend = impressions × CPM ÷ 1000,
   and impressions live only in opt-in panels. Public ad libraries expose
   creatives + run dates (banded spend only for EU/political ads). So we emit
   intensity proxies, never dollars — and ads never federate.
3. **Creator attribution — the hardest; partial recall, local-first.** YouTube
   Data API is the one fully-compliant organic-discovery route; the rule-based
   mention classifier is the missing middle layer. Creator data stays local.

---

## Install

```bash
git clone <your-fork> open-app-intel && cd open-app-intel
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.sample.json config.json                # then edit tracking.apps etc.
```

Keys are read from environment variables named in `config.json` (never stored):

```bash
export META_AD_TOKEN=...      # Meta Ad Library (ads, optional)
export YOUTUBE_API_KEY=...    # YouTube Data API (creators, optional)
export HF_TOKEN=...           # Hugging Face (contributors only)
```

## Run

```bash
# 1. Collect (one pass now, or run as a daily scheduler)
python -m appscope.scheduler --once
python -m appscope.scheduler            # daily at config.schedule.daily_hour_utc (UTC)

# 2. Seed + calibrate from the community anchors
python -m appscope.federation.refresh_dataset

# 3a. Local REST API
uvicorn appscope.api:app --host 127.0.0.1 --port 8000
#   GET /apps/{app_id}/estimate?country=us   -> P1 envelope
#   GET /apps/{app_id}/ads                    -> intensity proxies (no USD)
#   GET /apps/{app_id}/creators?min_confidence=0.6
#   GET /apps/{app_id}/ranks?days=30
#   GET /apps/{app_id}/reviews?days=30

# 3b. Local MCP server (point your Claude/Cursor at this)
python -m appscope.mcp_server
```

### Connecting your local Claude to your local MCP server

Add to your Claude/Cursor MCP config (each user, locally):

```json
{
  "mcpServers": {
    "appscope": {
      "command": "python",
      "args": ["-m", "appscope.mcp_server"],
      "cwd": "/path/to/open-app-intel"
    }
  }
}
```

Tools exposed: `app_estimate`, `ad_intensity`, `creator_mentions`, `rank_history`.

---

## Federation

The estimator's weak link is calibrating absolute scale (`scale_b`), which needs
anchor points that are scarce solo. Federating Android install-bucket deltas as
observed download-flow anchors pools enough data to calibrate per segment.

```bash
# Pull everyone's public anchors, validate, merge, and refit calibration
python -m appscope.federation.refresh_dataset            # --dry-run to preview

# Share YOUR public anchors (opt-in; needs --contributor AND HF_TOKEN)
python -m appscope.federation.contribute --dry-run        # prints what would be shared
python -m appscope.federation.contribute --contributor you
```

Shared dataset: <https://huggingface.co/datasets/Ahad690/app-rank-anchors>
(CC-BY-4.0). A contribution row is **only**: `platform, category, country,
list_type, rank, observed_downloads, window_days, min_installs, real_installs,
price_usd, is_free, rating_count, captured_on`. `app_id` is intentionally
omitted. **No ads, no creators, no identity** — enforced by `assert_public_only`
and proven by `tests/test_anchor_guard.py`. See **[DATA_POLICY.md](DATA_POLICY.md)**.

Contribution PRs are auto-merged daily by a GitHub Action
(`.github/workflows/automerge-dataset-prs.yml`) that **re-validates every anchor
row on the receiving side** before merging — see
[USER_MANUAL.md §7](USER_MANUAL.md#7-automated-pr-merging-ci) for the one-time
`HF_TOKEN` secret setup.

---

## Tests

```bash
pip install pytest
pytest -q
```

Covers anchor derivation, calibration, the never-HIGH cap, free-app revenue,
the no-USD ad gate (K2), the mention-precision gate (K5), and the federation
guard (K-P8).

---

## Legal / compliance

Self-host, compliant by default: Apple RSS, iTunes lookup, official Meta Ad
Library API, Google Ads Transparency, YouTube Data API, used within terms.
Opt-in scrapers (Play HTML, TikTok, Instagram) are operator responsibility under
each platform's ToS; the legal landscape is unsettled. **Estimates are modeled,
not measured** — labeled as such; the project warrants nothing about accuracy.

Code: MIT ([LICENSE](LICENSE)). Data + docs: CC-BY-4.0 ([LICENSE-DATA](LICENSE-DATA)).
