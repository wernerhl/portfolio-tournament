"""book_analytics.py — shared book arithmetic (order 16-Sept-2026, Phase 1).

Pure functions over the price store; no I/O except the loaders. Used by
compute_book.py (1.3 book analytics, 1.5 stress, 1.6 sleeves) and by
compute_comparators.py (1.4 rule postures translated to the book's beta).

Definitions (pre-answered questions, §7 of the order):
  window          126 sessions of daily simple returns (pct_change, no padding)
  beta            ordinary least squares slope with intercept, 126 sessions,
                  pairwise-complete observations, minimum 60
  volatility      sample standard deviation (ddof=1) of daily returns × √252
  risk share      w_i (Σw)_i / wᵀΣw with w over NAV and cash at zero volatility;
                  the shares sum to 100 percent across the equity positions
  effective bets  exponential entropy of the eigenvalues of the equity
                  correlation matrix: exp(−Σ p_i ln p_i), p_i = λ_i / Σλ
  effective theses 1 / Σ w² over the registry exposure vector of the invested
                  sleeve (the same n_eff as compute_thesis_daily.py)
  book series     constant current equity weights applied to daily returns
                  (a snapshot of today's book carried back over the window)
"""
from __future__ import annotations
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
SOURCE = DATA / "source"

WINDOW = 126
MIN_OBS = 60
ANN = 252.0


# ── loaders ─────────────────────────────────────────────────────────────
def load_holdings(path: Path | None = None) -> dict:
    p = path or (DATA / "holdings.json")
    if not p.exists():
        raise SystemExit("holdings_source_missing: data/holdings.json is the only holdings source")
    h = json.load(open(p))
    if not isinstance(h.get("holdings"), list) or "cash" not in h:
        raise SystemExit("holdings.json: expected {cash, holdings: [{ticker, shares, cost_basis}]}")
    return h


def load_prices() -> pd.DataFrame:
    px = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in px.columns:
        px = px.drop(columns=["SPY_volume"])
    px.index = pd.to_datetime(px.index)
    return px.sort_index()


def load_etfs() -> pd.DataFrame:
    """Sector / index ETFs (lowercase columns) plus TLT from the vol store,
    upper-cased to ticker names."""
    se = pd.read_parquet(SOURCE / "sector_etfs.parquet")
    se.index = pd.to_datetime(se.index)
    out = se.copy()
    out.columns = [c.upper() for c in out.columns]
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet")
    vol.index = pd.to_datetime(vol.index)
    for src, dst in (("tlt", "TLT"), ("gold", "GOLD_FUT")):
        if src in vol.columns and dst not in out.columns:
            out[dst] = vol[src].reindex(out.index)
    return out.sort_index()


def member_weight(v) -> float:
    """Registry member value: a float, or {"weight": w, "sub": ...} (registry v4)."""
    if isinstance(v, dict):
        return float(v.get("weight", 0.0))
    return float(v)


def member_sub(v) -> str | None:
    return v.get("sub") if isinstance(v, dict) else None


# ── returns and windows ─────────────────────────────────────────────────
def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None)


def window_returns(rets: pd.DataFrame, cols: list[str], through: pd.Timestamp | None = None,
                   window: int = WINDOW) -> pd.DataFrame:
    """Last `window` sessions of returns (through `through`, inclusive) for `cols`."""
    r = rets[[c for c in cols if c in rets.columns]]
    if through is not None:
        r = r.loc[:through]
    return r.iloc[-window:]


def ann_vol(r: pd.Series, min_obs: int | None = None) -> float | None:
    """Annualised sample volatility; needs min_obs non-missing returns (default
    MIN_OBS; a 60-session rule window passes 48 = 80 percent of the window)."""
    r = r.dropna()
    if len(r) < (MIN_OBS if min_obs is None else min_obs):
        return None
    return float(r.std(ddof=1) * math.sqrt(ANN))


def ols_beta(y: pd.Series, x: pd.Series) -> dict:
    """Slope of y on x with intercept; pairwise-complete; n reported."""
    d = pd.concat([y, x], axis=1).dropna()
    n = int(len(d))
    if n < MIN_OBS:
        return {"beta": None, "alpha_daily": None, "r2": None, "n_obs": n}
    yy = d.iloc[:, 0].to_numpy(dtype=float); xx = d.iloc[:, 1].to_numpy(dtype=float)
    vx = xx.var(ddof=1)
    if vx <= 0:
        return {"beta": None, "alpha_daily": None, "r2": None, "n_obs": n}
    beta = float(np.cov(yy, xx, ddof=1)[0, 1] / vx)
    alpha = float(yy.mean() - beta * xx.mean())
    resid = yy - (alpha + beta * xx)
    sst = float(((yy - yy.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / sst if sst > 0 else None
    return {"beta": beta, "alpha_daily": alpha, "r2": r2, "n_obs": n}


def corr(a: pd.Series, b: pd.Series) -> dict:
    d = pd.concat([a, b], axis=1).dropna()
    n = int(len(d))
    if n < MIN_OBS:
        return {"corr": None, "n_obs": n}
    c = float(d.iloc[:, 0].corr(d.iloc[:, 1]))
    return {"corr": None if math.isnan(c) else c, "n_obs": n}


def book_series(rets: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Constant-weight daily return of the equity sleeve (weights over equity,
    renormalised over the names priced on each day)."""
    cols = [c for c in weights if c in rets.columns]
    w = pd.Series({c: weights[c] for c in cols}, dtype=float)
    r = rets[cols]
    avail = r.notna()
    wsum = (avail * w).sum(axis=1)
    num = (r.fillna(0.0) * w).sum(axis=1)
    out = num / wsum.replace(0.0, np.nan)
    return out


# ── risk decomposition ──────────────────────────────────────────────────
def risk_contributions(r_win: pd.DataFrame, w_nav: dict[str, float]) -> dict:
    """Marginal contribution to portfolio variance with cash at zero volatility.
    w_nav: equity weights over NAV (they sum to the invested share). Returns
    per-name share of variance (sums to 1 over the names), the portfolio
    variance/vol (daily, annualised) and the covariance basis."""
    cols = [c for c in w_nav if c in r_win.columns]
    r = r_win[cols].dropna(how="any")
    n = int(len(r))
    if n < MIN_OBS or not cols:
        return {"shares": {c: None for c in w_nav}, "n_obs": n, "vol_nav_ann": None}
    S = r.cov(ddof=1).to_numpy()
    w = np.array([w_nav[c] for c in cols], dtype=float)
    Sw = S @ w
    var_p = float(w @ Sw)
    shares = {c: (float(w[i] * Sw[i] / var_p) if var_p > 0 else None) for i, c in enumerate(cols)}
    for c in w_nav:
        shares.setdefault(c, None)
    return {"shares": shares, "n_obs": n, "vol_nav_ann": math.sqrt(var_p * ANN) if var_p > 0 else None,
            "cols": cols}


def effective_bets(r_win: pd.DataFrame, cols: list[str]) -> dict:
    """Exponential entropy of the eigenvalues of the equity correlation matrix."""
    cols = [c for c in cols if c in r_win.columns]
    r = r_win[cols].dropna(how="any")
    n = int(len(r))
    if n < MIN_OBS or len(cols) < 2:
        return {"value": None, "n_obs": n, "n_names": len(cols), "eigenvalues": None}
    C = r.corr().to_numpy()
    lam = np.linalg.eigvalsh(C)
    lam = np.clip(lam, 1e-12, None)
    p = lam / lam.sum()
    H = float(-(p * np.log(p)).sum())
    return {"value": float(math.exp(H)), "n_obs": n, "n_names": len(cols),
            "eigenvalues": [float(x) for x in sorted(lam, reverse=True)]}


def n_eff(weights: dict[str, float]) -> float | None:
    vals = [v for v in weights.values() if v and v > 0]
    s2 = sum(v * v for v in vals)
    return (1.0 / s2) if s2 > 0 else None


def thesis_exposure(values: dict[str, float], registry: dict) -> tuple[dict, dict]:
    """Invested exposure by thesis (membership-weighted; residual → unclassified)
    and per-name membership map {ticker: {thesis: w}}. Same arithmetic as
    compute_thesis_daily.exposure_for_positions."""
    nw: dict[str, dict[str, float]] = {}
    for tid, th in registry["theses"].items():
        for name, v in th["members"].items():
            nw.setdefault(name, {})[tid] = member_weight(v)
    equity = float(sum(values.values()))
    inv: dict[str, float] = {}
    for tk, v in values.items():
        if not v or equity <= 0:
            continue
        share = v / equity
        assigned = 0.0
        for tid, w in nw.get(tk, {}).items():
            inv[tid] = inv.get(tid, 0.0) + share * w
            assigned += w
        resid = max(0.0, 1.0 - assigned)
        if resid > 1e-9:
            inv["unclassified"] = inv.get("unclassified", 0.0) + share * resid
    return inv, nw


# ── technicals ──────────────────────────────────────────────────────────
def rsi14(px: pd.Series) -> float | None:
    """Same construction as compute_signals.rsi14 (simple 14-session means)."""
    px = px.dropna()
    if len(px) < 16:
        return None
    delta = px.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    l = float(loss.iloc[-1]); g = float(gain.iloc[-1])
    if not math.isfinite(l) or not math.isfinite(g):
        return None
    if l == 0:
        return 100.0 if g > 0 else 50.0
    rs = g / l
    return float(100 - 100 / (1 + rs))
