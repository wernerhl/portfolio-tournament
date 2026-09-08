"""
compute_factor_exposure.py — order item 3.3: style-factor exposure.

Per name, an OLS regression of daily simple returns on four factor proxies
over the last 252 sessions:
    market   = r(SPY)
    size     = r(IWM) − r(SPY)
    value    = r(IWD) − r(IWF)
    momentum = r(MTUM) − r(SPY)
Portfolio exposure = weight-averaged beta per factor. Weights are equity
weights (position value / total equity value, cash excluded), renormalised
over the names that have betas; the covered share is reported and the
names without betas are listed. Portfolios: the book (Werner's holdings)
and every tier from the last row of tournament.json.

A portfolio-level regression on live tournament history (~70 sessions)
would be vacuous and is NOT used — the per-name regressions have the
observations.

History rule (order 3.3, pre-answered question): a name with fewer than
252 usable sessions regresses on what exists if it has at least 120
(status "partial_history"); below 120 it gets status "insufficient_history"
and no betas. n_obs, the sessions actually used, and the first available
price date are reported so a short listing can be told from a gappy series.

Sector: the thesis registry has no sector field, so sector comes from the
first of data/ticker_indicators.json, data/source/fundamentals_snapshot.parquet,
data/scored_universe.csv that carries one (source named per name; null if none).

Inputs   data/source/prices_daily.parquet    daily adjusted closes, columns = tickers
         data/source/sector_etfs.parquet     proxies: spy, iwm, iwd, iwf, mtum
         data/holdings.json | config.json    the book (shares)
         data/tournament.json                tiers, last row
Output   data/factor_exposure.json           daily; label "estimated, 252-session regression"

Usage:   python scripts/compute_factor_exposure.py [--allow-non-trading]
"""
from __future__ import annotations
import json, sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"
OUT    = DATA / "factor_exposure.json"

WINDOW  = 252     # sessions
MIN_OBS = 120     # below this: "insufficient_history", no betas
FACTORS = ("market", "size", "value", "momentum")
PROXIES = {"market": "SPY", "size": "IWM − SPY", "value": "IWD − IWF", "momentum": "MTUM − SPY"}
PROXY_COLS = ("spy", "iwm", "iwd", "iwf", "mtum")   # lowercase columns of sector_etfs.parquet
LABEL  = "estimated, 252-session regression"
METHOD = ("per-name OLS, 252 sessions, daily simple returns; factors: market SPY, size IWM−SPY, "
          "value IWD−IWF, momentum MTUM−SPY; portfolio exposure = weight-averaged beta "
          "(equity weights, names with betas only)")
STATUS_OK, STATUS_PARTIAL, STATUS_INSUFFICIENT = "ok", "partial_history", "insufficient_history"


def log(msg: str) -> None:
    print(f"[compute_factor_exposure] {msg}", flush=True)


# ── inputs ──────────────────────────────────────────────────────────────
def load_prices() -> pd.DataFrame:
    px = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in px.columns:
        px = px.drop(columns=["SPY_volume"])
    px.index = pd.to_datetime(px.index)
    return px.sort_index()


def load_proxies() -> pd.DataFrame:
    se = pd.read_parquet(SOURCE / "sector_etfs.parquet")
    se.index = pd.to_datetime(se.index)
    missing = [c for c in PROXY_COLS if c not in se.columns]
    if missing:
        sys.exit(f"[compute_factor_exposure] sector_etfs.parquet lacks proxy columns {missing} "
                 f"— refresh_data.py downloads IWD/IWF/MTUM into it")
    return se[list(PROXY_COLS)].sort_index()


def factor_returns(proxies: pd.DataFrame) -> pd.DataFrame:
    r = proxies.pct_change(fill_method=None)     # simple daily returns; NaN across a gap, never filled
    return pd.DataFrame({
        "market":   r["spy"],
        "size":     r["iwm"]  - r["spy"],
        "value":    r["iwd"]  - r["iwf"],
        "momentum": r["mtum"] - r["spy"],
    })


def book_shares() -> tuple[dict[str, float], str]:
    """The book: data/holdings.json if present (order 3.1 schema — "holdings" is a
    list of {"ticker", "shares", ...} records; a {TK: {"shares"}} / {TK: shares}
    mapping is also accepted), else config.json → werner_picks → holdings."""
    hp = DATA / "holdings.json"
    if hp.exists():
        h = json.load(open(hp))
        h = h.get("holdings", h) if isinstance(h, dict) else h
        shares: dict[str, float] = {}
        if isinstance(h, list):
            for e in h:
                if isinstance(e, dict) and e.get("ticker") is not None:
                    tk = str(e["ticker"]).upper()
                    shares[tk] = shares.get(tk, 0.0) + float(e.get("shares", 0) or 0)
        elif isinstance(h, dict):
            shares = {tk: float(v["shares"] if isinstance(v, dict) else v) for tk, v in h.items()}
        if not shares:
            sys.exit("[compute_factor_exposure] data/holdings.json has no holdings records")
        return shares, "data/holdings.json"
    cfg = json.load(open(REPO / "config.json"))
    shares = {tk: float(v["shares"]) for tk, v in cfg["werner_picks"]["holdings"].items()}
    return shares, "config.json:werner_picks.holdings"


def tier_positions() -> tuple[dict[str, dict[str, float]], str]:
    """{tier_id: {ticker: position value}} from the last row of tournament.json."""
    t = json.load(open(DATA / "tournament.json"))
    last = t["history"][-1]
    tiers = {}
    for tid, tv in last["tiers"].items():
        vals: dict[str, float] = {}
        for p in tv.get("positions", []):
            vals[p["ticker"]] = vals.get(p["ticker"], 0.0) + float(p["value"])
        tiers[tid] = vals
    return tiers, str(last["date"])


def sector_lookup(universe: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """First non-null sector per ticker from, in order: ticker_indicators.json,
    fundamentals_snapshot.parquet, scored_universe.csv."""
    sources: list[tuple[str, dict]] = []
    p = DATA / "ticker_indicators.json"
    if p.exists():
        ti = json.load(open(p))
        sources.append(("ticker_indicators.json",
                        {tk: v.get("sector") for tk, v in ti.items() if isinstance(v, dict)}))
    p = SOURCE / "fundamentals_snapshot.parquet"
    if p.exists():
        fs = pd.read_parquet(p)
        if "sector" in fs.columns:
            sources.append(("fundamentals_snapshot.parquet", fs["sector"].to_dict()))
    p = DATA / "scored_universe.csv"
    if p.exists():
        su = pd.read_csv(p)
        if {"ticker", "sector"} <= set(su.columns):
            sources.append(("scored_universe.csv", su.set_index("ticker")["sector"].to_dict()))
    out = {}
    for tk in universe:
        found = (None, None)
        for name, mp in sources:
            v = mp.get(tk)
            if isinstance(v, str) and v.strip():
                found = (v.strip(), name)
                break
        out[tk] = found
    return out


# ── regression ──────────────────────────────────────────────────────────
def ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, float]:
    """OLS of y on [1, X]; returns (coef[intercept, betas...], r2)."""
    A = np.column_stack([np.ones(len(y)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ coef
    sst = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / sst if sst > 0 else float("nan")
    return coef, r2


def regress_name(r: pd.Series, F: pd.DataFrame) -> dict:
    """r: the name's daily returns on the window index; F: factor returns on the same index."""
    valid = r.notna() & F.notna().all(axis=1)
    n = int(valid.sum())
    rec = {"n_obs": n, "window_sessions": int(len(F))}
    if n < MIN_OBS:
        rec.update({"status": STATUS_INSUFFICIENT, "betas": None, "intercept": None,
                    "intercept_bps_daily": None, "r2": None, "window_start": None, "window_end": None})
        return rec
    idx = F.index[valid.to_numpy()]
    coef, r2 = ols(r.loc[idx].to_numpy(dtype=float), F.loc[idx, list(FACTORS)].to_numpy(dtype=float))
    rec.update({
        "status": STATUS_OK if n >= WINDOW else STATUS_PARTIAL,
        "betas": {f: float(coef[i + 1]) for i, f in enumerate(FACTORS)},
        "intercept": float(coef[0]),
        "intercept_bps_daily": float(coef[0]) * 1e4,
        "r2": r2,
        "window_start": str(idx[0].date()),
        "window_end": str(idx[-1].date()),
    })
    return rec


# ── portfolio aggregation ───────────────────────────────────────────────
def portfolio_exposure(values: dict[str, float], names: dict[str, dict]) -> dict:
    """Weight-averaged betas. Weights = value / total equity value (cash excluded);
    renormalised over names with betas; covered share and excluded names reported."""
    total = float(sum(values.values()))
    if total <= 0 or not values:
        return {"exposure": {f: None for f in FACTORS}, "covered_weight": 0.0, "excluded": sorted(values),
                "n_names": len(values), "n_covered": 0, "equity_value": total, "weights": {}}
    w = {tk: v / total for tk, v in values.items()}
    covered = {tk: wt for tk, wt in w.items() if names.get(tk, {}).get("betas")}
    cw = float(sum(covered.values()))
    exposure = ({f: sum(wt / cw * names[tk]["betas"][f] for tk, wt in covered.items()) for f in FACTORS}
                if cw > 0 else {f: None for f in FACTORS})
    return {
        "exposure": exposure,
        "covered_weight": cw,
        "excluded": sorted(tk for tk in w if tk not in covered),
        "n_names": len(w),
        "n_covered": len(covered),
        "equity_value": total,
        "weights": dict(sorted(w.items(), key=lambda kv: -kv[1])),
    }


# ── output hygiene ──────────────────────────────────────────────────────
def _clean(o, nd: int = 4):
    """numpy → python, NaN/inf → None, floats rounded to nd decimals."""
    if isinstance(o, dict):
        return {k: _clean(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v, nd) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return None if not np.isfinite(f) else round(f, nd)
    return o


# ── main ────────────────────────────────────────────────────────────────
def main() -> int:
    from trading_calendar import last_completed_session, require_trading_day, now_et
    require_trading_day("compute_factor_exposure")          # --allow-non-trading bypasses (manual runs)
    session = last_completed_session()

    px = load_prices()
    F_all = factor_returns(load_proxies())
    common = px.index.intersection(F_all.index)
    if len(common) < MIN_OBS:
        sys.exit(f"[compute_factor_exposure] only {len(common)} common sessions between prices and proxies")
    window_idx = common[-WINDOW:]
    F = F_all.loc[window_idx]
    window_end = str(window_idx[-1].date())
    if window_end != session:
        log(f"WARNING: price data ends {window_end} but the last completed session is {session}")

    # universe = book ∪ every position in the last tournament row
    shares, book_source = book_shares()
    tiers, tourn_date = tier_positions()
    universe = sorted(set(shares) | {tk for vals in tiers.values() for tk in vals})
    log(f"session {session} · window {window_idx[0].date()}→{window_end} · {len(universe)} names · book from {book_source}")

    # per-name regressions
    sectors = sector_lookup(universe)
    names: dict[str, dict] = {}
    for tk in universe:
        sector, sector_src = sectors[tk]
        rec = {"ticker": tk, "sector": sector, "sector_source": sector_src}
        if tk not in px.columns:
            rec.update({"status": STATUS_INSUFFICIENT, "reason": "not in prices_daily", "n_obs": 0,
                        "window_sessions": int(len(F)), "betas": None, "intercept": None,
                        "intercept_bps_daily": None, "r2": None, "window_start": None, "window_end": None})
        else:
            r = px[tk].pct_change(fill_method=None).reindex(window_idx)
            rec.update(regress_name(r, F))
            fv = px[tk].first_valid_index()
            rec["history_start"] = str(fv.date()) if fv is not None else None
            missing = int(len(F)) - rec["n_obs"]
            if missing:
                rec["missing_sessions"] = missing
        rec["in_portfolios"] = ([ "book" ] if tk in shares else []) + [tid for tid, vals in tiers.items() if tk in vals]
        names[tk] = rec

    # portfolios: book (shares × latest price) + each tier (position values)
    latest = {tk: px[tk].dropna() for tk in shares if tk in px.columns}
    book_values = {tk: shares[tk] * float(s.iloc[-1]) for tk, s in latest.items() if len(s)}
    book_missing = sorted(set(shares) - set(book_values))
    portfolios = {"book": portfolio_exposure(book_values, names)}
    portfolios["book"].update({
        "source": book_source,
        "priced_at": {tk: str(s.index[-1].date()) for tk, s in latest.items() if len(s)},
        "unpriced": book_missing,
    })
    for tid, vals in tiers.items():
        portfolios[tid] = portfolio_exposure(vals, names)
        portfolios[tid]["source"] = f"tournament.json:history[-1] ({tourn_date})"

    # self-checks: SPY on the factors must be the identity; NVDA market beta above 1
    spy_rec = regress_name(F["market"], F)
    spy_b = spy_rec["betas"] or {}
    spy_pass = bool(spy_b) and abs(spy_b["market"] - 1) < 1e-8 and all(abs(spy_b[f]) < 1e-8 for f in FACTORS[1:])
    nvda_b = (names.get("NVDA") or {}).get("betas")
    checks = {
        "spy_self_regression": {"betas": spy_b, "intercept": spy_rec.get("intercept"), "r2": spy_rec.get("r2"),
                                "n_obs": spy_rec["n_obs"], "pass": spy_pass},
        "nvda_market_beta_gt_1": (nvda_b["market"] > 1) if nvda_b else None,
    }

    statuses = {s: sum(1 for v in names.values() if v["status"] == s)
                for s in (STATUS_OK, STATUS_PARTIAL, STATUS_INSUFFICIENT)}
    payload = {
        "cadence": "daily",
        "session_date": session,
        "as_of": window_end,
        "computed_at": now_et().isoformat(timespec="seconds"),
        "method": METHOD,
        "label": LABEL,
        "window_sessions": WINDOW,
        "min_obs": MIN_OBS,
        "proxies": PROXIES,
        "proxy_source": "data/source/sector_etfs.parquet (yfinance adjusted close: spy, iwm, iwd, iwf, mtum)",
        "note": ("Per-name regressions only; no portfolio-level regression on live tournament history "
                 "(too few sessions). Sector is not in the thesis registry (no sector field there); it is "
                 "taken per name from the first of ticker_indicators.json, fundamentals_snapshot.parquet, "
                 "scored_universe.csv that has one (sector_source), null if none. "
                 f"A name with {MIN_OBS} ≤ n_obs < {WINDOW} is 'partial_history' (regressed on what exists); "
                 f"n_obs < {MIN_OBS} is 'insufficient_history' (no betas, excluded from portfolio averages)."),
        "universe": universe,
        "status_counts": statuses,
        "names": names,
        "portfolios": portfolios,
        "checks": checks,
    }
    with open(OUT, "w") as f:
        json.dump(_clean(payload), f, indent=2, allow_nan=False)

    # console summary
    log(f"names: {statuses}")
    for tk, rec in names.items():
        if rec["status"] != STATUS_OK:
            log(f"  {tk}: {rec['status']} (n_obs {rec['n_obs']}, history from {rec.get('history_start')})")
    for pid, p in portfolios.items():
        e = p["exposure"]
        fmt = lambda f: "  n/a " if e[f] is None else f"{e[f]:+.3f}"
        log(f"  {pid:<13} mkt {fmt('market')}  size {fmt('size')}  value {fmt('value')}  mom {fmt('momentum')}"
            f"  covered {p['covered_weight']:.3f} of {p['n_names']} names" + (f"  excluded {p['excluded']}" if p["excluded"] else ""))
    log(f"checks: spy identity {'PASS' if spy_pass else 'FAIL'} {_clean(spy_b)} · "
        f"NVDA market beta {nvda_b['market']:.3f} {'>1 PASS' if checks['nvda_market_beta_gt_1'] else 'NOT >1'}"
        if nvda_b else f"checks: spy identity {'PASS' if spy_pass else 'FAIL'} · NVDA not in universe")
    log(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
