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
