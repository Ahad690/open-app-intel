# AppScope — User Manual

How this project actually works, end to end. If `README.md` is the pitch, this
is the mechanics.

---

## 1. The one idea you must hold in your head

**There is no server.** AppScope is not a website you log into and not an API
you call. It is a Python program **you** run on **your** machine. It captures
public app-store data into a local SQLite file, models download/revenue
estimates from that data, and answers questions — over a local REST API and a
local MCP server that your own Claude/Cursor talks to.

The only thing that is *shared* is a small Hugging Face dataset of **public
calibration anchors**. You opt in to push yours and pull everyone else's. That
shared data is what makes the estimates get better over time. Nothing else ever
leaves your machine — **ad data and creator data are never shared, by design and
by an enforced guard.**

```
YOUR MACHINE                                          SHARED (opt-in)
  collectors → local SQLite DB → estimator → REST API + MCP → your Claude
                     ▲   │
       refresh ──────┘   └────── contribute ──►  HF dataset: Ahad690/app-rank-anchors
       (pull public anchors)     (push public anchors only, guarded)   (public, CC-BY-4.0)
```

---

## 2. What lives where (the data model)

Everything is in one local SQLite file (default `appscope.db`). Tables (`§8` of
the PRD):

| Table | Holds | Shared? |
| ----- | ----- | ------- |
| `apps` | app metadata (name, developer, category, price, free/paid) | no |
| `rank_history` | one row per (app, country, list, category, day) | no |
| `install_buckets` | Android `minInstalls`/`realInstalls` per day — **the anchor source** | no (only derived anchors are) |
| `flow_anchors` | observed download-flow anchors (`source` = `local` or `community`) | the `local` ones, opt-in |
| `calibration` | fitted `scale_b` per segment | no |
| `estimates` | computed download/revenue estimates | no |
| `ad_snapshots` | ad creatives + first/last seen | **never** |
| `creator_mentions` | YouTube mentions + confidence | **never** |
| `reviews` | recent reviews | no |

---

## 3. How an estimate is actually computed

This is the heart of the project. It is a transparent regression — **no ML, no
black box** (`P6`, `N7`).

### Step A — the shape (`a`)
Downloads follow a power law against chart rank: `downloads(rank) = b · rank^(−a)`
(Garg & Telang, 2013). The exponent `a` is a published prior per platform/list
(e.g. android top-free `a≈0.95`, iOS paid `a≈0.944`). It lives in
`appscope/estimate/calibrate.py::SHAPE_A`.

### Step B — the scale (`b`), from real observations
`a` gives the *shape* of the curve but not its *height*. The height `scale_b`
must be calibrated from real observed data. An observation ("anchor") is:

> Google Play publishes `realInstalls` (cumulative). Capture it twice, N days
> apart. The **delta** is a real observed download flow. Pair it with the app's
> **rank** over that window → a real download flow at a known rank.

`derive_flow_anchor()` builds one anchor from two bucket captures + the ranks in
between. `calibrate_scale()` takes all anchors in a segment, normalizes each to a
monthly figure, and fits `scale_b` as the **geometric mean** in log space
(robust to outliers).

### Step C — the estimate, with honest confidence
`estimate_downloads()` returns `point = scale_b · rank^(−a)` plus a **range**:

- ≥ 5 anchors in the segment → band ×1.8, confidence **MEDIUM**
- < 5 anchors → band ×3.0, confidence **LOW**
- 0 anchors → confidence **NONE**, flag `no_anchor`
- **Never HIGH.** A modeled number is never presented as a measured fact (`P2`).

### Step D — sanity bound
`enforce_install_bucket()` checks the implied cumulative downloads against the
real Google install bucket. If it exceeds it (beyond a tolerance), it flags
`exceeds_install_bucket` and downgrades to LOW — it never silently emits a
bucket-violating number (`P4`).

### Step E — revenue
`estimate_revenue()`:
- **Paid app:** `downloads × price × (1 − store_cut)`, flagged `paid_app_excludes_iap`.
- **Free app, no ARPU:** returns *not estimable* (`free_app_revenue_not_estimable`).
  It will **not** invent a number (`N4`).
- **Free app + your ARPU:** `downloads × ARPU`, flagged `arpu_user_supplied`.

Every estimate comes out as the envelope:
`{value, low, high, confidence, method, sources, flags}` (`P1`).

---

## 4. The two things the project refuses to fake

1. **Dollar ad spend.** Spend = impressions × CPM ÷ 1000, and impressions live
   only in private panels. So the ad module (`appscope/ads/intensity.py`) emits
   **intensity proxies** — active-ad count, creative count, median longevity,
   refresh cadence, an intensity tier — plus a mandatory disclaimer. It never
   outputs a USD field (`P3`, hard-gated by a test).
2. **Panel-grade installs.** No estimate is ever HIGH confidence.

---

## 5. The collectors (where the data comes from)

All defaults are **compliant** sources (`P5`). Scrapers are opt-in and your
responsibility (`N6`).

| Collector | Source | Notes |
| --------- | ------ | ----- |
| `collectors/apple_rss.py` | Apple RSS top charts | default; no key |
| `collectors/itunes.py` | iTunes lookup | iOS metadata; no key |
| `collectors/play.py` | `google-play-scraper` | Android metadata + install buckets |
| `collectors/reviews.py` | Apple RSS + Play | recent reviews |
| `collectors/ads_meta.py` | **official** Meta Ad Library API | needs `META_AD_TOKEN`; local only |
| `collectors/ads_google.py` | Google Ads Transparency | opt-in, operator-supplied fetcher |
| `collectors/ads_tiktok.py` | TikTok | off by default, opt-in |
| `collectors/creators_youtube.py` | YouTube Data API | needs `YOUTUBE_API_KEY`; local only |

Every collector throttles and treats rate-limit/quota errors as non-fatal (`FR7`)
— one failing source never crashes a run.

`scheduler.py` ties them together: `python -m appscope.scheduler --once` for a
single pass, or `python -m appscope.scheduler` to run daily at the configured
UTC hour (APScheduler).

---

## 6. Federation (how estimates improve over time)

Solo, you have few anchors → LOW confidence, wide bands. The community dataset
pools anchors across self-hosters so each segment reaches ≥5 anchors → MEDIUM
confidence, tighter bands (KPI K6). **Only public app-store facts are shared.**

### Pull (everyone does this)
```bash
python -m appscope.federation.refresh_dataset            # --dry-run to preview
```
Downloads anchors from the HF dataset, validates each row (schema + range + no
banned fields), **refuses** corrupt-heavy files, **no-ops** if too few new rows,
merges clean new rows as `source='community'`, then refits calibration.

### Push (opt-in contributors)
```bash
python -m appscope.federation.contribute --dry-run             # prints what would be shared
python -m appscope.federation.contribute --contributor you     # opens a PR (needs HF_TOKEN)
```
`build_contribution()` takes your `local` anchors, **whitelists** them to the
public anchor schema (`strip_to_anchor_schema`), and runs `assert_public_only()`
— which **aborts the whole upload** if any of these appear:
`app_id, channel, creator, handle, advertiser, ad_snapshot_url, creative_id,
review_id, video_id, url, name, developer`.

Contribution is **OFF by default**: it requires BOTH dropping `--dry-run` AND an
`HF_TOKEN`. There is no background upload.

Each contribution is written to `contributions/<you>-<content-hash>.json`, so
repeat or parallel contributions never overwrite each other (and identical data
re-contributed is idempotent). `--existing <file.json>` dedups against anchors
already in the dataset. The guard `assert_public_only` aborts on **any** banned
field *and* on any field not on the public whitelist (defense in depth), and your
name is appended to `CONTRIBUTORS.md` on a successful upload.

After every collection/refresh run, a short colored reminder shows how to
contribute. Turn it off with `federation.contribute_reminder = false`.

A contribution row is only:
`platform, category, country, list_type, rank, observed_downloads, window_days,
min_installs, real_installs, price_usd, is_free, rating_count, captured_on`.
`app_id` is intentionally omitted — anchors need a *segment*, not an *identity*.

### The shared dataset
<https://huggingface.co/datasets/Ahad690/app-rank-anchors> (public, CC-BY-4.0).
It starts **empty of anchors** — it fills only with real contributions. (There is
no fabricated seed: `data/anchors.example.json` exists for tests/demos only and
is clearly marked `_synthetic`; it is never federated.)

---

## 7. Automated PR merging (CI)

Contributors open PRs against the dataset (via `contribute.py`). A GitHub Action
(`.github/workflows/automerge-dataset-prs.yml`) merges the clean ones daily.

**How the auth works** — this is *not* `git push`. It is the `huggingface_hub`
library making authenticated HTTPS API calls, driven by a token stored as a
GitHub secret:

```
fine-grained HF token → GitHub repo secret (HF_TOKEN) → workflow env var
  → huggingface_hub → HF REST API
```

The workflow runs `appscope/federation/automerge_prs.py`, which lists open PRs
and merges one ONLY if it clears every guard layer (else it comments the reason
and leaves the PR open for a human — never a silent drop):

| Layer | Guard |
| ----- | ----- |
| L0 | only **open** PRs are considered (idempotent / re-runnable) |
| L1c | **removes no** existing file (blob-id diff via `repo_info(files_metadata=True)`) |
| L1d | **modifies no** existing file, incl. the dataset card (blob-id diff) |
| L1a | adds files **only** under `contributions/*.json` |
| L1b | adds at least one contribution file |
| L2 | total added rows ≤ `federation.max_rows_per_pr` (default 2000) — anti-flood |
| L3 | **every** anchor row is a valid public anchor: right schema, in-range, and **no** ad/creator/identity field (any bad row holds the whole PR) |
| L4 | **anti-abuse heuristics** on well-formed-but-suspicious data: absolute ceilings (`rank ≤ 2000`, `window_days ≤ 365`, implied monthly downloads `≤ 100M`), duplicate-flooding (unique-row ratio `≥ 0.5`), and per-segment median that is a wild multiple (`>10×` or `<0.1×`) of the reference distribution already on `main` (scale manipulation). All thresholds live in `config.json` `federation.abuse`. The outlier check auto-activates only once a segment has ≥3 reference rows, so it is silent on a fresh/empty dataset. |

> **Concurrent-PR staleness (safe by design).** A PR's branch is a snapshot of
> `main` at branch time. If another PR merges first, open PRs branched earlier
> will look like they *delete/modify* the newly-merged files, so L1c/L1d will
> **HOLD** them. This never causes a wrong merge — only a conservative hold. The
> contributor resolves it by rebasing (or closing + re-running `contribute`).

**Recovery layer (the safety net).** A Hugging Face repo *is* a git repo, so
nothing is ever truly overwritten and any bad merge is one corrective commit
away from undone (we used exactly this to delete the synthetic seed). Two
practices make that real:

- **Pin consumers.** Set `federation.pinned_revision` to a reviewed commit SHA
  or tag; `refresh_dataset` then pulls *that* revision instead of `main`, so a
  bad auto-merge on `main` can't reach you until you bump the pin. CLI override:
  `python -m appscope.federation.refresh_dataset --revision <sha-or-tag>`.
- **Tag known-good snapshots** after review:
  `huggingface_hub.HfApi().create_tag("Ahad690/app-rank-anchors", tag="v1", revision="<sha>", repo_type="dataset")`,
  then point `pinned_revision` at `v1`.

So **prevention** (L0–L3) narrows the blast radius; **versioning + pinning**
guarantees recovery. The honest boundary: these layers prove a row is
well-formed, in-range, and identity-free — they do **not** prove the numbers are
authentic. A patient adversary could submit plausible, in-distribution fake
data. That residual risk is exactly why the recovery layer matters.

The script is self-contained (only needs `huggingface_hub`) so CI stays tiny; a
test (`test_automerge_banned_matches_canonical`) keeps its inlined guard in sync
with the canonical one.

### One-time setup to turn it on
1. Create a **fine-grained** HF token with **write** access to
   `Ahad690/app-rank-anchors` at <https://huggingface.co/settings/tokens>.
   *(Use a fine-grained token, not an `hf auth login` OAuth token — those expire
   and the scheduled job would silently start failing.)*
2. Store it as a GitHub Actions secret:
   ```bash
   gh secret set HF_TOKEN -R Ahad690/open-app-intel
   # paste the token when prompted
   ```
3. Trigger it manually to test: `gh workflow run "Auto-merge dataset PRs" -R Ahad690/open-app-intel`,
   or wait for the daily 06:00 UTC schedule.

Forked-PR runs don't receive secrets (GitHub security) — that's why this uses
`schedule` / `workflow_dispatch`, not a `pull_request` trigger. The workflow also
no-ops cleanly if the secret is unset.

---

## 8. Querying your data

### REST API
```bash
uvicorn appscope.api:app --host 127.0.0.1 --port 8000
```
- `GET /apps/{app_id}/estimate?country=us` → the P1 estimate envelope
- `GET /apps/{app_id}/ads` → intensity proxies (+ disclaimer, never USD)
- `GET /apps/{app_id}/creators?min_confidence=0.6`
- `GET /apps/{app_id}/ranks?days=30`
- `GET /apps/{app_id}/reviews?days=30`

### MCP server (for your Claude/Cursor)
```bash
python -m appscope.mcp_server
```
Add to your client's MCP config:
```json
{ "mcpServers": { "appscope": {
  "command": "python", "args": ["-m", "appscope.mcp_server"],
  "cwd": "/path/to/open-app-intel" } } }
```
Tools: `app_estimate`, `ad_intensity`, `creator_mentions`, `rank_history`.

---

## 9. Configuration & keys

Everything tunable is in `config.json` (copy from `config.sample.json`). All
estimator constants live there for determinism (`P7`): `min_anchors_for_medium`,
band factors, `store_cut`, `bucket_tolerance`, tracked apps/countries, the
federation repo and gates, the daily hour.

Keys are read from **environment variables named in the config** and are never
stored in the file or the DB:
- `META_AD_TOKEN` — Meta Ad Library (ads; optional)
- `YOUTUBE_API_KEY` — YouTube Data API (creators; optional)
- `HF_TOKEN` — Hugging Face (contributors / CITs only)

---

## 10. A typical first session

```bash
pip install -r requirements.txt
cp config.sample.json config.json            # edit tracking.apps to your targets
python -m appscope.scheduler --once          # capture today's data
python -m appscope.federation.refresh_dataset  # pull community anchors, calibrate
uvicorn appscope.api:app                     # ...or python -m appscope.mcp_server
# then ask your Claude:  "what's the download estimate for <app_id>?"
```

Run the scheduler daily for a couple of weeks and you'll have your own
install-bucket deltas → your own real anchors → you can `contribute` them back.

---

## 11. Tests

```bash
pip install pytest && pytest -q
```
56+ tests cover: anchor derivation, calibration, the never-HIGH cap, free-app
revenue honesty, the no-USD ad gate (K2), the mention-precision gate (K5 ≥ 0.8),
the federation guard (banned fields rejected), refresh gating, and the
auto-merge validation.

---

## 12. Honesty rules summary (what the code enforces)

| Rule | Meaning | Where |
| ---- | ------- | ----- |
| P1 | every number carries confidence + method + provenance | `estimate/`, `api.py`, `mcp_server.py` |
| P2 | estimates are ranges, **never above MEDIUM** | `estimate/downloads.py` |
| P3 | ad **proxies, never dollars** + disclaimer | `ads/intensity.py` |
| P4 | install-bucket sanity bound, flagged not hidden | `estimate/downloads.py` |
| N4 | free-app revenue **not invented** | `estimate/revenue.py` |
| P8 | local-first; federate **only public anchors**; guard aborts on ad/creator/identity | `federation/contribute.py`, `automerge_prs.py` |

See `DATA_POLICY.md` for the exact data-sharing policy.
