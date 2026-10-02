# Entry-state validation — registration v2 (registered, NOT run)

Registered 2 October 2026. It **supersedes** `reports/entry_state_validation_registration_2026-10-02.md` (v1). Machine-readable parameters: `data/entry_state_validation_registration_v2.json`, which records v1's sha256 and the reason.

**Why a second registration.** The order asks for a date-block bootstrap "with blocks by entry month, paired on common names". v1 implemented that as pairing on common (entry month, ticker) cells. The v1 power check (`reports/entry_state_power_check_2026-10-02.md`) showed that this conditions on the future. A later entry in the same month implies a pullback after the month-start baseline entry, so the paired baseline was the set that went on to fall: median early loss 5.32% against 2.30% in the other cells. Under v1 any contestant that enters after an intra-month pullback, READY included, would look better by construction. v1's READY stage was therefore never run, and the script now refuses it.

**What was seen before this registration was written.** The v1 power-check output: entry counts, the unconditional distributions of SETUP-ONLY and BASELINE, and the v1 paired statistics. Also the READY entry count (16,949). No READY return, excursion or stop-out figure has been computed for a report or seen.

## What is unchanged from v1

The question, the frozen 534-name universe (survivorship stated), the window (history from 2 January 2009, entries from 4 January 2010), prices and point-in-time states, the frozen rules (sha256 `0f438215…`), the C1 costs (10 bps one way on entry and exit), execution (signal at the close of *t*, entry at the open of *t*+1, exit at the close of *t*+*h*), the three contestants, the 20-session de-overlap, the metrics (X20, X60, MAE20, STOP20), 10,000 resamples, seed 20261002, 90 percent percentile intervals, the decision rule and the power thresholds. The v1 price fetch is reused, with its sha256 recorded in every result.

## What changes: the comparison

- **Common names.** Each comparison uses only the tickers that have at least one entry in both contestants over the window. Every entry of those tickers counts. No entry is matched to another, so nothing about one contestant's later entries selects the other's.
- **ΔMAE** = the median MAE20 over the contestant's entries minus the median over BASELINE's entries. **ΔX60** = the mean X60 over the contestant's entries minus BASELINE's mean. Reported beside them: the difference of median X60, ΔX20 (mean) and ΔSTOP20 (mean).
- **The bootstrap is paired at the resample level.** The distinct entry months of the two contestants are resampled with replacement, and each drawn month brings every entry of both contestants in that month. Both are measured on the same resampled history, which keeps market-wide months shared between them.

## The decision rule (unchanged)

READY passes if the 90 percent interval of ΔMAE lies entirely below zero and the lower bound of the 90 percent interval of ΔX60 is at least −1.0 point; otherwise it fails. The power check comes first, on SETUP-ONLY against BASELINE with this construction. The rule has power if the ΔMAE half-width is at most 0.25 point and the ΔX60 half-width at most 1.0 point. Without power the verdict is NO VERDICT and READY is reported descriptively. The badge stays DIAGNOSTIC on FAIL and on NO VERDICT; on PASS the operator decides.

## Expected result, stated in advance

- **READY against BASELINE: fail.** READY entries follow a pullback and a one-session turn. Volatility clusters, so the excursion over the next 20 sessions should be about the same as or larger than at a month-start entry. Expected ΔMAE between 0 and +0.5 point, its interval not entirely below zero, so the first condition fails. Expected ΔX60 within ±1 point, so the second holds.
- **SETUP-ONLY against BASELINE:** ΔMAE about +0.15 point, the unconditional difference already visible in the v1 output. Its interval may include zero. Whether the half-widths meet the power thresholds is uncertain. The two contestants' entries now fall in different months (setups cluster in sell-offs), and that widens a difference of medians under month resampling.

## Artifacts

`scripts/entry_state_validation.py --registration data/entry_state_validation_registration_v2.json` (`--stage power`, then `--stage ready`); `data/entry_state_power_check_v2.json`; `data/entry_state_validation.json`; `reports/entry_state_validation_2026-10-02.md`. A stage whose result is already committed for this registration is refused: a rerun needs a new registration.

## Do-not-touch

Everything above, once a run begins.
