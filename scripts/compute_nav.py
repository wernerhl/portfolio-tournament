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
BENCHMARK_KEYS = ["spy", "qqq", "sso", "tlt"]   # canonical lowercase storage keys
INCEPTION_FILE = DATA / "benchmark_inception.json"
START_CAPITAL = 100000.0


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


# ──────────────────────────────────────────────────────────────────────
# Inception-anchored benchmarks (replaces the buggy day-over-day chaining
# that hit a case-mismatch on prev_benchmarks and froze NAV at $100k).
# Each benchmark NAV = START_CAPITAL × (current_price / inception_price).
# Inception prices persist in data/benchmark_inception.json.
# ──────────────────────────────────────────────────────────────────────
def get_inception_prices(history, current_prices):
    """Return dict {spy, qqq, sso, tlt, date}. Create/persist if missing."""
    if INCEPTION_FILE.exists():
        try:
            return json.load(open(INCEPTION_FILE))
        except Exception as e:
            print(f"  warn corrupted {INCEPTION_FILE}: {e}", file=sys.stderr)

    inception = {}
    if history:
        first = history[0]
        bms = first.get("benchmarks", {}) or {}
        for b in BENCHMARK_KEYS:
            entry = bms.get(b, {})
            if isinstance(entry, dict) and entry.get("price"):
                inception[b] = float(entry["price"])
        inception_date = first.get("date")
    else:
        inception_date = datetime.now().strftime("%Y-%m-%d")

    # Fill any missing slot from today's fetched prices (first-ever run path)
    upper_map = {"spy": "SPY", "qqq": "QQQ", "sso": "SSO", "tlt": "TLT"}
    for b in BENCHMARK_KEYS:
        if b not in inception and current_prices.get(upper_map[b]):
            inception[b] = float(current_prices[upper_map[b]])

    inception["date"] = inception_date
    with open(INCEPTION_FILE, "w") as f:
        json.dump(inception, f, indent=2)
    print(f"  wrote {INCEPTION_FILE.name}  ({inception})")
    return inception


def benchmark_navs_from_prices(prices_lower: dict, inception: dict) -> dict:
    """
    prices_lower: {"spy": 759.57, "qqq": ..., "sso": ..., "tlt": ...}
    Returns {"spy":{nav,price}, "qqq":..., "sso":..., "tlt":..., "60_40":{nav}}.
    """
    out = {}
    for b in BENCHMARK_KEYS:
        px  = prices_lower.get(b)
        px0 = inception.get(b)
        if px is not None and px0:
            out[b] = {"nav": round(START_CAPITAL * px / px0, 2), "price": round(float(px), 4)}
        elif px is not None:
            out[b] = {"price": round(float(px), 4)}   # no inception yet → no nav

    spy_px, spy0 = prices_lower.get("spy"), inception.get("spy")
    tlt_px, tlt0 = prices_lower.get("tlt"), inception.get("tlt")
    if spy_px and spy0 and tlt_px and tlt0:
        nav_6040 = START_CAPITAL * (0.6 * spy_px / spy0 + 0.4 * tlt_px / tlt0)
        out["60_40"] = {"nav": round(nav_6040, 2)}
    return out


def backfill_benchmark_navs(tournament_path: Path = None) -> int:
    """
    One-off migration: recompute NAV for every benchmark on every past date
    using the persisted inception prices. Returns number of entries touched.
    """
    tournament_path = tournament_path or (DATA / "tournament.json")
    if not tournament_path.exists():
        return 0
    t = json.load(open(tournament_path))
    history = t.get("history", [])
    if not history:
        return 0

    # Ensure inception file exists before backfilling
    inception = get_inception_prices(history, {})
    touched = 0
    for entry in history:
        bms = entry.get("benchmarks", {}) or {}
        prices_lower = {}
        for b in BENCHMARK_KEYS:
            blob = bms.get(b, {})
            if isinstance(blob, dict) and blob.get("price"):
                prices_lower[b] = float(blob["price"])
        if not prices_lower:
            continue
        new_bms = benchmark_navs_from_prices(prices_lower, inception)
        entry["benchmarks"] = new_bms
        touched += 1
    t["history"] = history
    with open(tournament_path, "w") as f:
        json.dump(t, f, indent=2, default=str)
    print(f"  backfilled {touched} historical benchmark entries → {tournament_path.name}")
    return touched


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

    # ----- BENCHMARKS (inception-anchored: NAV = $100k × current/inception) -----
    # The old day-over-day chaining looked up prev_benchmarks["SPY"] but storage
    # was lowercase ("spy") → prev was always {} → NAV froze at 100000 forever.
    # Inception anchoring is robust to history corruption, missing days, and
    # case-sensitive key bugs.
    inception = get_inception_prices(history, prices)
    prices_lower = {
        "spy": prices.get("SPY"),
        "qqq": prices.get("QQQ"),
        "sso": prices.get("SSO"),
        "tlt": prices.get("TLT"),
    }
    bench_normalized = benchmark_navs_from_prices(prices_lower, inception)

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
