"""
Ticker signal engine v2 — router with two modes.

  compute_signal()           dispatch based on ownership in Werner's holdings
    ├─ compute_position_signal()   owned stocks: P&L, trailing stop, trim trigger,
    │                              hedge recommendation, thesis check.
    └─ compute_entry_signal()      non-owned: entry / stop / target / size,
                                   with EXTENDED-stock fix (>15% above MA200 →
                                   WATCH / WAIT for pullback, no fantasy entry).

The dashboard branches on `mode` ∈ {"position", "entry"}.

Output: data/ticker_signals.json (keyed by ticker).
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

# Trailing stop schedule for OWNED positions, by unrealized gain %
TRAIL_SCHEDULE = [
    # (gain_lt, trail_pct, label)
    (25,   0.12, "0–25%"),
    (50,   0.15, "25–50%"),
    (100,  0.18, "50–100%"),
    (10000, 0.22, "100%+"),
]

# Profit-trim schedule: every 100% of cost basis, trim 20%
TRIM_SCHEDULE = [(100, 0.20), (200, 0.20), (300, 0.20)]

RISK_BUDGET_PCT  = 0.01
MAX_POSITION_PCT = 0.05


# ====================================================================
# Helpers
# ====================================================================
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


def _swing(arr: pd.Series, kind: str, window: int = 10) -> list[float]:
    out = []
    a = arr.values
    n = len(a)
    op = np.min if kind == "low" else np.max
    for i in range(window, n - window):
        if a[i] == op(a[i - window:i + window + 1]):
            out.append(float(a[i]))
    return out


def find_support(prices: pd.Series, current: float) -> float:
    if len(prices) < 60:
        return current * 0.95
    recent = prices.tail(252) if len(prices) >= 252 else prices
    lows = _swing(recent, "low")
    supports = [s for s in lows if s < current * 0.98]
    if supports:
        return max(supports)
    if len(prices) >= 200:
        ma200 = float(prices.rolling(200).mean().iloc[-1])
        if ma200 < current:
            return ma200
    return current * 0.95


def find_resistance(prices: pd.Series, current: float) -> float:
    if len(prices) < 60:
        return current * 1.20
    recent = prices.tail(252) if len(prices) >= 252 else prices
    highs = _swing(recent, "high")
    resistances = [r for r in highs if r > current * 1.02]
    if resistances:
        return min(resistances)
    return float(recent.max())


def rsi14(px: pd.Series) -> float:
    delta = px.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    v = float((100 - 100 / (1 + rs)).iloc[-1])
    return 50.0 if (v is None or math.isnan(v)) else v


def fund_num(fund: dict, key: str):
    v = fund.get(key)
    if v is None: return None
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x): return None
        return x
    except (TypeError, ValueError):
        return None


def trail_for_gain(gain_pct: float) -> tuple[float, str]:
    for cap, trail, label in TRAIL_SCHEDULE:
        if gain_pct < cap:
            return trail, label
    return TRAIL_SCHEDULE[-1][1], TRAIL_SCHEDULE[-1][2]


def regime_multiplier(R_full: float) -> float:
    if   R_full < 0.30: return 1.0
    elif R_full < 0.50: return 0.75
    elif R_full < 0.70: return 0.50
    else:               return 0.0


# ── Trade-now strength = setup × entry-proximity discount ───────────────
# The raw signal_strength encodes "this is a great setup." It does NOT
# encode "buy at THIS price." When price has run above the model's entry,
# discount the strength so the dashboard's trade-now bar reflects actual
# entry timing, not just thesis quality. Without this, TPL would show
# strength 100 even when price is +3% above the buy zone.
def trade_now_strength(setup_strength: int, price: float | None,
                        entry: float | None, signal: str) -> int:
    if signal in ("BUY", "STRONG BUY") and entry and price and entry > 0:
        if price <= entry:
            prox = 1.0
        else:
            overshoot = (price - entry) / entry
            # Linear decay: at entry = 1.0, +10% = 0.4, floor 0.2.
            prox = max(0.2, 1.0 - overshoot * 6.0)
        return int(round(setup_strength * prox))
    return int(setup_strength)


def trade_now_note(price: float | None, entry: float | None, signal: str) -> str | None:
    if signal in ("BUY", "STRONG BUY") and entry and price and price > entry:
        pct = (price - entry) / entry * 100
        return f"price ${price:.0f} is {pct:.0f}% above entry ${entry:.0f} — wait for pullback"
    return None


# ====================================================================
# Position mode (owned stocks)
# ====================================================================
LABEL = "mechanical rulebook; expectancy not validated"     # order 16-Sept 1.7: on every signal record
POSITION_MIN_HISTORY = 120                                    # order 16-Sept 1.2: below this, "no signal (insufficient history)"


def _pct(x: float, nd: int = 1) -> str:
    return f"{x:+.{nd}f} percent" if abs(x) >= 0.05 else "0.0 percent"


def compute_position_signal(ticker, shares, cost_basis, scores, prices_df, fund_df,
                             regime, portfolio_value):
    """Position mode (order 16-Sept 1.7): observations against the rulebook, never
    imperatives. The stop level is computed from the cost basis under the
    rulebook's category rule; the record carries cost_basis, stop_from_cost and
    the label; no entry-mode trade-now strength is produced."""
    px = prices_df[ticker].dropna()
    current = float(px.iloc[-1]) if len(px) else None
    fund = fund_df.loc[ticker].to_dict() if ticker in fund_df.index else {}
    category   = classify_category(fund)
    hard_stop_pct = STOP_PCT_BY_CATEGORY.get(category, 0.15)
    hard_stop  = round(cost_basis * (1 - hard_stop_pct), 2)
    stop_rule  = f"-{int(hard_stop_pct*100)} percent rule ({category})"
    base = {
        "ticker": ticker, "mode": "position", "label": LABEL, "category": category,
        "cost_basis": round(float(cost_basis), 2), "stop_from_cost": hard_stop, "stop_rule": stop_rule,
        "signal_strength": None, "trade_now_strength": None, "trade_now_note": None,
        "history_sessions": int(len(px)),
    }
    if current is None or len(px) < POSITION_MIN_HISTORY:
        # 1.2: held, displayed, marked — never omitted
        gain_pct = (current / cost_basis - 1) * 100 if (current and cost_basis) else None
        base.update({
            "signal": "no signal (insufficient history)", "state": "insufficient_history",
            "observation": (f"{int(len(px))} sessions of price history; the rulebook's signals need "
                            f"{POSITION_MIN_HISTORY}. Held and displayed; not scored."),
            "position": {"shares": float(shares), "cost_basis": round(float(cost_basis), 2),
                         "current_price": round(current, 2) if current else None,
                         "gain_pct": round(gain_pct, 1) if gain_pct is not None else None,
                         "gain_dollars": round((current - cost_basis) * shares, 2) if current else None,
                         "position_value": round(current * shares, 2) if current else None,
                         "weight_pct": round(current * shares / portfolio_value * 100, 1) if (current and portfolio_value > 0) else None,
                         "peak_price": None},
            "stops": {"hard_stop": hard_stop, "hard_stop_pct": int(hard_stop_pct * 100), "trail_stop": None,
                      "trail_pct": None, "trail_bracket": None, "trail_distance_pct": None,
                      "active_stop": hard_stop, "active_stop_type": "hard"},
            "trim": None, "hedge": None, "thesis": [], "why": "insufficient history for the rulebook's signals",
            "data": {"price": round(current, 2) if current else None},
        })
        return base

    # P&L
    gain_pct      = (current / cost_basis - 1) * 100
    gain_dollars  = (current - cost_basis) * shares
    position_value = current * shares
    pos_weight     = position_value / portfolio_value * 100 if portfolio_value > 0 else 0

    # Trailing level from the 252-session peak (the rulebook's trailing schedule)
    peak = float(px.tail(252).max())
    trail_pct, bracket = trail_for_gain(gain_pct)
    trail_stop = round(peak * (1 - trail_pct), 2)
    trail_dist = round((current / trail_stop - 1) * 100, 1) if trail_stop > 0 else 0

    active_stop = max(trail_stop, hard_stop)
    active_stop_type = "trailing" if trail_stop >= hard_stop else "hard"

    # Trim schedule: highest unreached threshold + most-recently-crossed threshold
    next_trim = None
    fired_trim = None
    for cap, pct in TRIM_SCHEDULE:
        if gain_pct < cap:
            next_trim = {
                "at_gain":       f"+{cap}%",
                "trigger_price": round(cost_basis * (1 + cap / 100), 2),
                "trim_pct":      int(pct * 100),
                "trim_shares":   max(1, int(shares * pct)),
                "distance":      round((cost_basis * (1 + cap / 100) / current - 1) * 100, 1),
            }
            break
        else:
            fired_trim = {"at_gain": f"+{cap}%", "trim_pct": int(pct * 100),
                          "trim_shares": max(1, int(shares * pct))}

    # Technicals
    ma200 = float(px.rolling(200).mean().iloc[-1]) if len(px) >= 200 else None
    ma50  = float(px.rolling(50).mean().iloc[-1])  if len(px) >= 50  else None
    rsi   = rsi14(px)
    ma200_dist = ((current / ma200) - 1) * 100 if ma200 else 0

    # Hedge conditions of the rulebook (observed, not prescribed)
    reasons = []
    if rsi > 70:               reasons.append(f"RSI {rsi:.0f} (overbought)")
    if ma200_dist > 25:        reasons.append(f"{ma200_dist:.0f}% above 200-DMA (extended)")
    if gain_pct > 40:          reasons.append(f"+{gain_pct:.0f}% unrealized gain")
    R_full = float(regime.get("R_full", 0.3))
    if R_full > 0.50:          reasons.append(f"regime elevated (R={R_full:.2f})")
    hedge = None
    if len(reasons) >= 2:
        hedge = {"type": "condition_met", "reasons": reasons,
                 "text": f"the rulebook's hedge condition is met (two or more of its four flags): {'; '.join(reasons)}."}
    elif len(reasons) == 1:
        hedge = {"type": "one_flag", "reasons": reasons, "text": f"one of the rulebook's four hedge flags is present: {reasons[0]}."}

    # Thesis check (5 items) — descriptive readings
    thesis = []
    rev_g = fund_num(fund, "revenueGrowth")
    if   rev_g is not None and rev_g >  0.10: thesis.append({"status":"green",  "text":f"Revenue growth {rev_g*100:.0f}%"})
    elif rev_g is not None and rev_g >  0.0:  thesis.append({"status":"yellow", "text":f"Revenue growth slowing ({rev_g*100:.0f}%)"})
    elif rev_g is not None:                    thesis.append({"status":"red",    "text":f"Revenue declining ({rev_g*100:.0f}%)"})
    gm = fund_num(fund, "grossMargins")
    if   gm is not None and gm > 0.50: thesis.append({"status":"green",  "text":f"Gross margins {gm*100:.0f}%"})
    elif gm is not None and gm > 0.30: thesis.append({"status":"yellow", "text":f"Gross margins compressing ({gm*100:.0f}%)"})
    elif gm is not None:                thesis.append({"status":"red",    "text":f"Gross margins weak ({gm*100:.0f}%)"})
    if   rsi > 70: thesis.append({"status":"yellow", "text":f"RSI {rsi:.0f} — overbought"})
    elif rsi < 30: thesis.append({"status":"yellow", "text":f"RSI {rsi:.0f} — oversold"})
    else:          thesis.append({"status":"green",  "text":f"RSI {rsi:.0f} — neutral"})
    if   ma200_dist > 30:  thesis.append({"status":"yellow", "text":f"{ma200_dist:.0f}% above 200-DMA — technically extended"})
    elif ma200_dist < -10: thesis.append({"status":"red",    "text":f"{abs(ma200_dist):.0f}% below 200-DMA — trend broken"})
    else:                  thesis.append({"status":"green",  "text":"Within normal range of 200-DMA"})
    srow = scores[scores["ticker"] == ticker]
    if len(srow) > 0:
        composite = float(srow.iloc[0]["composite"]); rank = int(srow.iloc[0]["composite_rank"])
    else:
        composite = 0.0; rank = 999
    if   composite >= 35: thesis.append({"status":"green",  "text":f"Score {composite:.1f}/50 (rank #{rank})"})
    elif composite >= 25: thesis.append({"status":"yellow", "text":f"Score {composite:.1f}/50 (rank #{rank})"})
    else:                 thesis.append({"status":"red",    "text":f"Score weak: {composite:.1f}/50 (rank #{rank})"})
    n_red    = sum(1 for t in thesis if t["status"] == "red")
    n_yellow = sum(1 for t in thesis if t["status"] == "yellow")

    # The observation (1.7): the position's standing against each rulebook level, in words.
    # Imperatives ("SELL", "TRIM") are gone; the record states where price is relative to the level.
    vs_hard  = (current / hard_stop - 1) * 100
    vs_trail = (current / trail_stop - 1) * 100 if trail_stop > 0 else None
    if current <= hard_stop:
        state = "below_stop_from_cost"
        observation = (f"price ${current:.2f} is {abs(vs_hard):.1f} percent below the rulebook stop of ${hard_stop:.2f} "
                       f"(from cost ${cost_basis:.2f}, {stop_rule})")
    elif current <= trail_stop:
        state = "below_trailing_level"
        observation = (f"price ${current:.2f} is {abs(vs_trail):.1f} percent below the trailing level of ${trail_stop:.2f} "
                       f"(-{int(trail_pct*100)} percent from the ${peak:.2f} peak, {bracket} bracket); "
                       f"{_pct(vs_hard)} from the rulebook stop of ${hard_stop:.2f} (from cost, {stop_rule})")
    elif fired_trim is not None:
        state = "past_trim_level"
        observation = (f"position is {gain_pct:+.0f} percent on cost; the rulebook's trim level was {fired_trim['at_gain']} "
                       f"({fired_trim['trim_pct']} percent of the position at that level)")
    elif n_red >= 2:
        state = "thesis_flags"
        observation = (f"{n_red} of {len(thesis)} thesis checks read red: "
                       + "; ".join(t["text"] for t in thesis if t["status"] == "red")
                       + f". Price ${current:.2f} is {_pct(vs_hard)} from the rulebook stop of ${hard_stop:.2f} (from cost, {stop_rule})")
    elif hedge and hedge["type"] == "condition_met":
        state = "hedge_condition"
        observation = hedge["text"].rstrip(".") + f"; price ${current:.2f} is {_pct(vs_hard)} from the rulebook stop of ${hard_stop:.2f} (from cost, {stop_rule})"
    elif n_yellow >= 2:
        state = "yellow_flags"
        observation = (f"{n_yellow} of {len(thesis)} thesis checks read yellow; price ${current:.2f} is {_pct(vs_hard)} from the "
                       f"rulebook stop of ${hard_stop:.2f} (from cost ${cost_basis:.2f}, {stop_rule})")
    else:
        state = "within_rules"
        observation = (f"price ${current:.2f} is {_pct(vs_hard)} from the rulebook stop of ${hard_stop:.2f} "
                       f"(from cost ${cost_basis:.2f}, {stop_rule})")
    STATE_LABEL = {"below_stop_from_cost": "BELOW RULEBOOK STOP", "below_trailing_level": "BELOW TRAILING LEVEL",
                   "past_trim_level": "PAST TRIM LEVEL", "thesis_flags": "THESIS CHECKS RED",
                   "hedge_condition": "HEDGE CONDITION MET", "yellow_flags": "YELLOW FLAGS", "within_rules": "WITHIN RULES"}

    parts = [f"{gain_pct:+.0f}% on cost ({bracket} bracket)",
             f"trailing level ${trail_stop:.2f} (-{int(trail_pct*100)}% from the ${peak:.0f} peak)",
             f"rulebook stop from cost ${hard_stop:.2f} ({stop_rule})",
             f"active level = the higher of the two: ${active_stop:.2f} ({active_stop_type})"]
    if next_trim:
        parts.append(f"next trim level {next_trim['at_gain']} at ${next_trim['trigger_price']} ({next_trim['distance']:+.0f}% from here)")
    if hedge:
        parts.append(hedge["text"])
    why = ". ".join(parts) + "."

    base.update({
        "signal": STATE_LABEL[state], "state": state, "observation": observation,
        "position": {
            "shares":         float(shares),
            "cost_basis":     round(float(cost_basis), 2),
            "current_price":  round(current, 2),
            "gain_pct":       round(gain_pct, 1),
            "gain_dollars":   round(gain_dollars, 2),
            "position_value": round(position_value, 2),
            "weight_pct":     round(pos_weight, 1),
            "peak_price":     round(peak, 2),
        },
        "stops": {
            "trail_stop":          trail_stop,
            "trail_pct":           int(trail_pct * 100),
            "trail_bracket":       bracket,
            "trail_distance_pct":  trail_dist,
            "hard_stop":           hard_stop,
            "hard_stop_pct":       int(hard_stop_pct * 100),
            "active_stop":         active_stop,
            "active_stop_type":    active_stop_type,
            "vs_stop_from_cost_pct": round(vs_hard, 1),
            "vs_trailing_pct":     round(vs_trail, 1) if vs_trail is not None else None,
        },
        "trim":   next_trim,
        "trim_passed": fired_trim,
        "hedge":  hedge,
        "thesis": thesis,
        "why":    why,
        "data": {
            "price":      round(current, 2),
            "rsi":        round(rsi, 1),
            "ma200":      round(ma200, 2) if ma200 else None,
            "ma200_dist": round(ma200_dist, 1),
            "ma50":       round(ma50, 2)  if ma50  else None,
            "composite":  round(composite, 1),
            "rank":       rank,
        },
    })
    return base


# ====================================================================
# Entry mode (non-owned) — with extended-stock guard
# ====================================================================
def compute_entry_signal(ticker, scores, prices_df, fund_df, regime, portfolio_value):
    px = prices_df[ticker].dropna()
    if len(px) < 50:
        return None
    current = float(px.iloc[-1])

    row = scores[scores["ticker"] == ticker]
    if row.empty:
        return None
    row = row.iloc[0]
    composite = float(row.get("composite", 0))
    rank      = int(row.get("composite_rank", 999))

    ma200 = float(px.rolling(200).mean().iloc[-1]) if len(px) >= 200 else None
    ma50  = float(px.rolling(50).mean().iloc[-1])  if len(px) >= 50  else None
    rsi   = rsi14(px)
    hi52  = float(px.tail(252).max()) if len(px) >= 252 else float(px.max())
    lo52  = float(px.tail(252).min()) if len(px) >= 252 else float(px.min())
    rng52 = hi52 - lo52
    pct52 = ((current - lo52) / rng52 * 100) if rng52 > 0 else 50.0
    ma200_dist = ((current / ma200) - 1) * 100 if ma200 else 0.0
    ma50_dist  = ((current / ma50)  - 1) * 100 if ma50  else 0.0
    rvol  = float(px.pct_change().tail(20).std() * np.sqrt(252) * 100)

    fund = fund_df.loc[ticker].to_dict() if ticker in fund_df.index else {}
    fwd_pe     = fund_num(fund, "forwardPE")
    trail_pe   = fund_num(fund, "trailingPE")
    rev_growth = fund_num(fund, "revenueGrowth")
    gm         = fund_num(fund, "grossMargins")
    roe        = fund_num(fund, "returnOnEquity")
    fcf        = fund_num(fund, "freeCashflow")
    de         = fund_num(fund, "debtToEquity")
    beta       = fund_num(fund, "beta")
    sector     = fund.get("sector", "") or ""

    category   = classify_category(fund)
    stop_pct   = STOP_PCT_BY_CATEGORY.get(category, 0.15)

    R_full       = float(regime.get("R_full", 0.3))
    regime_lbl   = regime.get("regime", "LOW RISK")
    regime_mult  = regime_multiplier(R_full)

    # ---- Branch on technical posture ----
    extended = bool(ma200 and ma200_dist > 15)
    forced_signal = None

    if extended:
        # Wait for a pullback to MA50 or midpoint to MA200; no fantasy entry
        if ma50 and ma50 < current:
            pullback = ma50;            pullback_basis = "MA50"
        else:
            pullback = (current + ma200) / 2; pullback_basis = "midpoint to MA200"
        pullback_pct = round((pullback / current - 1) * 100, 1)
        entry_primary = round(float(pullback), 2)
        entry_secondary = round(entry_primary * 0.95, 2)
        entry_basis = f"WAIT — pullback to ${entry_primary} ({pullback_basis}, {pullback_pct:+.1f}%)"
        stop_price = round(entry_primary * (1 - stop_pct), 2)
        risk_per_share = max(0.0, entry_primary - stop_price)
        # Targets framed around CURRENT price, not the fantasy entry
        target_conservative = round(current * 0.98, 2)
        target_base         = round(current * 1.05, 2)
        target_aggressive   = round(hi52 * 1.10, 2)
        if rsi > 70:
            forced_signal = ("WAIT — OVERBOUGHT", 20)
        else:
            forced_signal = ("WATCH — EXTENDED", 35)
    elif ma200 and current <= ma200 * 1.02:
        # At/below MA200 — ideal entry
        entry_primary = round(current * 0.99, 2)
        entry_secondary = round(current * 0.95, 2)
        entry_basis = "at 200-DMA support"
        stop_price = round(entry_primary * (1 - stop_pct), 2)
        risk_per_share = max(0.0, entry_primary - stop_price)
        target_base = round(float(find_resistance(px, current)), 2)
        target_conservative = round(entry_primary + risk_per_share * 1.5, 2)
        target_aggressive   = round(hi52, 2)
    elif ma200 and 5 < ma200_dist <= 15:
        # Moderately above MA200 — pullback to nearest support / MA200
        support = find_support(px, current)
        entry_primary = round(float(max(support, ma200)), 2)
        entry_secondary = round(entry_primary * 0.95, 2)
        entry_basis = "pullback to support / 200-DMA"
        stop_price = round(entry_primary * (1 - stop_pct), 2)
        risk_per_share = max(0.0, entry_primary - stop_price)
        target_base = round(float(find_resistance(px, current)), 2)
        target_conservative = round(entry_primary + risk_per_share * 1.5, 2)
        target_aggressive   = round(hi52, 2)
    else:
        # No MA200 / fallback
        entry_primary = round(current * 0.97, 2)
        entry_secondary = round(current * 0.93, 2)
        entry_basis = "3% discount to current"
        stop_price = round(entry_primary * (1 - stop_pct), 2)
        risk_per_share = max(0.0, entry_primary - stop_price)
        target_base = round(current * 1.20, 2)
        target_conservative = round(entry_primary + risk_per_share * 1.5, 2)
        target_aggressive   = round(hi52, 2) if hi52 else round(current * 1.30, 2)

    reward_risk = round((target_base - entry_primary) / risk_per_share, 1) if risk_per_share > 0 else 0.0

    # ---- Size ----
    if portfolio_value <= 0 or risk_per_share <= 0 or entry_primary <= 0:
        target_shares = 0
    else:
        shares_by_risk = int((portfolio_value * RISK_BUDGET_PCT) / risk_per_share)
        shares_by_cap  = int((portfolio_value * MAX_POSITION_PCT) / entry_primary)
        target_shares  = max(1, min(shares_by_risk, shares_by_cap))
    target_shares = max(0, int(target_shares * regime_mult))
    dollar_size = round(target_shares * entry_primary, 2)
    max_loss    = round(target_shares * risk_per_share, 2)

    # ---- Signal ----
    if forced_signal is not None:
        signal, strength = forced_signal
        # Conditions still computed for the dropdown
        buy_cond = {
            "score_above_35":     composite >= 35,
            "rsi_not_overbought": rsi < 55,
            "near_support":       False,                  # by definition, extended ≠ near support
            "regime_permits":     R_full < 0.50,
            "not_overextended":   False,                  # extended is the override
        }
        strong_cond = {
            "score_top_20pct": composite >= 38,
            "rsi_oversold":    rsi < 40,
            "at_ma200":        False,
            "regime_low_risk": R_full < 0.30,
        }
        sell_cond = {
            "score_collapsed":         composite < 20,
            "rsi_extreme_overbought":  rsi > 80,
            "far_above_ma200":         ma200_dist > 40,
        }
    else:
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
        if R_full >= 0.70 and signal in ("BUY", "STRONG BUY"):
            signal, strength = "HOLD — REGIME CRISIS", 20

    # ---- WHY ----
    why = [f"Ranked #{rank} in universe ({composite:.1f}/50)"]
    if extended:
        why.append(f"{ma200_dist:.0f}% above 200-DMA — extended; wait for pullback to ${entry_primary}")
    else:
        if   rsi < 30: why.append(f"deeply oversold (RSI {rsi:.0f})")
        elif rsi < 40: why.append(f"oversold (RSI {rsi:.0f})")
        elif rsi > 70: why.append(f"overbought (RSI {rsi:.0f})")
        if ma200:
            if   abs(ma200_dist) < 3: why.append("right at 200-DMA support")
            elif ma200_dist < -5:     why.append(f"{abs(ma200_dist):.0f}% below 200-DMA")
    if fwd_pe is not None:
        if   fwd_pe < 15: why.append(f"forward P/E {fwd_pe:.1f}")
        elif fwd_pe > 50: why.append(f"expensive at {fwd_pe:.0f}× forward earnings")
    if gm and gm > 0.70:        why.append(f"{gm*100:.0f}% gross margins")
    if rev_growth and rev_growth > 0.20:   why.append(f"{rev_growth*100:.0f}% revenue growth")
    elif rev_growth and rev_growth < -0.05: why.append(f"revenue declining {rev_growth*100:.0f}%")
    dd_high = ((current / hi52) - 1) * 100
    if dd_high < -20: why.append(f"{abs(dd_high):.0f}% off 52-week high")
    why.append(f"regime: {regime_lbl} ({regime_mult:.0%} sizing)")
    why_text = ". ".join(why) + "."

    # ---- RISKS ----
    risks = []
    if trail_pe and fwd_pe and trail_pe > fwd_pe * 2.5:
        risks.append("Trailing P/E much higher than forward — consensus expects an earnings jump that may not materialize")
    if sector in ("Energy", "Basic Materials"):
        risks.append("Commodity-linked revenue, cyclical risk")
    if de and de > 150:     risks.append(f"High leverage (D/E {de:.0f})")
    if beta and beta > 1.5: risks.append(f"High market sensitivity (beta {beta:.1f})")
    if dd_high < -30:       risks.append(f"Deep drawdown ({dd_high:.0f}%) — momentum breakdown could continue")
    if rvol > 50:           risks.append(f"High volatility ({rvol:.0f}% annualized)")
    if fcf is not None and fcf < 0: risks.append("Negative free cash flow")
    if not risks:           risks.append("No major risk flags identified")
    risk_text = ". ".join(risks) + "."

    # Entry mode: discount setup strength when price has run above entry
    tn_strength = trade_now_strength(int(strength), current, entry_primary, signal)
    tn_note     = trade_now_note(current, entry_primary, signal)
    return {
        "ticker":          ticker,
        "mode":            "entry",
        "signal":          signal,
        "signal_strength": int(strength),
        "trade_now_strength": tn_strength,
        "trade_now_note":  tn_note,
        "category":        category,
        "extended":        extended,
        "entry":           {"primary": entry_primary, "secondary": entry_secondary, "basis": entry_basis},
        "stop":            {"price": stop_price, "pct": int(stop_pct * 100),
                            "category_rule": f"-{stop_pct*100:.0f}% ({category})"},
        "target":          {"conservative": target_conservative, "base": target_base,
                            "aggressive": target_aggressive, "reward_risk": reward_risk},
        "size":            {"shares": target_shares, "dollars": dollar_size,
                            "pct_portfolio": round(dollar_size / portfolio_value * 100, 1) if portfolio_value > 0 else 0,
                            "max_loss": max_loss, "regime_mult": regime_mult},
        "why":             why_text,
        "risks":           risk_text,
        "conditions":      {"buy": buy_cond, "strong_buy": strong_cond, "sell": sell_cond},
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
        },
    }


# ====================================================================
# Router
# ====================================================================
def compute_signal(ticker, scores, prices_df, fund_df, regime,
                   portfolio_holdings, portfolio_value):
    holding = portfolio_holdings.get(ticker, {})
    shares  = float(holding.get("shares", 0) or 0)
    cost    = float(holding.get("cost",   0) or 0)
    if shares > 0 and cost > 0 and ticker in prices_df.columns:
        return compute_position_signal(ticker, shares, cost, scores, prices_df,
                                        fund_df, regime, portfolio_value)
    sig = compute_entry_signal(ticker, scores, prices_df, fund_df, regime, portfolio_value)
    if sig is not None:
        sig["label"] = LABEL           # 1.7: the label rides on every signal record
    return sig


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


def _sanitize(o):
    if isinstance(o, dict):  return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, list):  return [_sanitize(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    return o


def estimate_portfolio_value() -> float:
    try:
        hj = json.load(open(DATA / "holdings.json"))          # the only holdings source
        cash = float(hj.get("cash", 0) or 0)
        prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
        equity = 0.0
        for h in hj.get("holdings", []):
            tk = h["ticker"]; sh = float(h.get("shares", 0) or 0)
            if sh <= 0: continue
            sym = tk if tk in prices.columns else tk.replace("-", ".")
            if sym in prices.columns:
                px = prices[sym].dropna()
                if not px.empty:
                    equity += sh * float(px.iloc[-1])
        return round(equity + cash, 2)
    except Exception as e:
        print(f"  warn portfolio_value fallback: {e}")
        return 176000.0


def main():
    from trading_calendar import require_trading_day  # SEPT AUDIT [2.4]
    require_trading_day("compute_signals")
    print("Loading data...")
    prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in prices.columns: prices = prices.drop(columns=["SPY_volume"])
    prices.index = pd.to_datetime(prices.index)
    fund = pd.read_parquet(SOURCE / "fundamentals_snapshot.parquet")
    scores = pd.read_csv(DATA / "scored_universe.csv")

    try:
        rdf = pd.read_csv(DATA / "regime_v2_daily.csv", parse_dates=["date"], index_col="date")
        last = rdf.dropna(subset=["R_full"]).iloc[-1]
        regime = {"R_full": float(last["R_full"]), "regime": str(last.get("regime", "LOW RISK"))}
    except Exception:
        regime = {"R_full": 0.3, "regime": "LOW RISK"}
    print(f"  regime: R_full={regime['R_full']:.3f} ({regime['regime']})")

    cfg = json.load(open(REPO / "config.json"))
    # P3.1 (dashboard order 9-Sept): data/holdings.json is the only holdings source
    _hj = json.load(open(DATA / "holdings.json"))
    holdings = {h["ticker"]: {"shares": h.get("shares", 0), "cost": h.get("cost_basis")} for h in _hj.get("holdings", [])}
    pv = estimate_portfolio_value()
    print(f"  portfolio value: ${pv:,.0f}")
    print(f"  Werner holdings: {[k for k, h in holdings.items() if float(h.get('shares', 0) or 0) > 0]}")

    tickers = set()
    try:
        th = json.load(open(DATA / "tier_holdings.json"))
        for _, lst in th.get("tiers", {}).items(): tickers.update(lst)
    except Exception: pass
    tickers.update(holdings.keys())
    if len(scores) > 0:
        tickers.update(scores.nlargest(50, "composite")["ticker"].tolist())
    print(f"  computing signals for {len(tickers)} tickers")

    signals = {}
    for tk in sorted(tickers):
        sym = tk if tk in prices.columns else tk.replace(".", "-")
        if sym not in prices.columns:
            if tk in holdings:            # 1.2: a held name outside every price source is displayed, not omitted
                h = holdings[tk]
                signals[tk] = {"ticker": tk, "mode": "position", "label": LABEL, "signal": "no price history",
                               "state": "no_price_history", "observation": "no price source carries this name; excluded from analytics",
                               "cost_basis": h.get("cost"), "stop_from_cost": None, "signal_strength": None,
                               "trade_now_strength": None, "trade_now_note": None,
                               "position": {"shares": float(h.get("shares") or 0), "cost_basis": h.get("cost")}}
            continue
        sig = compute_signal(sym, scores, prices, fund, regime, holdings, pv)
        if sig is None:
            continue
        # Add composite percentile against the FULL scored universe (not just
        # the 58 signals computed today). This drives the dashboard's "top X%"
        # subtitle on the Business Quality bar.
        n_universe = len(scores) if len(scores) > 0 else 1
        rank = sig.get("data", {}).get("rank")
        if rank and rank > 0:
            sig.setdefault("data", {})["composite_pct"] = round(100 * (1 - (rank - 1) / n_universe), 1)
        signals[tk] = sig
        mode = sig["mode"]
        if mode == "position":
            p = sig.get("position", {}); s = sig.get("stops", {})
            print(f"    {tk:8s} [POS] {sig['signal']:26s}  {(p.get('gain_pct') if p.get('gain_pct') is not None else 0):>+6.1f}%  "
                  f"price ${(p.get('current_price') or 0):>8.2f}  stop-from-cost ${(sig.get('stop_from_cost') or 0):>8.2f}  "
                  f"weight {(p.get('weight_pct') or 0):>5.1f}%  · {sig.get('observation','')[:90]}")
        else:
            sz = sig["size"]
            print(f"    {tk:8s} [ENT] {sig['signal']:30s}  entry ${sig['entry']['primary']:>7.2f}  "
                  f"stop ${sig['stop']['price']:>7.2f}  target ${sig['target']['base']:>7.2f}  "
                  f"size ${sz['dollars']:>7.0f}")

    from trading_calendar import last_completed_session
    payload = _sanitize({"cadence": "daily", "session_date": last_completed_session(),   # declared date (self-stamped)
                          "prices_through": str(prices.index[-1].date()),
                          "updated": pd.Timestamp.now().isoformat(),
                          "label": LABEL,
                          "portfolio_value": pv, "regime": regime,
                          "n": len(signals), "signals": signals})
    out = DATA / "ticker_signals.json"
    with open(out, "w") as f:
        json.dump(payload, f, separators=(",", ":"), cls=_NpEnc, allow_nan=False)

    dist = {}
    for s in signals.values():
        m = s["mode"]
        base = s.get("state") or (s["signal"].split("—")[0].strip() if "—" in s["signal"] else s["signal"].split(" at ")[0])
        key = f"[{m[:3].upper()}] {base}"
        dist[key] = dist.get(key, 0) + 1
    print(f"\nSignal distribution:")
    for k, n in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {k:35s} {n}")
    print(f"\nSaved {out}  ({len(signals)} tickers)")


if __name__ == "__main__":
    main()
