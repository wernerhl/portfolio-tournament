# Reconciliation Response — 8 September 2026

**Nothing here is live yet.** Both sites deploy from the workflow build, not from pushes to main; tonight's (Sept 8) nightly is the first deploy that carries the batch, the memo's three decisions, and the audit install. Verify against the live site tomorrow morning per memo §7.

## Verdict against the order's acceptance criterion

With the referee installed and corrected (below), run at 01:5x ET on main:

| | CRITICAL | HIGH | of which governance-deferred | exit |
|---|---|---|---|---|
| **before** (pre-batch: tournament `a41397f`, screener `ada6f78`) | **5** | 30 | 11 | 1 |
| **after** (tournament `9cae8c9`+rerun, screener `572d808`) | **0** | **11** | **11** (coverage ×5, review_overdue ×6) | **0** |

Zero CRITICAL; every remaining HIGH is `governance:coverage` or `governance:review_overdue`. One MEDIUM remains (`status:opaque` — the committed `status.json` still carries the Labor-Day text "validation failed (exit 1)"; the first post-batch run rewrites it with named checks). Both outputs verbatim in Appendices A/B; the first-pass outputs from the *uncorrected* suite are kept alongside as `audit_*_uncorrected_suite.txt`.

## The referee: installed, and corrected once more

`scripts/audit_nightly.py` is the memo's corrected suite verbatim plus the two additions you asked for: `HOLIDAYS` through 2027 (order item 6) and the `v4:monthly_columns` assertion (memo decision 1). Then the first after-run disagreed with the memo's stated result ("four to zero"): it reported **8 CRITICAL**, all `tournament:freshness` on static artifacts — `benchmark_inception`, `regime_comparison`, `regime_v2_auc`, `regime_v2_divergence_test`, `regime_v3_daily.csv`, `regime_v2_leadtimes.csv`, the legacy `vol_canonical_close.json`, a backtest log. The suite's static exemption was a hardcoded list that ignored the `cadence` declarations item 5 introduced — the "per-file list that can be forgotten" its own header warns about. Per memo §6 ("a referee that raises false alarms trains everyone to ignore it… these corrections are part of the deliverable"): it now honors a served JSON's own `cadence` (static/on_change/weekly/monthly) and lists the four analysis files that cannot declare. That correction is the difference between the uncorrected and corrected runs; it changes no CRITICAL that was real.

The **before** run's 5 CRITICAL are the real pre-batch defects: the phantom Sept-7 `intraday.json` and canonical records (×2 checks), `vol_regime` frozen at 07-17, plus `benchmark_inception` flagged stale — the pre-batch file carried no cadence declaration, so it is a static-file false positive *in that state only*.

## Memo §4 decisions — all executed

**1. v4 monthly columns.** `regime_v4_ml.py` rerun now (fitted 2026-09-07, train_end 2026-09-04), then the nightly rescore. Every probability column is populated through **2026-09-04**, `raw_score` survived the rewrite (5,390/5,394), and the suite's `v4:monthly_columns` assertion is in. One consequence to know: with repaired vol inputs the **model selection changed** — production ≥5%/40d winner is now `equal_weight` (Brier 0.1835 vs 0.1918 baseline), and ≥7%/60d moved from `logistic_pc` to `equal_weight` (its old column is superseded, not refilled); the three `p_15_*` model columns kept their methods and are refilled. All four columns the dashboard reads exist. This is the recalibration doing its job on inputs that were broken for the Sept-1 run.

**2. Intraday VVIX.** Root cause: the reconcile loop assigned only two top-level keys and skipped any key already null. It now maps all five and records `reconciled_fields`. The served Sept-4 record was reconciled the same way: `vvix 84.42`, `vix1d 12.03`. `nullguard` cleared.

**3. Run guard keyed on the session.** `last_completed_session()` (ET, close + 15 min); the daily job publishes S whenever S is the most recent completed session, regardless of calendar day. Proven without running the pipeline: `2026-08-28T02:02 → 2026-08-27` (the throttled-cron case), `09-08T01:30 → 09-04`, `09-08T15:59 → 09-04`, `09-08T16:20 → 09-08`, Labor Day `20:00 → 09-04`. `last_trading_session()` now delegates, so guard, validation and served_meta agree.

**Status file / small-n.** `today_excluded` is now declared at the top of `vol_regime.validation`; `small_n` flags the event-day subsample (n=17). `failure_reason` naming is code-complete; the served `status.json` shows it after the first post-batch run.

## Item 6 — CI

Both workflows run `audit_nightly.py` after the pipeline, before commit/deploy (each clones the other public repo for the second data tree). **CRITICAL:** `audit_status.py` restores the repo's served files to the last good commit, writes `failure_reason: "audit: <checks>"` into `status.json` (last_success preserved), the step fails and the job fails — the deploy then publishes the last good board plus the new status, so the dashboard shows the rejection (the [8.2] semantics the memo paraphrases as "blocks the deploy"). **HIGH:** logged in `status.json.audit.high`, surfaced in a new status strip on the tournament dashboard and the screener's info banner; never blocks. Strip render-verified locally against the current status (amber "last run rejected … served artifacts are the last good board (session 2026-09-04)"). One design note: the suite is cross-repo, so a tournament CRITICAL also blocks the screener's publish — as ordered ("any CRITICAL"), flagged here as coupling.

Also fixed on the way: the screener's staleness badge had the same weekend-only expected-session logic the tournament had; both are holiday-aware now.

## Memo §3 (VIX 15.30 vs 14.53)

Acknowledged; no action beyond the canonical chain. The regime published Friday stands as published; tonight's revised recompute uses 14.53.

## What tonight's run should show (verify tomorrow, memo §7)

Canonical `2026-09-08` with all five providers `cboe`; `intraday.json` post-close reconciled with `skew` and `vvix` populated; `vol_regime` as_of 09-08 with the assertion silent; `status.json` naming any check that fires; `reports/audit_last.txt` committed by the CI step; live suite run: 0 CRITICAL, HIGH = governance only.

## Open — yours

Provisional-classification vs manual approval of the 22 proposals (coverage 16–71% unclassified across tiers); six visibility reviews overdue since mid-August (AMZN, ANET, ETN, GD, MSFT, VRT).

Commits: tournament `48bb4f0` [memo-D3] · `185473e` [memo-D2] · `9cae8c9` [6] · [memo-D1] + reports (this push); screener `572d808` [6].

## Appendix A — `reports/audit_before.txt` (verbatim, corrected suite)

```
last trading session: 2026-09-04
[CRITICAL] tournament:freshness         benchmark_inception.json: max date 2026-05-20 is 74 sessions-old vs last session 2026-09-04
[CRITICAL] tournament:calendar          intraday.json: contains non-trading date 2026-09-07 (phantom session)
[CRITICAL] tournament:calendar          vol_close_canonical.json: contains non-trading date 2026-09-07 (phantom session)
[CRITICAL] tournament:freshness         vol_regime.json: max date 2026-07-17 is 35 sessions-old vs last session 2026-09-04
[CRITICAL] calendar:canonical_close     vol_close_canonical dated 2026-09-07 (non-trading day): phantom close written
[HIGH    ] tournament:gaps              regime_daily_published.csv: missing trading days in recent window [datetime.date(2026, 6, 24), datetime.date(2026, 6, 26), datetime.date(2026, 8, 27)]
[HIGH    ] tournament:dead_columns      regime_v4_daily.csv: columns empty for last 5+ rows but populated earlier: ['p_7_60_logistic_pc', 'p_15_20_elastic_net', 'p_15_40_logistic_pc', 'p_15_60_logistic_pc']
[HIGH    ] tournament:freshness         v4_scoring_params.json: max date 2026-09-01 is 3 sessions-old vs last session 2026-09-04
[HIGH    ] provider:vol_complex         canonical providers unavailable for ['vix3m', 'vvix', 'vix1d', 'skew'] (Cboe path failing; intraday nulls follow from this)
[HIGH    ] nullguard                    intraday.skew is null; dependent safety checks must read IMPAIRED not false
[HIGH    ] nullguard                    intraday.vvix is null; dependent safety checks must read IMPAIRED not false
[HIGH    ] ui:calendar                  lastTradingSessionISO() not holiday-aware
[HIGH    ] v4:monthly_columns           p_7_60_logistic_pc populated through 2026-08-24 but monthly model train_end is 2026-08-31
[HIGH    ] v4:monthly_columns           p_15_20_elastic_net populated through 2026-08-24 but monthly model train_end is 2026-08-31
[HIGH    ] v4:monthly_columns           p_15_40_logistic_pc populated through 2026-08-24 but monthly model train_end is 2026-08-31
[HIGH    ] v4:monthly_columns           p_15_60_logistic_pc populated through 2026-08-24 but monthly model train_end is 2026-08-31
[HIGH    ] governance:coverage          1_cap_pres: unclassified share 71% > 15%
[HIGH    ] governance:coverage          2_balanced: unclassified share 59% > 15%
[HIGH    ] governance:coverage          3_aggressive: unclassified share 41% > 15%
[HIGH    ] governance:coverage          4_tactical: unclassified share 35% > 15%
[HIGH    ] governance:coverage          5_werner: unclassified share 16% > 15%
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[MEDIUM  ] tournament:schema            backtest_metrics.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            event_calendar.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            indicator_series.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            intraday.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            regime_comparison.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            regime_conditional_scores.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            regime_v2_auc.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            regime_v2_divergence_test.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            thesis_backtest.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            thesis_claims.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            thesis_registry.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            ticker_indicators.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            ticker_signals.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            v4_calibration.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            v4_model_results.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] tournament:schema            v4_scoring_params.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] screener:schema              visibility_registry.json: no declared as_of/session_date; freshness inferred from max date (unreliable)
[MEDIUM  ] validation:small_n           event-day n<20 without caveat flag
[MEDIUM  ] status:opaque                tournament failure_reason does not name the failing assertion
[INFO    ] tournament:freshness         loco_cv_results.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         ml_indicator_weights.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_loadings.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_variance_explained.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_comparison.json: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v2_auc.json: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v2_divergence_test.json: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v3_correlation.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         scored_universe.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         v4_calibration.json: no date axis found (static config?)
[INFO    ] tournament:freshness         v4_model_results.json: no date axis found (static config?)
[INFO    ] screener:freshness           scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           watchlist_top30.csv: no date axis found (static config?)

59 findings; 5 CRITICAL
exit 1
```

## Appendix B — `reports/audit_after.txt` (verbatim, corrected suite)

```
last trading session: 2026-09-04
[HIGH    ] governance:coverage          1_cap_pres: unclassified share 71% > 15%
[HIGH    ] governance:coverage          2_balanced: unclassified share 59% > 15%
[HIGH    ] governance:coverage          3_aggressive: unclassified share 41% > 15%
[HIGH    ] governance:coverage          4_tactical: unclassified share 35% > 15%
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

20 findings; 0 CRITICAL
exit 0
```
