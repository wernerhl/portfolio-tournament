#!/usr/bin/env python3
"""
tests/test_calendar_checks.py — order 1-Oct-2026 item R6: the referee check calendar:treasury_source
(scripts/calendar_checks.py). Mutation tests: the check clears on the correct calendar, fires CRITICAL
on a misdated or missing announced coupon auction, HIGH on an unsourced TREASURY / REFUNDING event,
HIGH on a tentative auction past its announcement date, and reports a failed TA_WS fetch (MEDIUM with
a fresh cached list, HIGH without one) instead of passing silently. Fixtures only; nothing is fetched
and nothing under data/ is written.

    .venv/bin/python tests/test_calendar_checks.py
"""
from __future__ import annotations
import copy
import json
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import calendar_checks as cc  # noqa: E402
import build_event_calendar as bec  # noqa: E402
from test_event_calendar import _fixture_inputs  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "treasury"
TODAY = "2026-10-01"
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


def announced():
    return cc.normalize_ta_ws(json.load(open(FIX / "ta_ws_upcoming_2026-10-01.json")))


def correct_calendar():
    return {"events": bec.build_events([], _fixture_inputs(), today=TODAY)}


def sev(findings):
    return [s for s, _, _ in findings]


def test_clears_on_the_correct_calendar():
    f = cc.check_treasury_source(correct_calendar(), announced(), today=TODAY, fetch_status={"source": "live"})
    assert f == [], f


def test_accepts_raw_ta_ws_records():
    raw = json.load(open(FIX / "ta_ws_upcoming_2026-10-01.json"))
    assert cc.check_treasury_source(correct_calendar(), raw, today=TODAY) == []


def test_critical_on_a_misdated_announced_auction():
    cal = correct_calendar()
    for e in cal["events"]:
        if e["type"] == "TREASURY" and e["date"] == "2026-10-07":
            e["date"] = "2026-10-14"            # the generator's date for the 10Y
    f = cc.check_treasury_source(cal, announced(), today=TODAY)
    crit = [d for s, c, d in f if s == "CRITICAL"]
    assert len(crit) == 1 and "misdated" in crit[0] and "2026-10-07" in crit[0] and "2026-10-14" in crit[0], f
    assert all(c == "calendar:treasury_source" for _, c, _ in f)


def test_critical_on_a_missing_announced_auction():
    cal = correct_calendar()
    cal["events"] = [e for e in cal["events"] if not (e["type"] == "TREASURY" and e["date"] == "2026-10-08")]
    f = cc.check_treasury_source(cal, announced(), today=TODAY)
    crit = [d for s, c, d in f if s == "CRITICAL"]
    assert len(crit) == 1 and "missing" in crit[0] and "30Y reopening auction 2026-10-08" in crit[0], f


def test_critical_on_the_old_generator_calendar():
    """The published calendar before R6 (3Y/10Y/30Y on 10-13/14/15, pattern provenance)."""
    import subprocess
    try:
        old = json.loads(subprocess.run(["git", "-C", str(REPO), "show", "2082b01:data/event_calendar.json"],
                                        capture_output=True, text=True, check=True).stdout)
    except Exception:  # noqa: BLE001 — no git history available: skip
        return
    f = cc.check_treasury_source(old, announced(), today=TODAY)
    assert sev(f).count("CRITICAL") == 3, f                         # all three announced auctions misdated
    assert any(s == "HIGH" and "sourced provenance" in d for s, _, d in f), f


def test_critical_on_a_tentative_entry_left_beside_the_announced_date():
    cal = correct_calendar()
    cal["events"].append({"date": "2026-10-13", "type": "TREASURY", "label": "3Y", "tenor": "3Y", "tentative": True,
                          "announcement_date": "2026-10-08", "source_url": "https://home.treasury.gov/x.xml",
                          "retrieved_at": TODAY, "provenance": "tentative (test)", "impact": "low"})
    f = cc.check_treasury_source(cal, announced(), today=TODAY)
    assert any(s == "CRITICAL" and "not replaced" in d for s, _, d in f), f


def test_high_on_an_unsourced_treasury_event():
    cal = correct_calendar()
    e = next(x for x in cal["events"] if x["type"] == "TREASURY" and x["date"] == "2026-10-26")
    e["provenance"] = "refunding pattern (2nd-Wed anchor)"
    f = cc.check_treasury_source(cal, announced(), today=TODAY)
    assert sev(f) == ["HIGH"] and "lack a sourced provenance" in f[0][2] and "2026-10-26" in f[0][2], f
    for mutate in ({"source_url": "https://www.treasurydirect.gov/auctions/upcoming/"}, {"retrieved_at": None},
                   {"tentative": None}, {"source_url": "https://www.treasurydirect.gov/TA_WS/securities/upcoming?format=json"}):
        cal = correct_calendar()
        e = next(x for x in cal["events"] if x["type"] == "TREASURY" and x["date"] == "2026-10-26")   # a tentative row
        e.update(mutate)
        f = cc.check_treasury_source(cal, announced(), today=TODAY)
        assert sev(f) == ["HIGH"], (mutate, f)


def test_high_on_an_unsourced_refunding_event():
    cal = correct_calendar()
    e = next(x for x in cal["events"] if x["type"] == "REFUNDING" and x["date"] == "2026-11-04")
    e["source_url"] = "https://example.org/inferred"
    f = cc.check_treasury_source(cal, announced(), today=TODAY)
    assert sev(f) == ["HIGH"] and "REFUNDING" in f[0][2], f


def test_high_on_an_announced_auction_still_flagged_tentative():
    cal = correct_calendar()
    e = next(x for x in cal["events"] if x["type"] == "TREASURY" and x["date"] == "2026-10-06")
    e["tentative"] = True
    f = cc.check_treasury_source(cal, announced(), today=TODAY)
    assert "CRITICAL" not in sev(f) and any("still flagged tentative" in d for _, _, d in f), f


def test_high_on_a_tentative_auction_past_its_announcement_date():
    cal = correct_calendar()
    # on 2026-10-16 the 20Y reopening (announcement 10-15) and the 5Y TIPS (10-15) should have been announced
    f = cc.check_treasury_source(cal, announced(), today="2026-10-16")
    hi = [d for s, _, d in f if s == "HIGH"]
    assert len(hi) == 1 and "2 tentative" in hi[0] and "2026-10-21" in hi[0] and "2026-10-22" in hi[0], f
    # without an announcement date: within 7 days of the auction
    cal2 = copy.deepcopy(cal)
    for e in cal2["events"]:
        e.pop("announcement_date", None)
    f2 = cc.check_treasury_source(cal2, announced(), today="2026-10-15")
    assert any(s == "HIGH" and "2026-10-21" in d for s, _, d in f2), f2


def test_fetch_failure_is_reported_not_silent():
    cal = correct_calendar()
    f = cc.check_treasury_source(cal, announced(), today=TODAY,
                                 fetch_status={"source": "cache", "retrieved_at": "2026-09-29", "error": "URLError: timed out"})
    assert sev(f) == ["MEDIUM"] and "fetch failed" in f[0][2], f
    f = cc.check_treasury_source(cal, announced(), today=TODAY,
                                 fetch_status={"source": "cache", "retrieved_at": "2026-09-01", "error": "URLError"})
    assert sev(f) == ["HIGH"] and "unverified" in f[0][2], f
    f = cc.check_treasury_source(cal, [], today=TODAY, fetch_status={"source": "none", "retrieved_at": None, "error": "URLError"})
    assert sev(f) == ["HIGH"] and "no cached" in f[0][2], f


def test_loader_falls_back_to_the_cached_list(tmp=Path("/private/tmp") if Path("/private/tmp").exists() else Path("/tmp")):
    import tempfile
    def boom(_timeout):
        raise OSError("network down (test)")
    with tempfile.TemporaryDirectory(dir=str(tmp)) as d:
        p = Path(d) / "event_calendar.json"
        json.dump({"events": [], "treasury_sources": {"ta_ws_upcoming": {"retrieved_at": "2026-09-30", "items": announced()}}}, open(p, "w"))
        ann, st = cc.load_announced(p, fetch=boom)
        assert st["source"] == "cache" and st["retrieved_at"] == "2026-09-30" and "network down" in st["error"] and len(ann) == 3, st
        ann, st = cc.load_announced(Path(d) / "absent.json", fetch=boom)
        assert ann == [] and st["source"] == "none", st
        ann, st = cc.load_announced(p, fetch=lambda _t: json.load(open(FIX / "ta_ws_upcoming_2026-10-01.json")))
        assert st["source"] == "live" and [a["tenor"] for a in ann] == ["3Y", "10Y", "30Y"], (st, ann)


if __name__ == "__main__":
    for fn in [test_clears_on_the_correct_calendar, test_accepts_raw_ta_ws_records, test_critical_on_a_misdated_announced_auction,
               test_critical_on_a_missing_announced_auction, test_critical_on_the_old_generator_calendar,
               test_critical_on_a_tentative_entry_left_beside_the_announced_date, test_high_on_an_unsourced_treasury_event,
               test_high_on_an_unsourced_refunding_event, test_high_on_an_announced_auction_still_flagged_tentative,
               test_high_on_a_tentative_auction_past_its_announcement_date, test_fetch_failure_is_reported_not_silent,
               test_loader_falls_back_to_the_cached_list]:
        run(fn)
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
