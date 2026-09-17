# Fixed-income module — Phase 6 (validation, before any read drives sizing)

Order 16 September 2026, commit [B6]. Pre-registered retirement tests by the method of the
regime test. Registered, **not run**: they gate only the timing use, which is not adopted.

## Referee, before and after

**20 findings, 0 CRITICAL** (`reports/audit_2026-09-16_bonds_B6_after.txt`).

## The registration (acceptance §9.8)

`reports/bonds_retirement_registration_2026-09-16.md` registers three rules before they run:

1. **The rates-regime state as a duration-timing rule** — vs a static duration allocation and
   vs a constant-maturity ladder.
2. **A carry rule** (hold the highest yield-per-duration sleeve) — vs equal-weight across the
   Treasury ladder.
3. **A credit-timing rule** (add HY when spreads are wide, reduce when tight) — vs static
   credit.

Method, frozen: point-in-time yields and spreads from the vintage store; a circular block
bootstrap of all strategies jointly (60-session blocks, 1,000 resamples, seed 20260916),
**paired differences on the same resampled paths** (the discriminating statistic the regime
test v2 established — a margin-vs-own-interval test has no discriminating power); costs =
bond-ETF bid-ask at **one third of quoted width** (narrow for Treasuries, wider for HY and
EM). Decision rule: the 90% paired-difference interval in after-cost return per unit of
volatility lies entirely above zero, and the drawdown reduction is at least the comparator's.

## The gate (acceptance §9.8)

The DIAGNOSTIC gate on the rates-regime state lifts only on a pass of Test 1 against both
comparators, and adoption into live sizing is a separate written decision. Until then no
fixed-income read drives sizing, and the state stays labeled DIAGNOSTIC — enforced by the
referee's `bond:diagnostic_gate` CRITICAL. No code path reads the state for sizing (verified:
the only consumers are the bonds page and the evidence card, both display-only).

## Surfacing

The evidence page renders the registration (`renderBondsRegistrationCard`) beside the regime
retirement tests; the bonds page's rates-regime card links it.

## Deviation

The tests are registered but not run, per Phase 6 ("registered before they run" / "not
implemented in sizing until it passes") and the standing instruction that a run is a separate
order. When ordered, `scripts/bonds/retirement_tests.py` imports the C3 bootstrap and metric
functions unchanged.
