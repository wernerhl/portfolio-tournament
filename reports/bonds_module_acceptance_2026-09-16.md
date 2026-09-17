# Fixed-income module — acceptance (§9), all phases

Order: Execution Order — Fixed-Income Module, 16 September 2026. Built as a module inside the
merged portfolio-tournament repository (`scripts/bonds/`, `data/bonds/`, page `bonds.html`),
reading the same `holdings.json` and sharing the same referee. Commits `[B1.1]`…`[B6]`, one
report per phase.

## §9 checklist

1. **Referee before and after, zero CRITICAL, HIGH limited to deferred governance items.**
   ✔ Before (`audit_2026-09-16_bonds_B1_before.txt`) and after every phase
   (`..._B1_after`, `..._B4_after`, `..._B5_after`, `..._B6_after`): 20 findings, 0 CRITICAL.
   All HIGH are the pre-existing deferred governance items (overdue visibility reviews,
   unclassified-share coverage, one dead v4 column, the intraday vol single-source/nullguard).

2. **All sleeves fetch prices and yields, or are marked unavailable; sleeve_metrics carries
   the six fields.** ✔ 18/18 sleeves priced and yielded through 2026-09-16;
   `data/bonds/sleeve_metrics.json` carries yield, duration, yield-per-duration, volatility,
   1-year return and correlation to the book for each (Phase B1 report table).

3. **Curve, credit and breakeven render with footnoted percentile bands; the credit read is
   computed from option-adjusted spreads, not ETF ratios (verify in code).** ✔ Rendered on
   `bonds.html`; bands frozen and footnoted in `data/bonds/state_config.json`. `credit_state()`
   / `_oas_leg()` read `ig_oas`/`hy_oas` (BAMLC0A0CM/BAMLH0A0HYM2); the method string names OAS
   and the referee's `bond:credit_method` check is HIGH otherwise. No HYG/LQD ratio is used.

4. **The three allocation reads render with numbers and no rate forecast; "paid to take
   duration" reflects the current curve.** ✔ With cash (SHV) carrying the highest yield per
   unit of duration, the read states extension is not favourably compensated (`extension_favoured`
   false). No rate-direction language.

5. **The sleeve menu sorts by correlation to the book; the conditional message fires above 40%
   top-name risk share, with measured numbers.** ✔ Menu sorted ascending (SHV −0.02 → HY 0.52).
   MU is 57% of the book's variance; the message fires: adding 10% of NAV in IEF leaves the
   SPY −20% loss at −32.9% of NAV, halving MU takes it to −25.4%.

6. **The whole-portfolio stress panel combines rate and spread shocks on bonds with the equity
   scenarios.** ✔ Equity scenarios (SMH −30 … BMNR→0) beside per-sleeve ±100bp rate and
   90th-percentile spread shocks (IG 80→123 bp, HY 271→397 bp).

7. **All fixed-income yields and spreads stored point-in-time; a spot check on three past dates
   shows as-published values unchanged.** ✔ The point-in-time store carries the module's inputs;
   spot check at 2026-06-15 / 2026-03-16 / 2025-09-15 returns stable as-published us02y/us10y/
   ig_oas/hy_oas/breakeven_10y. The four new series (DGS5/DGS30/T5YIFR/DFII10) join the
   point-in-time overlay on the manual vintage rebuild (deviation 1).

8. **The rates-regime state is labeled DIAGNOSTIC and drives no sizing; Phase 6 tests are
   registered before they run.** ✔ Label DIAGNOSTIC (referee `bond:diagnostic_gate` CRITICAL if
   missing, verified by mutation); no sizing consumer. Three tests registered in
   `reports/bonds_retirement_registration_2026-09-16.md`, not run.

9. **No page emits a buy or sell instruction for any bond or sleeve; the words edge and alpha
   appear nowhere in the module.** ✔ No directive on `bonds.html` (descriptive throughout;
   referee `bond:directive` CRITICAL otherwise). No whole-word "edge"/"alpha" in
   `scripts/bonds/`, `data/bonds/`, `bonds.html`, the bond render functions of `app.js`, or the
   registration (referee `bond:language` CRITICAL otherwise).

## Deviations (with reasons), consolidated

1. **`FRED_API_KEY` is CI-only.** The four new series (DGS5, DGS30, T5YIFR, DFII10) and the
   point-in-time overlay for them are not populated locally; they land on the next nightly
   (revised) and the manual vintage rebuild (point-in-time). The module reads the curve at
   3m/2y/10y, the credit state (IG and HY) and the 10y breakeven on real as-published data now,
   and marks the rest **unavailable** — never substituting.
2. **Effective duration from a static category table**, source recorded, because yfinance
   exposes no duration field (order 1.3 allows this).
3. **Sleeve prices in a dedicated source store** (`bond_sleeves.parquet`), not the equity price
   store, so the sleeves never enter the equity universe or scoring; the fetch still runs in the
   shared nightly pipeline with the canonical provider.
4. **Phase 6 tests are registered, not run** (Phase 6: registered before they run; a run is a
   separate order). The DIAGNOSTIC gate holds until a pass.

## Governing premises honoured

Sleeve level only (no CUSIP prices, no single-bond selection). No forecast — states and
associations only. No buy or sell instruction; every panel descriptive. Point-in-time storage.
The rates-regime state gated DIAGNOSTIC, driving no sizing. The FRED key never printed, read
or handled locally.
