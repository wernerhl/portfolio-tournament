#!/usr/bin/env python3
"""
sec_facts.py — XBRL company facts from EDGAR for the fundamental features of the extended (43-variable) feature set
(follow-up order of 7 October 2026, F5), adapted from the design workspace's sec.py and fund.py
(research/ml_stratification_test/) with these changes: the User-Agent comes from SEC_USER_AGENT (the declared
contact the SEC requires; never written into the repository), the request rate stays under 4 a second, every
response is cached outside the repository, and the output is a parquet of trailing-twelve-month records with their
filing (availability) dates, stored raw under data/analyst/history/ with the download date in the name.

For every name in the raw history (members and former members with prices): the duration concepts (revenue, net
income, operating income, gross profit, cost of revenue, operating cash flow, capex, R&D, diluted shares) and the
instant concepts (assets, equity, shares outstanding) from 10-K/10-Q filings; TTM series built from annual and
quarterly facts (fund.py's method); lags of 1, 4 and 5 quarters; the standardised earnings surprise (the change in
TTM net income against its 8-quarter standard deviation); shares brought to the share basis of today by the splits
after each filing.

Usage:  SEC_USER_AGENT="Name contact" python scripts/analyst/sec_facts.py [--cache DIR] [--tickers MU,LMT]
Exit 3 without SEC_USER_AGENT.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
REPO = HERE.parent.parent
HIST = REPO / "data" / "analyst" / "history"
DUR = ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet',
       'SalesRevenueGoodsNet', 'NetIncomeLoss', 'OperatingIncomeLoss', 'GrossProfit', 'CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold',
       'NetCashProvidedByUsedInOperatingActivities', 'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations',
       'PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets', 'ResearchAndDevelopmentExpense',
       'WeightedAverageNumberOfDilutedSharesOutstanding']
INST = ['Assets', 'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', 'CommonStockSharesOutstanding']
FORMS = ('10-K', '10-Q', '10-K/A', '10-Q/A', '20-F', '40-F', '10-KT', '10-QT')
MIN_INTERVAL_S = 0.3


def log(m: str) -> None:
    print(f"[sec_facts] {m}", flush=True)


class Throttle:
    def __init__(self, interval=MIN_INTERVAL_S):
        self.interval, self.last, self.n = interval, 0.0, 0

    def wait(self):
        gap = time.monotonic() - self.last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self.last = time.monotonic(); self.n += 1


def fetch_json(url: str, ua: str, cache: Path, th: Throttle):
    import hashlib
    import urllib.error
    import urllib.request
    p = cache / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".json")
    if p.exists():
        return json.loads(p.read_text()) if p.stat().st_size > 2 else None
    for k in range(4):
        th.wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate", "Host": url.split("/")[2]})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip; raw = gzip.decompress(raw)
                body = raw.decode()
            p.write_text(body)
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                p.write_text(""); return None
            time.sleep(2 + 3 * k)
        except Exception:  # noqa: BLE001
            time.sleep(2 + 3 * k)
    return None


def facts_rows(tk: str, j: dict) -> list[tuple]:
    rows = []
    f = (j or {}).get("facts") or {}
    def grab(ns, c):
        for unit, lst in ((f.get(ns) or {}).get(c) or {}).get("units", {}).items():
            if unit not in ("USD", "shares"):
                continue
            for x in lst:
                if x.get("form", "") not in FORMS:
                    continue
                rows.append((tk, c, x.get("start"), x["end"], x["val"], x["filed"], x["form"]))
    for c in DUR + INST:
        grab("us-gaap", c)
    grab("dei", "EntityCommonStockSharesOutstanding")
    return rows


# ── fund.py's TTM construction ───────────────────────────────────────────────────────────────
D1 = pd.Timedelta(days=1)


def near(sorted_ends, target, tol=10):
    i = bisect.bisect_left(sorted_ends, target); best = None
    for jx in (i - 1, i):
        if 0 <= jx < len(sorted_ends) and abs((sorted_ends[jx] - target).days) <= tol:
            if best is None or abs((sorted_ends[jx] - target).days) < abs((best - target).days):
                best = sorted_ends[jx]
    return best


def ttm_series(df):
    ann = df[(df.dur >= 350) & (df.dur <= 380)]; A = {r.end: (r.val, r.filed) for r in ann.itertuples()}; aend = sorted(A)
    oth = df[(df.dur >= 80) & (df.dur <= 290)]; res = dict(A)
    byend = {}
    for r in oth.itertuples():
        byend.setdefault(r.end, []).append(r)
    oend = sorted(byend)
    for E in oend:
        if E in res:
            continue
        y = max(byend[E], key=lambda r: r.dur)
        fy = near(aend, y.start - D1)
        if fy is None:
            continue
        pe = near(oend, E - pd.Timedelta(days=365))
        if pe is None:
            continue
        cand = [r for r in byend[pe] if abs(r.dur - y.dur) <= 12]
        if not cand:
            continue
        res[E] = (A[fy][0] + y.val - cand[0].val, y.filed)
    return res


def with_lags(res):
    ends = sorted(res); out = {}
    for E in ends:
        l1 = near(ends, E - pd.Timedelta(days=91)); l4 = near(ends, E - pd.Timedelta(days=365)); l5 = near(ends, E - pd.Timedelta(days=456))
        out[E] = dict(v=res[E][0], avail=res[E][1], l1=res[l1][0] if l1 else np.nan, l4=res[l4][0] if l4 else np.nan, l5=res[l5][0] if l5 else np.nan)
    return out


def first(*ds):
    out = {}
    for d in ds:
        for E, v in d.items():
            if E not in out:
                out[E] = v
    return out


def records(F: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    F = F.dropna(subset=['end', 'filed', 'val']).sort_values('filed').drop_duplicates(['tic', 'concept', 'start', 'end'], keep='first').copy()
    F['dur'] = (F.end - F.start).dt.days
    REV = DUR[:5]
    recs = []
    for tic, g in F.groupby('tic'):
        c = {k: v for k, v in g.groupby('concept')}
        def T(name):
            return with_lags(ttm_series(c[name])) if name in c else {}
        rev = first(*[T(n) for n in REV]); ni = T('NetIncomeLoss'); oi = T('OperatingIncomeLoss'); gp = T('GrossProfit')
        cost = first(T('CostOfRevenue'), T('CostOfGoodsAndServicesSold'), T('CostOfGoodsSold'))
        cfo = first(T('NetCashProvidedByUsedInOperatingActivities'), T('NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'))
        cap = first(T('PaymentsToAcquirePropertyPlantAndEquipment'), T('PaymentsToAcquireProductiveAssets')); rd = T('ResearchAndDevelopmentExpense')
        def inst(name):
            if name not in c:
                return {}
            return {r.end: (r.val, r.filed) for r in c[name].itertuples()}
        assets = inst('Assets'); eq = first(inst('StockholdersEquity'), inst('StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'))
        aend = sorted(assets)
        sh = {}
        if 'WeightedAverageNumberOfDilutedSharesOutstanding' in c:
            for r in c['WeightedAverageNumberOfDilutedSharesOutstanding'].sort_values('dur').itertuples():
                if r.dur >= 80 and r.end not in sh:
                    sh[r.end] = (r.val, r.filed)
        deif = {}
        if 'EntityCommonStockSharesOutstanding' in c:
            for r in c['EntityCommonStockSharesOutstanding'].itertuples():
                deif[r.filed] = r.val
        ends = sorted(set(rev) | set(ni))
        niE = sorted(ni); dni = {E: ni[E]['v'] - ni[E]['l1'] for E in niE}
        for E in ends:
            r = rev.get(E, {}); n = ni.get(E, {}); av = [x.get('avail') for x in (r, n) if x.get('avail') is not None]
            if not av:
                continue
            avail = max(av)
            a = assets.get(E, (np.nan, None))[0]; al = near(aend, E - pd.Timedelta(days=365)); a4 = assets[al][0] if al else np.nan
            e = eq.get(E, (np.nan, None))[0]
            s = sh.get(E, (np.nan, None))[0]
            if not np.isfinite(s) or s <= 0:
                s = deif.get(avail, np.nan)
            sue = np.nan
            if E in dni and np.isfinite(dni[E]):
                i = niE.index(E); h = [dni[x] for x in niE[max(0, i - 8):i] if np.isfinite(dni[x])]
                if len(h) >= 6 and np.std(h) > 0:
                    sue = dni[E] / np.std(h)
            g_ = gp.get(E, {}).get('v', np.nan)
            if not np.isfinite(g_) and E in cost and E in rev:
                g_ = rev[E]['v'] - cost[E]['v']
            recs.append(dict(tic=tic, end=E, avail=avail, rev=r.get('v', np.nan), rev_l1=r.get('l1', np.nan), rev_l4=r.get('l4', np.nan), rev_l5=r.get('l5', np.nan),
                             ni=n.get('v', np.nan), ni_l4=n.get('l4', np.nan), oi=oi.get(E, {}).get('v', np.nan), oi_l4=oi.get(E, {}).get('l4', np.nan), gp=g_,
                             cfo=cfo.get(E, {}).get('v', np.nan), capex=cap.get(E, {}).get('v', np.nan), capex_l4=cap.get(E, {}).get('l4', np.nan), rd=rd.get(E, {}).get('v', np.nan),
                             assets=a, assets_l4=a4, equity=e, shares=s, sue=sue))
    R = pd.DataFrame(recs)
    if not len(R):
        return R
    R = R[R.avail.notna()].copy()
    fac = []
    for r in R.itertuples():
        s_ = splits[(splits.ticker == r.tic) & (splits.date > r.avail)]
        fac.append(float(np.prod(s_.ratio.values)) if len(s_) else 1.0)
    R['shares_adj'] = R.shares * np.array(fac)
    R = R.sort_values(['tic', 'end'])
    R['sh_l4'] = np.nan
    for tic, g in R.groupby('tic'):
        ends = list(g.end); m = dict(zip(g.end, g.shares_adj))
        R.loc[g.index, 'sh_l4'] = [m.get(near(ends, E - pd.Timedelta(days=365)), np.nan) if near(ends, E - pd.Timedelta(days=365)) is not None else np.nan for E in ends]
    return R


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(REPO.parent / ".cache_sec_facts"))
    ap.add_argument("--tickers", default=None)
    a = ap.parse_args()
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        log("SEC_USER_AGENT not set: EDGAR requires a declared contact; nothing fetched"); return 3
    cache = Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    import build_panel as bp
    stamps = bp.all_stamps()
    mp = bp.read_all("monthly_prices", stamps); splits = bp.read_all("splits", stamps)
    splits["date"] = pd.to_datetime(splits["date"])
    tickers = [t.strip().upper() for t in a.tickers.split(",")] if a.tickers else sorted(set(mp["ticker"]))
    th = Throttle()
    tk_map = fetch_json("https://www.sec.gov/files/company_tickers.json", ua, cache, th) or {}
    cik = {str(v["ticker"]).upper().replace(".", "-"): int(v["cik_str"]) for v in tk_map.values()}
    have = [t for t in tickers if t in cik]
    log(f"{len(tickers)} tickers, {len(have)} with a CIK; {len(tickers) - len(have)} without: {[t for t in tickers if t not in cik][:12]}")
    rows, miss = [], []
    t0 = time.time()
    for i, t in enumerate(have, 1):
        j = fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik[t]:010d}.json", ua, cache, th)
        if j is None:
            miss.append(t)
        else:
            rows += facts_rows(t, j)
        if i % 100 == 0 or i == len(have):
            log(f"{i}/{len(have)} · facts {len(rows)} · missing {len(miss)} · {th.n} requests in {time.time() - t0:.0f}s")
    F = pd.DataFrame(rows, columns=['tic', 'concept', 'start', 'end', 'val', 'filed', 'form'])
    for c in ('start', 'end', 'filed'):
        F[c] = pd.to_datetime(F[c], errors='coerce')
    R = records(F, splits)
    HIST.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    stamp, k = today, 1
    while (HIST / f"sec_fund_records_{stamp}.parquet").exists():
        k += 1; stamp = f"{today}-{k}"
    R.to_parquet(HIST / f"sec_fund_records_{stamp}.parquet", index=False)
    meta = {"task": "F5 of the follow-up order (7 October 2026): EDGAR company facts -> TTM fundamental records with filing dates, stored raw, never rewritten",
            "downloaded_on": stamp, "source": "https://data.sec.gov/api/xbrl/companyfacts/", "user_agent": "SEC_USER_AGENT (the declared contact; not recorded)",
            "rate": "under 4 requests a second", "requests": th.n, "elapsed_s": round(time.time() - t0),
            "tickers": {"requested": len(tickers), "with_cik": len(have), "no_facts": miss}, "records": int(len(R)), "companies": int(R.tic.nunique()) if len(R) else 0,
            "avail_range": [str(R.avail.min().date()), str(R.avail.max().date())] if len(R) else None,
            "method": "research/ml_stratification_test/fund.py: annual facts plus quarterly differences give TTM values at each quarter end; lags of 1, 4 and 5 quarters; SUE = the change in TTM net income over its 8-quarter standard deviation; shares to today's basis by the splits after the filing"}
    (HIST / f"_meta_sec_{stamp}.json").write_text(json.dumps(meta, indent=1))
    log(f"records {len(R)} for {meta['companies']} companies; {len(miss)} without facts; avail {meta['avail_range']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
