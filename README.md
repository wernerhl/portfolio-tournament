# Portfolio Tournament v2

Five competing strategies tracked daily, all sharing the same EWS regime signal $R_t$:

| Tier | Selection | Holdings | Cash floor | Benchmark |
|------|-----------|---------:|-----------:|-----------|
| **1 Capital Preservation** | Algorithm, defensive sectors only (GM>30%, FCF>0)     | 12 | 25 % | 60/40 SPY/TLT |
| **2 Balanced Growth**      | Algorithm, full universe, equal-weight 3 tech factors | 20 | 15 % | SPY |
| **3 Aggressive Growth**    | Algorithm, double weight on 6m relative strength      | 15 | 10 % | QQQ |
| **4 Tactical Alpha**       | Algorithm, concentrated 8-name basket                 |  8 |  0 % | SSO (1.5× SPY) |
| **5 Werner's Picks**       | Manual — discretionary judgment, not algorithm        | open | 15 % | SPY |

Tiers 1-4 are reselected monthly from a scored S&P 500 + 50-midcap universe. Tier 5 is
Werner's actual portfolio, updated by editing `config.json` after each trade.

---

## What changed from v1

- **5 tiers instead of 4** — adds `5_werner` (the manual tier).
- **Algorithmic tier selection** — `score_universe.py` + `select_tiers.py` pick holdings
  every month based on a 4-factor model. v1 had hand-curated holdings.
- **Walk-forward backtest** — each tier rebalances monthly from 2010 to 2026 with the
  actual top-N picks at each rebalance date, not a fixed holdings list.
- **$100K notional per tier** at inception (2010-01-04). Backtest tracks NAV directly.
- **Per-ticker drill-down** — click any ticker in the leaderboard to see chart,
  technicals, fundamentals, score breakdown, correlations.
- **Monthly rebalance workflow** — new `monthly_rebalance.yml` rescores + reselects
  on the 1st of every month.

---

## Layout

```
portfolio-tournament/
├── config.json                          ← Tier 5 holdings + system settings + tier_specs
├── index.html                           ← dashboard (5 tiers + ticker drill-down)
├── scripts/
│   ├── score_universe.py                ← monthly: score ~537 tickers (tech + fund)
│   ├── select_tiers.py                  ← monthly: pick top-N per tier → tier_holdings.json
│   ├── compute_regime.py                ← daily: R_t from 12 indicators
│   ├── compute_nav.py                   ← daily: 5 tier NAVs + 4 benchmarks
│   ├── build_ticker_data.py             ← daily: per-ticker indicators JSON for drill-down
│   ├── update_daily.py                  ← wrapper for the daily pipeline
│   └── backtest.py                      ← one-time: walk-forward 2010-2026
├── data/
│   ├── source/                          ← Phase 1 parquet files (42 MB)
│   │   ├── prices_daily.parquet         5376 days × 537 tickers
│   │   ├── returns_daily.parquet
│   │   ├── fundamentals_snapshot.parquet
│   │   ├── fred_indicators.parquet      EFFR + 21 macro series
│   │   ├── vol_indicators.parquet       VIX/VVIX/SKEW, SPX, oil, gold, TLT, HYG, LQD
│   │   ├── vol_derived.parquet
│   │   └── sector_etfs.parquet          SPY/QQQ/sector ETFs + 11 sector ETFs
│   ├── tournament.json                  ← live daily NAV history (frontend reads this)
│   ├── tier_holdings.json               ← current algorithmic picks per tier
│   ├── scored_universe.csv              ← latest scoring run (~535 tickers)
│   ├── ticker_indicators.json           ← per-ticker drill-down data (~550 KB)
│   ├── regime_daily.csv                 ← R_t history (rolling)
│   ├── backtest_equity_curves.csv       ← historical NAVs 2010-2026
│   ├── backtest_metrics.json            ← CAGR/Sharpe/MaxDD per tier
│   └── backtest_holdings_log.csv        ← per-rebalance holdings + R_t + turnover
├── charts/backtest_tournament.pdf       ← Palatino chart, log scale (legacy from v1)
├── .github/workflows/
│   ├── daily_update.yml                 ← weekdays 6 pm ET: regime + NAV + ticker data
│   └── monthly_rebalance.yml            ← 1st of month 10 am ET: rescore + reselect
└── README.md
```

---

## Scoring model

### Technical score (0-25)
Three sub-scores as cross-sectional percentile ranks among eligible tickers
(≥ 252 prior trading days of non-null price history):

1. **Distance from MA200** — lower distance → higher rank (better entry)
2. **RSI(14)** — lower RSI → higher rank (oversold)
3. **6-month relative strength vs SPX** — higher → higher rank (momentum)

Tier 3 and Tier 4 use 2× weight on factor 3 (momentum tilt).

### Fundamental score (0-25)
Five sub-scores as cross-sectional percentile ranks from `fundamentals_snapshot.parquet`:

1. Forward P/E (inverted)
2. Revenue growth
3. Gross margins
4. Return on equity
5. Operating margins

NaN-fill with median rank (0.5). Snapshot is May 2026, constant across the backtest —
a known Phase 1 look-ahead limitation (deferred to Phase 2 with PIT data).

### Composite = technical + fundamental (0-50)

### Tier filters

Tier 1 only:
- `sector ∈ {Consumer Defensive, Healthcare, Utilities, Financial Services, Industrials}`
- `gross_margin ≥ 0.30`
- `free_cashflow > 0`

Tiers 2-4: no filter, full universe.

---

## Regime score $R_t \in [0,1]$

12 risk indicators from `vol_indicators.parquet` + `vol_derived.parquet` (VIX, VVIX,
SKEW, realized vol, HYG/LQD, gold/SPX, TLT/SPX, def/cyc sectors, SPX 60d return, SPX
drawdown, oil velocity, DXY) z-scored over a rolling 252-day window, sign-flipped to a
common "higher = riskier" direction, mapped to [0,1] via the standard-normal CDF,
equal-weight averaged. Cash earns the Effective Fed Funds Rate (EFFR) compounded daily.

Cash formula per tier: `cash_pct = min(cash_max, cash_floor + R_t · cash_slope)`.

---

## Setup + first run

```bash
cd ~/portfolio-tournament
python3 -m venv .venv
.venv/bin/pip install yfinance fredapi pandas numpy scipy matplotlib pyarrow

# 1. Monthly: score + select algorithmic tier holdings
.venv/bin/python scripts/score_universe.py
.venv/bin/python scripts/select_tiers.py

# 2. One-time: historical backtest (2010 → today)
.venv/bin/python scripts/backtest.py

# 3. Daily: regime + NAV + per-ticker indicators
export FRED_API_KEY=...
.venv/bin/python scripts/update_daily.py
```

For local preview of the dashboard:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

---

## Backtest results (placeholder snapshot)

These numbers were the seed run on 2026-05-20. They will change as the universe
rescores monthly and Werner trades.

| Tier | CAGR | Sharpe | MaxDD | Final NAV from $100K |
|------|-----:|-------:|------:|--------------------:|
| Capital Preservation |  7.1 % | 1.08 |  -10.9 % |    $302,429 |
| Balanced Growth      | 11.8 % | 1.15 |  -16.9 % |    $612,711 |
| Aggressive Growth    | 20.4 % | 1.29 |  -24.3 % |  $2,037,952 |
| Tactical Alpha       | 16.4 % | 1.33 |  -18.8 % |  $1,175,361 |

**Known limitations (same as Phase 1):**
- Survivorship bias: universe = current S&P 500 + 50 midcaps. Stocks that delisted
  between 2010 and 2026 are not in the dataset.
- Look-ahead in fundamentals: snapshot is May 2026 data applied to all rebalance dates.
- Tier 5 (Werner) is not backtested — discretionary picks have no historical record.

Both limitations are documented in `backtest_metrics.json` under `_meta.limitations`.

---

## Editing `config.json`

After every trade in Werner's account:

```json
"holdings": {
  "TICKER": {"shares": N, "cost": cost_per_share}
}
```

The daily pipeline picks up the new holdings on the next run.

Tier 1-4 holdings are written by `select_tiers.py` to `data/tier_holdings.json`;
don't edit those by hand — the monthly rebalance overwrites them.

---

## GitHub Actions

| Workflow | Trigger | What runs |
|---|---|---|
| `daily_update.yml`    | Weekdays 22:00 UTC (~6 pm ET)        | `update_daily.py` (regime → NAV → ticker data), commits to `data/`, deploys Pages |
| `monthly_rebalance.yml` | 1st of month at 14:00 UTC (~10 am ET) | `score_universe → select_tiers → build_ticker_data`, commits new monthly picks |

The repo is **public**, so GitHub Pages on the free plan is fine. Holdings + cost basis
are visible to anyone with the URL — same trade-off as `portfolio-screener`.
