#!/usr/bin/env python3
"""bonds_common.py — shared constants and loaders for the fixed-income module.

Order 16-Sept-2026 (fixed-income module). The module operates at the SLEEVE level
(asset-class ETFs and the yield curve), never at the individual-bond level. It reads
observable data (curve, credit spreads, breakevens, sleeve prices/yields) and the
equity book; it forecasts nothing and emits no buy or sell instruction.

Paths, the sleeve universe, the static effective-duration table (with its source),
the frozen state-band config, and the price/return loaders live here so the fetch,
metrics and state scripts share one definition.
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent.parent
DATA = REPO / "data"
BONDS = DATA / "bonds"
SOURCE = DATA / "source"
SLEEVE_PRICES = SOURCE / "bond_sleeves.parquet"          # source store (never served)
SLEEVE_YIELDS = BONDS / "sleeve_yields.json"             # provider distribution yields + retrieval date

# ── Static effective-duration table (order 1.3: provider first, else a static category
# table with the source noted). yfinance exposes NO duration field for bond ETFs, so the
# module uses this static category table for every sleeve and records the source. ──
DURATION_SOURCE = ("issuer fund fact-sheet category effective duration, approximate, "
                   "as-of 2026-09; yfinance exposes no duration field, so the static "
                   "category table is used for every sleeve")
EFF_DURATION = {
    "SHV": 0.35, "SHY": 1.85, "IEF": 7.3, "TLT": 16.5, "GOVT": 5.9, "TIP": 6.8,
    "VCSH": 2.6, "VCIT": 6.2, "LQD": 8.4, "HYG": 3.2, "JNK": 3.3, "BKLN": 0.2,
    "FLOT": 0.10, "EMB": 7.0, "MUB": 6.3, "MBB": 5.9, "AGG": 6.0, "BND": 5.9,
}
# Spread duration for the credit sleeves (order 4.3 spread shock). Corporate/EM/muni:
# spread duration ≈ effective duration. Floating sleeves carry ~0 rate duration but a
# positive spread duration (BKLN senior loans ~2.5; FLOT small).
SPREAD_DURATION = {
    "VCSH": 2.6, "VCIT": 6.2, "LQD": 8.4, "FLOT": 0.10, "MUB": 6.3,   # IG-rated credit
    "HYG": 3.2, "JNK": 3.3, "BKLN": 2.5, "EMB": 7.0,                  # HY / loan / EM credit
}
# Which credit index prices each sleeve's spread: IG OAS (BAMLC0A0CM) or HY OAS
# (BAMLH0A0HYM2). Treasuries, TIPS, agency MBS and the aggregate carry no credit-spread
# shock (rate shock only).
CREDIT_INDEX = {
    "VCSH": "ig", "VCIT": "ig", "LQD": "ig", "FLOT": "ig", "MUB": "ig",
    "HYG": "hy", "JNK": "hy", "BKLN": "hy", "EMB": "hy",
}
NEAR_ZERO_DURATION = 0.5   # below this, yield-per-duration is unstable (floating / cash)

# ── Order 1-Oct-2026 [R3.2]: weighted-average maturity per sleeve, from the issuer's fund page, with the
# as-of date and source per sleeve (retrieved 2026-10-01). The curve-implied yield reads the curve at this
# maturity. A sleeve without a figure gets curve_implied_yield null with the reason. ──
AVG_MATURITY = {
    # ticker: (years, as_of, source)
    "SHV":  (0.29,  "2026-09-29", "iShares fund page, Weighted Avg Maturity (ishares.com/us/products/239466)"),
    "SHY":  (1.89,  "2026-09-29", "iShares fund page, Weighted Avg Maturity (ishares.com/us/products/239452)"),
    "IEF":  (8.42,  "2026-09-29", "iShares fund page, Weighted Avg Maturity (ishares.com/us/products/239456)"),
    "TLT":  (26.03, "2026-09-29", "iShares fund page, Weighted Avg Maturity (ishares.com/us/products/239454)"),
    "GOVT": (7.37,  "2026-09-29", "iShares fund page, Weighted Avg Maturity (ishares.com/us/products/239468)"),
    "TIP":  (7.00,  "2026-09-29", "iShares fund page, Weighted Avg Maturity (ishares.com/us/products/239467)"),
    "LQD":  (12.62, "2026-09-29", "iShares fund page, Weighted Avg Maturity (ishares.com/us/products/239566)"),
    "HYG":  (4.27,  "2026-09-29", "iShares fund page, Weighted Avg Maturity (ishares.com/us/products/239565)"),
    "VCSH": (3.1,   "2026-08-31", "Vanguard fund characteristics, average maturity (investor.vanguard.com, VCSH)"),
    "VCIT": (7.6,   "2026-08-31", "Vanguard fund characteristics, average maturity (investor.vanguard.com, VCIT)"),
    "JNK":  (5.07,  "2026-09-29", "State Street fund page, Average Maturity in Years (ssga.com, JNK)"),
}
# Which curve prices each sleeve (R3.2). treasury: the CMT curve at the maturity; ig: the CMT curve plus the
# IG OAS of the bucket containing the maturity; hy: the CMT curve plus the HY OAS; real: the TIPS real curve.
CURVE_TYPE = {"SHV": "treasury", "SHY": "treasury", "IEF": "treasury", "TLT": "treasury", "GOVT": "treasury",
              "VCSH": "ig", "VCIT": "ig", "LQD": "ig", "HYG": "hy", "JNK": "hy", "TIP": "real"}
NO_CURVE_REASON = {
    "EMB":  "no public spread series matches the sleeve (USD emerging-market sovereigns); never substituted",
    "MBB":  "no public spread series matches the sleeve (agency MBS, prepayment-sensitive cash flows); never substituted",
    "MUB":  "tax-exempt: compare at the holder's marginal tax rate, and no rate is assumed; no public spread series matches the sleeve; never substituted",
    "BKLN": "floating-rate senior loans: no public spread series matches the sleeve; never substituted",
    "FLOT": "floating-rate notes: the coupon resets with short rates, so no public spread series matches the sleeve; never substituted",
    "AGG":  "a mixed aggregate (Treasuries, MBS, corporates): no single curve or public spread series matches the sleeve; never substituted",
    "BND":  "a mixed aggregate (Treasuries, MBS, corporates): no single curve or public spread series matches the sleeve; never substituted",
}
CARRY_CONFIG = BONDS / "carry_config.json"     # the frozen CMT points, real points and IG maturity buckets
CASH_SERIES = "us03m"                          # DGS3MO: y_cash for the pickup
SIGMA_SERIES, SIGMA_WINDOW = "us10y", 126      # typical daily move of the 10-year, in bp
YPD_DEPRECATION = ("deprecated 2026-10-01 (order R3.3): a trailing distribution yield divided by duration "
                   "favours the shortest sleeve by construction (SHV's duration about 0.35) and lags rate moves; "
                   "the carry basis is the curve-implied yield. Kept for continuity only; read, sorted and shown nowhere.")


def load_carry_config() -> dict:
    return json.loads(CARRY_CONFIG.read_text())


def load_fred_store():
    """(indicators frame, store label, through-date) — the module's one FRED reader. The point-in-time
    store is preferred when it is within a week of the revised store; columns the point-in-time store
    does not carry yet (series added after its last vintage rebuild) come from the revised store, and
    the label says so."""
    rev = pd.read_parquet(SOURCE / "fred_indicators.parquet"); rev.index = pd.to_datetime(rev.index)
    rev = rev.sort_index(); rev_last = rev.index.max()
    try:
        pit = pd.read_parquet(SOURCE / "fred_indicators_pit.parquet"); pit.index = pd.to_datetime(pit.index)
        if (rev_last - pit.index.max()).days <= 7:
            pit = pit.sort_index()
            extra = [c for c in rev.columns if c not in pit.columns]
            if extra:
                idx = pit.index.union(rev.index)
                pit = pit.reindex(idx)
                for c in extra:
                    pit[c] = rev[c].reindex(idx)
            label = "point-in-time (as-published, ALFRED)" + (f"; {len(extra)} newer series from the revised store" if extra else "")
            return pit, label, pit.index.max()
    except Exception:  # noqa: BLE001
        pass
    return rev, "revised (as-published latest; point-in-time overlay rebuilds on the vintage workflow)", rev_last


def _notna(x) -> bool:
    try:
        return x is not None and not pd.isna(x)
    except Exception:  # noqa: BLE001
        return False


def _interp(points, T: float):
    """Linear interpolation in maturity over (maturity, yield) points; clamped at the ends."""
    pts = sorted(p for p in points if _notna(p[1]))
    if not pts:
        return None
    if T <= pts[0][0]:
        return pts[0][1]
    if T >= pts[-1][0]:
        return pts[-1][1]
    for (t0, y0), (t1, y1) in zip(pts, pts[1:]):
        if t0 <= T <= t1:
            return y0 + (y1 - y0) * (T - t0) / (t1 - t0)
    return None


def _bracket(points, T: float):
    mats = [m for m, _, _ in points]
    lo = max([m for m in mats if m <= T], default=min(mats))
    hi = min([m for m in mats if m >= T], default=max(mats))
    return sorted({c for m, c, _ in points if m in (lo, hi)})


def _row_on(ind, cols, through):
    """The latest date on or before `through` where every column in `cols` has a value."""
    miss = [c for c in cols if c not in ind.columns]
    if miss:
        return None, miss
    sub = ind.loc[:through, cols].dropna()
    if sub.empty:
        return None, list(cols)
    return sub.index[-1], []


def carry_for(tk: str, ind, through, duration, cfg: dict) -> dict:
    """Curve-implied yield and the carry metric for one sleeve (R3.2/R3.3). Every value carries its
    series and date; nothing is substituted when an input is missing."""
    out = {"curve_implied_yield_pct": None, "curve_type": CURVE_TYPE.get(tk), "avg_maturity_years": None,
           "avg_maturity_as_of": None, "avg_maturity_source": None, "inputs": None, "inputs_date": None,
           "curve_implied_reason": None, "pickup_bp": None, "breakeven_rise_bp": None,
           "real_yield_pct": None, "breakeven_at_maturity_pct": None, "nominal_equivalent_pct": None}
    if tk in NO_CURVE_REASON:
        out["curve_implied_reason"] = NO_CURVE_REASON[tk]
        return out
    if tk not in CURVE_TYPE or tk not in AVG_MATURITY:
        out["curve_implied_reason"] = "no average-maturity figure on record for the sleeve"
        return out
    T, mat_asof, mat_src = AVG_MATURITY[tk]
    out.update(avg_maturity_years=T, avg_maturity_as_of=mat_asof, avg_maturity_source=mat_src)
    cmt = [(float(p["maturity"]), p["col"], p["series"]) for p in cfg["cmt_points"]]
    real = [(float(p["maturity"]), p["col"], p["series"]) for p in cfg["real_points"]]
    kind = CURVE_TYPE[tk]
    pts = real if kind == "real" else cmt
    need = _bracket(pts, T)
    extra, bucket = [], None
    if kind == "ig":
        bucket = next((x for x in cfg["ig_buckets"] if x["from"] <= T and (x["to"] is None or T < x["to"])), None)
        if bucket is None:
            out["curve_implied_reason"] = f"maturity {T}y falls in no frozen IG bucket"
            return out
        extra = [bucket["col"]]
    elif kind == "hy":
        extra = ["hy_oas"]
    cols = need + extra + ([CASH_SERIES] if kind != "real" else [])
    d, missing = _row_on(ind, cols, through)
    if d is None:
        out["curve_implied_reason"] = f"input series missing from the store: {missing} (pending the FRED fetch); never substituted"
        return out
    row = ind.loc[d]
    sid = {c: s for _, c, s in pts}
    y = _interp([(m, float(row[c])) for m, c, _ in pts if c in need], T)
    ds = str(d.date())
    inputs = {c: {"series": sid[c], "value": float(row[c]), "date": ds, "provider": "FRED"} for c in need}
    if kind == "ig":
        inputs[bucket["col"]] = {"series": bucket["series"], "value": float(row[bucket["col"]]), "date": ds,
                                 "provider": "FRED (ICE BofA)", "bucket": bucket["label"]}
        y += float(row[bucket["col"]])
    elif kind == "hy":
        inputs["hy_oas"] = {"series": "BAMLH0A0HYM2", "value": float(row["hy_oas"]), "date": ds, "provider": "FRED (ICE BofA)"}
        y += float(row["hy_oas"])
    out["inputs"], out["inputs_date"] = inputs, ds
    if kind == "real":
        # TIP: a REAL yield, excluded from nominal comparisons. The nominal-equivalent (real plus the
        # breakeven at the same maturity) is shown only when both are available on the same date.
        out["real_yield_pct"] = round(y, 3)
        ncols = _bracket(cmt, T)
        if all(c in ind.columns and _notna(ind.loc[d, c]) for c in ncols):
            nom = _interp([(m, float(ind.loc[d, c])) for m, c, _ in cmt if c in ncols], T)
            out["breakeven_at_maturity_pct"] = round(nom - y, 3)
            out["nominal_equivalent_pct"] = round(y + (nom - y), 3)
            for c in ncols:
                inputs[c] = {"series": {cc: s for _, cc, s in cmt}[c], "value": float(ind.loc[d, c]), "date": ds, "provider": "FRED"}
        out["curve_implied_reason"] = "a real yield (TIPS curve): excluded from nominal comparisons"
        return out
    out["curve_implied_yield_pct"] = round(y, 3)
    y_cash = float(row[CASH_SERIES])
    inputs[CASH_SERIES] = {"series": "DGS3MO", "value": y_cash, "date": ds, "provider": "FRED"}
    out["pickup_bp"] = round((y - y_cash) * 100.0, 1)
    if duration and duration > 0:
        out["breakeven_rise_bp"] = round(out["pickup_bp"] / duration, 1)
    return out


def sigma_daily_bp(ind, through, col: str = SIGMA_SERIES, window: int = SIGMA_WINDOW):
    """Standard deviation of daily changes of the 10-year CMT over `window` sessions, in bp."""
    if col not in ind.columns:
        return None, 0
    s = ind.loc[:through, col].dropna()
    ch = s.diff().dropna().iloc[-window:] * 100.0
    if len(ch) < 60:
        return None, len(ch)
    return round(float(ch.std()), 2), len(ch)

WINDOW = 126               # correlation / vol window, matching the book panel (order §7)
MIN_OBS = 60
ANN = 252.0
YEAR_SESSIONS = 252        # ~1-year total return lookback


def load_sleeve_universe() -> dict:
    return json.loads((BONDS / "sleeve_universe.json").read_text())


def sleeve_tickers() -> list[str]:
    return [s["ticker"] for s in load_sleeve_universe()["sleeves"]]


def load_state_config() -> dict:
    return json.loads((BONDS / "state_config.json").read_text())


def load_sleeve_prices() -> pd.DataFrame:
    """Adjusted-close price history for the sleeves (data/source/bond_sleeves.parquet)."""
    df = pd.read_parquet(SLEEVE_PRICES)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def load_sleeve_yields() -> dict:
    """Provider distribution yields keyed by ticker, with the field and retrieval date."""
    if SLEEVE_YIELDS.exists():
        return json.loads(SLEEVE_YIELDS.read_text())
    return {"field": None, "retrieved_at": None, "yields": {}}


def pct_rank(window: pd.Series, value: float) -> float | None:
    """Percentile (0-100) of `value` within `window` (share of observations below it)."""
    w = window.dropna()
    if len(w) < 30 or value is None or pd.isna(value):
        return None
    return round(float((w < value).mean()) * 100.0, 1)


def state_from_bands(pct: float | None, bands: list[dict]) -> str | None:
    """Map a percentile to a band id. Each band: {id, min_pct?, max_pct?} (min inclusive,
    max exclusive; open where a bound is absent)."""
    if pct is None:
        return None
    for b in bands:
        lo = b.get("min_pct", 0.0)
        hi = b.get("max_pct", 100.0 + 1e-9)
        if lo <= pct < hi:
            return b["id"]
    return bands[-1]["id"] if pct >= bands[-1].get("min_pct", 0) else None
