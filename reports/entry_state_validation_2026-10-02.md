# Entry-state validation — READY against BASELINE (registration v2), run 2 October 2026

Registration: `reports/entry_state_validation_registration_v2_2026-10-02.md` (commit e8f7bd8). Power check: `reports/entry_state_power_check_2026-10-02.md`, committed first (9e50473). Result file: `data/entry_state_validation.json`, committed as produced. Prices: 531 of 535 tickers, 2 January 2009 to 1 October 2026, sha256 `fbe21a4b…`; entries through 1 October 2026.

## Verdict: NO VERDICT (the rule lacks power). The badge stays DIAGNOSTIC.

The registered power check failed: the median-early-loss difference resolves to ±0.27 point, against a required ±0.25. Under the registration that makes the READY comparison descriptive, not a judgment. The rule's own outcome is reported for completeness. It would not have passed either way: READY's median early loss is *higher* than the baseline's, not lower.

| READY (16,949 entries) against BASELINE (47,812), 525 common names, 202 months | READY | BASELINE | difference | 90% interval | rule |
|---|---|---|---|---|---|
| median MAE20 (loss before 20 sessions) | 3.96% | 3.77% | **+0.19 pt** | [−0.11, +0.49] | needs entirely below zero: ✘ |
| mean X60 (60-session excess over SPY, net) | +0.80% | +0.55% | **+0.24 pt** | [−0.09, +0.59] | lower bound ≥ −1 pt: ✔ |
| median X60 | −0.07% | −0.12% | +0.06 pt | [−0.26, +0.38] | |
| mean X20 | +0.13% | +0.04% | +0.09 pt | [−0.12, +0.29] | |
| stopped out within 20 sessions | 35.2% | 21.0% | **+14.3 pt** | [+12.1, +16.5] | |

**Against the expected result stated in advance:** it matches. Expected ΔMAE between 0 and +0.5 point with an interval not entirely below zero: realized +0.19 [−0.11, +0.49]. Expected ΔX60 within ±1 point: realized +0.24.

## What this says, and what it does not

- Over sixteen years and about 500 names, entering at the READY trigger did not reduce the early loss compared with entering trend-passing names on the first session of each month. The early loss was about the same, a fifth of a point larger at the median.
- The 60-session return was not worse; it was about a quarter-point better on average, with an interval that includes zero. Neither difference is distinguishable from zero.
- READY entries hit their stop within 20 sessions about one time in three (35%), against one in five for the baseline under the same stop formula. A READY entry comes right after a pullback, so its 40-session low sits close to the price and the stop is tight. At the default 0.5% risk budget, the size buys more shares against a nearer stop, and the stop is reached more often.
- What the test does not say: it covers today's universe only (survivorship). It uses the provider's daily history, enters at the next open, and holds to fixed horizons rather than exiting at the stop. It has no point-in-time earnings dates, so READY and READY-HALF are pooled.

## Full distributions (every entry)

| | entries | X20 mean | X20 p5 / p25 / p50 / p75 / p95 | X60 mean | X60 p5 / p25 / p50 / p75 / p95 | MAE20 p25 / p50 / p75 / p90 / p95 | stopped |
|---|---|---|---|---|---|---|---|
| READY | 16,949 | +0.13% | −10.7 / −3.9 / −0.2 / +3.8 / +11.6% | +0.80% | −18.6 / −7.0 / −0.1 / +7.0 / +21.7% | 1.8 / 4.0 / 7.5 / 12.5 / 16.6% | 35.2% |
| SETUP-ONLY | 30,334 | +0.22% | −10.7 / −3.8 / −0.1 / +3.8 / +11.7% | +0.79% | −18.4 / −7.0 / +0.0 / +7.2 / +21.0% | 1.7 / 3.9 / 7.4 / 12.4 / 16.6% | 31.7% |
| BASELINE | 47,812 | +0.04% | −10.5 / −3.9 / −0.2 / +3.5 / +10.9% | +0.55% | −18.2 / −6.9 / −0.1 / +6.8 / +20.1% | 1.7 / 3.8 / 7.3 / 11.7 / 15.2% | 21.0% |

The bootstrap percentiles of every difference are in the result file.

## By year (READY / BASELINE)

| year | READY entries | BASELINE entries | MAE20 median | X60 mean | stopped |
|---|---|---|---|---|---|
| 2010 | 979 | 2700 | 4.4 / 3.7% | 1.6 / 1.3% | 36 / 21% |
| 2011 | 966 | 2782 | 3.7 / 5.1% | −0.6 / 0.2% | 33 / 29% |
| 2012 | 898 | 2615 | 3.3 / 3.3% | 1.0 / 1.0% | 35 / 19% |
| 2013 | 1155 | 3806 | 3.1 / 2.8% | 2.1 / 1.7% | 24 / 10% |
| 2014 | 1191 | 3355 | 3.4 / 3.4% | 0.1 / 0.2% | 36 / 23% |
| 2015 | 996 | 2691 | 3.9 / 3.4% | 0.2 / 0.9% | 41 / 24% |
| 2016 | 868 | 2529 | 3.2 / 3.7% | 0.6 / 0.2% | 35 / 26% |
| 2017 | 1079 | 3374 | 2.6 / 2.7% | 1.0 / 0.6% | 24 / 12% |
| 2018 | 1090 | 2618 | 4.1 / 3.7% | 0.7 / 1.1% | 38 / 26% |
| 2019 | 844 | 2674 | 3.2 / 3.3% | −0.2 / −0.2% | 29 / 16% |
| 2020 | 810 | 2399 | 6.0 / 4.6% | −0.4 / 0.6% | 46 / 21% |
| 2021 | 1342 | 4063 | 4.3 / 4.2% | 0.8 / −0.4% | 32 / 16% |
| 2022 | 692 | 1719 | 7.3 / 7.8% | 1.3 / 1.8% | 56 / 42% |
| 2023 | 905 | 2077 | 4.4 / 4.4% | 1.0 / −0.3% | 39 / 24% |
| 2024 | 1376 | 3649 | 3.8 / 4.4% | 0.7 / −0.3% | 31 / 19% |
| 2025 | 912 | 2482 | 5.5 / 4.1% | 2.3 / 0.3% | 41 / 24% |
| 2026 | 846 | 2279 | 5.8 / 4.6% | 1.0 / 1.8% | 38 / 22% |

READY's stopped-out share is above the baseline's in every year. Its median early loss is lower in six years, higher in eight, and the same (to one decimal) in three.

## Consequence

1. The badge stays **DIAGNOSTIC**. The referee's `entry:diagnostic_gate` keeps it so while this file does not read PASS.
2. The entry state remains on the cards as a rule's reading of the tape: trend, pullback, turn, stop and size. It is not shown to reduce early losses, and nothing on the site may present it as doing so.
3. Any further test needs a new registration, and that is the operator's call. Options it could register, none chosen here: a mean rather than a median for MAE20; a test of the stop rule itself (the 35% stop-out rate); an exit at the stop instead of fixed horizons. Each would face a power check on SETUP-ONLY against BASELINE first.
