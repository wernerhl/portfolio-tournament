#!/usr/bin/env python3
"""holders_13f.py — E2 institutional ownership, context only, weekly → data/ownership/holders_13f.json
(order 30-Sept-2026).

For each held name, from the SEC quarterly Form 13F data sets: the latest available quarter-end, the
ten largest holders by shares (name, shares, value, share change on the quarter, prior shares,
disclosure date = the fund's filing date), and the new positions and full exits among funds whose
13F table value is at least $1 billion. Every figure object carries `as_of_quarter_end` and
`disclosed`, and each name carries the caption "positions as of {quarter-end}, disclosed {date};
long positions only; no hedges shown." where {date} is the latest filing date among the holders
shown. No signal, no score.

Conventions (also written into the file under `method`):
  * long positions only: rows with PUTCALL set are excluded, and only SSHPRNAMTTYPE == "SH" counts;
  * one filing per manager and quarter: the latest RESTATEMENT amendment replaces the original, a
    NEW HOLDINGS amendment is added to it; the disclosure date is the latest filing date used;
  * a fund's AUM is its SUMMARYPAGE TABLEVALUETOTAL (dollars for periods from 2023; thousands before,
    scaled here); the $1 billion screen uses the filing of the quarter the figure describes;
  * a full exit needs a current-quarter filing that shows no position; a prior holder without a
    current filing is listed apart (not an exit, the fund may have stopped filing or filed late);
  * shares reported by more than one manager under shared discretion are not de-duplicated (as
    reported);
  * CUSIPs are derived from the INFOTABLE itself: the majority CUSIP among rows whose NAMEOFISSUER
    starts with the company's core name (class hint applied — GOOG is Alphabet's class C, GOOGL
    class A; they are kept apart), recorded with its provenance under `cusip_map`.

CLI: --offline FIXTURE_DIR (fixture data-set directories under FIXTURE_DIR/13f; requires --data-dir
or --dry-run), --cache-dir, --dry-run, --as-of YYYY-MM-DD, --data-dir, --max-age-days N (default 7:
the weekly cadence built in — a live run exits 0 without any fetch while the served file's as_of is
younger than N days; 0 forces a refresh). Live mode with SEC_USER_AGENT unset: prints what it would
fetch, writes nothing, exits 3.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import edgar_common as ec  # noqa: E402

JOB = "holders_13f"
AUM_FLOOR = 1e9
TOP_N = 10
CAPTION = "positions as of {quarter_end}, disclosed {date}; long positions only; no hedges shown."
VALUE_DOLLARS_FROM = "2023-01-01"           # 13F values are whole dollars for periods from here; thousands before

# Core-name and share-class hints for the names on the book. The CUSIP itself is always derived from
# the data; the hint only steers the NAMEOFISSUER match and the class split. A name absent here is
# matched on the core of its company_tickers.json title.
ISSUER_HINTS = {
    "NVDA": ("NVIDIA", None), "AVGO": ("BROADCOM", None), "GOOG": ("ALPHABET", "C"), "GOOGL": ("ALPHABET", "A"),
    "GEV": ("GE VERNOVA", None), "BMNR": ("BITMINE IMMERSION", None), "MU": ("MICRON TECHNOLOGY", None),
    "ANET": ("ARISTA NETWORKS", None),
}
# Reference CUSIPs for a consistency warning only; never used as the mapping.
CUSIP_REFERENCE = {"NVDA": "67066G104", "AVGO": "11135F101", "GOOG": "02079K107", "GOOGL": "02079K305",
                   "MU": "595112103", "ANET": "040413106"}
SUFFIXES = {"INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "PLC", "LLC", "LP", "HOLDINGS", "HLDGS", "GROUP",
            "GRP", "THE", "NEW", "DEL", "DE", "SA", "NV", "AG", "COM", "COMMON", "STOCK", "SHS", "ADR", "ADS", "CL"}

METHOD = {
    "scope": "quarterly Form 13F data sets (SUBMISSION, COVERPAGE, SUMMARYPAGE, INFOTABLE); held names only; context, no signal, no score",
    "long_only": "rows with PUTCALL set are excluded (no hedges shown); only SSHPRNAMTTYPE = SH counts; values as reported (whole dollars for periods from %s, thousands before, scaled)" % VALUE_DOLLARS_FROM,
    "one_filing_per_manager_quarter": "the latest RESTATEMENT amendment replaces the original 13F-HR; NEW HOLDINGS amendments are added; the disclosure date is the latest filing date used",
    "top_holders": "the %d largest holders by shares at the latest quarter-end; share change against the same manager's prior-quarter filing (prior shares null when the manager has no prior filing in the data sets loaded)" % TOP_N,
    "new_and_exits": "new positions: held now, not held (or no filing) in the prior quarter; full exits: held in the prior quarter, current filing shows none; both restricted to managers whose TABLEVALUETOTAL for that quarter is at least $%d" % int(AUM_FLOOR),
    "no_current_filing": "prior holders without a current-quarter filing are listed apart, not as exits",
    "shared_discretion": "shares reported by more than one manager under shared discretion are not de-duplicated",
    "cusip": "derived from INFOTABLE: majority CUSIP (by distinct filings) among rows whose NAMEOFISSUER starts with the company's core name, class hint applied; provenance under cusip_map",
    "caption": CAPTION,
}


def log(m: str) -> None:
    print("[%s] %s" % (JOB, m), flush=True)


# ── name matching and CUSIP derivation ───────────────────────────────────
def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", str(s or "").upper())).strip()


def core_name(title: str) -> str:
    words = [w for w in norm_name(title).split() if w not in SUFFIXES]
    if not words:
        return norm_name(title)
    if len(words[0]) >= 5 or len(words) == 1:
        return words[0]
    return " ".join(words[:2])


def matcher_for(ticker: str, title: str | None) -> tuple[str, str | None]:
    """(core name prefix, class hint) for a held name."""
    if ticker in ISSUER_HINTS:
        return ISSUER_HINTS[ticker]
    return core_name(title or ticker), None


def class_of(title_of_class: str) -> str | None:
    t = norm_name(title_of_class)
    m = re.search(r"\b(?:CL|CLASS)\s*([A-C])\b", t)
    return m.group(1) if m else None


def name_matches(name_norm: str, core: str) -> bool:
    return name_norm == core or name_norm.startswith(core + " ")


# ── data sets ────────────────────────────────────────────────────────────
def load_filings(source: Path) -> dict[str, dict]:
    """accession → {cik, filing_date, type, period, manager, is_amendment, amendment_type, aum}."""
    sub = ec.read_tsv(source, "SUBMISSION.tsv")
    cover = ec.read_tsv(source, "COVERPAGE.tsv")
    summ = ec.read_tsv(source, "SUMMARYPAGE.tsv") if ec.has_member(source, "SUMMARYPAGE.tsv") else None
    cov = {str(r["ACCESSION_NUMBER"]).strip(): r for r in cover.to_dict("records")} if "ACCESSION_NUMBER" in cover.columns else {}
    sm = {str(r["ACCESSION_NUMBER"]).strip(): r for r in summ.to_dict("records")} if summ is not None and "ACCESSION_NUMBER" in summ.columns else {}
    out = {}
    for r in sub.to_dict("records"):
        acc = str(r.get("ACCESSION_NUMBER", "")).strip()
        if not acc:
            continue
        c, s = cov.get(acc, {}), sm.get(acc, {})
        period = ec.parse_sec_date(r.get("PERIODOFREPORT") or c.get("REPORTCALENDARORQUARTER"))
        aum = ec.num(s.get("TABLEVALUETOTAL"))
        if aum is not None and period and period < VALUE_DOLLARS_FROM:
            aum *= 1000.0
        out[acc] = {"accession": acc, "cik": ec.cik10(r.get("CIK")), "filing_date": ec.parse_sec_date(r.get("FILING_DATE")),
                    "type": str(r.get("SUBMISSIONTYPE", "")).strip().upper(), "period": period,
                    "manager": str(c.get("FILINGMANAGER_NAME", "")).strip() or None,
                    "is_amendment": str(c.get("ISAMENDMENT", "")).strip().upper() in ("Y", "YES", "TRUE", "1"),
                    "amendment_type": str(c.get("AMENDMENTTYPE", "")).strip().upper() or None, "aum": aum}
    return out


def scan_infotable(source: Path, matchers: dict[str, tuple[str, str | None]], chunksize: int = 200_000) -> tuple[list[dict], int]:
    """Rows of INFOTABLE whose NAMEOFISSUER starts with a held name's core name. Returns (rows, rows scanned)."""
    rows, scanned = [], 0
    cores = {tk: core for tk, (core, _) in matchers.items()}
    for chunk in ec.iter_tsv(source, "INFOTABLE.tsv", chunksize=chunksize):
        scanned += len(chunk)
        if "NAMEOFISSUER" not in chunk.columns:
            raise ValueError("%s INFOTABLE.tsv lacks NAMEOFISSUER" % source)
        names = chunk["NAMEOFISSUER"].map(norm_name)
        mask = None
        for core in set(cores.values()):
            m = (names == core) | names.str.startswith(core + " ")
            mask = m if mask is None else (mask | m)
        if mask is None or not mask.any():
            continue
        sel = chunk[mask].copy()
        sel["_NAME"] = names[mask]
        for r in sel.to_dict("records"):
            hits = [tk for tk, core in cores.items() if name_matches(r["_NAME"], core)]
            r["_TICKERS"] = hits
            rows.append(r)
    return rows, scanned


def derive_cusips(rows: list[dict], matchers: dict[str, tuple[str, str | None]], sources: list[str]) -> dict[str, dict]:
    """Majority CUSIP per ticker among its matched rows (class hint applied), with provenance."""
    out = {}
    for tk, (core, cls) in matchers.items():
        cand = [r for r in rows if tk in r["_TICKERS"]]
        if cls:
            cand = [r for r in cand if class_of(r.get("TITLEOFCLASS", "")) == cls]
        by: dict[str, set] = {}
        variants: dict[str, dict[str, int]] = {}
        for r in cand:
            cu = str(r.get("CUSIP", "")).strip().upper()
            if not cu:
                continue
            by.setdefault(cu, set()).add(str(r.get("ACCESSION_NUMBER", "")).strip())
            variants.setdefault(cu, {})
            key = "%s | %s" % (str(r.get("NAMEOFISSUER", "")).strip(), str(r.get("TITLEOFCLASS", "")).strip())
            variants[cu][key] = variants[cu].get(key, 0) + 1
        if not by:
            out[tk] = {"cusip": None, "provenance": "no INFOTABLE row with NAMEOFISSUER starting %r%s in %s" % (core, (" and class %s" % cls) if cls else "", sources)}
            continue
        best = max(by, key=lambda c: (len(by[c]), c))
        top_var = sorted(variants[best].items(), key=lambda kv: -kv[1])[:3]
        rec = {"cusip": best, "core_name": core, "class": cls, "distinct_filings": len(by[best]),
               "name_variants": [{"name_and_class": k, "rows": v} for k, v in top_var],
               "other_cusips_seen": {c: len(by[c]) for c in sorted(by) if c != best},
               "provenance": "majority CUSIP among INFOTABLE rows whose NAMEOFISSUER starts with %r%s, by distinct filings, in %s"
                             % (core, (" with class %s in TITLEOFCLASS" % cls) if cls else "", ", ".join(sources))}
        ref = CUSIP_REFERENCE.get(tk)
        if ref and ref != best:
            rec["warning"] = "derived CUSIP %s differs from the reference %s; the derived one is served" % (best, ref)
        out[tk] = rec
    return out


# ── positions ────────────────────────────────────────────────────────────
def effective_filings(filings: list[dict]) -> tuple[list[dict], dict | None]:
    """For one manager and quarter: the filings whose rows count, and the base filing (AUM, type)."""
    originals = sorted([f for f in filings if not f["is_amendment"] and f["type"].startswith("13F-HR")], key=lambda f: f["filing_date"] or "")
    restates = sorted([f for f in filings if f["is_amendment"] and f["amendment_type"] == "RESTATEMENT"], key=lambda f: f["filing_date"] or "")
    adds = sorted([f for f in filings if f["is_amendment"] and f["amendment_type"] == "NEW HOLDINGS"], key=lambda f: f["filing_date"] or "")
    base = restates[-1] if restates else (originals[-1] if originals else None)
    if base is None:
        if adds:                                  # amendment without its original in the data sets loaded
            return adds, adds[-1]
        others = sorted([f for f in filings if f["type"].startswith("13F-HR")], key=lambda f: f["filing_date"] or "")
        return (others[-1:], others[-1]) if others else ([], None)
    used = [base] + [a for a in adds if (a["filing_date"] or "") >= (base["filing_date"] or "")]
    return used, base


def positions_for(rows: list[dict], filings: dict[str, dict], cusip: str, period: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """(holders, filers) for one CUSIP and quarter-end. holders: manager CIK → figures (shares > 0);
    filers: every manager with an effective filing for the period (shares may be 0)."""
    by_mgr: dict[str, list[dict]] = {}
    for f in filings.values():
        if f["period"] == period and f["cik"] and f["type"].startswith("13F-HR"):
            by_mgr.setdefault(f["cik"], []).append(f)
    rows_by_acc: dict[str, list[dict]] = {}
    for r in rows:
        if str(r.get("CUSIP", "")).strip().upper() != cusip:
            continue
        if str(r.get("PUTCALL", "")).strip():
            continue                                  # long positions only
        if str(r.get("SSHPRNAMTTYPE", "")).strip().upper() != "SH":
            continue
        rows_by_acc.setdefault(str(r.get("ACCESSION_NUMBER", "")).strip(), []).append(r)
    holders, filers = {}, {}
    for cik, fl in by_mgr.items():
        used, base = effective_filings(fl)
        if base is None:
            continue
        shares = value = 0.0
        for f in used:
            for r in rows_by_acc.get(f["accession"], []):
                shares += ec.num(r.get("SSHPRNAMT")) or 0.0
                v = ec.num(r.get("VALUE")) or 0.0
                value += v * (1000.0 if period < VALUE_DOLLARS_FROM else 1.0)
        rec = {"manager": base["manager"] or cik, "manager_cik": cik, "shares": shares, "value_usd": round(value, 2), "aum_usd": base["aum"],
               "disclosed": max((f["filing_date"] or "") for f in used) or None,
               "filings_used": [f["type"] + (" " + (f["amendment_type"] or "")).rstrip() for f in used], "as_of_quarter_end": period}
        filers[cik] = rec
        if shares > 0:
            holders[cik] = rec
    return holders, filers


def analyze_name(tk: str, cusip: str, rows: list[dict], filings: dict[str, dict], latest: str, prior: str) -> dict:
    now_h, now_f = positions_for(rows, filings, cusip, latest)
    pr_h, pr_f = positions_for(rows, filings, cusip, prior)

    def fig(rec: dict, **extra) -> dict:
        d = {"manager": rec["manager"], "manager_cik": rec["manager_cik"], "shares": rec["shares"], "value_usd": rec["value_usd"],
             "aum_usd": rec["aum_usd"], "as_of_quarter_end": rec["as_of_quarter_end"], "disclosed": rec["disclosed"], "filings_used": rec["filings_used"]}
        d.update(extra)
        return d

    top = []
    for i, (cik, rec) in enumerate(sorted(now_h.items(), key=lambda kv: (-kv[1]["shares"], kv[1]["manager"]))[:TOP_N], 1):
        p = pr_f.get(cik)
        prior_shares = p["shares"] if p is not None else None
        top.append(fig(rec, rank=i, prior_shares=prior_shares, share_change=(rec["shares"] - (prior_shares or 0.0)),
                       share_change_pct=(round((rec["shares"] / prior_shares - 1) * 100, 2) if prior_shares else None),
                       prior_status=("held" if prior_shares else ("none" if p is not None else "no prior filing")),
                       prior_disclosed=(p["disclosed"] if p is not None else None), prior_quarter_end=prior))
    new_big, new_small = [], 0
    for cik, rec in sorted(now_h.items(), key=lambda kv: -kv[1]["shares"]):
        p = pr_f.get(cik)
        if p is not None and p["shares"] > 0:
            continue
        if (rec["aum_usd"] or 0) >= AUM_FLOOR:
            new_big.append(fig(rec, prior_status=("none" if p is not None else "no prior filing"), prior_quarter_end=prior))
        else:
            new_small += 1
    exits_big, exits_small, no_filing = [], 0, []
    for cik, prec in sorted(pr_h.items(), key=lambda kv: -kv[1]["shares"]):
        cur = now_f.get(cik)
        if cur is None:
            no_filing.append({"manager": prec["manager"], "manager_cik": cik, "prior_shares": prec["shares"], "prior_aum_usd": prec["aum_usd"],
                              "as_of_quarter_end": prior, "disclosed": prec["disclosed"], "status": "no current-quarter filing in the data sets loaded"})
            continue
        if cur["shares"] > 0:
            continue
        if (cur["aum_usd"] or 0) >= AUM_FLOOR:
            exits_big.append({"manager": cur["manager"], "manager_cik": cik, "prior_shares": prec["shares"], "prior_value_usd": prec["value_usd"],
                              "shares": 0.0, "aum_usd": cur["aum_usd"], "as_of_quarter_end": latest, "disclosed": cur["disclosed"],
                              "prior_quarter_end": prior, "prior_disclosed": prec["disclosed"], "filings_used": cur["filings_used"]})
        else:
            exits_small += 1
    shown = top + new_big + exits_big
    latest_disc = max((x["disclosed"] or "" for x in shown), default="") or None
    return {"cusip": cusip, "as_of_quarter_end": latest, "prior_quarter_end": prior, "disclosed_latest": latest_disc,
            "caption": CAPTION.format(quarter_end=latest, date=latest_disc or "n/a"),
            "top_holders": top, "new_positions_over_1b": new_big, "full_exits_over_1b": exits_big, "prior_holders_without_current_filing": no_filing,
            "counts": {"holders_latest": len(now_h), "holders_prior": len(pr_h), "filers_latest": len(now_f), "filers_prior": len(pr_f),
                       "new_positions_below_1b": new_small, "full_exits_below_1b": exits_small,
                       "shares_reported_latest": sum(r["shares"] for r in now_h.values()), "shares_reported_prior": sum(r["shares"] for r in pr_h.values())},
            "aum_floor_usd": AUM_FLOOR}


# ── data-set selection ───────────────────────────────────────────────────
def fixture_datasets(fx: Path) -> list[Path]:
    d = fx / "13f"
    return sorted(p for p in d.iterdir() if (p.is_dir() or p.suffix == ".zip") and "13f" in p.name.lower()) if d.exists() else []


def live_datasets(client: ec.EdgarClient, as_of: date, warnings: list[str]) -> list[tuple[Path, str, date]]:
    """The newest two posted data sets (path, url, quarter-end), newest first; a not-yet-posted window
    is skipped with a warning."""
    got: list[tuple[Path, str, date]] = []
    for qe in ec.f13_quarter_ends_available(as_of, 5):
        cands = ec.f13_dataset_candidates(qe)
        _, _, tag = ec.f13_window_for(qe)
        path, url = client.fetch_first(cands, "datasets/%s_form13f.zip" % tag)
        if path is None:
            warnings.append("13F data set for quarter-end %s (%s) not posted under either prefix or naming" % (qe, tag))
            continue
        got.append((path, url, qe))
        if len(got) == 2:
            break
    return got


def build(datasets: list[tuple[Path, str]], held: list[str], titles: dict[str, str], as_of: date, now_iso: str,
          source: dict, warnings: list[str], status: str) -> dict:
    filings: dict[str, dict] = {}
    rows: list[dict] = []
    matchers = {tk: matcher_for(tk, titles.get(tk)) for tk in held}
    used = []
    for path, url in datasets:
        f = load_filings(path)
        filings.update(f)
        r, scanned = scan_infotable(path, matchers)
        rows += r
        periods = sorted({v["period"] for v in f.values() if v["period"]})
        used.append({"file": path.name, "source_url": url, "filing_window": _window_of(path.name), "filings": len(f),
                     "quarter_ends_in_file": periods[-3:], "infotable_rows_scanned": scanned, "matched_rows": len(r),
                     "sha256": ec.sha256_file(path) if path.is_file() else None})
    periods = sorted({v["period"] for v in filings.values() if v["period"] and v["type"].startswith("13F-HR")})
    if not periods:
        raise RuntimeError("no 13F-HR filings in the data sets loaded")
    latest = periods[-1]
    prior = ec.quarter_end(*_prev_quarter(latest)).isoformat()
    cusips = derive_cusips(rows, matchers, [u["file"] for u in used])
    names = {}
    for tk in held:
        cu = cusips[tk].get("cusip")
        if not cu:
            names[tk] = {"cusip": None, "as_of_quarter_end": latest, "prior_quarter_end": prior, "disclosed_latest": None,
                         "caption": CAPTION.format(quarter_end=latest, date="n/a"), "top_holders": [], "new_positions_over_1b": [],
                         "full_exits_over_1b": [], "prior_holders_without_current_filing": [], "counts": {}, "note": cusips[tk]["provenance"]}
            warnings.append("%s: %s" % (tk, cusips[tk]["provenance"]))
            continue
        names[tk] = analyze_name(tk, cu, rows, filings, latest, prior)
    return {"cadence": "weekly", "as_of": as_of.isoformat(), "computed_at": now_iso, "status": status,
            "source": source, "datasets_used": used, "quarters": {"latest": latest, "prior": prior},
            "cusip_map": cusips, "method": METHOD, "universe": {"held": held}, "names": names, "warnings": warnings,
            "note": "context only: positions as disclosed on Form 13F, long positions only, no hedges shown; no signal, no score, no recommendation"}


def _prev_quarter(period_iso: str) -> tuple[int, int]:
    y, q = ec.quarter_of(date.fromisoformat(period_iso))
    return (y - 1, 4) if q == 1 else (y, q - 1)


def _window_of(name: str) -> str | None:
    m = re.match(r"^(\d{2}[a-z]{3}\d{4})-(\d{2}[a-z]{3}\d{4})", name.lower())
    if m:
        return "%s..%s" % (m.group(1), m.group(2))
    m = re.match(r"^(\d{4})q([1-4])", name.lower())
    return "%sq%s" % (m.group(1), m.group(2)) if m else None


def run(args) -> tuple[int, dict | None]:
    tc = ec.calendar()
    now = tc.now_et()
    as_of = date.fromisoformat(args.as_of) if args.as_of else now.date()
    warnings: list[str] = []
    data_dir = Path(args.data_dir) if args.data_dir else ec.DATA
    out_path = data_dir / "ownership" / "holders_13f.json"
    if args.offline:
        fx = Path(args.offline)
        if not args.data_dir and not args.dry_run:
            log("--offline needs --data-dir or --dry-run: fixture output never lands in the repository's data/")
            return 2, None
        up = fx / "universe.json"
        held = (json.loads(up.read_text()) if up.exists() else ec.universe())["held"]
        ctp = fx / "company_tickers.json"
        table = ec.company_tickers(raw=json.loads(ctp.read_text())) if ctp.exists() else {}
        titles = {t: table[t]["title"] for t in held if t in table}
        ds = [(p, "fixture:%s" % p.name) for p in fixture_datasets(fx)]
        if not ds:
            log("no data sets under %s/13f" % fx)
            return 2, None
        source = {"mode": "offline_fixture", "fixture_dir": str(fx), "fetched_at": None, "user_agent_declared": ec.user_agent_declared()}
        status = "offline_fixture"
    else:
        if out_path.exists() and args.max_age_days > 0:
            try:
                prev = json.loads(out_path.read_text())
                prev_as_of = date.fromisoformat(str(prev.get("as_of"))[:10])
                age = (as_of - prev_as_of).days
                if 0 <= age < args.max_age_days:
                    log("served file as_of %s is %d day(s) old (< %d): weekly cadence, nothing to do" % (prev_as_of, age, args.max_age_days))
                    return 0, None
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        held = ec.universe()["held"]
        if not ec.user_agent_declared():
            plan = [ec.COMPANY_TICKERS_URL] + [ec.f13_dataset_candidates(qe)[0] + " (or its other prefix / naming)" for qe in ec.f13_quarter_ends_available(as_of, 2)]
            return ec.no_ua_exit(JOB, plan), None
        client = ec.EdgarClient(cache_dir=args.cache_dir)
        table = ec.company_tickers(client)
        titles = {t: table[t]["title"] for t in held if t in table}
        live = live_datasets(client, as_of, warnings)
        if len(live) < 2:
            log("fewer than two 13F data sets available (%d); nothing written" % len(live))
            for w in warnings:
                log("  " + w)
            return 1, None
        ds = [(p, u) for p, u, _ in live]
        source = {"mode": "live", "feed": "SEC quarterly Form 13F data sets (www.sec.gov)", "fetched_at": now.isoformat(timespec="seconds"),
                  "user_agent_declared": True, "requests": client.requests_made, "cache_hits": client.cache_hits}
        status = "ok" if not warnings else "partial"
    payload = build(ds, held, titles, as_of, now.isoformat(timespec="seconds"), source, warnings, status)
    if not args.offline:
        payload["status"] = "ok" if not payload["warnings"] else "partial"
    log("as_of %s quarters %s/%s; %d held names; data sets %s; status %s" % (
        as_of, payload["quarters"]["latest"], payload["quarters"]["prior"], len(held), [u["file"] for u in payload["datasets_used"]], payload["status"]))
    for tk, n in payload["names"].items():
        log("  %s cusip %s holders %s top1 %s" % (tk, n.get("cusip"), (n.get("counts") or {}).get("holders_latest"),
                                                 (n["top_holders"][0]["manager"] if n.get("top_holders") else "-")))
    if args.dry_run:
        log("dry run: nothing written")
        return 0, payload
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    log("wrote %s" % out_path)
    return 0, payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="E2 13F holders (context only) → data/ownership/holders_13f.json")
    ap.add_argument("--offline", metavar="FIXTURE_DIR", default=None, help="fixture 13F data sets under FIXTURE_DIR/13f instead of the network")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: today, ET)")
    ap.add_argument("--data-dir", default=None, help="output root (default: the repository's data/)")
    ap.add_argument("--max-age-days", type=int, default=7, help="live mode: skip while the served as_of is younger than this (0 = always refresh)")
    args = ap.parse_args(argv)
    rc, _ = run(args)
    return rc


if __name__ == "__main__":
    sys.exit(main())
