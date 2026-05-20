"""
Compute today's NAV for all 5 tiers + 4 benchmarks.

Tiers 1-4 (algorithmic): hold the picks from data/tier_holdings.json (regenerated monthly).
                         Equal-weight on the equity sleeve; cash sleeve sized by R_t.
Tier 5 (Werner manual):  hold the positions in config.json.werner_picks.holdings, plus cash.
Benchmarks: SPY, QQQ, 60/40 SPY/TLT, SSO (synthetic 1.5×). All $100K notional, compounded.

Output: data/tournament.json  (frontend consumes this)
"""
from __future__ import annotations
import json, os, sys, warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

BENCHMARK_TICKERS = ["SPY", "TLT", "QQQ", "SSO"]


def load_json(p): return json.load(open(p))


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    tickers = [t for t in tickers if t]
    if not tickers: return {}
    try:
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
        if data is None or data.empty: return {}
        closes = data["Close"]
        if isinstance(closes, pd.Series):
            return {tickers[0]: float(closes.dropna().iloc[-1])} if not closes.dropna().empty else {}
        out = {}
        for t in closes.columns:
            ser = closes[t].dropna()
            if not ser.empty: out[t] = float(ser.iloc[-1])
        return out
    except Exception as e:
        print(f"  warn fetch_prices: {e}", file=sys.stderr)
        return {}


def latest_R_t() -> tuple[float, str]:
    df = pd.read_csv(DATA / "regime_daily.csv", index_col="date", parse_dates=["date"])
    R = float(df["R_t"].dropna().iloc[-1])
    return R, df["R_t"].dropna().index[-1].strftime("%Y-%m-%d")


def regime_label(R):
    return "LOW RISK" if R < 0.30 else "ELEVATED" if R < 0.50 else "HIGH RISK" if R < 0.70 else "CRISIS"


def effr_daily_rate():
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key: return 0.04 / 252
    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)
        effr = fred.get_series("EFFR",
            observation_start=(datetime.now() - pd.Timedelta(days=14)).strftime("%Y-%m-%d"))
        return float(effr.dropna().iloc[-1]) / 252 / 100
    except Exception as e:
        print(f"  warn EFFR fallback: {e}", file=sys.stderr)
        return 0.04 / 252


def cash_pct_from_formula(R, spec):
    cp = min(spec["cash_max"], spec["cash_floor"] + R * spec["cash_slope"])
    return max(cp, spec["cash_floor"])


def main():
    cfg = load_json(REPO / "config.json")
    tier_specs   = cfg["tier_specs"]
    werner_spec  = cfg["werner_picks"]
    settings     = cfg["system_settings"]
    initial_cap  = float(settings["inception_capital_per_tier"])

    R_t, r_date = latest_R_t()
    regime = regime_label(R_t)
    effr_daily = effr_daily_rate()
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Date: {today}  (R_t as of {r_date})")
    print(f"R_t: {R_t:.3f} → {regime}  ·  EFFR daily ann ≈ {effr_daily*252*100:.2f}%")

    # Algorithmic tier holdings
    tier_holdings = load_json(DATA / "tier_holdings.json")["tiers"]
    werner_holdings = werner_spec["holdings"]
    werner_tickers  = [t for t, h in werner_holdings.items() if (h.get("shares") or 0) > 0]

    all_tickers = set()
    for tickers in tier_holdings.values():
        all_tickers.update(tickers)
    all_tickers.update(werner_tickers)
    all_tickers.update(BENCHMARK_TICKERS)
    print(f"Fetching prices for {len(all_tickers)} tickers...")
    prices = fetch_prices(sorted(all_tickers))
    print(f"  got {len(prices)}/{len(all_tickers)} prices")

    # ----- Load existing tournament for NAV continuity -----
    tournament_file = DATA / "tournament.json"
    if tournament_file.exists():
        tournament = load_json(tournament_file)
    else:
        tournament = {"inception_date": today, "history": []}
    history = tournament["history"]

    # Get previous-day NAVs for compounding (for benchmarks + algo tiers)
    prev_navs = {}
    prev_benchmarks = {}
    prev_holdings_per_tier = {}
    prev_prices_per_tier = {}    # for daily return on the equity sleeve
    if history:
        last = history[-1]
        for tid, td in last.get("tiers", {}).items():
            prev_navs[tid] = td.get("nav")
            prev_holdings_per_tier[tid] = td.get("holdings", [])
            prev_prices_per_tier[tid]   = td.get("prices_snapshot", {})
        prev_benchmarks = last.get("benchmarks", {})

    # ----- ALGORITHMIC TIERS 1-4 -----
    tier_outputs = {}
    for tid, spec in tier_specs.items():
        picks = tier_holdings.get(tid, [])
        # Filter to tickers we have prices for
        held = [t for t in picks if t in prices]
        if not held:
            # No data → keep prior nav
            tier_outputs[tid] = {"nav": prev_navs.get(tid, initial_cap), "equity": 0, "cash": prev_navs.get(tid, initial_cap)}
            continue

        cp = cash_pct_from_formula(R_t, spec)
        ep = 1 - cp

        # If first observation or rebalance — fresh allocation
        prev_nav = prev_navs.get(tid)
        if prev_nav is None or set(held) != set(prev_holdings_per_tier.get(tid, [])):
            # Rebalance day — equal weight across `held`, take 5 bps of trading cost on each side
            cost = (10/10000) * 1.0 * ep if prev_nav is None else (10/10000) * 1.0 * ep
            nav_after_cost = (prev_nav or initial_cap) * (1 - cost)
            equity_value = nav_after_cost * ep
            cash_value   = nav_after_cost * cp
            # Position snapshot
            shares = {t: (equity_value / len(held)) / prices[t] for t in held}
            tier_outputs[tid] = {
                "nav":   round(equity_value + cash_value, 2),
                "equity": round(equity_value, 2),
                "cash":   round(cash_value, 2),
                "cash_pct":  round(cp * 100, 1),
                "target_cash_pct": round(cp * 100, 1),
                "actual_cash_pct": round(cash_value / (equity_value + cash_value) * 100, 1) if (equity_value+cash_value) > 0 else 0,
                "n_positions": len(held),
                "holdings": held,
                "shares": {t: round(s, 6) for t, s in shares.items()},
                "prices_snapshot": {t: round(prices[t], 4) for t in held},
                "positions": [{
                    "ticker": t,
                    "shares": round(shares[t], 6),
                    "price":  round(prices[t], 2),
                    "value":  round(shares[t] * prices[t], 2),
                    "weight": round(shares[t] * prices[t] / (equity_value + cash_value) * 100, 1)
                              if (equity_value + cash_value) > 0 else 0,
                } for t in held],
            }
        else:
            # Same holdings → just compound daily returns + cash yield
            # Equity sleeve: walk forward by per-ticker price ratio
            prev_prices = prev_prices_per_tier.get(tid, {})
            equity_value = 0.0
            positions = []
            # Recover shares from last snapshot if present
            last_tier = history[-1]["tiers"].get(tid, {})
            shares = last_tier.get("shares", {})
            for t in held:
                if t in prices and t in shares:
                    val = shares[t] * prices[t]
                    equity_value += val
                    positions.append({
                        "ticker": t, "shares": round(shares[t], 6),
                        "price":  round(prices[t], 2),
                        "value":  round(val, 2),
                    })
            # Cash sleeve compounds
            prev_cash = last_tier.get("cash", 0)
            cash_value = prev_cash * (1 + effr_daily)

            total = equity_value + cash_value
            for p in positions:
                p["weight"] = round(p["value"] / total * 100, 1) if total > 0 else 0
            tier_outputs[tid] = {
                "nav":   round(total, 2),
                "equity": round(equity_value, 2),
                "cash":   round(cash_value, 2),
                "cash_pct": round(cp * 100, 1),
                "target_cash_pct": round(cp * 100, 1),
                "actual_cash_pct": round(cash_value / total * 100, 1) if total > 0 else 0,
                "n_positions": len(held),
                "holdings": held,
                "shares": shares,
                "prices_snapshot": {t: round(prices[t], 4) for t in held if t in prices},
                "positions": positions,
            }

    # ----- TIER 5 (WERNER) -----
    equity_w = 0.0
    werner_positions = []
    for ticker, h in werner_holdings.items():
        shares = float(h.get("shares") or 0)
        if shares <= 0: continue
        if ticker not in prices:
            werner_positions.append({"ticker": ticker, "shares": shares, "price": None,
                                     "value": None, "cost_basis": h.get("cost"), "gain_pct": None, "_note":"no price"})
            continue
        px = prices[ticker]
        val = shares * px
        equity_w += val
        cost = float(h.get("cost") or 0)
        werner_positions.append({
            "ticker": ticker, "shares": shares,
            "price": round(px, 2), "value": round(val, 2),
            "cost_basis": round(cost, 2),
            "gain_pct": round((px / cost - 1) * 100, 1) if cost > 0 else None,
        })
    # Werner cash: from config.cash, compounded by EFFR if we have a previous record
    prev_werner = (history[-1]["tiers"].get("5_werner", {}) if history else {}) or {}
    if prev_werner and "cash" in prev_werner:
        cash_w = float(prev_werner["cash"]) * (1 + effr_daily)
    else:
        cash_w = float(werner_spec.get("cash", 0))
    total_w = equity_w + cash_w
    w_cp = cash_pct_from_formula(R_t, werner_spec)
    for p in werner_positions:
        if p.get("value"):
            p["weight"] = round(p["value"] / total_w * 100, 1) if total_w > 0 else 0
    tier_outputs["5_werner"] = {
        "nav": round(total_w, 2),
        "equity": round(equity_w, 2),
        "cash":   round(cash_w, 2),
        "cash_pct": round(w_cp * 100, 1),
        "target_cash_pct": round(w_cp * 100, 1),
        "actual_cash_pct": round(cash_w / total_w * 100, 1) if total_w > 0 else 0,
        "n_positions": len([p for p in werner_positions if p.get("value")]),
        "holdings": [p["ticker"] for p in werner_positions if p.get("value")],
        "positions": werner_positions,
    }

    # ----- BENCHMARKS ($100K notional, compounding by SPY/QQQ/SSO daily; 60/40 monthly rebalance) -----
    bench_out = {}
    today_prices = {b: prices.get(b) for b in BENCHMARK_TICKERS}

    for b in ["SPY", "QQQ"]:
        if not prev_benchmarks:
            bench_out[b] = {"nav": initial_cap, "price": today_prices.get(b)}
        else:
            prev = prev_benchmarks.get(b, {})
            prev_p = prev.get("price")
            prev_n = prev.get("nav", initial_cap)
            if prev_p and today_prices.get(b):
                ret = today_prices[b] / prev_p - 1
                bench_out[b] = {"nav": round(prev_n * (1 + ret), 2), "price": today_prices[b]}
            else:
                bench_out[b] = {"nav": prev_n, "price": today_prices.get(b)}

    # SSO: synthetic 1.5× daily SPY return
    if not prev_benchmarks:
        bench_out["SSO"] = {"nav": initial_cap, "price": today_prices.get("SSO")}
    else:
        prev_p_spy = prev_benchmarks.get("SPY", {}).get("price")
        prev_n_sso = prev_benchmarks.get("SSO", {}).get("nav", initial_cap)
        if prev_p_spy and today_prices.get("SPY"):
            spy_ret = today_prices["SPY"] / prev_p_spy - 1
            bench_out["SSO"] = {"nav": round(prev_n_sso * (1 + 1.5 * spy_ret), 2),
                                "price": today_prices.get("SSO")}
        else:
            bench_out["SSO"] = {"nav": prev_n_sso, "price": today_prices.get("SSO")}

    # 60/40 — buy & rebalance to 60/40 once per month-start; here just compound by daily return
    if not prev_benchmarks:
        bench_out["60_40"] = {"nav": initial_cap}
    else:
        prev_p_spy = prev_benchmarks.get("SPY", {}).get("price")
        prev_p_tlt = prev_benchmarks.get("TLT", {}).get("price")
        prev_n_60_40 = prev_benchmarks.get("60_40", {}).get("nav", initial_cap)
        ret_spy = (today_prices["SPY"] / prev_p_spy - 1) if (prev_p_spy and today_prices.get("SPY")) else 0
        ret_tlt = (today_prices["TLT"] / prev_p_tlt - 1) if (prev_p_tlt and today_prices.get("TLT")) else 0
        bench_out["60_40"] = {"nav": round(prev_n_60_40 * (1 + 0.6 * ret_spy + 0.4 * ret_tlt), 2)}
    if today_prices.get("TLT"):
        bench_out["TLT"] = {"price": today_prices["TLT"]}

    # ----- Compose entry + write -----
    # Re-key benchmarks to lowercase to match backtest CSV
    benchmark_lookup = {"SPY": "spy", "QQQ": "qqq", "SSO": "sso", "60_40": "60_40"}
    bench_normalized = {}
    for k, v in bench_out.items():
        bench_normalized[benchmark_lookup.get(k, k.lower())] = v

    entry = {
        "date": today,
        "R_t": round(R_t, 4),
        "regime": regime,
        "effr_daily_pct": round(effr_daily * 252 * 100, 3),
        "tiers": tier_outputs,
        "benchmarks": bench_normalized,
    }
    # Replace today's entry if duplicate
    if history and history[-1].get("date") == today:
        history[-1] = entry
    else:
        history.append(entry)
    tournament["history"] = history
    tournament["last_updated"] = datetime.now().isoformat()

    with open(tournament_file, "w") as f:
        json.dump(tournament, f, indent=2, default=str)

    # Pretty print
    for tid, td in tier_outputs.items():
        name = tier_specs[tid]["short"] if tid in tier_specs else werner_spec["short"]
        print(f"  {name:<11}  NAV ${td['nav']:>11,.2f}  "
              f"({td['n_positions']} pos, cash {td['actual_cash_pct']:.0f}% vs target {td['target_cash_pct']:.0f}%)")
    for b, bv in bench_normalized.items():
        if "nav" in bv:
            print(f"  bench {b:<8}  NAV ${bv['nav']:>11,.2f}")
    print(f"\nSaved → {tournament_file}  ({len(history)} days)")


if __name__ == "__main__":
    main()
