#!/usr/bin/env python3
"""
fetch_news.py — the two-tier news feed (Execution Order 30 Sept 2026, items B4 and E3).

Writes data/news.json: headline, source, URL, timestamp, tickers, topics and a SYSTEM-WRITTEN
one-line summary per item. Article bodies are never stored, and neither is the feed's own
description / summary text — every summary is composed here from structured fields only.

Tier 1 (primary, the issuer's own release): Federal Reserve press releases and speeches; BEA;
BLS release-day items (constructed from data/event_calendar.json and the release schedule —
nothing is fetched, BLS refuses automated clients); Census economic indicators (retail sales);
DOL (weekly claims); SEC EDGAR filings (8-K, 10-Q, 10-K, Form 4 for the held names and the
top-40 board; needs SEC_USER_AGENT); company investor-relations press releases for held names.
Tier 2 (secondary, labeled as such): per-ticker headline feeds for held names (yfinance
Ticker.news). A Tier 2 item is relevant only when its headline names a universe member.

Relevance: held names (data/holdings.json, shares > 0), the board's top 40 (data/screen/
scores.json, on_board_as == "top40") and macro topics mapped to calendar event types.
Language: the referee's two prohibited words (audit_nightly.py, language check) and buy/sell
directives are excluded at ingestion and counted under `excluded`, never stored; nothing here
recommends a trade. E3: a disclosed congressional / executive trade that appears in a Tier 2
headline is kept as news only and carries `disclosure_lag_label`; it is never a signal, a
score or a panel.

Run modes:
    python scripts/fetch_news.py                 fetch + write data/news.json
    python scripts/fetch_news.py --dry-run       fetch, print the summary, write nothing
    python scripts/fetch_news.py --hours 48      panel window (default 24); 7 days are stored
    python scripts/fetch_news.py --offline DIR   read feed files from DIR instead of the network
Offline layout: {source id}.xml for rss/atom sources, yahoo_{TICKER}.json (the yfinance list),
edgar_company_tickers.json and edgar_CIK{cik:010d}.json.
Test overrides: --out, --sources, --holdings, --scores, --calendar, --now (ET ISO), --no-merge.
Standard library only, plus yfinance for Tier 2 (imported lazily). Python 3.11 compatible.
Log lines are prefixed `[fetch_news]`.
"""
from __future__ import annotations

import argparse
import codecs
import email.utils
import gzip
import hashlib
import html
import json
import os
import re
import sys
import time
import traceback
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trading_calendar import last_completed_session, now_et  # noqa: E402

ET_ZONE = ZoneInfo("America/New_York")
USER_AGENT = "portfolio-tournament/1.0 (+https://github.com/wernerhl/portfolio-tournament)"
HEADLINE_MAX = 200
DEFAULT_WINDOW_HOURS = 24
DEFAULT_STORED_DAYS = 7
FETCH_TIMEOUT = 25
EDGAR_FORMS = ("8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "4", "4/A")
EDGAR_MIN_INTERVAL = 1.0 / 8          # at most 8 requests per second, sequential
RULE = ("primary sources first: Tier 1 = the issuer's own release (Fed, BEA, BLS, Census, DOL, SEC EDGAR "
        "filings, company investor relations); Tier 2 = secondary headline feeds, labeled; bodies never stored; "
        "summaries system-written")
DISCLOSURE_LAG_LABEL = "disclosed trade — reports lag the trade by up to 45 days; shown as news only, no signal"

# The referee's language check (scripts/audit_nightly.py): these two words appear nowhere in a
# served file. Checked on the FULL serialized item (headline, source, url, summary, ...).
PROHIBITED_WORDS = ("edge", "alpha")
PROHIBITED_RE = re.compile(r"\b(" + "|".join(PROHIBITED_WORDS) + r")\b", re.IGNORECASE)
# A buy/sell directive in any stored text — the referee's tokens plus the plain-English forms.
DIRECTIVE_PATTERNS = (
    r"\b(buy|sell)\s+now\b",
    r"\"(action|recommendation)\"\s*:\s*\"(buy|sell)\"",
    r"\b(buy|sell)\s+(the\s+)?dips?\b",
    r"\btime\s+to\s+(buy|sell)\b",
    r"\bshould\s+(you|i|we|investors)\s+(buy|sell)\b",
    r"\bstrong\s+(buy|sell)\b",
    r"\b(buy|sell)\s+ratings?\b",
    r"\bstocks?\s+to\s+(buy|sell)\b",
    r"\b(buy|sell)\s+(this|these|it)\b",
    r"\b(buy|sell)\s+(before|ahead\s+of)\b",
    r"\b(buy|sell)\s+more\b",
)
DIRECTIVE_RE = re.compile("|".join(DIRECTIVE_PATTERNS), re.IGNORECASE)

# E3: congressional / executive-branch trade disclosure vocabulary (case-insensitive) — a Tier 2
# headline matching one of these AND a trade word carries the disclosure-lag label.
DISCLOSURE_VOCAB = ("congress", "senator", "representative", "lawmaker", "pelosi", "capitol trades",
                    "stock act", "periodic transaction report", "executive branch", "cabinet")
TRADE_WORDS = ("bought", "sold", "trade", "purchase", "sale", "stock")

# Macro topic keywords → calendar event types (the registry may override with `topic_keywords`).
# Multi-word phrases and lowercase words match case-insensitively; all-caps acronyms match as
# whole words, case-sensitively.
DEFAULT_TOPIC_KEYWORDS = {
    "FOMC": ["FOMC", "Federal Open Market Committee", "federal funds"],
    "PCE": ["Personal Income and Outlays", "PCE"],
    "GDP": ["Gross Domestic Product", "GDP"],
    "CPI": ["Consumer Price Index", "CPI"],
    "PPI": ["Producer Price Index", "PPI"],
    "NFP": ["Employment Situation", "payroll"],
    "JOLTS": ["Job Openings", "JOLTS"],
    "RETAIL": ["Retail"],
    "CLAIMS": ["Unemployment Insurance Weekly Claims", "initial claims"],
    "TRADE": ["International Trade"],
}

# Ticker symbols that are ordinary English words in capitals: a bare whole-word match is not
# enough for these, the headline must show them in ticker context — (SYM), $SYM or NYSE: SYM.
AMBIGUOUS_SYMBOLS = {"A", "AI", "ALL", "AMP", "AN", "ARE", "AT", "BE", "BIG", "BR", "BY", "CAN", "CAT", "COST",
                     "DASH", "DE", "FAST", "FOR", "GAP", "GO", "GOOD", "HAS", "HIGH", "IN", "IT", "KEY", "LOVE",
                     "LOW", "MA", "MS", "NEXT", "NOW", "ON", "ONE", "OPEN", "PATH", "PLAY", "REAL", "RUN", "SAVE",
                     "SEE", "SO", "TECH", "TWO", "UP", "WELL"}
CORPORATE_SUFFIXES = ("inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "limited", "plc",
                      "nv", "n.v", "sa", "s.a", "llc", "the")
ATOM_NS = "{http://www.w3.org/2005/Atom}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"


def log(msg: str) -> None:
    print(f"[fetch_news] {msg}", flush=True)


# ─── time ─────────────────────────────────────────────────────────────────────────────────
def parse_timestamp(value) -> datetime | None:
    """RFC-822 (email.utils, incl. 2-digit years and EDT/EST names), ISO 8601 (with Z) or an
    epoch number → aware datetime in ET. Naive inputs are taken as UTC. None when unparseable."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(ET_ZONE)
        except (OverflowError, OSError, ValueError):
            return None
    s = " ".join(str(value).split())
    if not s:
        return None
    dt = None
    try:
        dt = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError, OverflowError):
        dt = None
    if dt is None:
        iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET_ZONE)


def iso_et(dt: datetime) -> str:
    return dt.astimezone(ET_ZONE).isoformat(timespec="seconds")


def parse_now(text: str | None) -> datetime:
    if not text:
        return now_et()
    dt = datetime.fromisoformat(text)
    return dt.replace(tzinfo=ET_ZONE) if dt.tzinfo is None else dt.astimezone(ET_ZONE)


# ─── text ─────────────────────────────────────────────────────────────────────────────────
def clean_headline(text) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    s = " ".join(s.split()).strip()
    if len(s) > HEADLINE_MAX:
        cut = s[:HEADLINE_MAX - 1]
        if " " in cut[HEADLINE_MAX // 2:]:           # cut at a word boundary: a hard cut could manufacture a word
            cut = cut.rsplit(" ", 1)[0]
        s = cut.rstrip(" ,;:-–—") + "…"
    return s


def clean_url(url) -> str:
    u = " ".join(str(url or "").split()).strip()
    if not u:
        return ""
    try:
        p = urllib.parse.urlsplit(u)
        q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
        u = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), p.fragment))
    except ValueError:
        pass
    return u


def item_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def match_topics(headline: str, keywords: dict) -> list[str]:
    out = []
    low = headline.lower()
    for topic, words in keywords.items():
        for w in words:
            if w.isupper() and " " not in w:
                hit = re.search(r"(?<![A-Za-z0-9])" + re.escape(w) + r"(?![A-Za-z0-9])", headline) is not None
            else:
                hit = re.search(r"(?<![A-Za-z0-9])" + re.escape(w.lower()), low) is not None
            if hit:
                out.append(topic)
                break
    return out


def disclosure_label(headline: str) -> str | None:
    low = headline.lower()
    if any(v in low for v in DISCLOSURE_VOCAB) and any(re.search(r"\b" + t + r"s?\b", low) for t in TRADE_WORDS):
        return DISCLOSURE_LAG_LABEL
    return None


def name_phrases(name: str) -> list[str]:
    """Company-name phrases used to spot a universe member in a Tier 2 headline. Cuts at the
    first comma / parenthesis, drops corporate suffixes (also truncated ones such as
    'Corporati' from the 30-char names of scores.json); a trailing partial word is fine
    because phrases match as prefixes."""
    base = re.sub(r"\s*\(.*$", "", str(name or "").split(",")[0]).strip()
    words = base.split()
    while words:
        w = words[-1].lower().rstrip(".")
        if any(w == s or (len(w) >= 3 and len(s) > len(w) and s.startswith(w)) for s in CORPORATE_SUFFIXES):
            words.pop()
            continue
        break
    phrase = " ".join(words)
    out = []
    if len(phrase) >= 4:
        out.append(phrase)
    if phrase.lower().endswith(".com") and len(phrase) > 8:
        out.append(phrase[:-4])
    return out


def mention_tickers(headline: str, names: dict) -> list[str]:
    """Universe members named in a headline: the symbol as a whole word (ticker context required
    for English-word symbols) or a company-name phrase, case-insensitively."""
    found = []
    low = headline.lower()
    for tk, phrases in names.items():
        hit = False
        sym = re.escape(tk)
        if tk in AMBIGUOUS_SYMBOLS:
            hit = re.search(r"\(" + sym + r"\)|\$" + sym + r"(?![A-Za-z0-9])|(NYSE|NASDAQ|Nasdaq):\s*" + sym + r"(?![A-Za-z0-9])", headline) is not None
        else:
            hit = re.search(r"(?<![A-Za-z0-9])" + sym + r"(?![A-Za-z0-9])", headline) is not None
        if not hit:
            for ph in phrases:
                if re.search(r"(?<![A-Za-z0-9])" + re.escape(ph.lower()), low):
                    hit = True
                    break
        if hit:
            found.append(tk)
    return found


def reference_period(day: date, lag_months: int) -> str:
    y, m = day.year, day.month - int(lag_months or 0)
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1).strftime("%B %Y")


# ─── network ──────────────────────────────────────────────────────────────────────────────
def fetch_bytes(url: str, headers: dict | None = None, timeout: int = FETCH_TIMEOUT) -> bytes:
    h = {"User-Agent": USER_AGENT,
         "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, application/json;q=0.9, */*;q=0.8",
         "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


# ─── feed parsing (xml.etree only; no feedparser) ─────────────────────────────────────────
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_feed(raw: bytes) -> list[dict]:
    """RSS 2.0 / RSS 1.0 / Atom → [{title, link, published, category, next_release}]. The
    description / content / summary elements are deliberately never read."""
    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[len(codecs.BOM_UTF8):]
    root = ET.fromstring(raw.lstrip())
    out = []
    entries = list(root.iter(ATOM_NS + "entry"))
    if entries:
        for e in entries:
            link = None
            for ln in e.findall(ATOM_NS + "link"):
                if ln.get("rel", "alternate") == "alternate" and ln.get("href"):
                    link = ln.get("href")
                    break
            if link is None:
                first = e.find(ATOM_NS + "link")
                link = first.get("href") if first is not None and first.get("href") else (e.findtext(ATOM_NS + "id") or "")
            cats = [c.get("term") for c in e.findall(ATOM_NS + "category") if c.get("term")]
            out.append({"title": e.findtext(ATOM_NS + "title") or "", "link": link,
                        "published": e.findtext(ATOM_NS + "published") or e.findtext(ATOM_NS + "updated"),
                        "category": cats[0] if cats else None, "next_release": None})
        return out
    for it in root.iter():
        if _local(it.tag) != "item":
            continue
        fields = {}
        for ch in it:
            name = _local(ch.tag)
            if name in ("title", "link", "pubDate", "date", "category", "NextReleaseDate", "guid") and name not in fields:
                fields[name] = ch
        title = (fields["title"].text or "") if "title" in fields else ""
        link = ((fields["link"].text or "").strip() or fields["link"].get("href", "")) if "link" in fields else ""
        if not link and "guid" in fields:
            g = fields["guid"]
            if (g.get("isPermaLink", "true").lower() != "false") and (g.text or "").strip().startswith("http"):
                link = g.text.strip()
        published = None
        for key in ("pubDate", "date"):
            if key in fields and (fields[key].text or "").strip():
                published = fields[key].text
                break
        out.append({"title": title, "link": link, "published": published,
                    "category": (fields["category"].text or "").strip() if "category" in fields else None,
                    "next_release": (fields["NextReleaseDate"].text or "").strip() if "NextReleaseDate" in fields else None})
    return out


# ─── context ──────────────────────────────────────────────────────────────────────────────
class Context:
    def __init__(self, now: datetime, window_hours: int, stored_days: int, held: list[str], top40: list[str],
                 names: dict, topic_keywords: dict, calendar_events: list, offline: Path | None):
        self.now = now
        self.window_hours = window_hours
        self.stored_days = stored_days
        self.held = held
        self.top40 = top40
        self.universe = sorted(set(held) | set(top40))
        self.names = names
        self.topic_keywords = topic_keywords
        self.calendar_events = calendar_events
        self.offline = offline
        self.stored_start = now - timedelta(days=stored_days)
        self.window_start = now - timedelta(hours=window_hours)


def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def held_names(holdings: dict) -> list[str]:
    out = []
    for h in (holdings or {}).get("holdings", []):
        tk = str(h.get("ticker", "")).strip().upper()
        try:
            shares = float(h.get("shares") or 0)
        except (TypeError, ValueError):
            shares = 0.0
        if tk and shares > 0 and tk not in out:
            out.append(tk)
    return out


def top40_names(scores: dict) -> list[str]:
    out = []
    for r in (scores or {}).get("watchlist", []):
        tk = str(r.get("ticker", "")).strip().upper()
        if tk and r.get("on_board_as") == "top40" and tk not in out:
            out.append(tk)
    return out


def build_name_index(cfg: dict, scores: dict, universe: list[str]) -> dict:
    idx = {tk: [] for tk in universe}
    for tk, aliases in (cfg.get("aliases") or {}).items():
        if tk in idx:
            for a in aliases:
                if a not in idx[tk]:
                    idx[tk].append(a)
    for r in (scores or {}).get("watchlist", []):
        tk = str(r.get("ticker", "")).strip().upper()
        if tk in idx:
            for ph in name_phrases(r.get("name") or ""):
                if ph not in idx[tk]:
                    idx[tk].append(ph)
    return idx


def candidate(tier: int, kind: str, headline, source: str, source_id: str, url, ts, tickers=None, topics=None,
              summary: str = "", keep_without_topic: bool = False, extra: dict | None = None) -> dict:
    return {"tier": tier, "kind": kind, "headline": clean_headline(headline), "source": source, "source_id": source_id,
            "url": clean_url(url), "ts": ts, "tickers": list(tickers or []), "topics": list(topics or []),
            "summary": summary, "keep_without_topic": keep_without_topic, "extra": extra or {}}


# ─── sources ──────────────────────────────────────────────────────────────────────────────
def offline_file(ctx: Context, name: str) -> Path | None:
    p = ctx.offline / name
    return p if p.exists() else None


def fetch_feed_source(src: dict, ctx: Context) -> tuple[list, str]:
    """rss / atom sources: macro feeds (tickers empty, topics from the title) and company
    investor-relations feeds (the registered ticker)."""
    status = str(src.get("status") or "ok")
    if not status.startswith("ok"):
        return [], f"skipped: {status}"
    ticker = (src.get("ticker") or "").upper() or None
    if ticker and ticker not in ctx.held:
        return [], f"skipped: {ticker} not held"
    if ctx.offline is not None:
        p = offline_file(ctx, f"{src['id']}.xml")
        if p is None:
            return [], "skipped: no offline fixture"
        raw = p.read_bytes()
    else:
        raw = fetch_bytes(src["url"])
    entries = parse_feed(raw)
    label = src.get("label") or src["id"]
    out = []
    for e in entries:
        ts = parse_timestamp(e.get("published"))
        if ticker:
            summary = f"Tier 1 · issuer press release · {ticker} · {label}"
            out.append(candidate(int(src.get("tier", 1)), "issuer", e["title"], label, src["id"], e["link"], ts,
                                 tickers=[ticker], summary=summary))
        else:
            extra = {"category": (e.get("category") or "").strip() or None, "next_release": e.get("next_release")}
            out.append(candidate(int(src.get("tier", 1)), "macro", e["title"], label, src["id"], e["link"], ts,
                                 keep_without_topic=bool(src.get("keep_without_topic")), extra=extra))
    return out, f"parsed {len(entries)}"


def release_day_items(src: dict, ctx: Context) -> tuple[list, str]:
    """BLS (and BEA fallback) release-day items constructed from the calendar and the registered
    release schedule: nothing is fetched. Only releases already past their scheduled time and
    inside the stored window are created; the URL carries the release date as a fragment so
    each print is one item while the link stays the live release page."""
    pages = src.get("release_pages") or {}
    out = []
    for ev in ctx.calendar_events:
        page = pages.get(str(ev.get("type", "")))
        if not page:
            continue
        try:
            day = date.fromisoformat(str(ev.get("date", ""))[:10])
        except ValueError:
            continue
        time_et = str(ev.get("time_et") or page.get("time_et") or "08:30")   # the calendar's official time first
        try:
            hh, mm = [int(x) for x in time_et.split(":")[:2]]
        except ValueError:
            hh, mm, time_et = 8, 30, "08:30"
        ts = datetime(day.year, day.month, day.day, hh, mm, tzinfo=ET_ZONE)
        if ts > ctx.now or ts < ctx.stored_start:
            continue
        ref = reference_period(day, int(page.get("reference_lag_months", 1)))
        headline = f"{src.get('headline_prefix') or 'Release'}: {page['name']} ({ref})"
        url = f"{page['url']}#{day.isoformat()}"
        summary = f"scheduled release at {time_et} ET; print not fetched"
        out.append(candidate(1, "release_day", headline, src.get("label") or src["id"], src["id"], url, ts,
                             topics=[str(ev.get("type"))], summary=summary, keep_without_topic=True))
    return out, f"constructed {len(out)}"


def edgar_user_agent() -> str | None:
    ua = (os.environ.get("SEC_USER_AGENT") or "").strip()
    return ua or None


def parse_edgar_submissions(obj: dict, cik: int, tk: str, forms, src_id: str, label: str) -> list[dict]:
    rec = ((obj or {}).get("filings") or {}).get("recent") or {}
    accs = rec.get("accessionNumber") or []
    n = len(accs)

    def col(name):
        v = rec.get(name) or []
        return list(v) + [None] * (n - len(v))
    fdates, fforms, docs, descs, acc_times = col("filingDate"), col("form"), col("primaryDocument"), col("primaryDocDescription"), col("acceptanceDateTime")
    name = (obj.get("name") or tk).strip()
    out = []
    for i in range(n):
        form = str(fforms[i] or "").strip()
        if form not in forms:
            continue
        ts = parse_timestamp(acc_times[i]) if acc_times[i] else None
        if ts is None and fdates[i]:
            try:
                d = date.fromisoformat(str(fdates[i])[:10])
                ts = datetime(d.year, d.month, d.day, 12, 0, tzinfo=ET_ZONE)   # no acceptance time: noon ET of the filing date
            except ValueError:
                ts = None
        acc = str(accs[i] or "").replace("-", "")
        doc = str(docs[i] or "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
        form_label = f"Form {form}" if form.split("/")[0].isdigit() else form
        headline = f"{form_label} filed by {name}"
        summary = f"EDGAR {form} · filed {fdates[i]} · {(descs[i] or '').strip() or form}"
        out.append(candidate(1, "edgar", headline, label, src_id, url, ts, tickers=[tk], summary=summary))
    return out


def fetch_edgar(src: dict, ctx: Context) -> tuple[list, str]:
    forms = tuple(src.get("forms") or EDGAR_FORMS)
    label = src.get("label") or "SEC EDGAR"
    headers = None
    if ctx.offline is None:
        ua = edgar_user_agent()
        if not ua:
            return [], "skipped: SEC_USER_AGENT not set"
        headers = {"User-Agent": ua}
        mapping = json.loads(fetch_bytes(src.get("ticker_map_url") or "https://www.sec.gov/files/company_tickers.json", headers=headers))
    else:
        p = offline_file(ctx, "edgar_company_tickers.json")
        if p is None:
            return [], "skipped: no offline fixture"
        mapping = load_json(p, {})
    by_ticker = {}
    for row in (mapping.values() if isinstance(mapping, dict) else mapping):
        if isinstance(row, dict) and row.get("ticker"):
            by_ticker[str(row["ticker"]).upper()] = (int(row.get("cik_str") or 0), str(row.get("title") or ""))
    out, failed, missing, n_names = [], [], [], 0
    last = 0.0
    for tk in ctx.universe:
        if tk not in by_ticker:
            missing.append(tk)
            continue
        cik, _title = by_ticker[tk]
        try:
            if ctx.offline is None:
                wait = EDGAR_MIN_INTERVAL - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait)
                last = time.monotonic()
                obj = json.loads(fetch_bytes(src["url"].format(cik=cik), headers=headers))
            else:
                p = offline_file(ctx, f"edgar_CIK{cik:010d}.json")
                if p is None:
                    continue
                obj = load_json(p, {})
            n_names += 1
            out.extend(parse_edgar_submissions(obj, cik, tk, forms, src["id"], label))
        except Exception as e:      # one name failing never fails the source
            failed.append(f"{tk} ({type(e).__name__})")
    note = f"parsed {n_names} names"
    if failed:
        note += f"; failed {len(failed)}: {', '.join(failed[:6])}"
    if missing:
        note += f"; no CIK: {', '.join(missing[:8])}"
    return out, note


def fetch_yahoo(src: dict, ctx: Context) -> tuple[list, dict]:
    """Tier 2 headlines per held name via yfinance Ticker.news. Only title, pubDate, provider
    displayName and the canonical / click-through URL are read; description and summary are
    never touched."""
    items, statuses = [], {}
    label = src.get("label") or "Yahoo Finance headline feed"
    for tk in ctx.held:
        key = f"{src['id']}:{tk}"
        try:
            if ctx.offline is not None:
                p = offline_file(ctx, f"yahoo_{tk}.json")
                if p is None:
                    statuses[key] = "skipped: no offline fixture"
                    continue
                raw = load_json(p, []) or []
            else:
                import yfinance as yf     # lazy: the offline path needs no third-party module
                raw = yf.Ticker(tk).news or []
            n = 0
            for rec in raw:
                c = rec.get("content") if isinstance(rec.get("content"), dict) else rec
                title = c.get("title") or ""
                pub = c.get("pubDate") or c.get("providerPublishTime")
                prov = c.get("provider") if isinstance(c.get("provider"), dict) else {}
                provider = (prov.get("displayName") or c.get("publisher") or "Yahoo Finance").strip()
                url = ""
                for k in ("canonicalUrl", "clickThroughUrl"):
                    v = c.get(k)
                    if isinstance(v, dict) and v.get("url"):
                        url = v["url"]
                        break
                url = url or c.get("link") or ""
                if not title or not url:
                    continue
                items.append(candidate(2, "secondary", title, provider, key, url, parse_timestamp(pub), tickers=[tk],
                                       summary="", extra={"provider": provider, "seed": tk, "label": label}))
                n += 1
            statuses[key] = f"parsed {n}"
        except Exception as e:
            statuses[key] = f"failed: {type(e).__name__}: {str(e)[:120]}"
    return items, statuses


# ─── the pipeline: window → relevance → language → dedupe ─────────────────────────────────
def relevant(c: dict, ctx: Context) -> bool:
    """Mutates tickers / topics / summary. Fed items (keep_without_topic) always pass; other
    macro items need a topic; issuer and EDGAR items need a universe ticker; a Tier 2 item needs
    a universe member named in its headline."""
    kind = c["kind"]
    if kind in ("macro", "release_day"):
        if not c["topics"]:
            c["topics"] = match_topics(c["headline"], ctx.topic_keywords)
        if not c["topics"] and not c["keep_without_topic"]:
            return False
        if kind == "macro":
            bits = [f"Tier 1 · {c['source']}"]
            cat = c["extra"].get("category")
            if cat:
                bits.append(cat)
            bits.append("topics: " + (", ".join(c["topics"]) if c["topics"] else "none"))
            if c["extra"].get("next_release"):
                bits.append("next release " + str(c["extra"]["next_release"]))
            c["summary"] = " · ".join(bits)
        return True
    if kind in ("issuer", "edgar"):
        return any(tk in ctx.universe for tk in c["tickers"])
    if kind == "secondary":
        mentioned = mention_tickers(c["headline"], ctx.names)
        if not mentioned:
            return False
        seed = c["extra"].get("seed")
        c["tickers"] = ([seed] if seed in mentioned else []) + [t for t in mentioned if t != seed]
        c["summary"] = f"Tier 2 headline · {c['extra'].get('provider') or c['source']} · about {', '.join(c['tickers'])}"
        return True
    return False


def finalize(c: dict) -> dict:
    tier = int(c["tier"])
    return {"id": item_id(c["url"]), "tier": tier, "tier_label": "primary" if tier == 1 else "secondary",
            "headline": c["headline"], "source": c["source"], "source_id": c["source_id"], "url": c["url"],
            "timestamp": iso_et(c["ts"]), "tickers": list(c["tickers"]), "topics": list(c["topics"]),
            "summary": c["summary"], "disclosure_lag_label": disclosure_label(c["headline"]) if tier == 2 else None}


def language_violation(item: dict) -> str | None:
    """Checked on the serialized item (as the referee reads the file) AND on the plain text
    fields (JSON escaping would otherwise hide a quoted directive inside a headline)."""
    plain = " ".join(str(v) for v in item.values() if isinstance(v, str))
    for text in (json.dumps(item, ensure_ascii=False), plain):
        if PROHIBITED_RE.search(text):
            return "vocabulary_rule"
        if DIRECTIVE_RE.search(text):
            return "directive_rule"
    return None


def merge_into(by_id: dict, item: dict) -> None:
    prev = by_id.get(item["id"])
    if prev is None:
        by_id[item["id"]] = item
        return
    keep, other = (item, prev) if item["tier"] < prev["tier"] else (prev, item)
    for tk in other["tickers"]:
        if tk not in keep["tickers"]:
            keep["tickers"].append(tk)
    for tp in other["topics"]:
        if tp not in keep["topics"]:
            keep["topics"].append(tp)
    if keep["tier"] == 2 and keep["summary"].startswith("Tier 2 headline"):
        keep["summary"] = keep["summary"].split(" · about ")[0] + " · about " + ", ".join(keep["tickers"])
    by_id[item["id"]] = keep


def process(cands: list, prior: list, ctx: Context) -> tuple[list, dict, dict]:
    excluded = {"vocabulary_rule": 0, "directive_rule": 0, "irrelevant": 0, "out_of_window": 0, "unparseable": 0}
    kept_by_source = {}
    by_id = {}
    for c in cands:
        if not c["headline"] or not c["url"] or c["ts"] is None:
            excluded["unparseable"] += 1
            continue
        if c["ts"] < ctx.stored_start:
            excluded["out_of_window"] += 1
            continue
        if not relevant(c, ctx):
            excluded["irrelevant"] += 1
            continue
        item = finalize(c)
        v = language_violation(item)
        if v:
            excluded[v] += 1
            continue
        merge_into(by_id, item)
        kept_by_source[c["source_id"]] = kept_by_source.get(c["source_id"], 0) + 1
    # the previously served items keep the 7-day depth for names whose feeds have moved on;
    # they are re-checked against the window and the language rules, never trusted blindly
    for p in prior or []:
        try:
            ts = parse_timestamp(p.get("timestamp"))
            if ts is None or ts < ctx.stored_start or not p.get("url") or not p.get("headline"):
                continue
            item = {"id": item_id(clean_url(p["url"])), "tier": int(p.get("tier", 2)),
                    "tier_label": "primary" if int(p.get("tier", 2)) == 1 else "secondary",
                    "headline": clean_headline(p["headline"]), "source": str(p.get("source") or ""),
                    "source_id": str(p.get("source_id") or ""), "url": clean_url(p["url"]), "timestamp": iso_et(ts),
                    "tickers": [str(t).upper() for t in (p.get("tickers") or [])], "topics": list(p.get("topics") or []),
                    "summary": str(p.get("summary") or ""),
                    "disclosure_lag_label": disclosure_label(clean_headline(p["headline"])) if int(p.get("tier", 2)) == 2 else None}
            if language_violation(item) or item["id"] in by_id:
                continue
            by_id[item["id"]] = item
        except (TypeError, ValueError, AttributeError):
            continue
    items = sorted(by_id.values(), key=lambda x: (x["timestamp"], -x["tier"], x["id"]), reverse=True)
    return items, excluded, kept_by_source


def assemble(items: list, ctx: Context, as_of: str, sources_status: dict, excluded: dict) -> dict:
    per_name = {}
    for tk in ctx.held:
        per_name[tk] = [it["id"] for it in items if tk in it["tickers"]][:5]
    win = [it for it in items if parse_timestamp(it["timestamp"]) >= ctx.window_start]
    last24h = [it["id"] for it in win if it["tier"] == 1] + [it["id"] for it in win if it["tier"] == 2]
    n1 = sum(1 for it in items if it["tier"] == 1)
    return {"cadence": "intraday", "as_of": as_of, "fetched_at": iso_et(ctx.now), "window_hours": ctx.window_hours,
            "stored_days": ctx.stored_days, "rule": RULE,
            "universe": {"held": list(ctx.held), "top40": list(ctx.top40)},
            "sources_status": sources_status, "excluded": excluded,
            "counts": {"items": len(items), "tier1": n1, "tier2": len(items) - n1, "last24h": len(last24h)},
            "items": items, "per_name": per_name, "last24h": last24h}


def served_text_violation(text: str) -> str | None:
    """The whole served blob passes the referee's language check, or nothing is written."""
    low = text.lower()
    hits = [w for w in PROHIBITED_WORDS if re.search(r"\b" + w + r"\b", low)]
    if hits:
        return f"prohibited word(s) {hits}"
    for tok in ('"action":"buy"', '"action":"sell"', '"recommendation":"buy"', '"recommendation":"sell"', "buy now", "sell now"):
        if tok in low:
            return f"directive token {tok!r}"
    return None


# ─── main ─────────────────────────────────────────────────────────────────────────────────
def run(args) -> int:
    now = parse_now(args.now)
    cfg = load_json(Path(args.sources))
    if not cfg or not isinstance(cfg.get("sources"), list):
        log(f"source registry unreadable: {args.sources}")
        return 2
    holdings = load_json(Path(args.holdings), {}) or {}
    scores = load_json(Path(args.scores), {}) or {}
    calendar = load_json(Path(args.calendar), {}) or {}
    held = held_names(holdings)
    top40 = top40_names(scores)
    universe = sorted(set(held) | set(top40))
    names = build_name_index(cfg, scores, universe)
    ctx = Context(now, int(args.hours), int(args.stored_days), held, top40, names,
                  cfg.get("topic_keywords") or DEFAULT_TOPIC_KEYWORDS,
                  list(calendar.get("events") or []), Path(args.offline) if args.offline else None)
    as_of = last_completed_session(now)
    log(f"as_of {as_of} · now {iso_et(now)} · window {ctx.window_hours}h · stored {ctx.stored_days}d · "
        f"held {len(held)} · top40 {len(top40)} · {'offline ' + str(ctx.offline) if ctx.offline else 'network'}")

    cands, status, notes = [], {}, {}
    for src in cfg["sources"]:
        sid = src.get("id")
        kind = src.get("kind")
        if not sid or not kind:
            continue
        try:
            if kind in ("rss", "atom"):
                got, note = fetch_feed_source(src, ctx)
            elif kind == "bls_release_day":
                got, note = release_day_items(src, ctx)
            elif kind == "bea_release_day":
                primary = str(status.get(src.get("fallback_for", ""), ""))
                if primary.startswith("failed"):
                    got, note = release_day_items(src, ctx)
                else:
                    got, note = [], "skipped: primary feed ok"
            elif kind == "edgar_submissions":
                got, note = fetch_edgar(src, ctx)
            elif kind == "yahoo_ticker":
                got, per = fetch_yahoo(src, ctx)
                for k, v in per.items():
                    status[k] = v
                    if not v.startswith("parsed"):
                        continue
                    notes[k] = v
                note = None
            else:
                got, note = [], f"skipped: unknown kind {kind}"
        except Exception as e:     # any single source failing never fails the run
            got, note = [], f"failed: {type(e).__name__}: {str(e)[:140]}"
            log(f"{sid} failed: {type(e).__name__}: {e}")
        cands.extend(got)
        if note is not None:
            status[sid] = note
            if note.startswith("parsed") or note.startswith("constructed"):
                notes[sid] = note
        log(f"{sid}: {note if note is not None else 'per-ticker'} · {len(got)} candidates")

    prior = []
    out_path = Path(args.out)
    if not args.no_merge and out_path.exists():
        prev = load_json(out_path, {}) or {}
        prior = list(prev.get("items") or [])
        log(f"prior file: {len(prior)} items to re-check")
    items, excluded, kept = process(cands, prior, ctx)
    for sid, note in notes.items():
        status[sid] = f"ok n={kept.get(sid, 0)} ({note})"
    out = assemble(items, ctx, as_of, status, excluded)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    bad = served_text_violation(text)

    log(f"excluded: " + " · ".join(f"{k} {v}" for k, v in excluded.items()))
    log(f"items {out['counts']['items']} (tier1 {out['counts']['tier1']}, tier2 {out['counts']['tier2']}) · last24h {out['counts']['last24h']}")
    for tk, ids in out["per_name"].items():
        log(f"per_name {tk}: {len(ids)} items")
    t1 = [it for it in items if it["tier"] == 1][:3]
    for it in t1:
        log(f"tier1: {it['timestamp']} · {it['source']} · {it['headline']}")
    if bad:
        log(f"REFUSED: the assembled file would violate the language rule ({bad}); nothing written")
        return 2
    if args.dry_run:
        log("dry run: nothing written")
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, out_path)
    log(f"wrote {out_path} ({len(text)} bytes)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="two-tier news feed → data/news.json (order 30-Sept-2026, B4/E3)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and print, write nothing")
    ap.add_argument("--hours", type=int, default=DEFAULT_WINDOW_HOURS, help="panel window in hours (default 24)")
    ap.add_argument("--stored-days", type=int, default=DEFAULT_STORED_DAYS, help="days of items kept in the file (default 7)")
    ap.add_argument("--offline", default=None, metavar="FIXTURE_DIR", help="read feed files from a directory, no network")
    ap.add_argument("--out", default=str(DATA / "news.json"))
    ap.add_argument("--sources", default=str(DATA / "news_sources.json"))
    ap.add_argument("--holdings", default=str(DATA / "holdings.json"))
    ap.add_argument("--scores", default=str(DATA / "screen" / "scores.json"))
    ap.add_argument("--calendar", default=str(DATA / "event_calendar.json"))
    ap.add_argument("--now", default=None, help="ET ISO datetime override (tests)")
    ap.add_argument("--no-merge", action="store_true", help="do not carry items over from the existing output file")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except Exception:
        traceback.print_exc()
        log("run failed before writing; the previous file (if any) stands")
        return 1


if __name__ == "__main__":
    sys.exit(main())
