# Rates-stress registration (draft) — 1 October 2026

**Status: proposed, awaiting the operator's written authorization. Nothing has been run.** No code path that computes R, the label, the headline, the overlay scalar, any sizing or the brief's colours reads MOVE or the DFII10 change; the referee's `bond:rates_stress_gate` (CRITICAL) enforces that until this test passes and the operator authorizes use in writing.

Order: "Rates and Bond Monitor Corrections" (1 October 2026), item R5.4.

## 1. Hypothesis

Adding two Tier-B channels to the v2 regime index improves R_full on the C3 criterion against R_full as published:

| channel | series | transform | direction |
|---|---|---|---|
| `move` | ICE BofA MOVE index (yfinance `^MOVE`) | level z on the 252-session window (the v2 method) | higher = riskier |
| `real10_chg60` | DFII10, 10-year TIPS real yield (FRED, point-in-time) | the 60-session change, z on the 252-session window | higher = riskier |

Everything else in v2 is unchanged: LOOKBACK 252, MIN_PERIODS 60, Φ(z) risk scores, tier weights A 2.0 / B 1.0 / C 0.5 (Tier B grows from 5 to 7 channels), the status buckets and the ±0.02 hysteresis corridor.

## 2. Contestants and comparator

- **Candidate:** R_full′, the v2 index with the two channels added.
- **Comparator:** R_full as published (`data/regime_daily_published.csv`); for the paired bootstrap, the revised R_full on the same window and the same resampled paths.

## 3. Criterion (the C3 v2 criterion, applied unchanged)

On tier 4 (the pure overlay: cash 0–100%, SPY, monthly, net of 10 bps one-way), decision window 2010-02-01 to 2026-05-21:

1. The 90 percent interval of the paired bootstrap difference (candidate minus comparator, same resampled paths as C3's B10) in after-cost return per unit of volatility has its lower bound above zero.
2. The candidate's drawdown reduction against buy-and-hold is at least the comparator's.

Both conditions must hold. Point-in-time inputs are required: MOVE is market data (unrevised); DFII10 comes from the ALFRED point-in-time store (`fred_vintages.PIT_SERIES["tips_real_10y"]`). The revised-input result is reported alongside and binds nothing.

## 4. Power check first

The convention since Failure 14: on the same resampled paths, the paired criterion must first distinguish two contestants known to differ — R_full as published against R_full lagged by 21 sessions (a deliberately degraded copy). If the criterion cannot separate them at the 90 percent level, the comparison in section 3 does not run, and this registration returns for amendment with the reason.

## 5. Data and coverage (measured 1 October 2026)

- MOVE: yfinance `^MOVE`, 5,379 daily values from 2005-01-03 to 2026-09-30 across 5,497 sessions of the trading calendar (118 missing, 2.15 percent). The misses fall almost entirely on market and bond-market holidays (Columbus Day and Veterans Day 2025 in the last year; the calendar lists holidays only from 2025, so earlier holidays count as sessions). ICE publishes no free official close; a missing session is unavailable, never substituted. The v2 panel's existing convention (a channel's last value carries forward over a missing session) applies, as for every channel.
- DFII10: FRED, daily from 2003; point-in-time through the vintage workflow.
- 30 September 2026, for the record: MOVE 110.45 (98.8th percentile of the trailing 252 sessions; 70.25 sixty sessions earlier); DFII10 2.91 percent, +67bp over 60 sessions, a ten-year high; DGS10 5.26 percent, +78bp.

## 6. Post-hoc caveat

This hypothesis was motivated by the September 2026 observation: implied rate volatility and the real yield at extremes of their own history while R_full read LOW RISK. A historical pass is therefore weaker evidence than a prospective one. The rates-stress block is kept DIAGNOSTIC from 1 October 2026 and its prospective record is reported at twelve months whatever the historical result.

## 7. Consequence

A pass changes nothing automatically. Any use (a v3 of the regime index, the headline, sizing or the brief's colours) is a new registered version and needs the operator's written authorization. A fail is recorded and the block stays DIAGNOSTIC.

## 8. Registered limitations

- MOVE's provider is yfinance, not ICE; there is no free official close to reconcile against.
- The 60-session change of DFII10 is one transform among several possible; it is fixed here before any run and is not tuned afterwards.
- The decision window is C3's; it ends before the motivating observation, which is the reason for the prospective record in section 6.
