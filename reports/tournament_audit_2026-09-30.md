# Tournament audit — reproduced from served data (2026-09-29)

`data/tournament.json`: 91 rows, 2026-05-20 → 2026-09-29 (12 backfilled: 2026-06-24, 2026-06-26, 2026-08-27, 2026-09-16, 2026-09-17, 2026-09-18, 2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24, 2026-09-25, 2026-09-28; missing now: none).

## Reconstitution dates and intra-month trades

| tier | reconstitutions | intra-month trades |
|---|---|---|
| 1_cap_pres | 2026-06-01, 2026-07-01, 2026-08-03, 2026-09-01 | 0 |
| 2_balanced | 2026-06-01, 2026-07-01, 2026-08-03, 2026-09-01 | 0 |
| 3_aggressive | 2026-06-01, 2026-07-01, 2026-08-03, 2026-09-01 | 0 |
| 4_tactical | 2026-06-01, 2026-07-01, 2026-08-03, 2026-09-01 | 0 |

## Cash gap (target − actual, points)

| tier | mean abs | max abs (on) | sessions > 5 | 3 June | 29 July |
|---|---|---|---|---|---|
| 1_cap_pres | 2.6 | 11.1 (2026-06-10) | 13 of 91 | 7.3 | 9.4 |
| 2_balanced | 2.3 | 9.5 (2026-06-10) | 9 of 91 | 6.8 | 8.7 |
| 3_aggressive | 1.3 | 5.3 (2026-06-10) | 1 of 91 | 4.5 | 4.3 |
| 4_tactical | 3.3 | 14.2 (2026-06-10) | 20 of 91 | 11.0 | 9.2 |
| all | 2.4 | 14.2 | | | |

## Operator tier

NAV 2026-09-15 $195,250.91; 2026-09-29 $249,639.07.
Re-seed 2026-09-29: $198,778.65 → $249,639.07 (+25.6%); AVGO, CEG, ETN, GOOG, MSFT, NVDA, TSM, VRT → ANET, AVGO, BMNR, GEV, GOOG, MU, NVDA.

## Regime label

Published label changes: 17 (2026-05 1, 2026-06 5, 2026-07 9, 2026-09 2). Entries into ELEVATED below 0.32: 2026-06-16 at 0.3027, 2026-07-06 at 0.3072, 2026-07-13 at 0.3177, 2026-07-17 at 0.3173, 2026-07-23 at 0.3198, 2026-09-10 at 0.3022. The corridor over the same history: 5 changes; entries into ELEVATED at 2026-06-03 (0.3877), 2026-07-27 (0.3233).

## Share classes held together

- 2_balanced: GOOG, GOOGL (Alphabet) 7.0% combined

## Name retention per reconstitution (kept / previous N)

| tier | 2026-06-01 | 2026-07-01 | 2026-08-03 | 2026-09-01 |
|---|---|---|---|---|
| 1_cap_pres | 5/12 | 5/12 | 3/12 | 3/12 |
| 2_balanced | 10/20 | 8/20 | 4/20 | 7/20 |
| 3_aggressive | 9/15 | 10/15 | 5/15 | 9/15 |
| 4_tactical | 6/8 | 3/8 | 3/8 | 4/8 |

## Holding spells (181) — share that beat SPY over the same window

| tier | spells | beat SPY | Wilson 95% | mean excess | decision dates | store variant |
|---|---|---|---|---|---|---|
| 1_cap_pres | 44 | 48% | [34, 62] | +0.6% | 5 | 55%, +1.0% |
| 2_balanced | 71 | 58% | [46, 69] | +2.4% | 5 | 61%, +1.9% |
| 3_aggressive | 42 | 52% | [38, 67] | +1.8% | 5 | 52%, +0.9% |
| 4_tactical | 24 | 58% | [39, 76] | +3.5% | 5 | 54%, +2.6% |

entry at the tier's position price on the first held row; exit at the position price on the last held row (open spells: the last row); SPY from the rows' benchmark prices.

the spells were chosen on a handful of dates and share factor exposure; the effective sample is the number of decision dates, not spells; no inference is possible from these intervals.
