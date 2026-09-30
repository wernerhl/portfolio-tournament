#!/usr/bin/env python3
"""edgar_common.py — shared EDGAR access for the ownership module (order 30-Sept-2026, E1 and E2).

Access policy — the one fact that governs every fetch. The SEC's fair-access rules require an
automated client to declare who it is: a User-Agent of the form "Company Name contact@domain".
Every EDGAR host (data.sec.gov, www.sec.gov, efts.sec.gov) answers 403 without it. The string is
read from the environment variable SEC_USER_AGENT; it is never hardcoded, never printed and never
served. When it is unset, every fetch raises RuntimeError BEFORE any connection is attempted and
the CLIs exit 3 having written nothing under data/ (they print what they would have fetched).
Requests are sequential at no more than 8 per second, declare Accept-Encoding gzip/deflate, and
are retried once after 2 s on 429 or 503. No browser user-agent, no other workaround.

The raw network call is the ONE function `http_get`; everything else (rate limit, retry, cache,
decoding, CIK lookup, the universe, the data-set readers) is testable with it replaced.

Universe: the held names (data/holdings.json) and the screen board's top 40 (data/screen/scores.json
watchlist rows with on_board_as == "top40"). The union universe (data/universe.txt) is the scope of
the insider-history store and of the registered candidate signal's validation.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent.parent.parent
DATA = REPO / "data"
OWN = DATA / "ownership"
# Downloaded data-set zips and Form 4 documents are cached here (gitignored `scratch/`), or under
# OWNERSHIP_CACHE_DIR, or wherever --cache-dir points. Nothing in the cache is served.
DEFAULT_CACHE = Path(os.environ.get("OWNERSHIP_CACHE_DIR") or (REPO / "scratch" / "edgar_cache"))

UA_ENV = "SEC_USER_AGENT"
UA_MISSING = "SEC_USER_AGENT not set: the SEC requires a declared contact for automated access"
MAX_RPS = 8                      # fair-access ceiling; enforced sequentially
RETRY_STATUSES = (429, 503)
RETRY_WAIT_S = 2.0
TIMEOUT_S = 60
EXIT_NO_UA = 3

HOST_DATA = "https://data.sec.gov"
HOST_WWW = "https://www.sec.gov"
COMPANY_TICKERS_URL = HOST_WWW + "/files/company_tickers.json"
INSIDER_DATASET_PREFIXES = (
    HOST_WWW + "/files/structureddata/data/insider-transactions-data-sets",
    HOST_WWW + "/files/datastandardsinnovation/data/insider-transactions-data-sets",
)
F13_DATASET_PREFIXES = (
    HOST_WWW + "/files/structureddata/data/form-13f-data-sets",
    HOST_WWW + "/files/datastandardsinnovation/data/form-13f-data-sets",
)
ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


# ── the declared contact ─────────────────────────────────────────────────
def user_agent() -> str:
    """The declared User-Agent from the environment. Raises before any network use when unset."""
    ua = (os.environ.get(UA_ENV) or "").strip()
    if not ua:
        raise RuntimeError(UA_MISSING)
    return ua


def user_agent_declared() -> bool:
    return bool((os.environ.get(UA_ENV) or "").strip())


# ── the one network call ─────────────────────────────────────────────────
class EdgarHTTPError(RuntimeError):
    def __init__(self, status: int, url: str):
        super().__init__("EDGAR returned HTTP %s for %s" % (status, url))
        self.status, self.url = status, url


def http_get(url: str, ua: str, timeout: float = TIMEOUT_S) -> tuple[int, dict, bytes]:
    """GET `url` with the declared User-Agent. Returns (status, lower-cased headers, raw body);
    HTTP error statuses are returned, not raised, so the caller decides about retries. This is the
    only place the module opens a connection — tests replace it."""
    req = Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate", "Accept": "*/*"})
    try:
        with urlopen(req, timeout=timeout) as r:
            return int(r.status), {k.lower(): v for k, v in r.headers.items()}, r.read()
    except HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        hdrs = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        return int(e.code), hdrs, body
    except URLError as e:
        raise RuntimeError("EDGAR unreachable for %s: %s" % (url, e.reason))


def decode_body(headers: dict, body: bytes) -> bytes:
    """Undo Content-Encoding gzip/deflate (urllib does not)."""
    enc = str(headers.get("content-encoding", "")).lower()
    if "gzip" in enc:
        try:
            return gzip.decompress(body)
        except Exception:
            return body
    if "deflate" in enc:
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


class RateLimiter:
    """Sequential ceiling of `per_second` requests: sleeps the remainder of 1/rate between calls."""

    def __init__(self, per_second: float = MAX_RPS, sleep=time.sleep, clock=time.monotonic):
        self.min_interval = 1.0 / float(per_second)
        self.sleep, self.clock = sleep, clock
        self._last: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self._last is not None:
            gap = self.min_interval - (now - self._last)
            if gap > 0:
                self.sleep(gap)
                now = self.clock()
        self._last = now


class EdgarClient:
    """Rate-limited, cached GET against EDGAR. Construction itself requires the declared contact."""

    def __init__(self, cache_dir: Path | str | None = None, ua: str | None = None,
                 sleep=time.sleep, clock=time.monotonic):
        self.ua = ua or user_agent()                       # raises when SEC_USER_AGENT is unset
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE)
        self.limiter = RateLimiter(MAX_RPS, sleep=sleep, clock=clock)
        self.sleep = sleep
        self.requests_made = 0
        self.cache_hits = 0
        self.log: list[tuple[str, int]] = []

    # cache ------------------------------------------------------------------
    def cache_path(self, url: str, cache_name: str | None = None) -> Path:
        if cache_name:
            return self.cache_dir / cache_name
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        tail = re.sub(r"[^A-Za-z0-9._-]", "_", url.rstrip("/").rsplit("/", 1)[-1])[:60] or "index"
        return self.cache_dir / "url" / (h + "_" + tail)

    def _cached(self, p: Path, max_age_s: float | None) -> bytes | None:
        if not p.exists():
            return None
        if max_age_s is not None and (time.time() - p.stat().st_mtime) > max_age_s:
            return None
        return p.read_bytes()

    @staticmethod
    def _write(p: Path, data: bytes) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    # fetch ------------------------------------------------------------------
    def _fetch(self, url: str) -> tuple[int, dict, bytes]:
        self.limiter.wait()
        self.requests_made += 1
        status, headers, body = http_get(url, self.ua)
        self.log.append((url, status))
        if status in RETRY_STATUSES:
            self.sleep(RETRY_WAIT_S)
            self.limiter.wait()
            self.requests_made += 1
            status, headers, body = http_get(url, self.ua)
            self.log.append((url, status))
        return status, headers, body

    def get(self, url: str, cache_name: str | None = None, max_age_s: float | None = None,
            allow_404: bool = False) -> bytes | None:
        """Bytes of `url`, from the cache when present (and younger than max_age_s when given).
        A 404 returns None when allow_404, else raises EdgarHTTPError; any other non-200 raises."""
        p = self.cache_path(url, cache_name)
        hit = self._cached(p, max_age_s)
        if hit is not None:
            self.cache_hits += 1
            return hit
        status, headers, body = self._fetch(url)
        if status == 404 and allow_404:
            return None
        if status != 200:
            raise EdgarHTTPError(status, url)
        data = decode_body(headers, body)
        self._write(p, data)
        return data

    def get_json(self, url: str, **kw):
        raw = self.get(url, **kw)
        return None if raw is None else json.loads(raw.decode("utf-8"))

    def fetch_first(self, candidates: list[str], cache_name: str) -> tuple[Path | None, str | None]:
        """The first candidate URL that exists (cached copy first, no network). Returns (path, url)."""
        p = self.cache_dir / cache_name
        if p.exists():
            self.cache_hits += 1
            return p, (candidates[0] if candidates else None)
        for url in candidates:
            data = self.get(url, cache_name=cache_name, allow_404=True)
            if data is not None:
                return self.cache_dir / cache_name, url
        return None, None


# ── CIK lookup ───────────────────────────────────────────────────────────
def cik10(x) -> str:
    """CIK as the 10-digit zero-padded string EDGAR uses in paths and XML."""
    s = str(x or "").strip()
    if not s:
        return ""
    try:
        return "%010d" % int(float(s))
    except ValueError:
        return s


def company_tickers(client: EdgarClient | None = None, raw: dict | None = None) -> dict[str, dict]:
    """{TICKER: {"cik": "0001045810", "title": "NVIDIA CORP"}} from company_tickers.json."""
    if raw is None:
        raw = client.get_json(COMPANY_TICKERS_URL, cache_name="company_tickers.json", max_age_s=12 * 3600)
    out: dict[str, dict] = {}
    rows = raw.values() if isinstance(raw, dict) else raw
    for r in rows:
        t = str(r.get("ticker", "")).upper().strip()
        if t:
            out[t] = {"cik": cik10(r.get("cik_str")), "title": str(r.get("title", "")).strip()}
    return out


def cik_for(ticker: str, table: dict[str, dict]) -> str | None:
    r = table.get(str(ticker).upper().strip())
    return r["cik"] if r else None


# ── universe ─────────────────────────────────────────────────────────────
def universe_from(holdings: dict | None, scores: dict | None) -> dict[str, list[str]]:
    """held = holdings.json positions with shares > 0; board = scores.json watchlist rows whose
    on_board_as == "top40" (a held name that also ranks on the board appears in both lists)."""
    held = sorted({str(h.get("ticker", "")).upper() for h in (holdings or {}).get("holdings", [])
                   if (h.get("shares") or 0) > 0 and h.get("ticker")})
    board = [str(r.get("ticker", "")).upper() for r in (scores or {}).get("watchlist", [])
             if r.get("on_board_as") == "top40" and r.get("ticker")]
    seen: set[str] = set()
    board = [t for t in board if not (t in seen or seen.add(t))]
    return {"held": held, "board": board}


def universe(data_dir: Path | None = None) -> dict[str, list[str]]:
    d = Path(data_dir or DATA)
    hp, sp = d / "holdings.json", d / "screen" / "scores.json"
    holdings = json.load(open(hp)) if hp.exists() else None
    scores = json.load(open(sp)) if sp.exists() else None
    return universe_from(holdings, scores)


def union_universe(data_dir: Path | None = None) -> list[str]:
    p = Path(data_dir or DATA) / "universe.txt"
    if not p.exists():
        return []
    return sorted({ln.strip().upper() for ln in p.read_text().splitlines() if ln.strip() and not ln.startswith("#")})


# ── submissions feed and Form 4 documents ────────────────────────────────
def submissions_url(cik) -> str:
    return "%s/submissions/CIK%s.json" % (HOST_DATA, cik10(cik))


def flatten_filings(block: dict) -> list[dict]:
    """The parallel arrays of a submissions `filings.recent` block (or a paging file) as rows."""
    if not block:
        return []
    keys = [k for k in ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument",
                        "primaryDocDescription") if k in block]
    n = len(block.get("accessionNumber") or [])
    return [{k: (block[k][i] if i < len(block[k]) else None) for k in keys} for i in range(n)]


def form4_filings(client: EdgarClient, cik, since_iso: str) -> tuple[list[dict], dict]:
    """Form 4 filings (form == "4") of an issuer filed on or after `since_iso`, following the
    submissions paging files when the recent block does not reach back that far."""
    sub = client.get_json(submissions_url(cik), cache_name="submissions/CIK%s.json" % cik10(cik), max_age_s=6 * 3600)
    filings = (sub or {}).get("filings") or {}
    rows = flatten_filings(filings.get("recent") or {})
    oldest = min((r.get("filingDate") or "9999") for r in rows) if rows else "9999"
    pages = 0
    for f in filings.get("files") or []:
        if oldest <= since_iso:
            break
        if str(f.get("filingTo") or "0000") < since_iso:
            continue
        more = client.get_json("%s/submissions/%s" % (HOST_DATA, f["name"]),
                               cache_name="submissions/%s" % f["name"], max_age_s=6 * 3600)
        page = flatten_filings(more or {})
        rows += page
        pages += 1
        if page:
            oldest = min(oldest, min((r.get("filingDate") or "9999") for r in page))
    counts = {"recent_rows": len(rows), "pages_followed": pages,
              "form4": sum(1 for r in rows if r.get("form") == "4" and (r.get("filingDate") or "") >= since_iso),
              "form4_amendments_skipped": sum(1 for r in rows if r.get("form") == "4/A" and (r.get("filingDate") or "") >= since_iso)}
    out = [r for r in rows if r.get("form") == "4" and (r.get("filingDate") or "") >= since_iso]
    out.sort(key=lambda r: (r.get("filingDate") or "", r.get("accessionNumber") or ""))
    return out, counts


def archive_folder_url(cik, accession: str) -> str:
    return "%s/Archives/edgar/data/%d/%s/" % (HOST_WWW, int(cik10(cik)), accession.replace("-", ""))


def form4_document_url(client: EdgarClient, cik, accession: str, primary_document: str | None) -> str:
    """URL of the ownership XML. The primaryDocument is usually the XML (sometimes prefixed with the
    XSL rendering folder); when it is not an .xml the folder listing is read and its ownership XML
    taken."""
    folder = archive_folder_url(cik, accession)
    pd_ = (primary_document or "").split("/")[-1]
    if pd_.lower().endswith(".xml"):
        return folder + pd_
    idx = client.get_json(folder + "index.json", cache_name="index/%s.json" % accession.replace("-", ""))
    items = ((idx or {}).get("directory") or {}).get("item") or []
    xmls = [it.get("name") for it in items if str(it.get("name", "")).lower().endswith(".xml")
            and not str(it.get("name", "")).lower().startswith("xsl")]
    if not xmls:
        raise RuntimeError("no ownership XML in %s" % folder)
    return folder + sorted(xmls)[0]


# ── quarterly data sets ──────────────────────────────────────────────────
def quarter_of(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def quarter_tag(y: int, q: int) -> str:
    return "%dq%d" % (y, q)


def quarters_between(start: date, end: date) -> list[tuple[int, int]]:
    y, q = quarter_of(start)
    ye, qe = quarter_of(end)
    out = []
    while (y, q) <= (ye, qe):
        out.append((y, q))
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def insider_dataset_candidates(y: int, q: int) -> list[str]:
    name = "%s_form345.zip" % quarter_tag(y, q)
    return [p + "/" + name for p in INSIDER_DATASET_PREFIXES]


def quarter_end(y: int, q: int) -> date:
    m = q * 3
    nxt = date(y + (m // 12), (m % 12) + 1, 1)
    return nxt - timedelta(days=1)


def f13_window_for(quarter_end_date: date) -> tuple[date, date, str]:
    """The three-month FILING window whose data set carries a quarter-end's 13F filings: it opens
    on the first day of the quarter-end's month (01mar, 01jun, 01sep, 01dec) and closes two months
    later. Returns (start, end, "01jun2026-31aug2026")."""
    start = date(quarter_end_date.year, quarter_end_date.month, 1)
    m = start.month + 3
    end = date(start.year + (m - 1) // 12, (m - 1) % 12 + 1, 1) - timedelta(days=1)
    tag = "%s-%s" % (start.strftime("%d%b%Y").lower(), end.strftime("%d%b%Y").lower())
    return start, end, tag


def f13_dataset_candidates(quarter_end_date: date) -> list[str]:
    """Both naming conventions under both prefixes; the newest window is expected under the
    datastandardsinnovation prefix, older ones under structureddata."""
    _, _, tag = f13_window_for(quarter_end_date)
    y, q = quarter_of(quarter_end_date)
    names = ["%s_form13f.zip" % tag, "%s_form13f.zip" % quarter_tag(y, q)]
    return [p + "/" + n for n in names for p in reversed(F13_DATASET_PREFIXES)]


def f13_quarter_ends_available(as_of: date, n: int = 2) -> list[date]:
    """The most recent quarter-ends whose filing window has closed by `as_of`, newest first."""
    out: list[date] = []
    y, q = quarter_of(as_of)
    while len(out) < n:
        qe = quarter_end(y, q)
        _, wend, _ = f13_window_for(qe)
        if wend < as_of:
            out.append(qe)
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        if y < 2013:
            break
    return out


# ── TSV readers (zip member or unpacked directory; names matched case-insensitively) ────
def _member_path(source: Path, member: str) -> tuple[str, str]:
    """('zip'|'dir', resolved member path)."""
    source = Path(source)
    want = member.lower()
    if source.is_dir():
        for p in source.rglob("*"):
            if p.is_file() and p.name.lower() == want:
                return "dir", str(p)
        raise FileNotFoundError("%s has no member %s" % (source, member))
    with zipfile.ZipFile(source) as z:
        for n in z.namelist():
            if n.split("/")[-1].lower() == want:
                return "zip", n
    raise FileNotFoundError("%s has no member %s" % (source, member))


def open_member(source: Path, member: str) -> io.TextIOBase:
    kind, path = _member_path(source, member)
    if kind == "dir":
        return open(path, "r", encoding="utf-8", errors="replace", newline="")
    z = zipfile.ZipFile(source)
    return io.TextIOWrapper(z.open(path), encoding="utf-8", errors="replace", newline="")


def _read_frame(fh, usecols=None, chunksize=None):
    import pandas as pd
    kw = dict(sep="\t", dtype=str, keep_default_na=False, quoting=csv.QUOTE_NONE,
              on_bad_lines="skip", engine="python" if chunksize is None else "c")
    if usecols is not None:
        want = {c.upper() for c in usecols}
        kw["usecols"] = lambda c: str(c).strip().upper() in want
    if chunksize:
        kw["chunksize"] = int(chunksize)
        kw["engine"] = "c"
    return pd.read_csv(fh, **kw)


def _norm(df):
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def read_tsv(source: Path, member: str, usecols=None):
    """Whole member as a DataFrame of strings (missing → ""), columns upper-cased."""
    with open_member(source, member) as fh:
        return _norm(_read_frame(fh, usecols=usecols))


def iter_tsv(source: Path, member: str, chunksize: int = 200_000, usecols=None):
    """Chunked reader for large members (INFOTABLE, NONDERIV_TRANS)."""
    fh = open_member(source, member)
    try:
        for chunk in _read_frame(fh, usecols=usecols, chunksize=chunksize):
            yield _norm(chunk)
    finally:
        fh.close()


def has_member(source: Path, member: str) -> bool:
    try:
        _member_path(source, member)
        return True
    except (FileNotFoundError, zipfile.BadZipFile):
        return False


# ── dates and numbers as the data sets write them ────────────────────────
_MON = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def parse_sec_date(s) -> str | None:
    """ISO date from the forms EDGAR uses: 2025-09-15, 15-SEP-2025, 20250915, 09/15/2025,
    2025-09-15T00:00:00. None when unparseable."""
    t = str(s or "").strip()
    if not t:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$", t)
        if m:
            d, y = int(m.group(1)), int(m.group(3))
            mo = _MON.get(m.group(2).upper())
            if not mo:
                return None
        else:
            m = re.match(r"^(\d{4})(\d{2})(\d{2})$", t)
            if m:
                y, mo, d = map(int, m.groups())
            else:
                m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", t)
                if not m:
                    return None
                mo, d, y = map(int, m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def num(s) -> float | None:
    t = str(s if s is not None else "").strip().replace(",", "")
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v == v else None


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


# ── served-file dates ────────────────────────────────────────────────────
def calendar():
    sys.path.insert(0, str(REPO / "scripts"))
    import trading_calendar as tc
    return tc


def et_now() -> datetime:
    return calendar().now_et()


def no_ua_exit(job: str, would_fetch: list[str]) -> int:
    """The CLI contract when SEC_USER_AGENT is unset: say so, list the fetches that were due,
    write nothing, exit 3."""
    print("[%s] %s" % (job, UA_MISSING), flush=True)
    print("[%s] nothing written under data/. It would have fetched:" % job, flush=True)
    for u in would_fetch:
        print("  would fetch " + u, flush=True)
    print("[%s] exit %d" % (job, EXIT_NO_UA), flush=True)
    return EXIT_NO_UA
