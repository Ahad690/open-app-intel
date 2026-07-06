# AGENTS.md — running AppScope from any agentic CLI

AppScope is a **Claude Code skill + local MCP server**, but CLI-agnostic: the
intelligence lives in `skills/appscope/SKILL.md` plus deterministic Python (`appscope.*`
modules), so any agentic coding CLI (Claude Code, Codex, OpenCode, Cursor, Gemini CLI,
Copilot CLI, Qwen, Kimi, Grok) can drive it. This file is the entry point those tools read.

## The rules you may never break

- **P1 — Every number carries confidence + method + provenance.** Envelope:
  `{value, low, high, confidence, method, sources, flags}`.
- **P2 — Estimates are ranges, capped at MEDIUM.** HIGH is reserved for directly
  observed facts (a captured rank, a real install bucket, a real review count). A
  modeled estimate is **never** HIGH.
- **P3 — Proxies, not dollars, for ads.** The ad module emits intensity proxies and a
  disclaimer; it **never** outputs USD spend.
- **N4 — Free-app revenue is never invented.** Returns *not estimable* without an ARPU.
- **P8 — Local-first; federate only public anchors.** Ads and creator data never leave
  the machine; `assert_public_only` aborts any contribution carrying ad/creator/identity.

If a segment is uncalibrated, the estimator returns NONE / *uncalibrated* — say so.
It is correct for the tool to refuse rather than guess.

## How to run it

1. Read `skills/appscope/SKILL.md` — the full operating procedure.
2. Drive the JSON CLI:

```bash
python -m appscope.cli collect  --app <id> [--charts]   # append-only observations
python -m appscope.cli summary  --app <id>              # observed facts (HIGH)
python -m appscope.cli estimate --app <id>              # banded estimate (≤ MEDIUM)
python -m appscope.cli report   --app <id>              # the HTML deliverable
python -m appscope.cli backup                           # timestamped DB snapshot
```

3. Or point a local MCP client at `python -m appscope.mcp_server` (tools:
   `app_estimate`, `ad_intensity`, `creator_mentions`, `rank_history`).

## Contract enforcement

`pytest -q` (73 tests) covers the never-HIGH cap, free-app revenue, the no-USD ad gate,
the mention-precision gate, and the federation guard. A change that emits USD ad spend,
lets an estimate reach HIGH, or federates non-public fields is a bug — not a feature.
