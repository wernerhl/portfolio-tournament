# Fixed-income module — Phase 2 (the state reads, pre-registered, no forecast)

Order 16 September 2026. Commits [B2.1] curve state, [B2.2] credit state, [B2.3]
real-vs-nominal. Bands are defined in `data/bonds/state_config.json` and frozen before
the state runs.

## Referee, before and after

Stable at **20 findings, 0 CRITICAL** across Phase 2 (baseline `..._B1_after.txt`,
end-of-phase `..._B4_after.txt`). The bond state checks run clean:
`bond:diagnostic_gate` (label present), `bond:credit_method` (method names OAS),
`bond:language`/`bond:directive` (no edge/alpha/directive). Acceptance §9.1 holds.

## Numeric checks (as-published, through the 2026-09-15 FRED close)

**Curve state (2.1).** 2s10s = 32 bp at its **45.9th** percentile over ten years → **normal**.
3m10y = 0.86%. Maturity levels and ten-year percentiles: 3m 4.11% (71st), 2y 4.65% (92nd),
10y 4.97% (99.9th, near a ten-year high). 5y and 30y marked **unavailable** (DGS5/DGS30
pending the FRED fetch). Bands footnoted: inverted <10th, flat 10-40th, normal 40-80th,
steep >80th.

**Credit state (2.2).** IG OAS 80 bp at its **21.5th** percentile → **normal**; HY OAS 271 bp
at its **10.1th** percentile → **tight**. Acceptance §9.3: the read is computed from the
option-adjusted spread series (`ig_oas`/`hy_oas` = BAMLC0A0CM/BAMLH0A0HYM2) — verify in
`credit_state()` / `_oas_leg()`; the method string names OAS and the referee's
`bond:credit_method` check fails otherwise. A raw HYG-versus-LQD ratio is prohibited
(duration-confounding); none is used.

**Real-vs-nominal (2.3).** 10y breakeven 2.38% at its **81.9th** percentile (priced inflation
historically high in its range). The real 10y yield (DFII10) and the 5y5y forward breakeven
(T5YIFR) are marked **unavailable** pending the FRED fetch.

## Deviations, with reasons

1. **5y/30y maturities, the 5y5y forward and the real 10y yield are unavailable locally.**
   `FRED_API_KEY` is CI-only; these four series populate on the next nightly. The states
   render on the series present and mark the rest unavailable — no substitution.
2. **The point-in-time store lags the revised store locally (2026-09-04 vs 2026-09-15).**
   The module reads the point-in-time (ALFRED) parquet when it is within a week of revised,
   else revised with the vintage recorded. Yields and OAS are essentially not revised, so
   the two coincide; the point-in-time overlay refreshes on the manual vintage rebuild, after
   which the module reads it automatically. Each block records its `vintage`.
