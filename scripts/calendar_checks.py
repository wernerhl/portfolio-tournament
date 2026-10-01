"""
calendar_checks.py — referee checks on data/event_calendar.json (order of 1-Oct-2026, item R6).

    check_treasury_source(calendar, announced, today=None, fetch_status=None)
        -> list[(severity, "calendar:treasury_source", detail)]

  CRITICAL  a coupon auction announced in TreasuryDirect TA_WS (`upcoming`) is missing from the
            calendar, or the calendar carries it on another date (an entry of the same series within
            14 days of the announced date, but not on it). A tentative entry left beside the announced
            date on another date is a misdated duplicate and also CRITICAL.
  HIGH      a TREASURY or REFUNDING event lacks a sourced provenance: its source_url must be
            TreasuryDirect TA_WS (announced / held auctions) or home.treasury.gov (the tentative
            auction schedule, the quarterly refunding page), with retrieved_at and a provenance text
            that names no pattern, rule or estimate; an announced auction still flagged tentative.
  HIGH      a tentative auction past its scheduled announcement date (the tentative schedule gives
            one per auction; without it, an auction within 7 days) that TA_WS has not announced:
            the tentative date stands unconfirmed exactly when it should have been replaced.
  MEDIUM    the live TA_WS fetch failed and the check ran against the list the builder cached in
            the calendar (treasury_sources.ta_ws_upcoming), no older than 7 days.
  HIGH      the live fetch failed and no cached list, or only one older than 7 days, was available:
            the announced auctions are unverified. The check never passes silently on a failed fetch.

    load_announced(calendar_path=..., timeout=20) -> (announced, fetch_status)

  Live fetch of TA_WS `upcoming`, normalised to coupon auctions; on failure the cached list from the
  calendar, and fetch_status says which ({"source": "live" | "cache" | "none", "retrieved_at", "error"}).

    treasury_source_findings(calendar_path=...) -> list of findings   (what the nightly referee calls)

normalize_ta_ws() is shared with scripts/build_event_calendar.py so the builder and the referee agree
on what a coupon auction is: Notes and Bonds of 2, 3, 5, 7, 10, 20 and 30 years and TIPS of 5, 10
and 30 years; bills, cash-management bills and floating-rate notes are excluded. The series (tenor)
is the smallest standard maturity at or above the security's remaining term, so a reopened 10-year
("9-Year 10-Month") is the 10Y series and a 2-year auctioned as a reopening of an old 5-year note is
the 2Y series.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_CAL = REPO / "data" / "event_calendar.json"
CHECK = "calendar:treasury_source"
USER_AGENT = "portfolio-tournament/1.0 (+https://github.com/wernerhl/portfolio-tournament)"
TA_WS_UPCOMING = "https://www.treasurydirect.gov/TA_WS/securities/upcoming?format=json"
NOMINAL_TENORS = (2, 3, 5, 7, 10, 20, 30)
TIPS_TENORS = (5, 10, 30)
MATCH_DAYS = 14                     # one auction per series per month: ±14 days is unambiguous
TENTATIVE_WINDOW_DAYS = 7           # no announcement date on a tentative entry → this window instead
CACHE_MAX_AGE_DAYS = 7
SOURCED_URL_PREFIXES = ("https://www.treasurydirect.gov/TA_WS/", "https://home.treasury.gov/")
UNSOURCED_WORDS = re.compile(r"pattern|rule|estimate|inferred|anchor|assum", re.I)


# ── normalisation (shared with the builder) ─────────────────────────────
def _yes(v) -> bool:
    return str(v).strip().lower() in ("yes", "y", "true", "1")


def term_years(term: str | None) -> float | None:
    """'9-Year 10-Month' → 9.833; '3-Year' → 3.0; '13-Week' → None."""
    if not term:
        return None
    y = re.search(r"(\d+)-Year", term)
    m = re.search(r"(\d+)-Month", term)
    if not y and not m:
        return None
    return (int(y.group(1)) if y else 0) + (int(m.group(1)) if m else 0) / 12.0


def series_of(term: str | None, tips: bool) -> str | None:
    """The auction series: the smallest standard maturity at or above the remaining term."""
    yrs = term_years(term)
    if yrs is None:
        return None
    for t in (TIPS_TENORS if tips else NOMINAL_TENORS):
        if yrs <= t + 1e-6:
            return f"TIPS {t}Y" if tips else f"{t}Y"
    return None


def time_24h(s: str | None) -> str | None:
    """'01:00 PM' → '13:00'; '11:30 AM' → '11:30'."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AP])M", str(s or ""), re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "P" else 0)
    return f"{h:02d}:{m.group(2)}"


def normalize_ta_ws(rows: list[dict]) -> list[dict]:
    """TA_WS security records → coupon auctions only, one per (CUSIP, auction date), sorted."""
    out: dict = {}
    for r in rows or []:
        st, kind = str(r.get("securityType", "")), str(r.get("type", ""))
        if st not in ("Note", "Bond") or kind in ("Bill", "FRN", "CMB") or _yes(r.get("floatingRate")):
            continue
        tips = _yes(r.get("tips")) or kind == "TIPS"
        tenor = series_of(r.get("securityTerm"), tips) or series_of(r.get("originalSecurityTerm"), tips)
        d = str(r.get("auctionDate") or "")[:10]
        if not tenor or not re.match(r"\d{4}-\d{2}-\d{2}$", d):
            continue
        item = {"date": d, "tenor": tenor, "tips": tips, "reopening": _yes(r.get("reopening")),
                "security_type": st, "security_term": r.get("securityTerm"),
                "original_term": r.get("originalSecurityTerm") or r.get("securityTerm"),
                "cusip": r.get("cusip"), "announcement_date": (str(r.get("announcementDate") or "")[:10] or None),
                "time_et": time_24h(r.get("closingTimeCompetitive")) or "13:00"}
        out[(item["cusip"], d)] = item
    return sorted(out.values(), key=lambda a: (a["date"], a["tenor"]))


def _http_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_ta_ws_upcoming(timeout: int = 20) -> list[dict]:
    raw = _http_json(TA_WS_UPCOMING, timeout)
    if not isinstance(raw, list):
        raise ValueError(f"TA_WS upcoming returned {type(raw).__name__}, not a list")
    return raw


# ── the loader ─────────────────────────────────────────────────────────
def _today() -> str:
    try:
        sys.path.insert(0, str(HERE))
        from trading_calendar import now_et
        return now_et().strftime("%Y-%m-%d")
    except Exception:
        return date.today().isoformat()


def load_announced(calendar_path: str | Path = DEFAULT_CAL, timeout: int = 20, fetch=None) -> tuple[list[dict], dict]:
    """Live TA_WS `upcoming` (coupon auctions); on failure the list the builder cached in the
    calendar. Returns (announced, fetch_status) — the status is passed to check_treasury_source,
    which reports a failed fetch instead of passing silently."""
    try:
        ann = normalize_ta_ws((fetch or fetch_ta_ws_upcoming)(timeout))
        return ann, {"source": "live", "url": TA_WS_UPCOMING, "retrieved_at": _today(), "n": len(ann)}
    except Exception as e:  # noqa: BLE001 — any failure falls back, and is reported
        err = f"{type(e).__name__}: {e}"[:300]
    try:
        cal = json.load(open(calendar_path))
        blk = (cal.get("treasury_sources") or {}).get("ta_ws_upcoming") or {}
        items = blk.get("items")
        if isinstance(items, list):
            return items, {"source": "cache", "url": TA_WS_UPCOMING, "retrieved_at": blk.get("retrieved_at"),
                           "n": len(items), "error": err}
    except Exception:  # noqa: BLE001
        pass
    return [], {"source": "none", "url": TA_WS_UPCOMING, "retrieved_at": None, "n": 0, "error": err}


# ── the check ───────────────────────────────────────────────────────────
def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def tenor_of(e: dict) -> str | None:
    """The series of a calendar event: its `tenor` field, else read from the label ('10Y reopening')."""
    if e.get("tenor"):
        return str(e["tenor"])
    m = re.match(r"\s*(TIPS\s+)?(\d+)Y\b", str(e.get("label") or ""))
    return (f"TIPS {m.group(2)}Y" if m.group(1) else f"{m.group(2)}Y") if m else None


def is_sourced(e: dict) -> tuple[bool, str]:
    url, prov = str(e.get("source_url") or ""), str(e.get("provenance") or "")
    if not url.startswith(SOURCED_URL_PREFIXES):
        return False, f"source_url {url or 'missing'} is neither TreasuryDirect TA_WS nor home.treasury.gov"
    if not e.get("retrieved_at"):
        return False, "no retrieved_at"
    if not prov:
        return False, "no provenance"
    if UNSOURCED_WORDS.search(prov):
        return False, f"provenance is not sourced: {prov[:80]}"
    if e.get("type") == "TREASURY":
        if not isinstance(e.get("tentative"), bool):
            return False, "no tentative flag"
        if e["tentative"] and not url.startswith("https://home.treasury.gov/"):
            return False, "tentative entry not sourced to Treasury's tentative auction schedule"
        if not e["tentative"] and not url.startswith("https://www.treasurydirect.gov/TA_WS/"):
            return False, "announced/held entry not sourced to TreasuryDirect TA_WS"
    return True, ""


def _label(a: dict) -> str:
    return f"{a.get('tenor')}{' reopening' if a.get('reopening') else ''}"


def check_treasury_source(calendar: dict, announced: list[dict], today: str | None = None,
                          fetch_status: dict | None = None) -> list[tuple[str, str, str]]:
    """Pure: the calendar (the served dict, or a bare list of events) against the TA_WS announced
    coupon auctions (normalised items, or raw TA_WS records). Returns (severity, check, detail)."""
    today = today or _today()
    td = _d(today)
    events = calendar if isinstance(calendar, list) else (calendar or {}).get("events", [])
    if announced and any("auctionDate" in a for a in announced):
        announced = normalize_ta_ws(announced)
    out: list[tuple[str, str, str]] = []

    # 0. the fetch itself
    fs = fetch_status or {}
    if fs and fs.get("source") != "live":
        ra = _d(fs.get("retrieved_at"))
        age = (td - ra).days if (ra and td) else None
        if fs.get("source") == "cache" and age is not None and age <= CACHE_MAX_AGE_DAYS:
            out.append(("MEDIUM", CHECK, f"TA_WS live fetch failed ({fs.get('error')}); checked against the calendar's cached "
                                         f"announced list retrieved {fs.get('retrieved_at')} ({age} days old)"))
        else:
            out.append(("HIGH", CHECK, f"TA_WS live fetch failed ({fs.get('error')}) and "
                                       + (f"the cached announced list is {age} days old (retrieved {fs.get('retrieved_at')})"
                                          if fs.get("source") == "cache" else "no cached announced list exists")
                                       + ": announced coupon auctions are unverified"))

    tsy = [e for e in events if e.get("type") == "TREASURY"]
    by_tenor: dict = {}
    for e in tsy:
        by_tenor.setdefault(tenor_of(e), []).append(e)

    # 1. every announced coupon auction on its date (CRITICAL)
    matched_tentative = set()
    for a in announced or []:
        ad = _d(a.get("date"))
        if ad is None:
            continue
        same = by_tenor.get(a.get("tenor"), [])
        on_date = [e for e in same if e.get("date") == a["date"]]
        near = [e for e in same if e.get("date") != a["date"] and _d(e.get("date")) and abs((_d(e["date"]) - ad).days) <= MATCH_DAYS]
        tag = f"{_label(a)} auction {a['date']}" + (f" (CUSIP {a['cusip']})" if a.get("cusip") else "")
        if not on_date:
            if near:
                matched_tentative.update(id(e) for e in near if e.get("tentative"))
                out.append(("CRITICAL", CHECK, f"announced {tag} is misdated in the calendar: carried on "
                                               f"{', '.join(sorted(e['date'] for e in near))}"))
            else:
                out.append(("CRITICAL", CHECK, f"announced {tag} is missing from the calendar"))
            continue
        for e in on_date:
            if e.get("tentative"):
                out.append(("HIGH", CHECK, f"announced {tag} is still flagged tentative in the calendar"))
        for e in near:
            if e.get("tentative"):
                matched_tentative.add(id(e))
                out.append(("CRITICAL", CHECK, f"tentative {tenor_of(e)} entry on {e['date']} was not replaced by the "
                                               f"announced date {a['date']} (a misdated duplicate)"))

    # 2. sourced provenance on every TREASURY / REFUNDING event (HIGH)
    bad = []
    for e in events:
        if e.get("type") in ("TREASURY", "REFUNDING"):
            ok, why = is_sourced(e)
            if not ok:
                bad.append(f"{e.get('date')} {e.get('type')} {e.get('label') or ''}: {why}".replace("  ", " "))
    if bad:
        out.append(("HIGH", CHECK, f"{len(bad)} TREASURY/REFUNDING entries lack a sourced provenance (first: {bad[0]})"))

    # 3. tentative entries that should have been announced by now (HIGH)
    overdue = []
    for e in tsy:
        if not e.get("tentative") or id(e) in matched_tentative:
            continue
        ann_d, ev_d = _d(e.get("announcement_date")), _d(e.get("date"))
        if td is None or ev_d is None:
            continue
        due = (ann_d <= td) if ann_d else (ev_d <= td + timedelta(days=TENTATIVE_WINDOW_DAYS))
        if due:
            overdue.append(f"{e['date']} {e.get('label') or tenor_of(e)}"
                           + (f" (scheduled announcement {e['announcement_date']})" if ann_d else ""))
    if overdue:
        out.append(("HIGH", CHECK, f"{len(overdue)} tentative auction(s) past their announcement date and not announced in "
                                   f"TA_WS: {'; '.join(overdue[:4])}{' …' if len(overdue) > 4 else ''}"))
    return out


def treasury_source_findings(calendar_path: str | Path = DEFAULT_CAL, timeout: int = 20) -> list[tuple[str, str, str]]:
    """What the nightly referee calls: load the calendar and the announced list, run the check."""
    try:
        cal = json.load(open(calendar_path))
    except Exception as e:  # noqa: BLE001
        return [("CRITICAL", CHECK, f"event calendar unreadable: {type(e).__name__}: {e}")]
    announced, status = load_announced(calendar_path, timeout=timeout)
    return check_treasury_source(cal, announced, fetch_status=status)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CAL
    fs = treasury_source_findings(path)
    for sev, chk, det in fs:
        print(f"{sev:8s} {chk}  {det}")
    print(f"{len(fs)} finding(s)" if fs else f"{CHECK}: clear")
