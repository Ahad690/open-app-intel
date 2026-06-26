# PRD — Open App Intelligence Stack (working name: **AppScope**)

**Version:** 1.1 (supersedes 1.0)
**Status:** Ready to build
**Type:** Self-hosted, federated open-source app market-intelligence tool + MCP server (OSS alternative to AppKittie for the replicable ~60%)
**Working name:** "AppScope" — verify no trademark collision and rename freely before launch.

---

## Changelog (v1.0 → v1.1)

v1.0 implied a **central server** that you host and others query over MCP. That makes you a single point of failure, puts all cost and scraping-ToS exposure on you, and is really a SaaS. v1.1 switches to the **federated, self-hosted-per-user model** (the same shape as `github.com/Ahad690/fiverr-gig-optimizer`): each user runs the collectors on their own machine with their own keys, their own Claude connects to their own local MCP server, and an opt-in `contribute.py` / `refresh_dataset.py` loop shares **public app-store calibration anchors** through a community Hugging Face dataset that everyone pulls back to improve their estimates.

- **A1 — Runtime is self-hosted-per-user + federated dataset, not a central server.** No shared uptime obligation, no central bill, no central ToS exposure. (§1.3, §7)
- **A2 — The shared dataset is the thing that makes estimates work.** Calibrating absolute download scale (`scale_b`) needs anchor points, which are scarce solo. Federating Android **install-bucket deltas** as observed download-flow anchors pools enough data to calibrate per segment — so federation isn't just cost-sharing, it's the mechanism that closes the estimator's weak link. (§9B, §9G/§9H, §17)
- **A3 — Only public app-store anchors federate; ads & creators stay local.** App rankings/install buckets/metadata are public facts with no personal data. Ad snapshots and creator handles are time-sensitive and/or personal, so they are **never uploaded**. A guard aborts any contribution carrying ad/creator/identity fields. (§3 P8, §9G, §15, DATA_POLICY.md)
- **A4 — New `flow_anchors` table; calibration refits from pooled local + community anchors.** (§8, §9B)
- **A5 — New federation build stage, acceptance checks, and a calibration-coverage KPI.** (§5a K6, §13 Stage 4, §14)
- **A6 — Config gains a `federation` block + HF token; deps gain `huggingface_hub`.** (§11, §12)

Where this changelog conflicts with anything below, the changelog and the updated section win.

---

## 0. How to build this with Claude Code

This is **not a Claude Code skill** — it is a self-hosted, federated Python tool you build with Claude Code and run locally (see §1.3). To one-shot the scaffold:

1. Create an empty directory, `git init`, save this file as `PRD.md`.
2. In Claude Code:
   > Read `PRD.md` in full including the Changelog. Build the project per Section 13 (Build Order), stage by stage. Create every file in Section 10. Use the reference code in Section 9 as the implementation starting point and complete it. There is NO central server: each user runs this locally with their own keys and their own MCP server. Enforce the honesty rules in Section 3: every estimate carries confidence + method + provenance, download/revenue estimates are ranges capped at MEDIUM confidence, dollar ad-spend is never emitted, free-app revenue is never fabricated. The federated dataset shares ONLY public app-store calibration anchors — ads and creator data are never uploaded; the contribution guard must abort if they appear.

**North-star rule (carried from the Fiverr project):** every number is produced by a documented model on real, locally-captured data, always with a confidence label, a method tag, and the data behind it. The system refuses to fabricate the two figures vendors model from private panels (dollar ad spend, panel-grade installs). The community dataset improves estimates over time by pooling observations — never by sharing fabricated numbers.

---

## 1. Overview

### 1.1 What we are building
A self-hostable, federated tool reproducing the reproducible parts of AppKittie and honest about the rest:

- **App discovery + metadata + rankings** (Apple RSS top charts, Google Play, iTunes lookup) — fully reproducible.
- **Download & revenue *estimates*** via the Garg–Telang public rank→download power law, with **scale calibrated from a community dataset of install-bucket-derived anchors** and cross-checked against AppTweak's free tier — directional ranges, never panel-grade precision.
- **Ad creative & cadence intelligence** (Meta Ad Library, Google Ads Transparency, optional TikTok) — creatives, run dates, refresh cadence. Emits **spend-intensity proxies, never dollars**. Stays local; never federated.
- **Organic creator attribution** (YouTube Data API backbone, optional TikTok) + a rule-based mention classifier — partial recall, local only.
- **Reviews monitoring** across both stores.
- **A local REST API + MCP server** so each user's Claude/Cursor queries their own instance.
- **A federated contribution loop** (`contribute.py` / `refresh_dataset.py`) to a shared HF calibration-anchor dataset.

### 1.2 Why it exists
AppKittie/Sensor Tower/AppTweak charge mainly for two panel-modeled numbers (downloads/revenue, ad spend) that open source can't give away. Everything else is reproducible. This project reproduces that layer, attempts **honest, confidence-labeled** download/revenue estimates via a documented method, and refuses to fake the two it can't know. Crucially, the estimator's hardest part — calibrating absolute scale — is solved the same way the Fiverr tool grows its data: a **community dataset that gets better as more people self-host and contribute**. The honesty plus the flywheel is the open-source pitch.

### 1.3 Runtime model — self-hosted per user + federated dataset (not a central server)
Each user clones the repo, supplies their own keys, and runs the collectors locally (or on their own cheap VPS). Their captured data lives in a **local** database; their own Claude/Cursor connects to their **own local MCP server**. You ship code, not a service — no uptime obligation, no central bill, no central scraping-ToS exposure, no scaling problem. This is exactly the `fiverr-gig-optimizer` pattern.

The only shared component is an **opt-in** dataset on the Hugging Face Hub containing **public app-store calibration anchors** (segment + rank + observed download flow, derived from Android install-bucket deltas). `contribute.py` pushes a user's anchors via PR; `refresh_dataset.py` pulls everyone's back to refit local estimate calibration. Because app rankings and install counts are public facts, this dataset carries no personal data — and ads/creator data are excluded entirely (§3 P8).

Claude integration is the **MCP server** (§9F), which each user runs locally. Claude Code is the build tool and the query client, not a hosted runtime.

---

## 2. Goals and Non-Goals

### 2.1 Goals
- G1. Capture daily app rankings (iOS + Android), metadata, reviews, and Android install buckets into a **local** time-series store.
- G2. Produce **directional** download/revenue estimates with explicit confidence ranges and a documented method.
- G3. Derive observed download-flow anchors from install-bucket deltas, and **calibrate the estimator from pooled local + community anchors**.
- G4. Track ad creatives/cadence (Meta/Google/optional TikTok) and surface spend-intensity proxies — locally.
- G5. Discover organic creator content (YouTube-first) with a rule-based mention classifier — locally.
- G6. Expose everything via a **local** REST API + MCP server.
- G7. Provide an opt-in federated contribution loop to a shared HF anchor dataset, sharing only public app-store facts.

### 2.2 Non-Goals (explicit)
- N1. **No central server / no SaaS / no shared uptime.** Each user self-hosts; the project ships code, not a hosted service.
- N2. **No fabricated precision.** No estimate above MEDIUM confidence (no panel data).
- N3. **No dollar ad-spend figures.** Intensity proxies only, always with the disclaimer.
- N4. **No free-app revenue invention.** Requires user-supplied ARPU or returns "not estimable."
- N5. **No federating of ads/creator/personal data.** Only public app-store anchors are shared.
- N6. **No ToS-violating scraping in the default config.** Compliant sources default; scrapers are opt-in, operator-responsibility.
- N7. No ML training in the core estimator (transparent regression only). No auth/billing/multi-tenant.

---

## 3. Design Principles (the honesty spine)

- **P1 — Every number carries confidence + method + provenance.** Envelope: `{value, low, high, confidence, method, sources, flags}`.
- **P2 — Estimates are ranges, capped at MEDIUM.** Confidence never exceeds MEDIUM (no panel). HIGH is reserved for directly observed facts (a captured rank, a real install bucket, a real review count).
- **P3 — Proxies, not dollars, for ads.** The ad module computes intensity proxies and a mandatory `disclaimer`; it must never output USD spend.
- **P4 — Sanity bounds enforced.** A cumulative download estimate must respect the Google install bucket where one exists; violations are flagged, not silently emitted.
- **P5 — Compliant by default.** Apple RSS, iTunes lookup, official Meta Ad Library API, Google Ads Transparency public endpoint, YouTube Data API are defaults. Scrapers (Play HTML, TikTok, Instagram) are opt-in, rate-limited, operator-responsibility.
- **P6 — Single-language core.** Python everywhere; Node `facundoolano/google-play-scraper` documented as the maintained alternative behind an optional bridge.
- **P7 — Determinism.** Same captured data + same config + same community-anchor snapshot ⇒ bit-for-bit reproducible estimates. All constants in `config.json` (§12).
- **P8 — Local-first, federate only public anchors.** All data lives locally by default. The only data that ever leaves a user's machine is public app-store calibration anchors (segment + rank + observed flow + bucket/metadata), opt-in, via `contribute.py`. **Ad snapshots and creator data are never uploaded.** A guard (`assert_public_only`) aborts any contribution carrying ad/creator/identity fields.

---

## 4. Target Users
- **U1 — Indie dev / founder** sizing a niche on a budget; runs the free default config locally.
- **U2 — Growth/ASO marketer** tracking competitors' ranks, ad creatives, and creator activity over time.
- **U3 — Analyst** wanting directional estimates with explicit confidence, not a black box.
- **U4 — Contributor** who self-hosts and shares anchors, improving everyone's calibration.

---

## 5. User Stories
- US1. As U1, I add a competitor app and get its rank history, a download/revenue range (with confidence), and its ad creatives — all on my own machine.
- US2. As U2, I see a competitor's creatives, longevity, and refresh cadence — without any fake spend number.
- US3. As U3, every estimate tells me its confidence, method, and the data behind it.
- US4. As U4, I contribute my anonymized install-bucket anchors and pull the community's back, and my estimates get sharper as the dataset grows.
- US5. As any user, I query all of this from my own Claude via my local MCP server.
- US6. As U1, when the system can't estimate something (free-app revenue, dollar ad spend), it says so plainly.

## 5a. Success Metrics / KPIs (soft targets)
- K1 — **Provenance coverage: 100%.** Every emitted estimate carries `confidence`, `method`, `sources`.
- K2 — **Zero dollar ad-spend figures.** Grep of the ad module + API finds no USD spend output. (Hard gate.)
- K3 — **Bucket accuracy ≥ 80%.** Android cumulative download estimates land in the correct install bucket ≥80% on a held-out sample.
- K4 — **External sanity ≤ 3×.** Monthly download estimates within ~2–3× of AppTweak free-tier figures on a spot-check.
- K5 — **Mention precision ≥ 0.8.** The mention classifier ≥0.8 precision on a hand-labeled sample before creator results are exposed.
- K6 — **Calibration coverage (federation).** Share of tracked (platform, category, country) segments with ≥5 pooled anchors (local + community) grows over time; segments below threshold emit only LOW-confidence estimates.

---

## 6. Functional Requirements (by module)

### 6.1 Collectors
- FR1. **Rankings:** daily-capture Apple RSS top-free/paid/grossing per configured country/category; capture Google Play chart positions. One row per (app, country, list, category, date).
- FR2. **Metadata:** name, developer, category, price, free/paid, rating count (iTunes lookup for iOS; Play for Android).
- FR3. **Install buckets (Android):** capture `min_installs` + `real_installs` daily — the anchor source.
- FR4. **Reviews:** recent reviews per app per store (id, rating, date), deduped.
- FR5. **Ads (local only):** creatives + `first_seen`/`last_seen`/`still_active` from Meta Ad Library (official API default), Google Ads Transparency, optional TikTok. Snapshot continuously.
- FR6. **Creators (local only):** discover videos mentioning a tracked app via YouTube Data API (default) and optional TikTok; store with a mention confidence.
- FR7. Every collector throttles, handles rate-limit/quota errors gracefully, records `captured_on`.

### 6.2 Estimation engine
- FR8. Derive observed download-flow anchors from install-bucket deltas (§9B).
- FR9. Calibrate `scale_b` per (platform, category, country) from **pooled local + community** anchors.
- FR10. Compute download estimates via Garg–Telang (§9B): `{point, low, high, confidence, method, anchors_used, flags}`.
- FR11. Enforce install-bucket sanity bounds (P4); flag violations.
- FR12. Revenue only for paid apps (downloads × price × (1 − store cut)); `not_estimable` for free apps unless ARPU supplied.
- FR13. Never return confidence above MEDIUM (P2).

### 6.3 Ad intelligence (local)
- FR14. Compute intensity proxies: active-ad count, total creatives, median longevity, platform mix, refresh rate, intensity tier.
- FR15. Mandatory `disclaimer`; never USD spend (P3). Never federated (P8).

### 6.4 Creator attribution (local)
- FR16. Run the rule-based mention classifier (§9D); store `mention_confidence`.
- FR17. Surface posts above a configurable threshold; expose recall/precision caveats. Never federated.

### 6.5 Federation (opt-in)
- FR18. `contribute.py` collects locally-derived flow anchors + public rank/bucket/metadata, **whitelists to the anchor schema**, dedups, and opens a PR to the HF dataset. Supports `--dry-run`.
- FR19. `assert_public_only` aborts if any ad/creator/identity field is present.
- FR20. `refresh_dataset.py` pulls community anchors, validates (schema/range), refuses corrupt files above a ratio, no-ops below `min_new`, merges clean new rows, and **refits calibration**. Supports `--dry-run`.
- FR21. Contribution is OFF by default; requires both dropping `--dry-run` **and** an `HF_TOKEN`. No background upload.

### 6.6 API + MCP (local)
- FR22. Local REST API (FastAPI) exposing apps, ranks, estimates, ad intensity, creators, reviews.
- FR23. Local MCP server exposing the same as tools (§9F).

---

## 7. System Architecture (per user; identical on every install)

```
   YOUR MACHINE (or your VPS)                          SHARED (opt-in)
 ┌─────────────────────────────────────────┐        ┌────────────────────────┐
 │  scheduler (APScheduler/cron, daily)      │        │  Hugging Face dataset   │
 │            │                              │        │  app-rank-anchors       │
 │            ▼                              │        │  (public anchors only,  │
 │  collectors (Apple RSS, Play+buckets,     │        │   CC-BY-4.0)            │
 │  iTunes, reviews, ads*, creators*)        │        └───────┬─────────┬──────┘
 │            │                              │                │         │
 │            ▼                              │     refresh_dataset.py    │ contribute.py
 │  local DB (SQLite default / Postgres)     │◄───── pull anchors ───────┘   (PR, opt-in,
 │   rank_history, install_buckets,          │                               token-gated,
 │   flow_anchors, ads*, creators*, reviews  │──────── push anchors ─────────► guarded:
 │            │                              │                               public only)
 │            ▼                              │
 │  estimator (Garg–Telang; scale_b refit    │   * ads & creators are LOCAL ONLY —
 │  from local + community anchors)          │     never uploaded (design principle P8)
 │  + ad intensity proxies + mention scorer  │
 │            │                              │
 │     ┌──────┴───────┐                      │
 │     ▼              ▼                      │
 │  REST API      MCP server  ───────────────┼──►  YOUR Claude / Cursor
 │  (FastAPI)     (FastMCP)                   │
 └─────────────────────────────────────────┘
```

There is no shared API/MCP endpoint. If any user's machine is down, only *their* instance is affected — everyone else is unaffected.

---

## 8. Data Schema (SQLite default; Postgres-compatible)

```sql
CREATE TABLE apps (
  app_id TEXT PRIMARY KEY, platform TEXT NOT NULL, name TEXT, developer TEXT,
  category TEXT, country TEXT, price_usd REAL, is_free INTEGER,
  first_seen DATE, last_updated DATE
);

CREATE TABLE rank_history (
  app_id TEXT, country TEXT, list_type TEXT, category TEXT,
  rank INTEGER, captured_on DATE,
  PRIMARY KEY (app_id, country, list_type, category, captured_on)
);

CREATE TABLE install_buckets (        -- ANDROID ONLY (anchor source)
  app_id TEXT, min_installs INTEGER, real_installs INTEGER, captured_on DATE,
  PRIMARY KEY (app_id, captured_on)
);

-- NEW in v1.1: observed download-flow anchors (from install-bucket deltas).
-- 'source' distinguishes your own observations from pulled community ones.
CREATE TABLE flow_anchors (
  platform TEXT, category TEXT, country TEXT, list_type TEXT,
  rank INTEGER, observed_downloads INTEGER, window_days INTEGER,
  captured_on DATE, source TEXT,      -- 'local' | 'community'
  PRIMARY KEY (platform, category, country, list_type, rank, captured_on, source)
);

CREATE TABLE calibration (            -- fitted scale per segment
  platform TEXT, list_type TEXT, category TEXT, country TEXT,
  shape_a REAL NOT NULL, scale_b REAL, n_anchors INTEGER NOT NULL, updated_on DATE,
  PRIMARY KEY (platform, list_type, category, country)
);

CREATE TABLE estimates (
  app_id TEXT, country TEXT, captured_on DATE,
  downloads_point REAL, downloads_low REAL, downloads_high REAL,
  revenue_point REAL, confidence TEXT NOT NULL, method TEXT NOT NULL, flags TEXT,
  PRIMARY KEY (app_id, country, captured_on)
);

CREATE TABLE ad_snapshots (           -- LOCAL ONLY; never federated
  app_id TEXT, platform TEXT, creative_id TEXT, ad_snapshot_url TEXT,
  first_seen DATE, last_seen DATE, still_active INTEGER,
  PRIMARY KEY (app_id, platform, creative_id)
);

CREATE TABLE creator_mentions (       -- LOCAL ONLY; never federated
  app_id TEXT, source TEXT, video_id TEXT, channel TEXT, url TEXT,
  mention_confidence REAL, captured_on DATE,
  PRIMARY KEY (app_id, source, video_id)
);

CREATE TABLE reviews (
  app_id TEXT, source TEXT, review_id TEXT, rating INTEGER, captured_on DATE,
  PRIMARY KEY (app_id, source, review_id)
);
```

**Shared HF dataset row schema (the only thing that leaves a machine):**
```
platform, category, country, list_type, rank, observed_downloads,
window_days, min_installs, real_installs, price_usd, is_free,
rating_count, captured_on
```
Note: `app_id` is intentionally **omitted** — anchors need only (segment, rank, flow), not app identity. No personal, ad, or creator field ever appears.

---

## 9. Module Specifications with Reference Code

> Reference implementations — correct in approach, compact. Complete error handling, typing, and tests during the build.

### 9A. Collectors
*(Unchanged from v1.0 — Apple RSS rankings, Google Play metadata + install buckets via the Python `google-play-scraper`, iTunes lookup, reviews. See the snippets below.)*

```python
import requests, datetime as dt
RSS = "https://rss.applemarketingtools.com/api/v2/{country}/apps/{feed}/{limit}/apps.json"

def fetch_apple_chart(country="us", feed="top-free", limit=100):
    url = RSS.format(country=country, feed=feed, limit=limit)
    r = requests.get(url, timeout=15); r.raise_for_status()
    results = r.json()["feed"]["results"]; today = dt.date.today().isoformat()
    return [{"app_id": a["id"], "platform": "ios", "name": a["name"],
             "developer": a.get("artistName"), "rank": i + 1,
             "list_type": feed, "country": country, "captured_on": today}
            for i, a in enumerate(results)]
```

```python
from google_play_scraper import app as gp_app   # exposes min/realInstalls
def fetch_play_app(package_id, country="us", lang="en"):
    d = gp_app(package_id, lang=lang, country=country)
    return {"app_id": package_id, "platform": "android", "name": d.get("title"),
            "developer": d.get("developer"), "category": d.get("genre"),
            "price_usd": (d.get("price") or 0.0), "is_free": 1 if d.get("free") else 0,
            "min_installs": d.get("minInstalls"), "real_installs": d.get("realInstalls"),
            "captured_on": dt.date.today().isoformat()}
# Throttle; google-play-scraper throws on rate-limiting.
```

### 9B. Estimator + anchor derivation (the core; updated for federation)

**Derive an observed download-flow anchor from two install-bucket captures:**
```python
import math

def derive_flow_anchor(bucket_rows, rank_rows):
    """From >=2 install-bucket captures of one Android app, derive a real
    observed download flow over the window at the app's (median) rank.
    bucket_rows: [{real_installs, captured_on(date)}...] sorted by date.
    rank_rows:   [{rank, captured_on(date)}...] over the same window.
    Returns {platform:'android', rank, observed_downloads, window_days} or None."""
    if len(bucket_rows) < 2: return None
    b0, b1 = bucket_rows[0], bucket_rows[-1]
    if not (b0["real_installs"] and b1["real_installs"]): return None
    delta = b1["real_installs"] - b0["real_installs"]
    window_days = (b1["captured_on"] - b0["captured_on"]).days
    ranks = sorted(r["rank"] for r in rank_rows if r.get("rank"))
    if delta <= 0 or window_days <= 0 or not ranks: return None  # not an anchor
    return {"platform": "android", "rank": ranks[len(ranks)//2],
            "observed_downloads": delta, "window_days": window_days}
```

**Calibrate scale from pooled anchors (local + community), normalized to monthly:**
```python
SHAPE_A = {("ios","top-paid"):0.944, ("ios","top-free"):0.90, ("ios","top-grossing"):0.92,
           ("android","top-paid"):0.985, ("android","top-free"):0.95,
           ("android","top-grossing"):0.96}
DEFAULT_A = 0.95

def relative_index(rank, a): return rank ** (-a)

def calibrate_scale(anchors, a):
    """anchors: list of {rank, observed_downloads, window_days} (local + community).
    Normalizes each to a monthly figure, fits scale_b as the geometric mean
    (robust in log space). Returns (scale_b, n) or (None, 0)."""
    logs = []
    for an in anchors:
        rank, obs, win = an["rank"], an["observed_downloads"], an["window_days"]
        if rank > 0 and obs > 0 and win > 0:
            monthly = obs * 30.0 / win
            logs.append(math.log(monthly / relative_index(rank, a)))
    return (math.exp(sum(logs)/len(logs)), len(logs)) if logs else (None, 0)
```

**Estimate downloads (range; capped at MEDIUM) + revenue + sanity bound:**
```python
from dataclasses import dataclass, field
STORE_CUT = {"standard": 0.30, "small_business": 0.15}

@dataclass
class DownloadEstimate:
    point: float|None; low: float|None; high: float|None
    confidence: str; method: str; anchors_used: int; flags: list = field(default_factory=list)

def estimate_downloads(rank, platform, list_type, scale_b, n_anchors):
    a = SHAPE_A.get((platform, list_type), DEFAULT_A)
    if scale_b is None or n_anchors == 0:
        return DownloadEstimate(None,None,None,"NONE","uncalibrated",0,["no_anchor"])
    point = scale_b * relative_index(rank, a)
    factor, conf = (1.8, "MEDIUM") if n_anchors >= 5 else (3.0, "LOW")  # never HIGH (P2)
    return DownloadEstimate(round(point), round(point/factor), round(point*factor),
                            conf, "garg_telang_powerlaw", n_anchors, [])

def enforce_install_bucket(est, real_installs, app_age_days):
    if est.point is None or not real_installs: return est
    if est.point * max(app_age_days/30.0, 1) > real_installs * 1.25:
        est.flags.append("exceeds_install_bucket"); est.confidence = "LOW"
    return est

def estimate_revenue(downloads_point, price_usd, is_free, cut="small_business", user_arpu=None):
    if is_free:
        return (None, ["free_app_revenue_not_estimable"]) if user_arpu is None \
               else (round(downloads_point*user_arpu), ["arpu_user_supplied"])
    if not price_usd or price_usd <= 0: return None, ["no_price"]
    return round(downloads_point*price_usd*(1-STORE_CUT[cut])), ["paid_app_excludes_iap"]
```

**Why federation closes the weak link:** solo, you have few anchors → LOW confidence and wide bands. As the community contributes install-bucket-derived anchors across segments, `calibrate_scale` has ≥5 anchors per (platform, category, country) → MEDIUM confidence and tighter bands. The dataset literally upgrades everyone's estimate quality (KPI K6), and it does so by pooling **observations**, never fabricated numbers.

### 9C. Ad Creative & Cadence Tracker (proxies, never dollars; local only)
```python
_DISCLAIMER = ("spend-intensity proxy, NOT USD spend; dollar ad spend is not "
              "derivable from public data and is never estimated here")

def ad_intensity_proxies(snapshots):
    if not snapshots: return {"active_ad_count": 0, "disclaimer": _DISCLAIMER}
    longevities = sorted((s["last_seen"]-s["first_seen"]).days + 1 for s in snapshots)
    span = max(longevities) or 1
    refresh = len(snapshots) / max(span/7.0, 1)
    active = sum(1 for s in snapshots if s["still_active"])
    return {"active_ad_count": active, "total_creatives_seen": len(snapshots),
            "median_ad_longevity_days": longevities[len(longevities)//2],
            "platform_mix": sorted({s["platform"] for s in snapshots}),
            "creative_refresh_per_week": round(refresh, 2),
            "intensity_tier": ("HIGH" if active>=20 or refresh>=5 else
                               "MEDIUM" if active>=5 or refresh>=1 else "LOW"),
            "disclaimer": _DISCLAIMER}
```
Meta Ad Library returns spend/impressions only for EU/UK + political ads; for commercial app ads capture creative + page name + `ad_snapshot_url` + platforms + `ad_delivery_start_time`, snapshot daily to build `first_seen`/`last_seen`. **This data is never federated (P8).**

### 9D. Creator Attribution (YouTube backbone + rule classifier; local only)
```python
import re
STORE_LINK = re.compile(r"(apps\.apple\.com|play\.google\.com/store/apps)")

def youtube_search(api_key, query, max_results=25):
    r = requests.get("https://www.googleapis.com/youtube/v3/search",
        params={"part":"snippet","q":query,"type":"video",
                "maxResults":max_results,"key":api_key}, timeout=15)
    r.raise_for_status(); return r.json().get("items", [])

def app_mention_score(text, app_name, package_id=None, brand_hashtags=()):
    t = (text or "").lower(); score = 0.0
    if app_name and app_name.lower() in t:           score += 0.5
    if package_id and package_id.lower() in t:       score += 0.3
    if any(h.lower() in t for h in brand_hashtags):  score += 0.2
    if STORE_LINK.search(t):                         score += 0.4  # strongest signal
    return min(round(score, 2), 1.0)
```
Recall is partial; TikTok/Instagram paths are opt-in, ToS-risky, fragile; TikTok's Research API is the only compliant TikTok route (non-commercial, 1,000 req/day). **Creator data is never federated (P8); creator handles are personal data.**

### 9E. REST API (FastAPI; local)
```python
from fastapi import FastAPI
app = FastAPI(title="AppScope")

@app.get("/apps/{app_id}/estimate")
def get_estimate(app_id: str, country: str = "us"): ...   # envelope: value/low/high/confidence/method/sources/flags
@app.get("/apps/{app_id}/ads")
def get_ads(app_id: str): ...                              # intensity proxies; no USD
@app.get("/apps/{app_id}/creators")
def get_creators(app_id: str, min_confidence: float = 0.6): ...
@app.get("/apps/{app_id}/ranks")
def get_ranks(app_id: str, country: str = "us", days: int = 30): ...
@app.get("/apps/{app_id}/reviews")
def get_reviews(app_id: str, days: int = 30): ...
```

### 9F. MCP Server (each user runs locally)
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("appscope")

@mcp.tool()
def app_estimate(app_id: str, country: str = "us") -> dict:
    """Download/revenue estimate with confidence + method + provenance (ranges; never >MEDIUM)."""
    ...
@mcp.tool()
def ad_intensity(app_id: str) -> dict:
    """Ad creative/cadence intensity proxies. Never USD spend."""
    ...
@mcp.tool()
def creator_mentions(app_id: str, min_confidence: float = 0.6) -> dict: ...
@mcp.tool()
def rank_history(app_id: str, country: str = "us", days: int = 30) -> dict: ...

if __name__ == "__main__": mcp.run()
```

### 9G. `contribute.py` — federated upload (opt-in, guarded)
```python
ANCHOR_KEEP = {"platform","category","country","list_type","rank",
               "observed_downloads","window_days","min_installs","real_installs",
               "price_usd","is_free","rating_count","captured_on"}
BANNED = {"app_id","channel","creator","handle","advertiser","ad_snapshot_url",
          "creative_id","review_id","video_id","url","name","developer"}

def strip_to_anchor_schema(row): return {k: row[k] for k in ANCHOR_KEEP if k in row}

def assert_public_only(records):
    """Hard guard (P8): abort if any ad/creator/identity field is present."""
    for rec in records:
        bad = BANNED & set(rec)
        if bad: raise ValueError(f"refusing to upload non-public fields: {sorted(bad)}")

def build_contribution(db):
    rows = db.fetch_shareable_anchors()       # local flow_anchors + bucket/metadata facts
    records = [strip_to_anchor_schema(r) for r in rows]
    assert_public_only(records)               # must pass before any upload
    return dedup(records)

# CLI: contribute.py --dry-run            -> print cleaned records, upload nothing
#      contribute.py --contributor NAME   -> open HF PR (requires HF_TOKEN)
# OFF by default: needs BOTH no --dry-run AND HF_TOKEN set. No background upload.
```

### 9H. `refresh_dataset.py` — federated download (validated, gated)
```python
def refresh(db, dataset_repo, min_new=50, max_corrupt_ratio=0.25, dry_run=False):
    """Pull community anchors, validate, merge clean NEW rows into flow_anchors
    (source='community'), then refit calibration. Refuses corrupt files; no-ops
    if too few new rows. Deterministic afterwards."""
    incoming = fetch_hf_dataset(dataset_repo)
    clean = [r for r in incoming if validate_anchor(r)]
    corrupt = len(incoming) - len(clean)
    if incoming and corrupt/len(incoming) > max_corrupt_ratio:
        return {"status":"refused","reason":"too_many_corrupt"}
    new = db.dedup_against_local(clean)
    if len(new) < min_new: return {"status":"noop","new_rows":len(new)}
    if not dry_run:
        db.insert_flow_anchors(new, source="community")
        db.recalibrate_all_segments()         # refit scale_b per segment
    return {"status": "preview" if dry_run else "merged", "new_rows": len(new)}

def validate_anchor(r):
    return (r.get("platform") in {"ios","android"} and isinstance(r.get("rank"), int)
            and r.get("rank",0) > 0 and (r.get("observed_downloads") or 0) > 0
            and (r.get("window_days") or 0) > 0 and not (BANNED & set(r)))
```

---

## 10. Repo Structure

```
open-app-intel/
├── appscope/
│   ├── config.py
│   ├── db.py                     # schema (§8) incl. flow_anchors
│   ├── collectors/{apple_rss,play,itunes,reviews,ads_meta,ads_google,ads_tiktok,creators_youtube}.py
│   ├── estimate/{downloads,revenue,calibrate}.py      # §9B (calibrate pools local+community)
│   ├── ads/intensity.py          # §9C (no dollars; local)
│   ├── creators/classify.py      # §9D (local)
│   ├── federation/
│   │   ├── contribute.py         # §9G (opt-in, guarded)
│   │   └── refresh_dataset.py    # §9H (validated, gated)
│   ├── api.py                    # §9E (local)
│   ├── mcp_server.py             # §9F (local)
│   └── scheduler.py
├── tests/{test_downloads,test_revenue,test_intensity,test_classify,test_anchor_guard}.py
├── data/anchors.sample.json      # small bundled anchor seed (public facts)
├── config.json / config.sample.json
├── requirements.txt
├── docker-compose.yml            # optional: app + postgres
├── DATA_POLICY.md
├── CONTRIBUTORS.md
├── LICENSE                       # MIT (code)
├── LICENSE-DATA                  # CC-BY-4.0 (anchors + docs)
├── .gitignore                    # *.db, .env, __pycache__
└── README.md
```

---

## 11. Dependencies
- **Python 3.10+.** Core: `requests`, `fastapi`, `uvicorn`, `apscheduler`, `pydantic`. Stdlib: `math`, `statistics`, `sqlite3`, `json`, `datetime`, `re`, `dataclasses`.
- **Data:** `google-play-scraper` (JoMingyu) for Play metadata/install buckets.
- **Federation:** `huggingface_hub>=0.23` (PRs + dataset pull).
- **MCP:** `mcp` (FastMCP).
- **Optional:** `psycopg2-binary` (Postgres); a Google Ads Transparency scraper or SerpApi; an unofficial TikTok scraper for the opt-in module.
- **Keys (operator-supplied, none shipped):** Meta Ad Library token, YouTube Data API key, Hugging Face token (contributors only). TikTok Research API only if eligible.
- `requirements.txt`: `requests>=2.31`, `fastapi>=0.110`, `uvicorn>=0.29`, `apscheduler>=3.10`, `pydantic>=2`, `google-play-scraper>=1.2`, `huggingface_hub>=0.23`, `mcp>=1.2`.

---

## 12. Configuration (`config.json`)
```json
{
  "storage": { "backend": "sqlite", "path": "appscope.db" },
  "tracking": { "countries": ["us","gb"], "categories": ["all"],
                "apps": ["com.example.app","284882215"] },
  "estimator": { "min_anchors_for_medium": 5, "band_factor_low": 3.0,
                 "band_factor_medium": 1.8, "store_cut": "small_business",
                 "bucket_tolerance": 1.25 },
  "ads": { "sources": ["meta","google"], "tiktok_enabled": false },
  "creators": { "sources": ["youtube"], "tiktok_enabled": false,
                "min_confidence": 0.6, "brand_hashtags_by_app": {} },
  "federation": {
    "dataset_repo": "https://huggingface.co/datasets/Ahad690/app-rank-anchors",
    "auto_contribute": false,
    "min_new_on_refresh": 50,
    "max_corrupt_ratio": 0.25
  },
  "schedule": { "daily_hour_utc": 6 },
  "keys": { "meta_ad_library_token_env": "META_AD_TOKEN",
            "youtube_api_key_env": "YOUTUBE_API_KEY",
            "hf_token_env": "HF_TOKEN" }
}
```
All estimator constants live here (P7). `auto_contribute` still requires `HF_TOKEN` and still prints what it shares. Keys are read from the named env vars, never stored.

---

## 13. Build Order

**Stage 0 — Scaffold.** Repo tree (§10); `db.py` (§8 incl. `flow_anchors`); `config.py`; `LICENSE` + `LICENSE-DATA`; `.gitignore`; `requirements.txt`; empty `CONTRIBUTORS.md`.

**Stage 1 — Compliant data spine.** `collectors/{apple_rss,itunes,play,reviews}.py`; `scheduler.py`. Rows land in `rank_history`, `apps`, `install_buckets`, `reviews`.

**Stage 2 — Estimator + anchors.** `estimate/downloads.py`, `estimate/calibrate.py` (anchor derivation + pooled calibration + bucket sanity), `estimate/revenue.py`. Seed `flow_anchors` from local install-bucket deltas + `data/anchors.sample.json`. Tests `test_downloads.py`, `test_revenue.py`.

**Stage 3 — Ad + creator (local).** `collectors/ads_*.py`, `ads/intensity.py`, `collectors/creators_youtube.py`, `creators/classify.py`. Tests `test_intensity.py`, `test_classify.py`.

**Stage 4 — Federation (NEW).** `federation/contribute.py` (§9G, with `assert_public_only`), `federation/refresh_dataset.py` (§9H), `DATA_POLICY.md`. Test `test_anchor_guard.py` (asserts ad/creator/identity fields are rejected). Create the HF dataset `Ahad690/app-rank-anchors` with a dataset card.

**Stage 5 — API + MCP (local).** `api.py` (§9E), `mcp_server.py` (§9F).

**Stage 6 — Packaging + docs.** `README.md`, optional `docker-compose.yml`.

---

## 14. Acceptance Criteria (per stage)

- **Stage 0.** `db.bootstrap()` creates all §8 tables incl. `flow_anchors`; both license files exist.
- **Stage 1.** A scheduled run inserts ≥1 `rank_history` row (Apple RSS) and a valid `install_buckets` row for a known Android app; rate-limit errors are caught, not fatal. You can reproduce a known app's current install bucket and rank trajectory.
- **Stage 2.** `derive_flow_anchor` returns a valid anchor from two increasing bucket captures and `None` when growth ≤ 0. `estimate_downloads(rank=10, platform='android', list_type='top-free', scale_b=B, n_anchors=6)` → `confidence='MEDIUM'`; `n_anchors=0` → `confidence='NONE', flags=['no_anchor']`. `estimate_revenue(..., is_free=True, user_arpu=None)` → `(None, ['free_app_revenue_not_estimable'])`. On a held-out Android sample: install-bucket accuracy ≥80% (K3), within ~2–3× of AppTweak (K4). No estimate returns `confidence='HIGH'`.
- **Stage 3.** `ad_intensity_proxies` output **always** has `disclaimer`, **never** a USD field (K2 hard gate). Mention classifier ≥0.8 precision on the labeled sample (K5).
- **Stage 4 (federation).** `contribute.py --dry-run` prints cleaned anchor records and uploads nothing; **`test_anchor_guard.py` proves `assert_public_only` raises** when an `app_id`/`channel`/`ad_snapshot_url`/etc. is injected. `refresh_dataset.py --dry-run` previews; a corrupt-heavy file is refused; a sub-`min_new` pull no-ops; a clean pull merges and refits calibration. Grep confirms uploads contain only the §8 shared-anchor fields (no ads/creator/identity).
- **Stage 5.** API returns the P1 envelope for estimates; the local MCP server exposes the four tools and a Claude query returns a confidence-labeled estimate.
- **Stage 6.** README documents the self-host model, the federation loop, the honesty rules, and the three known gaps; `DATA_POLICY.md` states what is/64isn't shared.

**Global gate.** Grep codebase + API + any upload payload: (a) no estimate without `confidence`+`method`; (b) no USD ad spend; (c) no `confidence='HIGH'` for a modeled estimate; (d) no ad/creator/identity field in any contribution.

---

## 15. Legal / Compliance / ToS (README + DATA_POLICY.md)
- **Self-host, compliant by default.** Each user runs locally; defaults are Apple RSS, iTunes lookup, official Meta Ad Library API, Google Ads Transparency, YouTube Data API, used within terms.
- **Federated data is public app-store facts only.** The shared dataset contains segment + rank + observed-flow + bucket/metadata rows — no personal data, no app identity, no ads, no creators. Released CC-BY-4.0.
- **Ads & creator data never leave the user's machine.** Enforced by `assert_public_only`.
- **Opt-in scrapers are operator responsibility** (Play HTML, TikTok, Instagram), under each platform's ToS; the legal landscape (e.g. *Meta v. Bright Data*) is unsettled.
- **Estimates are modeled, not measured** — labeled as such; the project warrants nothing about accuracy.

---

## 16. Out of Scope / Future (v2+)
- Dollar ad-spend estimation and panel-grade install precision (require an opt-in panel — excluded).
- Federating richer data types (e.g. anonymized aggregate ad-cadence stats) — only if a clean, non-personal aggregation is designed.
- Commercial-scale creator attribution (paid APIs collapse this from "build" to "integrate").
- A web dashboard UI; auth/multi-tenant/billing; a learned ML estimator; Apple install ranges (would tighten iOS bands if Apple ever exposed them).

---

## 17. Appendix — Academic Basis & Key Facts
- **Download method:** Garg, R. & Telang, R. (2013), "Inferring App Demand from Publicly Available Data," *MIS Quarterly* 37(4). Power law `d(rank)=b·rank^(−a)`; `a` from public lists, scale anchored from observed data. Validated against a real developer's numbers with no statistically significant mean difference. Shape priors: iPhone paid a≈0.944, iPad paid a≈0.903, Android paid a≈0.985. (First author: **Rajiv** Garg.)
- **The anchor mechanism (federation):** Google Play exposes `realInstalls` (cumulative). The **delta** between two captures over a window, paired with the app's rank in that window, is a *real observed download flow at a known rank* — a clean calibration anchor. Pooling these across self-hosting contributors (per platform/category/country) is what lets `scale_b` reach ≥5 anchors/segment and graduate estimates from LOW to MEDIUM (KPI K6). Apple exposes no install data, so iOS relies on shared anchors + wider bands.
- **Ad spend is fundamentally private:** spend = impressions × CPM ÷ 1000; impressions live only in opt-in panels. Public ad libraries expose creatives + run dates, banded spend only for EU/political ads. Hence proxies, not dollars — and ads never federate (handles/advertisers are identifying).
- **Creator attribution is greenfield:** YouTube Data API is the one fully-compliant organic-discovery route; TikTok's Research API is the closest compliant TikTok option (non-commercial, 1,000 req/day). The mention classifier is the "missing middle layer" you build. Creator data stays local.
- **Three-gap honesty summary:** downloads/revenue = *partially solvable, and improves with the shared dataset*; ad spend = *hard gap, proxies only*; creator attribution = *hardest, partial recall, local-first*.
- **Estimate envelope (enforced everywhere):** `{value, low, high, confidence∈{LOW,MEDIUM}, method, sources, flags}`.
