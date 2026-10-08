# Second follow-up to the analyst-data report — execution report, 8 October 2026

Order: "second follow-up (reconciliation correction, membership from 2004, ticker changes, universe list,
candidate-list test, snapshot cut-off, referee hardening, rates vintage, operator row)", 7 October 2026 (evening).
Commits `[G1]` to `[G9]`, in order. As-published files are unchanged throughout; corrections went to
`data/errata.json`; the ledger `data/mistakes.jsonl` gained three entries (-3, -4, -5 of 7 October).

## 1. Summary

| Item | State | Where |
|---|---|---|
| G1 reconciliation correction | done — the gap is the variable set and training history, not a sector filter; the repository's filter is look-ahead and now named so | `data/analyst/reconciliation_correction.json`, `[G1]` 8914e1e |
| G2 membership from June 2004, ticker changes, panels to 2005, Task D rerun | done — 268 month-ends, 77 ticker changes, coverage table by year, META from Dec 2013; the rerun fails the pass rule as before | `scripts/analyst/membership_build.py`, `data/analyst/membership_coverage.json`, `data/analyst/walkforward_test_2005.json`, `[G2]` 3abd8a4 |
| G3 universe lists, two referee checks | done — BK→BNY, EQR→VMRK, SATS→ECHO; `universe:stale_ticker`, `universe:index_gap` | `[G3]` dcce0de |
| G4 candidate-list test | registered before the run (sha256 `eed7fab5…`), then run — see section 5 | `[G4]` 1b581be, then the result commit |
| G5 snapshot availability cut-off | done — close-of-session rule, derived on every read, five tests, ledger -5 | `scripts/analyst/snapshot_common.py`, `[G5]` |
| G6 referee hardening | done — traceback detected by line; errata compared with the previous commit; tests | `scripts/audit_status.py`, `scripts/errata.py`, `[G6]` |
| G7 rates vintage named by session | done — erratum for `2026-10-06.json`; `rates:vintage_session` | `scripts/rates/fetch_global_rates.py`, `[G7]` |
| G8 operator row from the comparable series | done — 1M, 1W, SHARPE, MAX DD, vs BENCH from the comparable series while the tier is not comparable | `app.js`, `[G8]` |
| G9 five checks after the nightly | four confirmed, one pending (the 8-October options pull runs at 15:45 ET) | section 10 |

Referee: 33 findings, 0 CRITICAL before the order (`reports/audit_2026-10-07_followup_after.txt`);
after the order see section 10.

## 2. G1 — the reconciliation correction

The first follow-up's reconciliation (step 4) attributed the gap between the design workspace's t ≈ 2.1 and the
repository's t ≈ 0.8 to "the workspace's sector filter". The audit's rerun of the workspace code
(`research/ml_stratification_test/audit_rerun/agent.py`, `mine.py`, run again here and matching the audit's rows
exactly: a −2.55/−1.07, b 1.61/0.54, c 2.38/1.22, c2 −2.17/−0.97, d −2.75/−1.19, d2 1.46/0.49, e 4.03/1.66,
f 1.97/0.60, g 2.08/1.06, h 4.32/1.74) shows what the workspace does: it trains the 43 variables from June 2010
on the members that have fundamentals and never filters on a label. The repository's step-4 filter kept the names
with a sector label in **today's** canonical fundamentals — the current universe — which removes every company
that later left the index: a look-ahead filter.

Corrected table (top tenth, 12-month horizon, net of 10 bps; Newey-West t):

| Variables | Workspace from 2012 | Repository | Workspace from 2005 |
|---|---|---|---|
| 5 price | −3.49 (t −1.27) | −2.55 (t −1.07) | −2.94 (t −2.27) |
| 21 price | +1.42 (t 0.44) | +1.61 (t 0.54) | +2.85 (t 1.95) |
| 43 (price + fundamentals) | +2.44 (t 1.27) | +2.38 (t 1.22) | +2.64 (t 2.06) |

On the same variable set and the same training window the two implementations agree within 0.3 points and
0.1 of t. The gap in the first reconciliation came from the variable set (5 vs 21 vs 43) and from how far back the
training history reaches, not from any universe filter.

Repository changes: `build_table`'s `sector_known_only` is renamed `current_universe_only`, documented as
look-ahead and kept only for the record of this correction; every option is now written into the result's
`table.options`; a registered run that sets it is **CRITICAL `analyst:lookahead_filter`**. The same commit carries
the F4 check `analyst:provider_rows_in_test` (provider-reported consensus rows inside a test), which the F4 commit
had not actually landed (found while placing the new check). `info.csv` and the audit rerun live under
`research/ml_stratification_test/`. Ledger: `mistake-2026-10-07-3` (advisor: the workspace code was delivered
without its data and info table) and `-4` (agent: the look-ahead filter taken for the workspace's filter).
The correction section is appended to `reports/analyst_followup_2026-10-07.md`; its original text stands.

## 3. G2 — membership from June 2004, ticker changes, the panels, the coverage table, Task D rerun

### 3.1 Sources and the file

`data/analyst/sp500_membership_history.parquet` (built once by `scripts/analyst/membership_build.py`):
268 month-ends 2004-06-30 to 2026-09-30, 134,317 rows, 495–505 members a month, 1,026 tickers as listed,
956 current symbols. Columns: `month_end, ticker, ticker_current, cik, name, source, revid, rev_time`.

| Period | Source |
|---|---|
| 2004-06 to 2012-01 | github.com/fja05680/sp500, "S&P 500 Historical Components & Changes (Updated)" (MIT; cached copy in the session's scratch space, not committed); the latest dated row at or before each month-end |
| 2012-01 to date | the Wikipedia list's revision in force at each month-end (177 revisions; the Security name from 2012, the CIK from May 2014) |

One finding about the components list: its "(Updated)" file carries each company under its **later** symbol
throughout (MDLZ for Kraft Foods in 2005, ANTM for WellPoint), and the repository's "original" file turned out to
carry the same later symbols (identical sets on all 2,595 common dates), so no free source gives the symbol of the
day before 2012. The pre-2012 rows therefore carry the list's symbol, mapped on to today's symbol by the change
table; this is recorded in the meta file's `ticker_convention`.

### 3.2 The two sources compared, 2012–2026

Mean number of symbols a month on which the Wikipedia revision and the components list disagree, as listed and
after the ticker changes are applied (`data/analyst/membership_source_comparison.json`, with the cases per month):

| Year | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| as listed | 61.8 | 54.8 | 44.8 | 34.7 | 28.3 | 20.1 | 4.6 | 0.2 | 1.0 | 0.0 | 0.1 | 0.2 | 0.1 | 0.4 | 0.7 |
| after the changes | 11.3 | 7.3 | 5.7 | 5.3 | 4.3 | 1.1 | 0.2 | 0.0 | 1.0 | 0.0 | 0.1 | 0.0 | 0.1 | 0.4 | 0.7 |

The residue in 2012–2016 is notation (GOOG/GOOGL before the 2014 split, NWSA/FOXA before the 2013 split, TYC, UA/UAA,
the unresolved three below). In September 2026 the lists differ by six names: Wikipedia has BE, ILMN, P where the
list has BLDR, TAP, TTD — the list's maintainer had not entered the September changes. Where they differ the
Wikipedia revision is used.

### 3.3 Ticker changes (`data/analyst/ticker_changes.csv`, 77 rows)

| Method | n | Pairs (old→new; today's symbol in brackets where the chain continues) |
|---|---|---|
| confirmed by SEC CIK (delivered with the order) | 36 | ABC→COR, ANTM→ELV, ARNC→HWM, BHGE→BKR, BK→BNY, BLL→BALL, CBG→CBRE, COH→TPR, CTL→LUMN, DISCA→WBD, DISCK→WBD, DLPH→APTV, EQR→VMRK, FB→META, FLT→CPAY, HCN→WELL, HRS→LHX, JEC→J, KORS→CPRI, LB→BBWI, LUK→JEF, MHFI→SPGI, MMC→MRSH, NLOK→GEN, NU→ES, PCLN→BKNG, PEAK→DOC, PKI→RVTY, RE→EG, SATS→ECHO, TMK→GL, UA-C→UAA, UTX→RTX, VIAC→PARA, WLTW→WTW, ZMH→ZBH |
| components-list continuity (the list's later symbol against the revision's symbol of the day, same run of months; the SEC's former names of the candidate's CIK as tie-break) | 11 | KFT→MDLZ, SAIC→LDOS, JDSU→VIAV, WPO→GHC, PCS→TMUS, DPS→KDP, CSC→DXC, BHI→BKR, WYND→TNL, HSH→SLE, BTU→BTUUQ |
| Wikipedia CIK continuity (same CIK, new symbol, consecutive revisions) | 19 | WLP→ANTM (ELV), WAG→WBA, ACT→AGN, GCI→TGNA, KRFT→KHC, MWV→WRK, ACE→CB, AA→ARNC (HWM), TSO→ANDV, Q→IQV, DWDP→DD, HCP→PEAK (DOC), SYMC→NLOK (GEN), BBT→TFC, VIAB→VIAC (PARA), COG→CTRA, FISV→FI (FISV), CDAY→DAY, FI→FISV |
| Wikipedia name continuity (same Security name, new symbol, before the CIKs) | 6 | BF-B↔BFB (notation; resolves to BF-B), MHP→MHFI (SPGI), SAI→SAIC (LDOS), LTD→LB (BBWI), NAVIV→NAVI |
| SEC company list (a symbol the SEC no longer lists, found under its CIK's first ticker) | 5 | ESV→VAL, WYN→TNL, ADS→BFH, GPS→GAP, FBHS→FBIN |

Rules: chains are resolved to the current symbol; a cycle (FISV→FI→FISV, BF-B↔BFB) resolves to the symbol in the
latest month-end; a symbol the SEC still lists is never changed (NAVI stays NAVI beside its listed note JSM, which
the first draft had mapped it to); where the list's symbol is defunct and the revision's is the one listed today the
direction is reversed (WYND→TNL), unless the defunct side is a bankruptcy symbol (BTU→BTUUQ). The former-names
tie-break fetched four `data.sec.gov/submissions` records with `SEC_USER_AGENT` from the environment, cached
outside the repository.

Unresolved and reported in the comparison file: YHOO vs AABA (both defunct), DV vs ATGE (Adtalem is not in the
SEC's `company_tickers.json`, so no tie-break; 9 member-months), ANR vs ANRZQ (bankruptcy). HSH→SLE is recorded
with the reversed direction because "SLE" is a symbol the SEC lists today for another registrant; both Sara Lee
symbols are without bars, so nothing in the panels depends on it.

### 3.4 The panels

* Raw history: stamps `2026-10-07-3` (182 pre-2012 names: ratings for 41, earnings for 46, bars for 45 — the
  provider holds bars for a quarter of the names that left the index before 2012) and `2026-10-07-4` (the five
  mapped symbols BFH, FBIN, GAP, TNL, VAL); `sec_fund_records_2026-10-07-2.parquet` (694 companies, 41,134
  trailing-twelve-month records, availability dates 2009-04-15 to 2026-10-07). Written once, never rewritten.
* `panel_monthly.parquet`: 2005-01 to 2026-09 (`build_panel.py --from 2005-01-31`, union of the four stamps,
  736 names with bars). `panel_ext_monthly.parquet`: 109,753 rows, 685 names; members with EDGAR fundamentals
  0% before 2009 (XBRL company facts begin then), 73% in 2010, 83% in 2012, 87% in 2014, 95% in 2020, 98% in 2026.
  The builders and the harness key members by `ticker_current`.

### 3.5 Members with prices by year (`data/analyst/membership_coverage.json`)

| Year | Members a month | With prices | Share | Member-months: ticker change not mapped | Member-months: no bars at the provider |
|---|---|---|---|---|---|
| 2005 | 496 | 278 | 0.56 | 12 | 2,600 |
| 2006 | 497 | 292 | 0.59 | 12 | 2,449 |
| 2007 | 497 | 305 | 0.61 | 12 | 2,291 |
| 2008 | 497 | 321 | 0.64 | 19 | 2,104 |
| 2009 | 499 | 334 | 0.67 | 24 | 1,959 |
| 2010 | 498 | 345 | 0.69 | 24 | 1,807 |
| 2011 | 497 | 349 | 0.70 | 24 | 1,747 |
| 2012 | 500 | 361 | 0.72 | 72 | 1,599 |
| 2013 | 500 | 371 | 0.74 | 84 | 1,459 |
| 2014 | 501 | 380 | 0.76 | 112 | 1,341 |
| 2015 | 503 | 391 | 0.78 | 92 | 1,247 |
| 2016 | 504 | 410 | 0.81 | 58 | 1,070 |
| 2017 | 505 | 429 | 0.85 | 35 | 883 |
| 2018 | 505 | 438 | 0.87 | 14 | 787 |
| 2019 | 505 | 450 | 0.89 | 12 | 647 |
| 2020 | 505 | 460 | 0.91 | 12 | 526 |
| 2021 | 505 | 469 | 0.93 | 13 | 423 |
| 2022 | 504 | 475 | 0.94 | 12 | 334 |
| 2023 | 503 | 482 | 0.96 | 12 | 237 |
| 2024 | 503 | 487 | 0.97 | 1 | 190 |
| 2025 | 503 | 493 | 0.98 | 0 | 115 |
| 2026 | 503 | 500 | 0.99 | 0 | 28 |

"Ticker change not mapped" = no bar under the mapped symbol while the SEC lists the member's CIK under another
ticker that has bars, or the symbol is an `old` of the change table whose current symbol has no bars (the 2012–2015
peak is the GOOG/NWSA/UA notation cases and the three unresolved names). "No bars at the provider" = the current
symbol has no bars at all: the free provider drops most delisted names, so the early years carry a survivorship
tilt that no mapping repairs — 44% of the 2005 member-months have no price. Every test on this data carries the
label "free data, members with prices only"; the paid sources (Sharadar or Norgate, owner-approved) are the only
cure. Acceptance: **META is a member with prices from December 2013** (FB→META mapped; bars from May 2012).

### 3.6 Task D rerun on the extended history

`data/analyst/walkforward_test_2005.json` (table 111,176 rows, 268 months 2004-06 to 2026-09; the published
`walkforward_test.json` on 2012–2026 is unchanged). Top tenth, net of costs, excess over the average member,
Newey-West t; test years 2014–2026 in both:

| | Published (from 2012) | Rerun (from 2004-06) |
|---|---|---|
| 12-month, ridge: without analyst / with / paired | +2.60 (t 0.76) / +2.29 (t 0.94) / −0.31 (t −0.20) | +0.41 (t 0.11) / −0.29 (t −0.11) / −0.70 (t −0.67) |
| 12-month, boosted tree: without / with / paired | +4.03 (t 1.45) / +3.00 (t 1.56) / −1.03 (t −0.95) | +2.28 (t 0.84) / +1.73 (t 0.65) / −0.55 (t −0.70) |
| 1-month, ridge: without / with / paired | −1.16 (t −0.45) / −1.36 (t −0.60) / −0.21 (t −0.14) | −3.98 (t −1.12) / −3.62 (t −1.16) / +0.36 (t 0.29) |
| 1-month, boosted tree: without / with / paired | −1.91 (t −0.64) / +0.90 (t 0.33) / +2.81 (t 2.22) | −0.82 (t −0.24) / −1.70 (t −0.56) / −0.88 (t −0.85) |
| Placebo, analyst variables from 12 months later | +27.49 (t 6.51) | +27.32 (t 6.82) |
| Placebo, from 12 months earlier | +0.46 (t 0.17) | −0.11 (t −0.04) |

The pass rule fails on both histories; the longer training history lowers every figure. The one paired difference
that was positive with t above 2 on the published run (the 1-month boosted tree, +2.81, t 2.22) is −0.88 (t −0.85)
on the extended history: a single-configuration result of that size does not survive a change of training window.
The placebos behave as they should on both.

## 4. G3 — universe lists and two referee checks

* `data/canonical/universe.txt` and `data/screen/universe_535.txt`: BK→BNY, EQR→VMRK, SATS→ECHO (the provider
  serves only the new symbols). `scripts/build_universe.py` applies the change table through `ticker_map()` and
  writes `former_tickers` (29 current symbols with the symbols they replaced) and the table's path into
  `data/universe_meta.json`; `data/universe.txt` rebuilt (534 names).
* Referee: **HIGH `universe:stale_ticker`** — a universe name with no price bar in the last five sessions of
  `data/source/prices_daily.parquet`; **INFO `universe:index_gap`** — current index members (latest membership
  month, mapped to current symbols) not in the universe. Tonight's gap: BE, FDXF, FERG, FLEX, HONA, ILMN, P, Q,
  RDDT (nine September additions and symbols the screen's list has not taken in); the second share classes FOX,
  GOOGL and NWS are collapsed by the universe by design and are not reported.

## 5. G4 — the candidate-list test

Registration `data/analyst/candidate_list_test_registration.json`, committed before any run in `[G4]` 1b581be,
**sha256 `eed7fab55a4ae4f92cb14a4e438717cd7c00507a4cc9a31ab61dd89e6c48296e`**. Parameters: members at each
month-end from June 2004 mapped to current symbols, no filter on today's list (`current_universe_only` off — a run
that sets it is CRITICAL); the 43 variables (primary, trained from June 2010) and the 21 price variables (beside,
from January 2005); score = mean of the within-month percentile ranks of the ridge (penalty 100 on ranked
features and target; 10 and 1,000 as sensitivity with no part in the verdict) and the harness's boosted tree;
target = within-month rank of the 12-month return; expanding window retrained each January, test years
2014–2026, 1-month horizon beside; top tenth equal-weight formed monthly (primary) and at quarter-ends (beside);
delisted held to the last price (primary) and dropped (beside); 10 bps a trade both ways; Newey-West t (11 lags
monthly, 3 quarter-end); pass = top tenth > 2 points a year net, t > 3, and a paired difference against the 12-1
momentum top tenth > 0 with t > 2; placebo shifts ±12 months. Label: free data, members with prices only.

**Result (`data/analyst/candidate_list_test_result.json`, committed after the run in `[G4]` e7767f2; the file
records the registration's sha256): the test FAILS.** Table 111,176 rows, 268 months; the 43-variable set covers
388.6 members a month over 210 months from 2009 (EDGAR facts begin then), the 21-variable set 414.8 over 268.

| Configuration (12-month horizon, net of 10 bps, Newey-West t) | Top tenth | Pass rule |
|---|---|---|
| **Primary**: 43 variables, penalty 100, formed monthly, held to the last price | **+4.27 pts/yr (t 2.76)** | > 2 points: yes · t > 3: **no** |
| paired difference against the 12-1 momentum top tenth (+0.56, t 0.38) | **+2.77 (t 1.16)** | positive: yes · t > 2: **no** |
| beside: formed at quarter-ends (3 lags) | +4.87 (t 3.09) | — |
| beside: top fifth | +3.22 (t 2.88) | — |
| beside: 1-month horizon | +0.02 (t 0.01); quarter-end +0.92 (t 1.04) | — |
| beside: 21 price variables from January 2005 | +3.25 (t 2.14); quarter-end +3.74 (t 1.70); paired vs momentum +1.74 (t 0.65) | — |
| sensitivity, no part in the verdict: penalty 10 / 1,000 | +5.00 (t 3.09) / +3.61 (t 2.60) | — |
| beside: delisted names dropped | identical to the primary (see below) | — |
| placebo: every variable from 12 months later | +56.02 (t 11.32) | rises as it should |
| placebo: every variable from 12 months earlier | **+3.89 (t 3.81)** | **does not fall toward zero** |

Two readings the registration asks for:

* **Held vs dropped are identical** because on free data no name in the table has a price history that ends inside
  the test window: the provider holds bars only for symbols listed today, so a delisted member has no bars at all
  (section 3.5) and the "held to the last price" rule never fires. `panel_monthly` has zero names whose last price
  falls in 2014–2026. The beside configuration is uninformative on this data; it is not a harness defect.
* **The past placebo does not fall toward zero.** A copy of the score built from variables twelve months stale
  ranks the members about as well as the current one (+3.89, t 3.81, against +4.27, t 2.76). What the 43-variable
  score carries is therefore persistent characteristics — a style tilt (the valuation, quality and volatility
  variables move slowly) — not timely information. A tilt of that kind is what the registration's momentum
  comparison was meant to catch, and the paired difference against momentum is not distinguishable from zero.

The registration expected a failure of the t rule on the reconciliation's evidence (t ≈ 1.2–2.1); the registered
design (mean of the ridge and boosted-tree ranks, within-month rank target, members with fundamentals) came out
higher (t 2.76) but below the bar, and the momentum comparison fails. **Consequence, as registered: the
candidate list stays out of the score; the proposal's fallback is the 50 largest members.** A pass on free data
would in any case have stayed out of the score until confirmed on Sharadar or Norgate. Nothing in the
registration changed between the registration commit and the run; the referee checks `analyst:lookahead_filter`
(off) and `analyst:provider_rows_in_test` (none) on the result file.

## 6. G5 — the snapshot availability cut-off

Rule (`scripts/analyst/snapshot_common.py`): a snapshot is available from the capture's ET date when that date
is a trading day and the capture came **before the close** (16:00; 13:00 on the early-close days 2025-07-03,
2025-11-28, 2025-12-24, 2026-11-27, 2026-12-24, 2027-11-26); otherwise from the next trading session. The date is
**derived on every read** (`snapshot_available_from`); a stored `available_from` that differs is reported
(`stored_differs`) and never used. The index (`snapshot_index.py`) carries the derived date and the stored one as
`available_from_stored`; the referee reports a stored value that differs as **INFO `analyst:available_from_restated`**
— the files stay as written.

Tests (`tests/test_analyst_lookahead.py`, 9 pass): 15:50 ET on a trading day → that day; 17:30 ET → the next
session; 04:31 ET on d+1 → d+1; a Saturday capture → Monday; 13:30 ET on an early-close day → the next session
(12:30 → that day); a stored field that disagrees is reported and the derived date wins.

Ledger: `mistake-2026-10-07-5` (advisor: the first follow-up defined availability by the capture's calendar
date, which lets a post-close capture serve the session it was captured after).

## 7. G6 — referee hardening

* `scripts/audit_status.py`: a crash is recognised **by line** — a line beginning `Traceback (most recent call
  last):` outside a finding, or a missing `REFEREE COMPLETE` line — not by the word appearing anywhere in a
  finding's text. `tests/test_audit_status.py` (5 pass) covers a traceback inside a finding (not a crash), a real
  traceback, and a missing final line.
* `scripts/errata.py`: `compare_with_previous(repo, ref="HEAD")` reads the file at the previous commit and reports
  any entry deleted or edited (canonical-JSON comparison); `verify` runs it and the referee calls it alongside the
  per-entry hash check. `tests/test_errata.py` (4 pass): an edit without its hash, a deleted entry, an appended
  entry (clean), an unchanged file. During the order the first call passed a string path and crashed the
  tournament section (`referee:check_failed` cascades on regime and picks) — fixed to accept both.

## 8. G7 — the rates vintage is named by the session it holds

`scripts/rates/fetch_global_rates.py` names a vintage `data/rates/vintages/<session>.json` with
`session = PUBLISH_SESSION or last_completed_session(now_et())` and writes `session` and `naming` into the body;
the index is keyed by session. The already-published `2026-10-06.json` holds the 5-October session (written at
07:30 ET on 6 October by the morning retry); it stays as written, with erratum `erratum-2026-10-06-rates-vintage-1`
(`field: session`, published 2026-10-06, corrected 2026-10-05). Referee: **`rates:vintage_session`** — INFO when a
vintage's session differs from its name and an erratum covers it, HIGH otherwise.

## 9. G8 — the operator row from the comparable series

While the operator tier is not comparable, `renderLeaderboardBlock` builds its 1M, 1W, SHARPE and MAX DD from the
comparable series (`werner_comparable.series[].nav_comparable`: daily returns chain-linked with each re-seed step
excluded, errata applied) and vs BENCH from the benchmark over the series' own dates; NAV net and TOTAL stay as
published. Each of the five cells says so in its title. Verified on the local preview against the live page:

| Operator row | 1M | 1W | SHARPE | MAX DD | vs BENCH |
|---|---|---|---|---|---|
| Live before G8 (as-published NAV series, re-seed steps inside) | +19.7% | +35.4% | 0.99 | −29.6% | −832.0% |
| After G8 (comparable series, 2026-05-20 to 2026-10-07) | +1.1% | +1.2% | 0.39 | −8.3% | −3.1% |

## 10. G9 — the five checks after tonight's nightly; referee before and after

The nightly for the 7-October session ran at 01:36 UTC (scheduled 22:00 UTC; the cron arrived late again), finished
03:28 UTC, deployed 03:28:49 GMT.

1. **`data/analyst/snapshots/2026-10-07.json`**: `captured_at 2026-10-08T01:47:35+00:00` (21:47 ET on 7 October,
   after the close); stored `available_from 2026-10-07`, written by the code in force at the time. Under the G5
   rule the derived date is **2026-10-08**; the stored field stays as written and the referee reports it
   (`analyst:available_from_restated`). The 7-October snapshot therefore serves the 8-October session, not the
   7th.
2. **The 8-October options pull pushes its vintage**: scheduled 15:45 ET on 8 October — pending at the time of
   this report; to be confirmed from the options index after it runs.
3. **The live site serves the 7-October session**: `status.json` `session_date 2026-10-07`, `last_success
   2026-10-07T21:37:26-04:00`; `site:session` in the final referee run below.
4. **The operator tier's 7-October return is measured from the corrected 6-October value**: the published
   6-October row keeps `nav 191,067.57` (three positions without a price); the errata give 239,269.16; the
   7-October row is 238,154.79, which is **−0.47%** from the corrected value (and +24.6% from the published one).
   The comparable series carries 202,045.51 → 201,104.51, the same −0.47%; `errata_applied.dates` in
   `tournament.json` lists `2026-10-06: 5_werner`, and the page applies the errata on load (`applyErrata`), so the
   1-day and 1-week figures come from the corrected value.
5. **`status.json` no longer carries the 0-findings audit block**: tonight's block is `ran_at
   2026-10-08T03:28:02Z, n_findings 31, critical [], high [earnings:timing, governance:coverage,
   governance:review_overdue, options:captured_share, options:lens_spot_stale, options:vintage_missing,
   rates:stale, tournament:dead_columns]`.

**Found during the checks — a workflow file broken by F3.** Every push since the F3 commit (be56027) produced a
failed "Intraday Refresh" run with no jobs ("This run likely failed because of a workflow file issue"): the F3
edit had inserted the watchdog step between `actions/checkout` and its `with: sparse-checkout`, leaving a `with:`
on a `run:` step. The scheduled market-hours runs of 8 October would all have failed at start-up. Fixed in the
`[G9]` workflow commit (the `with:` moved back under the checkout step; the other workflows checked — none mixes
`run` with `with`/`uses`). The last intraday run before the break (23:41 UTC on 7 October) had succeeded, so no
session was lost; the four failed runs are start-up failures of the push events only.

Referee before the order: `reports/audit_2026-10-07_followup_after.txt` — **33 findings, 0 CRITICAL**.

Referee after the order (working tree at `[G8]`, `reports/audit_2026-10-08_followup2_after.txt`): **35 findings,
0 CRITICAL** — 19 HIGH, 1 MEDIUM, 15 INFO; the `REFEREE COMPLETE` line present, no `referee:check_failed`.

| | Before (33) | After (35) |
|---|---|---|
| New | | HIGH `universe:stale_ticker` (AVB, BNY, CFLT, EA, ECHO, PSTG, VMRK — no bar in 2026-10-01..07; BNY, ECHO, VMRK are the renamed symbols the price store has not fetched yet, the others are for the owner); INFO `universe:index_gap` (BE, FDXF, FERG, FLEX, HONA, ILMN, P, RDDT); INFO `analyst:available_from_restated` (2026-10-07: stored 2026-10-07 → derived 2026-10-08); INFO `rates:vintage_session` (2026-10-06 holds the 5-October session, erratum on record); HIGH `governance:coverage` ×2 and `tournament:dead_columns` from tonight's data |
| Gone | HIGH `brief:missing`, `nullguard`, `rates:vintage`, `tournament:freshness`, `xfile:vol_single_source` (cleared by tonight's nightly) | |
| `site:session` | 2026-10-06, 26.2 h since its last publish (at 03:28 UTC, before the deploy) | 2026-10-07, 2.2 h — check 3 confirmed |

The three new INFO findings are the order's checks reporting exactly the cases the order named (the post-close
snapshot, the mis-named vintage, the index gap). The remaining HIGHs are the standing ones (governance review
overdue ×9, governance coverage ×3, options vintage/lens/captured share, rates stale, earnings timing).

### Open items

* The 8-October options vintage (check 2) — confirm after 15:45 ET on 8 October.
* The unresolved ticker pairs YHOO/AABA, DV/ATGE, ANR/ANRZQ (section 3.3) and the survivorship of the free price
  history (section 3.5) — only a paid source cures the second.
* The deploy watchdog's crons (F3) still arrive late or not at all; the manual dispatch path works.
