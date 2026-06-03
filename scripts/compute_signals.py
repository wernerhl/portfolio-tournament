"""
Ticker signal engine — automated entry tickets per stock.

For every ticker in any tier or the scored-universe top-50, produce:

  signal           STRONG BUY / BUY / WATCH / HOLD / SELL (+ regime/gain overrides)
  signal_strength  0-100
  category         Compounder / Core / Growth / Cyclical / Catalyst / Speculative
  entry            {primary, secondary, basis}    (at MA200 / swing support / discount)
  stop             {price, pct, category_rule}    (Portfolio OS hard-stop rule)
  target           {conservative, base, aggressive, reward_risk}
  size             {shares, dollars, pct_portfolio, max_loss, regime_mult}
  why              1-paragraph plain-English rationale specific to the ticker
  risks            1-paragraph honest risk-flag enumeration

Output: data/ticker_signals.json   (keyed by ticker symbol)
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"

# ====================================================================
# Portfolio OS rules
# ====================================================================
STOP_PCT_BY_CATEGORY = {
    "Compounder":  0.15,
    "Core":        0.15,
    "Growth":      0.15,
    "Cyclical":    0.18,
    "Catalyst":    0.12,
    "Speculative": 0.25,
}

# Position sizing budget
RISK_BUDGET_PCT       = 0.01   # 1% of portfolio at risk per name
MAX_POSITION_PCT      = 0.05   # 5% portfolio cap per name


def classify_category(fund: dict) -> str:
    sector = fund.get("sector", "") or ""
    gm     = float(fund.get("grossMargins", 0) or 0)
    rev_g  = float(fund.get("revenueGrowth", 0) or 0)
    de     = float(fund.get("debtToEquity", 0) or 0)
    fcf    = float(fund.get("freeCashflow", 0) or 0)
    mcap   = float(fund.get("marketCap", 0) or 0)
    if sector in ("Energy", "Basic Materials"):
        return "Cyclical"
    if mcap > 0 and mcap < 10e9 and (gm < 0.20 or fcf < 0):
        return "Speculative"
    if gm > 0.40 and rev_g > 0.10 and de < 150 and fcf > 0:
        return "Compounder"
    if rev_g > 0.30:
        return "Growth"
    return "Core"


# ====================================================================
# Support / resistance — swing-low / swing-high detection
# ====================================================================
def _swing_extremes(arr: pd.Series, kind: str, window: int = 10) -> list[float]:
    """Return list of swing-low or swing-high price levels."""
    out = []
    a = arr.values
    n = len(a)
    cmp_ = np.less if kind == "low" else np.greater
    op   = np.min   if kind == "low" else np.max
    for i in range(window, n - window):
        lo, hi = i - window, i + window + 1
        if a[i] == op(a[lo:hi]):
            out.append(float(a[i]))
    return out


def find_support(prices: pd.Series, current: float) -> float:
    if len(prices) < 60:
        return current * 0.95
    recent = prices.tail(252) if len(prices) >= 252 else prices
    lows = _swing_extremes(recent, "low")
    supports = [s for s in lows if s < current * 0.98]
    if supports:
        return max(supports)        # nearest support BELOW
    if len(prices) >= 200:
        ma200 = float(prices.rolling(200).mean().iloc[-1])
        if ma200 < current:
            return ma200
    return current * 0.95


def find_resistance(prices: pd.Series, current: float) -> float:
    if len(prices) < 60:
        return current * 1.20
    recent = prices.tail(252) if len(prices) >= 252 else prices
    highs = _swing_extremes(recent, "high")
    resistances = [r for r in highs if r > current * 1.02]
    if resistances:
        return min(resistances)     # nearest resistance ABOVE
    return float(recent.max())


# ====================================================================
# Per-ticker signal
# ====================================================================
def compute_signal(ticker: str,
                   scores: pd.DataFrame,
                   prices_df: pd.DataFrame,
                   fund_df: pd.DataFrame,
                   regime: dict,
                   portfolio_holdings: dict,
                   portfolio_value: float) -> dict | None:
    if ticker not in prices_df.columns:
        return None
    px = prices_df[ticker].dropna()
    if len(px) < 50:
        return None
    current = float(px.iloc[-1])

    row = scores[scores["ticker"] == ticker]
    if row.empty:
        return None
    row = row.iloc[0]
    composite = float(row.get("composite", 0))
    tech_s    = float(row.get("tech_score", 0))
    fund_s    = float(row.get("fund_score", 0))
    rank      = int(row.get("composite_rank", 999))

    # Technicals
    ma200 = float(px.rolling(200).mean().iloc[-1]) if len(px) >= 200 else None
    ma50  = float(px.rolling(50).mean().iloc[-1])  if len(px) >= 50  else None
    delta = px.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = float((100 - 100 / (1 + rs)).iloc[-1])
    if np.isnan(rsi): rsi = 50.0
    hi52  = float(px.tail(252).max()) if len(px) >= 252 else float(px.max())
    lo52  = float(px.tail(252).min()) if len(px) >= 252 else float(px.min())
    rng52 = hi52 - lo52
    pct52 = ((current - lo52) / rng52 * 100) if rng52 > 0 else 50.0
    ma200_dist = ((current / ma200) - 1) * 100 if ma200 else 0.0
    ma50_dist  = ((current / ma50)  - 1) * 100 if ma50  else 0.0
    rvol  = float(px.pct_change().tail(20).std() * np.sqrt(252) * 100)

    # Fundamentals
    fund = fund_df.loc[ticker].to_dict() if ticker in fund_df.index else {}
    def _num(k):
        v = fund.get(k)
        if v is None or (isinstance(v, float) and math.isnan(v)): return None
        try: return float(v)
        except (ValueError, TypeError): return None
    fwd_pe     = _num("forwardPE")
    trail_pe   = _num("trailingPE")
    rev_growth = _num("revenueGrowth")
    gm         = _num("grossMargins")
    op_m       = _num("operatingMargins")
    roe        = _num("returnOnEquity")
    fcf        = _num("freeCashflow")
    de         = _num("debtToEquity")
    beta       = _num("beta")
    sector     = fund.get("sector", "") or ""

    category = classify_category(fund)
    stop_pct = STOP_PCT_BY_CATEGORY.get(category, 0.15)

    # Regime
    R_full = float(regime.get("R_full", 0.3))
    regime_label = regime.get("regime", "LOW RISK")
    if   R_full < 0.30: regime_mult = 1.0
    elif R_full < 0.50: regime_mult = 0.75
    elif R_full < 0.70: regime_mult = 0.50
    else:               regime_mult = 0.0

    # Portfolio context
    already_held = ticker in portfolio_holdings
    current_shares = float(portfolio_holdings.get(ticker, {}).get("shares", 0))
    current_cost   = float(portfolio_holdings.get(ticker, {}).get("cost",   0))

    # Support / resistance
    support    = find_support(px, current)
    resistance = find_resistance(px, current)

    # ---- Entry ----
    if ma200 and ma200 < current:
        entry_primary = max(ma200, support)
    elif ma200:
        entry_primary = support
    else:
        entry_primary = current * 0.95
    # If currently at/below MA200 ⇒ buy slight discount to current
    if ma200 and current <= ma200 * 1.02:
        entry_primary = current * 0.99
    entry_primary   = round(float(entry_primary), 2)
    entry_secondary = round(entry_primary * 0.93, 2)

    # Decide entry basis label
    if ma200 and abs((entry_primary / ma200 - 1) * 100) < 3:
        entry_basis = "200-DMA"
    elif support and abs(entry_primary / support - 1) < 0.02:
        entry_basis = "swing support"
    elif entry_primary > current:
        entry_basis = "stretch entry"
    else:
        entry_basis = "5% discount"

    # ---- Stop ----
    stop_price = round(entry_primary * (1 - stop_pct), 2)
    risk_per_share = max(0.0, entry_primary - stop_price)

    # ---- Target ----
    target_conservative = round(entry_primary + risk_per_share * 1.5, 2)
    targets_above = [r for r in [resistance, ma50] if r is not None and r > entry_primary * 1.05]
    target_base = round(min(targets_above), 2) if targets_above else target_conservative
    target_aggressive = round(hi52, 2)
    reward_risk = round((target_base - entry_primary) / risk_per_share, 1) if risk_per_share > 0 else 0.0

    # ---- Size ----
    if portfolio_value <= 0 or risk_per_share <= 0 or entry_primary <= 0:
        target_shares = 0
    else:
        shares_by_risk = int((portfolio_value * RISK_BUDGET_PCT) / risk_per_share)
        shares_by_cap  = int((portfolio_value * MAX_POSITION_PCT) / entry_primary)
        target_shares  = max(1, min(shares_by_risk, shares_by_cap))
    target_shares = max(0, int(target_shares * regime_mult))   # regime can zero it
    dollar_size   = round(target_shares * entry_primary, 2)
    max_loss      = round(target_shares * risk_per_share, 2)

    # ---- Signal logic ----
    buy_cond = {
        "score_above_35":     composite >= 35,
        "rsi_not_overbought": rsi < 55,
        "near_support":       (ma200_dist < 8) if ma200 else (pct52 < 50),
        "regime_permits":     R_full < 0.50,
        "not_overextended":   ma200_dist < 25,
    }
    strong_cond = {
        "score_top_20pct": composite >= 38,
        "rsi_oversold":    rsi < 40,
        "at_ma200":        (abs(ma200_dist) < 5) if ma200 else False,
        "regime_low_risk": R_full < 0.30,
    }
    sell_cond = {
        "score_collapsed":         composite < 20,
        "rsi_extreme_overbought":  rsi > 80,
        "far_above_ma200":         ma200_dist > 40,
    }
    n_buy, n_strong, n_sell = sum(buy_cond.values()), sum(strong_cond.values()), sum(sell_cond.values())

    if n_sell >= 2:
        signal, strength = "SELL", min(100, n_sell * 35)
    elif n_buy >= 4 and n_strong >= 3:
        signal, strength = "STRONG BUY", min(100, 70 + n_strong * 10)
    elif n_buy >= 3:
        signal, strength = "BUY", min(100, 40 + n_buy * 12)
    elif n_buy >= 2:
        signal, strength = "WATCH", 30 + n_buy * 10
    else:
        signal, strength = "HOLD", 50

    # Regime crisis override
    if R_full >= 0.70 and signal in ("BUY", "STRONG BUY"):
        signal, strength = "HOLD — REGIME CRISIS", 20

    # Big-winner trail override
    if already_held and current_cost > 0:
        gain_pct = (current / current_cost - 1) * 100
        if gain_pct > 100:
            trail = current * 0.78
            signal = f"HOLD — +{gain_pct:.0f}% (trail at ${trail:.0f})"
            strength = 60

    # ---- WHY ----
    why = [f"Ranked #{rank} in universe ({composite:.1f}/50)"]
    if   rsi < 30: why.append(f"deeply oversold (RSI {rsi:.0f})")
    elif rsi < 40: why.append(f"oversold (RSI {rsi:.0f})")
    elif rsi > 70: why.append(f"overbought (RSI {rsi:.0f})")
    if ma200:
        if abs(ma200_dist) < 3:    why.append("right at 200-DMA support")
        elif ma200_dist < -5:      why.append(f"{abs(ma200_dist):.0f}% below 200-DMA")
        elif ma200_dist > 20:      why.append(f"{ma200_dist:.0f}% above 200-DMA (extended)")
    if fwd_pe is not None:
        if   fwd_pe < 15: why.append(f"forward P/E {fwd_pe:.1f}")
        elif fwd_pe > 50: why.append(f"expensive at {fwd_pe:.0f}× forward earnings")
    if gm and gm > 0.70:       why.append(f"{gm*100:.0f}% gross margins")
    if rev_growth and rev_growth > 0.20:  why.append(f"{rev_growth*100:.0f}% revenue growth")
    elif rev_growth and rev_growth < -0.05: why.append(f"revenue declining {rev_growth*100:.0f}%")
    dd_high = ((current / hi52) - 1) * 100
    if dd_high < -20: why.append(f"{abs(dd_high):.0f}% off 52-week high")
    why.append(f"regime: {regime_label} ({regime_mult:.0%} sizing)")
    why_text = ". ".join(why) + "."

    # ---- RISKS ----
    risks = []
    if trail_pe and fwd_pe and trail_pe > fwd_pe * 2.5:
        risks.append("Trailing P/E much higher than forward — consensus expects an earnings jump that may not materialize")
    if sector in ("Energy", "Basic Materials"):
        risks.append("Commodity-linked revenue, cyclical risk")
    if de and de > 150:    risks.append(f"High leverage (D/E {de:.0f})")
    if beta and beta > 1.5:risks.append(f"High market sensitivity (beta {beta:.1f})")
    if dd_high < -30:      risks.append(f"Deep drawdown ({dd_high:.0f}%) — momentum breakdown could continue")
    if rvol > 50:          risks.append(f"High volatility ({rvol:.0f}% annualized)")
    if fcf is not None and fcf < 0: risks.append("Negative free cash flow")
    if not risks:          risks.append("No major risk flags identified")
    risk_text = ". ".join(risks) + "."

    return {
        "ticker":           ticker,
        "signal":           signal,
        "signal_strength":  int(strength),
        "category":         category,
        "entry":            {"primary": entry_primary, "secondary": entry_secondary, "basis": entry_basis},
        "stop":             {"price": stop_price, "pct": int(stop_pct * 100),
                              "category_rule": f"-{stop_pct*100:.0f}% ({category})"},
        "target":           {"conservative": target_conservative, "base": target_base,
                              "aggressive": target_aggressive, "reward_risk": reward_risk},
        "size":             {"shares": target_shares, "dollars": dollar_size,
                              "pct_portfolio": round(dollar_size / portfolio_value * 100, 1) if portfolio_value > 0 else 0,
                              "max_loss": max_loss, "regime_mult": regime_mult},
        "why":              why_text,
        "risks":            risk_text,
        "conditions":       {"buy": buy_cond, "strong_buy": strong_cond, "sell": sell_cond},
        "data": {
            "price":         round(current, 2),
            "rsi":           round(rsi, 1),
            "ma200":         round(ma200, 2) if ma200 else None,
            "ma200_dist":    round(ma200_dist, 1),
            "ma50":          round(ma50, 2)  if ma50  else None,
            "ma50_dist":     round(ma50_dist, 1),
            "pct_52w":       round(pct52, 1),
            "high_52w":      round(hi52, 2),
            "low_52w":       round(lo52, 2),
            "realized_vol":  round(rvol, 1),
            "composite":     round(composite, 1),
            "rank":          rank,
            "sector":        sector,
            "fwd_pe":        round(fwd_pe, 1) if fwd_pe is not None else None,
            "gross_margin":  round(gm * 100, 1) if gm is not None else None,
            "rev_growth":    round(rev_growth * 100, 1) if rev_growth is not None else None,
            "roe":           round(roe * 100, 1) if roe is not None else None,
            "fcf_B":         round(fcf / 1e9, 2) if fcf is not None else None,
            "support":       round(float(support), 2),
            "resistance":    round(float(resistance), 2),
        },
    }


# ====================================================================
# Main
# ====================================================================
class _NpEnc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):  return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, np.ndarray):     return o.tolist()
        if isinstance(o, (np.bool_,)):    return bool(o)
        return super().default(o)


def _sanitize_nan(o):
    if isinstance(o, dict):  return {k: _sanitize_nan(v) for k, v in o.items()}
    if isinstance(o, list):  return [_sanitize_nan(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    return o


def estimate_portfolio_value() -> float:
    """Werner equity (shares × latest price) + cash, from config + prices."""
    try:
        cfg = json.load(open(REPO / "config.json"))
        wp  = cfg.get("werner_picks", {})
        cash = float(wp.get("cash", 0))
        prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
        equity = 0.0
        for tk, h in wp.get("holdings", {}).items():
            shares = float(h.get("shares", 0) or 0)
            if shares <= 0: continue
            sym = tk if tk in prices.columns else tk.replace("-", ".")
            if sym in prices.columns:
                px = prices[sym].dropna()
                if not px.empty:
                    equity += shares * float(px.iloc[-1])
        return round(equity + cash, 2)
    except Exception as e:
        print(f"  warn portfolio_value fallback: {e}")
        return 176000.0


def main():
    print("Loading data...")
    prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in prices.columns:
        prices = prices.drop(columns=["SPY_volume"])
    prices.index = pd.to_datetime(prices.index)
    fund = pd.read_parquet(SOURCE / "fundamentals_snapshot.parquet")
    scores = pd.read_csv(DATA / "scored_universe.csv")
    print(f"  prices: {prices.shape}, fund: {fund.shape}, scores: {len(scores)}")

    # Regime
    try:
        rdf = pd.read_csv(DATA / "regime_v2_daily.csv", parse_dates=["date"], index_col="date")
        last = rdf.dropna(subset=["R_full"]).iloc[-1]
        regime = {
            "R_full": float(last.get("R_full", 0.3)),
            "R_lead": float(last.get("R_lead", 0.3)) if "R_lead" in last else 0.3,
            "regime": str(last.get("regime", "LOW RISK")),
        }
    except Exception:
        regime = {"R_full": 0.3, "R_lead": 0.3, "regime": "LOW RISK"}
    print(f"  regime: R_full={regime['R_full']:.3f} ({regime['regime']})")

    cfg = json.load(open(REPO / "config.json"))
    werner_holdings = cfg.get("werner_picks", {}).get("holdings", {})
    portfolio_value = estimate_portfolio_value()
    print(f"  portfolio value: ${portfolio_value:,.0f}")

    # Universe: tier holdings + Werner picks + scored top-50
    tickers = set()
    try:
        th = json.load(open(DATA / "tier_holdings.json"))
        for _, lst in th.get("tiers", {}).items():
            tickers.update(lst)
    except Exception: pass
    tickers.update(werner_holdings.keys())
    if len(scores) > 0:
        tickers.update(scores.nlargest(50, "composite")["ticker"].tolist())
    print(f"  computing signals for {len(tickers)} tickers")

    signals = {}
    for tk in sorted(tickers):
        # Try as-is then alt format
        sym = tk if tk in prices.columns else tk.replace(".", "-")
        if sym not in prices.columns:
            continue
        sig = compute_signal(sym, scores, prices, fund, regime,
                             werner_holdings, portfolio_value)
        if sig is None:
            continue
        signals[tk] = sig
        print(f"    {tk:8s} {sig['signal']:30s}  entry ${sig['entry']['primary']:>8.2f}  "
              f"stop ${sig['stop']['price']:>8.2f}  target ${sig['target']['base']:>8.2f}  "
              f"size ${sig['size']['dollars']:>8.0f}")

    payload = _sanitize_nan({"updated": pd.Timestamp.now().isoformat(),
                              "portfolio_value": portfolio_value,
                              "regime": regime,
                              "n": len(signals),
                              "signals": signals})
    out = DATA / "ticker_signals.json"
    with open(out, "w") as f:
        json.dump(payload, f, separators=(",", ":"), cls=_NpEnc, allow_nan=False)

    # Distribution
    dist = {}
    for s in signals.values():
        key = s["signal"].split(" —")[0].strip()
        dist[key] = dist.get(key, 0) + 1
    print(f"\nSignal distribution:")
    for k, n in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {k:20s} {n}")
    print(f"\nSaved {out}  ({len(signals)} tickers)")


if __name__ == "__main__":
    main()
