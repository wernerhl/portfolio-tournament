# Fixed-income module — Phase 5 (the panels)

Order 16 September 2026, commit [B5]. A new page `bonds.html` in the merged site, sharing
`styles.css`, `charts.js` and the `common.js` loader.

## Referee, before and after

**20 findings, 0 CRITICAL** (`reports/audit_2026-09-16_bonds_B5_after.txt`), unchanged. The
page files are not audited; the served data files pass the bond checks.

## The panels (acceptance §9)

Rendered in the preview at 1400 px (`reports/shotsB/bonds_1400.jpg`) and 390 px
(`reports/shotsB/bonds_390.jpg`):

- **The curve** — a line chart of today vs three months ago vs one year ago (3m/2y/10y; 5y/30y
  pending the FRED fetch), the state (**normal**), the 2s10s slope with its percentile, and
  each maturity's ten-year percentile.
- **The credit strip** — IG and HY OAS with their ten-year percentiles and states (IG normal,
  HY tight) and the duration-hedged note (computed from OAS, not an ETF ratio).
- **The breakeven read** — the 10y breakeven as priced inflation (2.4%, 81.9th percentile);
  the real 10y yield and 5y5y forward marked unavailable pending the FRED fetch.
- **The rates-regime state** — carries the **DIAGNOSTIC** label and its gate caption; state
  carry.
- **The sleeve menu** — yield, duration, yield-per-duration, volatility and correlation to the
  book, **sorted by correlation ascending** (SHV −0.02 → HY 0.52), sortable by clicking a
  header.
- **The three allocation reads** — plain-language with their numbers.
- **The whole-portfolio stress panel** — the equity book's scenarios beside each sleeve's rate
  (±100bp) and spread (to the 90th-percentile OAS) sensitivity.

Every panel carries its as-of date and wires to the stale badge (the FRED close lags the
equity session by a day, so the FRED panels correctly badge "STALE · as of 2026-09-14/15").

## Verification

No console errors. **Zero page-level horizontal overflow at 1400 and 390 px** (measured
`document.documentElement.scrollWidth === clientWidth` at both widths). The words *edge* and
*alpha* appear on no bond page (the referee's `bond:language` check is CRITICAL if they do);
no buy or sell instruction is rendered. Wide tables scroll inside `.tbl-scroll`, so the page
itself never scrolls sideways.

## Deviation

The curve chart shows three maturities (3m/2y/10y) until the FRED fetch adds DGS5/DGS30; the
real 10y yield and 5y5y forward render as "unavailable" for the same reason.
