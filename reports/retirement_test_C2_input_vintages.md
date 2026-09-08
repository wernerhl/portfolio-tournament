# Retirement test C2 — Input vintages (ALFRED point-in-time rebuild of the regime index)

**Order** (Governance Decisions and the Retirement Tests, 9 Sept 2026, C2): *"Rebuild the regime index's history on ALFRED vintages of every FRED series it uses, so each historical reading uses only data available on that date. Report how much the regime index's lead and its drawdown-reduction change between revised and as-published inputs."*

**Executed** 2026-09-08. Nothing served changed: the published vintage, `regime_v2_daily.csv`, the leaderboard backtest and every dashboard file are byte-identical to before this batch. All point-in-time artifacts live in `data/source/*_pit.parquet` (source) and `data/c2/` (working directory, outside the referee's scan; large files git-ignored, regenerable from the committed inputs in about two minutes).

## 1. Result in one paragraph

The 24-indicator regime index keeps its ranking power on point-in-time inputs (AUC against a 10% drawdown within 60 days: 0.637 revised → 0.639 point-in-time), and the "index above 0.50" warning is unchanged for every episode because the index sits above 0.50 for a year or more before most peaks. What changes is the higher-conviction signal and the money: the ≥0.70 warning arrives 4–49 trading days later and disappears entirely for the Sept-2018 episode, and when the index drives the tier sizing through the C1-costed engine, the tiers' drawdown reduction versus SPY shrinks by roughly a quarter to a third (tier 1: 70.9% → 61.0%; tier 2: 47.1% → 36.4%; tier 3: 23.2% → 17.8%; tier 4: 52.2% → 35.8%). Decomposition shows revisions are the channel: release lag alone costs 1.5–4.6 points of drawdown reduction, revisions a further 4.6–13.6 points, and removing the retro-filled histories of series that did not yet exist costs nothing (it adds 0.7–1.8 points back). The leaderboard's served backtest is driven by the internal 12-indicator vol-based `R_t`, which has no FRED inputs and is unaffected.

## 2. Method

**Vintage fetch** (`scripts/fred_vintages.py`, run only in CI by `.github/workflows/vintage_rebuild.yml` with the `FRED_API_KEY` secret; the key is not available locally and was never printed). For each of the 13 FRED series the index touches — nine direct inputs plus the four components of the two derived spreads — every release is pulled from ALFRED. ALFRED refuses more than 2,000 vintage dates per request and silently truncates at 100,000 rows; the first dispatch hit both (three daily series refused; NFCI, ANFCI and STLFSI4 truncated at exactly 100,000 rows). The fetch now splits the real-time window recursively on either signal (NFCI: 954,235 rows; ANFCI: 1,068,584) and treats a window that lies entirely before a series' first vintage as empty. Fixture-tested for release lag, revision capture, and reassembly across windows.

**Point-in-time value on day t** = the latest observation whose vintage date ≤ t, at its latest revision published by t, forward-filled daily and then to trading days. This honours release lag (a July print published in late August is not known in July) and revisions (each NFCI release re-estimates the whole history).

**Before a series' first ALFRED vintage**, two cases, documented per series in `data/source/fred_vintage_meta.json`:
- the series did not yet exist as a published product (NFCI/ANFCI launched 2011, KCFSI 2009/10, STLFSI4 in its current construction Nov 2022): point-in-time value is unavailable (NaN), because nobody could have used it;
- the series existed but ALFRED tracked it later (Treasury yields from June 2005, HY OAS from 2023, SLOOS from 2010, 5y breakeven from 2014): the revised value shifted by the series' *measured* publication lag (median first-release lag over its first two years of vintages).

**Rebuild and comparison.** `compute_regime_v2.py` gained a `REGIME_PIT=1` mode that reads the point-in-time parquets and writes to `data/c2/` (no compat shim, no published vintage, no JSON). `backtest.py` gained a regime-override mode (`REGIME_OVERRIDE_CSV/COL`, outputs tagged into `data/c2/`) so the same engine, tier sizing, and C1 cost model run on any external regime series; C3 reuses it. Lead times, AUC and drawdown episodes use the existing `validate_regime_v2.py` functions unchanged. To separate the causes, two further variants were built locally from committed data (`scripts/c2_build_variants.py`):

| variant | FRED inputs | isolates (vs previous column) |
|---|---|---|
| rev | as published today (revised) | — |
| lag | revised values shifted by measured publication lag; all series treated as existing | release lag |
| pitfill | true vintages after first vintage, lag-only before; all series treated as existing | revisions |
| pit | strict point-in-time: unavailable before the series existed | series existence |

## 3. Vintage coverage (from `fred_vintage_meta.json`)

| input | FRED id | releases | first vintage | measured lag | existed before? | PIT ≠ revised (days) | revision effect after first vintage |
|---|---|---|---|---|---|---|---|
| nfci | NFCI | 954,235 | 2011-05-25 | 5d | no | 99.6% | 99.7% |
| anfci | ANFCI | 1,068,584 | 2011-05-25 | 5d | no | 99.6% | 99.8% |
| kcfsi | KCFSI | 40,871 | 2010-11-08 | 38d | no | 100.0% | 100.0% |
| stlfsi | STLFSI4 | 307,029 | 2022-11-10 | 6d | no | 100.0% | 99.8% |
| mfg_new_orders | NEWORDER | 7,023 | 1997-03-06 | 56d | yes | 100.0% | 100.0% |
| loan_tightening | DRTSCILM | 184 | 2010-04-20 | 37d | yes | 96.5% | 4.4% |
| consumer_expect | MICH | 587 | 1999-02-26 | 27d | yes | 81.5% | 8.6% |
| breakeven_5y | T5YIE | 10,712 | 2014-01-27 | 1d | yes | 58.5% | 47.2%* |
| hy_oas | BAMLH0A0HYM2 | 795 | 2023-09-05 | 0d | yes | 0.0% | 0.0% |
| us10y | DGS10 | 59,210 | 2005-06-28 | 4d* | yes | 92.8% | 80.8%* |
| us03m | DGS3MO | 38,511 | 2005-06-28 | 4d* | yes | 71.1% | 64.8%* |
| baa_yield | BAA | 1,297 | 1996-12-03 | 35d | yes | 98.8% | 11.9% |
| aaa_yield | AAA | 1,298 | 1996-12-03 | 35d | yes | 98.8% | 12.1% |

"PIT ≠ revised" is dominated by release lag for monthly and quarterly series and is expected. "Revision effect" compares the point-in-time series with the lag-only comparator after the first vintage: near 100% for the four factor-model stress indices (re-estimated every release) and for NEWORDER (monthly and annual benchmark revisions); single digits for SLOOS, Michigan and Moody's yields. \*Treasury yields and the breakeven are not revised; their nonzero "revision effect" and the 4-day measured lag reflect ALFRED's weekly H.15 vintage capture in 2005–07, a comparator artefact that only affects the pre-June-2005 fill (immaterial) and the lag variant for those two series.

Indicator coverage (mean `n_full_indicators` by year): revised 21.8–22.0 from 2007; strict point-in-time 18.0 through 2010 (NFCI, ANFCI, KCFSI, STLFSI4 absent), 19.7 in 2011, 21.0 from 2012 to 2022 (STLFSI4 absent), converging with revised from 2023.

## 4. Results (verbatim output of `scripts/c2_vintage_compare.py`)

Window common to all variants: 2005-01-03 → 2026-09-04 for the index; the backtest engine's window is 2010-02-01 → 2026-05-21 (4,102 sessions, SPY max drawdown −33.7%), so the 2007–09 episode enters the lead-time table but not the drawdown table.

```
| metric | rev | lag | pitfill | pit |
|---|---|---|---|---|
| AUC R_full | 0.6372 | 0.6391 | 0.629 | 0.639 |
| AUC R_lead | 0.6276 | 0.6273 | 0.612 | 0.6131 |
| corr(R_full) vs rev | · | 0.9763 | 0.9522 | 0.924 |
| mean abs ΔR_full vs rev | · | 0.0266 | 0.0374 | 0.0491 |
| days abs Δ > 0.05 | · | 14.7% | 27.1% | 40.2% |
| days abs Δ > 0.10 | · | 1.3% | 5.4% | 11.8% |

Lead (trading days before peak) — R_full ≥ 0.50
| episode peak | DD | rev | lag | pitfill | pit |
|---|---|---|---|---|---|
| 2007-10-09 | -56.8% | 347 | 347 | 347 | 347 |
| 2015-05-21 | -14.2% | 203 | 213 | 203 | 203 |
| 2018-01-26 | -10.2% | 347 | 347 | 347 | 347 |
| 2018-09-20 | -19.8% | 159 | 151 | 151 | 151 |
| 2020-02-19 | -33.9% | 340 | 340 | 340 | 340 |
| 2022-01-03 | -25.4% | 297 | 299 | 297 | 333 |
| 2025-02-19 | -18.9% | 333 | 334 | 334 | 334 |

Lead (trading days before peak) — R_full ≥ 0.70
| episode peak | DD | rev | lag | pitfill | pit |
|---|---|---|---|---|---|
| 2007-10-09 | -56.8% | 335 | 307 | 315 | 313 |
| 2015-05-21 | -14.2% | 160 | 156 | 150 | 111 |
| 2018-01-26 | -10.2% | None | None | None | None |
| 2018-09-20 | -19.8% | 125 | None | None | None |
| 2020-02-19 | -33.9% | 311 | 295 | 294 | 292 |
| 2022-01-03 | -25.4% | None | None | None | None |
| 2025-02-19 | -18.9% | None | None | None | None |

Lead (trading days before peak) — R_lead ≥ 0.55
| episode peak | DD | rev | lag | pitfill | pit |
|---|---|---|---|---|---|
| 2007-10-09 | -56.8% | 341 | 345 | 347 | 347 |
| 2015-05-21 | -14.2% | 203 | 200 | 161 | 161 |
| 2018-01-26 | -10.2% | 347 | 347 | 347 | 347 |
| 2018-09-20 | -19.8% | 159 | 150 | 150 | 140 |
| 2020-02-19 | -33.9% | 340 | 334 | 340 | 340 |
| 2022-01-03 | -25.4% | 297 | 297 | 19 | 297 |
| 2025-02-19 | -18.9% | 146 | 332 | 131 | 131 |

Max drawdown / DD reduction vs SPY / CAGR net / Sharpe net
| tier | rev | lag | pitfill | pit |
|---|---|---|---|---|
| 1_cap_pres | -9.8% / 70.9% / 7.33% / 1.12 | -10.7% / 68.4% / 7.37% / 1.09 | -13.6% / 59.8% / 7.16% / 1.03 | -13.2% / 61.0% / 7.15% / 1.04 |
| 2_balanced | -17.8% / 47.1% / 12.24% / 1.19 | -18.9% / 44.0% / 12.18% / 1.15 | -21.9% / 35.1% / 11.94% / 1.11 | -21.4% / 36.4% / 11.98% / 1.12 |
| 3_aggressive | -25.9% / 23.2% / 20.96% / 1.31 | -26.4% / 21.7% / 20.84% / 1.29 | -27.9% / 17.1% / 20.67% / 1.27 | -27.7% / 17.8% / 20.67% / 1.27 |
| 4_tactical | -16.1% / 52.2% / 17.32% / 1.38 | -17.7% / 47.6% / 17.11% / 1.33 | -22.3% / 34.0% / 16.69% / 1.27 | -21.6% / 35.8% / 16.77% / 1.29 |
```

Served leaderboard backtest for reference (internal vol-based `R_t`, no FRED inputs, unaffected by vintages): tier 1 max DD −10.9% (67.6% reduction), tier 2 −17.0% (49.6%), tier 3 −24.3% (27.9%), tier 4 −18.9% (43.8%).

## 5. Reading the tables

- **Lead at the 0.50 threshold is saturated, not robust.** `lead_time` looks back 504 calendar days (about 347 trading days) from the peak; a lead of 333–347 means the index was already above the threshold at the start of the window. The 0.50 line is a persistent state, not a trigger, on either input set.
- **The 0.70 line is where vintages bite.** Point-in-time, the high-conviction warning is 22 days later for 2007, 49 days later for 2015, 19 days later for 2020, and never fires for Sept-2018 (revised: 125 days). The lead composite `R_lead ≥ 0.55` loses 42 days for 2015 and 19 for Sept-2018; the 2022 "19" in the pitfill column is a single-variant artefact (a brief dip below 0.55 inside the window) and does not appear in the strict series.
- **Drawdown reduction is the honest casualty.** Under the same engine and costs, point-in-time sizing leaves each tier 1.8–5.5 points deeper in its worst drawdown, costs 0.18–0.55 pp of net CAGR, and 0.04–0.09 of Sharpe. Tier 4 (tactical), which leans hardest on the overlay, loses the most (52.2% → 35.8% reduction).
- **Revisions, not lag, and not back-filled history.** rev→lag: −1.5 to −4.6 points of drawdown reduction. lag→pitfill: −4.6 to −13.6 points. pitfill→pit: +0.7 to +1.8 points. The four factor-model stress indices are re-estimated at every release and NEWORDER is benchmark-revised; today's revised series "knew" 2020 and 2022 better than any reader could at the time.
- **What does not change:** correlation between revised and strict point-in-time `R_full` is 0.924; the ranking power against forward drawdowns is the same. The index is a fair classifier point-in-time; its as-published *timing* at the high-conviction line and its as-published *overlay benefit* are overstated.

## 6. What this does and does not touch

- Served files: none. The dashboard's regime-index history remains the revised-input series and the published vintage remains append-only. Whether the dashboard's history panel should show the point-in-time series, or carry a note that historical readings are on revised inputs, is a governance decision recorded below — not made here.
- C3 will run on **as-published inputs** as the order specifies ("the window: full backtest history on C2's as-published inputs"); this report is the disclosed context that the 24-indicator contestant's drawdown reduction on those inputs carries roughly a quarter to a third of revision content.
- Costs: all four variants are net of the C1 model (3 bps half-spread + 7 bps impact, one-way, on NAV-weight turnover).

## 7. Referee before / after (verbatim, `scripts/audit_nightly.py`)

Before (`reports/audit_before_C2.txt`):

```
last trading session: 2026-09-04
[HIGH    ] governance:coverage          5_werner: unclassified share 16% > 15%
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[MEDIUM  ] status:opaque                tournament failure_reason does not name the failing assertion
[INFO    ] tournament:freshness         loco_cv_results.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         ml_indicator_weights.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_loadings.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_variance_explained.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v3_correlation.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           watchlist_top30.csv: no date axis found (static config?)

16 findings; 0 CRITICAL
```

After (`reports/audit_after_C2.txt`): identical — `diff` of the finding lines is empty; 16 findings, 0 CRITICAL. The C2 artifacts add no findings (working directory outside the scan; `c2_vintage_comparison.json` declares `cadence: on_change`).

The one MEDIUM, `status:opaque`, is the served `status.json` left by the Labor-Day nightly (2026-09-07 20:07 ET), which ran **pre-remediation code** (HEAD 2e85737, before the guard commits of 22:55 and 23:30 MDT): every stage labelled its data to session 2026-09-04 correctly and validation then rejected it against "last session 2026-09-07" — a NYSE holiday that the validator's private weekday-only helper did not know. The holiday guard was already fixed in [2.3]; the residual defect (the validator's own clock, which would have wrongly rejected the first post-Thanksgiving run if the cron throttled past midnight) is fixed in commit 6ae6c73: the freshness reference is now the session the guard decided to publish. Verified with the clock override at 2026-09-08 02:00 ET: "publishing session 2026-09-04 … Validation passed." The served status clears with the next successful nightly (2026-09-08 evening).

## 8. Commits

| commit | item |
|---|---|
| 82dc1ed | [C2] ALFRED vintage fetch (CI), `REGIME_PIT` rebuild mode, backtest regime override, comparison harness |
| 7011f50 | [C2] recursive window splitting for ALFRED caps; pre-vintage rule per series |
| c88bc9a | [C2] pre-vintage windows are empty, not errors; lag measured on post-first-vintage observations |
| 077cda8 | 🗂 ALFRED point-in-time inputs 2026-09-08 (CI, `vintage_rebuild.yml`; 13/13 series) |
| 6ae6c73 | [memo-§7] validator freshness keys on the guard's session (holiday-aware) |
| (this) | [C2][report] decomposition variants, comparison JSON, this report, referee before/after |

## 9. Decisions for Werner (nothing here has been applied)

1. **Dashboard disclosure.** The regime-index history panel shows revised-input readings. Options: (a) add a one-line note "history on revised inputs; point-in-time rebuild reduces overlay drawdown reduction by ~¼–⅓ (C2)"; (b) serve the point-in-time series as the history and the revised value only for the current reading; (c) leave as is. (a) is the smallest honest change.
2. **Overlay weighting.** The four factor-model stress indices (NFCI, ANFCI, KCFSI, STLFSI4) carry nearly all the revision content. A C4-style follow-up could test the index with those four replaced by their first-release values or removed — but C4 is deferred to C3's outcome by the order, so this is noted, not started.
3. **C3 context line.** When C3 reports the 24-indicator contestant's drawdown reduction on as-published inputs, the report will cite this document's revised-vs-point-in-time gap alongside it, as the order's "results restate the registered spec" rule allows context but not parameter changes.
