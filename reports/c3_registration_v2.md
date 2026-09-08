# C3 registration v2 — amended 9 September 2026 (one change only)

This document amends `reports/c3_registration.md` (v1, committed c39e2aa before any run). It is issued by the Decision Memo of 9 September 2026 after the v1 result was known. **The v1 verdict stays on record and is never removed from the paper, the dashboard, or the ledger; the amendment paragraph in section C travels with the v2 verdict everywhere it appears.**

## A. The v1 verdict of record (retained verbatim from `reports/retirement_test_C3_regime_vs_rules.md`)

> **The regime index fails the registered rule.** On tier 4 (the pure overlay: cash 0–100%, SPY, monthly, net of 10 bps one-way), over 2010-02-01 → 2026-05-21:
>
> | | regime index | best one-line rule (10% vol targeting) | condition |
> |---|---|---|---|
> | after-cost return per unit of volatility | 0.993 | 0.822 | margin +0.171 must exceed the half-width of the regime's own 90% interval, 0.411 → **not met** |
> | drawdown reduction vs buy-and-hold | 63.9% | 29.7% | regime ≥ rule → **met** |

## B. Registration v2 (Decision Memo, section 2, verbatim)

> All of v1 stands except condition 1, which is replaced as follows. Condition 1: the 90 percent interval of the paired bootstrap difference (regime minus best rule, same resampled paths as v1's B10) in after-cost return per unit of volatility lies entirely above zero. Condition 2 unchanged: drawdown reduction of the regime is at least that of the best rule, point estimates. Consequence unchanged. Window, contestants, metrics, bootstrap, seed, cost model unchanged. Reason for amendment: v1's statistic admitted no passing contestant on this window and confounded strategy differences with shared market-path variance; the paired difference is the correct comparison and was already registered as a reported quantity.
>
> Verdict under v2, decision window (tier 4, 2010-02-01 to 2026-05-21, revised inputs, net of costs): condition 1 met, paired interval [+0.017, +0.318]; condition 2 met. Pass.
>
> Context, reported alongside and binding on what may be claimed:
> Point-in-time inputs (C2's strict series): paired return-per-volatility interval [+0.006, +0.201], lower bound at zero for practical purposes; drawdown reduction 51.6 percent against 29.7. On real-time information the regime's drawdown advantage is intact and its return-per-volatility advantage is not distinguishable from nothing.
> Crisis-inclusive window (2005-01-03 to 2026-09-04): drawdown reduction 63.7 percent against vol targeting's 57.0; paired return-per-volatility intervals against the moving-average and momentum rules include zero, against vol targeting [+0.007, +0.282]. In 2008, a one-line volatility-targeting rule captured most of the protection the regime layer provides.
> Cost of the overlay: annualized return 7.92 percent against buy-and-hold's 14.52 over the decision window. The regime overlay is insurance with a substantial premium; its value is the ratio and the drawdowns, not the level of return.
> Tier 3: the moving-average rule's drawdown reduction exceeds the regime's (33.1 against 27.9). The regime does not dominate in every operating range.

## C. The amendment paragraph (Decision Memo, section 1, verbatim; travels with the v2 verdict)

> The rule was defective, and the defect is objective rather than a matter of taste. Condition 1 compared a point-estimate margin to the half-width of the regime's own marginal bootstrap interval. That half-width (0.411) is dominated by market-path uncertainty shared by every contestant, because all of them hold the same index most of the time. The report shows no monthly overlay on this window could clear it: the rules' own half-widths are 0.44 to 0.45, larger than any plausible margin between two overlays. A test that no contestant can pass has no discriminating power. The correct statistic for comparing two strategies on one history is the paired difference, computed on the same resampled paths, which cancels the shared variance. The registration itself required the paired difference to be reported, as context.
>
> The asymmetry must be stated: had the regime passed under v1, this defect would not have been examined. The amendment is prompted by the result. That is exactly the situation the amendment clause exists for, and it is honest only if the v1 verdict stays on record and this paragraph travels with the v2 verdict everywhere it appears.

## D. Mechanics

`scripts/c3_regime_vs_rules.py` evaluates both rules on the same run: `decision` (v1, unchanged code path) and `decision_v2` (paired 90% interval of return-per-volatility, regime minus best rule, lower bound > 0; drawdown-reduction condition unchanged). The best rule is the same object in both (highest point-estimate return-per-volatility among the three rules). Bootstrap resamples, seed, block length, window, costs and contestants are those of v1; the v1 output is byte-identical before and after the addition of the v2 evaluation, and the results report shows that check.
