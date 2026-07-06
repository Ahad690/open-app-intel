# Contributing to AppScope

Thanks for helping build app intelligence that's honest about what it can't know.
**First-timers welcome** — this repo is deliberately friendly to your first PR.

## Your first PR in 10 minutes

```bash
git clone https://github.com/Ahad690/open-app-intel && cd open-app-intel
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
pytest -q                                        # 73 tests — should be green
```

Pick a [`good first issue`](https://github.com/Ahad690/open-app-intel/labels/good%20first%20issue),
comment to claim it, open a PR.

## The rules (non-negotiable)

- Estimates are **ranges capped at MEDIUM**; HIGH is observed facts only.
- Ads emit **proxies, never USD**. Free-app revenue is never invented.
- Federation shares **public anchors only** (`assert_public_only`).

See `AGENTS.md` for the full contract. A PR that breaks any of these doesn't merge.

## What makes a good PR here

- **Small and scoped.** One issue, one PR, with a test. Keep `pytest -q` green.
- **Honest.** New public data collectors (with provenance), new deterministic model
  refinements (that stay ≤ MEDIUM), docs, and federation-guard tests are welcome.
  "Estimate dollar ad spend" or "make installs HIGH-confidence" is not.

## Good areas to contribute

- New **top-chart collectors** for additional countries/categories.
- New **review-source adapters** (observed counts only).
- **Calibration** improvements to the rank→download power law (documented, banded).
- **Federation** tooling and anchor-guard test coverage.
- Docs, examples, and MCP client setup guides.

By contributing you agree code is MIT-licensed and data/docs are CC-BY-4.0, like the repo.
