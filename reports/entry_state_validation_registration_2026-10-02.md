# Entry-state validation — registration (registered, NOT run)

Registered 2 October 2026 under the Execution Order: Entry-State Indicator, section 3: *"Registered before any run; the badge reads DIAGNOSTIC until it reports."* Acceptance 5: *"The validation registration is committed before any run, with the discriminating-power check reported first."*

**Status: registration only. No validation run, no power check and no historical price fetch for it has happened.** The machine-readable parameters are frozen in `data/entry_state_validation_registration.json`; the run script reads them from there and records the file's sha256 next to its results. Nothing below changes once a run begins; a change requires a new registration with a stated reason, and both results are reported.

## A. The question

Does entering when the state machine reads READY reduce the loss a position suffers in its first 20 sessions, compared with entering trend-passing names on a fixed monthly schedule, without giving up more than one percentage point of 60-session return?

## B. Universe, window, prices

- **Universe:** the union universe of 2 October 2026 (`data/universe.txt` at commit 7cc7e4c), 534 names, frozen as a list in the parameter file (sha256 of the sorted list `fca5420e…`). **Limitation, stated in advance:** survivorship. Only today's members are in it; names that were delisted or acquired before today are absent. That raises the level of every contestant's returns alike; the paired comparison is less exposed to it than the levels, but not immune.
- **Window:** daily history from 2 January 2009 (the trend gate needs 253 sessions), entries from 4 January 2010 to the last completed session at run time, less the horizon for each metric.
- **Prices:** daily OHLC from the same provider the live indicator uses (yfinance, `auto_adjust=False`). Split-adjusted open, high, low and close drive the states, as charted live; every indicator is a ratio or a difference of same-scale prices, so the split adjustment does not change any state. Returns and excursions use dividend-adjusted prices (open and low scaled by the day's adjusted-to-raw close ratio). Each state uses only data through its own session.
- **Rules:** exactly the frozen `data/entry_state_config.json` (sha256 `0f438215…`), applied by `scripts/entry_state.py`'s `indicators()` and `evaluate()`.

## C. Contestants

1. **READY:** every session graded READY or READY-HALF (the trigger sessions). The event gate changes the size, not whether there is an entry, so both count.
2. **SETUP-ONLY:** the first session of each WATCH spell (setup present, no trigger).
3. **BASELINE:** every name that passes the trend gate at the close of a month's last session, entered at the open of the next month's first session.

A name enters a contestant at most once in any 20 sessions (later signals inside that window are skipped).

## D. Execution and costs

The state is read at the close of session *t*; the entry is at the open of *t*+1; a horizon of *h* sessions exits at the close of *t*+*h*. Costs: the C1 model, 3 bps half-spread plus 7 bps impact, 10 bps one way, charged on the entry and on the exit of the name; the SPY benchmark is costless.

## E. Metrics

- **X20, X60:** the name's total return from the entry open to the close at 20 and 60 sessions, less SPY's over the same sessions, less 20 bps.
- **MAE20:** the maximum adverse excursion before 20 sessions: the largest drop from the entry open to any adjusted low in sessions *t*+1 … *t*+20, as a positive number (zero if the price never trades below the entry).
- **STOP20:** whether any close in those 20 sessions falls below the stop of session *t* (for READY the armed stop; for the others the stop formula at *t*). The share of entries stopped out is its mean.

## F. Pairing and the bootstrap

A **cell** is a (calendar month of the entry, ticker). A cell is common to two contestants when both have an entry in it; a contestant's value in the cell is the mean over its entries there. Cells lacking a metric's forward window are dropped from that metric only.

- **ΔMAE** = median MAE20 over the common cells for the contestant, minus the same median for BASELINE (negative = the contestant loses less early).
- **ΔX60** = mean over the common cells of X60(contestant) − X60(BASELINE). The median difference, ΔX20 and ΔSTOP20 are reported beside it.

Date-block bootstrap with blocks by entry month: the distinct entry months are resampled with replacement, each drawn month bringing all of its common cells; 10,000 resamples; seed 20261002; 90 percent percentile intervals (5th to 95th).

## G. The decision rule, registered in advance

**READY passes** if the 90 percent interval of ΔMAE lies entirely below zero **and** the lower bound of the 90 percent interval of ΔX60 is at least −1.0 percentage point. Otherwise it **fails**.

## H. The discriminating-power check (run and reported first)

Before READY is evaluated, the same construction, seed and rule are applied to **SETUP-ONLY against BASELINE**. The rule is declared to have power if the ΔMAE interval's half-width is at most 0.25 percentage points **and** the ΔX60 interval's half-width is at most 1.0 point: at that resolution a half-point difference in the median early loss, and the one-point tolerance on the 60-session return, can both be detected. The rule's outcome on that pair (whether its ΔMAE interval excludes zero, and in which direction) is reported beside it.

If the rule lacks power, READY is still computed and its full distributions reported, but the verdict is **NO VERDICT (rule lacks power)** and a new registration is required before anything judges the state machine.

## I. What is reported

Pass or fail (or no verdict) with both intervals; the power check first; for each contestant the number of entries and of common cells and the 5th, 10th, 25th, 50th, 75th, 90th and 95th percentiles of X20, X60 and MAE20, and the stopped-out share; the same by calendar year; the bootstrap distributions of each Δ (percentiles). Artifacts: `scripts/entry_state_validation.py`, `data/entry_state_power_check.json`, `data/entry_state_validation.json`, `reports/entry_state_validation_2026-10-02.md`. The price history is fetched into the git-ignored `scratch/entry_validation/`, with its sha256 and fetch time recorded in the result.

## J. Consequence for the label

The badge stays DIAGNOSTIC on a fail and on no verdict. On a pass the operator decides whether to lift it. The referee's `entry:diagnostic_gate` is CRITICAL if any other label appears while `data/entry_state_validation.json` does not read PASS.

## K. Expected result, stated in advance

- **READY against BASELINE: fail.** READY entries come after a pullback, when a name's recent volatility is above its norm; volatility clusters, so the excursion over the next 20 sessions should be about the same as, or larger than, at a month-start entry. Expected ΔMAE between −0.3 and +0.8 percentage points, with an interval that includes zero (the first condition fails); expected ΔX60 within ±1 point (the second condition holds).
- **SETUP-ONLY against BASELINE:** a larger early excursion for SETUP-ONLY (it enters a decline before the decline turns): ΔMAE positive with its interval above zero. The rule resolves this pair, and the power check passes on sample size (several thousand common cells over about 190 months).

## L. Do-not-touch

The rules, contestants, metrics, pairing, seed, resample count, interval, thresholds and expected result above; the frozen universe list; the C1 cost model.
