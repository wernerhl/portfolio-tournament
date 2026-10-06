#!/usr/bin/env python3
"""
provider_checks.py — provider-data sanity checks (Execution Order: Revision of the Entry-State Indicator and
Related Fixes, 6 October 2026, section 4).

Two provider errors reached recommendations in October. Nightly, for every analyzed name (the canonical
fundamentals), three checks; a failed check flags the field "provider data suspect" with the reason:

  forwardPE      the forward and the trailing P/E (both positive) differ by more than a factor of three
                 (Texas Pacific Land showed 4.7 and 44)
  freeCashflow   the provider's free cash flow has the opposite sign of operating cash flow minus capital
                 expenditure in the latest 10-Q or 10-K in EDGAR (TPL showed negative free cash flow against
                 a reported 63% free-cash-flow margin)
  revenueGrowth  quarterly revenue growth above 30% while the prior four quarters' year-on-year growth averaged
                 less than half of it, from EDGAR's quarterly revenue: "check for one-time items" (Incyte's
                 second quarter included $246.0 million from a CMS settlement)

A flagged field is shown greyed out on the cards and is excluded from the screen's scores
(scripts/screen/score_universe.py) until the next filing clears it: the flag holds while the check fails, and
after it passes it holds until a filing newer than the one on record when it was raised.

EDGAR (company-concept API, the declared contact SEC_USER_AGENT, rate-limited and cached by
ownership/edgar_common.py) is refreshed per name when its summary is older than --max-age-days, at most --batch
names per run. Without SEC_USER_AGENT the EDGAR checks keep the last summary and the P/E check still runs.

Writes data/provider_flags.json.  Usage:  python scripts/provider_checks.py [--all] [--tickers TPL,INCY] [--batch 100]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "ownership"))
REPO = HERE.parent
DATA = REPO / "data"
OUT = DATA / "provider_flags.json"
CANON = DATA / "canonical" / "fundamentals.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"   # one request per company (the company-concept
# endpoint returned empty unit lists for some concepts, e.g. Incyte's operating cash flow, on 6 Oct 2026)
OCF = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
         "PaymentsToAcquireOilAndGasPropertyAndEquipment", "PaymentsForCapitalImprovements"]
REVENUE = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
           "SalesRevenueNet"]
FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")
PE_FACTOR, REV_SPIKE, REV_HALF = 3.0, 0.30, 0.5


def log(m: str) -> None:
    print(f"[provider_checks] {m}", flush=True)


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def facts_of(gaap: dict, concepts: list[str]) -> tuple[str | None, list[dict]]:
    """Among the given us-gaap concepts, the one whose periodic-filing USD facts reach the latest period (a company
    can switch concepts: Incyte reported revenue as Revenues to 2022, then as RevenueFromContract...)."""
    best, best_end = (None, []), None
    for c in concepts:
        rows = [f for f in ((gaap.get(c) or {}).get("units", {}).get("USD") or []) if f.get("form") in FORMS and f.get("end")]
        if not rows:
            continue
        end = max(f["end"] for f in rows)
        if best_end is None or end > best_end:
            best, best_end = (c, rows), end
    return best


def dedupe(rows: list[dict]) -> list[dict]:
    """One fact per (start, end): the latest filed."""
    out = {}
    for f in sorted(rows, key=lambda f: f.get("filed", "")):
        out[(f.get("start"), f["end"])] = f
    return list(out.values())


def latest_ytd(rows: list[dict]) -> dict | None:
    """The latest period's fact with the longest duration (the year-to-date cash-flow figure of a 10-Q)."""
    rows = [f for f in dedupe(rows) if f.get("start")]
    if not rows:
        return None
    end = max(f["end"] for f in rows)
    same = [f for f in rows if f["end"] == end]
    return max(same, key=lambda f: (_d(f["end"]) - _d(f["start"])).days)


def quarterly(rows: list[dict]) -> list[dict]:
    """Quarterly revenue: 3-month facts, plus a fourth quarter derived from the annual figure less the three
    quarters inside its year where the 10-K reports only the year."""
    rows = [f for f in dedupe(rows) if f.get("start")]
    q = {}
    for f in rows:
        days = (_d(f["end"]) - _d(f["start"])).days
        if 80 <= days <= 100:
            q[f["end"]] = float(f["val"])
    for f in rows:
        days = (_d(f["end"]) - _d(f["start"])).days
        if 350 <= days <= 380 and f["end"] not in q:
            inside = [e for e in q if _d(f["start"]) < _d(e) < _d(f["end"]) - timedelta(days=20)]
            if len(inside) == 3:
                q[f["end"]] = float(f["val"]) - sum(q[e] for e in inside)
    return [{"end": e, "val": v} for e, v in sorted(q.items())]


def yoy(qs: list[dict]) -> list[dict]:
    out = []
    for i, x in enumerate(qs):
        prior = [y for y in qs[:i] if 345 <= (_d(x["end"]) - _d(y["end"])).days <= 385]
        if prior and prior[-1]["val"] > 0:
            out.append({"end": x["end"], "growth": round(x["val"] / prior[-1]["val"] - 1, 4)})
    return out


def edgar_summary(client, cik: str) -> dict:
    s = {"cik": cik, "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    j = client.get_json(FACTS_URL.format(cik=cik), max_age_s=6 * 86400, allow_404=True) or {}
    gaap = (j.get("facts") or {}).get("us-gaap") or {}
    oc_name, oc_rows = facts_of(gaap, OCF)
    cx_name, cx_rows = facts_of(gaap, CAPEX)
    rv_name, rv_rows = facts_of(gaap, REVENUE)
    filings = [f for f in (oc_rows + rv_rows) if f.get("accn")]
    if filings:
        lf = max(filings, key=lambda f: (f.get("filed", ""), f.get("accn", "")))
        s["latest_filing"] = {"form": lf.get("form"), "accn": lf.get("accn"), "filed": lf.get("filed"),
                              "period_end": max(f["end"] for f in filings if f.get("accn") == lf.get("accn"))}
    o = latest_ytd(oc_rows) if oc_rows else None
    if o:
        cap = None
        if cx_rows:
            cap = next((f for f in dedupe(cx_rows) if f.get("start") == o["start"] and f["end"] == o["end"]), None)
        s["cash_flow"] = {"concept_ocf": oc_name, "concept_capex": cx_name if cap else None, "start": o["start"], "end": o["end"],
                          "form": o.get("form"), "ocf": float(o["val"]), "capex": float(cap["val"]) if cap else 0.0,
                          "capex_note": None if cap else "no capital-expenditure fact for the period (taken as 0)"}
        s["cash_flow"]["fcf"] = s["cash_flow"]["ocf"] - s["cash_flow"]["capex"]
    if rv_rows:
        qs = quarterly(rv_rows)
        s["revenue"] = {"concept": rv_name, "quarters": qs[-9:], "yoy": yoy(qs)[-5:]}
    return s


def money(x: float | None) -> str:
    if x is None:
        return "—"
    a = abs(x)
    return ("−" if x < 0 else "+") + (f"${a / 1e9:.2f}B" if a >= 1e9 else f"${a / 1e6:.1f}M")


def checks(f: dict, ed: dict | None) -> list[dict]:
    """The failed checks for one name: [{field, check, reason}]."""
    out = []
    fpe, tpe = f.get("forwardPE"), f.get("trailingPE")
    if fpe and tpe and fpe > 0 and tpe > 0 and max(fpe, tpe) / min(fpe, tpe) > PE_FACTOR:
        out.append({"field": "forwardPE", "check": "pe_mismatch",
                    "reason": f"forward P/E {fpe:.1f} and trailing P/E {tpe:.1f} differ by more than a factor of three"})
    cf = (ed or {}).get("cash_flow")
    pfcf = f.get("freeCashflow")
    if cf and pfcf is not None and pfcf != 0 and cf["fcf"] != 0 and (pfcf > 0) != (cf["fcf"] > 0):
        out.append({"field": "freeCashflow", "check": "fcf_sign",
                    "reason": (f"provider free cash flow {money(pfcf)} has the opposite sign of the {cf['form']} for {cf['start']} to {cf['end']}: "
                               f"operating cash flow {money(cf['ocf'])} less capital expenditure {money(cf['capex'])} = {money(cf['fcf'])}")})
    rg = f.get("revenueGrowth")
    yy = ((ed or {}).get("revenue") or {}).get("yoy") or []
    # the provider's growth figure refers to its most recent quarter; when EDGAR does not hold that quarter yet
    # (its latest is older), all of EDGAR's last four year-on-year figures are "the prior four"
    mrq = f.get("mostRecentQuarter")
    mrq_end = datetime.fromtimestamp(mrq).date() if isinstance(mrq, (int, float)) else None
    lagging = bool(yy) and ((mrq_end is not None and _d(yy[-1]["end"]) < mrq_end - timedelta(days=20)) or
                            (mrq_end is None and (date.today() - _d(yy[-1]["end"])).days > 135))
    if rg is not None and rg > REV_SPIKE and len(yy) >= (4 if lagging else 5):
        prior = yy[-4:] if lagging else yy[-5:-1]
        prior4 = [x["growth"] for x in prior]
        avg = sum(prior4) / 4
        if avg < REV_HALF * rg:
            out.append({"field": "revenueGrowth", "check": "revenue_spike",
                        "reason": (f"quarterly revenue growth {rg * 100:.1f}% against an average of {avg * 100:.1f}% over the prior four quarters "
                                   f"(EDGAR, quarters to {prior[-1]['end']}): check for one-time items")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--max-age-days", type=int, default=7)
    a = ap.parse_args()
    canon = json.loads(CANON.read_text()).get("tickers", {})
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    names = prev.get("names", {})
    tks = [t.strip().upper() for t in a.tickers.split(",") if t.strip()] or sorted(canon)
    # EDGAR refresh (rolling): names whose summary is missing or older than max-age, oldest first
    client, table, refreshed, warn = None, None, 0, None
    if os.environ.get("SEC_USER_AGENT"):
        import edgar_common as ec
        client = ec.EdgarClient()
        table = ec.company_tickers(client)
        old = lambda tk: not ((names.get(tk) or {}).get("edgar") or {}).get("fetched_at") or \
            date.fromisoformat(names[tk]["edgar"]["fetched_at"][:10]) < date.today() - timedelta(days=a.max_age_days)
        todo = sorted([t for t in tks if old(t)], key=lambda t: (((names.get(t) or {}).get("edgar") or {}).get("fetched_at") or ""))
        if a.tickers:
            todo = tks                                       # named tickers are always refreshed
        elif not a.all:
            todo = todo[:a.batch]
        for tk in todo:
            cik = ec.cik_for(tk.replace(".", "-"), table) or ec.cik_for(tk, table)
            if not cik:
                names.setdefault(tk, {})["edgar"] = {"fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"), "note": "no CIK in company_tickers.json"}
                continue
            try:
                names.setdefault(tk, {})["edgar"] = edgar_summary(client, cik); refreshed += 1
            except Exception as e:  # noqa: BLE001
                log(f"{tk}: EDGAR {type(e).__name__}: {e}")
    else:
        warn = "SEC_USER_AGENT not set: EDGAR summaries kept as on record; the P/E check ran"
        log(warn)
    today = datetime.now().astimezone().isoformat(timespec="seconds")
    n_flag = 0
    for tk in tks:
        f = canon.get(tk) or {}
        rec = names.setdefault(tk, {})
        ed = rec.get("edgar")
        failed = {c["field"]: c for c in checks(f, ed)}
        latest_accn = ((ed or {}).get("latest_filing") or {}).get("accn")
        kept = []
        for fl in rec.get("flags", []):                     # a flag clears only after a newer filing and a passing check
            if fl["field"] in failed:
                continue
            if latest_accn and fl.get("filing_at_flag") and latest_accn != fl["filing_at_flag"]:
                continue
            kept.append({**fl, "status": "check passes; held until the next filing"})
        for fld, c in failed.items():
            prior = next((x for x in rec.get("flags", []) if x["field"] == fld), None)
            kept.append({**c, "status": "check fails", "flagged_at": (prior or {}).get("flagged_at") or today,
                         "filing_at_flag": (prior or {}).get("filing_at_flag") or latest_accn})
        rec["flags"] = kept
        rec["fields"] = {k: f.get(k) for k in ("shortName", "forwardPE", "trailingPE", "freeCashflow", "revenueGrowth",
                                              "operatingCashflow", "marketCap", "grossMargins", "operatingMargins")}
        n_flag += bool(kept)
    keep = {tk: v for tk, v in names.items() if tk in canon}
    payload = {"cadence": "daily", "as_of": json.loads(CANON.read_text()).get("provenance", {}).get("session_date"),
               "computed_at": today, "order": "Execution Order: Revision of the Entry-State Indicator (6 October 2026), section 4",
               "checks": {"forwardPE": "forward and trailing P/E differ by more than a factor of three",
                          "freeCashflow": "provider free cash flow has the opposite sign of operating cash flow less capital expenditure in the latest 10-Q/10-K",
                          "revenueGrowth": "quarterly revenue growth above 30% while the prior four quarters averaged less than half of it"},
               "rule": "a flagged field is greyed out and excluded from the screen's scores until the next filing clears it",
               "edgar_refreshed_this_run": refreshed, "warning": warn,
               "names": keep}
    OUT.write_text(json.dumps(payload, indent=1, default=str))
    flagged = {tk: [x["field"] for x in v["flags"]] for tk, v in keep.items() if v.get("flags")}
    log(f"{len(keep)} names; EDGAR refreshed {refreshed}; {n_flag} names flagged: {dict(list(flagged.items())[:12])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
