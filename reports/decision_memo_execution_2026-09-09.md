# Execution report — Decision Memo of 9 September 2026 (the Retirement Tests)

Executed 2026-09-09 against the memo's order (section 10, items 1–8). One item is blocked (7: no textbook on this machine), one is pending an external event (6: subscriptions), one carries a corrected premise (5: BMNR is not held; the 16% is partial-weight remainder). Nothing served was altered by hand: the dashboard and the registry change take effect with the next successful nightly, which also clears the Labor-Day status.

## 1. Item-by-item

| # | order | status | commit |
|---|---|---|---|
| 1 | Registration v2 with §2 verbatim, v1 verdict retained, amendment paragraph; C3 report regenerated with both verdicts and the four context lines | **done.** `reports/c3_registration_v2.md` (§A v1 verdict verbatim, §B memo §2 verbatim, §C amendment paragraph verbatim). `decision_v2` evaluated on the same run and resamples; the v1 output block is byte-identical before and after (diff empty). v2 verdict: paired interval [+0.017, +0.318] above zero, drawdown reduction 63.9% vs 29.7% → **pass**; v1 verdict **fail** retained. Report `reports/retirement_test_C3_regime_vs_rules.md` carries both verdicts, the amendment paragraph, the four context lines, both registrations verbatim and both mechanical diffs (empty). | 0f8ca92 |
| 2 | v4: out of the headline aggregation; ranking-panel note; out-of-fold Brier and base rate displayed; in-sample reliability diagram removed; model-version stamping as ordered | **done.** `headlineVerdict()` no longer takes v4's vote (the headline is the regime index; its inputs line shows "v4 … (ranking only, not voting)"); the cycle-position card is titled "regime index" and shows R_full, with the v4 probabilities in their own row; a standing note beside them reads the out-of-fold Brier and the base rate from `v4_calibration.json` (0.1989 vs 0.1918) with the ordered sentence "does not beat the base rate out of fold; use as a ranking, not a forecast". **No in-sample reliability diagram existed on the dashboard** (`v4_calibration.json` was loaded but never rendered); the note states why none is shown. Model-version stamping was done under B1 and is unchanged. | 675aac4 |
| 3 | Backtest panel: revised-inputs disclosure with the point-in-time figure beside it | **done, with one precision.** The leaderboard header now carries "backtest history on revised inputs · point-in-time drawdown reduction 36% vs 52% revised (C2)" and each tier's MAX DD cell shows the C2 pair (PIT vs revised) with a hover explanation. The precision: the served tier sizing uses the internal 12-indicator vol index, which has no FRED inputs, so the displayed max drawdown is not itself a revised-input number; the C2 pair is the 24-indicator overlay through the same engine (tier 4: 52.2% → 35.8%). The disclosure says this. | 675aac4 |
| 4 | Register C5 as a document only; do not run | **done, not run.** `reports/c5_registration.md`: combination fixed as the product e = e_regime × e_vol (no other form, to avoid multiplicity); passes only if the paired criterion holds against **each** of regime-alone and vol-targeting-alone (four conditions); post-hoc provenance registered; point-in-time regime input reported beside. | 97064f1 |
| 5 | `speculative_crypto` bucket; provisional workflow continues | **done, premise corrected.** Registry v3: `speculative_crypto` {BMNR: 1.0}, approval instrument the memo, v2 recorded in history, BMNR's v3-queue entry resolved, memory_semis deferred to its own registration after C4. Engine validation run: the basket computes (1 member priced); served outputs restored, the nightly publishes it. **Correction:** BMNR is not held in 5_werner today (positions: MSFT, NVDA, AVGO, GOOG, TSM, ETN, VRT, CEG). The tier's 16.3% "unclassified" is exactly the sum of partial-membership remainders (MSFT and GOOG at 0.7, ETN and CEG at 0.6, VRT at 0.8); `unclassified_names` is empty. The bucket is forward-looking and correct; the referee's coverage finding will persist because the coverage rule counts partial remainders. That is a policy question (section 4). The provisional workflow is untouched. | 30972b1 |
| 6 | C4: on receipt of the subscriptions, rebuild the point-in-time universe, re-run the fundamental sleeve per the practice review's item 3.1, report the information ratio with its interval | **pending receipt.** Nothing to run until the Sharadar/Norgate access exists. Plan on receipt: point-in-time fundamentals snapshot store keyed by report date, universe rebuilt as of each rebalance, sleeve re-run through the C1-costed engine, information ratio with block-bootstrap interval, both vintages reported (current-vintage null as the sensitivity). | — |
| 7 | Textbook: ledger entries 13 and 14, the Failure 10 supplement, the deflated abstract sentence into the preface and the regime chapter | **blocked: no textbook on this machine.** Spotlight and a recursive search of `~/Documents` for "Failure 10", "Failure 11", "textbook", "preface", "regime chapter" return nothing; `_paper/` holds only the May architecture note and the June regime-v3 draft. The entries and the abstract sentence are delivered verbatim, ready to paste, in `reports/ledger_entries_2026-09-09.md`. Give me the textbook's path (or repository) and I will place them. | d560236 |
| 8 | Referee before and after, verbatim | **done** (section 3). 16 findings, 0 CRITICAL, finding lines identical before and after. | — |

## 2. Verification

- Dashboard JavaScript parses (`node --check` on the inline script, 146 kB).
- Rendered locally from the repository (`python -m http.server`): the v4 standing note, the C3 verdict line (v1 FAIL / v2 PASS, amendment disclosed) on the regime card, and the C2 disclosure in the leaderboard header are all present in the DOM and visible; the only failed requests are the four local font files, pre-existing and unrelated.
- The local snapshot shows v4 as "stale (as of 2026-09-04)", correctly, because the last nightly to publish was 4 September; the live site clears with tonight's run.
- Served files in this batch: `data/thesis_registry.json` (by written order) and `index.html`. No as-published value, vintage file or thesis output was edited by hand.

## 3. Referee before / after (verbatim, `scripts/audit_nightly.py`)

Before (`reports/audit_before_memo.txt`):

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

After (`reports/audit_after_memo.txt`):

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

The `status:opaque` MEDIUM is the served Labor-Day status (pre-remediation code) and clears with the next successful nightly; the validator fix that prevents its recurrence is 6ae6c73. The `governance:coverage` HIGH is the partial-remainder question of item 5.

## 4. Decisions for Werner (nothing applied)

1. **Coverage rule and partial weights.** The referee flags 5_werner at 16% unclassified because partial memberships (a hyperscaler at 0.7) leave 0.3 uncovered by construction. Options: (a) keep the rule and accept the standing HIGH for tiers built from partial members; (b) count only zero-assignment names toward the >15% test and report the partial remainder separately; (c) raise the threshold for tiers whose remainder is entirely partial-weight. This is registry policy; I have not changed the rule.
2. **Textbook location** for item 7.
3. **C5**: run when told; nothing else changes until then.
4. **C4**: tell me when the subscriptions are active.
