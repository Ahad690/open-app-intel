---
name: appscope
description: >
  Honest app market intelligence from locally-captured store data. Collects
  rankings, metadata, install buckets, and reviews for iOS/Android apps into a
  local database; produces download/revenue ESTIMATES as confidence-banded
  ranges (never fabricated, never above MEDIUM); renders an app-intel report.
  Use when the user asks how many downloads an app gets, app revenue estimates,
  app rankings, competitor app research, ASO/app market intelligence, or wants
  to track an app over time.
allowed-tools: Bash(python3 *) Read Write
argument-hint: "[app name, store URL, or app id]"
metadata: { version: "1.1" }
license: MIT
---

# AppScope — honest app market intelligence

Self-hosted app intel from data captured on the user's own machine. **Every
number is produced by a documented model on real, locally-captured data, with a
confidence label, method tag, and flags.** The system refuses to fabricate the
figures vendors model from private panels.

## When to use
The user asks: how many downloads does app X get; estimate an app's revenue;
what rank is an app; track a competitor app; app-store market research / ASO
intelligence.

## Hard rules (NON-NEGOTIABLE)
1. **Never invent an app-market number.** Downloads, revenue, ranks, installs,
   review counts come ONLY from `python3 -m appscope.cli ...` output. Surface
   the JSON envelopes verbatim.
2. **Estimates are ranges, capped at MEDIUM confidence.** Observed facts
   (ranks, install buckets, review counts) are HIGH. Never present an estimate
   as a fact.
3. **Refuse what can't be known:** dollar ad spend (intensity proxies only)
   and panel-grade installs are never modeled. Say so if asked.
4. **Uncalibrated segment → "no data",** plus how to fix it (collect Android
   anchor apps in that category, or `refresh_dataset` to pull community
   anchors). Never fill the gap with a guess.
5. **Local-first.** The DB, ads, and creator data stay on the machine. Only
   public calibration anchors are ever shared, opt-in (see Federation).

Run every command from the plugin root:
`cd ${CLAUDE_PLUGIN_ROOT} && python3 -m appscope.cli <cmd> ...`
(First run: copy `config.sample.json` to `config.json` if missing.)

## Workflow

### Step 1 — Intake (ONE message)
Ask for: the app (name + a store URL, or the id directly), platform if
ambiguous, and country (default `us`). Resolve the id yourself from a store
URL — iOS ids are the digits after `/id` (e.g. `.../id284882215` → `284882215`);
Android ids are the `?id=` package (e.g. `?id=com.spotify.music`). If only a
name is given, ask for the store link — do NOT guess ids.

### Step 2 — Collect (writes are append-only; nothing is overwritten)
`python3 -m appscope.cli collect --app <id>` — metadata, install buckets
(Android), reviews. Add `--charts` to also capture the Apple top charts (needed
for rank-based estimates). Report what was collected.

### Step 3 — Answer from the local DB
- Observed facts: `python3 -m appscope.cli summary --app <id> --country <cc>`.
- Estimates: `python3 -m appscope.cli estimate --app <id> --country <cc>`.
  Present value + band + confidence + method + flags exactly as returned. If
  `confidence` is `NONE`/`uncalibrated`, say there is no estimate and explain
  the anchor path (rule 4).

### Step 4 — Deliverable
`python3 -m appscope.cli report --app <id> --out app-intel-report.html` —
renders the intel with provenance per row and the contribution banner. Tell
the user where it was written.

### Step 5 — Ongoing tracking (optional)
To track apps daily, add them to `config.json` → `tracking.apps` and suggest
`python -m appscope.scheduler` (daemon) or a cron of `--once`. Suggest
`python3 -m appscope.cli backup` before schema-affecting upgrades — backups
are timestamped and never pruned.

## Error handling
- App not collected yet → run collect first (Step 2), then answer.
- `no_anchor` / `uncalibrated` → no estimate; offer the calibration paths.
- A collector failure is logged, never fatal — report what succeeded and what
  didn't; never substitute a guess for the failed source.

## Federation (opt-in, OFF by default)
`python -m appscope.federation.contribute --dry-run` previews the ONLY data
that may leave: public rank→install calibration anchors (no ads, creators, or
identity). Real upload needs the flag dropped AND an HF token.
`python -m appscope.federation.refresh_dataset --dry-run` previews pulling
community anchors (validated, corrupt-refusing, additive-only merge).

## Example
"How many downloads does Spotify get on Android?" → intake (id
`com.spotify.music`, country us) → collect → estimate returns
`value 950000, low 530000, high 1710000, confidence LOW, method
garg_telang_calibrated, flags []` → present: "**≈530k–1.7M monthly downloads**
(point 950k) — LOW confidence, rank-curve calibrated from N anchors; this is a
model estimate, not a measured count" → render the report and link it.
