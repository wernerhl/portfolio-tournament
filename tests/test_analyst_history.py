#!/usr/bin/env python3
"""
tests/test_analyst_history.py — acceptance checks on the raw analyst history (free-analyst-data order, 7 October
2026, section 10) against the latest download in data/analyst/history/:

  - MU has at least 890 rating rows starting in 2012; LMT at least 300
  - MU's earnings rows start in 2002 and include the report of 30 September 2026 with estimate 31.82 and reported 33.42
  - the raw files are never rewritten: every file name carries its download date and the meta file records the run
  - the derived month-end table carries split-adjusted and dividend-adjusted closes and a dollar volume built on the
    split-adjusted close

    .venv/bin/python tests/test_analyst_history.py
"""
from __future__ import annotations
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "analyst" / "history"
RESULTS = []
sys.path.insert(0, str(REPO / "scripts" / "analyst"))
import build_panel as bp   # noqa: E402  (read_all: the union of every download, the latest per name)


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def stamp() -> str:
    st = sorted(p.name[len("upgrades_downgrades_"):-len(".parquet")] for p in HIST.glob("upgrades_downgrades_*.parquet"))
    assert st, "no raw history downloaded"
    return st[-1]


def test_mu_and_lmt_rating_rows():
    r = bp.read_all("upgrades_downgrades", bp.all_stamps())
    mu = r[r["ticker"] == "MU"]; lmt = r[r["ticker"] == "LMT"]
    assert len(mu) >= 890 and mu["grade_date_utc"].min().year == 2012, (len(mu), mu["grade_date_utc"].min())
    assert len(lmt) >= 300, len(lmt)
    assert {"firm", "to_grade", "from_grade", "action", "pt_action", "pt_current", "pt_prior"} <= set(r.columns)


def test_mu_earnings_rows():
    e = bp.read_all("earnings_dates", bp.all_stamps())
    mu = e[e["ticker"] == "MU"].sort_values("earnings_date_et")
    assert mu["earnings_date_et"].min().year == 2002, mu["earnings_date_et"].min()
    row = mu[mu["earnings_date_et"].dt.strftime("%Y-%m-%d") == "2026-09-30"]
    assert len(row) == 1 and abs(row["eps_estimate"].iloc[0] - 31.82) < 1e-9 and abs(row["reported_eps"].iloc[0] - 33.42) < 1e-9, row


def test_raw_files_are_dated_and_described():
    for s in bp.all_stamps():
        for n in ("upgrades_downgrades", "earnings_dates", "splits", "monthly_prices"):
            assert (HIST / f"{n}_{s}.parquet").exists(), (n, s)
        m = json.loads((HIST / f"_meta_{s}.json").read_text())
        assert m["downloaded_on"] == s and m["rate"].startswith("at most one request per second") and m["requests"] > 0
        assert "never rewritten" in m["task"]


def test_monthly_table_columns():
    m = bp.read_all("monthly_prices", bp.all_stamps())
    assert {"ticker", "month_end", "close", "adj_close", "dollar_volume_20", "sessions"} <= set(m.columns)
    lmt = m[m["ticker"] == "LMT"].sort_values("month_end")
    assert lmt["month_end"].min().year <= 1990 and lmt["dollar_volume_20"].notna().mean() > 0.9


if __name__ == "__main__":
    for fn in [test_mu_and_lmt_rating_rows, test_mu_earnings_rows, test_raw_files_are_dated_and_described, test_monthly_table_columns]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
