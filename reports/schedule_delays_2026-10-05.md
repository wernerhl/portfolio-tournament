# Scheduled-workflow delays: the last 10 trading days (22 September to 5 October 2026)

Execution Order: Make the Daily Options Snapshot Reliable (5 October 2026), item 2.7. Script: `scripts/ops/schedule_delays.py --start 2026-09-22 --end 2026-10-05T21:00`, measured at about 00:10 UTC on 6 October. Raw output: `reports/schedule_delays_2026-10-05.json`.

**Method.** Each workflow's crons are taken as committed on `main` at the time: the options snapshot and the nightly changed their schedules during the window. They are expanded into scheduled instants (UTC), and each schedule-event run is matched to an instant at or before its creation time, in order (GitHub fires crons in order and never early). GitHub's run metadata does not record which cron fired a run. So for the past, the earliest feasible match gives an upper bound on each delay and the latest gives a lower bound, and both are shown as a range; the never-produced share is the same under both. For the Nightly the cron is read from each run's log, where the decide step prints `GITHUB_SCHEDULE`. 15 of its 25 runs carry it, and those 15 give exact delays. From 5 October every scheduled workflow's run title carries its cron (`run-name`), so the next measurement is exact for all of them. A run more than 10 hours after every unmatched cron is not matched. Crons scheduled after 21:00 UTC on 5 October are outside the window: the nightly's 22:00 UTC cron for 5 October was still in GitHub's queue.

| workflow | crons in the window | crons | runs | never produced | median delay (min) | 90th pct (min) | max (min) | within 15 min | exact (median / 90th) |
|---|---|---|---|---|---|---|---|---|---|
| Intraday Refresh (`intraday.yml`) | `*/30 13-21 * * 1-5` | 178 | 23 | **87%** | 29–463 | 147–593 | 178–598 | 4% | — |
| Intraday analytics (`intraday_analytics.yml`) | `0 14,16,18,20 * * 1-5` | 40 | 18 | **55%** | 79–350 | 209–449 | 221–461 | 5% | — |
| Market Open Refresh (`market_open.yml`) | `0 14`, `0 15 * * 1-5` | 20 | 20 | 0% | **283** | 384 | 442 | 0% | — |
| Monthly Rebalance (`monthly_rebalance.yml`) | `0 14 1 * *` | 1 | 1 | 0% | 322 | 322 | 322 | 0% | — |
| Nightly (`nightly.yml`) | `0 22 * * 1-5` and the retries `30 1`, `0 8`, `30 3`, `17 5`, `41 10 * * 2-6` | 26 | 25 | 8% | 291–293 | 390–430 | 430–554 | 0% | 311 / 401 (15 runs) |
| Options snapshot (`options_snapshot.yml`) | 8 crons a day (from 28 Sept 09:00–15:30 ET; before that 15:32–16:55 ET) | 48 | 46 | 4% | **245–250** | 317–345 | 361–481 | 0% | — |

## What the table says

- **No scheduled workflow was delivered on time.** Across 313 crons in 10 trading days, the share delivered within 15 minutes is 0–5% for every workflow. Typical delays are four to five hours.
- **Market open:** every cron ran, but a median 4.7 hours late. The "market-open snapshot" lands around 14:40 ET, not 10:00.
- **Intraday Refresh:** 87% of the every-30-minute crons never produced a run. GitHub drops most high-frequency schedules, so the 30-minute shock watch ran about twice a day.
- **Intraday analytics:** more than half of the two-hourly crons never ran, and the rest ran hours late.
- **Options snapshot:** a median delay of about four hours; the 15:30–16:00 window was hit only when an early cron happened to land, after a delay, at the right moment.
- **Nightly:** the close cron arrives about five hours late (around 23:00 ET) and the retries similar. Its window, from the 16:15 ET close to the 09:30 ET open, absorbs that, and the retry chain publishes. Its failures this autumn came from the retry logic (fixed 2 Oct and 5 Oct), not from the delay.

## Consequence (item 2.7)

The workflows whose purpose is a time window move to the external trigger (`scheduler/worker`, docs/scheduling.md), each keeping its GitHub cron as a gated backup:

| workflow | external dispatch (ET, weekdays) | backup cron gate |
|---|---|---|
| Options snapshot | 15:40, 15:46, 15:52 | the one-writer guard (2.2); backup crons 13:00 and 17:00 UTC |
| Options snapshot check | 16:05 | backup cron 17:30 EDT |
| Market Open Refresh | 10:00 | skip if a successful run exists since 09:30 ET |
| Intraday analytics | 10:10, 12:10, 14:10, 16:10 | skip if a successful run exists in the last 100 minutes |
| Intraday Refresh | 09:50, then :20 and :50 to 15:50 | skip if a successful run exists in the last 25 minutes |

The deploying routes are staggered at least 10 minutes apart. The shared `pages-deploy` concurrency group keeps one pending deploy and cancels the rest, which is the same cancel-and-email mechanism as the options snapshot's on 2 October.

**Not moved:** the Nightly and the Monthly Rebalance. Neither purpose is a narrow window. The Nightly's overnight window absorbs a five-hour delay, its retry chain covers the rest, and a second, external trigger would run the full pipeline twice on the nights both arrive. If the operator wants a fixed publish time, the option is a dispatch at about 21:30 ET with the 22:00 UTC cron removed.
