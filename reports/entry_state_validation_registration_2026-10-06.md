# Entry-state validation, rules version 2: registration (registered, NOT run)

Registered 6 October 2026 under the Execution Order: Revision of the Entry-State Indicator and Related Fixes, section 7: *"Register before any run. Universe: point-in-time constituents of the S&P 500 from the purchased survivorship-free data (Sharadar or Norgate), 2005 to present, including delisted names."* Machine-readable parameters: `data/entry_state_validation_registration_2026-10-06.json`.

**Status: registration only. Nothing can run yet.** The survivorship-free data has not been received: the 9 September memo records the Sharadar/Norgate access as "pending receipt", and the repository has no such data or key. The run script is written when the data arrives, against these parameters. Nothing below changes once a run begins; a change needs a new registration with a stated reason, and both results are reported.

**What was seen before this registration.** The order's own section 1 table: about 80 large companies, 2011–2026, 4,540 oversold events, results by contestant. This registration's expected result is informed by it, and says so.

## A. Universe and data

- Point-in-time S&P 500 constituents on each event date, from the purchased survivorship-free data (Sharadar SEP and its S&P 500 membership table, or Norgate with its historical index constituents). Names that later left the index or were delisted are included.
- Window: events from 3 January 2005 to the last session whose 120-session outcome is complete. History from 2004 for the 200-day and 12-month inputs.
- Prices: split-adjusted OHLC for every state input, as charted; total-return closes for outcomes.
- The benchmark is SPY's total return. "Beating the index" means a positive excess return.

## B. Events and outcomes (as in the order's section 1, plus 120 sessions)

- **Event:** a session on which the stock's RSI(14) (simple-average, Cutler) closes below 30. Events for the same stock are at least 20 sessions apart: a later trigger inside 20 sessions of the last counted event is skipped.
- **Entry:** the event session's close; the next session's open is reported as a sensitivity. Costs: the C1 model, 10 bps one way on entry and on exit.
- **Outcomes at 60 and 120 sessions:**
  - the excess return over SPY, net of costs;
  - whether it beats the index;
  - the median drawdown in the first 20 sessions: the lowest close in sessions 1–20 against the entry, as a loss.

## C. Contestants

- **(a) The revised rules (version 2, `data/entry_state_config.json`).** An event counts when the revised machine reads READY or READY-HALF at the event close:
  - the trend gate is not failed (not both below the 200-day and with negative 12-1 momentum);
  - the setup holds (it does, since RSI below 30 implies RSI ≤ 40);
  - no long-term ceiling caps it, judged from the yearly closing highs available up to the event date;
  - the size modifiers stay at or above a quarter.

  Point-in-time limits:
  - The heavily-shorted modifier is **not applied**: there is no historical days-to-cover in either data set.
  - The earnings modifier is applied only if the purchased data carries report dates (Sharadar's filing dates do); otherwise it is not applied.

  Both omissions can only make more events READY than the live rule would; they are reported.
- **(b) The 2-October rules (version 1, frozen in `scripts/entry_state_v1.py`).** The first session within 10 sessions after the event on which the version-1 machine reads READY: trend gate (positive momentum and above the 200-day), setup, and a trigger. The outcome is measured from that session's close. Events without such a session are not entries for (b).
- **(c) All oversold events.**

## D. Statistics and the bootstrap

For each contestant and horizon, the following are reported, with the differences (a)−(c), (b)−(c) and (a)−(b):
- the mean and median excess return;
- the share beating the index;
- the worst 10% (the 10th percentile of the excess return);
- the median 20-session drawdown.

Intervals come from a date-block bootstrap clustered by month. The distinct event months are resampled with replacement, and each drawn month brings all its events from every contestant, so the contestants share each resampled history. There are 10,000 resamples, seed 20261006, and 90 percent percentile intervals.

## E. The discriminating-power check (run and reported first)

(c) is split at random into two halves, by event (seed 20261006), and the same statistics and bootstrap compare the halves. A sound method finds no difference between two random halves. **The check passes** if the 90 percent interval of every difference (five statistics, two horizons) includes zero. The half-widths are reported as the method's resolution. If the check fails, the method is unsound for this data: the real comparison is reported as descriptive only, and a new registration is needed.

## F. Decision rule, registered in advance

**(a) is supported** only when all three hold:
- the power check passes;
- the 90 percent interval of (a)−(c) in mean 60-session excess return lies entirely above zero;
- the lower bound of the interval of (a)−(c) in the worst 10% at 60 sessions is no worse than −1.0 point.

Otherwise it is **not supported**. The badge keeps the DIAGNOSTIC label until this test reports; on "supported" the operator decides whether to lift it. (b) against (c) is reported with the same statistics and decides nothing.

## G. Expected result, stated in advance

**Not supported.** The order's section 1 found differences of about one point over 60 sessions among oversold groups, on a universe biased toward survivors. Expected (a)−(c) mean 60-session excess within ±1 point with an interval including zero; worst-10% similar. Expected (b)−(c) similar, with fewer events. Expected median 20-session drawdowns within one point of each other.

## H. Artifacts and do-not-touch

- Artifacts, when the data arrives: `scripts/entry_state_validation_v3.py`, `data/entry_state_power_check_v3.json`, `data/entry_state_validation_v3.json`, `reports/entry_state_validation_v3_<date>.md`.
- The data, as received, is kept outside the served tree; its source, version and sha256 are recorded in every result.
- Everything above is fixed once a run begins.
