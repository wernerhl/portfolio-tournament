# Report — Tournament Audit and Execution Order (30 September 2026): continuous selection, trade logs, a mistakes ledger

Executed 30 September 2026 from the working copy at `/Users/whl/portfolio-tournament`, one commit per item [T1]–[T7]. Referee before (the served tree at 7b24098 judged by this order's referee, `reports/audit_2026-09-30_T_before.txt`): 29 findings, 1 CRITICAL — the twelve-session gap, which this order promotes from HIGH to CRITICAL and resolves; the previous referee read the same tree at 23 findings, 0 CRITICAL. Referee after: see section 7.1.

## T1 — Referee and the missing sessions (2f21167)

`scripts/backfill_sessions.py` filled the twelve sessions (24 and 26 June, 27 August, 16–28 September) under the as-published convention: every tier's shares as they stood in the previous row at the session's closes from the price store (SSO from the provider), cash at the previous row's EFFR, R from the revised series (no published vintage exists for a missed session; the row says so), the label from the hysteresis corridor, benchmarks anchored at inception; each row carries `backfilled: true`, the backfill date and a note. 79 → 91 rows; the operator tier holds its pre-re-seed names through 28 September; nothing already published is altered. `compute_nav.py` backfills before it appends the session's row and `compute_regime_v2.py` records a no-publish row for any session the vintage skipped, so a future gap heals on the next successful nightly. The referee's `tournament:gaps` is CRITICAL for the dated CSVs and for the tournament history (a row removed from a copy → CRITICAL; backfilled rows counted as INFO).

## T2 — The audit reproduced (6af8a45)

`scripts/tournament_audit.py` → `data/tournament/audit.json` (nightly) and `reports/tournament_audit_2026-09-30.md`. Against acceptance 7.2:

| finding | the order | reproduced |
|---|---|---|
| reconstitution dates per algorithmic tier | 1 June, 1 July, 3 Aug, 1 Sept; zero intra-month trades | identical, all four tiers; 0 intra-month trades |
| tier 4 cash gap on 3 June | 11.0 points | 11.0 (29 July: 9.2; mean absolute gap over all tiers 2.4, tier 4 3.3; maximum 14.2 on 10 June) |
| operator tier NAV | $195,250.91 (15 Sept), $249,639.07 (29 Sept) | identical; +27.9% between the published rows (+25.6% against the backfilled 28-Sept row) |
| missing sessions | twelve | twelve, the same dates; none missing now |
| label entries into ELEVATED below 0.32 | 0.3173, 0.3198, 0.3022 | those three and three more: 0.3027 (16 June), 0.3072 (6 July), 0.3177 (13 July) — six in all; 17 changes (9 dated in July, the order says eight) |
| GOOG + GOOGL in tier 2 | 7.0% combined | 6.9–7.0% (3.46 + 3.46) |
| spell hit rates vs SPY | 48, 56, 55, 54% | 48, 58, 52, 58% under the convention that reproduces tier 1 exactly (position prices, exit at the last held row, SPY from the rows); the price-store variant 55, 61, 52, 54%; 181 spells; mean excess +0.6 to +3.5%; every Wilson interval spans 50% |

The order's mean cash gap of 3.5 points is tier 4's under the audit's own count (3.3 here, 2.4 over all tiers); the hit rates for tiers 2–4 differ from the order's by two to four points under either convention — the convention is stated in the file and the difference is the first finding. The effective sample is five decision dates per tier (inception plus four reconstitutions), stated beside the spell count on the page.

## T3 — Fixes (7cc7e4c)

- **Hysteresis corridor.** `scripts/regime_label.py` is the one label function; compute_nav labels each row off the previous published row's label, the daily brief reads the row's label, the action ledger walks the published vintage sequentially, the signal alerts already applied the corridor. The referee raises CRITICAL on any row from 30 September whose label is not the corridor's (`label:corridor`). Earlier labels stay as published; the audit shows the corridor would have changed the label 5 times instead of 17, entering ELEVATED at 0.3877 (3 June) and 0.3233 (27 July). Under the brief's rules the 10-September flip would not have occurred.
- **Share classes.** `data/share_classes.json` lists the dual-class issuers and the class kept — the one the operator holds when there is one (GOOG), else the more liquid class measured once on 30 September (GOOGL $9.3bn a day against GOOG $6.2bn; FOXA over FOX; NWSA over NWS); `build_universe` drops the other class (GOOGL, FOX, NWS out; 535 names); `select_tiers` never picks two classes of one issuer. Tier 2's GOOG + GOOGL is an as-published holding until the 1 October reconstitution; `tournament:issuer_dup` (HIGH) says so meanwhile.
- **Operator tier.** `tournament.json` gains `werner_comparable`: `comparable: false` with the reason, the re-seed event of 29 September (names before and after, the step), and a series chain-linking the tier's returns with the step excluded. The leaderboard shows the tier last, unranked, NOT COMPARABLE, never the leader; the referee requires the block and refuses a comparable flag without a trades-based rebuild on record. The rebuild from the brokerage transactions export follows the export.
- **Retention** per reconstitution is on the tournament page as the noise indicator.

## T5 — C6 registered; the power check first (ed616e8)

`reports/c6_registration_continuous_vs_monthly_2026-09-30.md` registers the contestants, inputs, metrics, the paired block bootstrap (1000 resamples, 60-session blocks, seed 20260930), the decision rule R1 with R2 and R3 beside it, and a power threshold (a rule must tell two different monthly tiers apart in at least three of six pairs). `scripts/c6_power_check.py` applied the rules to the monthly tiers against each other first: R1 discriminates in 0 of 6 pairs, R2 and R3 in 2 of 6 — no candidate has power. The real comparison does not run; the twins run as a contest and replace nothing; a new registration with a power-checked rule is required before any comparison. This is Failure 14's failure mode caught before the comparison rather than after.

## T6 — The mistakes ledger (d2e9ffa)

`data/mistakes.jsonl`, append-only, hashed per entry; `scripts/mistakes_ledger.py` (seed, append, verify, test-append, from-trades); `mistakes.html`. The thirteen seed entries of the order carry each fix and the referee check that now catches a recurrence. Acceptance 7.6: `test-append` appends a test entry to a copy — 13 → 14 entries, prior entries unchanged, the chain verifies; the referee raises CRITICAL on an edited entry (mutation test). Operator decisions enter from the export-based action ledger nightly, with +20/+60 outcomes against not trading as separate entries; nothing to evaluate until the export lands.

## T4 — Continuous twins and the logs

`data/tournament/continuous_rules.json` freezes the rule of 4.1 (K per tier, δ = 2.0 tier-composite points, 2K exit buffer, 5-point cash gap, 25 percent drift, C1 cost, $100,000). `scripts/compute_twins.py` runs nightly after the signals — RANK_EXIT, RANK_ENTRY (open slots, then displacement by δ), REGIME_CASH on the corridor label, DRIFT — at the session's closes, with the session's cost charged as the tiers charge it (10 bps × one-way turnover in NAV-weight space including the cash sleeve, allocated pro rata to the trade rows; the backfill's four reconstitution turnovers reproduce the cost restatement's). The twins seeded on 2026-09-29 from all cash:

| twin | parent | NAV after cost | cash actual / target | positions |
|---|---|---|---|---|
| 1c | 1_cap_pres | $99,945.97 | 45.9% / 46.0% | LLY INCY V VEEV MA AMP DXCM ABBV MRK FDS AMGN GILD |
| 2c | 2_balanced | $99,934.57 | 34.5% / 34.6% | MU SNDK NVDA META FTNT NEM LLY CRDO INCY ANET PLTR CPAY V MSFT WDC NTAP VEEV GEN STX ALAB |
| 3c | 3_aggressive | $99,921.18 | 21.1% / 21.2% | MU SNDK NVDA META FTNT CRDO ANET LLY INCY PLTR NTAP WDC CPAY VEEV MSFT |
| 4c | 4_tactical | $99,927.96 | 27.9% / 28.0% | MU SNDK NVDA META FTNT CRDO ANET LLY |

Logs: `data/tournament/trades.jsonl` — 456 rows (401 for the monthly tiers backfilled from `tournament.json` and the scores committed at each reconstitution; 55 seed rows for the twins), each with reason code, the tier composite and rank, Business Quality and Trade-Now at decision (Business Quality from the screen's dated vintages from 29 July, Trade-Now from 3 June; earlier null with a note), the regime reading and label. `data/tournament/spells.jsonl` — 236 spells as events (opened, closed, follow-ups at 20 and 60 sessions) with the exit reason and the excess return against SPY and the thesis basket; 126 closed, 94 and 54 follow-ups already due. Each tier's detail on the tournament page renders both, newest first. `tests/test_twins.py`: 13 passed. The monthly tiers are unchanged.

## T7 — The monthly review

`scripts/monthly_review.py` generated `reports/reviews/review_2026-09.md` (index `data/tournament/reviews.jsonl`, sha256 844e02a7…; a second run refuses — never edited): per tier the five worst spells of the month with their scores at entry, the hit rate and mean excess, the effective sample size — 4, 5, 5 and 3 decision sessions for tiers 1 to 4 beside 21, 33, 21 and 12 spells, 1 for each twin — and the date-block bootstrap interval (2000 resamples of decision dates, seed 20260930) with the caption that fewer than five decision dates make it uninformative; the operator's month (no export-confirmed trades; the ANET and MU reports pending, not evaluated); the twelve September failures with fixes and checks; at most three candidate lessons as hypotheses. `monthly_rebalance.yml` runs it on the first of each month. Tests: 16 passed, including the proof that dates, not spells, are resampled.

## 7. Acceptance

1. **Referee before and after; zero CRITICAL; tournament:gaps resolved and promoted.** Before (this order's referee on the served tree at 7b24098): 29 findings, 1 CRITICAL — the gap; after (`reports/audit_2026-09-30_T_after.txt`): 27 findings, 0 CRITICAL; a row removed from a copy → CRITICAL. ✓
2. **Reproduce the audit.** Four reconstitution dates and zero intra-month trades ✓; tier 4's 11.0-point gap on 3 June ✓; $195,250.91 and $249,639.07 ✓; twelve missing sessions ✓; label entries at 0.3173, 0.3198, 0.3022 ✓ plus three more the order did not list; GOOG + GOOGL 6.9–7.0% ✓; spell hit rates 48, 58, 52, 58% against the order's 48, 56, 55, 54% — tier 1 exact under the stated convention, tiers 2–4 within four points (the convention is the first finding). ✓ with the stated discrepancies
3. **After the fixes: no gaps; no label entry below 0.32; no issuer held twice; the operator tier marked not comparable or rebuilt from trades.** No gap; the corridor governs every row from 30 September (CRITICAL otherwise); tier 2's GOOG + GOOGL is an as-published holding until the 1 October reconstitution, flagged HIGH meanwhile, the universe and the selector collapsed; the operator tier is marked not comparable and excluded from the ranking. ✓ (the share-class holding clears at the next reconstitution)
4. **Twins 1c–4c running with trade and spell logs populated from their first session; monthly tiers unchanged.** ✓ (seeded 2026-09-29; the nightly runs the engine)
5. **The C-series comparison registered, with the discriminating-power check reported first.** Registered; the power check shows the registered rule at 0 of 6 pairs (alternatives 2 of 6); no comparison runs until a rule with power is registered. ✓
6. **mistakes.html renders the seed ledger; one test entry appends without altering prior entries.** ✓ (13 entries; test-append on a copy 13 → 14, prior hashes unchanged)
7. **The first monthly review generated with effective sample sizes stated.** ✓ (`reports/reviews/review_2026-09.md`)

Deviations: the audit's hit rates for tiers 2–4 and the July flip count (9 against the order's 8) differ under every convention tried; the C6 rule lacked power on the controls, so the twins are a contest without a judge until a new registration; the operator tier's rebuild from trades waits for the export; the twins' Business Quality and Trade-Now at decision are null before the screen's vintages and the signals' first commits.

### Referee, verbatim

Before (this order's referee on the served tree at 7b24098):

```
last trading session: 2026-09-29
[CRITICAL] tournament:gaps              tournament.json history missing session(s) ['2026-06-24', '2026-06-26', '2026-08-27', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-21', '2026-09-22'] — backfill_sessions.py did not run
[HIGH    ] tournament:werner_comparable tournament.json carries no werner_comparable block (the operator tier must be marked not comparable until rebuilt from trades)
[HIGH    ] audit:missing                data/tournament/audit.json absent (tournament_audit.py did not run)
[HIGH    ] mistakes:missing             data/mistakes.jsonl absent
[HIGH    ] xfile:vol_single_source      intraday vix 15.92 vs canonical 16.04
[HIGH    ] nullguard                    intraday.vvix is null; dependent safety checks must read IMPAIRED not false
[HIGH    ] options:vintage_missing      no chain vintage for the last session 2026-09-29 (latest: 2026-09-25)
[HIGH    ] options:lens_spot_stale      held names whose lens spot is not the last session 2026-09-29: ['AVGO: 2026-09-25 close', 'BMNR: 2026-09-25 close', 'GEV: 2026-09-25 close', 'GOOG: 2026-09-25 close', 'NVDA: 2026-09-25 close']
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override AVGO review_by 2026-09-17 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override NVDA review_by 2026-09-09 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ORCL review_by 2026-09-23 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[INFO    ] tournament:freshness         loco_cv_results.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         ml_indicator_weights.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_loadings.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_variance_explained.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v3_correlation.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           watchlist_top30.csv: no date axis found (static config?)
[INFO    ] book:export                  no brokerage export on record (holdings_export.json absent); holdings.json source: brokerage positions, 2026-09-30 (manual transcription from the account summary; replaced by export ingestion per B-series)
[INFO    ] options:snapshot_backfill    vintage 2026-09-25 is a flagged backfill pulled 2026-09-26T13:16 (post-close quotes as retained by the provider), not a 15:45 snapshot
[INFO    ] insiders:missing             data/ownership/insiders.json absent (EDGAR access needs the declared contact, SEC_USER_AGENT)
[INFO    ] ownership:missing            data/ownership/holders_13f.json absent (EDGAR access needs the declared contact, SEC_USER_AGENT)

29 findings; 1 CRITICAL
```

After:

```
last trading session: 2026-09-29
[HIGH    ] tournament:issuer_dup        2_balanced: two classes of Alphabet held together ['GOOG', 'GOOGL'] (collapsed at the next reconstitution)
[HIGH    ] xfile:vol_single_source      intraday vix 15.92 vs canonical 16.04
[HIGH    ] nullguard                    intraday.vvix is null; dependent safety checks must read IMPAIRED not false
[HIGH    ] options:vintage_missing      no chain vintage for the last session 2026-09-29 (latest: 2026-09-25)
[HIGH    ] options:lens_spot_stale      held names whose lens spot is not the last session 2026-09-29: ['AVGO: 2026-09-25 close', 'BMNR: 2026-09-25 close', 'GEV: 2026-09-25 close', 'GOOG: 2026-09-25 close', 'NVDA: 2026-09-25 close']
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override AVGO review_by 2026-09-17 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override NVDA review_by 2026-09-09 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ORCL review_by 2026-09-23 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[INFO    ] tournament:freshness         loco_cv_results.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         ml_indicator_weights.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_loadings.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_variance_explained.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v3_correlation.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           watchlist_top30.csv: no date axis found (static config?)
[INFO    ] tournament:backfilled        12 history row(s) are backfilled under the as-published convention (marked backfilled: true)
[INFO    ] book:export                  no brokerage export on record (holdings_export.json absent); holdings.json source: brokerage positions, 2026-09-30 (manual transcription from the account summary; replaced by export ingestion per B-series)
[INFO    ] options:snapshot_backfill    vintage 2026-09-25 is a flagged backfill pulled 2026-09-26T13:16 (post-close quotes as retained by the provider), not a 15:45 snapshot
[INFO    ] insiders:missing             data/ownership/insiders.json absent (EDGAR access needs the declared contact, SEC_USER_AGENT)
[INFO    ] ownership:missing            data/ownership/holders_13f.json absent (EDGAR access needs the declared contact, SEC_USER_AGENT)

27 findings; 0 CRITICAL
```
