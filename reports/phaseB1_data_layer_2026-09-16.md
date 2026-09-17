# Fixed-income module — Phase 1 (data layer)

Order 16 September 2026. Commits [B1.1] sleeve universe, [B1.2] curve/macro series
(point-in-time), [B1.3] duration and carry per sleeve, [B1] referee checks.

## Referee, before and after (verbatim)

Before (`reports/audit_2026-09-16_bonds_B1_before.txt`) and after
(`reports/audit_2026-09-16_bonds_B1_after.txt`): **20 findings, 0 CRITICAL** in both.
Every HIGH is a pre-existing deferred governance item (overdue visibility reviews for
AMZN/ANET/ETN/GD/MSFT/NVDA/VRT, 5_werner unclassified-share coverage, one dead v4 column,
the intraday vol single-source and vvix nullguard). The bond block runs clean: no
staleness, no sleeve data gaps, no unavailable yields, no prohibited language. Acceptance
§9.1 holds.

## Numeric checks (acceptance §9.2)

All 18 sleeves fetch prices and a distribution yield; `sleeve_metrics.json` carries yield,
duration, yield-per-duration, volatility, 1-year return and correlation to the book for
each. Through the 2026-09-16 close:

| sleeve | yield | eff.dur | yield/dur | vol(126) | 1y ret | corr→book (n) |
|---|--:|--:|--:|--:|--:|--:|
| SHV  | 3.73% | 0.35 | 0.107 | 0.2% | +3.6% | −0.02 (124) |
| SHY  | 3.63% | 1.85 | 0.020 | 1.5% | +1.5% | 0.28 (124) |
| IEF  | 3.97% | 7.3  | 0.005 | 5.1% | −2.9% | 0.31 (124) |
| TLT  | 4.73% | 16.5 | 0.003 | 9.6% | −6.2% | 0.24 (124) |
| GOVT | 3.65% | 5.9  | 0.006 | 3.8% | −1.2% | 0.29 (124) |
| TIP  | 4.98% | 6.8  | 0.007 | 3.7% | −1.4% | 0.27 (124) |
| VCSH | 4.47% | 2.6  | 0.017 | 2.3% | +1.4% | 0.38 (124) |
| VCIT | 4.89% | 6.2  | 0.008 | 4.7% | −1.3% | 0.40 (124) |
| LQD  | 4.67% | 8.4  | 0.006 | 5.8% | −2.7% | 0.37 (124) |
| HYG  | 5.88% | 3.2  | 0.018 | 4.2% | +2.5% | 0.52 (124) |
| JNK  | 6.61% | 3.3  | 0.020 | 4.1% | +2.9% | 0.52 (124) |
| BKLN | 6.42% | 0.2  | 0.321* | 2.5% | +4.7% | 0.38 (124) |
| FLOT | 4.40% | 0.10 | 0.440* | 0.9% | +4.4% | 0.26 (124) |
| EMB  | 5.14% | 7.0  | 0.007 | 6.8% | +2.5% | 0.49 (124) |
| MUB  | 3.25% | 6.3  | 0.005 | 3.7% | −0.4% | 0.35 (124) |
| MBB  | 4.34% | 5.9  | 0.007 | 5.1% | −0.6% | 0.36 (124) |
| AGG  | 4.05% | 6.0  | 0.007 | 4.3% | −1.0% | 0.35 (124) |
| BND  | 4.04% | 5.9  | 0.007 | 4.1% | −1.0% | 0.34 (124) |

`*` floating sleeves carry ~0 rate duration, so their yield-per-duration is flagged
`near_zero_duration` (the ratio is unstable and not comparable to a duration sleeve's).
Equity book equity = $147,655 from `holdings.json` (the only holdings source), 7 positions.

Reading: the sleeves with the lowest correlation to this book — SHV (~0), then the
Treasury sleeves (~0.24–0.31) — diversify it; high yield (HYG/JNK ~0.52) and EM (0.49) move
with it. Long Treasuries (TLT) carry the least yield per unit of duration. Both facts are
what the module exists to surface; both are descriptive.

## FRED series (acceptance §9.2, curve/credit inputs)

Already ingested and read as-published: `us02y`, `us10y`, `us03m`, `effr`, `ig_oas`,
`hy_oas`, `breakeven_10y`, plus derived `yield_2s10s`/`yield_3m10y`, through 2026-09-15.
Added to the nightly revised fetch and the ALFRED point-in-time overlay: `us05y` (DGS5),
`us30y` (DGS30), `fwd_5y5y_infl` (T5YIFR), `tips_real_10y` (DFII10); the PIT overlay was
also extended to us02y/us05y/us30y/ig_oas/effr/breakeven_10y so the whole fixed-income
input set is stored point-in-time (acceptance §9.7).

## Deviations, with reasons

1. **The four new FRED series are not populated locally.** `FRED_API_KEY` is a CI
   secret and absent from the local shell (standing constraint: the key is never printed,
   read or handled here). `refresh_data.py` skips only the FRED block without the key, so
   `us05y`, `us30y`, `fwd_5y5y_infl` and `tips_real_10y` land on the next nightly (revised)
   and the manual vintage rebuild (point-in-time). Until then the module reads the curve at
   3m/2y/10y and marks 5y/30y, the 5y5y forward and the real 10y yield **unavailable** — it
   does not substitute. The credit state (IG and HY) and the 2s10s curve state are fully
   available now.
2. **Effective duration comes from a static category table, source noted.** yfinance
   exposes no duration field for bond ETFs (verified: `Ticker(tk).info` has no
   `effectiveDuration`/`duration`), so per order 1.3 the module uses a static category
   table for every sleeve and records the source. Provider duration would take precedence
   if it were ever available.
3. **Sleeve prices live in a dedicated source store**, `data/source/bond_sleeves.parquet`,
   not the equity price store. Putting bond ETFs into the equity universe would corrupt the
   tournament scoring, `build_universe.py`, and the union-universe referee check. The fetch
   still runs in the shared nightly pipeline and uses the canonical provider (yfinance), so
   "in the shared nightly fetch" is honoured; only the storage is separated.

## Pipeline wiring (deferred to the full producer set)

`fetch_sleeves.py` and `build_sleeve_metrics.py` run standalone and are verified. They join
`update_daily.py`'s script list together with the Phase 2–4 producer (`compute_bonds.py`)
in one commit, after that file exists, so the nightly order is set once. The served files
self-stamp `session_date` and live under `data/bonds/`, so they need no `SERVED_CADENCE`
entry (that map keys `data/*.json`); the referee checks them explicitly.
