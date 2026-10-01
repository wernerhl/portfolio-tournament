#!/usr/bin/env python3
"""
tests/test_event_calendar.py — order 30-Sept-2026 item A2: calendar coverage, anchors, impact
levels and the cluster detector; order 1-Oct-2026 item R6: Treasury auctions from TreasuryDirect
TA_WS and the tentative auction schedule, the REFUNDING type, the R6.4 hard assert. Pure functions
of scripts/build_event_calendar.py on fixtures under tests/fixtures/treasury/ (nothing is fetched);
nothing under data/ is written.

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


# ── R6 (order 1-Oct-2026): Treasury auctions from the source ────────────
FIX = REPO / "tests" / "fixtures" / "treasury"


def _fixture_inputs(announced=None, auctioned=None):
    import json
    inp = bec.offline_treasury_inputs({})
    inp["announced"] = bec.cc.normalize_ta_ws(json.load(open(FIX / "ta_ws_upcoming_2026-10-01.json"))) if announced is None else announced
    inp["auctioned"] = auctioned or []
    tent = bec.parse_tentative_xml(open(FIX / "TentativeAuctionScheduleQ32026.xml", "rb").read())
    tent.update({"url": "https://home.treasury.gov/system/files/221/TentativeAuctionScheduleQ32026.xml", "retrieved_at": "2026-10-01"})
    inp["tentative"] = tent
    ref = bec.parse_refunding_page(open(FIX / "refunding_documents_2026-10-01.html").read())
    inp["refunding"] = {"retrieved_at": "2026-10-01", "latest": ref["latest"], "next": ref["next"]}
    return inp


def test_r6_no_weekday_generator_and_the_announced_dates():
    ev = bec.build_events([], _fixture_inputs(), today="2026-10-01")
    tsy = [e for e in ev if e["type"] == "TREASURY"]
    have = {(e["date"], e["label"]) for e in tsy}
    # TA_WS on 1 Oct: 3Y 10-06, 10Y reopening 10-07, 30Y reopening 10-08 — announced, not tentative
    for d, lbl in [("2026-10-06", "3Y"), ("2026-10-07", "10Y reopening"), ("2026-10-08", "30Y reopening")]:
        assert (d, lbl) in have, (d, lbl)
        e = next(x for x in tsy if x["date"] == d)
        assert e["tentative"] is False and e["status"] == "announced" and e["cusip"], e
    # the generator's dates are gone (10-13/14/15; 11-11 is Veterans Day)
    assert not [e for e in tsy if e["date"] in ("2026-10-13", "2026-10-14", "2026-10-15", "2026-11-11")], \
        [(e["date"], e["label"]) for e in tsy if e["date"] in ("2026-10-13", "2026-10-14", "2026-10-15", "2026-11-11")]
    # the auctions the generator never carried, from the tentative schedule
    for d, lbl in [("2026-10-21", "20Y reopening"), ("2026-10-22", "TIPS 5Y"), ("2026-10-26", "2Y"), ("2026-10-27", "5Y"),
                   ("2026-10-29", "7Y"), ("2026-11-09", "3Y"), ("2026-11-10", "10Y"), ("2026-11-12", "30Y")]:
        assert (d, lbl) in have, (d, lbl)
        assert next(x for x in tsy if x["date"] == d and x["label"] == lbl)["tentative"] is True
    for e in tsy:
        assert "pattern" not in e["provenance"] and e["source_url"].startswith(("https://www.treasurydirect.gov/TA_WS/", "https://home.treasury.gov/")), e
        assert e["impact"] == "low" and e["time_et"] in ("13:00", "11:30"), e
    bec.hard_asserts(ev, _fixture_inputs()["announced"])


def test_r6_announced_date_replaces_the_tentative_one():
    # TA_WS announces the November 3Y on 11-10 instead of the tentative 11-09: the announced date wins
    ann = _fixture_inputs()["announced"] + [{"date": "2026-11-10", "tenor": "3Y", "tips": False, "reopening": False,
                                             "security_type": "Note", "security_term": "3-Year", "original_term": "3-Year",
                                             "cusip": "TEST3Y001", "announcement_date": "2026-11-04", "time_et": "13:00"}]
    ev = bec.build_events([], _fixture_inputs(announced=ann), today="2026-11-05")
    threes = [(e["date"], e["status"]) for e in ev if e["type"] == "TREASURY" and e["tenor"] == "3Y" and e["date"].startswith("2026-11")]
    assert threes == [("2026-11-10", "announced")], threes


def test_r6_tentative_rows_before_today_are_dropped_and_held_auctions_kept():
    held = [{"date": "2026-09-08", "tenor": "3Y", "tips": False, "reopening": False, "security_type": "Note",
             "security_term": "3-Year", "original_term": "3-Year", "cusip": "TESTCUSIP1", "announcement_date": "2026-09-03",
             "time_et": "13:00"}]
    ev = bec.build_events([], _fixture_inputs(auctioned=held), today="2026-10-01")
    sept = [(e["date"], e["label"], e["status"]) for e in ev if e["type"] == "TREASURY" and e["date"].startswith("2026-09")]
    assert sept == [("2026-09-08", "3Y", "auctioned")], sept      # tentative Sept rows dropped; the held one kept
    e = next(x for x in ev if x["type"] == "TREASURY" and x["date"] == "2026-09-08")
    assert "cusip=TESTCUSIP1" in e["source_url"] and e["tentative"] is False


def test_r6_announced_auction_kept_while_the_record_lags():
    # evening of 10-06: the 3Y has left `upcoming` but is not yet in the auction record
    prev = {"events": bec.build_events([], _fixture_inputs(), today="2026-10-01")}
    inp = _fixture_inputs(announced=[a for a in _fixture_inputs()["announced"] if a["date"] != "2026-10-06"])
    inp["announced_prev"] = bec.offline_treasury_inputs(prev)["announced_prev"]
    ev = bec.build_events([], inp, today="2026-10-06", existing_events=prev["events"])
    e = [x for x in ev if x["type"] == "TREASURY" and x["tenor"] == "3Y" and x["date"].startswith("2026-10")]
    assert [(x["date"], x["status"]) for x in e] == [("2026-10-06", "announced")], e


def test_r6_coupon_filter_and_series():
    import json
    raw = json.load(open(FIX / "ta_ws_upcoming_2026-10-01.json"))
    got = bec.cc.normalize_ta_ws(raw)
    assert [(a["date"], a["tenor"], a["reopening"]) for a in got] == [
        ("2026-10-06", "3Y", False), ("2026-10-07", "10Y", True), ("2026-10-08", "30Y", True)], got   # 5 bills dropped
    extra = [{"securityType": "Note", "type": "FRN", "floatingRate": "Yes", "securityTerm": "2-Year", "auctionDate": "2026-10-28T00:00:00", "cusip": "F"},
             {"securityType": "Bill", "type": "Bill", "securityTerm": "13-Week", "auctionDate": "2026-10-05T00:00:00", "cusip": "B"},
             {"securityType": "Note", "type": "TIPS", "tips": "Yes", "securityTerm": "4-Year 10-Month", "originalSecurityTerm": "5-Year",
              "reopening": "Yes", "auctionDate": "2026-12-22T00:00:00", "cusip": "T5"},
             {"securityType": "Note", "type": "Note", "securityTerm": "2-Year", "originalSecurityTerm": "5-Year", "reopening": "Yes",
              "auctionDate": "2026-01-26T00:00:00", "cusip": "R2", "closingTimeCompetitive": "11:30 AM"}]
    got = {a["cusip"]: a for a in bec.cc.normalize_ta_ws(extra)}
    assert set(got) == {"T5", "R2"}, got                            # FRN and bill excluded
    assert got["T5"]["tenor"] == "TIPS 5Y" and got["T5"]["reopening"] is True
    assert got["R2"]["tenor"] == "2Y" and got["R2"]["time_et"] == "11:30"   # a 2-year auctioned as a reopening of a 5-year


def test_r6_hard_assert_fires_on_a_missing_announced_auction():
    ev = bec.build_events([], _fixture_inputs(), today="2026-10-01")
    ev = [e for e in ev if not (e["type"] == "TREASURY" and e["date"] == "2026-10-07")]
    try:
        bec.hard_asserts(ev, _fixture_inputs()["announced"])
    except AssertionError as e:
        assert "2026-10-07" in str(e), e
    else:
        raise AssertionError("hard_asserts passed with the announced 10Y reopening removed")


def test_r6_refunding_from_the_page():
    ref = bec.parse_refunding_page(open(FIX / "refunding_documents_2026-10-01.html").read())
    assert ref == {"latest": "2026-08-05", "next": "2026-11-04",
                   "xml_url": "https://home.treasury.gov/system/files/221/TentativeAuctionScheduleQ32026.xml"}, ref
    ev = bec.build_events([], _fixture_inputs(), today="2026-10-01")
    r = [e for e in ev if e["type"] == "REFUNDING"]
    assert [(e["date"], e["impact"], e["time_et"]) for e in r] == [("2026-08-05", "medium", "08:30"), ("2026-11-04", "medium", "08:30")], r
    assert bec.IMPACT["REFUNDING"] == "medium" and bec.IMPACT["TREASURY"] == "low"
    # a past refunding is kept across rebuilds once the page has moved on
    ev2 = bec.build_events([], dict(_fixture_inputs(), refunding={"retrieved_at": "2026-11-05", "latest": "2026-11-04", "next": "2027-02-03"}),
                           today="2026-11-05", existing_events=ev)
    assert [e["date"] for e in ev2 if e["type"] == "REFUNDING"] == ["2026-08-05", "2026-11-04", "2027-02-03"]


def test_r6_snapshot_matches_the_official_xml():
    x = bec.parse_tentative_xml(open(FIX / "TentativeAuctionScheduleQ32026.xml", "rb").read())
    assert x["rows"] == sorted(bec.TENTATIVE_SNAPSHOT["rows"]) and len(x["rows"]) == 48
    assert x["name"] == bec.TENTATIVE_SNAPSHOT["name"] and x["end"] == bec.TENTATIVE_SNAPSHOT["end"]


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
    # R6: no TREASURY entry from a weekday pattern; the source block is served
    assert not [e for e in cal["events"] if e["type"] == "TREASURY" and "pattern" in str(e.get("provenance", ""))]
    assert "treasury_sources" in cal and isinstance(cal["treasury_sources"]["ta_ws_upcoming"].get("items"), list)


if __name__ == "__main__":
    for fn in [test_anchors_of_the_order, test_every_event_has_provenance_and_impact, test_opex_third_friday_and_quarterly_flag,
               test_claims_thursdays_with_holiday_shift, test_ism_business_day_rule, test_cluster_detector_on_constructed_events,
               test_earnings_preserved_and_impact_by_holding, test_r6_no_weekday_generator_and_the_announced_dates,
               test_r6_announced_date_replaces_the_tentative_one, test_r6_tentative_rows_before_today_are_dropped_and_held_auctions_kept,
               test_r6_announced_auction_kept_while_the_record_lags, test_r6_coupon_filter_and_series,
               test_r6_hard_assert_fires_on_a_missing_announced_auction,
               test_r6_refunding_from_the_page, test_r6_snapshot_matches_the_official_xml,
               test_live_calendar_file_carries_the_anchors_and_clusters]:
        run(fn)
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
