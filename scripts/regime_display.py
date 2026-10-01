"""
regime_display.py — display-only fields for the v2 regime cards (order 1-Oct-2026, item R1).

Nothing here is read by the model of record. compute_regime_v2.py computes z, phi, status, R_lead,
R_full and the label exactly as before; this module only turns each indicator's value and status into
the text a reader sees:

  value_str  the value with its true unit (R1.1). HY OAS is stored in percent (3.08) and is shown in
             basis points (308bp); Baa-Aaa is stored in basis points (43.0 = 6.19% - 5.76%).
  narrative  two computed parts (R1.2): a LEVEL phrase from the value itself (sign-aware where the
             sign carries meaning: contango/backwardation, inverted, up/down, easing/tightening,
             looser/tighter than average) and a RELATIVE phrase from the status bucket that names its
             window ("above its past-year norm"). Severity words never appear unless the reading's
             ten-year percentile in the risky direction is at least 90 — and the computed phrases use
             none, so they cannot frame an ordinary reading as a crisis.
  pctile_10y, pctile_10y_risky, rank_1y_pct, z_756, z_window  scale fields (R1.3); informational.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

SEVERITY_WORDS = ("crisis", "acute", "stress", "shock", "spike", "crunch", "drain", "severely", "panic")

# key -> (scale applied to the stored value for display, format, unit shown, plain name for the level phrase)
# The unit is "" for indices and ratios, which have none.
DISPLAY = {
    "nfci":            (1.0,   "{v:+.2f}",   "",    "NFCI"),
    "anfci":           (1.0,   "{v:+.2f}",   "",    "ANFCI"),
    "yield_3m10y":     (1.0,   "{v:+.2f}pp", "pp",  "3m-10y slope"),
    "breakeven_5y":    (1.0,   "{v:.2f}%",   "%",   "5-year breakeven"),
    "baa_aaa":         (1.0,   "{v:.0f}bp",  "bp",  "Baa-Aaa spread"),
    "vix_term":        (1.0,   "{v:+.1f} pts", "pts", "VIX minus VIX3M"),
    "skew":            (1.0,   "{v:.0f}",    "",    "SKEW"),
    "vix":             (1.0,   "{v:.2f}",    "",    "VIX"),
    "vvix":            (1.0,   "{v:.1f}",    "",    "VVIX"),
    "mfg_new_orders":  (1.0,   "${v:,.0f}M", "$M",  "durable-goods new orders"),
    "kcfsi":           (1.0,   "{v:+.2f}",   "",    "KCFSI"),
    "stlfsi":          (1.0,   "{v:+.2f}",   "",    "STLFSI"),
    "loan_tightening": (1.0,   "{v:+.1f}%",  "%",   "net share of banks tightening"),
    "consumer_expect": (1.0,   "{v:.1f}%",   "%",   "Michigan 1-year expected inflation"),
    "hy_oas":          (100.0, "{v:.0f}bp",  "bp",  "HY OAS"),
    "gold_spx":        (1.0,   "{v:.2f}",    "",    "gold/S&P 500 ratio"),
    "tlt_spx":         (1.0,   "{v:.3f}",    "",    "TLT/S&P 500 ratio"),
    "def_cyc":         (1.0,   "{v:.2f}",    "",    "defensive/cyclical ratio"),
    "dxy":             (1.0,   "{v:.1f}",    "",    "DXY"),
    "realized_vol":    (1.0,   "{v:.1f}%",   "%",   "20-day realized volatility"),
    "spx_ret_60d":     (1.0,   "{v:+.1f}%",  "%",   "S&P 500 60-session return"),
    "spx_drawdown":    (1.0,   "{v:+.1f}%",  "%",   "S&P 500 drawdown"),
    "oil_60d_vel":     (1.0,   "{v:+.1f}%",  "%",   "oil 60-session change"),
}
WINDOW_TXT = "past-year norm"
Z_WINDOW = "252 sessions"


def value_str(key: str, v: float | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    scale, fmt, _unit, _name = DISPLAY.get(key, (1.0, "{v:.2f}", "", key))
    try:
        return fmt.format(v=v * scale)
    except Exception:  # noqa: BLE001
        return f"{v * scale:.2f}"


def unit_of(key: str) -> str:
    return DISPLAY.get(key, (1.0, "", "", key))[2]


def level_phrase(key: str, v: float | None) -> str:
    """The value itself, sign-aware where the sign carries meaning (R1.2a)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "no reading"
    vs = value_str(key, v)
    name = DISPLAY.get(key, (1.0, "", "", key))[3]
    if key == "vix_term":
        return (f"VIX curve in contango ({vs})" if v < 0 else
                f"VIX curve in backwardation ({vs})" if v > 0 else f"VIX curve flat ({vs})")
    if key == "yield_3m10y":
        return f"3m-10y curve inverted ({vs})" if v < 0 else f"3m-10y curve upward-sloping ({vs})"
    if key == "spx_ret_60d":
        return f"S&P 500 {'up' if v >= 0 else 'down'} {abs(v):.1f}% over 60 sessions"
    if key == "oil_60d_vel":
        return f"oil {'up' if v >= 0 else 'down'} {abs(v):.1f}% over 60 sessions"
    if key == "spx_drawdown":
        return "S&P 500 at its high" if abs(v) < 0.05 else f"S&P 500 {abs(v):.1f}% below its high"
    if key == "loan_tightening":
        return (f"banks net tightening ({vs})" if v > 0 else f"banks net easing ({vs})" if v < 0
                else f"lending standards unchanged (net {vs})")
    if key in ("nfci", "anfci"):
        return f"{name} {vs}: conditions {'looser' if v < 0 else 'tighter'} than average"
    if key in ("kcfsi", "stlfsi"):
        return f"{name} {vs}: calmer than average" if v < 0 else f"{name} {vs}: above average"
    return f"{name} {vs}"


def relative_phrase(status: str, direction: str, rank_1y_pct: float | None) -> str:
    """The status bucket, naming its window (R1.2b). For lower-is-riskier channels the risky side is
    below the norm, so 'below' replaces 'above' and vice versa."""
    up, down = ("above", "below") if direction == "higher" else ("below", "above")
    if status == "safe":
        return f"{down} its {WINDOW_TXT}"
    if status == "neutral":
        return f"near its {WINDOW_TXT}"
    if status == "elevated":
        return f"{up} its {WINDOW_TXT}"
    # extreme against the past year: name the rank within the trailing 252 sessions
    if rank_1y_pct is None:
        return f"far {up} its {WINDOW_TXT}"
    side = rank_1y_pct if direction == "higher" else 100.0 - rank_1y_pct
    where = ("top decile" if side >= 90 else f"{_ordinal(round(rank_1y_pct))} percentile")
    return f"far {up} its {WINDOW_TXT} ({where} of the trailing 252 sessions)"


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def narrative(key: str, v: float | None, status: str, direction: str, rank_1y_pct: float | None) -> str:
    if v is None or status is None:
        return "—"
    return f"{level_phrase(key, v)}; {relative_phrase(status, direction, rank_1y_pct)}"


def pctile_10y(series: pd.Series, value: float | None, through: pd.Timestamp) -> float | None:
    """Same method as scripts/bonds/compute_bonds.py::pctile: the share of the trailing ten calendar
    years of the series, through the session, strictly below the value (0-100, one decimal); None with
    fewer than 250 observations."""
    if value is None:
        return None
    w = series.loc[through - pd.DateOffset(years=10):through].dropna()
    if len(w) < 250:
        return None
    return round(float((w < value).mean()) * 100.0, 1)


def rank_1y(series: pd.Series, value: float | None, through: pd.Timestamp) -> float | None:
    """Percentile of the value within the trailing 252 sessions of the same series (the z window)."""
    if value is None:
        return None
    w = series.loc[:through].dropna().iloc[-252:]
    if len(w) < 60:
        return None
    return round(float((w < value).mean()) * 100.0, 1)


def z_window(series: pd.Series, window: int, min_periods: int = 60) -> float | None:
    """Informational z of the last value on a longer window (756 sessions); never used by status."""
    s = series.dropna()
    if len(s) < min_periods:
        return None
    m = s.rolling(window, min_periods=min_periods).mean().iloc[-1]
    sd = s.rolling(window, min_periods=min_periods).std().iloc[-1]
    if sd is None or not np.isfinite(sd) or sd == 0:
        return None
    return float((s.iloc[-1] - m) / sd)


def display_fields(key: str, direction: str, panel_series: pd.Series, raw_v: float | None, status: str,
                   through: pd.Timestamp) -> dict:
    """Every display-only field for one indicator card."""
    p10 = pctile_10y(panel_series, raw_v, through)
    r1 = rank_1y(panel_series, raw_v, through)
    z756 = z_window(panel_series.loc[:through], 756)
    if z756 is not None and direction == "lower":
        z756 = -z756                     # the same risk orientation as the model's z
    risky = None if p10 is None else (p10 if direction == "higher" else round(100.0 - p10, 1))
    return {
        "value_str": value_str(key, raw_v),
        "unit": unit_of(key),
        "narrative": narrative(key, raw_v, status, direction, r1),
        "pctile_10y": p10,
        "pctile_10y_risky": risky,
        "rank_1y_pct": r1,
        "z_window": Z_WINDOW,
        "z_756": round(z756, 3) if z756 is not None else None,
    }
