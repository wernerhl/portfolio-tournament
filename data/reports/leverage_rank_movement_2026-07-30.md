# Leverage module (#93) — rank movement report · 2026-07-30

Tournament Business Quality gains a 6th cross-sectional rank: net-debt/EBITDA (inverted), fed by the canonical artifact. Financials excluded (NaN → skipna mean, 72 names); negative-EBITDA names with debt >10% of mcap take a worst-rank sentinel; interest coverage is unavailable in the data source (no interestExpense field) — documented, not approximated. The screener side scores the same inputs on absolute ramps (0 to −5 penalty), replacing the old hidden ROE haircut.

## Isolated leverage effect (same data, same day: 5-metric vs 6-metric)

Spearman 5m-vs-6m: **0.964** — one metric among six, as expected.

| ticker | rank 5-metric | rank 6-metric | ND/EBITDA |
|---|---|---|---|
| SPG | 153 | 281 | 5.79 |
| SBAC | 103 | 213 | 8.29 |
| IRM | 147 | 256 | 7.95 |
| WYNN | 150 | 251 | 5.89 |
| CCI | 244 | 339 | 8.31 |
| EIX | 191 | 285 | 4.96 |
| AMT | 259 | 353 | 6.18 |
| FIS | 246 | 340 | 6.16 |
| GPN | 283 | 375 | 4.52 |
| D | 174 | 265 | 6.29 |
| — risers — | | | |
| TSLA | 391 | 234 | -2.55 |
| HUM | 356 | 220 | -2.26 |
| CRWD | 294 | 162 | -62.9 |
| ELV | 276 | 149 | -0.78 |
| FN | 258 | 131 | -1.96 |
| CNC | 429 | 303 | -2.38 |
| SWKS | 387 | 264 | -0.26 |
| FIX | 257 | 134 | 0.12 |
| PLAB | 272 | 150 | -2.31 |
| DDOG | 320 | 206 | -100.28 |

Key names (isolated): ORCL 13→47 (nd 4.44) · TLN 59→109 (8.86) · GEV 114→64 (net cash) · NVDA 7→6 · AVGO 6→8 · MSFT 60→59 · GOOG 47→36.

## Published-total change (old monthly artifact → today's re-emit)

Spearman old-vs-new: **0.480**. CAUTION: this total conflates the leverage rank with ~4 weeks of technical drift since the July monthly scoring (the drawdown reshuffled MA/RSI/rel-strength ranks). The isolated table above is the leverage attribution; this table is what the dashboard visibly changes today. Do not read drift as leverage.

## Screener side (scratch-verified 2026-07-30, publishes tonight)

532/534 leverage-alive · 302 penalties firing · 2 unavailable (flagged). TLN −5.0 → falls #5→#14 · ORCL −3.5 → #43 · NBIS −4.0 (levered cash burner) · top-8 otherwise clean sheets (GEV 0.0, AVGO −0.5). Note: BMNR is sector-tagged Financial Services by the provider → leverage-exempt; flagged for the v3 judgment queue alongside its thesis classification.
