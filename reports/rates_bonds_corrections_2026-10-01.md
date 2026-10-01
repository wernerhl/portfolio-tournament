# Rates and Bond Monitor Corrections — report (1 October 2026)

Order: "Execution Order: Rates and Bond Monitor Corrections (1 October 2026)", from the advisory model; operator Werner Hernani-Limarino. Repository `wernerhl/portfolio-tournament`, served tree at `98a08cc` when the order was issued.

## Commits, one per item

| item | commit | subject |
|---|---|---|
| R1 | 2ef8d0d | Regime cards: true units, computed narratives, ten-year scale (display only) |
| R1 (correction) | 9cf40f3 | Scale fields name their actual window (HY OAS covers 3.3 years) |
| R3 | 80e2bbc | Bond carry basis: curve-implied yields replace distribution yields |
| R5 | 5f3694b | Rates-stress monitor (DIAGNOSTIC) and its gate |
| R4 | cb766ea | Bond Test 2 registration v2, drafted for authorization (not run) |
| R6 | fa33ecc | Treasury auctions and the refunding from source |
| R2 | 646f9bf | Decision memo: the crisis-channel vote (no code change) |
| R7 | ee27818 | Mistakes ledger: five entries |
| R8 | eb42e73 | Textbook notes and the guide |

R6 and R2 were prepared by sub-agents working in parallel, under instructions not to commit or touch the files the lead was editing; the lead reviewed, applied their patches to the shared files and committed. The sequencing in the order (R1, R3, R6; R5; R2, R4; R7; R8) was followed for dependencies; commits landed as each item was verified.

## 0. Findings reproduced

| id | reproduced? | evidence on 1 October |
|---|---|---|
| F1 | yes | served `hy_oas` value 3.08, `value_str` "3bp", from fmt `"{v:.0f}bp"` |
| F2 | yes | VIX term −2.03 narrated "Term backwardation"; SPX 60d +2.26% "Momentum negative"; HY OAS 47.3rd percentile of its record narrated "Credit stress acute"; DXY "Dollar liquidity drain" |
| F3 | yes | headline DEFENSIVE from `n_crisis` 2 (hy_oas, dxy) while R_full 0.3143 LOW RISK and early warning CLEAR |
| F4 | yes | served pickup cash→IEF 0.24 points against a term-premium proxy of 101bp; `extension_favoured` false by the hard-coded `best not in ("SHV",)` |
| F5 | yes | R's rate channels are 3m-10y, BE 5Y, Baa-Aaa, HY OAS, TLT/SPX; no MOVE or real-yield channel |
| F6 | yes | served 3Y 10-13, 10Y 10-14, 30Y 10-15; TA_WS `upcoming` (1 Oct) 3-Year 10-06, 9-Year 10-Month (10Y reopening) 10-07, 29-Year 10-Month (30Y reopening) 10-08 |
| F7 | recorded | in the ledger (R7, entry 5) |

Discrepancies with the order's figures:
- **DXY.** The order's 101.6 and z +2.14 (756-session −0.07) do not match the 29- or 30-Sept close (101.33, z +1.90; 101.45, z +1.99). They match a DXY of about 101.63, the 1-Oct pre-open intraday print in `data/intraday.json`.
- **HY 756-session z.** The model's method gives −0.053; +0.063 comes out only on the raw FRED series (871 observations against 846 sessions). Both are near zero; the reading does not change.
- **HY "ten-year" percentile.** FRED distributes the ICE BofA spread series for about three years; the stored HY and IG OAS start 2023-06-05. Every "ten-year" percentile of either (the order's 47.8th, the bond panel's state) is a 3.3-year percentile. Corrected in display by 9cf40f3.

## 1. Referee, before and after

Before (`reports/audit_2026-10-01_R_before.txt`, run before any change):

```
last trading session: 2026-09-30
[HIGH    ] tournament:issuer_dup        2_balanced: two classes of Alphabet held together ['GOOG', 'GOOGL'] (collapsed at the next reconstitution)
[HIGH    ] tournament:werner_vs_book    operator tier NAV 175,859 vs the book 234,836 on 2026-09-30 (25.1% apart; cash 89,340 vs 148,317)
[HIGH    ] xfile:vol_single_source      intraday vix 16.32 vs canonical 16.34
[HIGH    ] nullguard                    intraday.vvix is null; dependent safety checks must read IMPAIRED not false
[HIGH    ] governance:coverage          5_werner: unclassified share 17% > 15%
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override AVGO review_by 2026-09-17 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override NVDA review_by 2026-09-09 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ORCL review_by 2026-09-23 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[INFO    ] tournament:freshness  (6 static CSVs) · screener:freshness (2) · tournament:backfilled · book:export
24 findings; 0 CRITICAL
```

After (`reports/audit_2026-10-01_R_after.txt`, after every item): **the same 24 findings, 0 CRITICAL** (the sorted finding lists are identical; `diff` is empty). The five new checks report nothing on the corrected outputs. Run on the 30-Sept served artifacts, before the fixes, they report:

| check | on the 30-Sept served files | after |
|---|---|---|
| `regime:unit` | 6 HIGH (3m-10y, BE 5Y, Baa-Aaa, VIX term, MICH lack units; HY "3bp" ≠ 3.08 × 100) | 0 |
| `regime:narrative_level` | 6 HIGH (backwardation with a −2.03 spread; "negative" with +2.26%; severity words on ANFCI, KCFSI, HY OAS, DXY below the 90th percentile) | 0 |
| `bond:carry_basis` | 4 CRITICAL (fields `highest_yield_per_duration`/`extension_favoured`; IEF and TLT legs without a curve-implied yield; the menu's yield_per_duration) + 18 HIGH (no curve-implied yield or reason) | 0 |
| `bond:rates_stress_gate` | not applicable (no block existed) | 0 |
| `calendar:treasury_source` | 3 CRITICAL (10-06/07/08 carried on 10-13/14/15) + 1 HIGH (144 unsourced TREASURY entries) | 0 |

The governance and tournament HIGHs above are outside this order and unchanged (open items for the operator: the nine visibility overrides past review; the operator tier's 17% unclassified share; `werner_vs_book` clears with tonight's 1-Oct row).

**Mutation tests (acceptance 1).** Each new check fires on a mutated copy and clears on restore:

| check | test | result |
|---|---|---|
| `regime:unit`, `regime:narrative_level` | `tests/test_regime_display.py` (reintroduces "3bp", drops a unit, restores F2's three narratives) | 7 passed |
| `bond:carry_basis` | `tests/test_bond_carry.py` (re-adds `extension_favoured`/`highest_yield_per_duration`, sets IEF's curve yield to its distribution yield, sets the pickup to F4's 24bp, adds yield_per_duration to the menu) | 6 passed |
| `bond:rates_stress_gate` | `tests/test_rates_stress.py` (label changed; MOVE read injected into headlineVerdict, daily_brief, compute_nav and a "move" channel into compute_regime_v2's INDICATORS) | 5 passed |
| `calendar:treasury_source` | `tests/test_calendar_checks.py` (misdated, missing, unsourced, overdue tentative, failed fetch) | 12 passed |

Full suite after the order: 159 tests, 0 failures (bond carry 6, calendar checks 12, daily brief 16, event calendar 16, fetch news 18, ingest brokerage 16, monthly review 16, ownership 18, rates stress 5, realized gains 16, regime display 7, twins 13).

## 2. Model-of-record invariance (acceptance 2)

`compute_regime_v2.py` was run on the same source parquets in a scratch copy of the repository, once with the code as served and once after [R1] (and again after the 9cf40f3 correction). Results:

| artifact | before vs after |
|---|---|
| `regime_daily.csv` | byte-identical |
| `regime_daily_published.csv` | byte-identical |
| `regime_v2_daily.csv` | byte-identical |
| `regime_v2_risk_scores.parquet`, `regime_v2_zscores.parquet` | equal (DataFrame.equals) |
| `regime_indicators.json` | every top-level field and every indicator's value, z, phi, status, tier, weight, direction, as_of and label identical; differences only in `value_str`, `narrative` and the new fields (`unit`, `pctile_10y`, `pctile_10y_risky`, `pctile_window_from`, `pctile_window_years`, `rank_1y_pct`, `z_window`, `z_756`) |

The served file was produced on the CI runner (Python 3.11); this machine (3.12) reproduces its z values to about 1e-13. To keep the served numbers exactly as the runner wrote them, only the display fields of the local run were merged into the served 30-Sept file. `LOOKBACK`, the z/phi/status computations, R_lead, R_full, the corridor, `n_by_status` and every `regime_daily*.csv` are untouched. `headlineVerdict()` is unchanged.

## 3. [R1] The regime cards

**Units (R1.1).** Baa-Aaa is stored in basis points (BAA 6.19 − AAA 5.76 = 0.43 points, stored as 43). HY OAS is stored in percent and shown × 100. MICH is a percent.

**Narratives (R1.2), the 23 cards on 30 Sept, before and after** (z shown in the value's own direction; percentile of ten years, or of the record where shorter):

| card | before value | before narrative | after value | after narrative | z (252) | 10-y pct |
|---|---|---|---|---|---|---|
| NFCI | -0.55 | Financial conditions easy | -0.55 | NFCI -0.55: conditions looser than average; below its past-year norm | -0.91 | 33.7 |
| ANFCI | -0.57 | No financial stress | -0.57 | ANFCI -0.57: conditions looser than average; below its past-year norm | -0.39 | 32.5 |
| 3m-10y | +1.01 | Curve normal | +1.01pp | 3m-10y curve upward-sloping (+1.01pp); above its past-year norm | +1.79 | 68.6 |
| BE 5Y | 2.36 | Inflation expectations stable | 2.36% | 5-year breakeven 2.36%; below its past-year norm | -0.33 | 66.6 |
| Baa-Aaa | 43.00 | Quality spread normal | 43bp | Baa-Aaa spread 43bp; below its past-year norm | -1.44 | 0.0 |
| VIX term | -2.0 | Term backwardation | -2.0 pts | VIX curve in contango (-2.0 pts); above its past-year norm | +0.32 | 56.3 |
| SKEW | 142 | Tail risk underpriced | 142 | SKEW 142; below its past-year norm | -0.53 | 66.9 |
| VIX | 16.34 | Calm hedging demand | 16.34 | VIX 16.34; below its past-year norm | -0.54 | 44.8 |
| VVIX | 89.5 | Tail protection cheap | 89.5 | VVIX 89.5; below its past-year norm | -0.86 | 28.3 |
| Mfg orders | $86,261M | New orders trending up | $86,261M | durable-goods new orders $86,261M; above its past-year norm | +1.23 | 97.5 |
| KCFSI | -0.84 | KC stress below average | -0.84 | KCFSI -0.84: calmer than average; below its past-year norm | -1.08 | 0.8 |
| STLFSI | -0.81 | St. Louis FSI calm | -0.81 | STLFSI -0.81: calmer than average; below its past-year norm | -1.08 | 7.3 |
| Loan tight | +0.0% | Banks easing credit | +0.0% | lending standards unchanged (net +0.0%); below its past-year norm | -1.62 | 27.4 |
| UMich Exp. | 4.2 | Consumers cautious | 4.2% | Michigan 1-year expected inflation 4.2%; below its past-year norm | -0.51 | 68.1 |
| HY OAS | 3bp | Credit stress acute | 308bp | HY OAS 308bp; far above its past-year norm (85th percentile of the trailing 252 sessions) | +1.27 | 47.3 (since Jun 2023) |
| Gold/SPX | 0.55 | No safe-haven bid | 0.55 | gold/S&P 500 ratio 0.55; below its past-year norm | -1.26 | 79.5 |
| TLT/SPX | 0.010 | No flight to quality | 0.010 | TLT/S&P 500 ratio 0.010; below its past-year norm | -2.06 | 0.0 |
| Def/cyc | 0.39 | Cyclical leadership | 0.39 | defensive/cyclical ratio 0.39; below its past-year norm | -1.77 | 0.0 |
| DXY | 101.4 | Dollar liquidity drain | 101.4 | DXY 101.4; far above its past-year norm (top decile of the trailing 252 sessions) | +1.99 | 70.1 |
| Real vol | 8.3% | Below-average volatility | 8.3% | 20-day realized volatility 8.3%; below its past-year norm | -0.92 | 19.1 |
| SPX 60d | +2.3% | Momentum negative | +2.3% | S&P 500 up 2.3% over 60 sessions; below its past-year norm | -0.41 | 34.9 |
| SPX DD | -1.9% | Mild pullback | -1.9% | S&P 500 1.9% below its high; near its past-year norm | -0.23 | 50.3 |
| Oil 60d | +23.0% | Oil rallying | +23.0% | oil up 23.0% over 60 sessions; above its past-year norm | +0.39 | 88.5 |

No served narrative contradicts its value's sign, and no severity word appears (none of the computed phrases uses one; the rule would allow one only at a ten-year risky-direction percentile of 90 or more). **Scale (R1.3)** and **label (R1.4)**: each card reads, for example, "z +1.27 vs past year · percentile 47 since Jun 2023 (3.3 years on record)"; "crisis" displays as "Extreme (1y)" on the cards, the status counts and the headline's input line; one legend line sits under the cards.

## 4. [R2] The decision memo

`reports/decision_memo_crisis_vote_2026-10-01.md` (script `scripts/analysis/crisis_vote_history.py`, table `reports/crisis_vote_history_2026-10-01.csv`). 5,427 sessions (72 served snapshots, 5,355 revised): the vote alone raised the headline on 4,632 sessions (85.4%), 54 of the 72 served, 232 of the last 252. Headline changes: A 401, B 404, C 245 (last 252 sessions: 36, 37, 15). Under B or C today's headline would read COMPLACENT (the complacency flag is on). The advisor's recommendation is stated as such (C; B as fallback). `headlineVerdict()` unchanged. The 9-Sept Decision Memo itself is not in the repository; §5 is cited from the code comment and the execution report.

## 5. [R3] The carry basis

Expected through the 29-Sept close, and actual:

| sleeve | curve-implied yield | pickup over bills | breakeven rise | expected |
|---|---|---|---|---|
| IEF (8.42y, D 7.3) | 5.207% | 95.7bp | 13.1bp (3.0 typical daily moves) | ≈ 5.20% / 95bp / 13bp |
| TLT (26.03y, D 16.5) | 5.610% | 136.0bp | 8.2bp (1.9 moves) | ≈ 5.61% / 135bp / 8bp |
| σ of daily DGS10 changes, 126 sessions | 4.43bp | | | ≈ 4.4bp |

All within 1bp of the expected values. Bills (DGS3MO) 4.25%. Every sleeve:

| sleeve | maturity (y) | basis | curve-implied | pickup bp | BE rise bp | D | trailing dist. | reason when null |
|---|---|---|---|---|---|---|---|---|
| SHV | 0.29 | treasury | 4.268% | 1.8 | 5.1 | 0.35 | 3.73% | |
| SHY | 1.89 | treasury | 4.856% | 60.6 | 32.8 | 1.85 | 3.63% | |
| IEF | 8.42 | treasury | 5.207% | 95.7 | 13.1 | 7.3 | 3.97% | |
| TLT | 26.03 | treasury | 5.610% | 136.0 | 8.2 | 16.5 | 4.73% | |
| GOVT | 7.37 | treasury | 5.172% | 92.2 | 15.6 | 5.9 | 3.65% | |
| TIP | 7.00 | real | 2.80% real (nominal-equivalent 5.16%, breakeven 2.36%) | — | — | 6.8 | 4.98% | real yield, excluded from nominal comparisons |
| VCSH | 3.1 | ig (3–5y bucket) | 5.682% | 143.2 | 55.1 | 2.6 | 4.47% | |
| VCIT | 7.6 | ig (7–10y) | 6.200% | 195.0 | 31.5 | 6.2 | 4.89% | |
| LQD | 12.62 | ig (10–15y) | 6.370% | 212.0 | 25.2 | 8.4 | 4.67% | |
| HYG | 4.27 | hy | 8.099% | 384.9 | 120.3 | 3.2 | 5.88% | |
| JNK | 5.07 | hy | 8.143% | 389.3 | 118.0 | 3.3 | 6.61% | |
| BKLN, FLOT, EMB, MUB, MBB | — | — | null | — | — | | | no public spread series matches; MUB: tax-exempt, no rate assumed; never substituted |
| AGG, BND | — | — | null | — | — | | | mixed aggregate; no single curve or spread series (not in the order's table; null with the reason) |

Maturities: iShares fund pages (SHV, SHY, IEF, TLT, GOVT, TIP, LQD, HYG; as of 2026-09-29), Vanguard characteristics (VCSH, VCIT; 2026-08-31), State Street (JNK; 2026-09-29). The IG bucket table is frozen in `data/bonds/carry_config.json`.

**Consumers of `yield_per_duration` / `extension_favoured`** (grep across scripts, app.js, pages.js, daily_brief.py), each updated: `scripts/bonds/build_sleeve_metrics.py` (computes it; kept in the file with `deprecated: true` and the reason, used nowhere), `scripts/bonds/compute_bonds.py` (`q_duration` rewritten; `diversifier_menu` carries curve-implied fields instead), `app.js` (`renderBondsSleeveMenu`: the YIELD/DUR column replaced by CURVE-IMPLIED, PICKUP, BE RISE; YIELD retitled TRAILING DIST.; `renderBondsAllocationReads`: basis and footnotes). `pages.js` and `daily_brief.py` had no consumer. The bond registration v1 mentions it (unchanged, frozen; R4).

**Inputs (R3.1).** DGS1, DGS7, DGS20, DFII5, DFII7, DFII20, DFII30 and the six ICE BofA IG bucket OAS were added to the nightly FRED fetch and to `fred_vintages.PIT_SERIES`. Because the FRED key exists only in CI, today's values were seeded into the revised store from FRED's public CSV download (same source; existing columns untouched; tonight's keyed fetch overlays them). The bucket OAS history on FRED starts 2023-10-02.

## 6. [R4] Test 2 registration v2

`reports/bonds_retirement_registration_v2_2026-10-01.md`: Tests 1 and 3 and sections A, C, D, E verbatim; Test 2 replaced (b = (y_m − y_3m)/D_par on t−1 point-in-time CMT; hold the largest positive b, else SHV); power check first (SHV-only against TLT-only); limitations registered; status proposed; nothing run; `retirement_tests.py` not written. v1 sha256 before and after: `5a6de1d4c3bd63a6fe511a3417f18476c122a3fae9805028231042957a0e9040` (unchanged).

## 7. [R5] The rates-stress monitor

`data/bonds/states.json` → `rates_stress`, label DIAGNOSTIC:

| series | level | detail | expected |
|---|---|---|---|
| MOVE (yfinance ^MOVE) | 110.45 (30 Sept) | 98.8th percentile of the trailing 252 sessions; 80.9th of ten years; 70.25 sixty sessions earlier (7 July) | 110.45; 99th; 70.25 |
| DFII10 | 2.91% (29 Sept, FRED) | 100th ten-year percentile; +67bp over 60 sessions | 2.91%, +67bp |
| DGS10 | 5.26% | 100th ten-year percentile; +78bp | 5.26%, +78bp |
| real share of the 60-session rise | 0.859 | the rest is the breakeven | |

**MOVE coverage.** 5,379 values from 2005-01-03 to 2026-09-30 across 5,497 sessions of the trading calendar: 118 missing (2.15%), almost all market or bond-market holidays (the calendar lists holidays only from 2025, so earlier holidays count as sessions). In the last year two sessions are missing: Columbus Day (2025-10-13) and Veterans Day (2025-11-11), bond-market holidays. A missing session is unavailable, never substituted. The panel is on bonds.html; the strip "Rates stress (DIAGNOSTIC, not in R)" sits under the regime cards. Gate: `bond:rates_stress_gate` passes (0 findings). Registration draft: `reports/rates_stress_registration_2026-10-01.md`, proposed, not run.

## 8. [R6] Treasury dates from source

Sources: TA_WS (`upcoming` and the auction record since 2024), Treasury's tentative auction schedule ("Aug2026 Refunding Auction Calendar Official Ver 2", the XML linked from the refunding documents page, every coupon row checked against the PDF), and the quarterly refunding page (next statement **2026-11-04, 08:30 ET**). Next 60 days:

| date | event | status |
|---|---|---|
| 10-06 | 3Y | announced (TA_WS) |
| 10-07 | 10Y reopening | announced |
| 10-08 | 30Y reopening | announced |
| 10-21 | 20Y reopening | tentative |
| 10-22 | TIPS 5Y | tentative |
| 10-26 / 10-27 / 10-29 | 2Y / 5Y / 7Y | tentative |
| 11-04 | REFUNDING 08:30 ET | official |
| 11-09 / 11-10 / 11-12 | 3Y / 10Y / 30Y | tentative |
| 11-18 / 11-19 | 20Y / TIPS 10Y reopening | tentative |
| 11-23 / 11-24 / 11-25 | 2Y / 5Y / 7Y | tentative |

**Consumers (last 120 sessions 04-10..09-30 / next 60 sessions 10-01..12-24).** The corrected schedule moves these 3Y/10Y/30Y dates: past, 05-11 gains a 3Y and 05-14 loses the 30Y; ahead, 10-06/07/08, 11-09 and 12-07 gain, 10-13/14/15, 11-11 and 12-09 lose.
- `compute_vol_regime` (frozen conditioning): filtered to its pre-R6 set (TREASURY 3Y/10Y/30Y, no REFUNDING); behaviour changes only on the moved dates (05-11, 05-14 past; 10-06, 10-07, 10-13, 11-11, 12-07 ahead). Over the full history the event-day subsample goes from 20 to 23 sessions; the three additions are real 3Y auction dates the generator missed. Unfiltered it would have changed on 29 past sessions not on a moved date.
- `daily_brief`: colours unchanged on every date (TREASURY is low impact; REFUNDING is not a MACRO_TYPE). `next_events` filtered to its pre-R6 type set (it would otherwise have picked up REFUNDING on 15 past sessions and 1 ahead).
- `app.js` events board and calendar card: filtered to the pre-R6 type set (REFUNDING and the new tenors would otherwise have entered on 40/25 and 116/56 days); the calendar card still changes on 83 past / 27 upcoming days because of the moved dates and the "reopening" labels.

Hard assert replaced: every coupon auction announced in TA_WS within the horizon is present on the same date. Calendar vintages: none exist; nothing rewritten.

## 9. [R7] The ledger

Five entries appended; `verify` passes (24 entries, every hash matches): mistake-2026-09-30-8 (advisor, carry metric), -10-01-7 (agent, by git history: 12b5a38, the July audit's fix 6a specified no display unit), -10-01-8 (agent, by git history: ff09646, committed without an agent attribution line; the spec it cites is not in the repository, so the attribution is inferred and the entry says so), -10-01-9 (system, the pattern generator), -10-01-10 (advisor, dates relayed unverified; repeat of mistake-2026-09-25-1).

## 10. [R8] Documentation

`reports/textbook_notes_2026-10-01.md` (math and plain-language tracks: the two scales, the curve-implied yield, the breakeven-rise derivation with roll-down and convexity named as omitted, the par-bond duration, MOVE, Treasury date provenance). `guide.html`: reading a regime card, the rates-stress strip, and the Bonds duration read, in plain language; ordinary readings are never called a crisis.

## Acceptance

| # | check | status |
|---|---|---|
| 1 | referee before/after; 0 CRITICAL after; each new check fires on a mutation and clears | met (§1) |
| 2 | model-of-record invariance | met (§2) |
| 3 | HY OAS reads 308bp with its z and percentile; no sign contradiction; no severity word below the 90th | met (§3) |
| 4 | memo with A/B/C counterfactuals; headlineVerdict unchanged | met (§4) |
| 5 | duration read on curve-implied yields; IEF/TLT within 10bp; yield_per_duration absent from reads and sorts; null sleeves carry reasons | met (§5) |
| 6 | v2 drafted; v1 sha256 unchanged; proposed; nothing run | met (§6) |
| 7 | rates_stress present and DIAGNOSTIC; gate passes; MOVE coverage reported | met (§7) |
| 8 | 6/7/8 Oct from TA_WS; 2/5/7/20-year and TIPS sourced; refunding sourced; consumer diffs | met (§8) |
| 9 | five entries; verify passes | met (§9) |
| 10 | textbook notes; guide updated | met (§10) |

## Deviations, each with its reason

1. **The extreme-bucket phrase.** The order's "(top decile of the trailing 252 sessions)" is used only when the reading is in the top decile; otherwise the phrase names the actual percentile ("85th percentile of the trailing 252 sessions"). The bucket is Φ(z) ≥ 0.80, roughly the top fifth, so the fixed phrase would have been wrong for HY OAS.
2. **HY/IG "ten-year" percentiles** cover 3.3 years (FRED's ICE BofA history). The cards and the bond credit caption now name the window (9cf40f3, an extra [R1] commit).
3. **The extra [R1] commit** above, made after the R2 work exposed the window; display only, invariance rechecked.
4. **R4's power check is registered, not run.** "Report the result" is read as binding on the run; acceptance 6 says nothing is run.
5. **FRED series seeded from the public CSV** (the key exists only in CI); same source, overlaid by tonight's keyed fetch.
6. **The served regime file** keeps the runner's numbers; the local run supplied only display fields (1e-13 cross-machine difference).
7. **AGG and BND** are not in the order's mapping table; they carry `curve_implied_yield: null` with a reason, under the order's "never substitute".
8. **REFUNDING appears nowhere on the dashboard yet**: R6.3 filters each consumer to its current type set. Showing it on the events board is a separate decision for the operator.
9. **Treasury dates after 2027-01-28** are absent until Treasury publishes the next tentative schedule (expected with the 4 Nov refunding); the old generator filled 2027 by pattern.
10. **Effective durations.** The static `EFF_DURATION` table (IEF 7.3, TLT 16.5) is kept, as the order's expected values use it; the issuer pages show 6.84 and 14.74 on 29 Sept. With the issuer figures the breakeven rises would be 14.0bp and 9.2bp. Updating the table is outside this order.

## Found during the order, not fixed (outside its scope; each needs the operator)

1. **Weekend-dated FRED prints are dropped by the regime panel.** `build_daily_panel` reindexes onto a weekday grid, so a monthly or quarterly print dated on a Saturday or Sunday (1 Aug 2026 was a Saturday) never enters, and the previous value carries forward a month longer: 75 of 260 monthly prints and 26 of 87 quarterly. On 30 Sept, Baa-Aaa, MICH and two other monthly channels show their July values (Baa-Aaa 43 instead of August's 44; MICH 4.2 instead of 4.0). This is in the model of record; a fix changes R and needs a decision.
2. **Realized volatility has been stale since 4 September.** The volatility store keeps 13 non-session rows (market holidays, e.g. Labor Day 2026) because the Cboe overlay in `refresh_data.build_canonical_close` re-adds them after the phantom-row drop; on those rows the S&P 500 is empty, so the 20-day realized volatility is blank for the next 20 sessions and the model carries 8.30 forward. This likely recurs after every holiday. The fix (drop non-session rows after the overlay) is one line in the producer, but it changes R's input from the next nightly.
3. **`consumer_expect` is MICH**, the Michigan one-year expected inflation in percent, but the channel is labelled "consumer expectations", its old narratives spoke of consumer optimism, and its direction treats lower values as riskier. The display now states what the series is; the channel's meaning and direction are a model question.
4. **The 9-Sept Decision Memo is not in the repository.**
