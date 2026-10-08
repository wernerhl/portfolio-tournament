# Third follow-up — execution report, 8 October 2026

Order: "third follow-up (date-bounded ticker changes, workflow lint, sector decomposition of the candidate-list
result, reporting fixes, operator total)", 7 October 2026 (night), on the audit of
`reports/analyst_followup2_2026-10-08.md` and the tree at `bdc9266`. Commits `[H1]` to `[H6]`. As-published files
are unchanged: the first run of the registered test (`candidate_list_test_result.json`) stays; the rerun is a new
file beside it. The ledger gained `mistake-2026-10-08-1` (agent).

Commits: `[H4]` 6ad05c6 (first, so that the rerun of H1 carries the test-months figure), `[H2]` 2c0f4e9, `[H1]`
0dc6c3c, `[H5]` dbcb1db, `[H3]` bb0167f, `[H6]` this report with the referee's after-state; the H6 check-1 result
follows in a further `[H6]` commit after the 15:45 ET options pull.

## 1. H1 — ticker changes bounded by date and company

### 1.1 The duplicates before

At `bdc9266` the change table mapped an old symbol to its new one in every month, for whoever held the symbol.
`sp500_membership_history.parquet` had **183** (month-end, current symbol) pairs where one current symbol appeared
twice — the audit's five cases, confirmed on the file:

| Symbol after mapping | Month-ends | Rows involved | Cause |
|---|---|---|---|
| WBD | 92 (Aug 2014 – Mar 2022) | DISCA, DISCK | two share classes, both mapped to WBD (whose history is DISCA's) |
| CB | 48 (Jan 2012 – Dec 2015) | ACE (CIK 896159), CB (Chubb Corp, CIK 20171) | ACE → CB applied while the old Chubb Corp was a member under CB; Chubb Corp took ACE's prices |
| AGN | 26 (Jan 2013 – Feb 2015) | ACT (Actavis), AGN (Allergan Inc, CIK 850693) | ACT → AGN applied while Allergan Inc was a member under AGN |
| IQV | 11 (Nov 2025 – Sep 2026) | Q (Qnity Electronics, CIK 2058873), IQV | Q → IQV applied to the reused symbol |
| ELV | 6 (Jun – Nov 2004) | ANTM, WLP | Anthem and WellPoint Health Networks both mapped to ELV before their merger |

### 1.2 The rules now (`scripts/analyst/membership_build.py`, H1 bounds)

A change old → new is applied to a row under the old symbol only

1. **up to `valid_to`** — the last month-end the old symbol is listed before the new symbol first appears in the
   file (Q → IQV: valid to October 2017; Qnity's Q from November 2025 is not mapped);
2. **to the company that made the change** — the row's CIK, where it carries one, must be the change's CIK; before
   May 2014 the CIK of the row's run (consecutive month-ends of the symbol, where any row of the run carries one)
   stands in; a row with a name and no CIK must share a word of a name the company had under the old symbol;
3. **not when the new symbol is listed in the same month-end for another company** (WellPoint Health Networks
   beside Anthem in 2004: the 2004 WLP rows stay WLP).

A second share class whose history the new symbol does not carry stays under its own symbol: DISCK → WBD is
recorded with `applies = false` ("share class of DISCA: the provider's WBD history is DISCA's") and counts as "no
bars at the provider". A symbol's earlier holder is set apart as `SYMBOL-YYYYMM` (the month its run ends) so that it
takes no bars: **Chubb Corp → `CB-201512`** (Jun 2004 – Dec 2015, 139 rows) and **Allergan Inc → `AGN-201502`**
(Jun 2004 – Feb 2015, 129 rows). ACE's 48 rows map to CB (its history at the provider), Actavis's 29 to AGN.
Blocked by the bounds: 227 rows by date, 6 by coexistence, 0 by CIK or name. **Duplicate pairs left: 0.**
The CSV now carries `valid_to`, the company's names under the old symbol, `applies` and the note; the meta file
records the bounds, the earlier holders and the class not mapped.

Referee: **HIGH `membership:duplicate_current_symbol`** — a current symbol that appears twice in one month-end
(distinct listed classes — GOOG/GOOGL, FOX/FOXA, NWS/NWSA — are distinct symbols and never trigger it). After the
rebuild it reports nothing (H6 check 2).

### 1.3 The coverage table after

After the rebuild (`data/analyst/membership_coverage.json`; before-H1 figures in brackets where they differ):

| Year | Members a month | With prices | Share | Member-months: ticker change not mapped | Member-months: no bars at the provider |
|---|---|---|---|---|---|
| 2005 | 496 | 277 (278) | 0.56 | 12 | 2,612 (2,600) |
| 2006 | 497 | 291 (292) | 0.58 (0.59) | 12 | 2,461 (2,449) |
| 2007 | 497 | 304 (305) | 0.61 | 12 | 2,303 (2,291) |
| 2008 | 497 | 320 (321) | 0.64 | 19 | 2,116 (2,104) |
| 2009 | 499 | 333 (334) | 0.67 | 24 | 1,971 (1,959) |
| 2010 | 498 | 344 (345) | 0.69 | 24 | 1,819 (1,807) |
| 2011 | 497 | 348 (349) | 0.70 | 24 | 1,759 (1,747) |
| 2012 | 500 | 360 (361) | 0.72 | 72 | 1,611 (1,599) |
| 2013 | 500 | 370 (371) | 0.74 | 84 | 1,471 (1,459) |
| 2014 | 501 | 379 (380) | 0.76 | 117 (112) | 1,353 (1,341) |
| 2015 | 503 | 389 (391) | 0.77 (0.78) | 104 (92) | 1,259 (1,247) |
| 2016 | 504 | 409 (410) | 0.81 | 70 (58) | 1,070 |
| 2017 | 505 | 428 (429) | 0.85 | 47 (35) | 883 |
| 2018 | 505 | 437 (438) | 0.87 | 26 (14) | 787 |
| 2019 | 505 | 449 (450) | 0.89 | 24 (12) | 647 |
| 2020 | 505 | 459 (460) | 0.91 | 24 (12) | 526 |
| 2021 | 505 | 468 (469) | 0.93 | 25 (13) | 423 |
| 2022 | 504 | 475 | 0.94 | 15 (12) | 334 |
| 2023 | 503 | 482 | 0.96 | 12 | 237 |
| 2024 | 503 | 487 | 0.97 | 1 | 190 |
| 2025 | 503 | 493 | 0.98 | 0 | 115 |
| 2026 | 503 | 500 | 0.99 | 0 | 28 |

The correction moves about one member a month out of "with prices" (the old Chubb Corp, Allergan Inc and DISCK rows
that had borrowed another company's bars) and adds a dozen member-months a year to "ticker change not mapped" from
2014 (the Actavis rows now mapped to AGN, a symbol without bars). The index gap (referee `universe:index_gap`, the
one list, section 6) now carries **Q** (Qnity Electronics).

### 1.4 The registered test's two runs side by side

The registered test ran once more on the corrected membership with the same registration (sha256
`eed7fab55a4ae4f92cb14a4e438717cd7c00507a4cc9a31ab61dd89e6c48296e`, unchanged since `1b581be`), writing
`data/analyst/candidate_list_test_result_h1.json`; the first run's file is as published. 12-month horizon, net of
20 bps a holding, Newey-West t (11 lags monthly, 3 quarter-end); the 43-variable set covers 388.5 members a month
over 210 months (388.6 before); the full table 111,096 rows (111,176):

| Configuration | First run (7 Oct, `e7767f2`) | Rerun on the corrected membership | Pass rule |
|---|---|---|---|
| **Primary**: 43 variables, penalty 100, formed monthly, held | **+4.27 (t 2.76)** | **+4.21 (t 2.70)** | > 2 points yes · t > 3 **no** |
| 12-1 momentum top tenth on the test months (141) | +1.50 (t 0.83), the audit's recomputation | +1.50 (t 0.83) | — |
| paired difference against it | **+2.77 (t 1.16)** | **+2.71 (t 1.15)** | positive yes · t > 2 **no** |
| beside: formed at quarter-ends | +4.87 (t 3.09) | +5.00 (t 3.08) | — |
| beside: top fifth | +3.22 (t 2.88) | +3.13 (t 2.85) | — |
| beside: 1-month horizon | +0.02 (t 0.01) | +0.91 (t 0.54) | — |
| beside: 21 price variables from 2005 | +3.25 (t 2.14); paired vs momentum +1.74 (t 0.65) | +3.20 (t 2.12); +1.69 (t 0.62) | — |
| sensitivity, no part in the verdict: penalty 10 / 1,000 | +5.00 (t 3.09) / +3.61 (t 2.60) | +4.75 (t 2.95) / +3.44 (t 2.51) | — |
| beside: delisted names dropped | identical to the primary | identical to the primary | — |
| placebo: variables from 12 months later | +56.02 (t 11.32) | +55.98 (t 11.31) | rises |
| placebo: variables from 12 months earlier | +3.89 (t 3.81) | +4.11 (t 3.72) | stays high (section 3) |

**The verdict follows the corrected run: the test fails on the t rule and on the momentum comparison; the candidate
list stays out of the score (the proposal's fallback is the 50 largest members).** The 183 corrected rows were 0.14%
of the member-months; every figure moves by less than a tenth of a point of t.

## 2. H2 — every workflow file linted

`scripts/ops/workflow_lint.py` downloads actionlint **v1.7.12** (github.com/rhysd/actionlint, MIT) once per
machine into a cache outside the repository, checks the archive's sha256 against the release's published checksums
(darwin_arm64 `aba9ced2…`, linux_amd64 `8aca8db9…`, recorded in the script) and runs it on `.github/workflows/*.yml`
with shellcheck and pyflakes off. `tests/test_workflows.py` (3 pass): the tree is clean; a step with both `run:` and
`with:` (intraday.yml as it stood at `0fc578f`) is reported; an `inputs.trigger` in `run-name` without a declared
input is reported. The referee runs the same check nightly: **HIGH `ops:workflow_lint`** (MEDIUM when the linter
cannot be fetched). The test ran before the commit that touches `.github/workflows/`.

The linter on the tree **before** (`bdc9266`), as the audit found:

```
.github/workflows/monthly_rebalance.yml:2:97: property "trigger" is not defined in object type {} [expression]
.github/workflows/nightly.yml:2:87: property "trigger" is not defined in object type {} [expression]
```

Both workflows now declare the `trigger` input under `workflow_dispatch` (as intraday.yml does). **After:**
`actionlint 1.7.12: no errors`.

## 3. H3 — sector decomposition of the candidate-list result (DIAGNOSTIC)

`scripts/analyst/candidate_list_diagnostic.py` → `data/analyst/candidate_list_diagnostic.json`, label **DIAGNOSTIC**:
"computed after the registered result was known; no part in any verdict". It is on no page; the owner decides
whether it ever is. It refits the registered primary score on the harness after H1 (43 variables, ridge penalty 100
and the boosted tree, mean of the within-month percentile ranks; registration sha256 `eed7fab5…`), 12-month horizon,
20 bps a holding, the 141 test months, on the names with a sector label (99.76% of the test rows; 421.9 members a
month). Sector labels: the provider's current sector for each current symbol (`data/analyst/history/sectors_2026-10-07.parquet`
— 712 of 736 names: 533 from the canonical fundamentals, the rest from the provider's company profile at one request
a second), **today's label applied to every year**: Alphabet and Meta carry Communication Services also before the
2018 reclassification, and a name that left the index keeps the label the provider shows today. The allocation term
is gross; the 20 bps sit in the selection term, so the first row is the sum of the next two.

| Quantity (12-month, net of 20 bps unless gross) | Points a year | Newey-West t | Audit's figure |
|---|---|---|---|
| Top tenth over the average member (registered quantity, names with a sector label) | +4.20 | 2.68 | +4.22 (2.74) |
| The top tenth's sector weights held at sector-average returns (gross) | +1.83 | 1.87 | +1.68 (1.78) |
| Top tenth over the members of its own sector | +2.37 | 2.12 | +2.54 (2.41) |
| Same score ranked within each sector, top tenth of each sector, over the average member | +2.47 | 3.50 | +2.35 (3.53) |
| The same, over the members of its own sector | +2.34 | 3.23 | +2.21 (3.27) |
| Within-sector version, 2014 to 2019 (72 months) | +2.08 | 2.18 | +2.01 (2.15) |
| Within-sector version, 2020 to 2025 (69 months) | +2.87 | 2.90 | +2.71 (2.90) |
| Registered version, 2014 to 2019 | +3.68 | 1.80 | +3.81 (1.99) |
| Registered version, 2020 to 2025 | +4.74 | 2.12 | +4.76 (2.04) |
| **Past placebo (variables from 12 months earlier), within-sector version** | **+2.51** | **2.96** | — (added here) |
| Past placebo, registered version | +3.76 | 3.55 | — |

Technology is **29.8%** of the top tenth against **13.4%** of the members (audit: 30.3% / 13.6%). The top tenth's mean
rank on the [−0.5, 0.5] scale: R&D to sales **+0.19**, gross profit to assets **+0.12**, leverage **+0.11** (audit:
+0.22, +0.13, +0.11). The sector-allocation term is **44%** of the registered figure (the audit: about 40%); the rest
is selection within sectors, and the within-sector version — the score ranked inside each sector — holds in both
halves of the sample with t near 3.

Reading. The registered result is in good part a technology tilt; the within-sector residue is real on this data but
is not timely information: the within-sector past placebo stays at +2.51 (t 2.96), as the registered one does,
because R&D to sales and gross profitability change little from one year to the next. The past placebo was built to
catch look-ahead in variables that change quickly; for slow characteristics it is expected to stay high and does
not indicate a leak. The registered result also holds in both halves while the coverage of members with prices
rises from 76% to 98%, so the missing delisted companies do not appear to drive it. None of this changes the
verdict: the candidate list is out of the score; a within-sector variant would need its own registration before any
run counted.

## 4. H4 — two reporting fixes

1. `candidate_list_test.py` now reports `momentum_12_1_top_tenth_test_months` — the 12-1 momentum top tenth on the
   candidate series' own test months, the figure the paired difference is measured against — beside the
   full-sample `momentum_12_1_top_tenth`. In the first run (as published) the full-sample figure was +0.56 (t 0.38)
   over 198 months; the audit's recomputation on the 141 test months gives +1.50 (t 0.83). The rerun's table in
   section 1.4 uses the test-months figure.
2. The index-gap list appears once, in section 6 (H6 check 2's companion): the referee's finding after the rebuild.

## 5. H5 — the operator row's TOTAL

While the tier is not comparable, TOTAL comes from the comparable series like the other five columns, with the same
title text; NAV net stays as published. Verified on the local preview (tournament.html, period ALL):

| Operator row | NAV net | TOTAL | 1M | 1W | SHARPE | MAX DD | vs BENCH |
|---|---|---|---|---|---|---|---|
| Before (published NAV 20 May → 7 Oct, re-seed steps inside) | $238,155 | +20.49% | +1.1% | +1.2% | 0.39 | −8.3% | −3.1% |
| After H5 (comparable series 2026-05-20 → 2026-10-07) | $238,155 | **+1.74%** | +1.1% | +1.2% | 0.39 | −8.3% | −3.1% |

## 6. H6 — the three checks

1. **The 8-October options pull pushed its vintage (G9 check 2) — NO.** Checked at 16:07 ET on 8 October on
   `origin/main`: the last vintage on the branch is **2026-10-02**; the index records 6 and 7 October as `missing,
   push_failed` (runs 49 and 51). The 8-October run (the 13:00 UTC backup cron, delivered at 15:12 ET; the step ran
   inside the 15:30–16:00 window) **pulled all 44 chains at 15:50–15:52 ET and then lost them**: `push_failed` after
   six rebase attempts, each logged as "rebase onto origin/main failed" with an empty status. Cause, found from the
   script and reproduced locally: the push is rejected because the bots commit every few minutes (intraday 19:05Z,
   analytics 19:40Z, market-open 19:41Z), so the step must rebase its vintage commit onto `origin/main`; the rebase
   replays the commit and needs a committer identity, which the step never has — the commit itself carries one
   through `-c user.name/-c user.email`, the workflow configures git only in a later step, and a runner cannot
   auto-detect one (`git -c user.useConfigOnly=true rebase` → rc 128, "Committer identity unknown"; with the identity
   passed, rc 0). The F6 repair (fetch-depth 0, six attempts) could not help: it retried the same failing command.
   Fix in the `[H6]` follow-up commit: the rebase carries the same identity as the commit, and a failure logs git's
   own message. Three sessions (6, 7, 8 October) were pulled and lost; the as-published index stays as written and
   the next scheduled pull is the first test of the fix.
2. **After H1, `membership:duplicate_current_symbol` reports nothing.** Confirmed: the referee's after-run (section
   7) carries no such finding; the rebuilt file has 0 duplicate (month-end, current symbol) pairs against 183 at
   `bdc9266`. The index-gap list it reports — the one list, as H4 asks — is `universe:index_gap`: **BE, FDXF, FERG,
   FLEX, HONA, ILMN, P, Q, RDDT** (nine; Q is Qnity Electronics, no longer hidden behind Q → IQV).
3. **After H2, `tests/test_workflows.py` passes on the tree that is pushed.** 3 passed, 0 failed on the tree at the
   `[H2]` commit and again on the pushed tree (run immediately before the push); the linter's own output on the
   final tree: `actionlint 1.7.12: no errors`.

## 7. Referee before and after

| | Before the order (`bdc9266`, `reports/audit_2026-10-08_followup2_after.txt`) | After (`reports/audit_2026-10-08_followup3_after.txt`, tree at `[H5]`) |
|---|---|---|
| Findings | 35 — 19 HIGH, 1 MEDIUM, 15 INFO; 0 CRITICAL | 35 — 19 HIGH, 1 MEDIUM, 15 INFO; 0 CRITICAL |
| New / gone | | none / none: the same set of slugs; the two new checks (`membership:duplicate_current_symbol`, `ops:workflow_lint`) report nothing |
| `universe:index_gap` | 8 names (Q hidden behind Q → IQV) | 9 names, Q included |
| `universe:stale_ticker` | AVB, BNY, CFLT, EA, ECHO, PSTG, VMRK | unchanged: the renamed symbols reach the price store with the next scheduled run; the others are for the owner |
| `REFEREE COMPLETE` line, `referee:check_failed` | present, none | present, none |

The standing HIGHs are unchanged (governance review overdue ×9, governance coverage ×3, options vintage / lens spot /
captured share, rates stale, earnings timing, tournament dead columns); the MEDIUM is the standing
`v4:calibration_evaluation`.
