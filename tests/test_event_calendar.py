#!/usr/bin/env python3
"""
tests/test_event_calendar.py — order 30-Sept-2026 item A2: calendar coverage, anchors, impact
levels and the cluster detector. Pure functions of scripts/build_event_calendar.py; nothing under
data/ is written.

    .venv/bin/python tests/test_event_calendar.py
"""
from __future__ import annotations
import sys
import traceback
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import build_event_calendar as bec  # noqa: E402

RESULTS = []


def run(fn):
    try:
        fn()
        RESULTS.append((fn.__name__, True, ""))
        print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False, f"{type(e).__name__}: {e}"))
        print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
        traceback.print_exc()


def index(events):
    by = {}
    for e in events:
        by.setdefault((e["date"], e["type"]), []).append(e)
    return by


def test_anchors_of_the_order():
    ev = bec.build_events([])
    by = index(ev)
    for d, t in [("2026-09-30", "PCE"), ("2026-10-02", "NFP"), ("2026-10-14", "CPI"), ("2026-10-15", "PPI"),
                 ("2026-10-28", "FOMC"), ("2026-10-29", "PCE"), ("2026-11-03", "ELECTION"), ("2026-12-09", "FOMC")]:
        assert (d, t) in by, f"{t} {d} missing"
    bec.hard_asserts(ev)


def test_every_event_has_provenance_and_impact():
    for e in bec.build_events([]):
        assert e["source_url"] and e["retrieved_at"] and e["provenance"], e
        assert e["impact"] in ("high", "medium", "low"), e
        assert date.fromisoformat(e["date"]).weekday() < 5, e


def test_opex_third_friday_and_quarterly_flag():
    by = index(bec.build_events([]))
    for d in ("2026-10-16", "2026-11-20", "2026-12-18", "2027-03-19", "2027-06-17", "2027-09-17", "2027-12-17"):
        assert (d, "OPEX") in by, d          # 2027-06-18 is the observed Juneteenth holiday → Thursday 17th
    assert by[("2026-12-18", "OPEX")][0]["quarterly"] is True
    assert by[("2026-10-16", "OPEX")][0]["quarterly"] is False
    assert bec.third_friday_expiry(2026, 6) == date(2026, 6, 18)   # Juneteenth Friday → Thursday


def test_claims_thursdays_with_holiday_shift():
    by = index(bec.build_events([]))
    assert ("2026-10-01", "CLAIMS") in by and ("2026-10-08", "CLAIMS") in by
    assert ("2026-11-25", "CLAIMS") in by and ("2026-11-26", "CLAIMS") not in by   # Thanksgiving week → Wednesday
    assert all(e["impact"] == "low" for k, es in by.items() if k[1] == "CLAIMS" for e in es)


def test_ism_business_day_rule():
    by = index(bec.build_events([]))
    assert ("2026-10-01", "ISM_MFG") in by and ("2026-10-05", "ISM_SVC") in by
    assert ("2026-11-02", "ISM_MFG") in by and ("2026-11-04", "ISM_SVC") in by
    assert ("2026-12-01", "ISM_MFG") in by and ("2026-12-03", "ISM_SVC") in by
    assert ("2027-01-04", "ISM_MFG") in by and ("2027-01-06", "ISM_SVC") in by   # Jan 1 2027 is a Friday holiday


def test_cluster_detector_on_constructed_events():
    events = [
        {"date": "2026-10-28", "type": "FOMC", "label": "FOMC", "impact": "high"},
        {"date": "2026-10-28", "type": "EARNINGS", "label": "GEV", "ticker": "GEV", "impact": "high"},
        {"date": "2026-10-28", "type": "EARNINGS", "label": "XYZ", "ticker": "XYZ", "impact": "medium"},
        {"date": "2026-10-15", "type": "PPI", "label": "PPI", "impact": "medium"},          # medium → no cluster
        {"date": "2026-10-15", "type": "EARNINGS", "label": "NVDA", "ticker": "NVDA", "impact": "high"},
        {"date": "2026-12-09", "type": "FOMC", "label": "FOMC", "impact": "high"},
        {"date": "2026-12-09", "type": "EARNINGS", "label": "AVGO", "ticker": "AVGO", "impact": "high"},
        {"date": "2026-11-03", "type": "ELECTION", "label": "Election", "impact": "high"},    # no held earnings → none
    ]
    cl = bec.detect_clusters(events, {"GEV", "NVDA", "AVGO"})
    assert [c["date"] for c in cl] == ["2026-10-28", "2026-12-09"], cl
    assert cl[0]["earnings"] == ["GEV"] and cl[0]["macro"] == ["FOMC"]
    assert cl[1]["earnings"] == ["AVGO"]


def test_earnings_preserved_and_impact_by_holding():
    ex = [{"date": "2026-10-28", "type": "EARNINGS", "ticker": "GEV", "label": "GEV", "name": "Earnings · GEV",
           "source_url": "x", "retrieved_at": "2026-09-29", "provenance": "provider"}]
    ev = bec.build_events(ex)
    got = [e for e in ev if e["type"] == "EARNINGS"]
    assert len(got) == 1 and got[0]["impact"] in ("high", "medium")


def test_live_calendar_file_carries_the_anchors_and_clusters():
    import json
    p = REPO / "data" / "event_calendar.json"
    if not p.exists():
        return
    cal = json.load(open(p))
    by = index(cal["events"])
    for d, t in [("2026-09-30", "PCE"), ("2026-10-02", "NFP"), ("2026-10-14", "CPI"), ("2026-10-15", "PPI"),
                 ("2026-10-28", "FOMC"), ("2026-10-29", "PCE"), ("2026-11-03", "ELECTION")]:
        assert (d, t) in by, f"live file: {t} {d} missing"
    assert cal.get("version") == "3.0" and "clusters" in cal


if __name__ == "__main__":
    for fn in [test_anchors_of_the_order, test_every_event_has_provenance_and_impact, test_opex_third_friday_and_quarterly_flag,
               test_claims_thursdays_with_holiday_shift, test_ism_business_day_rule, test_cluster_detector_on_constructed_events,
               test_earnings_preserved_and_impact_by_holding, test_live_calendar_file_carries_the_anchors_and_clusters]:
        run(fn)
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
