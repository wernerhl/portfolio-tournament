# C6 registration — banded-continuous selection against monthly reconstitution (registered, NOT run)

Registered 30 September 2026 under the Tournament Audit and Execution Order (section 4.2): *"Before either version is preferred, run the C-series comparison on the full backtest history with the C1 cost model and point-in-time inputs: contestants monthly and banded-continuous per tier; metrics return per unit of volatility, drawdown reduction, turnover, and cost drag; paired block bootstrap on common resamples; decision rule registered in advance and applied first to the two monthly tiers against each other to confirm it can discriminate. The live twins supply out-of-sample evidence as it accrues; the backtest supplies the sample size."* Acceptance 7.5: *"The C-series comparison registered, with the discriminating-power check on monthly-versus-monthly reported before the real comparison runs."*

**Status: registration and the power check only. The real comparison has not run; the banded-continuous backtest engine is not built. The monthly tiers are not replaced by the twins before a rule with demonstrated power judges them.** Nothing below changes once a run begins; a change requires a new registration with a stated reason and both results reported.

## A. Contestants

Per algorithmic tier (1_cap_pres, 2_balanced, 3_aggressive, 4_tactical): the monthly-reconstitution tier as published in the backtest (control) and its banded-continuous twin (challenger) — identical universe, scores, cash targets and cost model, differing only in the execution rule of section 4.1: daily evaluation; entry within the top K into an open slot or by displacing the weakest holding by a score margin δ = 2.0 tier-composite points; exit only when the rank falls below 2K; regime cash executed when the gap exceeds 5 points (the corrected corridor label); resizing when a weight drifts beyond 25 percent of target (`data/tournament/continuous_rules.json`). No other exit rule; the Trade-Now stops do not trade.

## B. Inputs and window

The full backtest history (`data/backtest_equity_curves.csv`, 2010-02-01 → 2026-05-21, net of the C1 cost model: 3 bps half-spread + 7 bps impact, one-way, on NAV-weight turnover) for the controls; the challengers require the same engine run daily with point-in-time scores — the scores' history is not archived before 2026 (`data/scored_universe.csv` is overwritten nightly and committed; the point-in-time series exists only from the nightly commits), so the backtest of the challengers must be rebuilt from the same inputs as `backtest.py` with the continuous rule inside its loop. Costs identical. Turnover and cost drag reported per contestant.

## C. Metrics and the bootstrap

Return per unit of volatility (annualized mean over annualized standard deviation of daily returns), maximum drawdown, one-way turnover per year, cost drag on annualized return. Paired block bootstrap on common resamples of the daily returns: 1000 resamples, 60-session blocks, seed 20260930, the same block indices for every contestant in a pair (as in C3).

## D. The decision rule, registered in advance

R1 (interval): the challenger is preferred when the 90 percent paired interval of the difference in return per unit of volatility lies above zero, the paired interval of the difference in maximum drawdown does not lie below zero (the challenger does not draw down more), and its turnover is under three times the control's.

Two alternatives are registered beside it, to be tried in this order only if R1 fails the power check: R2 (probability): the paired-resample probability that the difference in return per unit of volatility is positive is at least 0.80, drawdown not worse, turnover under three times; R3 (composite): R2, or the 90 percent interval of the drawdown difference above zero (a shallower drawdown) with the probability of a positive return-per-volatility difference at least 0.50, turnover under three times.

Power threshold, registered: a rule has power if it tells the two contestants of a pair of DIFFERENT monthly tiers apart (in either direction) in at least three of the six pairs on their own backtests. A rule without power judges no twin.

## E. The discriminating-power check, monthly against monthly (run 30 September 2026)

`scripts/c6_power_check.py` → `data/tournament/c6_power_check.json`, 4,097 sessions:

| pair | Δ return/vol, 90% | P(a > b) | Δ max drawdown, 90% | R1 | R2 | R3 |
|---|---|---|---|---|---|---|
| 1_cap_pres · 2_balanced | [−0.358, +0.179] | 0.27 | [+0.012, +0.135] | no | no | no |
| 1_cap_pres · 3_aggressive | [−0.542, +0.044] | 0.09 | [+0.048, +0.204] | no | no | no |
| 1_cap_pres · 4_tactical | [−0.604, +0.018] | 0.06 | [+0.020, +0.130] | no | no | no |
| 2_balanced · 3_aggressive | [−0.325, +0.016] | 0.07 | [−0.000, +0.107] | no | yes | yes |
| 2_balanced · 4_tactical | [−0.403, +0.005] | 0.05 | [−0.053, +0.052] | no | yes | yes |
| 3_aggressive · 4_tactical | [−0.240, +0.140] | 0.32 | [−0.125, +0.013] | no | no | no |

Power: R1 0 of 6, R2 2 of 6, R3 2 of 6. **No candidate reaches the registered threshold.** The registered rule lacks power on the controls and must not judge the twins; the same failure mode as ledger Failure 14 (a rule no contestant could satisfy), caught here before the comparison instead of after. The monthly tiers differ only in universe filter, factor weights and cash formula, and their sixteen-year return-per-volatility differences are within a paired 90 percent interval that spans zero in every pair; the drawdown differences separate the capital-preservation tier from the three others.

## F. Consequence and next registration

1. The real comparison does not run under R1, R2 or R3. The twins run live from 30 September 2026 as a contest, logged; they replace nothing.
2. A new registration is required before any comparison: a rule with power on the controls. Candidates to register (not chosen here): a drawdown-first rule (the drawdown interval above zero with turnover under three times, which separates 1_cap_pres from each other tier), or a longer block (120 sessions) with the probability threshold at 0.75. Whichever is registered next is checked for power on the same six pairs first, with the same seed, and both results reported.
3. Until then the tournament page shows the twins beside their parents with the power check's verdict; no "preferred" label appears anywhere.

## G. Do-not-touch

The registered rules, thresholds, seed and block length above; the C1 cost model; the as-published backtest curves.
