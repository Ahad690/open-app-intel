# Good First Issues — seed list

16 small, well-scoped tasks that make good first PRs. Label them `good first issue`;
this is the **fork-funnel** that drove 11.5k forks on comparable repos.

| # | Title | Area | Acceptance |
|---|-------|------|-----------|
| 1 | Add Play top-chart collector for more countries | collectors | new country codes wired; test with a recorded fixture |
| 2 | Add an Apple RSS chart collector for a new category | collectors | new category feed + test |
| 3 | Add `--json` pretty-print flag to the CLI | feature | flag formats envelope output; test |
| 4 | Add a dark-mode theme to `app-intel-report.html` | ui | `prefers-color-scheme: dark`; screenshot in PR |
| 5 | Document the P1 envelope schema with examples | docs | one markdown page |
| 6 | Add a fixture + test for the never-HIGH cap | tests | asserts an estimate can never be HIGH |
| 7 | Add a fixture + test for the no-USD ad gate | tests | asserts ad module never emits USD |
| 8 | Improve the "uncalibrated segment" empty-state | ux | report renders an honest NONE card; test |
| 9 | Add a `make test` / `just test` shortcut | dx | one-command test run + README note |
| 10 | Add an MCP setup guide for Cursor | docs | step-by-step config page |
| 11 | Add an MCP setup guide for OpenCode/Codex | docs | config page |
| 12 | Validate `assert_public_only` rejects a crafted row | tests | adversarial fixture with ad fields is rejected |
| 13 | Add alt-text lint for README images | a11y | script flags `<img>` missing `alt` |
| 14 | Add a `pre-commit` config running pytest | dx | `.pre-commit-config.yaml` + docs |
| 15 | Localize `app-intel-report.html` labels (Spanish) | i18n | `.es` label set + test |
| 16 | Add a contributors shout-out section to the README | community | auto-updatable section |

## Creating them

Run a `gh issue create` loop (template in the fiverr repo's `GOOD_FIRST_ISSUES.md`),
or create by hand. **Public issues are outward-facing and hard to undo — start with
5–8 and review before sharing.** Labels: `good first issue` (`7057ff`), `hacktoberfest`
(`ff6b35`).
