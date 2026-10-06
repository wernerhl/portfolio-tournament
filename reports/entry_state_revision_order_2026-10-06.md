# Execution Order: Revision of the Entry-State Indicator and Related Fixes (6 October 2026) — report

All eight items are committed as [R1]–[R8]. The one part that cannot run is the section 7 validation: it is registered, and it waits for the survivorship-free data (Sharadar/Norgate access, pending receipt since 9 September).

## Acceptance

| # | criterion | result |
|---|---|---|
| 1 | referee before and after, zero CRITICAL | Before (`reports/audit_2026-10-06_R_before.txt`): 27 findings, 0 CRITICAL. After (`…_R_after.txt`): 28 findings, 0 CRITICAL. The only new line is an INFO: the screen applies the provider exclusions at tonight's rebuild. |
| 2 | states at the 5-Oct close | **Lockheed Martin READY-HALF**: flag `below_200d` (close $506.63 under the 200-day $563.03, 12-1 momentum +6.7%); earnings-conflict flag (provider 22 Oct, WSJ 27 Oct, investor relations 22 Oct, decided by IR); stop **$487.62** = 40-session low $498.55 − ATR $10.93; size a quarter of the base (`below_200d` and earnings), 15 shares. **Micron WAIT** (no setup). **Incyte WATCH**: ceiling flag, capped by the $131.47 ceiling; also heavily shorted (days-to-cover 7.62). **Texas Pacific Land**: heavily-shorted flag (days-to-cover **12.59**) and the provider-data flag (forward P/E, free cash flow, revenue growth); state READY at a quarter size (`below_200d` and shorting). |
| 3 | Incyte's card: the ceiling near $131.50, the 5-year high and the all-time high of $152.66 | "ceiling $131.47 (2015-09 $131.47, then −27.6%; 2026-07 $129.93, then −12.2%) · within 15% below: state capped at WATCH"; 5-year closing high $129.93 (2026-07-28); all-time closing high $152.66 (2017-03-15). The provider's close series gives $131.47 for the 2015 peak. |
| 4 | TPL's forward P/E and free cash flow greyed out with the reason | Book page, "names under review": FWD P/E 4.7 and FCF −$33M are greyed and struck through, with the reasons ("forward P/E 4.7 and trailing P/E 44.0 differ by more than a factor of three"; "provider free cash flow −$32.8M has the opposite sign of the 10-Q for 2026-01-01 to 2026-06-30: operating cash flow +$334.9M …"). Revenue growth is flagged too (31.2% against a 15.1% average). |
| 5 | GEV's reaction history, before-open convention: −4.5, +1.3, +2.7, +3.1, +14.6, −1.6, +2.7, +13.7, −8.7 (July 2024–July 2026) | Exact, in the card's options drawer: "2024-07 before open −4.5% · 2024-10 +1.3% · 2025-01 +2.7% · 2025-04 +3.1% · 2025-07 +14.6% · 2025-10 −1.6% · 2026-01 +2.7% · 2026-04 +13.7% · 2026-07 −8.7%". Eight of the nine timings come from 8-Ks accepted before the open; the July 2025 one comes from the provider's 06:00 stamp. |
| 6 | max pain and dealer gamma only in the details drawer | Both now sit in the collapsed "options detail" drawer. Max pain was not shown anywhere before. The preview finds neither phrase outside a drawer. |
| 7 | section 7 registration committed before any run | `reports/entry_state_validation_registration_2026-10-06.md` and its parameter file (85fb230). No run has happened or can happen until the data arrives. |
| 8 | the five ledger entries | `mistake-2026-10-06-1`, `-06-2`, `-05-1`, `-05-2`, `-02-3`. The ledger verifies intact. |

## What was built

- **[R1] Rules version 2.**
  - Configuration: `data/entry_state_config.json` (version 2). The 2-Oct rules stay byte-identical in `data/entry_state_config_2026-10-02.json` and `scripts/entry_state_v1.py`, so the 2-Oct validation stays reproducible.
  - The rules: trend gate, entry without confirmation, modifiers with the quarter floor, ceiling cap, a stop without the 200-day floor, and the size rule.
  - Inputs: volume kept in the price store; days-to-cover and its monthly change from the canonical fetch.
  - Cards: the entry-state block and the board's FLAGS column.
  - Referee checks: `entry:stop_rule`, `entry:modifiers`, `entry:ceiling_cap`, `entry:trend_gate`.
- **[R2] The ceiling.** `scripts/long_range.py` produces `data/long_range.json`: yearly highs with the declines that followed, ceilings, and the 5-year and all-time highs. 530 names; 214 have a standing ceiling. Tests: 12 pass.
- **[R3] Provider checks.** `scripts/provider_checks.py` (EDGAR company facts) produces `data/provider_flags.json`. The screen blanks flagged fields for scoring and records `provider_suspect(field)`. Cards grey the field with its reason. A "names under review" section on the book page (`data/review_names.json`) gives TPL, LMT, INCY and MU full cards.
- **[R4] Earnings timing and conflicts.**
  - Reactions record their timing and source. An 8-K accepted before 09:30 ET proves a before-open release; otherwise the provider's stamp decides.
  - `scripts/earnings_dates.py` produces `data/earnings_dates.json`, with all sources shown and IR deciding. Curated sources live in `data/earnings_date_sources.json`.
- **[R5] Days-to-cover and the volume check** on every card. Following the main-view rule, the options row keeps only the earnings line. The drawer holds the volatility state, term structure, skew, past reactions, hedge structure, dealer gamma and max pain. The signal box's mean-reversion reference and its 1%-risk rulebook size move to a drawer.
- **[R6] The validation registration.** **[R7] The ledger.** **[R8] Referee checks:**
  - `provider:flags` and `provider:excluded`;
  - `earnings:conflict` (both directions) and `earnings:timing`;
  - `long_range:coverage` and `long_range:stale`.

  Each was caught by a mutation on a scratch copy (ten mutations, all caught).

## Decisions taken, stated

1. **Ceiling lookback:** the current calendar year and the eleven before it. The order says 10 years, but its own reference (Incyte, September 2015) is eleven years back.
2. **A ceiling the price has closed above since it formed is lifted.** The order caps "until the price closes above the ceiling". Without this, Lockheed would read WATCH under a 2025 ceiling ($514.24) that it broke on 6 January 2026, contrary to acceptance 2.
3. **Which P/E is flagged:** in a mismatch the forward P/E is flagged. It is the field the screen scores; the reason names both values.
4. **EDGAR timing:** EDGAR decides timing only when the 8-K was filed before the open. A later filing is not proof of an after-close release, since Schwab filed after the close for releases made before the open. This rule corrected two provider stamps (AXP and 3M, both stamped 13:00 with 8-Ks before 07:05).
5. **The WSJ date** (27 Oct for Lockheed) is recorded from the order in a curated sources file; the pipeline does not fetch it. Lockheed's investor-relations release of 1 October (call 22 Oct, 08:30 ET) is recorded the same way and decides the date.
6. **The rulebook's 1%-risk size** moves to a drawer: the entry state's 0.5%-risk size is the operative one, and two sizes on one card contradicted each other.

## Consequences to know

- **More READY names.** Without the confirmation requirement, 125 names read READY and 26 READY-HALF at the 5-Oct close, against 14 under the 2-Oct rules. It remains DIAGNOSTIC.
- **The provider checks flag 99 of 533 names.**
  - Free cash flow: 45. The order compares the provider's figure (trailing twelve months) with the latest 10-Q's year-to-date figure, so a period mismatch can flip the sign; a trailing-twelve-month EDGAR figure would be a tighter test, if the operator wants it.
  - Forward P/E: 38.
  - Revenue: 34. Micron is flagged at 379% against 84%. The rule as written also does **not** flag Incyte: EDGAR's prior four quarters averaged about 21%, above half of its 37.7%, so the CMS settlement quarter passes that threshold.

  Flagged fields leave the screen's scores at tonight's rebuild.
- **The validation cannot be run** until the survivorship-free data is purchased and delivered. The label stays DIAGNOSTIC.

## Left for the operator

1. The survivorship-free data (Sharadar or Norgate), to run the registered validation.
2. Whether the free-cash-flow check should compare trailing twelve months on both sides, and whether the revenue threshold should catch cases like Incyte's.
3. `data/review_names.json` and `data/earnings_date_sources.json` are curated lists; names and dates are added there.
