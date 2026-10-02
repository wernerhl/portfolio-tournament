# Entry-state validation — the discriminating-power check (registration v1), run 2 October 2026

Run under `reports/entry_state_validation_registration_2026-10-02.md` (v1, commit fc8ece3), script `scripts/entry_state_validation.py --stage power` (commit fd48e7a). Result file: `data/entry_state_power_check.json`, committed as produced.

**Summary: by its registered criterion the v1 rule has power, but the result shows its pairing looks into the future. The v1 READY comparison is therefore not run. A v2 registration, closer to the order's wording, replaces it and is committed before any v2 run.**

## Inputs

- Prices: 531 of the 535 registered tickers (the 534-name universe plus SPY) returned history, 2 January 2009 to 1 October 2026; BK, CFLT, PSTG and SATS returned none. File `scratch/entry_validation/ohlc.parquet` (git-ignored), sha256 `fbe21a4b…`, fetched 2 October 2026.
- Entries (after the 20-session de-overlap, from 4 January 2010): BASELINE 47,812; SETUP-ONLY 30,334; READY 16,949 (counted only; no READY metric was computed for a report or looked at).

## Result on the registered rule (SETUP-ONLY against BASELINE, 24,279 common cells, 201 months)

| statistic | point | 90% interval | half-width | power threshold |
|---|---|---|---|---|
| ΔMAE (median early loss) | −1.46 pt | [−1.69, −1.21] | 0.24 pt | ≤ 0.25 pt ✔ |
| ΔX60 (mean 60-session excess) | +2.27 pt | [+2.01, +2.53] | 0.26 pt | ≤ 1.0 pt ✔ |
| ΔX20 (mean) | +2.37 pt | [+2.11, +2.62] | | |
| ΔSTOP20 (stopped-out share) | +10.3 pt | [+8.6, +12.0] | | |

By the registered criterion the rule **has power**, and on this pair it would read SETUP-ONLY as passing: a smaller early loss and a better 60-session return than the baseline. The expected result, stated in advance, was the opposite (SETUP-ONLY with the larger early loss).

## Why the result runs the wrong way: the pairing conditions on the future

v1 paired the contestants on common (entry month, ticker) cells. The BASELINE entry is at the open of the month's first session; a SETUP-ONLY (or READY) entry in the same cell comes later in that month, a median of **10 business days** after the baseline entry (on the same day in 1,267 of 24,358 cases). A setup can only appear after a pullback, so restricting the baseline to cells with a later setup selects exactly the baseline entries that were followed by a decline:

| BASELINE entries | n | median MAE20 | mean X60 | stopped-out share |
|---|---|---|---|---|
| in cells with a later setup entry (the v1 paired set) | 24,279 | 5.32% | −1.62% | 20.7% |
| in cells without one | 23,533 | 2.30% | +2.80% | 21.3% |

The v1 comparison therefore favours any contestant that enters after an intra-month pullback, and READY is such a contestant (its trigger follows a setup). A READY "pass" under v1 would be an artifact of the pairing, and the referee's `entry:diagnostic_gate` would accept it. Same course as the C6 precedent (30 September): **the real comparison does not run under a rule the power check has shown to be unfit.** The flaw is in the lead's translation of the order's "paired on common names" into common month-ticker cells. It is logged in the mistakes ledger.

## Unconditional distributions (every entry, not only the paired cells)

| | entries | X20 mean | X20 p5 / p50 / p95 | X60 mean | X60 p5 / p50 / p95 | MAE20 p25 / p50 / p75 / p95 | stopped |
|---|---|---|---|---|---|---|---|
| BASELINE | 47,812 | +0.04% | −10.5 / −0.2 / +10.9% | +0.55% | −18.2 / −0.1 / +20.1% | 1.7 / 3.8 / 7.3 / 15.2% | 21.0% |
| SETUP-ONLY | 30,334 | +0.22% | −10.7 / −0.1 / +11.7% | +0.79% | −18.4 / +0.0 / +21.0% | 1.7 / 3.9 / 7.4 / 16.6% | 31.7% |

Without the conditioning, SETUP-ONLY carries a slightly larger early loss (median +0.15 point, 95th percentile +1.4 points) and a much higher stopped-out share than the baseline, in the direction the registration expected. These figures were seen before v2 was written, and the v2 registration says so; no READY figure was seen.

## Consequence

1. v1 stands as committed. Its READY stage does not run, and the script refuses it once a later registration supersedes v1.
2. v2 (`reports/entry_state_validation_registration_v2_2026-10-02.md`) uses the order's wording: both contestants restricted to their common names, every entry counted, the months resampled jointly for both contestants, and no pairing on cells. It is committed before any v2 run, and its power check runs first.
