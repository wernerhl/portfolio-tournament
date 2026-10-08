# Follow-up to the analyst-data report: referee, errata, deploy watchdog, snapshot timing, one test harness — report, 7 October 2026

Commits: [F1] b644107, [F2] 3ef5e9e, [F3] be56027, [F4] 99e5561, [F5] d9f2ee4, [F6] dfa3163 (this report; amended with the watchdog's acceptance result). The referee output before this order is `reports/audit_2026-10-07_analyst_after.txt` (29 findings, 1 CRITICAL, from the previous order's close); after, `reports/audit_2026-10-07_followup_after.txt` (section 7).

## 1. F1 — the referee fails closed

`audit_nightly.py` now ends every run with `REFEREE COMPLETE: <n> findings; <m> CRITICAL`, and each of its 21 check sections (and the file scan) runs inside its own error handler: a check that raises becomes `CRITICAL referee:check_failed:<name>` with the exception text and the other checks still run. `audit_status.py` treats a report without the final line, with a traceback, or whose completion count disagrees with the parsed lines as `CRITICAL referee:crashed`: served files restored to the last good commit, `failure_reason` written, exit 1. The status strip shows both like any other CRITICAL.

**The three test outcomes** (`tests/test_audit_status.py`, four tests pass):

| test | outcome |
|---|---|
| a report file containing only a traceback | `referee:crashed` in `audit.critical`, `failure_reason` "audit: referee:crashed", exit 1 |
| a report file with findings and no final line | `referee:crashed`, exit 1; the HIGH findings are still recorded |
| a check that raises (the picks file corrupted on a scratch copy of `data/`) | `referee:check_failed:picks` reported; the entry, options, governance and analyst checks still report; the run ends with `REFEREE COMPLETE: 35 findings; 1 CRITICAL` and the count matches the lines |

**The referee output of a forced crash** (the third test's run, abridged):

```
[CRITICAL] referee:check_failed:picks   the picks checks did not finish: TypeError: 'int' object is not iterable
[HIGH    ] options:captured_share       4 of the last 9 trading days captured (44% < 90%); missing: [...]
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
...
35 findings; 1 CRITICAL
REFEREE COMPLETE: 35 findings; 1 CRITICAL
```

And `audit_status.py` on a report that is nothing but a traceback: `audit [all]: 1 findings — blocking CRITICAL ['referee:crashed'] ...`, `::error::audit CRITICAL — served files restored to last good`, exit 1.

## 2. F2 — errata for the 6 October operator-tier row

**The errata entries** (`data/errata.json`, append-only, each with its sha256; ledger id `mistake-2026-10-06-5`; added 2026-10-07):

| id | tier · date | field | published | corrected | reason (short) |
|---|---|---|---|---|---|
| erratum-2026-10-06-5_werner-1 | 5_werner · 2026-10-06 | GEV price | None | 1,029.21 | the provider's 6-Oct close; the bar was missing at 21:16 ET |
| erratum-2026-10-06-5_werner-2 | | GEV value | None | 25,730.25 | 25 shares at the 6-Oct close |
| erratum-2026-10-06-5_werner-3 | | GOOG price | None | 344.59 | |
| erratum-2026-10-06-5_werner-4 | | GOOG value | None | 17,229.50 | 50 shares |
| erratum-2026-10-06-5_werner-5 | | BMNR price | None | 26.20 | |
| erratum-2026-10-06-5_werner-6 | | BMNR value | None | 5,241.84 | 200.0702 shares |
| erratum-2026-10-06-5_werner-7 | | equity | 42,750.60 | 90,952.19 | the five positions' values with the three at their 6-Oct closes |
| erratum-2026-10-06-5_werner-8 | | nav | 191,067.57 | 239,269.16 | corrected equity plus the published cash 148,316.97 |

The published row keeps its bytes (verified: the 6-October row's `nav`, `equity`, `cash` and positions are unchanged in `data/tournament.json`; the per-row `drawdown` annotation is a derived field recomputed every night since the dashboard order and is now computed on the corrected values). Every reader applies `scripts/errata.py`: `compute_nav` (the comparable series, the cost restatement, the drawdowns), `tournament_audit`, `daily_brief`, `compute_twins` (the parents' NAVs), `picks_vs_qqq`, the referee; the pages apply it in memory after loading and footnote the date under the leaderboard and the book panel with a link to the entries. New referee checks: `errata:edited` (CRITICAL), `errata:unexplained_jump` (HIGH for a day-to-day tier change above 15% with no erratum and no recorded flow), `errata:applied` (INFO); `identity:position_price` skips positions an erratum covers.

**Found while doing this:** the operator tier's comparable series had been frozen since 1 October. Every row re-syncs its cash to the holdings file and carried `reseeded: true`, so every day's return was excluded as a "re-seed step" (the 5-October step of +0.49% was the market). A cash re-sync is now a re-seed only when the cash moved by more than 0.5% of NAV; the three real re-seeds (29 and 30 September, 1 October) are unchanged.

**The operator tier before and after** (the comparable series, re-seed steps excluded, 96 sessions since 20 May):

| | volatility (annualised) | largest drawdown | worst day | 6 October return |
|---|---|---|---|---|
| as published | 35.1% | −20.4% | −19.6% (6 Oct) | −19.61% |
| corrected | 14.4% | −8.3% | −2.7% | **+0.67%** |

After the change no day beyond 10% in either direction remains on 6 October; 7 October's return will be measured from the corrected 6-October value when tonight's nightly publishes it (as published it would have read about +24%). The 6-October brief entry (`brief-2026-10-06-1`), whose run had crashed on a None sector change from the same missing bars, is generated from the template with the model's rejection recorded.

## 3. F3 — deploy watchdog

- `timeout-minutes: 15` on every deploy job (nightly, intraday, intraday analytics, market open).
- `scripts/ops/deploy_watchdog.py` lists runs whose `deploy` job has been waiting, queued or in progress for more than 30 minutes and cancels them with the workflow's own `GITHUB_TOKEN` (`actions: write`), skipping its own run. It runs first in the nightly and intraday workflows and every 30 minutes on weekdays from `watchdog.yml`. No new credential.
- Referee `site:session` (INFO, every run) and `site:stale` (HIGH when the live session is more than one trading session behind); `scripts/site_alerts.py` opens one issue labelled `site-stale` while that holds and closes it when the site catches up.

**The watchdog's first runs and the acceptance test.** The test run (`watchdog_test.yml`, a `deploy` job that only waits) was dispatched at 20:14 ET. The watchdog's first run, dispatched by hand at 20:23 ET, found nothing to cancel ("no deploy job older than 30 min in the waiting/queued/in-progress states" — the test job was nine minutes old). GitHub did not deliver the scheduled 00:30 or 01:00 UTC runs by 21:28 ET (the nightly's own 22:00 UTC cron was likewise undelivered three and a half hours after its time that evening), so the watchdog was dispatched by hand again at 21:29 ET and cancelled the test run: `CANCELLED run 1 (Deploy watchdog test, id 37706691839): deploy job in_progress since 2026-10-08T00:14:21+00:00 (74.9 min)`; the run shows `completed cancelled` at 21:29:38 ET. The cancel path is verified end to end; the 60-minute bound of the acceptance holds when the 30-minute cron is delivered on time, which GitHub does not promise — the same step running first in every nightly and intraday run (every 30 minutes during market hours) is the second path, and a deploy job can no longer outlive its 15-minute timeout once it has started.

**The site age the referee reports:** `[INFO] site:session — live site session 2026-10-06, 23.0 h since its last publish (last session 2026-10-07)` (run at 20:20 ET on 7 October, before tonight's nightly).

## 4. F4 — availability date of a snapshot

Every new snapshot carries `available_from`: the first trading session whose close is at or after the capture — the capture's own ET date when that is a trading day, else the next trading day. The first file (captured 04:31 ET on 7 October, named 2026-10-06) gets `available_from = 2026-10-07` derived from its `captured_at`; the index records the field per day. The revisions builder computes its variables as of the latest availability date and chooses today's and the base snapshot by `available_from`, not by the file name; every `consensus_history` row carries `available_from` and `cards_only`. Provider-reported rows (the first file's 7/30/60/90-day look-backs) are cards-only; the harness's loader takes observed rows only, attached to a month-end only when available by its close, and records the counts in `walkforward_test.json` (`inputs.consensus_rows`); the referee's `analyst:provider_rows_in_test` is CRITICAL if one enters.

**The two test outcomes** (`tests/test_analyst_lookahead.py`, nine tests pass):

| test | outcome |
|---|---|
| a snapshot named 30 October, captured at 04:31 ET on 2 November | `available_from = 2026-11-02`; not usable for the 30-October month-end; usable from 2 November |
| a snapshot captured at 17:30 ET on its own session date (7 October) | `available_from = 2026-10-07`; usable for that date |

(Also covered: a Saturday capture is available from Monday; a file that carries the field keeps it; the provider-reported rows are marked cards-only and dated back from the first file.)

## 5. F5 — one test harness

**The research folder.** `ml_stratification_test.zip` is unpacked under `research/ml_stratification_test/` (`feats2.py`, `ml2.py`, `uni2.py`, `ev.py`, `fund.py`, `sec.py`, `dl.py`, `dl2.py` and the result tables `res_all.csv`, `res_price.csv`, `res_fund.csv`, `uni2.csv`, `events.csv`, `capex_signal.csv`). The folder is not served: every deploy job removes it before the Pages upload. One change on delivery: `sec.py` carried the owner's email address in its User-Agent literal; it now reads `SEC_USER_AGENT` from the environment. The files hold no transactions or account history (checked). The design-layer error is in the ledger as `mistake-2026-10-07-2`.

**The reconciliation.** Starting from the repository's configuration, each difference is removed in turn, cumulatively; the ridge top tenth at twelve months after each step (`scripts/analyst/reconcile.py`, `data/analyst/reconciliation.json`). The design workspace's 43 variables were rebuilt on the repository's data by `scripts/analyst/features_ext.py` (its `feats2.py` adapted: the 21 price variables from the provider's daily bars and SPY, the 22 fundamentals from EDGAR company facts through `scripts/analyst/sec_facts.py` — 38,973 trailing-twelve-month records for 651 companies with their filing dates, 654 requests under four a second with the declared contact).

| step | difference removed | top tenth, points a year | Newey-West t | members a month |
|---|---|---|---|---|
| 0 | the repository's result: 5 price variables, 10 bps a trade, a delisted name held to its last price, the excess return as the training target, ridge penalty 1 | +2.60 | 0.76 | 427 |
| 1 | no cost | +2.80 | 0.81 | 427 |
| 2 | the workspace's return treatment: a name whose prices end inside the horizon is dropped; returns capped at 300% | +2.09 | 0.68 | 427 |
| 3 | the workspace's fit: the within-month percentile rank of the outcome as the training target, penalty 100 | −2.55 | −1.07 | 427 |
| 4 | **the workspace's universe filters: 63-day dollar volume of at least $3 million, and a current sector label — which removes the names that later left the index** | **+4.03** | **1.66** | 376 |
| 5 | the workspace's 21 price variables | +5.60 | 1.67 | 376 |
| 6 | the 22 fundamental variables (43 in all; names with fundamentals) | +4.53 | 2.04 | 359 |
| | the workspace's own reported result (`res_all.csv`, 43 variables) | +2.64 | 2.06 | — |

The months in the sample are the same (141 twelve-month test months, January 2014 to September 2025) and the Newey-West code is the same: the workspace's `nw_t` run on the repository's series reproduces every t in the table to the second decimal. The 12-month top tenth of the workspace's 21 price variables reads t 1.95 in its own table and 1.67 here; its 43 variables 2.06 and 2.04.

**Conclusion in one sentence:** the gap in the t-statistic (2.1 against 0.76) comes from the design workspace's universe filter — its requirement of a current sector label, with the liquidity screen, drops the companies that later left the index and moves the top tenth from −2.6 to +4.0 points (t −1.1 to 1.7) — and from its 43 variables (t 2.0); the cost, the treatment of names whose prices end inside the horizon, the months in the sample and the Newey-West code explain none of it.

**The single harness.** `scripts/analyst/walkforward_test.py` stays the one harness. The 43 variables are an optional feature set (`EXT_VARS`, through `build_table(ext=True)` from `data/analyst/panel_ext_monthly.parquet`), with the workspace's return treatment, fit and filters as options used by the reconciliation. The candidate-list test is registered on it (`data/analyst/candidate_list_test_registration.json`: the harness, the feature sets, the design, the pass rule of section D2 and the look-ahead checks); the proposal's own candidate list and any parameter it fixes are not in the repository and are to be entered there from the proposal text before any run.

### Correction, 8 October

The audit of this report (second follow-up order of 7 October, G1) found that the conclusion above is wrong about what explains the gap, and the earlier text stands as written with this correction beside it.

**Findings.**

1. The design workspace's filter used the provider's sector label for every ticker with prices (`info.csv`, 665 of 687 tickers labelled; delivered with the second follow-up and now under `research/ml_stratification_test/`). It removed 22 tickers in all: ABI, AT, AV, BBBY, CAM, CSRA, EMC, FB, FISV, GDT, GENZ, INFO, JAVA, MEDI, NFX, PCL, PWER, SDS, SHLD, SPLS, TEK, UST.
2. `info.csv` had not been delivered with the code, and step 4 of the reconciliation used the sector labels in `data/canonical/fundamentals.json` instead. That file labels the dashboard's current universe only: it covers 80% of the 2014 member-months in `panel_ext_monthly.parquet` and 99% of the 2026 ones. A filter on it keeps the companies that are still in the index today — the look-ahead the workspace had removed after its first run. The option is renamed `current_universe_only`, its docstring calls it look-ahead, and a registered run that sets it is CRITICAL `analyst:lookahead_filter`.
3. The harness with each filter alone (5 variables, ranked target, penalty 100, delisted names dropped, returns capped at 300%, no cost; `data/analyst/reconciliation_correction.json`, recomputed on this tree and identical to the audit's rows): no filter −2.55 (t −1.07); the dollar-volume filter alone −2.75 (t −1.19); the substitute sector filter alone +4.03 (t 1.66). The jump to +4.0 is the substitute filter.
4. The two universes are nearly the same. In 2014 the workspace had 355 members a month with prices and the repository 374, with 343 in common. From 2019 on, the workspace has no member the repository lacks.

**What explains the gap:** the variable set and the length of the training history. Ridge top tenth at 12 months, ranked target, penalty 100, delisted names dropped, returns capped at 300%, no cost, the same 141 test months (January 2014 to September 2025); the 43-variable rows use names with fundamentals only.

| Variables | Workspace code, training from 2012 | Repository harness, training from 2012, no filter | Workspace code, training from 2005 (price) or June 2010 (43) |
|---|---|---|---|
| 5 price | −3.49 (t −1.27) | −2.55 (t −1.07) | −2.94 (t −2.27) |
| 21 price | +1.42 (t 0.44) | +1.61 (t 0.54) | +2.85 (t 1.95) |
| 43 | +2.44 (t 1.27) | +2.38 (t 1.22) | +2.64 (t 2.06) |

With the same variables and the same training start, the two implementations agree within one point and 0.2 of t. The t of about 2 in the workspace needs training data from before 2012; the repository's membership file started in 2012, so its 2014 model trained on one year of month-ends. G2 of the second follow-up extends the membership file to June 2004 and reruns the test on it.

For the record, on the repository's own treatment (delisted names held to the last price, 10 bps a trade) the 43 variables give +2.08 (t 1.06) with the ranked target and penalty 100, and +4.32 (t 1.74) with the raw target and penalty 1.

Ledger: `mistake-2026-10-07-3` (design layer: the code delivered without its sector file) and `mistake-2026-10-07-4` (agent layer: a substitute filter reported as the workspace's filter).

## 6. F6 — open referee findings

| Finding | Result |
|---|---|
| `brief:missing` for 6 October | **Generated.** The brief's run had crashed on the same missing bars (`sorted(sectors.items(), key=...)` met a None sector change); the sort now skips a missing value, and the 6-October entry (`brief-2026-10-06-1`, YELLOW on rules Y4 and Y6: 10-year 5.31%, VIX 15.01, book +0.37%) is appended from the template with the model's rejection recorded ("CLAUDE_CODE_OAUTH_TOKEN and ANTHROPIC_API_KEY not set" locally). Cleared. The referee now asks for 7 October, which tonight's nightly writes. |
| `rates:stale`, series two business days behind | **Cause found; lag set per series.** On 6 October at 21:16 ET FRED's constant-maturity series (DGS2, DGS10, DGS30, DFII10) still ended on 2 October while the breakeven (T10YIE) had 5 October; the 5- and 6-October values arrived together on 7 October at 16:16 ET (FRED's `Last-Modified`). FRED posts the H.15 series the business day after the observation, at times two; the CSV endpoint itself is not the cause (`Cache-Control: max-age=600`). `data/rates/global_rates_config.json` now allows two business days for the FRED daily series (us2, us10, us30, us_real10, us3m, effr, us_be10) with the observation documented in each series' `lag_note`; the referee flags a third. A second wrinkle is recorded for the owner: the rates vintage is written once per ET date, so a morning retry run that publishes the previous session writes the day's vintage before the close run can (the 6-October vintage was written at 07:30 ET with the 5-October session's state). |
| `options:captured_share`, 4 of the last 8 days | **Report only** (the external scheduler waits for the owner's setup). The index now reads 4 of the last 9 trading days: 28–29 September and 5 October had no run in the window; 6 and 7 October are `push_failed` (next row). |
| `options:vintage_missing` for 6 October, "provider error" | **There was no provider error.** Run 49 pulled every chain in the window ("vintage 2026-10-06: wrote 44, failed 0" at 15:49 ET) and then failed to push it: "push_failed — the 2026-10-06 vintage could not be pushed after three attempts" (15:53 ET). Run 51 on 7 October did the same ("wrote 44, failed 0", then push_failed). The cause: the workflow checks the repository out shallow, and the publish's `git rebase origin/main` fails on a shallow history once another bot has pushed, so three quick attempts over twelve seconds all failed. A retry of the push with a full history would have succeeded (the data was complete on the runner). Repairs: `fetch-depth: 0` on the snapshot workflow, six attempts with a longer backoff and an unshallow before retrying a failed rebase; the vintage index reads the step's own annotation and records `push_failed` (a new reason) instead of `provider_error` for both days. The next pull is tomorrow at 15:45 ET. |
| `governance:review_overdue`, 9 visibility overrides | **Decay confirmed active for each.** `visibility_from_registry` moves an override linearly to the sector prior over the 90 days past `review_by` (weight w = 1 − days late / 90) and retires it after two earnings cycles without review. On 7 October: AMZN (entry 17, review_by 13 Aug, 55 days late, w 0.39), ANET (20, 18 Aug, 50 d, 0.44), AVGO (22, 17 Sept, 20 d, 0.78 — served 19.3), ETN (19, 14 Aug, 54 d, 0.40), GD (21, 12 Aug, 56 d, 0.38), MSFT (18, 12 Aug, 56 d, 0.38), NVDA (20, 9 Sept, 28 d, 0.69 — served 16.9), ORCL (19, 23 Sept, 14 d, 0.84 — served 17.6), VRT (20, 12 Aug, 56 d, 0.38). The three on the board show the decayed value; the other six are not on the board and get it when scored. GD, MSFT and VRT reach the sector prior on 10 November, AMZN and ETN on 11–12 November. **For the owner's review:** confirm or re-register each with a fresh rationale and date; the finding stays until then. |
| `book:export`, no brokerage export | **Report only; owner action.** `holdings.json` is still the 30-September manual transcription. |
| `v4:calibration_evaluation` | **Report only.** `v4_calibration.json` lacks an out-of-fold evaluation with a fold definition; in-sample reliability is not calibration evidence. |

## 7. The referee before and after this order

**Before** (`reports/audit_2026-10-07_analyst_after.txt`, the committed tree at the close of the analyst-data order, run at 05:10 ET on 7 October): 29 findings, **1 CRITICAL** — `identity:position_price`, the 6-October positions published without a price. The referee itself had crashed on that data the night before and been recorded as 0 findings; F1 is the repair.

**After** (`reports/audit_2026-10-07_followup_after.txt`, run at 20:30 ET on 7 October, before tonight's nightly): 33 findings, **0 CRITICAL**, ending `REFEREE COMPLETE: 33 findings; 0 CRITICAL`. What changed:

- the CRITICAL is gone: the three positions are covered by errata entries and the referee says so (`errata:applied`, INFO); `tournament:werner_vs_book` is gone with it (the corrected tier NAV 239,269 is within 0.4% of the book);
- `options:vintage_missing` now names the real reason (`push_failed`, run 51) instead of a provider error;
- `brief:missing` moved from 6 October (generated) to 7 October, which tonight's nightly writes;
- `rates:stale` reads three business days behind 7 October with two allowed: the local data is still the 6-October fetch; tonight's fetch gets the 5- and 6-October values FRED posted at 16:16 ET today;
- new lines: `site:session` (the live site's session and age), `errata:applied`; the fail-closed line at the end.

Unchanged, for the owner: the nine `governance:review_overdue` overrides (section 6), `options:captured_share` (the external scheduler), `book:export`, `v4:calibration_evaluation`.
