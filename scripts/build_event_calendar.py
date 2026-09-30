"""
Generate data/event_calendar.json — scheduled macro events 2024-2027 (version 3.0).

AUDIT FIX 1 (2026-06-11): dates come from OFFICIAL release schedules, not inferred
weekday rules. The old "second Tuesday" CPI rule was wrong by a day (May-2026 CPI
released Wed 2026-06-10, not Tue 06-09), which mis-tagged spikes and contaminated the
event-day validation subsample.

ORDER 30-Sept-2026, item A2 — calendar coverage. The calendar held only NFP, CPI, FOMC,
Treasury auctions and earnings; today's PCE release was absent. Added, from the agencies'
published schedules, each event carrying its source URL, retrieval date and provenance:
  BEA   Personal Income and Outlays (PCE) and GDP releases      (bea.gov/news/schedule)
  BLS   PPI and JOLTS                                            (bls.gov/schedule/news_release/*)
  ISM   Manufacturing and Services PMI                           (release rule; see ISM note)
  Census Advance Monthly Retail Sales                            (census.gov economic-indicator calendar)
  DOL   weekly jobless claims, type CLAIMS, low impact           (Thursdays 08:30 ET; holiday shifts)
  the 3 November 2026 general election, type ELECTION            (2 U.S.C. §7; usa.gov; FEC)
  monthly options expirations and the quarterly expiry, type OPEX (Cboe 2026 expiration calendar)
Every event carries an `impact` level (high / medium / low). A CLUSTER is any session where a
macro event of impact high coincides with a held name's earnings (holdings.json); clusters are
written to the file and highlighted on the events board.

Sources retrieved 2026-06-11 (via web.archive.org snapshots) for CPI / NFP / FOMC 2024-2026 and
2026-09-30 (live pages) for everything added by the order, including the official 2027 FOMC
calendar (which replaced the earlier 2027 pattern estimates). 2027 BLS/BEA/Census schedules are
not yet published — those months are PATTERN ESTIMATES and flagged as such in provenance.

These are CONDITIONING markers only. ZERO directional information. Pre-FOMC drift is
published, crowded, and decayed; do not add tilts.

Usage:  python scripts/build_event_calendar.py [--allow-non-trading] [--print]
The EARNINGS events written by build_earnings_calendar.py are preserved across rebuilds.
"""
from __future__ import annotations
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
OUT = DATA / "event_calendar.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))

RETRIEVED_AT = "2026-06-11"          # the original CPI / NFP / FOMC lists
RETRIEVED_A2 = "2026-09-30"          # everything added by the order of 30-Sept-2026
SRC_CPI = "https://www.bls.gov/schedule/news_release/cpi.htm"
SRC_NFP = "https://www.bls.gov/schedule/news_release/empsit.htm"
SRC_PPI = "https://www.bls.gov/schedule/news_release/ppi.htm"
SRC_JOLTS = "https://www.bls.gov/schedule/news_release/jolts.htm"
SRC_FOMC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
SRC_TSY = "https://www.treasurydirect.gov/auctions/upcoming/"
SRC_BEA = "https://www.bea.gov/news/schedule"
SRC_ISM = "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/"
SRC_CENSUS = "https://www.census.gov/economic-indicators/calendar-listview.html"
SRC_DOL = "https://www.dol.gov/ui/data.pdf"
SRC_ELECTION = "https://www.usa.gov/midterm-elections"
SRC_ELECTION_LAW = "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title2-section7"
SRC_OPEX = "https://cdn.cboe.com/resources/options/Cboe2026OPTIONSCalendar.pdf"

# Impact levels by type — the levels the colour rules and the cluster detector read.
IMPACT = {"FOMC": "high", "CPI": "high", "NFP": "high", "PCE": "high", "ELECTION": "high",
          "PPI": "medium", "GDP": "medium", "JOLTS": "medium", "ISM_MFG": "medium", "ISM_SVC": "medium",
          "RETAIL": "medium", "OPEX": "low", "CLAIMS": "low", "TREASURY": "low", "EARNINGS": "medium"}

# ── OFFICIAL CPI release dates (BLS schedule pages, archived) ──────────
# 2025 reflects ACTUALS including the Oct-Nov 2025 shutdown disruptions
# (September-2025 data released 10-24; October-2025 data release skipped).
OFFICIAL_CPI = {
    2024: ["2024-01-11","2024-02-13","2024-03-12","2024-04-10","2024-05-15","2024-06-12",
            "2024-07-11","2024-08-14","2024-09-11","2024-10-10","2024-11-13","2024-12-11"],
    2025: ["2025-01-15","2025-02-12","2025-03-12","2025-04-10","2025-05-13","2025-06-11",
            "2025-07-15","2025-08-12","2025-09-11","2025-10-24","2025-12-18"],
    2026: ["2026-01-13","2026-02-13","2026-03-11","2026-04-10","2026-05-12","2026-06-10",
            "2026-07-14","2026-08-12","2026-09-11","2026-10-14","2026-11-10","2026-12-10"],
}

# ── OFFICIAL Employment Situation (NFP) release dates ──────────────────
OFFICIAL_NFP = {
    2024: ["2024-01-05","2024-02-02","2024-03-08","2024-04-05","2024-05-03","2024-06-07",
            "2024-07-05","2024-08-02","2024-09-06","2024-10-04","2024-11-01","2024-12-06"],
    2025: ["2025-01-10","2025-02-07","2025-03-07","2025-04-04","2025-05-02","2025-06-06",
            "2025-07-03","2025-08-01","2025-09-05","2025-11-20","2025-12-16"],
    2026: ["2026-01-09","2026-02-11","2026-03-06","2026-04-03","2026-05-08","2026-06-05",
            "2026-07-02","2026-08-07","2026-09-04","2026-10-02","2026-11-06","2026-12-04"],
}

# ── OFFICIAL FOMC decision (statement, day-2) dates ────────────────────
# 2027 replaced on 2026-09-30 by the Board's published 2027 calendar (Jan 26-27, Mar 16-17,
# Apr 27-28, Jun 8-9, Jul 27-28, Sep 14-15, Oct 26-27, Dec 7-8); the earlier list was a pattern
# estimate and is gone.
FOMC = [
    "2024-01-31","2024-03-20","2024-05-01","2024-06-12",
    "2024-07-31","2024-09-18","2024-11-07","2024-12-18",
    "2025-01-29","2025-03-19","2025-05-07","2025-06-18",
    "2025-07-30","2025-09-17","2025-10-29","2025-12-10",
    "2026-01-28","2026-03-18","2026-04-29","2026-06-17",
    "2026-07-29","2026-09-16","2026-10-28","2026-12-09",
    "2027-01-27","2027-03-17","2027-04-28","2027-06-09",
    "2027-07-28","2027-09-15","2027-10-27","2027-12-08",
]
FOMC_2027_RETRIEVED = RETRIEVED_A2

# ── OFFICIAL PPI (BLS, retrieved 2026-09-30): reference month → release ─
OFFICIAL_PPI_2026 = ["2026-01-14","2026-01-30","2026-02-27","2026-03-18","2026-04-14","2026-05-13",
                     "2026-06-11","2026-07-15","2026-08-13","2026-09-10","2026-10-15","2026-11-13","2026-12-15"]
# ── OFFICIAL JOLTS (BLS, retrieved 2026-09-30; 10:00 ET) ───────────────
OFFICIAL_JOLTS_2026 = ["2026-03-13","2026-03-31","2026-05-05","2026-06-02","2026-06-30","2026-08-04",
                       "2026-09-01","2026-09-29","2026-11-03","2026-12-01"]
# ── OFFICIAL BEA (bea.gov/news/schedule, page last modified 2026-09-30; 08:30 ET) ──
BEA_PCE = [("2026-09-30", "Personal Income and Outlays, August 2026"),
           ("2026-10-29", "Personal Income and Outlays, September 2026"),
           ("2026-11-25", "Personal Income and Outlays, October 2026"),
           ("2026-12-23", "Personal Income and Outlays, November 2026")]
BEA_GDP = [("2026-09-30", "GDP, 2nd Quarter 2026 (Third Estimate)"),
           ("2026-10-29", "GDP, 3rd Quarter 2026 (Advance Estimate)"),
           ("2026-11-25", "GDP, 3rd Quarter 2026 (Second Estimate)"),
           ("2026-12-23", "GDP, 3rd Quarter 2026 (Third Estimate)")]
# ── OFFICIAL Census advance retail sales (retrieved 2026-09-30; 08:30 ET) ──
CENSUS_RETAIL = [("2026-10-15", "September 2026"), ("2026-11-17", "October 2026"), ("2026-12-16", "November 2026")]
# ── ISM: the dated calendar page redirects to a member login; the release rule is published
# (Manufacturing PMI on the first business day, Services PMI on the third, 10:00 ET) and the
# October / November / December 2026 manufacturing dates (Oct 1, Nov 2, Dec 1) were confirmed on
# the ISM report pages. Generated by the rule from October 2026; flagged as rule-derived.
ISM_START = date(2026, 10, 1)
# ── Election: Tuesday after the first Monday in November of even years (2 U.S.C. §7);
# usa.gov: "The next midterm elections will be in November 2026"; FEC: Tuesday, November 3, 2026.
ELECTIONS = ["2026-11-03"]
# ── Options expirations: standard monthly expiration = third Friday (Thursday when that Friday
# is an exchange holiday, as on 2026-06-18); quarterly in March, June, September and December.
# 2026 dates verified on the Cboe 2026 Options Expiration Calendar (Oct 16, Nov 20, Dec 18).
OPEX_START = date(2026, 10, 1)

FEDERAL_HOLIDAYS = {   # federal (release) calendar for the claims shift and the ISM business-day rule
    date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,5,25),date(2026,6,19),date(2026,7,3),
    date(2026,9,7),date(2026,10,12),date(2026,11,11),date(2026,11,26),date(2026,12,25),
    date(2027,1,1),date(2027,1,18),date(2027,2,15),date(2027,5,31),date(2027,6,18),date(2027,7,5),
    date(2027,9,6),date(2027,10,11),date(2027,11,11),date(2027,11,25),date(2027,12,24),
}
NYSE_HOLIDAYS = {
    date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,4,3),date(2026,5,25),date(2026,6,19),
    date(2026,7,3),date(2026,9,7),date(2026,11,26),date(2026,12,25),
    date(2027,1,1),date(2027,1,18),date(2027,2,15),date(2027,3,26),date(2027,5,31),date(2027,6,18),
    date(2027,7,5),date(2027,9,6),date(2027,11,25),date(2027,12,24),
}


def first_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def is_business_day(d: date, holidays=FEDERAL_HOLIDAYS) -> bool:
    return d.weekday() < 5 and d not in holidays


def nth_business_day(y: int, m: int, n: int, holidays=FEDERAL_HOLIDAYS) -> date:
    d = date(y, m, 1); k = 0
    while True:
        if is_business_day(d, holidays):
            k += 1
            if k == n:
                return d
        d += timedelta(days=1)


def third_friday_expiry(y: int, m: int) -> date:
    """Standard monthly expiration: the third Friday, or the Thursday before it when that
    Friday is an exchange holiday (Cboe convention)."""
    f = nth_weekday(y, m, weekday=4, n=3)
    return f - timedelta(days=1) if f in NYSE_HOLIDAYS else f


def claims_thursday(d: date) -> date:
    """DOL releases weekly claims on Thursdays at 08:30 ET; in Thanksgiving week the release
    moves to Wednesday, and a Thursday federal holiday moves it to Wednesday as well."""
    if d in FEDERAL_HOLIDAYS or (d + timedelta(days=0)).month == 11 and (d + timedelta(days=0)) in {h for h in FEDERAL_HOLIDAYS if h.month == 11 and h.weekday() == 3}:
        return d - timedelta(days=1)
    return d


def ev(d, type_, name, label, src, retrieved, prov, impact=None, **extra) -> dict:
    e = {"date": d if isinstance(d, str) else d.isoformat(), "type": type_, "name": name, "label": label,
         "impact": impact or IMPACT.get(type_, "medium"), "source_url": src, "retrieved_at": retrieved,
         "provenance": prov}
    e.update(extra)
    return e


def held_tickers() -> set:
    p = DATA / "holdings.json"
    if not p.exists():
        return set()
    try:
        return {str(h["ticker"]).upper() for h in json.load(open(p)).get("holdings", []) if (h.get("shares") or 0) > 0}
    except Exception:
        return set()


def detect_clusters(events: list, held: set) -> list:
    """A2: any session where a macro event of impact HIGH coincides with a held name's earnings.
    Returns [{date, macro: [labels], earnings: [tickers], note}], ascending."""
    by_date: dict = {}
    for e in events:
        by_date.setdefault(e["date"], []).append(e)
    out = []
    for d in sorted(by_date):
        es = by_date[d]
        macro = [e for e in es if e.get("type") != "EARNINGS" and e.get("impact") == "high"]
        earn = [e for e in es if e.get("type") == "EARNINGS" and str(e.get("ticker", "")).upper() in held]
        if macro and earn:
            out.append({"date": d, "macro": sorted({e["label"] for e in macro}),
                        "earnings": sorted({str(e["ticker"]).upper() for e in earn}),
                        "note": "a high-impact macro release and a held name's earnings on the same session"})
    return out


def build_events(existing_earnings: list | None = None) -> list:
    events = []
    # CPI — official 2024-2026; 2027 pattern estimate (≈2nd Wednesday)
    for y, dates in OFFICIAL_CPI.items():
        for d in dates:
            events.append(ev(d, "CPI", "Consumer Price Index", "CPI", SRC_CPI, RETRIEVED_AT, "official", time_et="08:30"))
    for m in range(1, 13):
        d = nth_weekday(2027, m, weekday=2, n=2)
        events.append(ev(d, "CPI", "Consumer Price Index", "CPI", SRC_CPI, RETRIEVED_AT,
                         "pattern_estimate (BLS 2027 schedule not yet published)", time_et="08:30"))
    # NFP — official 2024-2026; 2027 first-Friday pattern
    for y, dates in OFFICIAL_NFP.items():
        for d in dates:
            events.append(ev(d, "NFP", "Nonfarm Payrolls", "NFP", SRC_NFP, RETRIEVED_AT, "official", time_et="08:30"))
    for m in range(1, 13):
        events.append(ev(first_friday(2027, m), "NFP", "Nonfarm Payrolls", "NFP", SRC_NFP, RETRIEVED_AT,
                         "pattern_estimate (BLS 2027 schedule not yet published)", time_et="08:30"))
    # FOMC — official list (2027 from the Board's published calendar, retrieved 2026-09-30)
    for d in FOMC:
        events.append(ev(d, "FOMC", "FOMC Statement", "FOMC", SRC_FOMC,
                         FOMC_2027_RETRIEVED if d.startswith("2027") else RETRIEVED_AT, "official", time_et="14:00"))
    # PPI — official 2026; 2027 pattern (≈ mid-month, the CPI date + 1 business day is NOT assumed: second Thursday)
    for d in OFFICIAL_PPI_2026:
        events.append(ev(d, "PPI", "Producer Price Index", "PPI", SRC_PPI, RETRIEVED_A2, "official", time_et="08:30"))
    for m in range(1, 13):
        events.append(ev(nth_weekday(2027, m, weekday=3, n=2), "PPI", "Producer Price Index", "PPI", SRC_PPI, RETRIEVED_A2,
                         "pattern_estimate (BLS 2027 schedule not yet published)", time_et="08:30"))
    # JOLTS — official 2026 (10:00 ET); no 2027 estimate (the cadence shifted after the 2025 shutdown)
    for d in OFFICIAL_JOLTS_2026:
        events.append(ev(d, "JOLTS", "Job Openings and Labor Turnover Survey", "JOLTS", SRC_JOLTS, RETRIEVED_A2, "official", time_et="10:00"))
    # BEA — PCE and GDP, official from the schedule page (page last modified 2026-09-30)
    for d, name in BEA_PCE:
        events.append(ev(d, "PCE", name, "PCE", SRC_BEA, RETRIEVED_A2, "official (BEA schedule, page last modified 2026-09-30)", time_et="08:30"))
    for d, name in BEA_GDP:
        events.append(ev(d, "GDP", name, "GDP", SRC_BEA, RETRIEVED_A2, "official (BEA schedule, page last modified 2026-09-30)", time_et="08:30"))
    # ISM — rule-derived from October 2026 through December 2027
    y, m = ISM_START.year, ISM_START.month
    while (y, m) <= (2027, 12):
        events.append(ev(nth_business_day(y, m, 1), "ISM_MFG", "ISM Manufacturing PMI", "ISM mfg", SRC_ISM, RETRIEVED_A2,
                         "release rule: first business day, 10:00 ET (the dated ISM calendar page requires a login; Oct 1 / Nov 2 / Dec 1 2026 confirmed on the report pages)", time_et="10:00"))
        events.append(ev(nth_business_day(y, m, 3), "ISM_SVC", "ISM Services PMI", "ISM svc", SRC_ISM, RETRIEVED_A2,
                         "release rule: third business day, 10:00 ET (the dated ISM calendar page requires a login)", time_et="10:00"))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    # Census — advance retail sales, official (retrieved 2026-09-30)
    for d, ref in CENSUS_RETAIL:
        events.append(ev(d, "RETAIL", f"Advance Monthly Retail Sales, {ref}", "Retail sales", SRC_CENSUS, RETRIEVED_A2, "official (Census 2026 economic-indicator calendar)", time_et="08:30"))
    # DOL — weekly claims, Thursdays 08:30 ET, from 2026-10-01 through 2027-12-30
    d = date(2026, 10, 1)
    while d <= date(2027, 12, 31):
        rd = claims_thursday(d)
        events.append(ev(rd, "CLAIMS", "Unemployment Insurance Weekly Claims", "Claims", SRC_DOL, RETRIEVED_A2,
                         "release rule: Thursdays 08:30 ET; Wednesday in Thanksgiving week and when Thursday is a federal holiday (the weekly release states each week's embargo time)", time_et="08:30"))
        d += timedelta(days=7)
    # Election
    for d in ELECTIONS:
        events.append(ev(d, "ELECTION", "United States general election (midterm)", "Election", SRC_ELECTION, RETRIEVED_A2,
                         "statute: the Tuesday after the first Monday in November of even-numbered years (2 U.S.C. §7, " + SRC_ELECTION_LAW + "); usa.gov: November 2026", time_et=None))
    # OPEX — third Friday, quarterly flagged; 2026 verified on the Cboe calendar, 2027 by rule
    y, m = OPEX_START.year, OPEX_START.month
    while (y, m) <= (2027, 12):
        q = m in (3, 6, 9, 12)
        events.append(ev(third_friday_expiry(y, m), "OPEX", "Quarterly options expiration" if q else "Monthly options expiration",
                         "Quarterly OPEX" if q else "OPEX", SRC_OPEX, RETRIEVED_A2,
                         ("official (Cboe 2026 Options Expiration Calendar)" if y == 2026 else "rule: third Friday (Thursday when that Friday is an exchange holiday); Cboe 2027 calendar not yet published"),
                         impact="medium" if q else "low", quarterly=q, time_et="16:00"))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    # Treasury — monthly refunding pattern anchored on the 2nd WEDNESDAY
    # (10Y), with 3Y the Tuesday BEFORE and 30Y the Thursday AFTER — one
    # contiguous Tue/Wed/Thu sequence, matching the actual refunding order.
    # JULY AUDIT FIX 6b: the old independent nth-weekday rule inverted the
    # sequence in months starting Wed-Sun (July 2026 gave 3Y 07-14 AFTER 10Y
    # 07-08; TreasuryDirect confirms 3Y 07-07 / 10Y 07-08 / 30Y 07-09).
    for y in range(2024, 2028):
        for m in range(1, 13):
            d10 = nth_weekday(y, m, weekday=2, n=2)
            d3 = d10 - timedelta(days=1)
            d30 = d10 + timedelta(days=1)
            assert d3 < d10 < d30, f"refunding order broken {y}-{m}"
            for d, lbl, name in [(d3, "3Y", "3Y Note Auction"), (d10, "10Y", "10Y Note Auction"), (d30, "30Y", "30Y Bond Auction")]:
                events.append(ev(d, "TREASURY", name, lbl, SRC_TSY, RETRIEVED_AT,
                                 "refunding pattern (2nd-Wed anchor; verified vs TreasuryDirect for Jul-2026)", time_et="13:00"))
    # EARNINGS — preserved from the existing file (written by build_earnings_calendar.py)
    held = held_tickers()
    for e in (existing_earnings or []):
        e = dict(e)
        e["impact"] = "high" if str(e.get("ticker", "")).upper() in held else "medium"
        events.append(e)
    events.sort(key=lambda e: (e["date"], e["type"], e.get("label", "")))
    return events


def hard_asserts(events: list) -> None:
    by = {}
    for e in events:
        by.setdefault((e["date"], e["type"]), []).append(e)
    assert ("2026-06-10", "CPI") in by, "ASSERT FAIL: May-2026 CPI must be 2026-06-10 (BLS official)"
    assert ("2026-06-09", "CPI") not in by, "ASSERT FAIL: stale 2026-06-09 CPI entry present"
    assert ("2026-06-05", "NFP") in by, "ASSERT FAIL: June NFP must be 2026-06-05"
    assert ("2026-06-17", "FOMC") in by, "ASSERT FAIL: 2026-06-17 FOMC decision missing"
    # Order 30-Sept A2 anchors
    for d, t in [("2026-09-30", "PCE"), ("2026-09-30", "GDP"), ("2026-10-02", "NFP"), ("2026-10-14", "CPI"),
                 ("2026-10-15", "PPI"), ("2026-10-28", "FOMC"), ("2026-10-29", "PCE"), ("2026-11-03", "ELECTION"),
                 ("2026-12-09", "FOMC"), ("2026-10-16", "OPEX"), ("2026-11-20", "OPEX"), ("2026-12-18", "OPEX"),
                 ("2026-10-01", "ISM_MFG"), ("2026-10-05", "ISM_SVC"), ("2026-10-01", "CLAIMS"), ("2026-11-25", "CLAIMS")]:
        assert (d, t) in by, f"ASSERT FAIL: {t} anchor {d} missing"
    assert ("2026-11-26", "CLAIMS") not in by, "ASSERT FAIL: claims on Thanksgiving Day"
    jul = {(e["date"], e["label"]) for e in events if e["type"] == "TREASURY" and e["date"].startswith("2026-07")}
    assert ("2026-07-07", "3Y") in jul and ("2026-07-08", "10Y") in jul and ("2026-07-09", "30Y") in jul, \
        f"ASSERT FAIL: July-2026 refunding sequence wrong: {sorted(jul)}"
    for e in events:
        wd = date.fromisoformat(e["date"]).weekday()
        assert wd < 5, f"ASSERT FAIL: weekend event {e['date']} {e['type']}"
        assert e.get("impact") in ("high", "medium", "low"), f"ASSERT FAIL: impact missing on {e['date']} {e['type']}"
        assert e.get("source_url"), f"ASSERT FAIL: no source_url on {e['date']} {e['type']}"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-non-trading", action="store_true")
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args()
    from trading_calendar import require_trading_day, now_et  # SEPT AUDIT [2.4]
    require_trading_day("build_event_calendar")
    existing = {}
    if OUT.exists():
        try:
            existing = json.load(open(OUT))
        except Exception:
            existing = {}
    existing_earnings = [e for e in existing.get("events", []) if e.get("type") == "EARNINGS"]
    events = build_events(existing_earnings)
    hard_asserts(events)
    held = held_tickers()
    clusters = detect_clusters(events, held)
    print("  hard asserts: May-2026 CPI=06-10 ✓ · June NFP=06-05 ✓ · FOMC 06-17 ✓ · A2 anchors ✓ · all weekdays ✓")
    payload = {
        "version": "3.0",
        "rebuilt_at": now_et().strftime("%Y-%m-%d"),
        "cadence": "weekly",
        "as_of": now_et().strftime("%Y-%m-%d"),
        "note": ("Scheduled macro events 2024-2027 from OFFICIAL release schedules (2027 BLS/BEA/Census = "
                 "pattern estimate or rule; ISM by its published release rule). CONDITIONING markers only — these "
                 "encode ZERO directional information. Pre-FOMC drift is published, crowded, and decayed; do not add tilts."),
        "sources": {"CPI": SRC_CPI, "NFP": SRC_NFP, "PPI": SRC_PPI, "JOLTS": SRC_JOLTS, "FOMC": SRC_FOMC, "PCE": SRC_BEA,
                    "GDP": SRC_BEA, "ISM": SRC_ISM, "RETAIL": SRC_CENSUS, "CLAIMS": SRC_DOL, "ELECTION": SRC_ELECTION,
                    "OPEX": SRC_OPEX, "TREASURY": SRC_TSY},
        "impact_levels": IMPACT,
        "cluster_rule": "a session where a macro event of impact high coincides with a held name's earnings (holdings.json)",
        "held_names": sorted(held),
        "clusters": clusters,
        "earnings_note": existing.get("earnings_note", ("EARNINGS events: provider earnings calendar per ticker for the held names, the "
                                                         "register's claim tickers, the ai_infra members and the screen board's top 40; "
                                                         "written by scripts/build_earnings_calendar.py")),
        "events": events,
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2)
    by_type = {}
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print(f"  saved {OUT}  ({len(events)} events; {len(clusters)} clusters)")
    for k, n in sorted(by_type.items()):
        print(f"    {k:10s} {n}")
    for c in clusters:
        print(f"    cluster {c['date']}: {', '.join(c['macro'])} with {', '.join(c['earnings'])} earnings")
    if args.do_print:
        for e in events:
            if "2026-09-30" <= e["date"] <= "2026-12-31" and e["type"] not in ("TREASURY", "CLAIMS"):
                print(f"    {e['date']} {e['type']:9s} {e['impact']:6s} {e['name']}")


if __name__ == "__main__":
    main()
