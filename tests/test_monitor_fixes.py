#!/usr/bin/env python3
"""
tests/test_monitor_fixes.py — the referee fixes of 4 November 2026. Fixtures and fakes only: nothing is fetched,
nothing under data/ is written.

  R1  fetch_global_rates.fred(): the FRED API is used when FRED_API_KEY is set; the key never reaches the stored
      URL or an error message; a CSV timeout stops the later series from waiting on the CSV again
  I1  compute_intraday: the vol complex's prior close is the canonical close when the canonical file holds the
      previous session (vix_prior equals it; vix_change_pct measures from it); otherwise the provider's prior
  I2  compute_intraday: VVIX is published at the top level (the referee's nullguard reads intraday.vvix)
  U1  build_universe: a retired name leaves the union, a held retired name stays
  A1  audit_alerts: report parsing, first_seen carried across runs, age in sessions, dropped checks forgotten

    .venv/bin/python tests/test_monitor_fixes.py
"""
from __future__ import annotations
import importlib
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "rates"))
RESULTS = []


def check(name, fn):
    try:
        fn(); RESULTS.append((name, True)); print(f"PASS  {name}")
    except Exception:  # noqa: BLE001
        RESULTS.append((name, False)); print(f"FAIL  {name}"); traceback.print_exc()


# ── R1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def r1_api_first_and_redaction():
    import fetch_global_rates as f
    f = importlib.reload(f)
    calls = []

    def fake_get(url, timeout=90):
        calls.append(url)
        if "api.stlouisfed.org" in url:
            return json.dumps({"observations": [{"date": "2026-11-02", "value": "3.61"},
                                                {"date": "2026-11-03", "value": "."}]}).encode()
        raise AssertionError("the CSV endpoint must not be called when the API answers")
    f.get = fake_get
    os.environ["FRED_API_KEY"] = "SECRET123"
    try:
        s, url = f.fred("DGS2")
    finally:
        del os.environ["FRED_API_KEY"]
    assert list(s.values) == [3.61], s                                   # "." is missing, not zero
    assert "SECRET123" not in url and "api.stlouisfed.org" in url, url   # the stored URL has no key
    assert any("api_key=SECRET123" in c for c in calls)


def r1_breaker():
    import fetch_global_rates as f
    f = importlib.reload(f)
    calls = []

    def dead(url, timeout=90):
        calls.append(url); raise TimeoutError(f"The read operation timed out ({url})")
    f.get = dead
    os.environ["FRED_API_KEY"] = "SECRET123"
    try:
        msgs = []
        for sid in ("DGS2", "DGS10", "DGS30"):
            try:
                f.fred(sid)
            except RuntimeError as e:
                msgs.append(str(e))
    finally:
        del os.environ["FRED_API_KEY"]
    assert len(msgs) == 3 and all("SECRET123" not in m for m in msgs), msgs
    assert sum("fredgraph" in c for c in calls) == 1, calls             # the CSV is tried once per run
    assert "skipped" in msgs[1] and "skipped" in msgs[2], msgs


def r1_keyless_uses_csv():
    import fetch_global_rates as f
    f = importlib.reload(f)
    os.environ.pop("FRED_API_KEY", None)
    f.get = lambda url, timeout=90: b"observation_date,DGS2\n2026-11-02,3.61\n2026-11-03,.\n"
    s, url = f.fred("DGS2")
    assert "fredgraph.csv" in url and list(s.values) == [3.61]


# ── I1 / I2 ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _run_intraday(canonical: dict, session: str):
    import compute_intraday as ci
    ci = importlib.reload(ci)
    px = {"vix": {"last": 18.57, "prior_close": 20.81}, "vix3m": {"last": 20.0, "prior_close": 21.2},
          "vvix": {"last": 90.67, "prior_close": 107.22}, "skew": {"last": 150.0, "prior_close": 150.0},
          "spx": {"last": 6000.0, "prior_close": 5990.0}, "hyg": {"last": 80.0, "prior_close": 80.0},
          "tlt": {"last": 90.0, "prior_close": 90.0}}
    written = {}
    with tempfile.TemporaryDirectory() as t:
        ci.DATA = Path(t)
        ci.fetch_intraday = lambda: json.loads(json.dumps(px))
        ci._load_canonical = lambda: canonical
        os.environ["NOW_ET_OVERRIDE"] = f"{session}T08:13"
        try:
            ci.main()
        finally:
            del os.environ["NOW_ET_OVERRIDE"]
        written = json.loads((Path(t) / "intraday.json").read_text())
    return written


def i1_canonical_prior():
    st = _run_intraday({"date": "2026-11-03", "session_date": "2026-11-03", "vix": 20.83, "vix3m": 21.27,
                        "vvix": 107.4, "skew": 150.01}, "2026-11-04")
    assert st["vix_prior"] == 20.83, st["vix_prior"]
    assert st["prices"]["vix"]["prior_close_provider"] == 20.81
    assert st["prices"]["vix"]["prior_source"] == "canonical close (2026-11-03)"
    assert abs(st["vix_change_pct"] - round((18.57 / 20.83 - 1) * 100, 1)) < 1e-9, st["vix_change_pct"]


def i1_stale_canonical_keeps_provider():
    st = _run_intraday({"date": "2026-10-30", "session_date": "2026-10-30", "vix": 19.0}, "2026-11-04")
    assert st["vix_prior"] == 20.81 and "prior_source" not in st["prices"]["vix"], st["prices"]["vix"]


def i2_vvix_top_level():
    st = _run_intraday({}, "2026-11-04")
    assert st["vvix"] == 90.67, st.get("vvix")


# ── U1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def u1_retired():
    import build_universe as bu
    bu = importlib.reload(bu)
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / "canonical").mkdir(); (d / "screen").mkdir()
        (d / "canonical" / "universe.txt").write_text("AAA\nBBB\nDEAD\nHELD\n")
        (d / "screen" / "universe_535.txt").write_text("AAA\nDEAD\n")
        cfg = d / "config.json"; cfg.write_text(json.dumps({"midcap_additions": ["CCC"]}))
        (d / "holdings.json").write_text(json.dumps({"as_of": "2026-11-03", "holdings": [{"ticker": "HELD", "shares": 1}]}))
        (d / "universe_retired.json").write_text(json.dumps({"cadence": "on_change", "names": {
            "DEAD": {"last_bar": "2026-08-01", "verified": False}, "HELD": {"last_bar": "2026-08-01", "verified": False}}}))
        bu.TOURNAMENT_UNIVERSE = d / "canonical" / "universe.txt"; bu.SCREENER_UNIVERSE = d / "screen" / "universe_535.txt"
        bu.SCREEN_CONFIG = cfg; bu.HOLDINGS = d / "holdings.json"; bu.RETIRED = d / "universe_retired.json"
        bu.OUT_UNIVERSE = d / "universe.txt"; bu.OUT_META = d / "universe_meta.json"
        bu.TICKER_CHANGES = d / "none.csv"; bu.DATA = d
        bu.main()
        assert (d / "universe.txt").read_text().split() == ["AAA", "BBB", "CCC", "HELD"]
        meta = json.loads((d / "universe_meta.json").read_text())
        assert [r["ticker"] for r in meta["retired"]] == ["DEAD"], meta["retired"]


# ── A1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
REPORT = """last trading session: {s}
[HIGH    ] rates:stale                  global-rates series older than their expected lag: ['us2: ...']
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed
[MEDIUM  ] v4:calibration_evaluation    not tracked
[INFO    ] site:session                 not tracked

3 findings; 0 CRITICAL
REFEREE COMPLETE: 5 findings; 0 CRITICAL
"""


def a1_state():
    import audit_alerts as aa
    aa = importlib.reload(aa)
    with tempfile.TemporaryDirectory() as t:
        rp = Path(t) / "r.txt"
        rp.write_text(REPORT.format(s="2026-10-20"))
        s1, f1 = aa.parse(rp)
        assert s1 == "2026-10-20" and set(f1) == {"rates:stale", "governance:review_overdue"}, f1
        assert len(f1["governance:review_overdue"]["details"]) == 2
        st1 = aa.update_state(s1, f1, {})
        rp.write_text(REPORT.format(s="2026-11-03").replace("[HIGH    ] rates:stale", "[INFO    ] rates:fine"))
        s2, f2 = aa.parse(rp)
        st2 = aa.update_state(s2, f2, st1)
        c = st2["checks"]
        assert "rates:stale" not in c                                      # gone from the report: forgotten
        r = c["governance:review_overdue"]
        assert r["first_seen"] == "2026-10-20" and r["last_seen"] == "2026-11-03", r
        assert r["age_sessions"] == 11, r                                  # 20-Oct .. 3-Nov: eleven sessions


if __name__ == "__main__":
    for n, fn in (("R1 FRED API first; the key never stored or printed", r1_api_first_and_redaction),
                  ("R1 a CSV timeout is not waited on again in the same run", r1_breaker),
                  ("R1 without a key the CSV download is used", r1_keyless_uses_csv),
                  ("I1 prior close of the vol complex = canonical close of the previous session", i1_canonical_prior),
                  ("I1 a canonical file of an older session leaves the provider's prior", i1_stale_canonical_keeps_provider),
                  ("I2 VVIX published at the top level", i2_vvix_top_level),
                  ("U1 retired names leave the union; held names stay", u1_retired),
                  ("A1 audit_alerts keeps first_seen and counts sessions", a1_state)):
        check(n, fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
