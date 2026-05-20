"""
Compute today's NAV per tier from config.json holdings + latest prices.

Reads:
  config.json          — holdings + cash per tier
  data/regime_daily.csv — R_t (computed by compute_regime.py)

Appends to:
  data/tournament.json  — cumulative daily history (frontend consumes this)
"""
from __future__ import annotations
import json, os, sys, warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR  = REPO_ROOT / "data"

BENCHMARKS = ["SPY", "TLT", "QQQ", "SSO"]


def load_config() -> dict:
    with open(REPO_ROOT / "config.json") as f:
        return json.load(f)


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Returns ticker → latest close, dropping tickers with no data."""
    tickers = [t for t in tickers if t]
    if not tickers:
        return {}
    try:
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
        if data is None or data.empty:
            return {}
        closes = data["Close"]
        if isinstance(closes, pd.Series):
            return {tickers[0]: float(closes.dropna().iloc[-1])} if not closes.dropna().empty else {}
        out = {}
        for t in closes.columns:
            ser = closes[t].dropna()
            if not ser.empty:
                out[t] = float(ser.iloc[-1])
        return out
    except Exception as e:
        print(f"  warn fetch_prices: {e}", file=sys.stderr)
        return {}


def latest_R_t() -> tuple[float, str]:
    """Read latest R_t from data/regime_daily.csv (produced by compute_regime.py)."""
    p = DATA_DIR / "regime_daily.csv"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found — run compute_regime.py first")
    df = pd.read_csv(p, index_col="date", parse_dates=["date"])
    R = float(df["R_t"].dropna().iloc[-1])
    return R, df["R_t"].dropna().index[-1].strftime("%Y-%m-%d")


def regime_label(R: float) -> str:
    if R < 0.30: return "LOW RISK"
    if R < 0.50: return "ELEVATED"
    if R < 0.70: return "HIGH RISK"
    return "CRISIS"


def effr_daily_rate() -> float:
    """Return today's daily cash return = EFFR/252/100. Falls back to ~4 % if FRED unreachable."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return 0.04 / 252
    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)
        effr = fred.get_series("EFFR",
                               observation_start=(datetime.now() - pd.Timedelta(days=14)).strftime("%Y-%m-%d"))
        latest = float(effr.dropna().iloc[-1])
        return latest / 252 / 100
    except Exception as e:
        print(f"  warn EFFR fallback: {e}", file=sys.stderr)
        return 0.04 / 252


def compute_tier_nav(tier_cfg: dict, prices: dict[str, float],
                     R_t: float, effr_daily: float) -> dict:
    holdings = tier_cfg.get("holdings", {})
    cash = float(tier_cfg.get("cash_allocated", 0))

    equity_value = 0.0
    positions = []
    for ticker, h in holdings.items():
        shares = float(h.get("shares", 0) or 0)
        if shares <= 0:
            continue
        # try ticker as-is then with .  / - swap (yfinance vs broker conventions)
        price = prices.get(ticker) or prices.get(ticker.replace("-", ".")) or prices.get(ticker.replace(".", "-"))
        if price is None:
            continue
        pos_value = shares * price
        equity_value += pos_value
        cost = float(h.get("cost", 0) or 0)
        positions.append({
            "ticker": ticker,
            "shares": shares,
            "price":  round(price, 2),
            "value":  round(pos_value, 2),
            "cost_basis": round(cost, 2),
            "gain_pct": round((price / cost - 1) * 100, 1) if cost > 0 else None,
            "weight":  None,  # filled below
        })

    cash_after_yield = cash * (1 + effr_daily)
    total_value = equity_value + cash_after_yield
    if total_value > 0:
        for p in positions:
            p["weight"] = round(p["value"] / total_value * 100, 1)

    cash_floor = float(tier_cfg.get("cash_floor", 0.15))
    cash_formula = tier_cfg.get("cash_formula", "min(1.0, 0.15 + R * 0.70)")
    # Safe eval of the formula
    safe_globals = {"__builtins__": {}, "min": min, "max": max, "R": R_t}
    try:
        target_cash_pct = float(eval(cash_formula, safe_globals))
    except Exception:
        target_cash_pct = min(1.0, cash_floor + R_t * (1.0 - cash_floor))
    target_cash_pct = max(target_cash_pct, cash_floor)

    actual_cash_pct = cash_after_yield / total_value if total_value > 0 else 0.0

    return {
        "equity_value": round(equity_value, 2),
        "cash_value":   round(cash_after_yield, 2),
        "total_nav":    round(total_value, 2),
        "n_positions":  len(positions),
        "target_cash_pct": round(target_cash_pct * 100, 1),
        "actual_cash_pct": round(actual_cash_pct * 100, 1),
        "positions": positions,
    }


def main():
    config = load_config()
    R_t, r_date = latest_R_t()
    regime = regime_label(R_t)
    effr_daily = effr_daily_rate()
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"Date: {today}  (R_t as of {r_date})")
    print(f"R_t: {R_t:.3f} → {regime}")
    print(f"EFFR daily rate: {effr_daily*252*100:.2f}% annualized")

    # Collect tickers
    all_tickers = set()
    for tier in config["tiers"].values():
        for ticker, h in tier.get("holdings", {}).items():
            if float(h.get("shares", 0) or 0) > 0:
                all_tickers.add(ticker)
    all_tickers.update(BENCHMARKS)
    print(f"Fetching prices for {len(all_tickers)} tickers...")
    prices = fetch_prices(sorted(all_tickers))
    print(f"  got {len(prices)}/{len(all_tickers)} prices")

    tier_results = {}
    for tier_id, tier in config["tiers"].items():
        res = compute_tier_nav(tier, prices, R_t, effr_daily)
        tier_results[tier_id] = res
        print(f"  {tier['short']:11s}  NAV ${res['total_nav']:>11,.2f}  "
              f"({res['n_positions']} pos, {res['actual_cash_pct']:.0f}% cash vs "
              f"target {res['target_cash_pct']:.0f}%)")

    # Load existing tournament
    tournament_file = DATA_DIR / "tournament.json"
    if tournament_file.exists():
        with open(tournament_file) as f:
            tournament = json.load(f)
    else:
        tournament = {"inception_date": today, "history": []}

    # Skip if we already have today's entry (avoid duplicates on manual reruns)
    if tournament["history"] and tournament["history"][-1].get("date") == today:
        tournament["history"][-1] = {}  # we'll rebuild it below
        tournament["history"].pop()

    entry = {
        "date": today,
        "R_t": round(R_t, 4),
        "regime": regime,
        "effr_daily_pct": round(effr_daily * 252 * 100, 3),
        "tiers": {},
        "benchmarks": {b: round(prices[b], 2) for b in BENCHMARKS if b in prices},
    }
    inception_navs = {}
    if len(tournament["history"]) > 0:
        first = tournament["history"][0]
        inception_navs = {tid: tdata.get("nav") for tid, tdata in first.get("tiers", {}).items()}

    for tier_id, res in tier_results.items():
        tier_entry = {
            "nav":            res["total_nav"],
            "equity":         res["equity_value"],
            "cash":           res["cash_value"],
            "n_positions":    res["n_positions"],
            "target_cash_pct": res["target_cash_pct"],
            "actual_cash_pct": res["actual_cash_pct"],
            "positions":      res["positions"],
        }
        if inception_navs.get(tier_id):
            tier_entry["total_return_pct"] = round(
                (res["total_nav"] / inception_navs[tier_id] - 1) * 100, 2)
        entry["tiers"][tier_id] = tier_entry

    tournament["history"].append(entry)
    tournament["last_updated"] = datetime.now().isoformat()
    with open(tournament_file, "w") as f:
        json.dump(tournament, f, indent=2, default=str)
    print(f"\nSaved {tournament_file}  ({len(tournament['history'])} days)")


if __name__ == "__main__":
    main()
