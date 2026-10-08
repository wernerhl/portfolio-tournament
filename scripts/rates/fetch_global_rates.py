#!/usr/bin/env python3
"""
fetch_global_rates.py — the global-rates series, official sources first (Execution Order: Global Rates Panels on the
Bonds Page, 6 October 2026, section 1).

Sources (data/rates/global_rates_config.json names each series):
  FRED            U.S. yields, real yield, breakeven, Kim-Wright term premium, fed funds, 3-month bill, the OECD
                  monthly 10-year series for the G7, Brent (EIA spot), yen per dollar — the public CSV download
                  (fredgraph.csv), no key
  NYFED_ACM       New York Fed ACM term premium file (ACM Daily, ACMTP10)
  BUNDESBANK      Bundesbank statistics API, 10-year yield on listed federal securities (Svensson), daily
  BOE_IADB        Bank of England database, 10-year nominal zero-coupon (IUDMNZC), daily
  BOE_GLC         Bank of England yield-curve spreadsheets, nominal spot curve, 30 years (current month; the
                  archive once, to seed the history)
  MOF             Ministry of Finance JGB interest rates (jgbcme_all.csv history + jgbcme.csv current month)
  BOC_VALET       Bank of Canada Valet API, benchmark 10-year yield
  PROVIDER        the price provider's Brent front-month contract (BZ=F): the same-day value, labelled as such
  FISCAL_DATA     U.S. Treasury Fiscal Data API, Treasury securities auctions (notes and bonds; announced ones too)

Stores
  data/source/rates_daily.parquet         long (date, series, value), every series' history; each run overlays
                                          what it retrieved; a failed source keeps its stored history
  data/rates/series_meta.json             per series: source, URL, retrieved_at, as_of (latest observation), error
  data/rates/auctions.json                the notes-and-bonds auctions since 2025 and the announced ones
  data/rates/vintages/YYYY-MM-DD.json     the day's retrieved values (each series' last 30 observations and its
                                          metadata), written ONCE and never rewritten; sha256 in vintages/_index.json

Usage:  python scripts/rates/fetch_global_rates.py [--only us10,de10]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
from trading_calendar import now_et   # noqa: E402  (the ET date: a runner's clock is UTC)
DATA = REPO / "data"
RATES = DATA / "rates"
CONFIG = RATES / "global_rates_config.json"
STORE = DATA / "source" / "rates_daily.parquet"
META = RATES / "series_meta.json"
AUCTIONS = RATES / "auctions.json"
VINT = RATES / "vintages"
UA = {"User-Agent": "Mozilla/5.0 (portfolio-tournament rates monitor)"}
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
BBK = "https://api.statistiken.bundesbank.de/rest/data/{id}?format=csv&lang=en"
BOE_IADB = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=01/Jan/2005"
            "&Dateto=now&SeriesCodes={id}&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
BOE_GLC_LATEST = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip"
BOE_GLC_ARCHIVE = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip"
MOF_ALL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
MOF_CUR = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
BOC = "https://www.bankofcanada.ca/valet/observations/{id}/json?start_date=2005-01-01"
ACM = "https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls"
FISCAL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
          "?filter=auction_date:gte:{start},security_type:in:(Note,Bond)&sort=-auction_date&page[size]=500")


def log(m: str) -> None:
    print(f"[global_rates] {m}", flush=True)


def get(url: str, timeout: int = 90) -> bytes:
    last = None
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(3 * (attempt + 1))
    raise last


def num(s) -> pd.Series:
    return pd.to_numeric(s.replace({".": np.nan, "-": np.nan, "": np.nan}), errors="coerce")


# ── one function per source: returns {series_key: pd.Series(date -> value)} and the URL used ───────
def fred(sid: str) -> tuple[pd.Series, str]:
    url = FRED_CSV.format(id=sid)
    df = pd.read_csv(io.BytesIO(get(url)))
    df.columns = ["date", "v"]
    s = pd.Series(num(df["v"].astype(str)).values, index=pd.to_datetime(df["date"])).dropna()
    return s, url


def bundesbank(sid: str) -> tuple[pd.Series, str]:
    url = BBK.format(id=sid)
    rows = []
    for line in get(url).decode("utf-8-sig", "replace").splitlines():
        m = re.match(r'^"?(\d{4}-\d{2}-\d{2})"?,"?([-0-9.]*)"?', line)
        if m and re.match(r"^-?\d+(\.\d+)?$", m.group(2) or ""):      # "." marks a day without a value
            rows.append((m.group(1), float(m.group(2))))
    s = pd.Series({pd.Timestamp(d): v for d, v in rows}).sort_index()
    return s, url


def boe_iadb(code: str) -> tuple[pd.Series, str]:
    url = BOE_IADB.format(id=code)
    df = pd.read_csv(io.BytesIO(get(url)))
    df.columns = ["date", "v"]
    s = pd.Series(num(df["v"].astype(str)).values, index=pd.to_datetime(df["date"], format="%d %b %Y")).dropna()
    return s.sort_index(), url


def _glc_spot_30(xlsx: bytes) -> pd.Series:
    x = pd.ExcelFile(io.BytesIO(xlsx), engine="openpyxl")
    df = x.parse("4. spot curve", header=None)
    yrow = next(i for i in range(len(df)) if str(df.iloc[i, 0]).strip().lower().startswith("years"))
    cols = {float(v): j for j, v in enumerate(df.iloc[yrow]) if j > 0 and pd.notna(v)}
    j30 = cols.get(30.0)
    out = {}
    for i in range(yrow + 1, len(df)):
        d = df.iloc[i, 0]
        if isinstance(d, (datetime, pd.Timestamp)) and pd.notna(df.iloc[i, j30]):
            out[pd.Timestamp(d).normalize()] = float(df.iloc[i, j30])
    return pd.Series(out).sort_index()


def boe_glc_30(stored: pd.Series | None) -> tuple[pd.Series, str]:
    """The current month from the latest-data zip; the archive ('2025 to present') once, when the stored history
    does not reach the end of the previous month."""
    z = zipfile.ZipFile(io.BytesIO(get(BOE_GLC_LATEST)))
    cur = _glc_spot_30(z.read("GLC Nominal daily data current month.xlsx"))
    month_start = pd.Timestamp(now_et().date().replace(day=1))
    need_archive = stored is None or not len(stored) or stored.index.max() < month_start - pd.Timedelta(days=7)
    url = BOE_GLC_LATEST
    if need_archive:
        log("BoE GLC: seeding the 30-year history from the archive (one download)")
        za = zipfile.ZipFile(io.BytesIO(get(BOE_GLC_ARCHIVE, timeout=300)))
        name = next(n for n in za.namelist() if "present" in n)
        hist = _glc_spot_30(za.read(name))
        cur = pd.concat([hist, cur]); cur = cur[~cur.index.duplicated(keep="last")].sort_index()
        url = BOE_GLC_LATEST + " + " + BOE_GLC_ARCHIVE
    return cur, url


def mof(col: str) -> tuple[pd.Series, str]:
    frames = []
    for url in (MOF_ALL, MOF_CUR):
        raw = get(url).decode("utf-8", "replace").splitlines()
        hdr = next(i for i, l in enumerate(raw) if l.startswith("Date,"))
        df = pd.read_csv(io.StringIO("\n".join(raw[hdr:])))
        df = df[df["Date"].astype(str).str.match(r"^\d{4}/\d{1,2}/\d{1,2}$")]
        frames.append(pd.Series(num(df[col].astype(str)).values, index=pd.to_datetime(df["Date"], format="%Y/%m/%d")))
    s = pd.concat(frames).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index(), MOF_ALL + " + " + MOF_CUR


def boc(sid: str) -> tuple[pd.Series, str]:
    url = BOC.format(id=sid)
    j = json.loads(get(url))
    s = pd.Series({pd.Timestamp(o["d"]): float(o[sid]["v"]) for o in j.get("observations", []) if o.get(sid, {}).get("v") not in (None, "")})
    return s.sort_index(), url


def acm() -> tuple[pd.Series, str]:
    x = pd.ExcelFile(io.BytesIO(get(ACM, timeout=180)), engine="xlrd")
    df = x.parse("ACM Daily")
    s = pd.Series(pd.to_numeric(df["ACMTP10"], errors="coerce").values, index=pd.to_datetime(df["DATE"], format="%d-%b-%Y", errors="coerce"))
    return s[s.index.notna()].dropna().sort_index(), ACM + " (sheet ACM Daily, ACMTP10)"


def provider_brent() -> tuple[pd.Series, str]:
    import yfinance as yf
    h = yf.Ticker("BZ=F").history(period="3mo", interval="1d", auto_adjust=False)
    s = h["Close"].dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s.astype(float), "price provider (yfinance) BZ=F, Brent front-month future, daily close"


def auctions() -> dict:
    start = (now_et().date() - timedelta(days=500)).isoformat()
    url = FISCAL.format(start=start)
    j = json.loads(get(url))
    keep = ("auction_date", "issue_date", "security_type", "security_term", "cusip", "reopening", "offering_amt",
            "high_yield", "bid_to_cover_ratio", "indirect_bidder_accepted", "direct_bidder_accepted", "primary_dealer_accepted",
            "comp_accepted", "total_accepted", "inflation_index_security", "floating_rate", "announcemt_date")
    rows = [{k: r.get(k) for k in keep} for r in j.get("data", [])]
    return {"source": "U.S. Treasury Fiscal Data API, auctions_query (notes and bonds)", "url": url,
            "retrieved_at": datetime.now().astimezone().isoformat(timespec="seconds"), "rows": rows}


# ── the run ─────────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    cfg = json.loads(CONFIG.read_text())
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    store = pd.read_parquet(STORE) if STORE.exists() else pd.DataFrame(columns=["date", "series", "value"])
    if len(store):
        store["date"] = pd.to_datetime(store["date"])
    meta = json.loads(META.read_text()) if META.exists() else {}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    got: dict[str, pd.Series] = {}
    cache: dict[tuple, tuple] = {}
    for key, s in cfg["series"].items():
        if only and key not in only:
            continue
        src, sid = s["source"], s["id"]
        try:
            if src == "FRED":
                ser, url = cache.setdefault(("FRED", sid), fred(sid))
            elif src == "BUNDESBANK":
                ser, url = bundesbank(sid)
            elif src == "BOE_IADB":
                ser, url = boe_iadb(sid)
            elif src == "BOE_GLC":
                prev = store[store["series"] == key].set_index("date")["value"] if len(store) else None
                ser, url = boe_glc_30(prev)
            elif src == "MOF":
                ser, url = mof(sid)
            elif src == "BOC_VALET":
                ser, url = boc(sid)
            elif src == "NYFED_ACM":
                ser, url = acm()
            elif src == "PROVIDER":
                ser, url = provider_brent()
            else:
                raise ValueError(f"unknown source {src}")
            ser = ser[ser.index >= "2005-01-01"] if s["freq"] == "daily" and key not in ("us_tp_kw",) else ser
            got[key] = ser
            meta[key] = {"label": s["label"], "source": src, "id": sid, "url": url, "freq": s["freq"], "retrieved_at": now,
                         "as_of": str(ser.index.max().date()) if len(ser) else None, "latest": round(float(ser.iloc[-1]), 4) if len(ser) else None,
                         "n": int(len(ser)), "error": None}
            log(f"{key:10s} {src:11s} {meta[key]['as_of']}  {meta[key]['latest']}")
        except Exception as e:  # noqa: BLE001
            meta.setdefault(key, {"label": s["label"], "source": src, "id": sid})
            meta[key].update(error=f"{type(e).__name__}: {str(e)[:160]}", error_at=now)
            log(f"{key:10s} {src:11s} FAILED ({type(e).__name__}: {str(e)[:120]}); stored history kept")
    # overlay the retrieved series on the store
    frames = [store[~store["series"].isin(list(got))]] if len(store) else []
    for key, ser in got.items():
        frames.append(pd.DataFrame({"date": ser.index, "series": key, "value": ser.values}))
    new = pd.concat(frames, ignore_index=True).sort_values(["series", "date"])
    STORE.parent.mkdir(parents=True, exist_ok=True)
    new.to_parquet(STORE, index=False)
    RATES.mkdir(parents=True, exist_ok=True)
    META.write_text(json.dumps(meta, indent=1, default=str))
    if not only or "auctions" in only:
        try:
            AUCTIONS.write_text(json.dumps(auctions(), indent=1))
            log(f"auctions: {len(json.loads(AUCTIONS.read_text())['rows'])} notes and bonds since {(now_et().date() - timedelta(days=500)).isoformat()}")
        except Exception as e:  # noqa: BLE001
            log(f"auctions FAILED ({type(e).__name__}: {e}); previous file kept")
    # the session's vintage: written once, never rewritten. G7 (7-Oct-2026, second follow-up): named by the SESSION
    # whose data it holds (the session the nightly publishes), not by the calendar date of the run — a morning retry
    # that published the previous session had written the day's vintage with that session's state (6 Oct 2026)
    VINT.mkdir(parents=True, exist_ok=True)
    today = now_et().date().isoformat()
    from trading_calendar import last_completed_session
    session = os.environ.get("PUBLISH_SESSION") or last_completed_session(now_et())
    vp = VINT / f"{session}.json"
    idx_p = VINT / "_index.json"
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {"note": "one vintage per session, written once and never rewritten; sha256 recorded at write time", "vintages": {}}
    if vp.exists():
        log(f"vintage {vp.name} already written; not rewritten")
    else:
        body = {"session": session, "date": today, "written_at": now, "order": "Execution Order: Global Rates Panels on the Bonds Page (6 October 2026)",
                "naming": "the session whose data the vintage holds (second follow-up of 7 October 2026, G7)",
                "series": {}}
        for key in cfg["series"]:
            sub = new[new["series"] == key].tail(30)
            body["series"][key] = {**{k: meta.get(key, {}).get(k) for k in ("label", "source", "id", "url", "retrieved_at", "as_of", "error")},
                                   "observations": [[str(d.date()), round(float(v), 4)] for d, v in zip(sub["date"], sub["value"])]}
        vp.write_text(json.dumps(body, indent=1, default=str))
        idx["vintages"][session] = {"sha256": hashlib.sha256(vp.read_bytes()).hexdigest(), "written_at": now, "session": session}
        idx_p.write_text(json.dumps(idx, indent=1))
        log(f"vintage {vp.name} written")
    fails = [k for k, v in meta.items() if v.get("error")]
    log(f"{len(got)} series retrieved; failed: {fails or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
