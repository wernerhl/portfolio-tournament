# Execution order: free analyst data (search, ingest, snapshot, test) — report, 7 October 2026

Commits: [A1] 21e18c0 (`docs/sources_analyst.md`), [B1] adeeb83 and 291f9af (the raw history, then the former index members), [C1] 811419d (the nightly snapshot), [B2] and [D1] below. One repair found on the way is committed separately (ef21878, section 8).

## 1. Sources (task A)

The full table, with the fields, history, dating, limits, terms and verdict of every source, is `docs/sources_analyst.md`. The search ran within the two-hour limit (about 45 minutes of fetching in three parallel passes), with no account, key, trial or email, every host's `robots.txt` read first, one request a second, and every response cached.

| Source | Verdict |
|---|---|
| Nasdaq.com analyst endpoints | **Not usable** — `api.nasdaq.com/robots.txt` disallows every path for every agent, and the Terms forbid automated or manual capture; the endpoints are an undated current snapshot in any case |
| Alpha Vantage `EARNINGS`, `EARNINGS_ESTIMATES` | **Usable with a key** — both functions are on the free tier (verified through the published demo calls); surprise history to 1996; estimates with 7/30/60/90-day look-backs and revision counts; 25 requests a day; no dated back-history |
| Finnhub | **Usable with a key** for monthly recommendation trends (dated) and the last four quarters of surprises; EPS and revenue estimates, price targets and rating changes are premium |
| Financial Modeling Prep | **Usable with a key** within its free plan: 87 symbols, annual estimates only, 250 calls a day; consensus rows carry no observation date; the personal licence forbids copying or downloading |
| Zacks | **Snapshot only** — a 90-day look-back in a browser; every programmatic request met a bot challenge |
| MarketWatch | **Not usable** — `robots.txt` disallows all automated access and the Dow Jones Terms name AI agents |
| Seeking Alpha | **Not usable** — estimates are Premium; `robots.txt` names Claude agents with `Disallow: /` |
| TipRanks | **Snapshot only** — a Cloudflare challenge to direct requests; the API path is disallowed |
| Estimize (ExtractAlpha) | **Not usable free** — give-to-get only; the paid feed ($249 a month with API) is the one product that structurally meets the definition: daily dated crowd and FactSet consensus since January 2012, point-in-time guaranteed |
| Wayback Machine captures of the Yahoo analysis page | **Usable now for spot checks; snapshot-only as a panel** — point-in-time by construction, extractable in every page generation since 2003 (verified on 2016, 2019, 2021, 2023 and 2025 captures), but sparse and skewed to mega-caps: 7 of 15 sampled names have 24 or more capture-months in eleven years; INCY 7, TPL 6, POWL 5, GEV 4 |
| Public datasets (Kaggle, Hugging Face, GitHub, Zenodo, Dataverse, figshare, Mendeley, OpenICPSR, data.world) | **None meets the definition** — two Hugging Face scrapes of Yahoo with one and two dates, per-quarter surprise files, replication code that assumes a WRDS login; one sparse dated panel (GitHub `consensus-drift`, weekly since August 2026, FY2 only) |
| WRDS I/B/E/S | **Usable with a login** — the only source that meets the definition in full (monthly dated consensus since January 1976, every S&P 500 member); an institutional subscription and a university login; listed for the owner, not accessed |
| SEC 8-K Item 2.02 guidance | **Usable now** as a free, dated, point-in-time source of company guidance (10 requests a second with a declared contact); not a substitute for consensus: the company's view, quarterly, free text |

## 2. Does any free source meet the definition of a usable history (A3)?

**No.** Every free source is a current snapshot, a per-quarter pre-report estimate, or a dated panel too sparse in dates or names. The sources that meet the definition are licensed: I/B/E/S or Zacks through WRDS, the terminal feeds (Bloomberg, LSEG Workspace, FactSet, Capital IQ), Estimize's paid feed, and Nasdaq Data Link's ZEEH. Rating changes, price targets and earnings surprises do have free history in the price provider, which task B ingested; a dated consensus history is what the repository now builds for itself (task C).

## 3. Coverage of the history variables (task B)

**The raw history (B1).** For the 535 names of the universe and the 346 former index members: 198,791 rating rows for 658 names (December 2011 to 6 October 2026, each with the firm, the grades, the action and the current and prior price target), 55,228 reported earnings rows (back to 2002 for the oldest names), 1,792 splits, and a month-end price table. Price targets are nominal at their date (NVDA's 2024 medians read 750, its 2025 medians 211), so the panel rebases them by the splits between the row and the month-end. 203 former members are delisted and the provider holds nothing for them. Acceptance: MU 894 rating rows from February 2012, LMT 306; MU's earnings rows start in 2002 and carry the 30 September 2026 report at 31.82 estimated and 33.42 reported.

**The panel (B2).** `data/analyst/panel_monthly.parquet`: 105,949 rows for 668 names at 177 month-ends (January 2012 to September 2026), each variable ranked within the S&P 500 members of the month and scaled to [−0.5, 0.5] (average ranks; a non-member placed within the members' distribution). Members come from `data/analyst/sp500_membership_history.parquet`, the Wikipedia list's revision in force at each month-end (500–505 names a month, 846 names over the period; no membership history existed in the repository and the survivorship-free data is not installed).

**Members with data, by year** (the index as it was against the names the provider has prices for):

| | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| members in the file | 500 | 500 | 501 | 503 | 504 | 505 | 505 | 505 | 505 | 505 | 504 | 503 | 503 | 503 | 503 |
| with prices | 327 | 338 | 346 | 361 | 380 | 394 | 409 | 425 | 441 | 451 | 462 | 475 | 482 | 489 | 499 |
| share | 0.65 | 0.68 | 0.69 | 0.72 | 0.75 | 0.78 | 0.81 | 0.84 | 0.87 | 0.89 | 0.92 | 0.94 | 0.96 | 0.97 | 0.99 |

The missing members are delisted names (acquired, merged, failed) the provider has no bars for; the test therefore still leans toward survivors in its early years, and section 5 says what that did to the numbers.

**Share of members with prices that carry each variable, by year:**

| year | net_up_90 | pt_rev_90 | pt_gap | n_act_90 | surprise | sue | surprise_streak |
|---|---|---|---|---|---|---|---|
| 2012 | 0.75 | 0.70 | 0.73 | 1.00 | 0.97 | 0.97 | 0.99 |
| 2014 | 0.88 | 0.80 | 0.86 | 1.00 | 0.98 | 0.98 | 0.99 |
| 2016 | 0.87 | 0.71 | 0.78 | 1.00 | 0.98 | 0.98 | 0.99 |
| 2018 | 0.90 | 0.82 | 0.85 | 1.00 | 0.99 | 0.99 | 1.00 |
| 2020 | 0.92 | 0.89 | 0.92 | 1.00 | 0.99 | 0.99 | 1.00 |
| 2022 | 0.95 | 0.93 | 0.94 | 1.00 | 0.99 | 1.00 | 1.00 |
| 2024 | 0.97 | 0.96 | 0.97 | 1.00 | 0.99 | 0.99 | 1.00 |
| 2026 | 0.98 | 0.98 | 0.98 | 1.00 | 0.99 | 0.99 | 1.00 |

`an_n_act_90` counts zero actions as a value, so it is always present; `an_net_up_90` and the target variables need an action within 90 days. **The price-target columns are filled for at least half of the members from 2012, the first year of the history:** every rating row since the start carries a target (338 members with rows in 2012, all with a target). The earnings rule held throughout: a row counts only with a reported EPS and an effective date at or before the month-end, and a report at or after 16:00 ET is effective the next trading day (the planted-row tests in `tests/test_analyst_lookahead.py` cover both).

## 4. Snapshot status (task C)

- **First day captured: 2026-10-06** — `data/analyst/snapshots/2026-10-06.json`, captured at 04:31 ET on 7 October (the state after the 6-October close and before the 7-October open), 530 of 535 names (99.1%; the five without analysis data at the provider are BK, CFLT, L, PSTG and SATS), 965 KB, 547 requests in nine minutes, flagged `first_run`. From tonight the nightly writes one file per session after the close, keyed by the session it publishes.
- **Index:** `data/analyst/snapshots/_index.json` — one captured day, no missing day; a session is decided at 09:30 ET on the next trading day, after the nightly's last retry.
- **The missed-day issue:** `scripts/analyst/snapshot_alerts.py` opens one issue per missed day (label `analyst-snapshot-missed`) and closes it when a later day is captured; it runs in the nightly's alerts step and at the 16:05 ET check.
- **Referee:** the latest snapshot must be at most one trading day old and cover at least 95% of the universe; every captured file must match the sha256 the index recorded (CRITICAL otherwise); the revision variables must stay DIAGNOSTIC and out of every score until twelve months of snapshots exist (CRITICAL otherwise).
- **The revision variables:** `data/analyst/revisions.json` reads "waiting: 1 of 30 days of snapshots"; once 30 days exist it carries `an_eps_rev_30`, `an_eps_breadth_30` and `an_rev_rev_30` for every name, and the stock cards show them with the DIAGNOSTIC label and the words "in no score". The derived history `data/analyst/consensus_history.parquet` already holds 10,588 dated rows: the observed values of the first snapshot and, marked `provider-reported`, its 7-, 30-, 60- and 90-day-ago values dated back (8 July to 29 September), one extra dated observation per horizon.
- **Acceptance "a snapshot file exists for the first trading day after this order is executed":** the file for 7 October is written by tonight's nightly (the step runs right after the price refresh; the three retries re-attempt it until 06:41 ET). The 6-October file above is one day earlier than that requirement.

## 5. Test results (task D)

**Design.** The `ml_stratification_test/` code the order refers to (`feats2.py`, `ml2.py`, `uni2.py`) is not on this machine and not in the owner's repositories, so the test was built fresh on the stated design (`scripts/analyst/walkforward_test.py`; every table is in `data/analyst/walkforward_test.json`). Universe: the S&P 500 members at each month-end from the membership file (the survivorship-free data is not installed). Features at month-end t use only what was known at its close: the seven analyst variables above and a base set from prices alone (12-1 momentum, the 1-month return, 12-month volatility, the distance from the 12-month high on split-adjusted closes, log 20-session dollar volume on split-adjusted prices), each ranked within the month. Outcomes: the 12-month (primary) and 1-month forward return on dividend-adjusted closes, in excess of the average member of the month; a name whose bars end inside the horizon is held to its last price. Test years 2014 to 2026; the models are retrained each January on month-ends whose 12-month outcome was complete before the test year (the 12-month test runs through September 2025, the last month with a complete outcome; the 1-month test through August 2026). Two models, each with and without the analyst variables: ridge (the primary, the form a candidate score could use) and a boosted tree (sklearn `HistGradientBoostingRegressor`). Portfolios: the top tenth and top fifth of each month's predictions, equal-weighted, against the average member, after 10 basis points per trade (20 bps per 12-month holding; monthly turnover times 10 bps at one month); Newey-West t-statistics with 11 lags for the overlapping 12-month returns and 1 lag at one month. 177 months, 75,586 member-months, 427 members a month on average; 10.2% of member-months have no complete 12-month outcome (almost all in the last twelve months); 13,491 member-months belong to names without prices.

**Table 1 — each variable alone, 12-month horizon** (IC = the monthly rank correlation with the later excess return, averaged; top fifth = the equal-weighted top fifth against the average member, points a year; Newey-West t in brackets; 72 months in 2014–2019, 69 in 2020–2026):

| variable | IC 2014–19 | IC 2020–26 | top fifth 2014–19 | top fifth 2020–26 | coverage |
|---|---|---|---|---|---|
| an_net_up_90 | +0.013 (0.7) | −0.001 (−0.2) | −0.59 (−0.9) | −0.38 (−0.4) | 0.84 / 0.95 |
| an_pt_rev_90 | +0.028 (0.7) | −0.002 (−0.1) | +1.05 (0.7) | +1.99 (1.2) | 0.71 / 0.93 |
| an_pt_gap | −0.051 (−1.6) | +0.019 (0.8) | −2.63 (−1.5) | +3.86 (1.6) | 0.77 / 0.95 |
| an_n_act_90 | +0.011 (0.4) | +0.017 (0.8) | +1.93 (1.4) | +3.71 (1.5) | 0.96 / 1.00 |
| an_surprise | +0.014 (0.8) | −0.000 (0.0) | −0.64 (−0.6) | +1.78 (1.3) | 0.95 / 0.99 |
| an_sue | +0.049 (2.6) | −0.006 (−0.5) | +1.22 (2.1) | −0.03 (−0.1) | 0.95 / 0.99 |
| an_surprise_streak | +0.028 (1.4) | −0.030 (−2.0) | +0.61 (0.9) | −2.69 (−3.6) | 0.96 / 1.00 |

No variable holds its sign across the two periods. The standardised surprise (`an_sue`) is the only one with a t above 2 in 2014–2019 (IC +0.049, top fifth +1.2 points a year), and it is flat in 2020–2026; the surprise streak turns against itself after 2020 (top fifth −2.7 points, t −3.6); the target gap flips sign. At the 1-month horizon every IC lies within ±0.02 and the top fifths run from −1.6 to +3.3 points a year, none with a t above 1.5.

**Table 2 — the models, top tenth against the average member, after costs, points a year (Newey-West t):**

| horizon | model | without the analyst variables | with the analyst variables | paired difference, with − without |
|---|---|---|---|---|
| 12 months | ridge (primary) | +2.60 (0.76) | **+2.29 (0.94)** | **−0.31 (−0.20)** |
| 12 months | boosted tree | +4.03 (1.45) | +3.00 (1.56) | −1.03 (−0.95) |
| 1 month | ridge | −1.16 (−0.45) | −1.36 (−0.60) | −0.21 (−0.14) |
| 1 month | boosted tree | −1.91 (−0.64) | +0.90 (0.33) | +2.81 (2.22) |

Top fifths at 12 months: ridge +1.77 without and +1.79 with; the tree +2.03 and +1.37. One-way turnover of the 12-month top tenth is 26–43% a month; at one month about 60%. The one positive paired result, the tree at one month, comes with a top tenth of +0.9 points a year (t 0.33) and is not the primary design.

**The pass rule.** The pass rule fails: the ridge model with the analyst variables puts its top tenth +2.29 points a year against the average member after costs (Newey-West t 0.94; the rule needs more than 2 points and t above 3), and the paired difference against the same model without them is −0.31 points (t −0.20). Of the four conditions, the top tenth above 2 points and the cost condition hold; the t-statistic above 3 and the paired improvement do not. **The analyst variables therefore do not enter the candidate score; they stay on the stock cards as description.**

**The four look-ahead checks.**

1. **No variable depends on the current index membership list.** The only membership input is the dated membership file; no sector label is used; the builders take the member flag as an argument and read no current list (`tests/test_analyst_lookahead.py`). This check failed once during the work: the first run of the test used only the names in today's universe (the past members absent from it were not downloaded), so its universe depended on the current list. The member counts caught it (338 of 500 members with data in 2013). After the 346 former members were downloaded and the test rebuilt, the ridge top tenth fell from +5.40 points (t 1.92) to +2.29, and the model without the analyst variables from +6.43 to +2.60: the survivors had flattered both. Ledger entry `mistake-2026-10-07-1`.
2. **Dollar volume uses prices adjusted for splits only.** The 20-session dollar volume is the split-adjusted close times volume from the provider's unadjusted history; dividend-adjusted closes enter the outcomes only (unit test: a dividend changes the adjusted close, not the dollar volume).
3. **Two placebo runs** (ridge, 12 months, after costs). Each analyst variable replaced by its value **12 months later**: the top tenth rises to **+27.49 points a year (t 6.51)**, the paired difference to +24.88 (t 7.66), and the single-variable ICs to +0.49/+0.55 for the target revision, +0.22/+0.20 for the standardised surprise, +0.11/+0.14 for net upgrades (the future target gap is negative, −0.27/−0.33: a price that rose closes the gap). The test detects information. Each variable replaced by its value **12 months earlier**: the top tenth falls to **+0.46 points (t 0.17)** and the paired difference to −2.14; the ICs sit within ±0.05. The effect falls toward zero, so the variables are not a persistent company trait.
4. **No analyst row after the month-end enters that month's variables.** `tests/test_analyst_lookahead.py` plants a rating row at 16:01 ET on the month-end and another the next morning and asserts every variable unchanged, while a row at 15:59 ET counts; it also plants a report at 16:05 ET and asserts it is effective the next session. Seven tests pass.

**What the results say.** Over 2014–2026 the free analyst history — rating changes, price-target changes and gaps, attention, earnings surprises — carries no reliable information about the next twelve months of a large stock's return beyond what prices already say, once it is ranked, walked forward, costed and judged with overlapping-return t-statistics. The two sub-periods disagree on every variable's sign. The dated consensus-revision history is the piece that could differ (it is what the literature's revision effects rest on), and it does not exist in free form; the repository starts owning it today, and its registered test can run once twelve months of snapshots exist.

**The referee.** Before (`reports/audit_2026-10-07_analyst_before.txt`): the committed tree's referee crashed (section 8), the state the nightly had recorded as 0 findings. After (`…_after.txt`): 29 findings, 1 CRITICAL — `identity:position_price`, the 6-October positions published without a price, which the repaired referee now reports and which clears when the 7-October session publishes tonight. The new checks (`analyst:snapshot_stale`, `analyst:snapshot_coverage`, `analyst:snapshot_immutable`, `analyst:diagnostic_gate`, `analyst:in_score`, `analyst:language`) raise nothing: the snapshot is current, covers 99.1% of the universe, matches its recorded sha256, and the revision variables are DIAGNOSTIC and in no score. Unit tests: `tests/test_analyst_lookahead.py` (7) and `tests/test_analyst_history.py` (4) pass. The vendor names "Alpha Vantage" and "Seeking Alpha" appear in `docs/sources_analyst.md` and this report as proper nouns; no served data file carries the word.

## 6. Sources that need a key or a login — for the owner to decide

| Source | What it buys | Cost | Weigh |
|---|---|---|---|
| Alpha Vantage free key | `EARNINGS_ESTIMATES` snapshots with 7–90-day look-backs and revision counts; `EARNINGS` surprise history to 1996 | Free | 25 requests a day (a 500-name pass takes 20 days); personal, non-commercial licence; no dated back-history |
| Finnhub free key | Monthly dated recommendation trends; four quarters of surprises | Free | Estimates, targets and rating changes are premium; no redistribution |
| Financial Modeling Prep free key | Current annual consensus and dated rating counts, rating events and surprises for 87 symbols | Free | 87 symbols; the licence forbids copying or downloading content |
| WRDS I/B/E/S or Zacks on WRDS | The full monthly dated consensus history since 1976 — meets the definition | Institutional subscription through a university affiliation | Academic, non-commercial use only; a university login the owner would have to hold |
| Estimize Premium Plus | Daily dated crowd and FactSet Wall Street consensus since 2012, with API | $249 a month | Crowd consensus beside the sell-side one; no redistribution |
| Nasdaq Data Link ZEEH / ARPT | Zacks consensus history; TipRanks ratings and targets | Paid, quotation | Commercial licences |

## 7. Recommendation on purchase

**Not needed now.** The free history already in hand covers rating changes, price targets and earnings surprises back to 2012, and the walk-forward test finds that these add nothing to the candidate score under the pass rule. A purchase would buy the one thing the free sources lack, a dated consensus-revision history (I/B/E/S through WRDS, Estimize Premium Plus, or Zacks through Nasdaq Data Link), and would let the revision test run now instead of in October 2027, when the repository's own snapshots reach twelve months. Buying is worth reconsidering only if the owner wants that answer a year earlier; the snapshots cost nothing and start the clock today. The survivorship-free universe (Sharadar or Norgate) is a separate decision already pending for the entry-state validation; it would also tighten this test's early years, where 31–35% of the index members have no prices at the free provider.

## 8. Found on the way: the 6-October publish and the stuck deploy (repair commit ef21878)

The referee's before-run for this order crashed on the committed data. The nightly of 6 October had published the operator tier with GEV, GOOG and BMNR priced None (the provider's 6-October bar was missing for 95 of 540 names at 21:16 ET), so its NAV went out at 191,068 against 237,670 the day before; the referee then failed on the None value in its equity sum and the run was recorded as 0 findings, 0 CRITICAL. The 6-October row stays as published. Repairs: the referee's sums treat None as 0 and a position without a price is CRITICAL (`identity:position_price`); `update_daily` rejects a publish with an unpriced position (`PRICE_MISSING`) so the retries find the bar; ledger entry `mistake-2026-10-06-5`. Separately, a Market Open deploy job had been "waiting" on the Pages environment since 19:19 UTC on 6 October with no reviewer and no timer, holding the deploy queue: three later deploys were cancelled and the nightly's was pending, so the site served the 5-October session until the stuck run was cancelled by hand at 04:10 ET on 7 October (the pending deploy then completed).
