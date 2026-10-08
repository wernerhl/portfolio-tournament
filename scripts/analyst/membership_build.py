#!/usr/bin/env python3
"""
membership_build.py — the S&P 500 membership file from June 2004, with ticker changes (second follow-up order of
7 October 2026, G2).

Sources
  2004-06 to the first Wikipedia revision of 2012   the dated components list of github.com/fja05680/sp500 (MIT
                                                     licence; "S&P 500 Historical Components & Changes (Updated)"),
                                                     one row per date with the member tickers: the latest row at or
                                                     before each month-end (cached copy: --components)
  2012-01 to date                                    the Wikipedia list's revision in force at each month-end
                                                     (scripts/analyst/sp500_membership.py's cache), with the CIK and
                                                     the company name where the revision carries them
For the overlap (2012 to 2026) the two sources are compared month by month; where they differ the Wikipedia
revision is used and the cases are listed (data/analyst/membership_source_comparison.json).

Ticker changes (data/analyst/ticker_changes.csv), by method, in the order they are applied:
  sec_cik_confirmed            the 36 pairs confirmed by SEC CIK delivered with the order
  components_list_continuity   the components list carries each company under its later symbol (MDLZ for Kraft
                               Foods throughout, where a Wikipedia revision of 2012 says KFT): a Wikipedia symbol
                               whose run of disagreement with the list starts in the same month as one list symbol's
                               run and ends within two months of it, leaves Wikipedia at the end of the run, and whose
                               counterpart was not in Wikipedia before, is the same company; where several pairs share
                               a start month the SEC's former names of the candidate's CIK decide (data.sec.gov
                               submissions, fetched with SEC_USER_AGENT and cached outside the repository); the rest is
                               reported unresolved in the comparison file
  wikipedia_cik_continuity     the same CIK under a new symbol in consecutive Wikipedia rows (CIKs from May 2014)
  wikipedia_name_continuity    the same Security name under a new symbol in consecutive rows, before the CIKs
  sec_company_tickers_cik      a member whose symbol the SEC no longer lists, found under its CIK's first (primary)
                               ticker in company_tickers.json
Chains are resolved to the current symbol; a cycle (FISV -> FI -> FISV) resolves to the symbol in the latest month-end.
Where a pair's older side is the symbol listed today or at the SEC and the other side is not (the list carries WYND
where today's symbol is TNL), the direction is reversed, unless the other side is a bankruptcy symbol (BTUUQ).
Every member row carries `ticker` (as the source lists it) and `ticker_current`. Before 2012 no source gives the
symbol of the day: the repository's "original" list carries the same later symbols as its "(Updated)" list.

Bounds (H1, third follow-up of 7 October 2026). A change is applied to a row under the old symbol only up to
`valid_to` - the last month-end the old symbol is listed before the new one first appears in the file - and only to
the company that made the change: the row's CIK (where it carries one; before May 2014 the CIK of its run of
consecutive month-ends, where any row of the run carries one) must be the change's; a row with a name and no CIK must
share a word of a name the company had under the old symbol; and the change is withheld when the new symbol is listed
in the same month-end for another company. A second share class whose history the new symbol does not carry (DISCK
beside DISCA) stays under its own symbol. A symbol's earlier holder (Chubb Corp under CB until ACE took the symbol,
Allergan Inc under AGN until Actavis took it) is set apart as SYMBOL-YYYYMM, the month its run ends, so that it takes
no bars. The file carries no duplicate (month-end, ticker_current) pair; the referee checks
(membership:duplicate_current_symbol). The CSV records valid_to, the names, `applies` and the note.

Outputs
  data/analyst/sp500_membership_history.parquet   month_end, ticker, ticker_current, cik, name, source, revid, rev_time
  data/analyst/sp500_membership_meta.json
  data/analyst/membership_source_comparison.json
  data/analyst/ticker_changes.csv

Usage:  python scripts/analyst/membership_build.py --components <csv> --cache <wiki cache dir> [--from 2004-06-30]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sp500_membership as sm   # noqa: E402  (fetch with cache, revision lookup, Throttle)

REPO = HERE.parent.parent
AN = REPO / "data" / "analyst"
OUT = AN / "sp500_membership_history.parquet"
META = AN / "sp500_membership_meta.json"
CMP = AN / "membership_source_comparison.json"
CHANGES = AN / "ticker_changes.csv"


def log(m: str) -> None:
    print(f"[membership_build] {m}", flush=True)


def norm(t: str) -> str:
    return re.sub(r"\[.*?\]", "", str(t)).strip().upper().replace(".", "-")


STOP = {"inc", "corp", "co", "the", "ltd", "plc", "company", "incorporated", "corporation", "group", "holdings", "holding",
        "international", "intl", "and", "of", "de", "cos", "companies", "limited", "class", "a", "b", "c", "common", "stock",
        "series", "new", "nv", "sa", "ag", "se"}


def name_tokens(nm) -> set:
    """The words of a company name that identify it (no corporate suffixes, no share-class words)."""
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", str(nm).lower()).split() if t and t not in STOP}


def wiki_rows(html: str) -> pd.DataFrame:
    """Symbol, Security (name) and CIK from the list table of a revision; empty where the revision lacks them."""
    for t in pd.read_html(StringIO(html)):
        cols = {str(c).strip().lower(): c for c in t.columns}
        sym = next((cols[k] for k in ("symbol", "ticker symbol", "ticker") if k in cols), None)
        if sym is None or len(t) < 400:
            continue
        name = next((cols[k] for k in ("security", "company", "name") if k in cols), None)
        cik = next((cols[k] for k in ("cik",) if k in cols), None)
        df = pd.DataFrame({"ticker": [norm(x) for x in t[sym].astype(str)],
                           "name": t[name].astype(str).str.strip() if name is not None else None,
                           "cik": pd.to_numeric(t[cik], errors="coerce").astype("Int64") if cik is not None else pd.array([None] * len(t), dtype="Int64")})
        df = df[df["ticker"].str.fullmatch(r"[A-Z0-9\-]{1,6}")]
        if len(df) >= 400:
            return df.drop_duplicates("ticker")
    return pd.DataFrame(columns=["ticker", "name", "cik"])


def components_rows(components_csv: Path, start: str, end: str) -> dict[str, set]:
    m = pd.read_csv(components_csv); m["date"] = pd.to_datetime(m["date"]); m = m.sort_values("date")
    out = {}
    for me in pd.date_range(start, end, freq="ME"):
        row = m[m["date"] <= me]
        if not len(row):
            continue
        out[me.strftime("%Y-%m-%d")] = {norm(t) for t in str(row.iloc[-1]["tickers"]).split(",") if t.strip()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--components", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--from", dest="start", default="2004-06-30")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--sec-tickers", default=None, help="the SEC's company_tickers.json (cached): CIK -> current ticker")
    a = ap.parse_args()
    end = a.end or (pd.Timestamp.today().normalize() - pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")
    sec_t2c = {}
    if a.sec_tickers and Path(a.sec_tickers).exists():
        for v in json.load(open(a.sec_tickers)).values():
            sec_t2c.setdefault(norm(v["ticker"]), int(v["cik_str"]))
    cache = Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    th = sm.Throttle()
    # ── Wikipedia revisions, 2012-01 onward (cached), with names and CIKs
    wiki: dict[str, pd.DataFrame] = {}; revmeta = {}
    for me in [d.strftime("%Y-%m-%d") for d in pd.date_range("2012-01-31", end, freq="ME")]:
        rv = sm.revision_at(me, cache, th)
        if not rv:
            continue
        revid, ts = rv
        html = sm.fetch(f"https://en.wikipedia.org/w/index.php?title={sm.TITLE}&oldid={revid}", cache, th)
        df = wiki_rows(html)
        if len(df) >= 400:
            wiki[me] = df; revmeta[me] = {"revid": revid, "rev_time": ts, "n": int(len(df)), "with_cik": int(df["cik"].notna().sum()), "with_name": int(df["name"].notna().sum()) if "name" in df else 0}
    first_wiki = min(wiki)
    log(f"Wikipedia revisions: {len(wiki)} month-ends from {first_wiki}; CIK present from {min((k for k, v in revmeta.items() if v['with_cik'] >= 400), default='never')}")
    # ── the components list for 2004-06 up to the month before the first revision, and for the overlap comparison
    comp = components_rows(Path(a.components), a.start, end)
    comparison = []
    for me in sorted(wiki):
        if me in comp:
            w = set(wiki[me]["ticker"]); c = comp[me]
            comparison.append({"month_end": me, "wikipedia": len(w), "components": len(c), "differ": len(w ^ c),
                               "only_wikipedia": sorted(w - c)[:40], "only_components": sorted(c - w)[:40]})
    # ── the rows
    rows = []
    for me in sorted(comp):
        if me >= first_wiki:
            break
        for t in sorted(comp[me]):
            rows.append({"month_end": me, "ticker": t, "name": None, "cik": None, "source": "fja05680/sp500 components list (updated symbols)", "revid": None, "rev_time": None})
    for me in sorted(wiki):
        for r in wiki[me].itertuples():
            rows.append({"month_end": me, "ticker": r.ticker, "name": (r.name if isinstance(r.name, str) and r.name != "nan" else None),
                         "cik": (int(r.cik) if pd.notna(r.cik) else None), "source": "Wikipedia revision", "revid": revmeta[me]["revid"], "rev_time": revmeta[me]["rev_time"]})
    df = pd.DataFrame(rows); df["month_end"] = pd.to_datetime(df["month_end"])
    # ── ticker changes: confirmed pairs, CIK continuity, name continuity; chains resolved
    changes = pd.read_csv(CHANGES) if CHANGES.exists() else pd.DataFrame(columns=["old", "new", "method"])
    changes["old"] = changes["old"].map(norm); changes["new"] = changes["new"].map(norm)
    if "method" not in changes.columns:
        changes["method"] = None
    changes["method"] = changes["method"].fillna("sec_cik_confirmed")        # the delivered pairs, confirmed by CIK at the SEC
    if "source" not in changes.columns:
        changes["source"] = None
    changes["source"] = changes["source"].fillna("research/ml_stratification_test/ticker_changes_confirmed_2026-10-07.csv")
    known = {(o, n) for o, n in zip(changes["old"], changes["new"])}
    found = []
    latest_set = set(df[df["month_end"] == df["month_end"].max()]["ticker"])
    months = sorted(wiki)
    for i in range(1, len(months)):
        prev, cur = wiki[months[i - 1]], wiki[months[i]]
        # CIK continuity
        # a CIK listed twice (share classes: GOOG/GOOGL, FOX/FOXA, NWS/NWSA) is left out of the continuity test
        pc = prev.dropna(subset=["cik"]).drop_duplicates("cik", keep=False).set_index("cik")["ticker"]
        cc = cur.dropna(subset=["cik"]).drop_duplicates("cik", keep=False).set_index("cik")["ticker"]
        for cik in pc.index.intersection(cc.index):
            o, n = pc[cik], cc[cik]
            if o != n and (o, n) not in known and o not in set(cur["ticker"]):
                found.append({"old": o, "new": n, "method": "wikipedia_cik_continuity", "first_seen_new": months[i], "cik": int(cik), "source": f"revisions {revmeta[months[i-1]]['revid']} -> {revmeta[months[i]]['revid']}"})
                known.add((o, n))
        # name continuity where no CIK
        if prev["cik"].notna().sum() < 400 and "name" in prev and prev["name"].notna().any():
            pn = prev.dropna(subset=["name"]).drop_duplicates("name", keep=False).set_index("name")["ticker"]
            cn = cur.dropna(subset=["name"]).drop_duplicates("name", keep=False).set_index("name")["ticker"]
            for nm in pn.index.intersection(cn.index):
                o, n = pn[nm], cn[nm]
                if o != n and (o, n) not in known and o not in set(cur["ticker"]):
                    found.append({"old": o, "new": n, "method": "wikipedia_name_continuity", "first_seen_new": months[i], "name": nm, "source": f"revisions {revmeta[months[i-1]]['revid']} -> {revmeta[months[i]]['revid']}"})
                    known.add((o, n))
    if found:
        changes = pd.concat([changes, pd.DataFrame(found)], ignore_index=True)
    # the SEC company list: a member row with a CIK whose current SEC ticker differs is a change (the SEC company search)
    if a.sec_tickers and Path(a.sec_tickers).exists():
        sec = {}; sec_all = set()
        for v in json.load(open(a.sec_tickers)).values():          # ordered by the SEC's rank: the first ticker of a CIK is the primary listing
            sec.setdefault(int(v["cik_str"]), norm(v["ticker"])); sec_all.add(norm(v["ticker"]))
        latest = df.dropna(subset=["cik"]).sort_values("month_end").groupby("ticker").tail(1)
        dup = latest[latest.duplicated("cik", keep=False)]["cik"]; latest = latest[~latest["cik"].isin(dup)]   # share classes left out
        for r in latest.itertuples():
            cur = sec.get(int(r.cik))
            # a symbol the SEC still lists trades under that symbol (NAVI beside its note JSM): no change
            if cur and cur != r.ticker and r.ticker not in sec_all and (r.ticker, cur) not in known and not any(o == r.ticker for o, _ in known):
                found.append({"old": r.ticker, "new": cur, "method": "sec_company_tickers_cik", "first_seen_new": None, "cik": int(r.cik), "source": "https://www.sec.gov/files/company_tickers.json"})
                known.add((r.ticker, cur))
        if found and not changes["old"].isin([f["old"] for f in found]).all():
            changes = pd.concat([changes, pd.DataFrame([f for f in found if f["old"] not in set(changes["old"])])], ignore_index=True).drop_duplicates(["old", "new"])
    # chains -> the current symbol; a cycle (a symbol changed and changed back, or two notations of one symbol) resolves
    # to the member of the cycle listed in the latest month-end
    def make_resolve(m):
        def resolve(t):
            seen = [t]
            while t in m and m[t] not in seen:
                seen.append(m[t]); t = m[t]
            if t in m and m[t] in seen:                               # a cycle
                cyc = seen[seen.index(m[t]):]
                inlatest = [x for x in cyc if x in latest_set]
                return inlatest[0] if inlatest else cyc[-1]
            return t
        return resolve
    # the components list as a third witness, for the revisions before May 2014 that carry no CIK: a Wikipedia symbol
    # whose run of disagreement with the list (three or more consecutive months) starts in the same month as one list
    # symbol's run and ends within two months of it (the list and Wikipedia record a change a month or two apart),
    # leaves Wikipedia at the end of its run, and whose counterpart was not in Wikipedia before, is the same company
    # under its later symbol (SAIC -> LDOS in 2013). Where several pairs share a start month (KFT and DV both from
    # January 2012, Wikipedia's first revision) the SEC's former names of the candidate's CIK decide; a group the
    # names do not decide is reported unresolved.
    r0 = make_resolve(dict(zip(changes["old"], changes["new"])))
    wk = df[df["source"] == "Wikipedia revision"].assign(tc=lambda x: x["ticker"].map(r0))
    last_w = wk.groupby("tc")["month_end"].max().dt.strftime("%Y-%m-%d").to_dict(); first_w = wk.groupby("tc")["month_end"].min().dt.strftime("%Y-%m-%d").to_dict()
    onlyw, onlyc = {}, {}
    for me in sorted(comp):
        if me not in wiki:
            continue
        w = {r0(t) for t in wiki[me]["ticker"]}; c = {r0(t) for t in comp[me]}
        for x in w - c:
            onlyw.setdefault(x, []).append(me)
        for y in c - w:
            onlyc.setdefault(y, []).append(me)
    def consecutive(ms):
        ps = [pd.Period(m_, freq="M") for m_ in ms]
        return all((ps[i] - ps[i - 1]).n == 1 for i in range(1, len(ps)))
    cand = {}
    for x, xm in onlyw.items():
        if len(xm) < 3 or not consecutive(xm) or last_w.get(x) != xm[-1]:
            continue
        for y, ym in onlyc.items():
            if len(ym) < 3 or not consecutive(ym) or ym[0] != xm[0] or abs(len(ym) - len(xm)) > 2:
                continue
            if y in first_w and first_w[y] <= xm[-1]:
                continue
            cand.setdefault(x, []).append(y)
    from collections import Counter
    ycount = Counter(y for ys in cand.values() for y in ys)
    witness, unresolved = [], []
    def live(t):
        return t in latest_set or t in sec_t2c
    def add_pair(x, y, how):
        # the list lags today's symbol (WYND for TNL): the live symbol is the current one, unless the list's symbol is a
        # bankruptcy symbol (BTUUQ), where the live symbol is a later company under a reused symbol
        if live(x) and not live(y) and not (len(y) == 5 and y.endswith("Q")):
            x, y = y, x
        if (x, y) in known or any(o == x for o, _ in known):
            return
        witness.append({"old": x, "new": y, "method": "components_list_continuity", "first_seen_new": onlyw.get(x, onlyc.get(x, [None]))[-1],
                        "source": f"fja05680/sp500 components list vs Wikipedia revisions: the same run of disagreement from {onlyw.get(x, onlyc.get(x, ['?']))[0][:7]}; {how}"})
        known.add((x, y))
    ambiguous = {x: ys for x, ys in cand.items() if not (len(ys) == 1 and ycount[ys[0]] == 1)}
    for x, ys in cand.items():
        if x not in ambiguous:
            add_pair(x, ys[0], "unique")
    if ambiguous:
        ua = os.environ.get("SEC_USER_AGENT")
        tokens = name_tokens
        def former_names(cik):
            pth = cache / f"sec_submissions_{cik}.json"
            if not pth.exists():
                if not ua:
                    return None
                import gzip, urllib.request
                th.wait()
                req = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
                raw = urllib.request.urlopen(req, timeout=30).read()
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
                pth.write_bytes(raw)
            j = json.loads(pth.read_text())
            return [j.get("name", "")] + [f.get("name", "") for f in j.get("formerNames", [])]
        for x, ys in ambiguous.items():
            xn = wk[wk["tc"] == x].sort_values("month_end")["name"].dropna()
            xt = tokens(xn.iloc[-1]) if len(xn) else set()
            if live(x):
                # a symbol listed today or at the SEC: its counterpart is the one defunct candidate (neither listed today nor at the SEC)
                defunct = [y for y in ys if not live(y)]
                if len(defunct) == 1:
                    add_pair(x, defunct[0], f"the one defunct candidate beside today's symbol {x}")
                    continue
            hits = []
            for y in ys:
                cik = sec_t2c.get(y)
                names = former_names(cik) if cik else None
                if names is None:
                    continue
                if xt and any(len(xt & tokens(nm)) >= max(1, min(2, len(xt))) for nm in names):
                    hits.append((y, cik))
            if len(hits) == 1 and xt:
                add_pair(x, hits[0][0], f"former names of CIK {hits[0][1]} match the revision's name '{xn.iloc[-1]}'")
            else:
                unresolved.append({"wikipedia": x, "name": (xn.iloc[-1] if len(xn) else None), "candidates": ys, "months": f"{onlyw[x][0][:7]} to {onlyw[x][-1][:7]}",
                                   "reason": ("no SEC_USER_AGENT for the former-names tie-break" if not ua and not any(sec_t2c.get(y) is None for y in ys) and not hits else f"{len(hits)} name matches")})
    if witness:
        changes = pd.concat([changes, pd.DataFrame(witness)], ignore_index=True)
        log(f"components-list continuity: {len(witness)} changes: " + ", ".join(f"{w_['old']}->{w_['new']}" for w_ in witness))
    if unresolved:
        log(f"components-list continuity: {len(unresolved)} unresolved: " + "; ".join(f"{u_['wikipedia']} ({u_['name']}) vs {u_['candidates']}: {u_['reason']}" for u_ in unresolved))
    resolve = make_resolve(dict(zip(changes["old"], changes["new"])))
    changes["current"] = changes["new"].map(resolve)
    # ── H1 (third follow-up, 7 Oct 2026): a change is bounded by date and company. It applies to a row under the old
    # symbol only (1) at month-ends up to valid_to - the last month-end the old symbol is listed before the new symbol
    # first appears in the file (a symbol reused later by another company, Q after Quintiles, is not mapped);
    # (2) when the row's CIK, where it carries one, is the CIK of the change; (3) when the row's name, where it carries
    # one and no CIK, shares a word with a name the company had under the old symbol; (4) when the new symbol is not
    # listed in the same month-end for another company (WellPoint Health Networks beside Anthem in 2004). A second
    # share class whose history the new symbol does not carry (DISCK beside DISCA) stays under its own symbol. A
    # symbol's earlier holder (Chubb Corp under CB before ACE took the symbol) is set apart as SYMBOL-YYYYMM, the
    # month its run ends, so that it takes no bars.
    changes = changes.drop_duplicates(["old", "new"]).reset_index(drop=True)
    if "cik" not in changes.columns:
        changes["cik"] = None
    wrows = df[df["source"] == "Wikipedia revision"]
    lit_first = df.groupby("ticker")["month_end"].min().to_dict()
    row_cik = df["cik"].astype("float")
    valid_to, old_names = [], []
    for ch in changes.itertuples():
        cik = float(ch.cik) if pd.notna(ch.cik) else None
        rows = df[(df["ticker"] == ch.old) & (row_cik.isna() | (row_cik == cik) if cik is not None else True)]
        nf = lit_first.get(ch.new)
        before = rows[rows["month_end"] < nf] if (nf is not None and len(rows) and nf > rows["month_end"].min()) else rows
        vt = (before if len(before) else rows)["month_end"].max() if len(rows) else None
        valid_to.append(vt)
        names = []
        if isinstance(ch.old_name, str) and ch.old_name:
            names.append(ch.old_name)
        wn = wrows[(wrows["ticker"] == ch.old) & wrows["name"].notna() & ((wrows["month_end"] <= vt) if vt is not None else True)]
        if cik is not None and (wn["cik"].astype("float") == cik).any():
            wn = wn[wn["cik"].astype("float") == cik]
        names += [n for n in wn["name"].unique().tolist() if n not in names]
        old_names.append(" | ".join(names) if names else None)
    changes["valid_to"] = [pd.Timestamp(v).strftime("%Y-%m-%d") if v is not None and pd.notna(v) else None for v in valid_to]
    changes["old_name"] = old_names
    # share classes: two old symbols of one company (the same CIK in their rows) mapped to one new symbol - the class
    # whose symbol ends in A (or the first) carries the provider's history; the other stays under its own symbol
    changes["applies"] = True; changes["note"] = None
    cik_of_old = {o: set(df.loc[(df["ticker"] == o) & df["cik"].notna(), "cik"].astype(int)) for o in changes["old"].unique()}
    for new, grp in changes.groupby("new"):
        if len(grp) < 2:
            continue
        olds = list(grp["old"])
        for i in range(len(olds)):
            for j in range(i + 1, len(olds)):
                if cik_of_old[olds[i]] & cik_of_old[olds[j]]:
                    keep = olds[i] if olds[i].endswith("A") else (olds[j] if olds[j].endswith("A") else min(olds[i], olds[j]))
                    drop = olds[j] if keep == olds[i] else olds[i]
                    changes.loc[(changes["old"] == drop) & (changes["new"] == new), ["applies", "note"]] = [False, f"share class of {keep}: the provider's {new} history is {keep}'s; stays under its own symbol"]
    by_old = {}
    for ch in changes[changes["applies"]].itertuples():
        by_old.setdefault(ch.old, []).append(ch)
    literal_at = {me: set(g["ticker"]) for me, g in df.groupby("month_end")}
    # a literal run: consecutive month-ends of one symbol with no change of CIK; the run's CIK, where any row carries
    # one, is the company's CIK for every row of the run (the revisions before May 2014 carry none)
    run_id = {}; run_cik = {}
    for t, g in df.sort_values("month_end").groupby("ticker"):
        rid, prev = 0, None
        for r in g.itertuples():
            if prev is not None and ((r.month_end.to_period("M") - prev.month_end.to_period("M")).n > 1 or
                                     (pd.notna(r.cik) and run_cik.get((t, rid)) is not None and int(r.cik) != run_cik[(t, rid)])):
                rid += 1
            run_id[r.Index] = (t, rid)
            if pd.notna(r.cik) and run_cik.get((t, rid)) is None:
                run_cik[(t, rid)] = int(r.cik)
            prev = r
    cik_at = {(me, t): run_cik.get(run_id[i]) for i, me, t in zip(df.index, df["month_end"], df["ticker"])}
    blocked = {"date": 0, "cik": 0, "name": 0, "coexistence": 0}; name_blocked_cases = {}
    def step(t, t0, me, cik, name):
        for ch in by_old.get(t, []):
            if ch.valid_to is not None and me > pd.Timestamp(ch.valid_to):
                blocked["date"] += 1; continue
            if pd.notna(ch.cik) and cik is not None and int(ch.cik) != cik:
                blocked["cik"] += 1; continue
            if t == t0 and cik is None and name and ch.old_name and not (name_tokens(name) & name_tokens(ch.old_name)):
                blocked["name"] += 1; name_blocked_cases.setdefault((t, name, ch.new), 0); name_blocked_cases[(t, name, ch.new)] += 1; continue
            if ch.new in literal_at[me] and ch.new != t0:
                same_company = pd.notna(ch.cik) and cik is not None and int(ch.cik) == cik   # the row is the company that took the symbol; the literal holder is the earlier one
                if not same_company:
                    blocked["coexistence"] += 1; continue
            return ch.new
        return None
    def resolve_row(t, me, cik, name):
        t0 = t; seen = [t]
        while True:
            n = step(t, t0, me, cik, name)
            if n is None:
                return t
            if n in seen:                                                 # a cycle: the symbol listed in the latest month-end
                cyc = seen[seen.index(n):]
                inlatest = [x for x in cyc if x in latest_set]
                return inlatest[0] if inlatest else cyc[-1]
            seen.append(n); t = n
    df["ticker_current"] = [resolve_row(t, me, cik_at[(me, t)], (n if isinstance(n, str) else None))
                            for t, me, n in zip(df["ticker"], df["month_end"], df["name"])]
    if name_blocked_cases:
        log("name rule blocked: " + "; ".join(f"{k[0]} '{k[1]}' -> {k[2]} x{v}" for k, v in sorted(name_blocked_cases.items(), key=lambda kv: -kv[1])[:12]))
    # earlier holders of a symbol: a literal run of the symbol that collides with rows mapped on to it
    prior_holders, unmapped_collisions = [], []
    dup = df[df.duplicated(["month_end", "ticker_current"], keep=False)]
    for sym in sorted(dup["ticker_current"].unique()):
        g = dup[dup["ticker_current"] == sym]
        lit_months = set(g.loc[g["ticker"] == sym, "month_end"])
        if lit_months:
            L = df[(df["ticker"] == sym)].sort_values("month_end")
            runs = {}
            for r in L.itertuples():
                runs.setdefault(run_id[r.Index], []).append(r)
            for run in runs.values():
                if any(r.month_end in lit_months for r in run):
                    tag = f"{sym}-{run[-1].month_end.strftime('%Y%m')}"
                    df.loc[[r.Index for r in run], "ticker_current"] = tag
                    prior_holders.append({"symbol": sym, "set_apart_as": tag, "from": run[0].month_end.strftime("%Y-%m-%d"), "to": run[-1].month_end.strftime("%Y-%m-%d"),
                                          "months": len(run), "cik": (int(run[-1].cik) if pd.notna(run[-1].cik) else None), "name": next((r.name for r in reversed(run) if isinstance(r.name, str)), None)})
        else:
            # two mapped rows: the company with the longer chain was absorbed; it stays under its own symbol
            olds = sorted(g["ticker"].unique(), key=lambda o: (-len(set(resolve_chain(o))), o)) if False else sorted(g["ticker"].unique())
            keep = olds[0]
            for o in olds[1:]:
                df.loc[(df["ticker"] == o) & (df["ticker_current"] == sym), "ticker_current"] = o
                unmapped_collisions.append({"symbol": o, "collides_with": keep, "on": sym})
    dups_left = int(df.duplicated(["month_end", "ticker_current"]).sum())
    changes.to_csv(CHANGES, index=False)
    log(f"H1 bounds: blocked by date {blocked['date']}, CIK {blocked['cik']}, name {blocked['name']}, coexistence {blocked['coexistence']}; "
        f"share classes not mapped {int((~changes['applies']).sum())}; earlier holders set apart {len(prior_holders)} ({', '.join(p['set_apart_as'] for p in prior_holders)}); "
        f"collisions unmapped {len(unmapped_collisions)}; duplicate (month-end, current symbol) pairs left {dups_left}")
    for c_ in comparison:                                             # the same comparison with both sides mapped to current symbols
        me = c_["month_end"]; w = {resolve(t) for t in wiki[me]["ticker"]}; c = {resolve(t) for t in comp[me]}
        c_["differ_mapped"] = len(w ^ c); c_["only_wikipedia_mapped"] = sorted(w - c)[:40]; c_["only_components_mapped"] = sorted(c - w)[:40]
    mapped = int((df["ticker_current"] != df["ticker"]).sum())
    AN.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    CMP.write_text(json.dumps({"cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"),
                               "rule": "for 2012 to 2026 both sources are read; where they differ the Wikipedia revision is used; the components list serves 2004-06 to the month before the first revision",
                               "note": "the components list ('Updated') carries each company's later symbol (ANTM for WLP, BKNG for PCLN, ANRZQ for a bankruptcy) while a Wikipedia revision carries the symbol of the day, so `differ` counts notation as well as membership; `differ_mapped` compares both sides after the ticker changes are applied",
                               "unresolved_wikipedia_vs_components": unresolved,
                               "months": comparison}, indent=1))
    g = df.groupby("month_end").size()
    META.write_text(json.dumps({
        "cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"),
        "sources": {"2004-06 to " + first_wiki: "github.com/fja05680/sp500, 'S&P 500 Historical Components & Changes (Updated)', MIT licence (cached copy)",
                    first_wiki + " to date": "Wikipedia, List of S&P 500 companies: the revision in force at each month-end (CIK and Security where the revision carries them)"},
        "months": len(g), "first": str(g.index.min().date()), "last": str(g.index.max().date()), "members_min": int(g.min()), "members_max": int(g.max()),
        "ticker_convention": {"components list rows (2004-06 to the first revision)": "the list's symbol: the company's later symbol as the list's maintainer carries it (ANTM for WellPoint's WLP, MDLZ for Kraft Foods' KFT), mapped on to today's symbol by the change table (ELV); the repository's 'original' file carries the same later symbols, so no source gives the symbol of the day before 2012",
                              "Wikipedia rows": "the symbol of the revision, mapped to today's symbol by the change table"},
        "tickers_ever": int(df["ticker"].nunique()), "tickers_current_ever": int(df["ticker_current"].nunique()), "rows_with_a_mapped_ticker": mapped,
        "ticker_changes": {"rows": int(len(changes)), "by_method": changes["method"].value_counts().to_dict(), "applied": int(changes["applies"].sum())},
        "h1_bounds": {"rule": "a change applies to a row under the old symbol only up to valid_to (the last month-end the old symbol is listed before the new symbol first appears), only when the row's CIK (where carried) is the change's, only when the row's name (where carried, no CIK) shares a word with a name the company had under the old symbol, and not when the new symbol is listed in the same month-end for another company",
                      "blocked": blocked, "share_classes_not_mapped": changes.loc[~changes["applies"], ["old", "new", "note"]].to_dict("records"),
                      "earlier_holders_set_apart": prior_holders, "collisions_unmapped": unmapped_collisions, "duplicate_pairs_left": dups_left},
        "wikipedia_revisions": revmeta,
        "limits": "volunteer-maintained lists; a change can lag by days; delisted members have no bars at the price provider and enter a test only where bars exist",
    }, indent=1, default=str))
    log(f"{len(df)} rows, {len(g)} month-ends {g.index.min().date()}..{g.index.max().date()}, {df['ticker'].nunique()} tickers ({df['ticker_current'].nunique()} current); "
        f"{len(changes)} ticker changes ({changes['method'].value_counts().to_dict()}); {mapped} rows mapped; overlap months compared {len(comparison)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
