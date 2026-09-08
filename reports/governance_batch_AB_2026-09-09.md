# Governance Decisions and Mechanics — Batch A + B Report

Order issued 9 September 2026; executed 8 September 01:50–02:40 ET on main. Commits per item: tournament `c251a4d` [A1] · `87f47c8` [B1] · `299e239` [B2] · `a11c3f8` [B3] · `305ccfd` [A1][B1][B3] dashboard; screener `ea484b7` [A2] · `ffc1163` [B3]. Nothing is live until the next workflow deploy (the Sept-8 nightly, which had not fired at execution time).

## Referee

| run | findings | CRITICAL | HIGH | of which governance-deferred | exit |
|---|---|---|---|---|---|
| before (main `1e8c853` / `572d808`) | 20 | **0** | 11 | 11 (coverage ×5, review_overdue ×6) | 0 |
| after (main `305ccfd` / `ffc1163`) | 16 | **0** | 7 | 7 (coverage ×1 — 5_werner; review_overdue ×6) | 0 |

Both outputs verbatim in Appendices A/B. Coverage HIGHs fell from five tiers to one (Werner's tier: BMNR has no proposal). The six `review_overdue` HIGHs are the decay engine working, as A2 states; they clear on review or on retirement (Nov 11–17). One MEDIUM (`status:opaque`) clears on the first post-batch run.

## A1 — Provisional classification: adopted and applied

Implemented as the 7-Sept order specified. Agent-proposed **name** mappings apply immediately on top of the frozen registry (never overriding it), are tagged **PROVISIONAL** on every panel that uses them (tier bars, basket rows, the registry banner), count toward coverage with a one-line caveat, and expire back to unclassified **30 days after first proposal** unless approved into the registry — a human act with recorded provenance, unchanged. `data/provisional_ledger.json` carries first-proposed dates across the nightly proposal regeneration; an expired name is **not** re-provisionalised automatically (a human approves it or clears the entry). Nothing provisional is ever silently permanent.

First application, as_of 2026-09-04: **21 of the 22 proposals provisional, expiring from 2026-10-04.**

| tier | unclassified, registry only | provisional | unclassified now |
|---|---|---|---|
| cap_pres | 70.6% | 66.2% | 4.4% |
| balanced | 58.6% | 55.0% | 3.6% |
| aggressive | 41.2% | 39.2% | 2.0% |
| tactical | 35.4% | 35.4% | 0.0% |
| werner | 16.3% | — | 16.3% |

**The 22nd — reported, not applied:** `memory_semis` is a structural proposal (a new sub-thesis), not a name mapping. Its member MU is already in `ai_infra` at weight 1.0; applying it mechanically would breach the Σweights ≤ 1 invariant the pipeline asserts, and the registry has no thesis hierarchy to express a sub-thesis. It stays `pending` with that note; approval (a registry version with a hierarchy) is the only path. Werner's tier remains above 15% because BMNR has no proposal (it sits in the v3 queue as a residual with no thesis that fits).

## A2 — Visibility review policy: the decay engine carries it

Policy added to the registry (metadata, no value touched): an override that passes **two consecutive earnings cycles without review** retires to the sector prior and is archived under `retired` with its full record; returning it requires re-registration with a fresh rationale and date. `visibility_retire_at()`: earnings-anchored entries retire at `next_earnings + 91d + 14d grace`; 180-day entries at `as_of + 182d + 14d`; any review resets the clock. The nightly archival pass in `build_json` moves retired entries and logs `policy_events`; scoring returns the capped sector prior for a retired name.

The six overdue overrides keep decaying and retire unless reviewed: GD, MSFT, VRT **2026-11-11** · AMZN 11-12 · ETN 11-13 · ANET 11-17. Nothing retires tonight; the operator reviews when the operator reviews.

## B1 — The v4 model change is stamped and announced

`regime_v4_daily.csv` now carries `model_version` on every row — `v4-2026-09-07-equal_weight` (keyed to the calibration file's `as_of` + winning method), and the calibration file writes `as_of`/`model_version` natively.

**Deviation, recorded:** the order asked to backfill historical rows with the *prior* version's identifier. That would misdescribe them: the monthly run rewrites **every** row, so no pre-rerun row survived — all 5,394 rows were produced by the Sept-7 calibration and are labelled so. To make the series self-describing across future changes, `regime_v4_ml` now archives the outgoing series under its own `model_version` (`data/v4_vintages/`) before overwriting. As-published values are unchanged.

Dashboard note (30 sessions from 2026-09-07), carrying the **out-of-fold** numbers from B2 rather than the order's in-sample figures: *"model changed 2026-09-07: equal-weight replaces logistic; out-of-fold Brier 0.1989 vs 0.2145 (logistic) — base rate 0.1918: no out-of-fold skill over the base rate on Brier; in-sample 0.1835 was the isotonic fit."*

**Ledger supplement — Failure 10 addendum (B1.3):** a repair to inputs changed the winning model. With `vix3m`, `vix1d` and `skew` restored from Cboe, the Sept-7 recalibration selected `equal_weight` over `logistic_pc` for the production target. This is expected — model selection is a function of the inputs it sees — and it is why model identity must travel with the data (`model_version`) and why calibration evidence must be out-of-fold, not in-sample.

## B2 — Out-of-fold calibration evidence

`scripts/v4_oof_calibration.py`. Folds: the leave-one-crisis-out episodes from `data/source/spx_drawdown_episodes.csv` (deduped as `regime_v3_ml` does), extended to full coverage — each crisis episode [peak, recovery] is a fold and each calm stretch between episodes is a fold, so every day is held out exactly once: **15 folds (7 crisis + 8 calm)**, purge 40+20 sessions either side, isotonic fitted on *training* predictions per fold. Production target ≥5%/40d, 5,393 days, 1,395 positives.

| method | Brier out-of-fold | Brier in-sample | n (oof) |
|---|---|---|---|
| equal_weight | **0.1989** | 0.1835 | 5393 |
| logistic_pc | 0.2145 | 0.1695 | 5393 |
| elastic_net | 0.2494 | 0.1622 | 5393 |
| base rate | 0.1918 | 0.1918 | 5393 |

**Decision (B2.2):** equal_weight wins out of fold → **the switch stands**, consistent with the textbook finding on ML weighting. **The finding that matters more:** no method beats the base-rate Brier out of fold — the calibrated v4 probability has no out-of-fold Brier skill over the unconditional rate; the four-decimal in-sample reliability was the isotonic fit on its own training data, exactly as suspected. In-sample rankings (elastic_net best) invert out of fold (worst): the ML methods overfit. Recorded in `v4_calibration.json` (`evaluation: out_of_fold`, `fold_definition`, both tables, `decision`), with the OOF series in `data/v4_oof_predictions.csv`. This is direct context for C3: the regime layer's case cannot rest on the calibrated probability's calibration.

**B2.3:** the suite now warns (MEDIUM, `v4:calibration_evaluation`) when a calibration file lacks `evaluation: out_of_fold` with a fold definition.

## B3 — Cross-repository blocking decoupled

`audit_status.py --scope tournament|screener`: a CRITICAL restores/blocks only when its label belongs to that repository (`screener:*`, `governance:visibility`, `governance:review_overdue` → screener; everything else → tournament). `xfile:*` findings are reported in both status strips and block neither; the other repository's CRITICALs are shown, not enforced. A tournament defect can no longer take the screener offline.

## B4 — Workflow wiring, by name

| repository | workflow file | job | post-publish stages present |
|---|---|---|---|
| portfolio-tournament | `.github/workflows/daily_update.yml` | `update` | Run daily pipeline → **Nightly audit sweep** (`audit_nightly.py` + `audit_status.py --scope tournament`) → Commit (`data/`, `reports/audit_last.txt`) → Propagate failure; separate `deploy` job (`if: always()`, serialized `pages-deploy`) |
| portfolio-screener | `.github/workflows/rescore.yml` | `score` | Run scoring model → **Nightly audit sweep** (clones tournament; `--scope screener`) → Commit results → Propagate failure; separate `deploy` job |

Restore-last-good: tournament — `update_daily` on validation rejection (`git checkout -- data/` + `clean`) and `audit_status` on a scoped CRITICAL; screener — `build_json` validates before writing anything, `audit_status` on a scoped CRITICAL. Status write: `status.json` on success and rejection in both, with the check names.

## Deviations

1. B1 backfill labels all rows with the current model (see B1); prior-version archive added instead.
2. B1.2 note carries out-of-fold figures, not the order's in-sample 0.1835/0.1918 pair (0.1918 is the base rate, not logistic's Brier).
3. A1: memory_semis not applied (structural; invariant breach); 21/22 applied.
4. `index.html` is shared by A1/B1/B3 and was committed once, labelled.

## C — status

C1 (transaction costs) starts next: recon of `backtest.py` and `compute_nav.py` is in hand. C3's registration is understood to be frozen as written in the order; nothing in it will be touched, and its results file will restate it with an empty diff. C4 remains deferred to C3's outcome.

## Appendix A — `reports/audit_before_AB.txt` (verbatim)

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

## Appendix B — `reports/audit_after_AB.txt` (verbatim)

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
