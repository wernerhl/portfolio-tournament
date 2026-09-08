# Holdings diff — screener `config.json["portfolio"]` vs tournament `data/holdings.json`

Order item 3.1 (one holdings source), 2026-09-09. Left: the screener's former own list (`portfolio-screener` `config.json` at commit `ffc1163`, now removed). Right: the tournament's new `data/holdings.json`, generated from `config.json` `werner_picks` (tier 5). From this date the right-hand file is the only holdings source; the screener reads it cross-repository.

## Ticker sets

| | tickers |
|---|---|
| only in the screener (former list) | BMNR |
| only in the tournament (holdings.json) | CEG, ETN, TSM, VRT |
| in both | AVGO, GOOG, MSFT, NVDA |

## Per-ticker

| ticker | screener shares | tournament shares | Δ shares | screener cost | tournament cost_basis | Δ cost | screener category | status |
|---|---:|---:|---:|---:|---:|---:|---|---|
| AVGO | 50 | 50 | 0 | 326.75 | 326.75 | 0 | Compounder | match |
| BMNR | 200.0702 | — | — | 39.046 | — | — | Speculative | screener only — dropped |
| CEG | — | 15 | — | — | 275 | — | — | tournament only — now held by the screener too |
| ETN | — | 15 | — | — | 410 | — | — | tournament only — now held by the screener too |
| GOOG | 50 | 50 | 0 | 326.81 | 326.81 | 0 | Compounder | match |
| MSFT | 50 | 50 | 0 | 500.4 | 500.4 | 0 | Catalyst | match |
| NVDA | 100.0224 | 100 | -0.0224 | 86.68 | 86.68 | 0 | Compounder | DIFFERS |
| TSM | — | 25 | — | — | 380 | — | — | tournament only — now held by the screener too |
| VRT | — | 20 | — | — | 400 | — | — | tournament only — now held by the screener too |

## Cash

| | screener `cash` | tournament `cash` | Δ |
|---|---:|---:|---:|
| cash | 87820.06 | 87820 | -0.06 |

## Notes

- **BMNR** was in the screener's former list (200.0702 sh @ 39.046, tagged Speculative) but is not in the tier-5 configuration and has never appeared in the `5_werner` positions of `data/tournament.json` (72 sessions, 2026-05-20 to 2026-09-04). Per the order it is absent from both systems until Werner adds a line to `holdings.json`; the agent did not decide. It remains in the screener's `midcap_additions` (scored as a candidate, not marked held).
- **NVDA** shares differ by 0.0224 (screener 100.0224 vs tier-5 100). `holdings.json` carries the tier-5 figure as ordered; if the fractional share is real (a DRIP or partial fill), Werner corrects the one file.
- **Cash** differs by 0.06 (screener 87820.06 vs tier-5 87820). `holdings.json` carries the tier-5 figure; the screener now reads cash from it and its own `cash` key is removed.
- **TSM, ETN, VRT, CEG** were held in the tournament all along but absent from the screener's list, so the screener's correlation penalty was computed against a 4-name (+BMNR) book. It now uses the 8-name book.
- The screener keeps only a per-ticker category tag (`holding_categories`: GOOG/AVGO/NVDA Compounder, MSFT Catalyst; the four newly-read names default to Core). No share, cost or cash figure lives in the screener any more.
