#!/usr/bin/env python3
"""
tests/test_entry_state.py — Execution Order: Entry-State Indicator (2 Oct 2026), E1.

Acceptance 2: Incyte and Corpay reproduce the order's 1-Oct reference values from fixtures of their daily
OHLC (tests/fixtures/entry/*.csv, yfinance auto_adjust=False, as of 1 Oct).
Acceptance 4: a synthetic series moves through AVOID, WAIT, WATCH, READY and back to WATCH on a stop breach,
each transition logged with its reason. Plus the event gate (READY-HALF) and the sizing rule.

    .venv/bin/python tests/test_entry_state.py
"""
from __future__ import annotations
import sys
import traceback
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import entry_state as es  # noqa: E402

CFG = es.load_config()
FX = REPO / "tests" / "fixtures" / "entry"
RESULTS = []


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def load(tk):
    return pd.read_csv(FX / f"{tk}_ohlc_to_2026-10-01.csv", index_col=0, parse_dates=True)


def close_to(a, b, tol):
    assert abs(float(a) - float(b)) <= tol, (a, b)


def test_incyte_reference_values():
    ind = es.indicators(load("INCY"), CFG); r = ind.iloc[-1]
    assert str(ind.index[-1].date()) == "2026-10-01"
    close_to(r["close"], 117.14, 0.005); close_to(r["ma_short"], 124.13, 0.005); close_to(r["ma50"], 123.65, 0.005)
    close_to(r["ma_long"], 106.77, 0.005); close_to(r["atr"], 3.27, 0.005); close_to(r["rsi"], 41, 0.5)
    close_to(r["range_lo"], 115.77, 0.005); close_to(r["range_hi"], 130.80, 0.005)
    assert bool(r["trend"]) and bool(r["setup"]) and not (r["trig_high"] or r["trig_failed_breakdown"])
    ev = es.evaluate(ind.iloc[-60:], CFG, [date(2026, 10, 27)])
    assert ev.iloc[-1]["state"] == "WATCH", ev.iloc[-1]
    close_to(r["stop"], 112.50, 0.005)
    # "READY-HALF once triggered; earnings 27 October": the event gate on a triggered session
    trig = ind.iloc[-1:].copy(); trig["trig_high"] = True
    assert es.evaluate(trig, CFG, [date(2026, 10, 27)]).iloc[-1]["state"] == "READY-HALF"
    assert es.sessions_until(date(2026, 10, 1), date(2026, 10, 27)) == 18


def test_corpay_reference_values():
    ind = es.indicators(load("CPAY"), CFG); r = ind.iloc[-1]
    close_to(r["close"], 389.73, 0.005); close_to(r["ma_long"], 346.32, 0.005); close_to(r["atr"], 7.47, 0.005)
    close_to(r["rsi"], 31, 0.5); close_to(r["range_lo"], 386.23, 0.005); close_to(r["range_hi"], 427.46, 0.005)
    assert es.evaluate(ind.iloc[-60:], CFG, []).iloc[-1]["state"] == "WATCH"
    close_to(r["stop"], 378.76, 0.005)


def synthetic() -> pd.DataFrame:
    """Decline (AVOID), slow then fast rise (WAIT once the trend gate passes), an eight-session pullback
    (WATCH), a +3% close above the prior high (READY), then on the next session a close below the armed stop
    that stays above the 200-day average (back to WATCH, logged as a stop breach)."""
    px = [100.0]
    for _ in range(299): px.append(px[-1] * (60 / 100) ** (1 / 299))       # decline 100 -> 60
    for _ in range(200): px.append(px[-1] * (80 / 60) ** (1 / 200))        # slow rise 60 -> 80
    for _ in range(60):  px.append(px[-1] * (170 / 80) ** (1 / 60))        # fast rise 80 -> 170
    for _ in range(8):   px.append(px[-1] * 0.975)                         # pullback
    px.append(px[-1] * 1.03)                                               # trigger: above the prior high
    px.append(px[-1] * 0.68)                                               # next session: below the armed stop
    c = np.array(px)
    idx = pd.bdate_range("2023-01-02", periods=len(c))
    df = pd.DataFrame({"open": np.r_[c[0], c[:-1]], "high": c * 1.005, "low": c * 0.995, "close": c}, index=idx)
    df["adj_close"] = df["close"]
    return df


def test_synthetic_walks_every_state_and_logs_each_transition():
    ind = es.indicators(synthetic(), CFG)
    ev = es.evaluate(ind, CFG, None)
    tr = es.transitions_of(ev)
    seq = [(t["from"], t["to"]) for t in tr]
    assert seq == [("AVOID", "WAIT"), ("WAIT", "WATCH"), ("WATCH", "READY"), ("READY", "WATCH")], tr
    breach = [t for t in tr if t["reason"].startswith("stop breach")]
    assert len(breach) == 1 and breach[0]["from"] == "READY" and breach[0]["to"] == "WATCH", tr
    assert list(ev["state"].iloc[-2:]) == ["READY", "WATCH"], list(ev["state"].iloc[-2:])
    last = ind.iloc[-1]
    assert bool(last["trend"]) and last["close"] > last["ma_long"], "the breach must stay above the 200-day average"
    assert [t["reason"] for t in tr][2] == "close above the prior session's high"
    assert ev.iloc[-1]["armed_stop"] is None or pd.isna(ev.iloc[-1]["armed_stop"]), "the breach disarms the stop"


def test_stop_floor_and_failed_breakdown():
    df = synthetic()
    ind = es.indicators(df, CFG)
    assert (ind["stop"].dropna() >= ind["ma_long"].dropna().reindex(ind["stop"].dropna().index).fillna(-1) - 1e-9).all()
    # a close below the prior 40-session low, then the first close back above it, is a trigger
    c = np.r_[np.linspace(100, 140, 300), [138, 137, 136, 139.5, 141.0]]
    lows = c * 0.995; lows[-4] = 135.0           # a new low on the session before the break
    df2 = pd.DataFrame({"open": c, "high": c * 1.005, "low": lows, "close": c}, index=pd.bdate_range("2024-01-01", periods=len(c)))
    df2.iloc[-3, df2.columns.get_loc("close")] = 130.0      # close below the prior 40-session low
    df2.iloc[-3, df2.columns.get_loc("low")] = 129.0
    i2 = es.indicators(df2, CFG)
    assert bool(i2["trig_failed_breakdown"].iloc[-2]) or bool(i2["trig_failed_breakdown"].iloc[-1]), i2[["close", "prior_lo", "breakdown_level", "trig_failed_breakdown"]].tail(5)


def test_states_are_from_the_allowed_set():
    ev = es.evaluate(es.indicators(load("INCY"), CFG).iloc[-120:], CFG, [date(2026, 10, 27)])
    assert set(ev["state"].dropna()) <= set(es.STATES)


if __name__ == "__main__":
    for fn in [test_incyte_reference_values, test_corpay_reference_values, test_synthetic_walks_every_state_and_logs_each_transition,
               test_stop_floor_and_failed_breakdown, test_states_are_from_the_allowed_set]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
