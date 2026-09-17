#!/usr/bin/env python3
"""compute_bonds.py — data/bonds/states.json (order phases 2, 3, 4).

The state reads (pre-registered, no forecast), the allocation questions (pre-registered
rules), and the book integration for the fixed-income module. Every rule that drives a
display is defined in config and frozen before it runs (data/bonds/state_config.json).

The module reads the level and slope of the curve, credit spreads versus their history,
and breakevens; it does not predict rates. States are descriptive; the rates-regime state
is gated DIAGNOSTIC and drives no sizing (Phase 6 validates it). No buy or sell instruction.

Reads the FRED store as-published: the point-in-time (ALFRED) parquet when it is current,
else the revised parquet with the vintage recorded (yields and OAS are essentially not
revised, so the two coincide; the point-in-time overlay refreshes on the vintage rebuild).
"""
from __future__ import annotations
import json, sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import bonds_common as bc
import book_analytics as ba

HISTORY_YEARS = 10


def log(m: str) -> None:
    print(m, flush=True)


# ── FRED store (as-published) ──────────────────────────────────────────────
def load_fred() -> tuple[pd.DataFrame, str, pd.Timestamp]:
    """Indicators frame, store label, through-date. Prefer the point-in-time store when it
    is within a week of the revised store; else use revised and say the overlay is pending."""
    rev = pd.read_parquet(bc.SOURCE / "fred_indicators.parquet"); rev.index = pd.to_datetime(rev.index)
    rev_last = rev.index.max()
    try:
        pit = pd.read_parquet(bc.SOURCE / "fred_indicators_pit.parquet"); pit.index = pd.to_datetime(pit.index)
        if (rev_last - pit.index.max()).days <= 7:
            return pit.sort_index(), "point-in-time (as-published, ALFRED)", pit.index.max()
    except Exception:
        pass
    return rev.sort_index(), "revised (as-published latest; point-in-time overlay rebuilds on the vintage workflow)", rev_last


def last_valid(s: pd.Series) -> tuple[float | None, pd.Timestamp | None]:
    s = s.dropna()
    if s.empty:
        return None, None
    return float(s.iloc[-1]), s.index[-1]


def pctile(series: pd.Series, value: float | None, through: pd.Timestamp, years: int = HISTORY_YEARS) -> float | None:
    """Percentile (0-100) of `value` within the trailing `years` of `series` up to `through`."""
    if value is None:
        return None
    w = series.loc[through - pd.DateOffset(years=years):through].dropna()
    if len(w) < 250:
        return None
    return round(float((w < value).mean()) * 100.0, 1)


def band_for(pct: float | None, bands: list[dict]) -> str | None:
    if pct is None:
        return None
    for b in bands:
        if b.get("min_pct", 0.0) <= pct < b.get("max_pct", 100.0 + 1e-9):
            return b["id"]
    return None


# ── 2.1 curve state ────────────────────────────────────────────────────────
def curve_state(cfg: dict, ind: pd.DataFrame, through: pd.Timestamp) -> dict:
    cc = cfg["curve"]
    have = lambda c: c in ind.columns and ind[c].dropna().size > 0
    # slope 2s10s (config series) and 3m10y for context; computed from the maturities
    slope = (ind["us10y"] - ind["us02y"]) if (have("us10y") and have("us02y")) else pd.Series(dtype=float)
    cur_slope, slope_date = last_valid(slope)
    slope_pct = pctile(slope, cur_slope, through)
    state = band_for(slope_pct, cc["bands"])

    slope_3m10y = (ind["us10y"] - ind["us03m"]) if (have("us10y") and have("us03m")) else pd.Series(dtype=float)
    cur_3m10y, _ = last_valid(slope_3m10y)

    maturities = []
    for m in cfg["maturities"]:
        lbl = cfg["maturity_labels"].get(m, m)
        if have(m):
            lvl, d = last_valid(ind[m])
            maturities.append({"maturity": lbl, "series": m, "level_pct": round(lvl, 2) if lvl is not None else None,
                               "pctile_10y": pctile(ind[m], lvl, through), "as_of": str(d.date()) if d is not None else None})
        else:
            maturities.append({"maturity": lbl, "series": m, "level_pct": None, "pctile_10y": None,
                               "as_of": None, "unavailable": "series not yet in the store (pending FRED fetch)"})
    return {
        "series": cc["series"], "label": cc["label"],
        "slope_2s10s_pct": round(cur_slope, 2) if cur_slope is not None else None,
        "slope_2s10s_bps": round(cur_slope * 100, 0) if cur_slope is not None else None,
        "slope_2s10s_pctile_10y": slope_pct,
        "slope_3m10y_pct": round(cur_3m10y, 2) if cur_3m10y is not None else None,
        "state": state,
        "as_of": str(slope_date.date()) if slope_date is not None else None,
        "maturities": maturities,
        "bands": cc["bands"],
        "footnote": ("States: inverted (2s10s below its 10th percentile over ten years), flat (10th–40th), "
                     "normal (40th–80th), steep (above 80th). Descriptive; no rate direction implied."),
    }


# ── 2.2 credit state ───────────────────────────────────────────────────────
def _oas_leg(ind: pd.DataFrame, col: str, bands: list[dict], through: pd.Timestamp) -> dict:
    if col not in ind.columns:
        return {"oas_pct": None, "oas_bps": None, "pctile_10y": None, "state": None,
                "unavailable": "OAS series not in the store"}
    lvl, d = last_valid(ind[col])                    # OAS series are in percent (0.80 = 80 bps)
    pct = pctile(ind[col], lvl, through)
    return {"oas_pct": round(lvl, 3) if lvl is not None else None,
            "oas_bps": round(lvl * 100, 0) if lvl is not None else None,
            "pctile_10y": pct, "state": band_for(pct, bands),
            "as_of": str(d.date()) if d is not None else None}


def credit_state(cfg: dict, ind: pd.DataFrame, through: pd.Timestamp) -> dict:
    cc = cfg["credit"]
    return {
        "method": cc["method"],   # references option-adjusted spreads; the referee enforces this
        "ig": _oas_leg(ind, "ig_oas", cc["bands"], through),
        "hy": _oas_leg(ind, "hy_oas", cc["bands"], through),
        "bands": cc["bands"],
        "duration_caveat": ("Computed from the option-adjusted spread series, which are "
                            "duration-controlled by construction — NOT an ETF price ratio. A raw "
                            "HYG-versus-LQD ratio is prohibited (duration-confounding, per the ledger)."),
        "footnote": ("States against ten-year OAS history: tight (<20th percentile), normal (20–60th), "
                     "wide (60–90th), stressed (>90th). Descriptive; no spread direction implied. "
                     "Tight spreads mean little compensation for default and illiquidity risk."),
    }


# ── payload ────────────────────────────────────────────────────────────────
def build() -> dict:
    cfg = bc.load_state_config()
    ind, store, through = load_fred()

    curve = curve_state(cfg, ind, through)
    credit = credit_state(cfg, ind, through)

    session = str(through.date())
    return {
        "cadence": "daily",
        "session_date": session,
        "as_of": datetime.now().astimezone().date().isoformat(),
        "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "vintage": {"store": store, "fred_through": str(through.date()), "history_years": HISTORY_YEARS},
        "config_frozen_at": cfg.get("frozen_at"),
        "curve": curve,
        "credit": credit,
        "note": "descriptive; states and associations only, no rate forecast; no buy or sell instruction.",
    }


def main() -> int:
    payload = build()
    out = bc.BONDS / "states.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    c = payload["curve"]
    log(f"saved states.json  vintage={payload['vintage']['store']} through {payload['session_date']}")
    log(f"  curve: 2s10s {c['slope_2s10s_bps']}bp (pctile {c['slope_2s10s_pctile_10y']}) → state {c['state']!r}")
    cr = payload["credit"]
    log(f"  credit IG: {cr['ig']['oas_bps']}bp (pctile {cr['ig']['pctile_10y']}) → {cr['ig']['state']!r} · "
        f"HY: {cr['hy']['oas_bps']}bp (pctile {cr['hy']['pctile_10y']}) → {cr['hy']['state']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
