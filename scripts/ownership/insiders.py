#!/usr/bin/env python3
"""insiders.py — E1 insider purchases, nightly → data/ownership/insiders.json (order 30-Sept-2026).

From the Form 4 feed: every open-market transaction (transaction code P = purchase, S = sale;
nonDerivative table only) for the held names and the top-40 board over the last 90 days, each
insider classified routine or opportunistic by the Cohen, Malloy and Pomorski rule — an insider who
traded in the same calendar month in each of the three prior calendar years is routine; every other
insider is opportunistic (an insider with fewer than three prior years of trading history at the
company is opportunistic by the rule, and the classification_basis says so). Held-name cards get
the opportunistic purchases of the window (insider, role, shares, dollars, date) and a cluster flag
when three or more distinct opportunistic insiders buy within 30 days; sales are shown only when
opportunistic AND clustered, under the label "sales are mostly compensation or diversification".
Board names get the flag and the counts only.

Descriptive. Opportunistic-purchase clusters are a REGISTERED CANDIDATE signal for the Phase 5
validation on the union universe (reports/insider_signal_registration_2026-09-30.md); it enters no
score before it passes, and nothing here is a recommendation.

Sources: the live Form 4 XML documents from each issuer's EDGAR submissions feed (the last 90
days), and the SEC quarterly Insider Transactions data sets for the three prior years, extracted
once per quarter for the union universe into data/ownership/insider_history.parquet (the store,
with insider_history_meta.json beside it) so a quarter is downloaded only once.

CLI: --offline FIXTURE_DIR (fixture Form 4 XMLs + fixture data-set TSVs, no network; requires
--data-dir or --dry-run so fixture output never lands in the repository's data/), --cache-dir,
--dry-run (compute and print, write nothing), --as-of YYYY-MM-DD (window end), --data-dir (output
root; tests). Live mode with SEC_USER_AGENT unset: prints what it would fetch, writes nothing,
exits 3.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import edgar_common as ec  # noqa: E402

JOB = "insiders"
WINDOW_DAYS = 90
CLUSTER_DAYS = 30
CLUSTER_MIN = 3
HISTORY_YEARS = 3
OPEN_MARKET = ("P", "S")
SALES_LABEL = "sales are mostly compensation or diversification"
CITATION = ('Cohen, Malloy and Pomorski (2012), "Decoding Inside Information", '
            "Journal of Finance 67(3), 1009-1043")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")
STORE_NAME = "insider_history.parquet"
STORE_META_NAME = "insider_history_meta.json"
STORE_COLS = ["quarter", "ticker", "issuer_cik", "accession", "filing_date", "insider_cik", "insider", "role",
              "owner_ciks", "co_owners", "date", "code", "shares", "price", "acq_disp", "ownership", "security"]

METHOD = {
    "rule": ("Cohen, Malloy and Pomorski: an insider who made an open-market trade (purchase or sale) in the same "
             "calendar month in each of the three prior calendar years is routine; every other insider is "
             "opportunistic. An insider with fewer than three prior calendar years of trading history at the company "
             "is opportunistic by the rule, and each trade's classification_basis states which case applies."),
    "citation": CITATION,
    "open_market": ("Form 4 nonDerivative transactions with code P (open-market purchase) or S (open-market sale) only; "
                    "codes A, F, M, G, C, D, J, W and every derivative-table row are ignored and counted; "
                    "dollars = shares × price per share as reported; amendments (4/A) are not re-counted."),
    "window": "transactions dated within the last %d calendar days through as_of" % WINDOW_DAYS,
    "cluster": ("flag when %d or more distinct opportunistic insiders buy with purchase dates spanning at most %d "
                "calendar days; the window reported is the %d-day span holding the most distinct buyers (the latest on "
                "ties) and its start/end are the first and last purchase dates inside it; sales get the same test and "
                "are shown only when opportunistic and clustered" % (CLUSTER_MIN, CLUSTER_DAYS, CLUSTER_DAYS)),
    "attribution": ("a filing with several reporting owners is one transaction attributed to the first-listed owner "
                    "(co-owners recorded); the trading history that classifies an owner includes every filing that lists "
                    "that owner; distinct insiders are distinct reporting-owner CIKs"),
    "history": ("prior three calendar years from the SEC quarterly Insider Transactions data sets (Form 4 rows) plus "
                "the live feed, keyed by issuer CIK and insider CIK; all share classes of the issuer count as trades at "
                "the company (the security title is recorded on each trade)"),
    "sales_label": SALES_LABEL,
}


def log(m: str) -> None:
    print("[%s] %s" % (JOB, m), flush=True)


# ── Form 4 XML ───────────────────────────────────────────────────────────
def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _t(el, path: str) -> str:
    if el is None:
        return ""
    x = el.find(path)
    if x is None:
        return ""
    # values sit either directly in the element or under a <value> child
    if x.text and x.text.strip():
        return x.text.strip()
    v = x.find("value")
    return (v.text or "").strip() if v is not None and v.text else ""


def _flag(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes")


def role_text(is_officer: bool, is_director: bool, is_ten: bool, is_other: bool,
              officer_title: str = "", other_text: str = "") -> str:
    parts = []
    if is_officer:
        parts.append(officer_title.strip() or "Officer")
    if is_director:
        parts.append("Director")
    if is_ten:
        parts.append("10% owner")
    if is_other:
        parts.append(other_text.strip() or "Other")
    return ", ".join(parts) if parts else "reporting owner"


def parse_form4(xml_bytes: bytes) -> dict:
    """The ownership document: issuer, reporting owners (in filing order), the open-market
    nonDerivative transactions, and a count of every ignored row by code."""
    root = _strip_ns(ET.fromstring(xml_bytes))
    doc = {"document_type": _t(root, "documentType"), "period_of_report": ec.parse_sec_date(_t(root, "periodOfReport")),
           "issuer_cik": ec.cik10(_t(root, "issuer/issuerCik")), "issuer_name": _t(root, "issuer/issuerName"),
           "symbol": _t(root, "issuer/issuerTradingSymbol").upper(), "owners": [], "transactions": [], "ignored": {}}
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        o = {"cik": ec.cik10(_t(ro, "reportingOwnerId/rptOwnerCik")), "name": _t(ro, "reportingOwnerId/rptOwnerName"),
             "is_director": _flag(_t(rel, "isDirector")), "is_officer": _flag(_t(rel, "isOfficer")),
             "is_ten_percent": _flag(_t(rel, "isTenPercentOwner")), "is_other": _flag(_t(rel, "isOther")),
             "officer_title": _t(rel, "officerTitle"), "other_text": _t(rel, "otherText")}
        o["role"] = role_text(o["is_officer"], o["is_director"], o["is_ten_percent"], o["is_other"],
                              o["officer_title"], o["other_text"])
        doc["owners"].append(o)
    ignored: Counter = Counter()
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _t(tx, "transactionCoding/transactionCode").upper()
        if code not in OPEN_MARKET:
            ignored[code or "?"] += 1
            continue
        shares = ec.num(_t(tx, "transactionAmounts/transactionShares"))
        price = ec.num(_t(tx, "transactionAmounts/transactionPricePerShare"))
        doc["transactions"].append({
            "date": ec.parse_sec_date(_t(tx, "transactionDate")), "code": code, "shares": shares, "price": price,
            "acq_disp": _t(tx, "transactionAmounts/transactionAcquiredDisposedCode").upper(),
            "ownership": _t(tx, "ownershipNature/directOrIndirectOwnership").upper(),
            "security": _t(tx, "securityTitle"),
            "owned_after": ec.num(_t(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction"))})
    n_deriv = len(root.findall("derivativeTable/derivativeTransaction"))
    if n_deriv:
        ignored["derivative"] += n_deriv
    doc["ignored"] = dict(ignored)
    return doc


def trades_from_form4(doc: dict, accession: str, filing_date: str | None, filing_url: str | None,
                      ticker: str | None, source: str) -> list[dict]:
    owners = doc.get("owners") or []
    if not owners:
        return []
    p = owners[0]
    out = []
    for tx in doc["transactions"]:
        if not tx.get("date"):
            continue
        sh, px = tx.get("shares"), tx.get("price")
        out.append({"ticker": ticker or doc.get("symbol") or "", "issuer_cik": doc["issuer_cik"], "accession": accession,
                    "filing_date": filing_date, "filing_url": filing_url, "insider_cik": p["cik"], "insider": p["name"],
                    "role": p["role"], "owner_ciks": [o["cik"] for o in owners], "co_owners": [o["name"] for o in owners[1:]],
                    "date": tx["date"], "code": tx["code"], "shares": sh, "price": px,
                    "dollars": (round(sh * px, 2) if sh is not None and px is not None else None),
                    "acq_disp": tx.get("acq_disp"), "ownership": tx.get("ownership"), "security": tx.get("security"),
                    "source": source})
    return out


# ── quarterly data sets → history rows ───────────────────────────────────
def _dataset_role(relationship: str, title: str) -> str:
    r = (relationship or "").upper()
    return role_text("OFFICER" in r, "DIRECTOR" in r, "TENPERCENT" in r or "10%" in r, "OTHER" in r, title or "", "")


def _first_col(cols, *names) -> str | None:
    for n in names:
        if n in cols:
            return n
    return None


def extract_quarter(source: Path, quarter: str, cik_set: set[str], ticker_by_cik: dict[str, str]) -> list[dict]:
    """Form 4 open-market rows (P/S) of the issuers in `cik_set` from one quarterly data set
    (zip or unpacked directory). Column names are matched upper-cased; optional ones tolerated."""
    sub = ec.read_tsv(source, "SUBMISSION.tsv")
    cols = set(sub.columns)
    acc_col = _first_col(cols, "ACCESSION_NUMBER", "ACCESSION_NO")
    iss_col = _first_col(cols, "ISSUERCIK", "ISSUER_CIK")
    if not acc_col or not iss_col:
        raise ValueError("%s SUBMISSION.tsv lacks ACCESSION_NUMBER/ISSUERCIK (columns: %s)" % (source, sorted(cols)[:12]))
    form_col = _first_col(cols, "FORM_TYPE", "DOCUMENT_TYPE", "SUBMISSIONTYPE")
    fd_col = _first_col(cols, "FILING_DATE", "FILINGDATE")
    sym_col = _first_col(cols, "ISSUERTRADINGSYMBOL", "ISSUER_TRADING_SYMBOL")
    sub["_CIK"] = sub[iss_col].map(ec.cik10)
    keep = sub[sub["_CIK"].isin(cik_set)]
    if form_col:
        keep = keep[keep[form_col].astype(str).str.strip().str.upper() == "4"]
    meta = {}
    for _, r in keep.iterrows():
        meta[str(r[acc_col]).strip()] = {"issuer_cik": r["_CIK"], "filing_date": ec.parse_sec_date(r[fd_col]) if fd_col else None,
                                         "symbol": str(r[sym_col]).strip().upper() if sym_col else ""}
    if not meta:
        return []
    acc_set = set(meta)
    own = ec.read_tsv(source, "REPORTINGOWNER.tsv")
    oc = set(own.columns)
    o_acc = _first_col(oc, "ACCESSION_NUMBER", "ACCESSION_NO")
    o_cik = _first_col(oc, "RPTOWNERCIK", "RPTOWNER_CIK")
    o_name = _first_col(oc, "RPTOWNERNAME", "RPTOWNER_NAME")
    o_rel = _first_col(oc, "RPTOWNER_RELATIONSHIP", "RPTOWNERRELATIONSHIP")
    o_title = _first_col(oc, "RPTOWNER_TITLE", "RPTOWNERTITLE", "OFFICER_TITLE")
    owners: dict[str, list[dict]] = {}
    for _, r in own[own[o_acc].astype(str).str.strip().isin(acc_set)].iterrows():
        a = str(r[o_acc]).strip()
        owners.setdefault(a, []).append({
            "cik": ec.cik10(r[o_cik]) if o_cik else "", "name": str(r[o_name]).strip() if o_name else "",
            "role": _dataset_role(str(r[o_rel]) if o_rel else "", str(r[o_title]) if o_title else "")})
    rows: list[dict] = []
    for chunk in ec.iter_tsv(source, "NONDERIV_TRANS.tsv"):
        cc = set(chunk.columns)
        c_acc = _first_col(cc, "ACCESSION_NUMBER", "ACCESSION_NO")
        c_code = _first_col(cc, "TRANS_CODE", "TRANSACTION_CODE")
        c_date = _first_col(cc, "TRANS_DATE", "TRANSACTION_DATE")
        c_sh = _first_col(cc, "TRANS_SHARES", "TRANSACTION_SHARES")
        c_px = _first_col(cc, "TRANS_PRICEPERSHARE", "TRANS_PRICE_PER_SHARE", "TRANSACTION_PRICEPERSHARE")
        c_ad = _first_col(cc, "TRANS_ACQUIRED_DISP_CD", "TRANS_ACQUIRED_DISPOSED_CD", "ACQUIRED_DISPOSED_CODE")
        c_own = _first_col(cc, "DIRECT_INDIRECT_OWNERSHIP", "DIRECT_INDIRECT")
        c_sec = _first_col(cc, "SECURITY_TITLE", "SECURITYTITLE")
        if not (c_acc and c_code and c_date):
            raise ValueError("%s NONDERIV_TRANS.tsv lacks ACCESSION_NUMBER/TRANS_CODE/TRANS_DATE" % source)
        sel = chunk[chunk[c_acc].astype(str).str.strip().isin(acc_set) & chunk[c_code].astype(str).str.strip().str.upper().isin(OPEN_MARKET)]
        for _, r in sel.iterrows():
            a = str(r[c_acc]).strip()
            ow = owners.get(a) or [{"cik": "", "name": "", "role": "reporting owner"}]
            d = ec.parse_sec_date(r[c_date])
            if not d:
                continue
            sh, px = ec.num(r[c_sh]) if c_sh else None, ec.num(r[c_px]) if c_px else None
            m = meta[a]
            rows.append({"quarter": quarter, "ticker": ticker_by_cik.get(m["issuer_cik"]) or m["symbol"], "issuer_cik": m["issuer_cik"],
                         "accession": a, "filing_date": m["filing_date"], "filing_url": ec.archive_folder_url(m["issuer_cik"], a) if ec.ACCESSION_RE.match(a) else None,
                         "insider_cik": ow[0]["cik"], "insider": ow[0]["name"], "role": ow[0]["role"],
                         "owner_ciks": [o["cik"] for o in ow], "co_owners": [o["name"] for o in ow[1:]],
                         "date": d, "code": str(r[c_code]).strip().upper(), "shares": sh, "price": px,
                         "dollars": (round(sh * px, 2) if sh is not None and px is not None else None),
                         "acq_disp": str(r[c_ad]).strip().upper() if c_ad else "", "ownership": str(r[c_own]).strip().upper() if c_own else "",
                         "security": str(r[c_sec]).strip() if c_sec else "", "source": "dataset:" + quarter})
    return rows


# ── the history store ────────────────────────────────────────────────────
def load_store(store: Path) -> tuple[list[dict], dict]:
    meta_p = store.with_name(STORE_META_NAME)
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {"quarters": {}, "universe_ciks": []}
    if not store.exists():
        return [], meta
    import pandas as pd
    df = pd.read_parquet(store)
    rows = []
    for r in df.to_dict("records"):
        r["owner_ciks"] = [x for x in str(r.get("owner_ciks") or "").split("|") if x]
        r["co_owners"] = [x for x in str(r.get("co_owners") or "").split("|") if x]
        for k in ("shares", "price"):
            v = r.get(k)
            r[k] = None if v is None or v != v else float(v)
        r["dollars"] = round(r["shares"] * r["price"], 2) if r["shares"] is not None and r["price"] is not None else None
        r["source"] = "dataset:" + str(r.get("quarter"))
        r["filing_url"] = ec.archive_folder_url(r["issuer_cik"], r["accession"]) if ec.ACCESSION_RE.match(str(r.get("accession") or "")) else None
        rows.append(r)
    return rows, meta


def save_store(store: Path, rows: list[dict], meta: dict) -> None:
    import pandas as pd
    recs = []
    for r in rows:
        rec = {k: r.get(k) for k in STORE_COLS}
        rec["owner_ciks"] = "|".join(r.get("owner_ciks") or [])
        rec["co_owners"] = "|".join(r.get("co_owners") or [])
        recs.append(rec)
    df = pd.DataFrame(recs, columns=STORE_COLS)
    for c in STORE_COLS:
        if c in ("shares", "price"):
            df[c] = df[c].map(lambda v: float("nan") if v is None else float(v)).astype(float)
        else:
            df[c] = df[c].map(lambda v: "" if v is None else str(v)).astype(str)
    store.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(store, index=False)
    store.with_name(STORE_META_NAME).write_text(json.dumps(meta, indent=2))


def required_quarters(window_start: date, as_of: date) -> list[str]:
    """Every quarter of the calendar years y−3 … y−1 for each year y a window trade can fall in."""
    y0, y1 = window_start.year - HISTORY_YEARS, as_of.year - 1
    return [ec.quarter_tag(y, q) for y in range(y0, y1 + 1) for q in (1, 2, 3, 4)]


def _tkey(r: dict) -> tuple:
    return (r.get("accession"), r.get("date"), r.get("code"), r.get("shares"), r.get("price"), r.get("insider_cik"), r.get("security"))


def _dedup(rows: list[dict]) -> list[dict]:
    """One row per transaction; a live Form 4 row wins over its data-set duplicate."""
    seen: dict[tuple, dict] = {}
    for r in rows:
        k = _tkey(r)
        if k not in seen or not str(seen[k].get("source", "")).startswith("form4"):
            seen[k] = r
    return list(seen.values())


# ── classification ───────────────────────────────────────────────────────
def history_index(rows: list[dict]) -> dict[tuple[str, str], set[tuple[int, int]]]:
    """(issuer CIK, insider CIK) → {(year, month)} of open-market trades, every listed owner counted."""
    idx: dict[tuple[str, str], set[tuple[int, int]]] = {}
    for r in rows:
        if r.get("code") not in OPEN_MARKET or not r.get("date"):
            continue
        y, m = int(r["date"][:4]), int(r["date"][5:7])
        for cik in (r.get("owner_ciks") or [r.get("insider_cik")]):
            if cik:
                idx.setdefault((r["issuer_cik"], cik), set()).add((y, m))
    return idx


def classify(trade: dict, idx: dict) -> tuple[str, str]:
    """Cohen–Malloy–Pomorski for one trade: ("routine" | "opportunistic", basis)."""
    y, m = int(trade["date"][:4]), int(trade["date"][5:7])
    months = idx.get((trade["issuer_cik"], trade["insider_cik"]), set())
    prior = [y - k for k in range(1, HISTORY_YEARS + 1)]
    hit = [yy for yy in prior if (yy, m) in months]
    years_hist = sorted({yy for (yy, _) in months if yy in prior})
    mon = MONTHS[m - 1]
    if len(hit) == HISTORY_YEARS:
        return "routine", ("routine: traded in %s of %s (same calendar month in each of the three prior years)"
                           % (mon, ", ".join(str(x) for x in sorted(hit))))
    if len(years_hist) < HISTORY_YEARS:
        return "opportunistic", ("opportunistic by the rule: %d prior year(s) of trading history at the company (%s); "
                                 "the rule requires a trade in the same calendar month in each of the three prior years"
                                 % (len(years_hist), ", ".join(str(x) for x in years_hist) or "none"))
    missing = [yy for yy in sorted(prior) if yy not in hit]
    return "opportunistic", ("opportunistic: no open-market trade in %s of %s (traded in %s of %s); prior-year history %s"
                             % (mon, ", ".join(str(x) for x in missing), mon, ", ".join(str(x) for x in sorted(hit)) or "no year",
                                ", ".join(str(x) for x in years_hist)))


# ── clusters ─────────────────────────────────────────────────────────────
def cluster_of(trades: list[dict], kind: str = "buyers") -> dict:
    """The CLUSTER_DAYS-day span holding the most distinct insiders among `trades` (opportunistic
    trades of one code). Flag when that count reaches CLUSTER_MIN."""
    n_key = "n_distinct_%s_%dd" % (kind, CLUSTER_DAYS)
    rule = "%d or more distinct opportunistic %s with trade dates spanning at most %d calendar days" % (CLUSTER_MIN, kind, CLUSTER_DAYS)
    if not trades:
        return {"flag": False, n_key: 0, "window_start": None, "window_end": None, kind: [], "rule": rule}
    best = None
    for d0 in sorted({t["date"] for t in trades}):
        d1 = (date.fromisoformat(d0) + timedelta(days=CLUSTER_DAYS)).isoformat()
        inside = [t for t in trades if d0 <= t["date"] <= d1]
        people = {}
        for t in inside:
            people.setdefault(t["insider_cik"] or t["insider"], t["insider"])
        n = len(people)
        key = (n, len(inside), d0)                 # most distinct insiders, then most trades, then the latest start
        if best is None or key > best["key"]:
            best = {"n": n, "key": key, "inside": inside, "people": people}
    ins = best["inside"]
    return {"flag": best["n"] >= CLUSTER_MIN, n_key: best["n"],
            "window_start": min(t["date"] for t in ins), "window_end": max(t["date"] for t in ins),
            kind: sorted(set(best["people"].values())), "rule": rule, "_members": ins}


def card_row(t: dict, label: str, basis: str) -> dict:
    return {"insider": t["insider"], "insider_cik": t["insider_cik"], "role": t["role"], "shares": t["shares"],
            "price": t["price"], "dollars": t["dollars"], "date": t["date"], "filing_date": t.get("filing_date"),
            "filing_url": t.get("filing_url"), "ownership": {"D": "direct", "I": "indirect"}.get(t.get("ownership") or "", t.get("ownership") or None),
            "security": t.get("security") or None, "co_owners": t.get("co_owners") or [],
            "classification": label, "classification_basis": basis}


def analyze_name(tk: str, trades: list[dict], idx: dict, card: bool) -> dict:
    """Per name: classification of every window trade, the purchase cluster, the sales cluster, the
    card lists (held names) and the counts."""
    purchases = sorted([t for t in trades if t["code"] == "P"], key=lambda t: (t["date"], t["insider"]))
    sales = sorted([t for t in trades if t["code"] == "S"], key=lambda t: (t["date"], t["insider"]))
    opp_p, opp_s, rt_p, rt_s = [], [], 0, 0
    for t in purchases:
        lab, basis = classify(t, idx)
        if lab == "routine":
            rt_p += 1
        else:
            opp_p.append((t, basis))
    for t in sales:
        lab, basis = classify(t, idx)
        if lab == "routine":
            rt_s += 1
        else:
            opp_s.append((t, basis))
    cl = cluster_of([t for t, _ in opp_p], "buyers")
    scl = cluster_of([t for t, _ in opp_s], "sellers")
    members_s = {_tkey(t) for t in scl.pop("_members", [])}
    cl.pop("_members", None)
    out = {"card": card,
           "cluster": cl, "sales_cluster": scl,
           "counts": {"purchases_90d": {"opportunistic": len(opp_p), "routine": rt_p, "distinct_opportunistic_buyers": len({t["insider_cik"] for t, _ in opp_p})},
                      "sales_90d": {"opportunistic": len(opp_s), "routine": rt_s, "distinct_opportunistic_sellers": len({t["insider_cik"] for t, _ in opp_s})}},
           "routine_excluded": {"purchases": rt_p, "sales": rt_s},
           "sales_shown_label": SALES_LABEL}
    if card:
        out["opportunistic_purchases_90d"] = [card_row(t, "opportunistic", b) for t, b in opp_p]
        out["sales_shown"] = [card_row(t, "opportunistic", b) for t, b in opp_s if _tkey(t) in members_s] if scl["flag"] else []
        out["sales_shown_reason"] = ("opportunistic and clustered: shown" if scl["flag"] else
                                     "not shown: sales are listed only when opportunistic AND clustered (%d or more distinct sellers within %d days); %d opportunistic, %d routine in the window"
                                     % (CLUSTER_MIN, CLUSTER_DAYS, len(opp_s), rt_s))
    return out


# ── inputs: live feed or fixtures ────────────────────────────────────────
def load_fixture_universe(fx: Path) -> dict | None:
    p = fx / "universe.json"
    return json.loads(p.read_text()) if p.exists() else None


def fixture_form4s(fx: Path, ticker_by_cik: dict[str, str]) -> tuple[list[dict], dict]:
    """Every *.xml under FIXTURE_DIR/form4 as the live feed. Filing dates/URLs from an optional
    form4/filings.json {accession: {filingDate, primaryDocument}}; else the period of report."""
    d = fx / "form4"
    meta_p = d / "filings.json"
    fmeta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    rows, ignored, n = [], Counter(), 0
    for p in sorted(d.glob("*.xml")) if d.exists() else []:
        doc = parse_form4(p.read_bytes())
        acc = p.stem
        fm = fmeta.get(acc) or {}
        fd = ec.parse_sec_date(fm.get("filingDate")) or doc["period_of_report"]
        url = ec.archive_folder_url(doc["issuer_cik"], acc) if (ec.ACCESSION_RE.match(acc) and doc["issuer_cik"]) else "fixture:%s" % p.name
        rows += trades_from_form4(doc, acc, fd, url, ticker_by_cik.get(doc["issuer_cik"]), "form4")
        ignored.update(doc["ignored"])
        n += 1
    return rows, {"filings_parsed": n, "ignored_rows": dict(ignored)}


def fixture_datasets(fx: Path) -> list[tuple[str, Path]]:
    """(quarter tag, path) for every data set under FIXTURE_DIR/datasets (dirs or zips named like
    2025q3_form345)."""
    d = fx / "datasets"
    out = []
    if d.exists():
        for p in sorted(d.iterdir()):
            tag = p.name.split("_")[0].lower()
            if len(tag) == 6 and tag[4] == "q" and (p.is_dir() or p.suffix == ".zip"):
                out.append((tag, p))
    return out


def fixture_ciks(fx: Path, names: list[str]) -> dict[str, dict]:
    p = fx / "company_tickers.json"
    table = ec.company_tickers(raw=json.loads(p.read_text())) if p.exists() else {}
    if not table:                                   # derive from the fixture Form 4s' issuer blocks
        for x in sorted((fx / "form4").glob("*.xml")) if (fx / "form4").exists() else []:
            doc = parse_form4(x.read_bytes())
            if doc["symbol"] and doc["issuer_cik"]:
                table.setdefault(doc["symbol"], {"cik": doc["issuer_cik"], "title": doc["issuer_name"]})
    return {t: table[t] for t in names if t in table}


def live_form4s(client: ec.EdgarClient, names: list[str], table: dict[str, dict], since_iso: str,
                warnings: list[str]) -> tuple[list[dict], dict]:
    rows, per_name, ignored = [], {}, Counter()
    for tk in names:
        cik = ec.cik_for(tk, table)
        if not cik:
            warnings.append("%s: no CIK in company_tickers.json" % tk)
            per_name[tk] = {"cik": None, "filings": 0, "error": "no CIK"}
            continue
        try:
            filings, counts = ec.form4_filings(client, cik, since_iso)
        except Exception as e:
            warnings.append("%s: submissions feed failed (%s: %s)" % (tk, type(e).__name__, str(e)[:120]))
            per_name[tk] = {"cik": cik, "filings": 0, "error": "submissions: %s" % type(e).__name__}
            continue
        n_ok = 0
        for f in filings:
            acc = f.get("accessionNumber") or ""
            try:
                url = ec.form4_document_url(client, cik, acc, f.get("primaryDocument"))
                xml = client.get(url, cache_name="form4/%s.xml" % acc.replace("-", ""))
                doc = parse_form4(xml)
                rows += trades_from_form4(doc, acc, f.get("filingDate"), url, tk, "form4")
                ignored.update(doc["ignored"])
                n_ok += 1
            except Exception as e:
                warnings.append("%s: Form 4 %s not parsed (%s: %s)" % (tk, acc, type(e).__name__, str(e)[:100]))
        per_name[tk] = {"cik": cik, "filings": len(filings), "parsed": n_ok, "amendments_skipped": counts.get("form4_amendments_skipped", 0)}
    return rows, {"per_name": per_name, "ignored_rows": dict(ignored)}


# ── the run ──────────────────────────────────────────────────────────────
def build_payload(names_held: list[str], names_board: list[str], cik_by_ticker: dict[str, str], trades_all: list[dict],
                  as_of: date, window_start: date, coverage: dict, source: dict, warnings: list[str],
                  session_date: str, now_iso: str, status: str) -> dict:
    idx = history_index(trades_all)
    lo, hi = window_start.isoformat(), as_of.isoformat()
    names: dict[str, dict] = {}
    board: dict[str, dict] = {}
    for tk in sorted(set(names_held) | set(names_board)):
        cik = cik_by_ticker.get(tk)
        roles = (["held"] if tk in names_held else []) + (["board"] if tk in names_board else [])
        win = [t for t in trades_all if t["issuer_cik"] == cik and cik and lo <= t["date"] <= hi]
        a = analyze_name(tk, win, idx, card=(tk in names_held))
        a.update({"roles": roles, "cik": cik, "window_trades": len(win)})
        if not cik:
            a["note"] = "no CIK resolved; nothing scanned"
        elif not win:
            a["note"] = "no open-market Form 4 transactions in the window (foreign private issuers file no Form 4)"
        names[tk] = dict(sorted(a.items()))
        if tk in names_board:
            board[tk] = {"cluster_flag": a["cluster"]["flag"], "n_distinct_buyers_30d": a["cluster"]["n_distinct_buyers_%dd" % CLUSTER_DAYS],
                         "cluster_window": [a["cluster"]["window_start"], a["cluster"]["window_end"]],
                         "sales_cluster_flag": a["sales_cluster"]["flag"], "counts": a["counts"], "routine_excluded": a["routine_excluded"], "held": tk in names_held}
    return {
        "cadence": "daily", "session_date": session_date, "as_of": as_of.isoformat(), "computed_at": now_iso,
        "fetched_at": source.get("fetched_at"), "status": status,
        "source": source,
        "window": {"start": lo, "end": hi, "days": WINDOW_DAYS, "cluster_days": CLUSTER_DAYS, "cluster_min_distinct": CLUSTER_MIN},
        "method": METHOD,
        "history_coverage": coverage,
        "universe": {"held": names_held, "board": names_board},
        "names": names, "board": board,
        "warnings": warnings,
        "signal_registration": {"candidate": "opportunistic-purchase clusters", "status": "registered, not validated; enters no score",
                                "document": "reports/insider_signal_registration_2026-09-30.md"},
        "note": ("descriptive: open-market insider purchases and sales with the routine/opportunistic classification; "
                 "the cluster flag is a registered candidate for validation on the union universe and enters no score before "
                 "it passes; nothing here is a recommendation"),
    }


def run(args) -> tuple[int, dict | None]:
    tc = ec.calendar()
    now = tc.now_et()
    as_of = date.fromisoformat(args.as_of) if args.as_of else now.date()
    window_start = as_of - timedelta(days=WINDOW_DAYS)
    session_date = tc.last_completed_session()
    warnings: list[str] = []
    data_dir = Path(args.data_dir) if args.data_dir else ec.DATA
    out_path = data_dir / "ownership" / "insiders.json"
    req_q = required_quarters(window_start, as_of)

    if args.offline:
        fx = Path(args.offline)
        if not args.data_dir and not args.dry_run:
            log("--offline needs --data-dir or --dry-run: fixture output never lands in the repository's data/")
            return 2, None
        uni = load_fixture_universe(fx) or ec.universe()
        held, board = uni["held"], uni["board"]
        names = sorted(set(held) | set(board))
        table = fixture_ciks(fx, names)
        cik_by_ticker = {t: table[t]["cik"] for t in names if t in table}
        ticker_by_cik = {v: k for k, v in cik_by_ticker.items()}
        for t in names:
            if t not in cik_by_ticker:
                warnings.append("%s: no CIK in the fixture" % t)
        live_rows, feed_info = fixture_form4s(fx, ticker_by_cik)
        hist_rows, loaded, missing = [], [], []
        avail = dict(fixture_datasets(fx))
        for q in req_q:
            if q in avail:
                hist_rows += extract_quarter(avail[q], q, set(cik_by_ticker.values()), ticker_by_cik)
                loaded.append(q)
            else:
                missing.append(q)
        extra = [q for q in sorted(avail) if q not in req_q]
        for q in extra:                            # fixtures outside the required years still count as history
            hist_rows += extract_quarter(avail[q], q, set(cik_by_ticker.values()), ticker_by_cik)
        coverage = {"years_required": sorted({int(q[:4]) for q in req_q}), "quarters_required": req_q, "quarters_loaded": loaded + extra,
                    "quarters_missing": missing, "complete": not missing, "store": "fixture:%s" % (fx / "datasets"), "rows": len(hist_rows)}
        source = {"mode": "offline_fixture", "fixture_dir": str(fx), "fetched_at": None, "user_agent_declared": ec.user_agent_declared(),
                  "feed": feed_info}
        status = "offline_fixture"
    else:
        plan = [ec.COMPANY_TICKERS_URL]
        uni = ec.universe()
        held, board = uni["held"], uni["board"]
        names = sorted(set(held) | set(board))
        if not ec.user_agent_declared():
            plan += ["%s/submissions/CIK<cik of %s>.json + its Form 4 documents since %s" % (ec.HOST_DATA, t, window_start.isoformat()) for t in names]
            store_p = Path(args.history_store) if args.history_store else ec.OWN / STORE_NAME
            _, meta0 = load_store(store_p)
            plan += [ec.insider_dataset_candidates(int(q[:4]), int(q[5]))[0] + " (or the datastandardsinnovation prefix)"
                     for q in req_q if q not in (meta0.get("quarters") or {})]
            return ec.no_ua_exit(JOB, plan), None
        client = ec.EdgarClient(cache_dir=args.cache_dir)
        table = ec.company_tickers(client)
        cik_by_ticker = {t: table[t]["cik"] for t in names if t in table}
        ticker_by_cik = {v: k for k, v in cik_by_ticker.items()}
        union = ec.union_universe()
        union_ciks = {table[t]["cik"] for t in union if t in table} | set(cik_by_ticker.values())
        union_t_by_cik = {table[t]["cik"]: t for t in union if t in table}
        union_t_by_cik.update(ticker_by_cik)
        store_p = Path(args.history_store) if args.history_store else ec.OWN / STORE_NAME
        store_rows, meta = load_store(store_p)
        qmeta = meta.setdefault("quarters", {})
        known_ciks = set(meta.get("universe_ciks") or [])
        new_ciks = union_ciks - known_ciks
        loaded, missing, fetched_now = [], [], []
        for q in req_q:
            have = q in qmeta
            if have and not new_ciks:
                loaded.append(q)
                continue
            y, qq = int(q[:4]), int(q[5])
            path, url = client.fetch_first(ec.insider_dataset_candidates(y, qq), "datasets/%s_form345.zip" % q)
            if path is None:
                (loaded if have else missing).append(q)
                if not have:
                    warnings.append("%s: insider data set not found under either prefix" % q)
                continue
            try:
                rows_q = extract_quarter(path, q, union_ciks, union_t_by_cik)
            except Exception as e:
                warnings.append("%s: data set unreadable (%s: %s)" % (q, type(e).__name__, str(e)[:100]))
                (loaded if have else missing).append(q)
                continue
            store_rows = [r for r in store_rows if r.get("quarter") != q] + rows_q
            qmeta[q] = {"file": path.name, "source_url": url, "rows": len(rows_q), "fetched_at": now.isoformat(timespec="seconds"),
                        "sha256": ec.sha256_file(path), "issuers_scoped": len(union_ciks)}
            loaded.append(q)
            fetched_now.append(q)
        meta["universe_ciks"] = sorted(union_ciks)
        meta.update({"cadence": "on_change", "as_of": as_of.isoformat(), "scope": "open-market Form 4 rows (codes P and S) for the union universe (data/universe.txt), one extract per quarterly data set",
                     "note": "history store for the routine/opportunistic classification; not a served panel"})
        hist_rows = store_rows
        live_rows, feed_info = live_form4s(client, names, table, window_start.isoformat(), warnings)
        coverage = {"years_required": sorted({int(q[:4]) for q in req_q}), "quarters_required": req_q, "quarters_loaded": loaded,
                    "quarters_missing": missing, "complete": not missing, "store": str(store_p.relative_to(ec.REPO)) if store_p.is_relative_to(ec.REPO) else str(store_p),
                    "rows": len(hist_rows), "fetched_this_run": fetched_now}
        source = {"mode": "live", "feed": "EDGAR submissions + Form 4 ownership XML (data.sec.gov, www.sec.gov); SEC quarterly Insider Transactions data sets",
                  "fetched_at": now.isoformat(timespec="seconds"), "user_agent_declared": True, "requests": client.requests_made,
                  "cache_hits": client.cache_hits, "per_name": feed_info["per_name"], "ignored_rows": feed_info["ignored_rows"]}
        failed = [t for t, v in feed_info["per_name"].items() if v.get("error")]
        status = "ok" if not failed and not missing else "partial"
        if failed:
            warnings.append("names without a feed this run: %s" % failed)
        if not args.dry_run:
            save_store(store_p, store_rows, meta)

    trades_all = _dedup(live_rows + hist_rows)
    payload = build_payload(held, board, cik_by_ticker, trades_all, as_of, window_start, coverage, source, warnings,
                            session_date, now.isoformat(timespec="seconds"), status)
    n_flags = [t for t, n in payload["names"].items() if n["cluster"]["flag"]]
    log("as_of %s window %s..%s session %s status %s; %d names; history rows %d (quarters %s); cluster flags: %s"
        % (as_of, window_start, as_of, session_date, status, len(payload["names"]), len(hist_rows),
           ",".join(coverage["quarters_loaded"]) or "none", n_flags or "none"))
    if args.dry_run:
        log("dry run: nothing written")
        return 0, payload
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    log("wrote %s" % out_path)
    return 0, payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="E1 insider purchases → data/ownership/insiders.json")
    ap.add_argument("--offline", metavar="FIXTURE_DIR", default=None, help="fixture Form 4 XMLs and data-set TSVs instead of the network")
    ap.add_argument("--cache-dir", default=None, help="download cache (default: scratch/edgar_cache or OWNERSHIP_CACHE_DIR)")
    ap.add_argument("--dry-run", action="store_true", help="compute and print; write nothing")
    ap.add_argument("--as-of", default=None, help="window end YYYY-MM-DD (default: today, ET)")
    ap.add_argument("--data-dir", default=None, help="output root (default: the repository's data/)")
    ap.add_argument("--history-store", default=None, help="parquet history store (default: data/ownership/insider_history.parquet)")
    args = ap.parse_args(argv)
    rc, _ = run(args)
    return rc


if __name__ == "__main__":
    sys.exit(main())
