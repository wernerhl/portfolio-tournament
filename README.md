# Portfolio Tournament

Four risk-tiered paper portfolios competing live, all governed by the same EWS regime
signal $R_t$ but with different concentration, cash floors, and hedging intensity.
Stocks (not ETFs) at the core; the regime overlay only sizes the cash sleeve.

| Tier | Description | Cash floor | Max positions | Benchmark |
|---|---|---:|---:|---|
| **1 Capital Preservation** | Defensive compounders + infrastructure; full hedging | 25 % | 12 | 60/40 SPY/TLT |
| **2 Balanced Growth**       | Compounders + AI infra + defensives; moderate hedging | 15 % | 20 | SPY |
| **3 Aggressive Growth**     | Concentrated AI + infra, momentum tilt; light hedging | 10 % | 15 | QQQ |
| **4 Tactical Alpha**        | 8–10 highest conviction; regime is the only brake | 0 %  | 10 | SSO |

---

## Layout

```
portfolio-tournament/
├── config.json                      ← holdings + cash per tier (source of truth)
├── index.html                       ← dashboard (Chart.js race chart + leaderboard)
├── scripts/
│   ├── compute_regime.py            ← fetches Yahoo data → R_t → data/regime_daily.csv
│   ├── compute_nav.py               ← config + R_t + EFFR → data/tournament.json (live)
│   ├── backtest_tournament.py       ← Phase 1 historical curves → data/backtest_*.{csv,json}
│   └── update_tournament.py         ← wrapper: compute_regime → compute_nav
├── data/
│   ├── regime_daily.csv             ← full R_t history (updated daily)
│   ├── tournament.json              ← live forward NAV history (frontend reads this)
│   ├── backtest_equity_curves.csv   ← historical tier NAVs + benchmarks 2010–2026
│   └── backtest_metrics.json        ← CAGR / Sharpe / MaxDD per tier (backtest)
├── charts/
│   └── backtest_tournament.pdf      ← Palatino chart, log scale + DD ribbons
├── .github/workflows/daily_update.yml ← weekdays 6 pm ET cron
└── README.md
```

---

## How it works

### Regime score $R_t \in [0,1]$

12 risk indicators (VIX, VVIX, SKEW, SPX realized vol, HYG/LQD, gold/SPX, TLT/SPX,
defensive/cyclical sectors, SPX 60-day return, SPX drawdown, oil velocity, DXY),
z-scored over a rolling 252-day window, sign-flipped to a common "higher = riskier"
direction, mapped to [0,1] via the standard-normal CDF, and equal-weight averaged.

### Cash sleeve formula per tier

| Tier | Formula | Cap |
|---|---|---|
| 1 Capital Preservation | `min(1.0, 0.25 + R · 0.75)` | 100 % |
| 2 Balanced Growth      | `min(0.85, 0.15 + R · 0.70)` | 85 % |
| 3 Aggressive Growth    | `min(0.50, 0.10 + R · 0.40)` | 50 % |
| 4 Tactical Alpha       | `min(1.0, R · 1.0)`           | 100 % |

Cash earns the Effective Fed Funds Rate (EFFR) compounded daily.

### Holdings

Holdings are **fixed per tier** in `config.json`. No quant stock selection runs in this
system; the regime overlay is the only active element. Edit `config.json` after every
trade (add positions, update shares, update cost basis) — the daily pipeline reads
this file as the source of truth.

### Backtest vs live

- **Backtest** (`backtest_tournament.py`): replays each tier's current holdings list
  back to 2010-01, with the regime overlay sizing cash daily. Tickers that didn't
  exist yet at a given date are filtered out at that rebalance; weight is
  redistributed equally to the survivors. Uses Phase 1's data files
  (`../phase1_data/output/*.parquet`).
- **Live forward** (`compute_regime.py` + `compute_nav.py`): runs every weekday at
  6 pm ET via GitHub Actions. Fetches today's prices and R_t, appends one row per
  tier to `data/tournament.json`.

The dashboard merges the two: backtest curves first, live NAVs scaled to match the
backtest endpoint on the seam date.

---

## Setup

```bash
cd ~/portfolio-tournament

# venv + deps
python3 -m venv .venv
.venv/bin/pip install yfinance fredapi pandas numpy scipy matplotlib

# 1. Verify config.json has your actual holdings per tier (edit before going live)

# 2. Generate historical curves (one-time, uses Phase 1 data)
.venv/bin/python scripts/backtest_tournament.py --data-dir ../phase1_data/output

# 3. Compute today's R_t and tier NAVs (this gets called daily by GitHub Actions)
export FRED_API_KEY=your_fred_key
.venv/bin/python scripts/update_tournament.py
```

### GitHub deployment

```bash
gh repo create portfolio-tournament --private --source=. --push
gh secret set FRED_API_KEY --repo wernerhl/portfolio-tournament
gh api repos/wernerhl/portfolio-tournament/pages -X POST \
   -f build_type=workflow -f 'source[branch]=main' -f 'source[path]=/'
gh workflow run daily_update.yml --repo wernerhl/portfolio-tournament
```

Note: GitHub Pages on **private** repos requires a Pro plan ($4/mo). If on the free
plan, either (a) keep the repo private and view the dashboard locally via
`python3 -m http.server 8000`, or (b) make it public (publishes holdings publicly —
not recommended).

---

## Editing `config.json`

After every trade, update the relevant tier's holdings dict:

```json
"holdings": {
  "TICKER": {"shares": N, "cost": cost_per_share}
}
```

Set `shares: 0` for watchlist entries you haven't bought yet. The dashboard will
show them dimmed.

The four tiers' holdings can overlap (and should — most defensive names appear in
both Tier 1 and Tier 2). This is a tournament of **strategies**, not a partitioning
of a single account. The total "cash" across tiers is your total dry powder split
notionally between the four tiers.

---

## Phase 1 data dependency

`backtest_tournament.py` needs the Phase 1 parquet files in
`../phase1_data/output/` (relative to this repo). If you've moved that folder, pass
its path with `--data-dir`.

The Phase 1 readme is at `../phase1_data/README.md`.
