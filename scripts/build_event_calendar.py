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

ORDER 1-Oct-2026, item R6 — Treasury auctions from the source. The second-Wednesday generator
served 3Y/10Y/30Y on 2026-10-13/14/15 and 11-10/11/12 (11-11 is Veterans Day); TreasuryDirect had
announced 10-06/07/08. It is removed. TREASURY events (coupon auctions: 2, 3, 5, 7, 10, 20 and
30-year notes and bonds and TIPS; bills and FRNs excluded; reopenings labelled as reopenings) now come
from TreasuryDirect TA_WS — the auction record for auctions held since 2024-01-01 and `upcoming` for
auctions announced — and, for dates not yet announced, from Treasury's tentative auction schedule
(flagged tentative: true; replaced by the announced date once TA_WS announces the auction). A new type
REFUNDING (impact medium, 08:30 ET) carries the quarterly refunding statement dates from Treasury's
quarterly refunding page. Each source is fetched live at build time; when a fetch fails the builder
falls back to the previous calendar's sourced entries or the snapshot transcribed below, and records
which source it used in `treasury_sources`. The referee check is scripts/calendar_checks.py.

These are CONDITIONING markers only. ZERO directional information. Pre-FOMC drift is
published, crowded, and decayed; do not add tilts.

Usage:  python scripts/build_event_calendar.py [--allow-non-trading] [--print] [--offline]
The EARNINGS events written by build_earnings_calendar.py are preserved across rebuilds.
"""
from __future__ import annotations
import html as _html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
OUT = DATA / "event_calendar.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import calendar_checks as cc  # noqa: E402  (R6: the coupon-auction normaliser shared with the referee)

RETRIEVED_AT = "2026-06-11"          # the original CPI / NFP / FOMC lists
RETRIEVED_A2 = "2026-09-30"          # everything added by the order of 30-Sept-2026
SRC_CPI = "https://www.bls.gov/schedule/news_release/cpi.htm"
SRC_NFP = "https://www.bls.gov/schedule/news_release/empsit.htm"
SRC_PPI = "https://www.bls.gov/schedule/news_release/ppi.htm"
SRC_JOLTS = "https://www.bls.gov/schedule/news_release/jolts.htm"
SRC_FOMC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
SRC_BEA = "https://www.bea.gov/news/schedule"
SRC_ISM = "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/"
SRC_CENSUS = "https://www.census.gov/economic-indicators/calendar-listview.html"
SRC_DOL = "https://www.dol.gov/ui/data.pdf"
SRC_ELECTION = "https://www.usa.gov/midterm-elections"
SRC_ELECTION_LAW = "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title2-section7"
SRC_OPEX = "https://cdn.cboe.com/resources/options/Cboe2026OPTIONSCalendar.pdf"
# R6 (order 1-Oct-2026): Treasury auction and refunding sources
SRC_TSY = cc.TA_WS_UPCOMING                       # announced coupon auctions (TA_WS `upcoming`)
SRC_TA_WS_SEARCH = ("https://www.treasurydirect.gov/TA_WS/securities/search?startDate={start}&endDate={end}"
                    "&dateFieldName=auctionDate&type={kind}&format=json")     # the auction record (held)
SRC_TA_WS_CUSIP = "https://www.treasurydirect.gov/TA_WS/securities/search?cusip={cusip}&format=json"
SRC_REFUNDING = ("https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding/"
                 "most-recent-quarterly-refunding-documents")
SRC_TENTATIVE_PDF = "https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.pdf"
TREASURY_START = "2024-01-01"
USER_AGENT = cc.USER_AGENT

# Impact levels by type — the levels the colour rules and the cluster detector read.
IMPACT = {"FOMC": "high", "CPI": "high", "NFP": "high", "PCE": "high", "ELECTION": "high",
          "PPI": "medium", "GDP": "medium", "JOLTS": "medium", "ISM_MFG": "medium", "ISM_SVC": "medium",
          "RETAIL": "medium", "OPEX": "low", "CLAIMS": "low", "TREASURY": "low", "EARNINGS": "medium",
          "REFUNDING": "medium"}

# ── R6 fallback snapshots, retrieved 2026-10-01 (used only when the live fetch fails) ──────────
# TA_WS `upcoming`, coupon auctions (bills excluded), as served on 2026-10-01.
ANNOUNCED_SNAPSHOT_RETRIEVED = "2026-10-01"
ANNOUNCED_SNAPSHOT = [
    {"date": "2026-10-06", "tenor": "3Y", "tips": False, "reopening": False, "security_type": "Note",
     "security_term": "3-Year", "original_term": "3-Year", "cusip": "91282CRQ6", "announcement_date": "2026-10-01", "time_et": "13:00"},
    {"date": "2026-10-07", "tenor": "10Y", "tips": False, "reopening": True, "security_type": "Note",
     "security_term": "9-Year 10-Month", "original_term": "10-Year", "cusip": "91282CRF0", "announcement_date": "2026-10-01", "time_et": "13:00"},
    {"date": "2026-10-08", "tenor": "30Y", "tips": False, "reopening": True, "security_type": "Bond",
     "security_term": "29-Year 10-Month", "original_term": "30-Year", "cusip": "912810UW6", "announcement_date": "2026-10-01", "time_et": "13:00"},
]
# Treasury's tentative auction schedule — "Aug2026 Refunding Auction Calendar Official Ver 2"
# (2026-08-05 → 2027-01-30), the XML linked from the quarterly refunding documents page; the PDF at
# SRC_TENTATIVE_PDF is the same schedule (sha256 3b83706a…; created 2026-08-04). Coupon rows only
# (bills and the 2-year FRN excluded), machine-read from the XML on 2026-10-01 with
# xml.etree and checked row by row against the PDF.
# (auction date, announcement date, term, security type, reopening, TIPS)
TENTATIVE_SNAPSHOT = {
    "url": "https://home.treasury.gov/system/files/221/TentativeAuctionScheduleQ32026.xml",
    "name": "Aug2026 Refunding Auction Calendar Official Ver 2", "start": "2026-08-05", "end": "2027-01-30",
    "retrieved_at": "2026-10-01", "parse": "snapshot transcribed in build_event_calendar.py (XML read 2026-10-01)",
    "rows": [
        ("2026-08-11", "2026-08-05", "3-Year", "NOTE", False, False),
        ("2026-08-12", "2026-08-05", "10-Year", "NOTE", False, False),
        ("2026-08-13", "2026-08-05", "30-Year", "BOND", False, False),
        ("2026-08-19", "2026-08-13", "20-Year", "BOND", False, False),
        ("2026-08-20", "2026-08-13", "30-Year", "BOND", True, True),
        ("2026-08-25", "2026-08-20", "2-Year", "NOTE", False, False),
        ("2026-08-26", "2026-08-20", "5-Year", "NOTE", False, False),
        ("2026-08-27", "2026-08-20", "7-Year", "NOTE", False, False),
        ("2026-09-08", "2026-09-03", "3-Year", "NOTE", False, False),
        ("2026-09-09", "2026-09-03", "10-Year", "NOTE", True, False),
        ("2026-09-10", "2026-09-03", "30-Year", "BOND", True, False),
        ("2026-09-15", "2026-09-10", "20-Year", "BOND", True, False),
        ("2026-09-17", "2026-09-10", "10-Year", "NOTE", True, True),
        ("2026-09-22", "2026-09-17", "2-Year", "NOTE", False, False),
        ("2026-09-23", "2026-09-17", "5-Year", "NOTE", False, False),
        ("2026-09-24", "2026-09-17", "7-Year", "NOTE", False, False),
        ("2026-10-06", "2026-10-01", "3-Year", "NOTE", False, False),
        ("2026-10-07", "2026-10-01", "10-Year", "NOTE", True, False),
        ("2026-10-08", "2026-10-01", "30-Year", "BOND", True, False),
        ("2026-10-21", "2026-10-15", "20-Year", "BOND", True, False),
        ("2026-10-22", "2026-10-15", "5-Year", "NOTE", False, True),
        ("2026-10-26", "2026-10-22", "2-Year", "NOTE", False, False),
        ("2026-10-27", "2026-10-22", "5-Year", "NOTE", False, False),
        ("2026-10-29", "2026-10-22", "7-Year", "NOTE", False, False),
        ("2026-11-09", "2026-11-04", "3-Year", "NOTE", False, False),
        ("2026-11-10", "2026-11-04", "10-Year", "NOTE", False, False),
        ("2026-11-12", "2026-11-04", "30-Year", "BOND", False, False),
        ("2026-11-18", "2026-11-12", "20-Year", "BOND", False, False),
        ("2026-11-19", "2026-11-12", "10-Year", "NOTE", True, True),
        ("2026-11-23", "2026-11-19", "2-Year", "NOTE", False, False),
        ("2026-11-24", "2026-11-19", "5-Year", "NOTE", False, False),
        ("2026-11-25", "2026-11-19", "7-Year", "NOTE", False, False),
        ("2026-12-07", "2026-12-03", "3-Year", "NOTE", False, False),
        ("2026-12-08", "2026-12-03", "10-Year", "NOTE", True, False),
        ("2026-12-10", "2026-12-03", "30-Year", "BOND", True, False),
        ("2026-12-22", "2026-12-17", "5-Year", "NOTE", True, True),
        ("2026-12-23", "2026-12-17", "20-Year", "BOND", True, False),
        ("2026-12-28", "2026-12-24", "2-Year", "NOTE", False, False),
        ("2026-12-28", "2026-12-24", "5-Year", "NOTE", False, False),
        ("2026-12-29", "2026-12-24", "7-Year", "NOTE", False, False),
        ("2027-01-11", "2027-01-07", "3-Year", "NOTE", False, False),
        ("2027-01-12", "2027-01-07", "10-Year", "NOTE", True, False),
        ("2027-01-13", "2027-01-07", "30-Year", "BOND", True, False),
        ("2027-01-20", "2027-01-14", "20-Year", "BOND", True, False),
        ("2027-01-21", "2027-01-14", "10-Year", "NOTE", False, True),
        ("2027-01-25", "2027-01-21", "2-Year", "NOTE", False, False),
        ("2027-01-26", "2027-01-21", "5-Year", "NOTE", False, False),
        ("2027-01-28", "2027-01-21", "7-Year", "NOTE", False, False),
    ],
}
# The quarterly refunding documents page, read 2026-10-01: the 8:30 AM block (the policy statement —
# the refunding statement) "DOCUMENTS RELEASED at 8:30 AM Wednesday, August 5, 2026" and, under it,
# "(The next release is scheduled for November 4, 2026)".
REFUNDING_SNAPSHOT = {"retrieved_at": "2026-10-01", "latest": "2026-08-05", "next": "2026-11-04"}

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


# ── R6: Treasury auctions and the quarterly refunding, from the source ─────────────────────────
def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_tentative_xml(raw: bytes) -> dict:
    """Treasury's tentative auction schedule (XML) → {name, start, end, rows}; coupon rows only
    (NOTE / BOND, FloatingRate N), each (auction, announcement, term, type, reopening, tips)."""
    root = ET.fromstring(raw)
    rows = []
    for a in root.iter("AuctionCalendarDate"):
        d = {ch.tag: (ch.text or "").strip() for ch in a}
        if d.get("SecurityType") not in ("NOTE", "BOND") or d.get("FloatingRate") == "Y":
            continue
        if not (d.get("AuctionDate") and d.get("SecurityTermWeekYear")):
            continue
        rows.append((d["AuctionDate"][:10], (d.get("AnnouncementDate") or "")[:10] or None, d["SecurityTermWeekYear"],
                     d["SecurityType"], d.get("ReOpeningIndicator") == "Y", d.get("TIPS") == "Y"))
    if not rows:
        raise ValueError("tentative schedule XML carries no coupon rows")
    return {"name": root.findtext("AuctionCalendarName"), "start": root.findtext("StartDate"),
            "end": root.findtext("EndDate"), "rows": sorted(rows)}


def parse_refunding_page(page: str) -> dict:
    """The quarterly refunding documents page → {latest, next, xml_url}. `latest` is the date of the
    8:30 AM documents block (the policy statement = the refunding statement); `next` is that block's
    "next release is scheduled for …"; xml_url is the tentative auction schedule's XML link."""
    m = re.search(r'href="?([^"\s>]*TentativeAuctionSchedule[^"\s>]*\.xml)', page, re.I)
    xml_url = None
    if m:
        xml_url = m.group(1) if m.group(1).startswith("http") else "https://home.treasury.gov" + m.group(1)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", page))
    text = re.sub(r"\s+", " ", text)
    blk = re.search(r"DOCUMENTS RELEASED at 8:30 AM \w+, (\w+ \d{1,2}, \d{4})(.*?)(?:DOCUMENTS RELEASED|$)", text, re.I)
    if not blk:
        raise ValueError("refunding page: no 8:30 AM documents block")
    nxt = re.search(r"next release is scheduled for (\w+ \d{1,2}) ?, (\d{4})", blk.group(2), re.I)
    if not nxt:
        raise ValueError("refunding page: the 8:30 AM block names no next release date")
    f = lambda s: datetime.strptime(s.title(), "%B %d, %Y").date().isoformat()   # noqa: E731
    return {"latest": f(blk.group(1)), "next": f(f"{nxt.group(1)}, {nxt.group(2)}"), "xml_url": xml_url}


def _tentative_items(tent: dict, retrieved: str) -> list:
    out = []
    for auc, ann, term, kind, reopen, tips in tent.get("rows", []):
        tenor = cc.series_of(term, tips)
        if not tenor:
            continue
        out.append({"date": auc, "announcement_date": ann, "tenor": tenor, "tips": tips, "reopening": reopen,
                    "security_type": kind.title(), "security_term": term, "original_term": term, "cusip": None,
                    "time_et": "13:00"})
    return out


def _item_from_event(e: dict) -> dict:
    return {k: e.get(k) for k in ("date", "tenor", "tips", "reopening", "security_type", "security_term",
                                   "original_term", "cusip", "announcement_date", "time_et")}


def offline_treasury_inputs(existing: dict | None = None) -> dict:
    """The inputs when nothing is fetched: the previous calendar's sourced entries and the snapshots."""
    existing = existing or {}
    prev_src = existing.get("treasury_sources") or {}
    cached = (prev_src.get("ta_ws_upcoming") or {})
    held = [_item_from_event(e) for e in existing.get("events", [])
            if e.get("type") == "TREASURY" and e.get("status") == "auctioned"]
    # announced entries of the previous calendar: an auction that has left TA_WS `upcoming` but is not
    # yet in the auction record (results lag) stays as announced instead of falling back to tentative
    prev_announced = [_item_from_event(e) for e in existing.get("events", [])
                      if e.get("type") == "TREASURY" and e.get("status") == "announced"]
    use_cache = isinstance(cached.get("items"), list)
    return {
        "announced_prev": prev_announced,
        "announced": cached["items"] if use_cache else list(ANNOUNCED_SNAPSHOT),
        "announced_status": {"source": "cache" if use_cache else "snapshot", "url": SRC_TSY,
                             "retrieved_at": cached.get("retrieved_at") if use_cache else ANNOUNCED_SNAPSHOT_RETRIEVED},
        "auctioned": held,
        "auctioned_status": {"source": "previous calendar" if held else "none", "url": SRC_TA_WS_SEARCH,
                             "retrieved_at": (prev_src.get("ta_ws_auctioned") or {}).get("retrieved_at")},
        "tentative": TENTATIVE_SNAPSHOT,
        "tentative_status": {"source": "snapshot", "url": TENTATIVE_SNAPSHOT["url"], "pdf": SRC_TENTATIVE_PDF,
                             "retrieved_at": TENTATIVE_SNAPSHOT["retrieved_at"], "parse": TENTATIVE_SNAPSHOT["parse"],
                             "name": TENTATIVE_SNAPSHOT["name"], "start": TENTATIVE_SNAPSHOT["start"], "end": TENTATIVE_SNAPSHOT["end"]},
        "refunding": dict(REFUNDING_SNAPSHOT),
        "refunding_status": {"source": "snapshot", "url": SRC_REFUNDING, "retrieved_at": REFUNDING_SNAPSHOT["retrieved_at"]},
    }


def gather_treasury_inputs(existing: dict | None, today: str, timeout: int = 30) -> dict:
    """Live fetch of every R6 source; each one that fails falls back (offline_treasury_inputs) and
    its status says so."""
    inp = offline_treasury_inputs(existing)
    try:
        ann = cc.normalize_ta_ws(json.loads(_http_get(SRC_TSY, timeout)))
        inp["announced"] = ann
        inp["announced_status"] = {"source": "live", "url": SRC_TSY, "retrieved_at": today}
    except Exception as e:  # noqa: BLE001
        inp["announced_status"]["error"] = f"{type(e).__name__}: {e}"[:200]
        print(f"  WARN TA_WS upcoming fetch failed ({e}); using the {inp['announced_status']['source']} list", file=sys.stderr)
    try:
        rows = []
        for kind in ("Note", "Bond", "TIPS"):
            got = json.loads(_http_get(SRC_TA_WS_SEARCH.format(start=TREASURY_START, end=today, kind=kind), timeout))
            if not isinstance(got, list):
                raise ValueError(f"TA_WS search {kind} returned {type(got).__name__}")
            rows += got
        held = [a for a in cc.normalize_ta_ws(rows) if a["date"] <= today]
        if not held:
            raise ValueError("TA_WS search returned no coupon auctions")
        inp["auctioned"] = held
        inp["auctioned_status"] = {"source": "live", "url": SRC_TA_WS_SEARCH, "retrieved_at": today, "start": TREASURY_START}
    except Exception as e:  # noqa: BLE001
        inp["auctioned_status"]["error"] = f"{type(e).__name__}: {e}"[:200]
        print(f"  WARN TA_WS auction-record fetch failed ({e}); keeping the previous calendar's held auctions", file=sys.stderr)
    try:
        page = _http_get(SRC_REFUNDING, timeout).decode("utf-8", "replace")
        ref = parse_refunding_page(page)
        inp["refunding"] = {"retrieved_at": today, "latest": ref["latest"], "next": ref["next"]}
        inp["refunding_status"] = {"source": "live", "url": SRC_REFUNDING, "retrieved_at": today}
        if not ref.get("xml_url"):
            raise ValueError("refunding page links no tentative auction schedule XML")
        tent = parse_tentative_xml(_http_get(ref["xml_url"], timeout))
        tent.update({"url": ref["xml_url"], "retrieved_at": today, "parse": "XML (xml.etree), fetched at build time"})
        inp["tentative"] = tent
        inp["tentative_status"] = {"source": "live", "url": ref["xml_url"], "pdf": SRC_TENTATIVE_PDF, "retrieved_at": today,
                                   "parse": tent["parse"], "name": tent.get("name"), "start": tent.get("start"), "end": tent.get("end")}
    except Exception as e:  # noqa: BLE001
        for k in ("refunding_status", "tentative_status"):
            if inp[k]["source"] != "live":
                inp[k]["error"] = f"{type(e).__name__}: {e}"[:200]
        print(f"  WARN refunding page / tentative schedule fetch failed ({e}); using the snapshot", file=sys.stderr)
    return inp


def _tsy_name(a: dict) -> str:
    kind = "TIPS" if a.get("tips") else (a.get("security_type") or "Note").title()
    base = f"{a['tenor'].replace('TIPS ', '').replace('Y', '-Year')} {kind} auction"
    if a.get("reopening"):
        term = a.get("security_term") or ""
        base += f" (reopening{', ' + term if term and term != a['tenor'].replace('TIPS ', '').replace('Y', '-Year') else ''})"
    return base


def treasury_events(inp: dict, today: str, existing_events: list | None = None) -> list:
    """TREASURY (held + announced from TA_WS, tentative from the schedule) and REFUNDING events.
    An announced or held auction of the same series within 14 days replaces a tentative row;
    tentative rows dated before today are dropped (the auction record is authoritative for the past)."""
    prev_ret = {(e.get("type"), e.get("date"), e.get("label"), e.get("source_url")): e.get("retrieved_at")
                for e in (existing_events or []) if e.get("type") in ("TREASURY", "REFUNDING")}
    out = []

    def add(a: dict, status: str, src: str, retrieved: str, prov: str):
        label = f"{a['tenor']}{' reopening' if a.get('reopening') else ''}"
        e = ev(a["date"], "TREASURY", _tsy_name(a), label, src, retrieved, prov, time_et=a.get("time_et") or "13:00",
               tenor=a["tenor"], reopening=bool(a.get("reopening")), tips=bool(a.get("tips")),
               security_type=a.get("security_type"), security_term=a.get("security_term"),
               original_term=a.get("original_term"), cusip=a.get("cusip"), announcement_date=a.get("announcement_date"),
               tentative=(status == "tentative"), status=status)
        e["retrieved_at"] = prev_ret.get(("TREASURY", e["date"], e["label"], e["source_url"])) or retrieved
        out.append(e)

    seen = {}
    for a in inp.get("auctioned") or []:
        seen[(a.get("cusip"), a["date"])] = ("auctioned", a)
    for a in inp.get("announced") or []:
        seen.setdefault((a.get("cusip"), a["date"]), ("announced", a))
    for a in inp.get("announced_prev") or []:   # left `upcoming`, not yet in the record: past/today only
        if a.get("date") and a["date"] <= today and a.get("tenor"):
            seen.setdefault((a.get("cusip"), a["date"]), ("announced", a))
    st_h, st_a = inp.get("auctioned_status") or {}, inp.get("announced_status") or {}
    for (cusip, d), (status, a) in sorted(seen.items(), key=lambda kv: (kv[0][1], kv[1][1]["tenor"])):
        if status == "auctioned":
            add(a, "auctioned", SRC_TA_WS_CUSIP.format(cusip=cusip), st_h.get("retrieved_at") or today,
                "auctioned (TreasuryDirect TA_WS auction record)")
        else:
            add(a, "announced", SRC_TSY, st_a.get("retrieved_at") or today,
                f"announced (TreasuryDirect TA_WS upcoming; announced {a.get('announcement_date') or 'n/a'})")
    sourced = [(a["tenor"], date.fromisoformat(a["date"])) for _, a in seen.values()]
    tent = inp.get("tentative") or {}
    st_t = inp.get("tentative_status") or {}
    for a in _tentative_items(tent, st_t.get("retrieved_at") or today):
        if a["date"] < today:
            continue
        ad = date.fromisoformat(a["date"])
        if any(t == a["tenor"] and abs((d - ad).days) <= cc.MATCH_DAYS for t, d in sourced):
            continue
        add(a, "tentative", tent.get("url") or SRC_TENTATIVE_PDF, tent.get("retrieved_at") or today,
            f"tentative (Treasury tentative auction schedule \"{tent.get('name') or 'n/a'}\", "
            f"{tent.get('start')} to {tent.get('end')}; PDF {SRC_TENTATIVE_PDF}; announcement scheduled "
            f"{a.get('announcement_date') or 'n/a'}; replaced by the TA_WS announced date once announced)")
    # REFUNDING — the quarterly refunding statement (policy statement), 08:30 ET, from the page;
    # past ones kept from the previous calendar (the page shows only the latest and the next)
    ref = inp.get("refunding") or {}
    ref_dates = {}
    for e in existing_events or []:
        if e.get("type") == "REFUNDING" and str(e.get("source_url", "")).startswith("https://home.treasury.gov/"):
            ref_dates[e["date"]] = e
    for key, what in (("latest", "the most recent 8:30 AM documents block (policy statement)"),
                      ("next", "the 8:30 AM block's \"next release is scheduled for\"")):
        d = ref.get(key)
        if not d:
            continue
        ref_dates[d] = ev(d, "REFUNDING", "Quarterly refunding statement (Treasury)", "Refunding", SRC_REFUNDING,
                          ref.get("retrieved_at") or today, f"official (Treasury quarterly refunding documents page: {what})",
                          time_et="08:30")
    for d in sorted(ref_dates):
        e = dict(ref_dates[d])
        e["retrieved_at"] = prev_ret.get(("REFUNDING", e["date"], e["label"], e["source_url"])) or e["retrieved_at"]
        e["impact"] = IMPACT["REFUNDING"]
        out.append(e)
    return out


def build_events(existing_earnings: list | None = None, treasury_inputs: dict | None = None,
                 today: str | None = None, existing_events: list | None = None) -> list:
    """treasury_inputs: what gather_treasury_inputs fetched; None → offline (snapshots only)."""
    today = today or date.today().isoformat()
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
    # Treasury — R6 (order 1-Oct-2026): the second-Wednesday generator is removed. Coupon auctions
    # from TreasuryDirect TA_WS (held + announced) and Treasury's tentative auction schedule (not yet
    # announced, tentative: true); REFUNDING from the quarterly refunding page.
    events += treasury_events(treasury_inputs if treasury_inputs is not None else offline_treasury_inputs(),
                              today, existing_events)
    # EARNINGS — preserved from the existing file (written by build_earnings_calendar.py)
    held = held_tickers()
    for e in (existing_earnings or []):
        e = dict(e)
        e["impact"] = "high" if str(e.get("ticker", "")).upper() in held else "medium"
        events.append(e)
    events.sort(key=lambda e: (e["date"], e["type"], e.get("label", "")))
    return events


def hard_asserts(events: list, announced: list | None = None) -> None:
    """announced: the TA_WS coupon auctions the build used (live, or the cached / snapshot list when
    the fetch failed); None → the 2026-10-01 snapshot."""
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
    # R6.4 (replaces the July-2026 pattern assert): every coupon auction announced in TA_WS within the
    # horizon is present, same series, on the same date.
    horizon_end = max((e["date"] for e in events), default="2027-12-31")
    tsy = {(e["date"], e.get("tenor")) for e in events if e["type"] == "TREASURY"}
    for a in (ANNOUNCED_SNAPSHOT if announced is None else announced):
        if a["date"] <= horizon_end:
            assert (a["date"], a["tenor"]) in tsy, \
                f"ASSERT FAIL: TA_WS announced {a['tenor']} auction {a['date']} (CUSIP {a.get('cusip')}) not on that date"
    for e in events:
        if e["type"] in ("TREASURY", "REFUNDING"):
            ok, why = cc.is_sourced(e)
            assert ok, f"ASSERT FAIL: {e['type']} {e['date']} {e.get('label')} not sourced: {why}"
        if e["type"] == "TREASURY":
            assert date.fromisoformat(e["date"]) not in FEDERAL_HOLIDAYS, f"ASSERT FAIL: auction on a federal holiday {e['date']}"
    assert ("2026-11-04", "REFUNDING") in by, "ASSERT FAIL: the November 2026 refunding statement (2026-11-04) missing"
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
    ap.add_argument("--offline", action="store_true", help="fetch nothing: previous calendar's sourced entries + snapshots")
    args = ap.parse_args()
    from trading_calendar import require_trading_day, now_et  # SEPT AUDIT [2.4]
    require_trading_day("build_event_calendar")
    existing = {}
    if OUT.exists():
        try:
            existing = json.load(open(OUT))
        except Exception:
            existing = {}
    today = now_et().strftime("%Y-%m-%d")
    existing_earnings = [e for e in existing.get("events", []) if e.get("type") == "EARNINGS"]
    tsy_in = offline_treasury_inputs(existing) if args.offline else gather_treasury_inputs(existing, today)
    events = build_events(existing_earnings, tsy_in, today, existing.get("events", []))
    hard_asserts(events, tsy_in["announced"])
    held = held_tickers()
    clusters = detect_clusters(events, held)
    print("  hard asserts: May-2026 CPI=06-10 ✓ · June NFP=06-05 ✓ · FOMC 06-17 ✓ · A2 anchors ✓ · all weekdays ✓ · "
          f"R6: {len(tsy_in['announced'])} TA_WS-announced coupon auctions on their dates ✓ · TREASURY/REFUNDING sourced ✓")
    treasury_sources = {
        "ta_ws_upcoming": dict(tsy_in["announced_status"], items=tsy_in["announced"]),
        "ta_ws_auctioned": dict(tsy_in["auctioned_status"], n=len(tsy_in.get("auctioned") or [])),
        "tentative_schedule": dict(tsy_in["tentative_status"]),
        "refunding": dict(tsy_in["refunding_status"], latest=tsy_in["refunding"].get("latest"), next=tsy_in["refunding"].get("next")),
        "rule": ("TREASURY = coupon auctions (2, 3, 5, 7, 10, 20, 30-year notes and bonds; 5, 10, 30-year TIPS; bills and "
                 "FRNs excluded). status auctioned / announced from TreasuryDirect TA_WS; status tentative from Treasury's "
                 "tentative auction schedule, replaced by the TA_WS date once announced (same series within 14 days). "
                 "No date is generated by a weekday pattern."),
    }
    for k, v in treasury_sources.items():
        if isinstance(v, dict) and v.get("source") != "live":
            print(f"  NOTE {k}: source {v.get('source')} (retrieved {v.get('retrieved_at')}){' · ' + v['error'] if v.get('error') else ''}")
    payload = {
        "version": "3.0",
        "rebuilt_at": today,
        "cadence": "weekly",
        "as_of": today,
        "note": ("Scheduled macro events 2024-2027 from OFFICIAL release schedules (2027 BLS/BEA/Census = "
                 "pattern estimate or rule; ISM by its published release rule; Treasury auctions from TreasuryDirect "
                 "TA_WS and Treasury's tentative auction schedule, never a weekday pattern). CONDITIONING markers only — these "
                 "encode ZERO directional information. Pre-FOMC drift is published, crowded, and decayed; do not add tilts."),
        "sources": {"CPI": SRC_CPI, "NFP": SRC_NFP, "PPI": SRC_PPI, "JOLTS": SRC_JOLTS, "FOMC": SRC_FOMC, "PCE": SRC_BEA,
                    "GDP": SRC_BEA, "ISM": SRC_ISM, "RETAIL": SRC_CENSUS, "CLAIMS": SRC_DOL, "ELECTION": SRC_ELECTION,
                    "OPEX": SRC_OPEX, "TREASURY": SRC_TSY, "TREASURY_TENTATIVE": tsy_in["tentative_status"].get("url"),
                    "REFUNDING": SRC_REFUNDING},
        "treasury_sources": treasury_sources,
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
