# Entry-state validation, rules version 3: registration (registered, NOT run)

Registered 6 October 2026 under the revised Execution Order: Revision of the Entry-State Indicator and Related Fixes, section 7: *"Register before any run. Universe: point-in-time constituents of the S&P 500 from the purchased survivorship-free data (Sharadar or Norgate), 2005 to present, including delisted names."* Machine-readable parameters: `data/entry_state_validation_registration_v4.json`.

**Status: registration only. Nothing can run yet.** The survivorship-free data has not been received; the Sharadar/Norgate access is still pending receipt. The run script is written when the data arrives, against these parameters. Nothing below changes once a run begins; a change needs a new registration with a stated reason, and both results are reported.

**This registration supersedes the one made this morning** (`reports/entry_state_validation_registration_2026-10-06.md`, version 2 of the rules). That one never ran. The order was revised the same day, before any run:
- the WAIT state was removed;
- short interest of 20% or more of the float became a heavily-shorted trigger;
- contestant (d), all overbought events, was added.

The superseded file is left unedited. The version-2 configuration it pinned (sha256 `4aa58cc4…`) is kept byte-identical at `data/entry_state_config_2026-10-06_v2.json`.

**What was seen before this registration.**
- The order's two section 1 tables: about 80 large companies, 2011–2026, with 4,540 oversold and 6,593 overbought events.
- The 5-October states of the reference names (LMT, MU, POWL, INCY, TPL, ONDS).

The expected result below is informed by both, and says so.

## A. Universe and data

- **Universe:** point-in-time S&P 500 constituents on each event date, from the purchased survivorship-free data. That is Sharadar SEP and its S&P 500 membership table, or Norgate with its historical index constituents. Names that later left the index or were delisted are included.
- **Window:** events from 3 January 2005 to the last session whose 120-session outcome is complete. History from 2004 feeds the 200-day and 12-month inputs.
- **Prices:** split-adjusted OHLC for every state input, as charted; total-return closes for outcomes.
- **Benchmark:** SPY's total return. "Beating the index" means a positive excess return.

## B. Events and outcomes (as in the order's section 1, plus 120 sessions)

- **Oversold event:** a session on which the stock's RSI(14) (simple-average, Cutler) closes below 30.
- **Overbought event:** a session on which it closes above 70.
- **Spacing:** events of the same type for the same stock are at least 20 sessions apart.
- **Entry:** the event session's close. The next session's open is reported as a sensitivity. Costs follow the C1 model: 10 bps one way on entry and on exit.
- **Outcomes at 60 and 120 sessions:** the excess return over SPY net of costs; whether it beats the index; and the drawdown in the first 20 sessions (the lowest close in sessions 1–20 against the entry, as a loss), reported as a median.

## C. Contestants

- **(a) The revised rules (version 3, `data/entry_state_config.json`, sha256 `962fe81c…`; module `scripts/entry_state.py`, sha256 `286c0f90…`).** Applied at the event close, separately for each event type:
  - **(a1)** the oversold events at which the version-3 machine reads READY or READY-HALF;
  - **(a2)** the overbought events at which it does.

  The machine reads READY or READY-HALF when three conditions hold:
  - the trend gate is not failed (not both below the 200-day and with negative 12-1 momentum);
  - no long-term ceiling caps the state, judged from the yearly closing highs available up to the event date;
  - the size modifiers stay at or above a quarter.

  Point-in-time limits:
  - The heavily-shorted modifier is **not applied**. Neither days-to-cover nor short interest as a share of the float exists point-in-time in either data set.
  - The earnings modifier is applied only if the purchased data carries report dates.

  Both omissions can only make more events READY than the live rule would; they are reported.
- **(b) The 2-October rules (version 1, frozen in `scripts/entry_state_v1.py`, configuration sha256 `0f438215…`).** From each oversold event, the first session within 10 sessions on which the version-1 machine reads READY: trend gate, setup and trigger. The outcome is measured from that session's close.
- **(c) All oversold events.**
- **(d) All overbought events.**

## D. Comparisons and statistics

- **Primary:** (a1)−(c). Does the version-3 gate improve oversold entries?
- **Secondary:**
  - (a2)−(d), the same gate on overbought entries;
  - **(c)−(d), buying pullbacks against buying strength**, which is the basis for removing WAIT;
  - (b)−(c) and (a1)−(b), the 2-October rules.
- **Descriptive subgroups** (as in the order's second table):
  - overbought with positive 12-month momentum, within 5% of the 52-week high;
  - oversold with positive 12-month momentum.

For each contestant and horizon, five statistics are reported, along with every difference above:
- the mean and the median excess return;
- the share beating the index;
- the worst 10% (the 10th percentile of the excess return);
- the median 20-session drawdown.

Intervals come from a date-block bootstrap clustered by month. The distinct event months are resampled with replacement, and each drawn month brings all its events from every contestant and both event types. There are 10,000 resamples, seed 20261006, and the intervals are 90 percent percentile intervals.

## E. The discriminating-power check (run and reported first)

(c) is split at random into two halves by event (seed 20261006), and the same statistics and bootstrap compare the halves. **The check passes** if the 90 percent interval of every difference (five statistics, two horizons) includes zero. The half-widths are reported as the method's resolution. If the check fails, the real comparison is reported as descriptive only, and a new registration is needed.

## F. Decision rule, registered in advance

**(a) is supported** only when all three hold:
1. the power check passes;
2. the 90 percent interval of (a1)−(c) in mean 60-session excess lies entirely above zero;
3. the lower bound of the interval of (a1)−(c) in the worst 10% at 60 sessions is no worse than −1.0 point.

Otherwise it is **not supported**.

**The removal of WAIT stands** unless the 90 percent interval of (c)−(d) in mean 60-session excess lies entirely above zero, meaning pullbacks did better than strength. In that case it is reported for the operator's decision.

The badge keeps the DIAGNOSTIC label until this test reports; on "supported" the operator decides whether to lift it. (b) decides nothing.

## G. Expected result, stated in advance

**Not supported.**
- (a1)−(c) in mean 60-session excess: within ±1 point, with an interval including zero. The worst 10% is similar.
- (c)−(d): within ±1 point, with an interval including zero. The order's sample had +0.6% for oversold against +0.4% for overbought.
- Median 20-session drawdowns: within one point of each other.

## H. Artifacts and do-not-touch

- **Artifacts, when the data arrives:**
  - `scripts/entry_state_validation_v4.py`;
  - `data/entry_state_power_check_v4.json`;
  - `data/entry_state_validation_v4.json`;
  - `reports/entry_state_validation_v4_<date>.md`.
- The data, as received, is kept outside the served tree; its source, version and sha256 are recorded in every result.
- Everything above is fixed once a run begins.
