# Fourth follow-up — execution report, 9 October 2026

Order: "fourth follow-up (benchmarks for the selection tests, Qwest mapping, a test of the options publish path, two
ledger entries, a READY line on the Screen page, a paper tier, entry-state twins, the operator chart)", 8 October
2026, on the audit of `reports/analyst_followup3_2026-10-08.md` and the tree at `64186c0`. Commits `[J1]` to `[J8]`
(in the order their data allowed: J3, J4, J5 first; J2 before J1 because J1's figures are computed on the J2
membership; J6, J7, J8 after). As-published files are unchanged; new fields were added to two result files as the
order asks, with the verdict fields untouched. The ledger gained `mistake-2026-10-08-2` and `-3`.

## 1. J1 — every selection test against SPY, QQQ and RSP

`walkforward_test.portfolio_series` now carries each series' raw horizon return and the month's average member;
`summarize_series` (and the candidate test's quarter-end summary, and the diagnostic) append a `benchmarks` block:
the series' average 12-month return net of the 20 bps beside SPY, QQQ and RSP over the same formation months
(monthly adjusted closes of the three funds, pulled once at one request a second into the raw history, stamp
`2026-10-08`) and the harness's own benchmark, with the paired differences against SPY and against QQQ
(Newey-West t, 11 lags monthly, 3 quarter-end). The blocks were added to `candidate_list_test_result_h1.json` and
`candidate_list_diagnostic.json` as new fields from a rerun of the same registered configuration on the J2
membership; the verdict fields and every other value stay as first written, and each file lists under
`fields_added[].recomputed_values_differing` the rerun's figures that differ (the primary top tenth +4.26, t 2.67
against +4.21, t 2.70 as written: J2 moved rows without prices out of the cross-section ranks). Recomputed on the
harness, 141 formation months, January 2014 to September 2025:

| Portfolio or fund | Average 12-month return | Audit's figure |
|---|---|---|
| QQQ | 20.37% | 20.37% |
| Registered top tenth (43 variables, net of 20 bps) | **16.67%** | 16.64% |
| Within-sector top tenth (DIAGNOSTIC, net) | **14.93%** | 14.76% |
| SPY | 14.34% | 14.34% |
| Average member with fundamentals and prices (the 43-set's cross-section) | 12.54% | — |
| Average member with prices (the harness's benchmark, all members) | 12.41% | 12.41% |
| RSP, the equal-weighted S&P 500 fund | 11.41% | 11.41% |

| Difference | Points a year | Newey-West t | Audit's figure |
|---|---|---|---|
| Registered top tenth minus SPY | **+2.33** | 1.41 | +2.30 (1.40) |
| Registered top tenth minus QQQ | **−3.70** | −1.59 | −3.73 (−1.58) |
| Within-sector top tenth minus SPY | +0.59 | 0.53 | +0.42 (0.37) |
| Within-sector top tenth minus QQQ | −5.44 | −2.07 | −5.60 (−2.09) |
| beside: top fifth minus SPY / minus QQQ | +1.31 (0.88) / −4.71 (−1.90) | | |
| beside: quarter-end formation (47 quarters, 3 lags) minus SPY / minus QQQ | +3.07 (1.71) / −3.14 (−1.32) | | |
| beside: 21 price variables minus SPY / minus QQQ | +1.30 (0.73) / −4.73 (−1.49) | | |
| beside: 12-1 momentum top tenth (test months) minus SPY / minus QQQ | −0.42 (−0.35) / −6.45 (−2.59) | | |
| sensitivity: penalty 10 / 1,000, minus SPY | +2.76 (1.56) / +1.33 (0.95) | | |
| placebo, variables from 12 months later, minus SPY | +54.04 (10.83) | | |
| placebo, variables from 12 months earlier, minus SPY / minus QQQ | +2.38 (1.88) / −3.64 (−1.41) | | |

Against the funds the registered score is about two points a year above SPY and nearly four below QQQ, neither
distinguishable from zero at the conventional level; the within-sector version is level with SPY and below QQQ at
t −2. **The RSP gap** (`membership_coverage.json`, `survivorship_tilt_vs_RSP`): the average member with prices
returned 12.41% a year against RSP's 11.41% over the same 141 months — **+1.0 point a year, t 4.67**. RSP holds every
member, including the companies that later disappeared, and charges about 0.2% a year; most of the gap is the
survivorship tilt of the free data, now a measured number beside every coverage table.

## 2. J2 — Qwest and the components-list rows bounded by the price history

A change applied to a components-list row (2004–2011, no name, no CIK) now holds only when the current symbol's price
history at the provider starts on or before the row's month-end; otherwise the row keeps its own symbol and counts
as "no bars at the provider" (`membership_build.py`, `j2_price_history_bound` in the meta; a symbol set apart as an
earlier holder, `CB-201512`, is not a change from the list and stays set apart). Rows the rule changed — 505, in
seven symbols; none had a price before, so no return in any test changes:

| Symbol in the list | Was mapped to | Rows | Months | The current symbol's first bar |
|---|---|---|---|---|
| **Q** (Qwest Communications) | IQV | 82 | 2004-06 – 2011-03 | 2013-05 |
| ARNC (Alcoa Inc, the list's later symbol) | HWM | 91 | 2004-06 – 2011-12 | 2016-11 |
| MWV (MeadWestvaco) | WRK | 91 | 2004-06 – 2011-12 | none (WestRock delisted 2024) |
| HSH (Hillshire) | SLE | 91 | 2004-06 – 2011-12 | 2019-02 (another registrant's symbol) |
| VIAB (Viacom) | PARA | 72 | 2006-01 – 2011-12 | 2021-02 |
| COG (Cabot Oil & Gas) | CTRA | 43 | 2008-06 – 2011-12 | none in the raw history (see note) |
| ESV (Ensco) | VAL | 35 | 2007-01 – 2009-11 | 2021-05 |

Note: CTRA (Coterra) has no bars in the analyst raw history although it is a current member — the raw history was
pulled from `data/universe.txt`, which lists it; the provider returned nothing for it on 7 October. It is listed for
the next raw download; it changes no test (the symbol's rows before 2021 carry no price in either case). After the
rule the membership file still has 0 duplicate (month-end, current symbol) pairs; the panels were rebuilt and the
coverage table moved by at most one member a month.

## 3. J3 — the options publish path tested without a git identity

`tests/test_options_publish.py` builds a bare `origin`, a publishing clone and a second clone that moves `origin`
first so that the push is rejected; `HOME` and `GIT_CONFIG_GLOBAL` point at an empty temporary folder, the identity
variables are unset and `user.useConfigOnly` is on (a runner cannot invent an identity from the machine's user; a
developer's Mac can, which would otherwise hide the defect); `snapshot_chains.publish()` runs against the clone and
the test passes when the vintage's `_meta.json` is on `origin/main`.

* On the code before `172aa60` (a worktree at `172aa60^`): **FAIL** — `publish() returned 'push_failed'; vintage on
  origin: False; the rebase in this environment says: Committer identity unknown | *** Please tell me who you
  are. | Run | git config --global user.email ... | git config --global user.name ...`; the six attempts logged
  `rebase onto origin/main failed (attempt n);` with an empty status, as on the runner.
* On the current code: **PASS** (1 passed, 0 failed); `origin/main` holds "another bot" and "🧾 options vintage
  2026-10-08 · pulled 15:50 ET".

The test runs before every commit that touches `scripts/options/` (none in this order besides the test).

## 4. J4 — two ledger entries

`mistake-2026-10-08-2` (agent): the F6 report of 7 October named the shallow checkout as the cause of `push_failed`
and said a push with the full history would have succeeded; the repair retried the same failing command and the
8 October chains were pulled and lost after it; the step's log printed an empty `git status` instead of git's
message. `mistake-2026-10-08-3` (advisor): the audit of 7 October accepted the F6 cause without reproducing it; a
third day of chains was lost before the real cause was found. Both carry `tests/test_options_publish.py` as the
check. Ledger verified intact.

## 5. J5 — the READY line at the top of the Screen page

One block above THE BOARD (`screen.js renderReadyStrip`), from the two files the page already loads
(`data/screen/scores.json`, `data/entry_state.json`), no new computation of states; the rule lives once in
`common.js readyStrip()` (shared with the home page) and once in `scripts/screen/ready_strip.py` (the test and the
referee). As rendered locally for the latest session (close of 2026-10-07, regime ELEVATED · R 0.373, DIAGNOSTIC):

```
READY ON THE BOARD · close of 2026-10-07 · DIAGNOSTIC                              regime ELEVATED · R 0.373
Full size: #4 PATH 13.07 · stop 11.02 (-15.7%)  #5 AVGO HELD 376.51 · stop 325.44 (-13.6%)  #17 ABNB 160.63 · stop 143.69 (-10.5%)
           #34 WDAY 184.26 · stop 166.69 (-9.5%)  #35 NVDA HELD 237.47 · stop 202.11 (-14.9%)  #37 POWL 197.74 · stop 159.21 (-19.5%)
           #255 BMNR HELD 24.66 · stop 15.82 (-35.8%)
Half size (earnings within 20 sessions): #1 LMT 499.22 · stop 488.54 (-2.1%) · earnings in 11 sessions  #2 GOOG HELD 347.37 · stop 316.83 (-8.8%) · earnings in 15 sessions
           #3 GEV HELD 997.09 · stop 834.95 (-16.3%) · earnings in 15 sessions  #7 QCOM 177.12 · stop 147.73 (-16.6%) · earnings in 20 sessions
           #10 GDDY 97.21 · stop 83.94 (-13.7%) · earnings in 16 sessions  #12 META 721.31 · stop 508.73 (-29.5%) · earnings in 15 sessions
           #16 TSM 472.20 · stop 395.15 (-16.3%) · earnings in 6 sessions  #18 RTX 180.26 · stop 176.70 (-2.0%) · earnings in 9 sessions
           #21 DASH 191.24 · stop 170.60 (-10.8%) · earnings in 20 sessions  #25 ADP 264.00 · stop 250.40 (-5.2%) · earnings in 15 sessions
           #26 IT 185.77 · stop 158.57 (-14.6%) · earnings in 19 sessions  #27 GE 303.62 · stop 295.43 (-2.7%) · earnings in 9 sessions
           #33 SCHW 95.58 · stop 92.46 (-3.3%) · earnings in 6 sessions  #36 HIG 126.92 · stop 118.04 (-7.0%) · earnings in 13 sessions
Changed since the previous session: DASH READY → READY-HALF (a passing trend gate (earnings within 20 sessions: half size))
           MCO READY-HALF → AVOID (trend gate failed: below the 200-day average with negative 12-month momentum)
           QCOM READY → READY-HALF (a passing trend gate (earnings within 20 sessions: half size))
States are rule outputs from the entry-state rules, version 3. They have not passed their registered validation. The page gives no buy or sell instruction.
```

BMNR carries rank 255: a held name outside the top 40 sits on the board with its universe rank. When the two files
carry different session dates the block shows both dates and `stale` in the warning colour and lists nothing. On a
360-px viewport every name is one unit (the earnings count may move to the next line as a second unit) and the page
has no horizontal scroll (document width 360). Home page: `READY on the board today: 7 full size, 14 half size ·
Screen` under the daily brief, linked to `screen.html#ready`. Words: the block uses none of buy, sell, best, edge,
alpha except in the order's own closing sentence ("gives no buy or sell instruction"), kept as worded.

Checks: `tests/test_ready_strip.py` (3 pass) — the block's two lines equal the board's READY and READY-HALF rows in
names and order; referee **HIGH `screen:ready_strip`** when the block's names differ from the board's READY rows or
the two files' sessions differ (tonight: nothing).

## 6. J6 — the STRATIFIED paper tier

Tier `6_strat`, STRATIFIED (`config.json strat_tier`; `scripts/strat_tier.py`, `scripts/analyst/strat_holdings.py`,
`scripts/strat_quarter_report.py`; integrated in `compute_nav.py`, `update_daily.py`, `backfill_sessions.py`; kept
apart from the four tiers and the operator by explicit allow-lists in the action log, the thesis and factor
readers, the entry-state cards and the earnings calendar). Equal weights, fully invested, no regime cash; rebalanced
on the last session of March, June, September and December to the holdings file of that month-end; the C1 cost
model, 10 bps one-way; start capital 100,000; first session **2026-10-09** (the order came after the 8-October
close), seeded with the 2026-09-30 holdings and the model fitted in January 2026.

**First holdings** — `data/tournament/strat_holdings/2026-09-30.json` (immutable; registration sha256
`eed7fab5…48296e` recorded; model fitted January 2026 on 68,949 month-end rows 2010-06 to 2024-12): 490 members
scored, top tenth = **49 names** (the order said "about 40"), in rank order with the score:

BKNG .994, MCK .978, GEN .976, AIZ .973, COIN .969, FICO .967, ABNB .965, CAH .962, GDDY .962, NTAP .962, SBAC .957,
TRMB .956, HLT .950, DVA .946, META .946, CVNA .945, EBAY .944, GM .936, MRK .934, QCOM .929, COR .923, HSIC .920,
MMM .918, IBM .915, MSCI .913, WYNN .908, HCA .906, TDG .903, MAR .901, ADSK .896, CBRE .895, LDOS .883, MO .883,
TPR .878, KR .876, AXON .874, GILD .874, TKO .874, PTC .873, KLAC .872, EXPE .869, NXPI .867, EW .861, LII .857,
MGM .857, CRWD .852, SYY .852, IT .845, MA .841.

A simulated seed at the 7-October closes: NAV 99,900 (10 bps on turnover 1.0), 49 positions at 2.0%, cash residue
$0.01. The tournament row (below the operator, outside the ranking, no rank number): `STRATIFIED PAPER TIER · paper
tier · DIAGNOSTIC · its registered test failed on 8 October 2026 · seeds 2026-10-09 with the 2026-09-30 holdings`,
with TOTAL, vs QQQ / vs SPY since its first session and a `holdings` link to the file in force. Checks:
`tests/test_strat_tier.py` (9 pass: equal weights and full investment; nothing before the first session; the
quarter-end file of that month-end; a late file applied on the first session it exists and marked `on_time: false`;
a holdings file never rewritten; the C1 cost; the registration sha256; the backfill carry-forward; the quarter
report before any session); a referee run on a scratch copy with a synthetic row carrying the tier: 0 CRITICAL, no
finding mentions it. `strat_quarter_report.json` reports "no session yet" until the first row; RSP is not in the
price store and is reported as such (no provider call).

Two things to know. (1) The quarter-end holdings file needs the analyst panel for that month-end; the raw download,
the features and the panel are built outside the nightly (the daily dumps live outside the repository and the CI
environment has no scikit-learn), so the file is produced by hand after each quarter-end close and committed; the
nightly applies it on the first session it exists and records a late one. (2) The tier marks its old positions at
the session's closes before trading at those closes, where the four tiers trade from the previous row's NAV — a
convention difference, recorded in the code.

## 7. J7 — entry-state twins 1e to 4e and their comparison

Four twins `1e` to `4e` run inside the same engine (`scripts/compute_twins.py`, `Twin(mode="entry_state")`),
identical to `1c` to `4c` — same `continuous_rules.json` parameters, scores, cash formula, costs and start capital
— and differing in the three rules of the order: **entry** (a RANK_ENTRY or SEED buys only a name whose entry state
on the session is READY, at the full target weight, or READY-HALF, at half the weight with the other half left in
cash; WATCH and AVOID are skipped and the next-ranked READY name is taken, bounded at rank 2K); **stop** (the
entry-state stop recorded on the day of purchase, fixed for the spell; a close strictly below it sells with the new
reason code `STOP_EXIT`; RANK_EXIT unchanged); **re-entry** (a name sold at its stop may be bought again only after a
later session shows it READY or READY-HALF). The entry-state rules are frozen at version 3: the config's sha256
`962fe81cf48b33370e1caf85e28f15a0413b9a8029f4ca031373fb8ebd87cdf0` (`data/entry_state_config.json`, the one the
v4 validation registration pins) is recorded in the rules block, in `twins.json` and in `twins_state.json`; a
session whose entry-state file carries another version, another sha or another session date makes the e twins
sit it out (the c twins proceed) and a rerun restarts them from the saved stops. First session **2026-10-09**;
nothing is written for the e twins before it. Trades and spells go to the existing logs with the new reason code;
the e twins are served under `twins.json → entry_state_twins`, which no page renders.

Two readings the order left open, stated in the rules block and easy to change before the first session: the
unfilled part of a slot (a skipped name, or the half of a READY-HALF) raises the e twin's cash target above the
formula's (`target_cash_pct` beside `formula_cash_pct`), because REGIME_CASH and DRIFT would otherwise re-invest it
within the session; re-entry after a stop happens at the close of the first later READY session.

**Comparison, fixed before any data** — `data/tournament/twins_e_comparison.json` (sha256
`e0b58973cbccd5f076c3a02452a7a67ec069900ef38dceeecfc96fadfd76d1e4`): the daily return of each e twin minus its c twin
after costs from the first common session, the pooled series the average across the four tiers; a monthly report
(`scripts/twins_e_report.py` → `twins_e_comparison_report.json`, nightly) with the pooled and per-tier differences
annualised, Newey-West t with 5 lags, and the largest drawdown of each twin; after three months the tracking
volatility of the pooled difference and the smallest annual difference that reaches t 2 at 12 and at 24 months; no
verdict before 12 months — at the NYSE session nearest 12 months after the start (2027-10-08) the entry rules
**help** if the pooled difference is positive with t above 2 and the pooled largest drawdown of the e twins is no
deeper than the c twins', **hurt** if negative with t below −2, otherwise no difference, and the same rule once more,
for the last time, at 24 months (2028-10-09); no automatic consequence for any tier or page. Today the report says
"no sessions yet".

**Planned first session (dry run on the 7-October data, `--out-dir` outside `data/`)** — `TICKER½` = half slot
(READY-HALF); weights c → e; the e twins start 50–75% in cash because October is earnings season and most READY
names carry the "earnings within 20 sessions" modifier:

| Tier (K) | c cash → e cash | e holdings (skipped top-K names → their replacements) |
|---|---|---|
| 1c/1e CAP PRES (12) | 52.9% → 74.5% | V½, ABBV½, MA½, JNJ½, LLY½, KO½, GL½, ALL½, MRK½, VRTX, GILD½, AFL½ (INCY, AMP, VEEV, DXCM in WATCH → MRK½, VRTX, GILD½, AFL½); c-only INCY, AMP, VEEV, DXCM, BMY |
| 2c/2e BALANCED (20) | 41.1% → 63.2% | GEN, SNDK½, EXPE, MU, NEM½, MS½, PLTR½, CRDO, META½, ANET½, SCHW½, EBAY½, CPAY½, ALAB½, HOOD½, PATH, V½, ADP½, ABBV½, GS½ (INCY, AMP, VEEV, DXCM WATCH and PAYX, FISV, ADBE AVOID → ALAB½, HOOD½, PATH, V½, ADP½, ABBV½, GS½) |
| 3c/3e AGGRESSIVE (15) | 21.6% → 49.9% | SNDK½, GEN, MU, CRDO, PLTR½, ANET½, META½, EXPE, CPAY½, ALAB½, MS½, NVDA, HOOD½, V½, FTNT½ (INCY, AMP, VEEV WATCH and PAYX AVOID → NVDA, HOOD½, V½, FTNT½) |
| 4c/4e TACTICAL (8) | 37.3% → 52.9% | SNDK½, GEN, MU, CRDO, PLTR½, ANET½, META½, EXPE (INCY WATCH, PAYX AVOID → META½, EXPE) |

55 SEED trades in the dry run; the live files were untouched. A confound to keep in the diagnostic table: on
9 October the c twins hold their 29-September picks carried by banded execution while the e twins seed on the
9-October ranking, so the first weeks of the e − c series carry a seed-date difference as well as the entry rules.
Checks: `tests/test_twins_e.py` (12 pass — the entry skip and replacement, the half weight and its cash, STOP_EXIT
strictly below a fixed stop, re-entry only after a later READY session, nothing before the first session, a stale
or re-versioned entry-state file sits the e twins out and a rerun restarts them, the c twin byte-identical with and
without the e block, the report on synthetic NAVs with the verdict sessions, the registration's consistency);
`tests/test_twins.py` still 13 pass. `compute_twins.py` now runs right after `entry_state.py` in the nightly (it ran
22 steps earlier; nothing in between reads its outputs), with `twins_e_report.py` after it. The first session's
holdings beside the c twins' are recorded after the 9-October nightly (scheduled check).

## 8. J8 — the operator tier drawn from the comparable series

While the tier is marked not comparable (`werner_comparable.comparable === false`), `buildSeries()` makes the
operator's line `werner_comparable.series[].nav_comparable`; the published NAV is kept aside and drawn as a thin
dotted line labelled `WERNER as published, includes re-syncs` on the race chart; the drawdown chart (home page and
tournament page) draws the operator's depth from the comparable series (`WERNER (comparable)`); the tooltip names
the series through the dataset label. The book page has no chart of the operator line. Rendered locally:

| Operator line | Sessions | Annualised volatility | Max drawdown | Total |
|---|---|---|---|---|
| Before (published NAV, re-syncs of 29 Sep, 30 Sep, 1 Oct; missing prices 6 Oct; rebound 7 Oct) | 97 (20 May – 7 Oct) | **99.5%** | −29.6% | +20.49% |
| After (comparable series) | 97 | **14.4%** | −8.3% | +1.74% |

Race chart datasets after: CAP PRES, BALANCED, AGGRESSIVE, TACTICAL, **WERNER (comparable)** (last 1.0174×), **WERNER
as published, includes re-syncs** (dotted, 1 px, last 1.2049×), SPY. Drawdown chart on the home page: the operator
as WERNER (comparable).

## 9. The first in-window options pull after this order

The first in-window pull after this order is Friday 9 October, 15:30–16:00 ET (a backup cron delivered inside the
window, or a dispatch). At the time of this report the last vintage on `origin/main` is still 2026-10-02 and the 6-,
7- and 8-October days are `push_failed`; the 8-October 17:00 UTC backup cron arrived at 17:50 ET, outside the
window, and wrote nothing (`outside_window`, as designed). Whether the 9-October vintage reaches `origin/main` — the
first real test of the identity fix (`172aa60`, `tests/test_options_publish.py`) — is recorded here by the scheduled
check after the 9-October nightly, in a follow-up `[J8]` commit.

## 10. Referee before and after

| | Before the order (`64186c0`, `reports/audit_2026-10-08_followup3_after.txt`, run after the 7-October nightly) | After (`reports/audit_2026-10-09_followup4_after.txt`, tree at `[J7]`, run on 8 October at 21:30 ET, before the 8-October nightly) |
|---|---|---|
| Findings | 35 — 19 HIGH, 1 MEDIUM, 15 INFO; 0 CRITICAL | 42 — 26 HIGH, 1 MEDIUM, 15 INFO; 0 CRITICAL |
| New | | HIGH `twins:rules_changed` — `twins.json` was computed under the previous `continuous_rules.json`; J7 adds the `entry_state_twins` block to that file (the order asks for the same file), no c parameter changes, and the nightly's recompute writes the new sha, so the finding clears with the 8-October nightly. The six others (`book:holdings_age`, `brief:missing`, `nullguard`, `rates:vintage`, `tournament:freshness`, `xfile:vol_single_source`) are the time-of-day findings of a run between two nightlies — the same six were "gone" in the third follow-up's after-run because that run came after a nightly. |
| Gone | | none |
| The order's checks | | `screen:ready_strip`: nothing (the block matches the board's READY rows); `membership:duplicate_current_symbol`: nothing; `ops:workflow_lint`: nothing; no finding mentions `6_strat` or the e twins |
| `REFEREE COMPLETE` line, `referee:check_failed` | present, none | present, none |

Tests on the tree: `test_options_publish.py` 1, `test_ready_strip.py` 3, `test_strat_tier.py` 9, `test_twins_e.py` 12,
`test_twins.py` 13, `test_workflows.py` 3 — all pass; every changed script parses on CI's Python 3.11; `app.js`,
`screen.js`, `common.js`, `pages.js` pass `node --check`.

### Open items

* The 9-October facts (section 9; the first session of `6_strat` and of the e twins) — the scheduled check after
  the 9-October nightly records them in a follow-up commit.
* The quarter-end holdings file of the paper tier is produced by hand (section 6); the December file is the first.
* CTRA (Coterra, a former member) has no bars in the raw history because the former-members download requested its
  Wikipedia-era symbol COG; listed for the next raw download.
* The twins' monthly review (`monthly_review.py`) discovers tiers from the shared logs, so from November the e twins
  appear under its "other" tiers; no page or consumer change was ordered.
