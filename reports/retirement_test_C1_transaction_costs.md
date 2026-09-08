# C1 — Transaction Costs

Order of 9 September 2026, section C1. Executed 8 September (03:00–03:40 ET). Commit `[C1]` on portfolio-tournament. Referee before/after verbatim in the appendices (before = the batch-A+B after-run; after = post-C1).

## What existed, what changed

**Found:** the backtest already charged 10 bps on *name* turnover over the equity sleeve at each rebalance, but had no gross series to label, did not cost the regime overlay's cash-sleeve resizing (the very frequency effect C3 needs), and did not cost the 60/40 benchmark's rebalances. The live tournament NAV charged a **flat, hardcoded 10 bps of the whole equity sleeve** on any holdings change, regardless of actual turnover, and recorded no turnover.

**Cost model (config `system_settings.cost_model`):** half-spread 3 bps + impact 7 bps = **10 bps one-way**, applied to **one-way turnover in NAV-weight space** — names *and* cash-sleeve resizing — at every rebalance, in the backtest, the live tiers, and the 60/40 benchmark. SPY/QQQ buy-and-hold have no trades (gross = net); SSO is a synthetic 1.5× daily proxy with no cost applied — labelled as such.

**Turnover definition:** pre-rebalance weights are the current equity fraction spread equally over the held names (the intra-month sleeve is daily-rebalanced equal-weight by construction) plus cash; target weights are the new equal-weight picks × equity fraction plus the regime's cash target; turnover = ½ Σ|Δw|. On the first rebalance this equals the equity fraction (all trades from cash), matching the old convention.

## Backtest — restated net of costs, pre-cost labelled

Window 2010-02 → 2026-05, 196 monthly rebalances, $100k per tier.

| strategy | CAGR **net** | CAGR pre-cost | cost drag pp/yr | Sharpe net | Max DD net | one-way turnover / yr | prior publication CAGR |
|---|---|---|---|---|---|---|---|
| 1_cap_pres | 6.91% | 7.33% | 0.42 | 1.06 | −10.9% | 3.98 | 6.99% |
| 2_balanced | 11.78% | 12.30% | 0.52 | 1.15 | −17.0% | 4.68 | 11.84% |
| 3_aggressive | 20.64% | 21.24% | 0.60 | 1.30 | −24.3% | 5.00 | 20.67% |
| 4_tactical | 16.71% | 17.28% | 0.57 | 1.35 | −18.9% | 4.93 | 16.78% |
| 60/40 (rebalanced) | 10.21% | 10.23% | 0.02 | 1.01 | −27.6% | — | 10.23% |
| SPY | 14.51% | 14.51% | 0 | 0.88 | −33.7% | none | 14.51% |
| QQQ | 19.81% | 19.81% | 0 | 0.98 | −35.1% | none | 19.81% |
| SSO (synthetic) | 21.18% | 21.18% | not applied | 0.88 | −47.3% | — | 21.18% |

Per-rebalance one-way NAV turnover averages 0.33–0.42 (vs 0.53–0.65 under the old name-only ratio, which ignored the cash sleeve but over-counted partial sleeves). The prior publication is stashed under `_meta.previous_publication` with its basis ("10 bps on name-turnover only; cash-sleeve resizing and 60/40 uncosted; no gross series"). Files: `backtest_metrics.json` (every headline figure carries `basis`, `pre_cost`, `cost_drag_cagr_pp`, `turnover_one_way_annual`), `backtest_equity_curves.csv` (net, the published series) and `backtest_equity_curves_gross.csv` (pre-cost twin), `backtest_holdings_log.csv` (adds `turnover_one_way_nav`, `cost_pct`).

## Live tournament — model going forward, restatement additive

`compute_nav` now charges `COST_RT × one-way NAV-weight turnover` at rebalances, computed from the last snapshot's position values, and records `rebalance: {turnover_one_way, cost_pct, cost_model}` in the tier entry. **As-published NAV history is untouched.** `tournament.json.cost_restatement` (recomputed each run from the stored snapshots) carries, per algo tier: the flat cost actually charged, the cost the model would have charged, the pre-cost NAV (flat costs added back) and the restated net NAV:

| tier | NAV as published | pre-cost | restated net | cost charged (flat) | cost (model) | one-way turnover, 5 rebalances |
|---|---|---|---|---|---|---|
| 1_cap_pres | $104,140.81 | $104,419.21 | $104,209.70 | 0.267% | 0.201% | 2.01 |
| 2_balanced | $108,097.16 | $108,448.08 | $108,189.31 | 0.324% | 0.239% | 2.39 |
| 3_aggressive | $109,738.48 | $110,169.89 | $109,917.69 | 0.392% | 0.229% | 2.29 |
| 4_tactical | $114,440.53 | $114,848.70 | $114,590.08 | 0.355% | 0.225% | 2.25 |

The flat model over-charged relative to the turnover model in every tier. Dashboard: the leaderboard NAV column is labelled **net**, its tooltip shows pre-cost, restated net, both cost totals and turnover; the sub-line states the cost model.

## Deviations and limits, recorded

1. Intra-month drift trades implied by the daily-rebalanced equal-weight sleeve are not costed — a simplification shared by every C3 contestant (all run through the same walk), so C3's comparison is internally fair; absolute cost drag is modestly understated for all.
2. SSO carries no cost (synthetic proxy); labelled, not modelled.
3. The live tiers' history remains as published under the flat model; only the restated figures are additive. Going forward the model applies.

## Referee

before (post-A+B) → after (post-C1): **0 → 0 CRITICAL**; HIGH governance-only in both. The two evaluation CSVs added by B2/C1 are declared static in the suite.

C2 (ALFRED vintages for the regime index) is next.

## Appendix A — before (`reports/audit_after_AB.txt`, verbatim)

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
exit 0
```

## Appendix B — after (`reports/audit_after_C1.txt`, verbatim)

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
exit 0
```
