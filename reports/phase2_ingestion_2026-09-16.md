# Phase 2 report — Ingestion and the journal

Execution Order of 16 September 2026, Phase 2 (items 2.1–2.3). Executed 16 September 2026, 13:00–13:20 CST.

| commit | item |
|---|---|
| 9943f20 | [2.1] Brokerage export as the only producer of holdings |
| 663b3bd | [2.2] The action log seeded from transactions |
| ad5baf6 | [2.3] Referee checks for the book; the status strip shows the holdings date |

## 1. Referee, verbatim

**Before Phase 2** is the reading after Phase 1 (`reports/audit_2026-09-16_phase1_after.txt`, 19 findings, 0 CRITICAL), reproduced in the Phase 1 report.

**After Phase 2** (`reports/audit_2026-09-16_phase2_after.txt`):

```
last trading session: 2026-09-15
[HIGH    ] tournament:dead_columns      regime_v4_daily.csv: columns empty for last 5+ rows but populated earlier: ['p_15_20_elastic_net', 'p_15_40_logistic_pc', 'p_15_60_logistic_pc']
[HIGH    ] xfile:vol_single_source      intraday vix 16.85 vs canonical 17.2
[HIGH    ] nullguard                    intraday.vvix is null; dependent safety checks must read IMPAIRED not false
[HIGH    ] governance:coverage          5_werner: unclassified share 17% > 15%
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override NVDA review_by 2026-09-09 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[INFO    ] tournament:freshness         loco_cv_results.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         ml_indicator_weights.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_loadings.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_variance_explained.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v3_correlation.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           watchlist_top30.csv: no date axis found (static config?)
[INFO    ] book:export                  no brokerage export on record (holdings_export.json absent); holdings.json source: brokerage positions, 2026-09-16 (manual transcription; replaced by CSV ingestion in Phase 2)

20 findings; 0 CRITICAL
```

The one new line is the INFO the new book checks emit while no export is on record. Zero CRITICAL; HIGH unchanged (deferred governance items, the intraday-bot findings, the v4 monthly columns).

## 2. The three checks, fired on a deliberately corrupted test export

A copy of `data/` was given a `holdings_export.json` with BMNR dropped and TSM added, cash 5 percent above the served figure, and a served book dated 2026-08-04 (29 sessions back). The referee on that copy:

```
[CRITICAL] book:export_mismatch         export holdings absent from holdings.json: ['TSM']
[CRITICAL] book:export_mismatch         served holdings absent from the latest export: ['BMNR']
[HIGH    ] book:holdings_age            holdings.json as_of 2026-08-04 is 29 sessions old (>20): re-export the account
[HIGH    ] book:cash_mismatch           holdings.json cash 74527.68 differs from the export cash 78254.06 by 4.8% (>1%)
```

Exactly the three checks of item 2.3: the set difference in both directions (CRITICAL), the age (HIGH), the cash (HIGH). On the real data none fires.

## 3. Item by item

**2.1 Ingestion.** `scripts/ingest_brokerage.py` (agent-built to the order's text, reviewed and adjusted by the lead). Files in `inbox/` are recognised by header sniffing; the synonym table (positions: symbol, quantity or shares, market value, average cost or total cost, price, description, type; transactions: date, action, symbol, quantity, price, amount, fees) is a plain dictionary to extend. The job prints the mapping it chose and the unmatched headers; with a complete mapping and `--write` it writes `data/holdings.json` (cadence on_change, as_of from the export's own stamp else today, source "brokerage export", exported_at with offset, input_sha256 over positions bytes then transactions bytes, input_files, cash from the export's cash line, holdings with per-share cost_basis and a `cost_basis_basis` saying whether the export gave per-share or total cost) and `data/holdings_export.json` (the export's own positions and cash, for the referee). An unmapped required header writes nothing served, puts the best guess under `scratch/` and exits 2. Fractional shares are kept as given (100.1509 stays 100.1509). Raw exports never enter git (`inbox/*.csv`, `scratch/` ignored).

Tests (`tests/test_ingest_brokerage.py`, synthetic fixtures in three dialects under `tests/fixtures/brokerage/`), verbatim:

```
PASS test_number_and_date_parsing
PASS test_schwab_dialect_mapping
PASS test_fidelity_dialect_mapping
PASS test_fractional_shares_preserved
PASS test_cash_taken_from_cash_line
PASS test_total_cost_divided_to_per_share
PASS test_cli_dry_run_finds_files_by_header_not_name
PASS test_cli_write_writes_holdings_json_to_temp_data_dir
PASS test_unmapped_header_exits_2_and_writes_nothing_served
PASS test_session_mapping_for_non_session_dates
PASS test_regime_lookup_from_published_vintage
PASS test_signal_lookup_from_git_history
PASS test_build_entry_shape_with_real_regime_and_signal
PASS test_seed_actions_idempotent_on_temp_copy
PASS test_seed_from_inbox_and_fidelity_dialect
PASS test_zz_repository_data_and_inbox_untouched

16 passed, 0 failed
```

**2.2 Seeding.** `scripts/seed_actions_from_transactions.py` builds one `actions.jsonl` entry per buy or sell: session date (a weekend or holiday trade date maps to the next session, both dates kept), date, ticker, quantity, price, amount, the published regime (`regime_daily_published.csv`; a session with no published vintage carries the CSV's `no_publish_reason`), the signal record from the `ticker_signals.json` the system committed for that session (git history, read-only; the source commit is named; a session whose file has no record for the ticker says so), `source: "brokerage transactions"`, the export hash. Idempotent on date, ticker, action, quantity and price regardless of which export carries the trade — a trade is one fact (the lead flipped the agent's per-hash default). Verified against real published vintages in the tests (2026-08-07 → R 0.2467 LOW RISK; 2026-08-27 → null with the recorded refusal reason).

**2.3 Referee.** Three checks added to `audit_nightly.py` (§2), the status strip shows the holdings date with its source, and the export hash and export time once an export is on record. Blocking semantics unchanged: CRITICAL blocks, HIGH is logged.

## 4. Deviation

**No brokerage export exists on this machine** (searched Downloads, Desktop, Documents and the repository for positions or transactions files). Consequently:

- `data/holdings.json` remains the 16-Sept manual transcription of item 1.1 (`source` says so); the referee reports INFO `book:export` until an export is ingested.
- The July–September rotation (sales of MSFT, CEG, ETN, TSM, VRT; purchases of MU, GEV, ANET) is not in the action log. The order forbids fabricating an entry for a trade the export does not contain, and the previous `holdings.json` is not a transaction record. Both jobs are ready; the sequence when the two CSVs are dropped into `inbox/` is in `inbox/README.md`:

```bash
.venv/bin/python scripts/ingest_brokerage.py --write
```

```bash
.venv/bin/python scripts/seed_actions_from_transactions.py --write
```

Acceptance 5 is therefore met for the machinery (ingestion writes holdings.json with export provenance; the three checks fire on the corrupted export) and open for the content (the rotation entries) until the export arrives.

## 5. Judgment calls recorded by the builder and kept

Schwab's "posting date as of effective date" resolves to the effective date; a non-session trade date maps to the next session with a note; the regime label is derived from the published R with the NAV job's thresholds; the signal commit is the latest one whose file carries the session's `session_date`, else the last nightly at or before 23:59 ET of that date; dividend reinvestments are skipped unless `--include-reinvest`; Fidelity's `Type` column (the account type "Cash" on every equity) never marks a cash line by itself; sell quantities exported negative are stored as absolute quantities with the direction in the action.
