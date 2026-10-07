#!/usr/bin/env python3
"""
sp500_membership.py — a point-in-time S&P 500 membership file from the revision history of the Wikipedia list
(free-analyst-data order, 7 October 2026, task D1: "use the membership history file and say so").

No membership history exists in the repository and the survivorship-free data (Sharadar, Norgate) is not
installed. Wikipedia's "List of S&P 500 companies" has a revision for every edit since 2006; the revision in force
at each month-end is the list as the public saw it then, so a member that later left the index (or was delisted) is
present in the months it was a member. That removes the dependence on the current list (look-ahead check D3.1).
Limits, stated: the list is maintained by volunteers and can lag an index change by days; the price provider has
no bars for many delisted names, so those members enter the membership file but not the test — the report counts
them.

For each month-end from 2013-01-31: the latest revision at or before 23:59 UTC of that day (MediaWiki API,
rvdir=older), then that revision's page (index.php?oldid=), parsed for its first table's ticker column. One request
per second; every response cached under --cache (not committed); revision ids recorded in the output so the file
can be rebuilt exactly.

Outputs: data/analyst/sp500_membership_history.parquet (month_end, ticker, revid, rev_time) and
         data/analyst/sp500_membership_meta.json

Usage:  python scripts/analyst/sp500_membership.py [--from 2013-01-31] [--to 2026-09-30] [--cache DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = REPO / "data" / "analyst" / "sp500_membership_history.parquet"
META = REPO / "data" / "analyst" / "sp500_membership_meta.json"
TITLE = "List_of_S%26P_500_companies"
API = "https://en.wikipedia.org/w/api.php"
UA = "portfolio-tournament/1.0 (https://github.com/wernerhl/portfolio-tournament; research script, one request per second)"
MIN_INTERVAL_S = 1.0


def log(m: str) -> None:
    print(f"[sp500_membership] {m}", flush=True)


class Throttle:
    def __init__(self, interval=MIN_INTERVAL_S):
        self.interval, self.last, self.n = interval, 0.0, 0

    def wait(self):
        gap = time.monotonic() - self.last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self.last = time.monotonic(); self.n += 1


def fetch(url: str, cache: Path, th: Throttle) -> str:
    import hashlib
    import urllib.request
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    p = cache / f"{key}.txt"
    if p.exists():
        return p.read_text()
    th.wait()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8", errors="replace")
    p.write_text(body)
    return body


def revision_at(month_end: str, cache: Path, th: Throttle) -> tuple[int, str] | None:
    url = (f"{API}?action=query&prop=revisions&titles={TITLE}&rvlimit=1&rvdir=older"
           f"&rvstart={month_end}T23:59:59Z&rvprop=ids|timestamp&format=json&formatversion=2")
    j = json.loads(fetch(url, cache, th))
    pages = (j.get("query") or {}).get("pages") or []
    revs = (pages[0].get("revisions") if pages else None) or []
    return (int(revs[0]["revid"]), revs[0]["timestamp"]) if revs else None


def tickers_from_html(html: str) -> list[str]:
    tabs = pd.read_html(StringIO(html))
    for t in tabs:
        cols = [str(c).strip().lower() for c in t.columns]
        for want in ("symbol", "ticker symbol", "ticker"):
            if want in cols:
                col = t.columns[cols.index(want)]
                syms = [str(s).strip().upper() for s in t[col].dropna().tolist()]
                syms = [re.sub(r"\[.*?\]", "", s).replace(".", "-") for s in syms if s and s != "NAN"]
                syms = [s for s in syms if re.fullmatch(r"[A-Z0-9\-]{1,6}", s)]
                if len(syms) >= 400:
                    return sorted(set(syms))
    return []


def month_ends(a: str, b: str) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(a, b, freq="ME")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2013-01-31")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--cache", default=str(REPO.parent / ".cache_wiki_sp500"))
    a = ap.parse_args()
    end = a.end or (pd.Timestamp.today().normalize() - pd.offsets.MonthEnd(1)).strftime("%Y-%m-%d")
    cache = Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    th = Throttle()
    rows, meta_rows, problems = [], [], []
    mes = month_ends(a.start, end)
    log(f"{len(mes)} month-ends {mes[0]}..{mes[-1]}; cache {cache}")
    for i, me in enumerate(mes, 1):
        try:
            rv = revision_at(me, cache, th)
            if not rv:
                problems.append(f"{me}: no revision"); continue
            revid, ts = rv
            html = fetch(f"https://en.wikipedia.org/w/index.php?title={TITLE}&oldid={revid}", cache, th)
            syms = tickers_from_html(html)
            if len(syms) < 400:
                problems.append(f"{me}: revision {revid} parsed {len(syms)} tickers"); continue
            rows += [{"month_end": me, "ticker": s, "revid": revid, "rev_time": ts} for s in syms]
            meta_rows.append({"month_end": me, "revid": revid, "rev_time": ts, "n": len(syms)})
        except Exception as e:  # noqa: BLE001
            problems.append(f"{me}: {type(e).__name__}: {str(e)[:100]}")
        if i % 12 == 0 or i == len(mes):
            log(f"{i}/{len(mes)} months; {th.n} requests; {len(problems)} problems")
    df = pd.DataFrame(rows)
    df["month_end"] = pd.to_datetime(df["month_end"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    META.write_text(json.dumps({
        "cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"),
        "source": "Wikipedia, List of S&P 500 companies: the revision in force at each month-end (MediaWiki API + index.php?oldid)",
        "user_agent": UA, "rate": "one request per second; responses cached locally, not committed",
        "months": meta_rows, "problems": problems,
        "limits": "volunteer-maintained (an index change can lag by days); delisted members have no bars at the price provider and enter the test only where bars exist; tickers normalised '.'->'-'",
    }, indent=1))
    log(f"wrote {len(df)} rows for {df['month_end'].nunique()} month-ends; tickers ever listed {df['ticker'].nunique()}; problems {len(problems)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
