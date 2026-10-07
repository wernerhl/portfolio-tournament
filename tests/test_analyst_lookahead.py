#!/usr/bin/env python3
"""
tests/test_analyst_lookahead.py — the look-ahead checks of the free-analyst-data order (7 October 2026, section D3),
as unit tests on the builders:

  1. a rating row with a timestamp after the month-end's close does not enter that month's variables (a planted
     future row leaves every variable unchanged); a row at 15:59 ET on the month-end does enter
  2. an earnings report at or after 16:00 ET is effective the next trading day, so it does not count at that day's
     month-end; a report before the open counts the same day
  3. dollar volume uses split-adjusted closes only (a dividend changes the adjusted close, not the dollar volume)
  4. the placebo shift puts the value observed 12 months later (or earlier) on month t
  5. ranks are computed within the members given to the builder; a non-member cannot change a member's rank, and
     the builder reads no membership list of its own (it takes the member flag as an argument)
  6. a price target from before a split is brought to the share basis of the month-end

    .venv/bin/python tests/test_analyst_lookahead.py
"""
from __future__ import annotations
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "scripts" / "analyst"))
import build_panel as bp          # noqa: E402
import fetch_history as fh        # noqa: E402
import walkforward_test as wf     # noqa: E402

RESULTS = []
T = pd.Timestamp("2025-06-30")                      # a Monday month-end


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def ratings(rows):
    df = pd.DataFrame(rows, columns=["ts_et", "action", "pt_current", "pt_prior"])
    df["ts_et"] = pd.to_datetime(df["ts_et"])
    return df


NO_SPLITS = pd.DataFrame(columns=["ticker", "date", "ratio"])


def test_future_rating_row_does_not_enter_the_month():
    base = ratings([("2025-05-15 10:00", "up", 120.0, 100.0), ("2025-06-10 09:00", "down", 90.0, 110.0), ("2025-06-30 15:59", "up", 130.0, 100.0)])
    a = bp.month_variables("X", T, base, None, NO_SPLITS, 100.0)
    planted = pd.concat([base, ratings([("2025-06-30 16:01", "up", 200.0, 100.0), ("2025-07-01 09:00", "up", 250.0, 100.0)])], ignore_index=True)
    b = bp.month_variables("X", T, planted, None, NO_SPLITS, 100.0)
    for k in ("an_n_act_90", "an_net_up_90", "an_pt_rev_90", "an_pt_gap"):
        assert a.get(k) == b.get(k), (k, a.get(k), b.get(k))
    assert a["an_n_act_90"] == 3 and abs(a["an_net_up_90"] - (2 - 1) / 3) < 1e-12, a
    assert abs(a["an_pt_gap"] - (np.median([120.0, 90.0, 130.0]) / 100.0 - 1)) < 1e-12, a["an_pt_gap"]


def test_rating_rows_outside_the_90_day_window_are_out():
    df = ratings([("2025-03-31 10:00", "up", 120.0, 100.0), ("2025-04-02 10:00", "down", 90.0, 100.0)])   # 91 and 89 days before
    r = bp.month_variables("X", T, df, None, NO_SPLITS, 100.0)
    assert r["an_n_act_90"] == 1 and r["n_down_90"] == 1 and r["an_net_up_90"] == -1.0, r


def test_after_close_report_counts_next_trading_day():
    e = pd.DataFrame({"ticker": "X", "earnings_date_et": pd.to_datetime(["2025-03-27 08:00", "2025-06-30 16:05"]),
                      "eps_estimate": [1.0, 1.0], "reported_eps": [1.2, 2.0], "surprise_pct": [20.0, 100.0]})
    e = bp.effective_dates(e)
    assert str(e["effective"].iloc[1].date()) == "2025-07-01", e["effective"].tolist()     # after the close: next session
    assert str(e["effective"].iloc[0].date()) == "2025-03-27"
    r = bp.month_variables("X", T, None, e, NO_SPLITS, 100.0)
    assert r["an_surprise"] == 20.0 and str(r["last_report"].date()) == "2025-03-27", r      # the 30-June report is not in June
    r2 = bp.month_variables("X", pd.Timestamp("2025-07-31"), None, e, NO_SPLITS, 100.0)
    assert r2["an_surprise"] == 100.0, r2
    # a row without a reported EPS never counts: the latest report falls back to March, 126 days before the July
    # month-end, outside the 100-day window, so no surprise is carried
    e3 = e.copy(); e3.loc[1, "reported_eps"] = np.nan
    r3 = bp.month_variables("X", pd.Timestamp("2025-07-31"), None, e3, NO_SPLITS, 100.0)
    assert "an_surprise" not in r3 and str(r3["last_report"].date()) == "2025-03-27" and r3["last_report_age_days"] == 126, r3


def test_dollar_volume_uses_split_adjusted_close_only():
    idx = pd.bdate_range("2025-01-02", periods=45)
    h = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Adj Close": 90.0, "Volume": 1000.0,
                      "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)
    _, m = fh.history_frames("X", h)
    assert np.allclose(m["dollar_volume_20"].dropna(), 100.0 * 1000.0), m["dollar_volume_20"].tolist()   # not 90 x 1000
    assert np.allclose(m["adj_close"], 90.0) and np.allclose(m["close"], 100.0)


def test_placebo_shift_moves_the_future_value_onto_t():
    an = pd.DataFrame({"p": pd.period_range("2024-01", "2025-12", freq="M"), "ticker": "X", "an_sue": np.arange(24, dtype=float)})
    fut = wf.shift_analyst_frame(an, 12)
    v = fut[(fut["p"] == pd.Period("2024-06", freq="M"))]["an_sue"].iloc[0]
    assert v == an[an["p"] == pd.Period("2025-06", freq="M")]["an_sue"].iloc[0], v          # June 2025's value sits on June 2024
    past = wf.shift_analyst_frame(an, -12)
    v2 = past[(past["p"] == pd.Period("2025-06", freq="M"))]["an_sue"].iloc[0]
    assert v2 == an[an["p"] == pd.Period("2024-06", freq="M")]["an_sue"].iloc[0], v2
    assert wf.shift_analyst_frame(an, 0) is an


def test_ranks_within_members_only():
    vals = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0], index=list("abcde"))
    member = pd.Series([True, True, True, True, False], index=list("abcde"))
    rk = bp.rank_scaled(vals, member)
    assert rk["a"] == -0.5 and rk["d"] == 0.5 and abs(rk["b"] - (-0.5 + 1 / 3)) < 1e-12, rk.to_dict()
    assert rk["e"] == 0.5, rk["e"]                                   # placed within the members' distribution, not above it
    rk2 = bp.rank_scaled(vals, pd.Series([True] * 5, index=list("abcde")))
    assert rk2["d"] == 0.25 and rk2["e"] == 0.5                      # the same name ranks differently once it is a member
    import inspect
    src = inspect.getsource(bp.month_variables) + inspect.getsource(bp.rank_scaled)
    assert "universe.txt" not in src and "universe_meta" not in src   # the builders take the member flag; they read no current list


def test_price_target_before_a_split_is_rebased():
    splits = pd.DataFrame({"ticker": ["X"], "date": [pd.Timestamp("2025-06-10")], "ratio": [10.0]})
    df = ratings([("2025-05-20 10:00", "up", 1000.0, 900.0), ("2025-06-20 10:00", "main", 110.0, 100.0)])   # 1000 pre-split = 100 post
    r = bp.month_variables("X", T, df, None, splits, 100.0)
    assert abs(r["pt_median_90"] - np.median([100.0, 110.0])) < 1e-9, r["pt_median_90"]
    assert abs(r["an_pt_gap"] - (105.0 / 100.0 - 1)) < 1e-9, r["an_pt_gap"]
    # a split after t rebases the close at t to its nominal basis instead
    later = pd.DataFrame({"ticker": ["X"], "date": [pd.Timestamp("2025-07-10")], "ratio": [2.0]})
    r2 = bp.month_variables("X", T, ratings([("2025-06-20 10:00", "up", 220.0, 200.0)]), None, later, 100.0)
    assert abs(r2["price_nominal"] - 200.0) < 1e-9 and abs(r2["an_pt_gap"] - (220.0 / 200.0 - 1)) < 1e-9, r2


if __name__ == "__main__":
    for fn in [test_future_rating_row_does_not_enter_the_month, test_rating_rows_outside_the_90_day_window_are_out,
               test_after_close_report_counts_next_trading_day, test_dollar_volume_uses_split_adjusted_close_only,
               test_placebo_shift_moves_the_future_value_onto_t, test_ranks_within_members_only, test_price_target_before_a_split_is_rebased]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
