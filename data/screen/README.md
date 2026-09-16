# data/screen — the screen view's served data

This directory is the served data of the **screen view** (the 4-factor
universe screener: Fundamental 0–25 + Technical 0–25 + Visibility 0–25 +
Correlation penalty 0 to −10 + Leverage penalty 0 to −5 = composite 0–75).
It was absorbed into this repository on 2026-09-16 (execution order of
16 Sept 2026, Phase 6.1 and 6.2) from the private `portfolio-screener`
repository, whose `data/` directory it reproduces byte-for-byte
(`scores.json`, `status.json`, `scored_universe.csv`, `watchlist_top30.csv`,
`portfolio_report.txt`, `visibility_registry.json`, the whole
`vintages/` tree — 29 sessions, 2026-07-29 → 2026-09-15 — and the historical
universe input `universe_535.txt`). The screener's page assets
(`index.html`, `screener.css`, `styles.css`, `charts.js`, `fonts/`) and its
`reports/`, `data/reports/` and `data/scratch/` were **not** copied.

| File | Written by | Meaning |
|---|---|---|
| `scores.json` | `scripts/screen/build_json.py` | the board: session_date, provenance (data source, holdings source, publish/scratch/forced), watchlist (top 40 + every held name outside it, `on_board_as: "held"`), portfolio, drawdown watch, corr coverage |
| `status.json` | `scripts/screen/build_json.py` | last_attempt / last_success / failure_reason / session_date — written on success **and** rejection (the badge reads it) |
| `scored_universe.csv`, `watchlist_top30.csv`, `portfolio_report.txt` | `scripts/screen/score_universe.py` | the full scored universe, the top-40 board, the text report |
| `visibility_registry.json` | governed by hand (Werner freezes); the nightly retirement pass may archive an entry | the frozen visibility overrides (v1, frozen 2026-07-29) with full provenance — every field carried over intact |
| `reconciliation.json` | `scripts/screen/reconcile_views.py` | rank correlation between the two scoring views and the ten largest divergences with attributed cause (cadence daily) |
| `vintages/<session>/` | `scripts/screen/build_json.py` (publish mode only) | immutable as-published copies of `scores.json`, `scored_universe.csv`, `watchlist_top30.csv` |
| `scratch/<ts>/` | `scripts/screen/build_json.py` (pre-close runs) | never served, never committed (`.gitignore: scratch/`) |
| `universe_535.txt` | historical input, frozen | the screener's own universe as it was on absorption — an input to `scripts/build_universe.py`, not a served file |

Inputs the screen view now reads locally (no cross-repository fetch): the
canonical artifact `data/canonical/fundamentals.json` +
`data/source/prices_daily.parquet` (published-URL fallback recorded in
provenance only), the book `data/holdings.json` (raw-GitHub fallback recorded
only; `HOLDINGS_LOCAL_PATH` overrides), and the ONE universe `data/universe.txt`
built by `scripts/build_universe.py` (union of both views' universes plus every
held name; `data/universe_meta.json` records the one-sided names).

**Referee coverage.** The nightly referee (`scripts/audit_nightly.py`)
discovers files — it never keeps a per-file list — by globbing every `*.json`
and `*.csv` under each data root it is given, and applies its screener-specific
checks (corr column alive, typed ranges, broken-base tagging, fundamental
dispersion, visibility review dates, session staleness) to the second root.
This directory is that second root: `python scripts/audit_nightly.py data data/screen`
(replacing the pre-absorption `../portfolio-screener/data` clone). Files that
are old by design declare it (`cadence: on_change` / the STATIC set includes
`visibility_registry.json`); everything else is held to the daily freshness rule.
