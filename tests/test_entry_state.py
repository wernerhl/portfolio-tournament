#!/usr/bin/env python3
"""
tests/test_entry_state.py — the entry-state rules, version 3 (Execution Order: Revision of the Entry-State Indicator,
6 October 2026, as revised the same day). The 2-Oct rules' tests stay in tests/test_entry_state_v1.py against the
frozen module.

Acceptance 2 (states at the 5 October close), from fixtures of each name's daily OHLC and volume
(tests/fixtures/entry/*_ohlc_to_2026-10-05.csv) with the inputs the order states: Lockheed Martin READY-HALF with
below_200d, stop near $487 (40-session low $498.55 less ATR); Micron READY at full size; Powell READY with
below_200d at half size; Incyte capped at WATCH by its ceiling ($131.50); Texas Pacific Land heavily shorted
(days-to-cover 12.6); Ondas AVOID (close $7.42, 200-day $9.44, 12-month momentum -17%), heavily shorted by short
interest of the float (days-to-cover 3.8). No WAIT state. Plus the rule mechanics: the trend gate fails only below
the 200-day with negative momentum, no 200-day floor on the stop, the quarter-size floor, the ceiling cap lifting
on a close above it.

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
    return pd.read_csv(FX / f"{tk}_ohlc_to_2026-10-05.csv", index_col=0, parse_dates=True)


def last(tk, earnings=None, dtc=None, ceiling=None, spf=None):
    ind = es.indicators(load(tk), CFG)
    ev = es.evaluate(ind.iloc[-5:], CFG, earnings, dtc, ceiling, spf)
    return ind.iloc[-1], ev.iloc[-1]


def test_config_is_version_3_and_earlier_versions_are_kept():
    assert CFG["version"] == 3 and CFG["label"] == "DIAGNOSTIC"
    assert "WAIT" not in CFG["states"] and "WAIT" not in es.STATES
    import hashlib
    v1 = REPO / "data" / "entry_state_config_2026-10-02.json"
    assert hashlib.sha256(v1.read_bytes()).hexdigest().startswith("0f438215"), "the 2-Oct config must stay byte-identical"
    v2 = REPO / "data" / "entry_state_config_2026-10-06_v2.json"
    assert hashlib.sha256(v2.read_bytes()).hexdigest().startswith("4aa58cc4"), "the morning's version 2 must stay byte-identical"


def test_lockheed_ready_half_below_200d():
    r, e = last("LMT", [date(2026, 10, 22)], 2.26)
    assert str(r.name.date()) == "2026-10-05"
    assert bool(r["below_200d"]) and r["mom_12_1"] > 0 and bool(r["trend"]), (r["close"], r["ma_long"], r["mom_12_1"])
    assert e["state"] == "READY-HALF", e
    assert e["modifiers"] == ["below_200d", "earnings"] and abs(e["size_factor"] - 0.25) < 1e-9, e
    lo40 = load("LMT")["low"].iloc[-40:].min()
    assert abs(lo40 - 498.55) < 0.01, lo40
    assert abs(r["stop"] - (lo40 - r["atr"])) < 1e-9 and abs(r["stop"] - 487) < 1.5, r["stop"]


def test_micron_ready_at_full_size():
    """Above its 200-day, positive 12-month momentum, earnings on 23 December (56 sessions away), days-to-cover 1.07 and
    short interest 2.5% of the float: READY with no modifier. Under version 2 it read WAIT (extended, no pullback)."""
    r, e = last("MU", [date(2026, 12, 23)], 1.07, None, 0.0245)
    assert not bool(r["below_200d"]) and r["mom_12_1"] > 0, (r["close"], r["ma_long"], r["mom_12_1"])
    assert e["state"] == "READY" and e["modifiers"] == [] and e["size_factor"] == 1.0, e


def test_powell_ready_half_size_below_200d():
    """Below its 200-day with positive momentum, extended (RSI above 70): READY at half size, the below_200d modifier only
    (earnings on 17 November, 31 sessions away; days-to-cover 4.4, short interest 9.8% of the float)."""
    r, e = last("POWL", [date(2026, 11, 17)], 4.38, None, 0.0975)
    assert abs(r["close"] - 197.84) < 0.005 and bool(r["below_200d"]) and r["mom_12_1"] > 0 and r["rsi"] > 70, (r["close"], r["rsi"])
    assert e["state"] == "READY" and e["modifiers"] == ["below_200d"] and e["size_factor"] == 0.5, e


def test_ondas_avoid_and_heavily_shorted_by_float():
    """Close $7.42 under the 200-day $9.44 with 12-month momentum -17%: AVOID. Heavily shorted by short interest of the
    float (days-to-cover 3.8 alone would not set it)."""
    r, e = last("ONDS", None, 3.83, None, 0.4096)
    assert abs(r["close"] - 7.42) < 0.005 and abs(r["ma_long"] - 9.44) < 0.005 and abs(r["mom_12_1"] + 0.17) < 0.01, (r["close"], r["ma_long"], r["mom_12_1"])
    assert e["state"] == "AVOID", e
    assert es.heavily_shorted(3.83, 0.4096, CFG) and not es.heavily_shorted(3.83, None, CFG) and not es.heavily_shorted(3.83, 0.19, CFG)
    assert es.heavily_shorted(7.0, None, CFG) and es.heavily_shorted(None, 0.20, CFG)


def test_no_wait_state_extended_names_are_ready():
    """An extended name and a pulling-back name read the same: every session with a passing gate is READY, READY-HALF or
    WATCH, never WAIT."""
    for tk in ("MU", "POWL", "LMT", "TPL", "INCY"):
        ev = es.evaluate(es.indicators(load(tk), CFG).iloc[-120:], CFG)
        assert "WAIT" not in set(ev["state"].dropna()), tk


def test_incyte_watch_under_its_ceiling():
    r, e = last("INCY", [date(2026, 10, 27)], 7.62, 131.50)
    assert abs(r["close"] - 114.13) < 0.005
    assert e["ceiling_capped"] and e["state"] == "WATCH", e
    assert "ceiling" in e["watch_reason"]
    # without the ceiling it would be READY-HALF: earnings and heavy shorting give a quarter of the base
    _, e2 = last("INCY", [date(2026, 10, 27)], 7.62, None)
    assert e2["state"] == "READY-HALF" and e2["modifiers"] == ["earnings", "heavily_shorted"], e2


def test_tpl_heavily_shorted():
    r, e = last("TPL", [date(2026, 11, 4)], 12.59)
    assert "heavily_shorted" in e["modifiers"], e
    assert e["state"] == "READY" and abs(e["size_factor"] - 0.25) < 1e-9, e          # below_200d and shorting; earnings 22 sessions away


def synth(closes, vol=1e6):
    c = np.asarray(closes, float)
    idx = pd.bdate_range("2023-01-02", periods=len(c))
    return pd.DataFrame({"open": c, "high": c * 1.005, "low": c * 0.995, "close": c, "adj_close": c, "volume": vol}, index=idx)


def test_trend_gate_fails_only_below_200d_with_negative_momentum():
    falling = np.linspace(200, 100, 320)                          # below the 200-day, momentum negative
    ind = es.indicators(synth(falling), CFG)
    assert not bool(ind["trend"].iloc[-1]) and bool(ind["below_200d"].iloc[-1])
    assert es.evaluate(ind.iloc[-1:], CFG)["state"].iloc[-1] == "AVOID"
    # above the 200-day with negative 12-1 momentum passes (the 2-Oct rule would have failed it)
    up_then_flat_dip = np.r_[np.full(60, 200.0), np.linspace(200, 100, 150), np.linspace(100, 150, 90)]   # 12-1 return about -27%
    i2 = es.indicators(synth(up_then_flat_dip), CFG); r2 = i2.iloc[-1]
    assert r2["close"] > r2["ma_long"] and r2["mom_12_1"] < 0 and bool(r2["trend"]), (r2["close"], r2["ma_long"], r2["mom_12_1"])


def test_no_200d_floor_on_the_stop():
    ind = es.indicators(load("TPL"), CFG); r = ind.iloc[-1]
    assert r["stop"] < r["ma_long"], "the stop is the 40-session low less 1 ATR even when that lies under the 200-day"


def test_quarter_floor_turns_three_modifiers_into_watch():
    r, e = last("LMT", [date(2026, 10, 22)], 9.0)                  # below_200d, earnings, heavily shorted: an eighth
    assert e["state"] == "WATCH" and e["size_factor"] == 0.125 and "quarter" in e["watch_reason"], e


def test_ceiling_cap_lifts_above_the_ceiling():
    _, e = last("INCY", [date(2026, 10, 27)], 1.0, 110.0)            # the close is above this level: no cap
    assert not e["ceiling_capped"] and e["state"] == "READY-HALF", e
    _, e = last("INCY", [date(2026, 10, 27)], 1.0, 140.0)            # 18% above: outside the 15% band, no cap
    assert not e["ceiling_capped"]


def test_incyte_long_range_ceiling_reference():
    """Section 3 reference: yearly peaks $131.50 (Sept 2015, then -28%) and $129.93 (July 2026, then -12% so far) set a
    ceiling near $131.50, about 13% above the 5-Oct close of $114.13; the 2017 peak $152.66 is the all-time high."""
    import long_range as lr
    c = pd.read_csv(FX / "INCY_close_max_to_2026-10-05.csv", index_col=0, parse_dates=True)["close"]
    rec = lr.analyze(c, CFG, date(2026, 10, 5))
    ceil = es.nearest_ceiling(114.13, rec)
    assert [x["level"] for x in es.active_ceilings(rec)] == [ceil["level"]], "the lower INCY ceilings were all closed above since they formed"
    assert ceil and abs(ceil["level"] - 131.50) < 0.10, ceil
    dates = [p_["date"][:7] for p_ in ceil["pair"]]
    assert dates == ["2015-09", "2026-07"], dates
    assert ceil["pair"][0]["decline"] < -0.27 and -0.13 < ceil["pair"][1]["decline"] < -0.10, ceil["pair"]
    assert abs(rec["ath"]["close"] - 152.66) < 0.01 and rec["ath"]["date"].startswith("2017"), rec["ath"]
    assert abs(rec["high_5y"]["close"] - 129.93) < 0.01, rec["high_5y"]
    assert es.ceiling_capped(114.13, [x["level"] for x in rec["ceilings"]], CFG) is not None
    assert abs(114.13 / ceil["level"] - 1 + 0.132) < 0.005        # about 13% below


def test_lockheed_ceiling_broken_so_no_cap():
    """Lockheed's 2025 ceiling (yearly highs near $514) was closed above in January 2026: the cap is lifted, so its
    state stays READY-HALF (acceptance 2) and no ceiling flag is shown."""
    import long_range as lr
    c = pd.read_csv(FX / "LMT_close_max_to_2026-10-05.csv", index_col=0, parse_dates=True)["close"]
    rec = lr.analyze(c, CFG, date(2026, 10, 5))
    assert any(x["broken"] for x in rec["ceilings"]), rec["ceilings"]
    act = es.active_ceilings(rec)
    assert es.ceiling_capped(506.63, [x["level"] for x in act], CFG) is None, act
    _, e = last("LMT", [date(2026, 10, 22)], 2.26, [x["level"] for x in act])
    assert e["state"] == "READY-HALF", e


def test_states_are_from_the_allowed_set():
    ev = es.evaluate(es.indicators(load("INCY"), CFG).iloc[-120:], CFG, [date(2026, 10, 27)], 7.62, 131.5)
    assert set(ev["state"].dropna()) <= set(es.STATES)


if __name__ == "__main__":
    for fn in [test_config_is_version_3_and_earlier_versions_are_kept, test_lockheed_ready_half_below_200d, test_micron_ready_at_full_size,
               test_powell_ready_half_size_below_200d, test_ondas_avoid_and_heavily_shorted_by_float, test_no_wait_state_extended_names_are_ready,
               test_incyte_watch_under_its_ceiling, test_tpl_heavily_shorted, test_trend_gate_fails_only_below_200d_with_negative_momentum,
               test_no_200d_floor_on_the_stop, test_quarter_floor_turns_three_modifiers_into_watch, test_ceiling_cap_lifts_above_the_ceiling,
               test_incyte_long_range_ceiling_reference, test_lockheed_ceiling_broken_so_no_cap, test_states_are_from_the_allowed_set]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
