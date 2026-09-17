# Fixed-income module — Phase 3 (the allocation questions, pre-registered rules)

Order 16 September 2026. Commits [B3.1] paid to take duration, [B3.2] paid to take credit,
[B3.3] real vs nominal, [B3.4] the rates regime as a state. Each read is registered before
it runs; the rates-regime state is gated DIAGNOSTIC.

## Referee, before and after

Stable at **20 findings, 0 CRITICAL**. The DIAGNOSTIC gate is machine-enforced: mutating the
rates-regime label away from DIAGNOSTIC raises a CRITICAL `bond:diagnostic_gate` (verified),
restoring it clears the finding.

## Numeric checks (through the 2026-09-16 close)

**3.1 Are you paid to take duration.** Read: "cash (SHV) yields 3.73% at duration 0.35,
intermediate (IEF) 3.97% at duration 7.3, long (TLT) 4.73% at duration 16.5; the yield per
unit of duration is highest at SHV." Term premium proxy (10y − 3m) = 86 bp at its 63.9th
percentile. Extending cash → long picks up 100 bp for +16.15 of duration (6.2 bp per year of
duration). **Acceptance §9.4 holds:** with cash carrying the highest yield per unit of
duration, the read states extension is not favourably compensated. Not phrased as a rate call.

**3.2 Are you paid to take credit.** IG spreads pick up 80 bp over duration-matched
Treasuries (21.5th percentile, normal); HY 271 bp (10.1th percentile, tight). Note carried:
credit spreads mean-revert slowly, and a tight percentile means little compensation for
default and illiquidity risk. No spread-direction prediction.

**3.3 Real vs nominal.** At the 10-year maturity, TIPS and nominal Treasuries carry the same
real yield at the 2.38% breakeven; TIPS out-carry above it, nominal below. The breakeven is
at its 81.9th percentile — the inflation compensation priced into nominals is historically
high. The real 10y yield is marked unavailable pending the FRED fetch (breakeven identity
only). Descriptive, not an inflation forecast.

**3.4 The rates regime, as a state not a forecast.** A combined curve-plus-credit state,
pre-registered and frozen in config: defense (credit stressed), duration (curve inverted, an
association not a prediction), carry (normal/steep curve, non-stressed credit), else mixed.
Through the close: curve normal, credit non-stressed → **carry**. Labeled **DIAGNOSTIC** with
the gate caption and a reference to the Phase 6 registration; no code path reads it for
sizing (acceptance §9.8).

## Deviations

The real 10y yield and 5y5y forward remain unavailable pending the FRED fetch (Phase 2
deviation 1); the duration and credit reads are otherwise complete on real data.
