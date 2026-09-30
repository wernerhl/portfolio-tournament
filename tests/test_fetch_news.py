#!/usr/bin/env python3
"""
tests/test_fetch_news.py — the two-tier news feed (order 30-Sept-2026, items B4 and E3).

Run with the venv interpreter, either way (no pytest dependency):
    .venv/bin/python tests/test_fetch_news.py
    .venv/bin/python -m pytest tests/test_fetch_news.py

Every run of the fetcher here is OFFLINE (--offline tests/fixtures/news) and writes to a temporary
directory. Nothing under data/ of the repository is written — the final test asserts it. The
vocabulary / directive cases build the offending headlines at run time in a temporary copy of the
fixtures, so no fixture on disk carries the referee's prohibited words.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
FIX = REPO / "tests" / "fixtures" / "news"
DATA = REPO / "data"
PY = sys.executable
NOW = "2026-09-30T09:00"            # Wednesday, ET, before the close → as_of is Tuesday 2026-09-29
SENTINEL = "SENTINEL-DESCRIPTION-TEXT-DO-NOT-STORE"
WORD_A = "Al" + "pha"                # the referee's two prohibited words, never spelled out in this file
WORD_B = "ed" + "ge"

sys.path.insert(0, str(SCRIPTS))
import fetch_news as fn  # noqa: E402
from trading_calendar import is_trading_day, last_completed_session  # noqa: E402


# ─── guard: the repository's served files must be untouched by this run ──────────────────
def _digest(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


_GUARD = {"news": _digest(DATA / "news.json"), "sources": _digest(DATA / "news_sources.json"),
          "holdings": _digest(DATA / "holdings.json"), "tmp": sorted(x.name for x in DATA.glob("news*.tmp"))}


# ─── helpers ─────────────────────────────────────────────────────────────────────────────
def run_fetch(out: Path, fixture_dir: Path = FIX, *extra: str, now: str = NOW, merge: bool = False) -> tuple[subprocess.CompletedProcess, dict | None]:
    args = [PY, str(SCRIPTS / "fetch_news.py"), "--offline", str(fixture_dir),
            "--sources", str(fixture_dir / "sources_test.json"), "--holdings", str(fixture_dir / "holdings_test.json"),
            "--scores", str(fixture_dir / "scores_test.json"), "--calendar", str(fixture_dir / "calendar_test.json"),
            "--now", now, "--out", str(out), *extra]
    if not merge:
        args.append("--no-merge")
    cp = subprocess.run(args, capture_output=True, text=True, cwd=str(REPO))
    obj = json.loads(out.read_text()) if out.exists() else None
    return cp, obj


def fetch(*extra: str, now: str = NOW) -> tuple[dict, subprocess.CompletedProcess]:
    with tempfile.TemporaryDirectory() as td:
        cp, obj = run_fetch(Path(td) / "news.json", FIX, *extra, now=now)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert obj is not None, cp.stdout + cp.stderr
        return obj, cp


def by_id(obj: dict) -> dict:
    return {it["id"]: it for it in obj["items"]}


def find(obj: dict, needle: str) -> dict | None:
    return next((it for it in obj["items"] if needle in it["headline"]), None)


def ts(item: dict) -> datetime:
    return datetime.fromisoformat(item["timestamp"])


def rss_item(title: str, link: str, pub: str, desc: str = SENTINEL) -> str:
    return (f"<item><title>{title}</title><link>{link}</link><description>{desc}</description>"
            f"<pubDate>{pub}</pubDate></item>")


def fixture_copy_with(tmp: Path, fed_extra: str = "", yahoo_extra: list | None = None) -> Path:
    """A temporary copy of the fixtures with extra Fed items and / or extra Yahoo NVDA records."""
    d = tmp / "fixtures"
    shutil.copytree(FIX, d)
    if fed_extra:
        p = d / "fed_press.xml"
        p.write_text(p.read_text().replace("</channel>", fed_extra + "</channel>"))
    if yahoo_extra:
        p = d / "yahoo_NVDA.json"
        recs = json.loads(p.read_text())
        recs.extend(yahoo_extra)
        p.write_text(json.dumps(recs))
    return d


def yahoo_rec(title: str, url: str, pub: str = "2026-09-30T02:00:00Z", provider: str = "Example Wire") -> dict:
    return {"id": url, "content": {"id": url, "contentType": "STORY", "title": title, "description": SENTINEL,
                                   "summary": SENTINEL, "pubDate": pub, "provider": {"displayName": provider},
                                   "canonicalUrl": {"url": url}}}


# ─── unit level ──────────────────────────────────────────────────────────────────────────
def test_timestamp_parsing():
    et = ZoneInfo("America/New_York")
    p = fn.parse_timestamp
    assert p("Tue, 29 Sep 2026 18:00:00 GMT") == datetime(2026, 9, 29, 14, 0, tzinfo=et)
    assert p("Thu, 24 Sep 2026 08:30:00 EDT").isoformat() == "2026-09-24T08:30:00-04:00"          # zone name
    assert p("Tue, 29 Sep 26 12:00:00 +0000").isoformat() == "2026-09-29T08:00:00-04:00"           # 2-digit year (DOL)
    assert p("Tue, 29 Sep 2026 13:35:53\n +0000").isoformat() == "2026-09-29T09:35:53-04:00"       # line break (GE Vernova)
    assert p("Mon, 22 Apr 2024 12:35 GMT").isoformat() == "2024-04-22T08:35:00-04:00"              # no seconds (GlobeNewswire)
    assert p("2026-09-29T21:44:33Z").isoformat() == "2026-09-29T17:44:33-04:00"                    # ISO Z (Yahoo, EDGAR)
    assert p("2026-09-29T16:05:12.000Z").isoformat() == "2026-09-29T12:05:12-04:00"
    assert p("2026-09-29T15:00:00-04:00").isoformat() == "2026-09-29T15:00:00-04:00"
    epoch = int(datetime(2026, 9, 29, 20, 0, tzinfo=et).timestamp())
    assert p(epoch).isoformat() == "2026-09-29T20:00:00-04:00"                                      # epoch (old yfinance schema)
    for bad in ("", None, "not a date", "yesterday"):
        assert p(bad) is None, bad
    assert fn.iso_et(p("2026-09-29T21:44:33Z")) == "2026-09-29T17:44:33-04:00"
    assert fn.reference_period(datetime(2026, 10, 14).date(), 1) == "September 2026"
    assert fn.reference_period(datetime(2026, 1, 7).date(), 2) == "November 2025"


def test_name_phrases_and_mentions():
    nps = fn.name_phrases
    assert nps("Broadcom Inc.") == ["Broadcom"]
    assert nps("NVIDIA Corporation") == ["NVIDIA"]
    assert nps("Amazon.com, Inc.") == ["Amazon.com", "Amazon"]
    assert nps("Cincinnati Financial Corporati") == ["Cincinnati Financial"]        # truncated suffix dropped
    assert nps("Charles Schwab Corporation (Th") == ["Charles Schwab"]
    assert nps("Taiwan Semiconductor Manufactu") == ["Taiwan Semiconductor Manufactu"]  # prefix match at use
    assert nps("T. Rowe Price Group, Inc.") == ["T. Rowe Price Group"]
    assert nps("Corpay, Inc.") == ["Corpay"] and nps("RTX Corporation") == []       # too short: symbol only
    names = {"NVDA": ["NVIDIA", "Nvidia"], "MU": ["Micron"], "TSM": ["Taiwan Semiconductor Manufactu"],
             "MS": ["Morgan Stanley"], "LMT": ["Lockheed Martin"], "GOOG": ["Alphabet", "Google"]}
    m = fn.mention_tickers
    assert m("Nvidia's answer to rogue AI changes the conversation", names) == ["NVDA"]
    assert m("SPCX, TGT, AAPL, MU, NVDA move", names) == ["NVDA", "MU"] or m("SPCX, TGT, AAPL, MU, NVDA move", names) == ["MU", "NVDA"]
    assert m("Taiwan Semiconductor Manufacturing expands capacity", names) == ["TSM"]
    assert m("Jensen Huang: AI data center push will create 1 million US jobs", names) == []
    assert m("MS Dhoni retires", names) == [] and m("Morgan Stanley (MS) reports", names) == ["MS"]   # English-word symbol needs context
    assert m("Alphabet's Google unveils a model", names) == ["GOOG"]
    assert m("mu is a Greek letter", names) == []                                     # symbol match is case-sensitive
    assert fn.disclosure_label("Senator's periodic transaction report shows NVDA stock purchase") == fn.DISCLOSURE_LAG_LABEL
    assert fn.disclosure_label("Congress debates chip subsidies") is None             # vocabulary without a trade word
    assert fn.disclosure_label("Insider sold shares") is None                         # trade word without the vocabulary
    assert fn.match_topics("Federal Reserve issues FOMC statement", fn.DEFAULT_TOPIC_KEYWORDS) == ["FOMC"]
    assert fn.match_topics("Personal Income and Outlays, August 2026", fn.DEFAULT_TOPIC_KEYWORDS) == ["PCE"]
    assert fn.match_topics("Advance Monthly Sales for Retail and Food Services", fn.DEFAULT_TOPIC_KEYWORDS) == ["RETAIL"]
    assert fn.match_topics("New Home Sales", fn.DEFAULT_TOPIC_KEYWORDS) == []
    assert fn.match_topics("The cpi of the ppi", fn.DEFAULT_TOPIC_KEYWORDS) == []      # acronyms match in capitals only


# ─── the relevance filter ────────────────────────────────────────────────────────────────
def test_relevance_filter():
    obj, cp = fetch()
    heads = [it["headline"] for it in obj["items"]]
    # held / top-40 names and macro topics are kept
    assert find(obj, "Federal Reserve issues FOMC statement")["topics"] == ["FOMC"]
    assert find(obj, "Example Bancorp")["topics"] == []                       # a Fed item without a topic is still kept
    assert find(obj, "Personal Income and Outlays")["topics"] == ["PCE"]
    assert find(obj, "Retail and Food Services")["topics"] == ["RETAIL"]
    assert find(obj, "Unemployment Insurance Weekly Claims")["topics"] == ["CLAIMS"]
    assert find(obj, "NRC issues first U.S. construction permit")["tickers"] == ["GEV"]
    assert find(obj, "Arista Networks Announces Availability")["tickers"] == ["ANET"]  # Atom source
    lmt = find(obj, "Lockheed Martin wins award")
    assert lmt is not None and lmt["tickers"] == ["LMT", "TSM"]                # top-40 names in a Tier 2 headline
    # ... and the rest is dropped and counted
    for gone in ("International Transactions and Investment Position", "New Home Sales", "Mexico Announce",
                 "Jensen Huang", "Three chip names to watch"):
        assert not any(gone in h for h in heads), gone
    assert obj["excluded"]["irrelevant"] == 5, obj["excluded"]
    assert obj["universe"]["held"] == ["MU", "GEV", "NVDA", "ANET", "AVGO"]   # GOOG has 0 shares → not held
    assert "GOOG" in obj["universe"]["top40"] and "LMT" in obj["universe"]["top40"]
    assert obj["sources_status"]["ir_goog"].startswith("skipped: no feed found")
    assert obj["sources_status"]["ir_avgo"] == "skipped: no offline fixture"
    assert obj["sources_status"]["fed_press"].startswith("ok n=3")
    assert obj["sources_status"]["yahoo_headlines:NVDA"].startswith("ok n=4")
    assert "[fetch_news]" in cp.stdout


# ─── language rules ──────────────────────────────────────────────────────────────────────
def test_vocabulary_rule_exclusion():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        extra = (rss_item(f"Fed speech on the {WORD_A} of monetary policy", "https://www.federalreserve.gov/x/a1.htm", "Tue, 29 Sep 2026 19:00:00 GMT")
                 + rss_item(f"Cutting-{WORD_B} payment systems remarks", "https://www.federalreserve.gov/x/a2.htm", "Tue, 29 Sep 2026 19:10:00 GMT")
                 + rss_item("A clean title whose link carries the word", f"https://www.federalreserve.gov/x/{WORD_B}-computing.htm", "Tue, 29 Sep 2026 19:20:00 GMT")
                 + rss_item(f"{WORD_A}bet is fine: the word is longer", "https://www.federalreserve.gov/x/a4.htm", "Tue, 29 Sep 2026 19:30:00 GMT"))
        yextra = [yahoo_rec(f"Nvidia results seen by Seeking {WORD_A}", "https://example.com/y1"),
                  yahoo_rec("Nvidia headline from a provider with the word in its name", "https://example.com/y2", provider="Seeking " + WORD_A)]
        d = fixture_copy_with(tmp, extra, yextra)
        cp, obj = run_fetch(tmp / "news.json", d)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert obj["excluded"]["vocabulary_rule"] == 5, obj["excluded"]         # 3 Fed + 2 Yahoo
        text = (tmp / "news.json").read_text().lower()
        assert not re.search(r"\b(" + WORD_A.lower() + "|" + WORD_B.lower() + r")\b", text)
        assert find(obj, "is fine: the word is longer") is not None             # a longer word is not the word
        assert find(obj, "clean title whose link") is None                     # the URL counts too
        assert "Seeking" not in json.dumps(obj["items"])


def test_directive_rule_exclusion():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        extra = (rss_item("Buy now: a reading of the statement", "https://www.federalreserve.gov/x/d1.htm", "Tue, 29 Sep 2026 19:00:00 GMT")
                 + rss_item("Board to sell now its holdings of agency debt", "https://www.federalreserve.gov/x/d2.htm", "Tue, 29 Sep 2026 19:05:00 GMT")
                 + rss_item("Federal Reserve Board announces it will sell a building", "https://www.federalreserve.gov/x/d3.htm", "Tue, 29 Sep 2026 19:06:00 GMT"))
        yextra = [yahoo_rec("Is it time to buy the dip on Nvidia?", "https://example.com/d4"),
                  yahoo_rec("Nvidia: 3 stocks to buy before earnings", "https://example.com/d5"),
                  yahoo_rec('Nvidia {"action":"buy"} test record', "https://example.com/d6"),
                  yahoo_rec("Nvidia gets a strong buy from a broker", "https://example.com/d7"),
                  yahoo_rec("NVIDIA announces share repurchase, will buy back stock", "https://example.com/d8")]
        d = fixture_copy_with(tmp, extra, yextra)
        cp, obj = run_fetch(tmp / "news.json", d)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert obj["excluded"]["directive_rule"] == 6, obj["excluded"]
        assert find(obj, "will sell a building") is not None                    # the verb alone is not a directive
        assert find(obj, "will buy back stock") is not None
        blob = (tmp / "news.json").read_text().lower()
        for tok in ('"action":"buy"', '"action":"sell"', '"recommendation":"buy"', '"recommendation":"sell"', "buy now", "sell now"):
            assert tok not in blob, tok                                          # the referee's own token list


def test_no_feed_text_copied():
    obj, _ = fetch()
    text = json.dumps(obj)
    assert SENTINEL not in text
    assert "monetary policy statement text" not in text and "retail sales text" not in text
    for it in obj["items"]:
        s = it["summary"]
        assert s and "\n" not in s and len(s) <= 200, s
        assert len(it["headline"]) <= 200
        if it["tier"] == 2:
            assert s.startswith("Tier 2 headline · ") and " · about " in s and it["tier_label"] == "secondary"
        elif it["source_id"] == "edgar":
            assert s.startswith("EDGAR ") and " · filed " in s
        elif it["source_id"] == "bls_release_day":
            assert re.fullmatch(r"scheduled release at \d\d:\d\d ET; print not fetched", s), s
        else:
            assert s.startswith("Tier 1 · "), s
    assert obj["rule"].startswith("primary sources first")


# ─── ordering, window, dedupe, dates ─────────────────────────────────────────────────────
def test_tier_ordering():
    obj, _ = fetch()
    items = obj["items"]
    stamps = [it["timestamp"] for it in items]
    assert stamps == sorted(stamps, reverse=True)                                # newest first overall
    idx = by_id(obj)
    tiers = [idx[i]["tier"] for i in obj["last24h"]]
    assert tiers and tiers == sorted(tiers)                                      # all Tier 1 before any Tier 2
    assert 1 in tiers and 2 in tiers
    for t in (1, 2):
        sub = [idx[i]["timestamp"] for i in obj["last24h"] if idx[i]["tier"] == t]
        assert sub == sorted(sub, reverse=True), t                               # newest first within a tier
    for it in items:
        assert it["tier_label"] == ("primary" if it["tier"] == 1 else "secondary")
        assert set(it) == {"id", "tier", "tier_label", "headline", "source", "source_id", "url", "timestamp",
                           "tickers", "topics", "summary", "disclosure_lag_label"}


def test_disclosure_lag_label_e3():
    obj, _ = fetch()
    it = find(obj, "periodic transaction report")
    assert it is not None and it["tier"] == 2 and it["disclosure_lag_label"] == fn.DISCLOSURE_LAG_LABEL
    assert it["tickers"] == ["NVDA"] and it["topics"] == []
    others = [x for x in obj["items"] if x["id"] != it["id"]]
    assert all(x["disclosure_lag_label"] is None for x in others)
    text = json.dumps(obj, ensure_ascii=False)
    assert text.count(fn.DISCLOSURE_LAG_LABEL) == 1                              # the label lives in that one field only
    assert "signal" not in it["headline"] and "signal" not in it["summary"]
    # the item is news in the Tier 2 list and nowhere else: no score, no signal field, no panel key
    assert not any(k in obj for k in ("signals", "scores", "congress", "trades"))


def test_24h_window_and_stored_depth():
    obj, _ = fetch()
    assert obj["window_hours"] == 24 and obj["stored_days"] == 7
    now = datetime.fromisoformat(obj["fetched_at"])
    assert obj["fetched_at"] == "2026-09-30T09:00:00-04:00"
    idx = by_id(obj)
    for i in obj["last24h"]:
        assert ts(idx[i]) >= now - timedelta(hours=24)
    for it in obj["items"]:
        assert ts(it) >= now - timedelta(days=7)
        assert (it["id"] in obj["last24h"]) == (ts(it) >= now - timedelta(hours=24))
    old = find(obj, "$150 Billion Share Repurchase")                            # 2 days old: stored, not in the window
    assert old is not None and old["id"] not in obj["last24h"]
    assert find(obj, "annual bank stress test") is None                          # 20 days old: not stored
    assert find(obj, "Old NVIDIA headline") is None
    assert obj["excluded"]["out_of_window"] == 5, obj["excluded"]
    edge_case = find(obj, "Open Agent Safety Platform")                          # exactly 24h ago: inside
    assert edge_case["timestamp"] == "2026-09-29T09:00:00-04:00" and edge_case["id"] in obj["last24h"]
    obj72, _ = fetch("--hours", "72")
    assert obj72["window_hours"] == 72 and find(obj72, "$150 Billion Share Repurchase")["id"] in obj72["last24h"]
    assert len(obj72["last24h"]) > len(obj["last24h"])


def test_dedupe_by_url():
    obj, _ = fetch()
    ids = [it["id"] for it in obj["items"]]
    assert len(ids) == len(set(ids))
    urls = [it["url"] for it in obj["items"]]
    assert len(urls) == len(set(urls))
    for it in obj["items"]:
        assert it["id"] == hashlib.sha1(it["url"].encode()).hexdigest()
    dup = [it for it in obj["items"] if it["url"] == "https://nvidianews.nvidia.com/news/open-agent-safety-platform"]
    assert len(dup) == 1 and "duplicate entry" not in dup[0]["headline"]         # first entry wins
    shared = find(obj, "memory supply agreement")                                # same URL in the MU and NVDA feeds
    assert shared is not None and sorted(shared["tickers"]) == ["MU", "NVDA"]
    assert shared["id"] in obj["per_name"]["MU"] and shared["id"] in obj["per_name"]["NVDA"]
    assert shared["summary"].endswith("about MU, NVDA")
    tracked = find(obj, "Dow Extend Losses")
    assert "utm_" not in tracked["url"] and tracked["url"].endswith("/abc123")   # tracking parameters stripped


def test_as_of_is_trading_session():
    obj, _ = fetch()
    assert obj["cadence"] == "intraday"
    assert obj["as_of"] == "2026-09-29" and is_trading_day(obj["as_of"])
    assert obj["as_of"] == last_completed_session(datetime.fromisoformat(obj["fetched_at"]))
    sat, _ = fetch(now="2026-10-03T10:00")                                       # Saturday → Friday's session
    assert sat["as_of"] == "2026-10-02" and is_trading_day(sat["as_of"])
    hol, _ = fetch(now="2026-09-07T12:00")                                       # Labor Day → the Friday before
    assert hol["as_of"] == "2026-09-04"
    late, _ = fetch(now="2026-09-30T16:30")                                      # after the close: today's session
    assert late["as_of"] == "2026-09-30"


# ─── BLS release-day items, EDGAR ────────────────────────────────────────────────────────
def test_bls_release_day_items():
    obj, _ = fetch()
    cpi = find(obj, "BLS release: Consumer Price Index")
    assert cpi is not None and cpi["tier"] == 1 and cpi["source"] == "BLS (release page)"
    assert cpi["headline"] == "BLS release: Consumer Price Index (August 2026)"
    assert cpi["url"] == "https://www.bls.gov/news.release/cpi.nr0.htm#2026-09-30"
    assert cpi["summary"] == "scheduled release at 08:30 ET; print not fetched"
    assert cpi["timestamp"] == "2026-09-30T08:30:00-04:00" and cpi["topics"] == ["CPI"] and cpi["tickers"] == []
    jolts = find(obj, "BLS release: Job Openings")
    assert jolts is not None and jolts["headline"].endswith("(July 2026)") and jolts["timestamp"] == "2026-09-29T10:00:00-04:00"
    assert find(obj, "BLS release: Employment Situation") is None               # 2026-10-02 has not happened
    ppi = find(obj, "BLS release: Producer Price Index")                         # the calendar's own time_et wins
    assert ppi["timestamp"] == "2026-09-28T08:45:00-04:00" and ppi["summary"] == "scheduled release at 08:45 ET; print not fetched"
    assert ppi["headline"] == "BLS release: Producer Price Index (August 2026)" and ppi["url"].endswith("ppi.nr0.htm#2026-09-28")
    assert len([it for it in obj["items"] if it["source_id"] == "bls_release_day"]) == 3   # the 09-11 CPI is outside 7 days
    assert obj["sources_status"]["bls_release_day"] == "ok n=3 (constructed 3)"
    assert obj["sources_status"]["bea_release_day"] == "skipped: primary feed ok"
    early, _ = fetch(now="2026-09-30T08:00")                                     # before 08:30: not yet released
    assert find(early, "BLS release: Consumer Price Index") is None
    # BEA fallback: only when the BEA feed fails
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        d = fixture_copy_with(tmp)
        (d / "bea.xml").write_text("this is not xml at all")
        cal = json.loads((d / "calendar_test.json").read_text())
        cal["events"].append({"date": "2026-09-29", "type": "GDP", "name": "GDP", "label": "GDP"})
        (d / "calendar_test.json").write_text(json.dumps(cal))
        cp, o = run_fetch(tmp / "news.json", d)
        assert cp.returncode == 0, cp.stdout + cp.stderr                          # one source failing never fails the run
        assert o["sources_status"]["bea"].startswith("failed: ParseError")
        gdp = find(o, "BEA release: Gross Domestic Product")
        assert gdp is not None and gdp["url"] == "https://www.bea.gov/data/gdp/gross-domestic-product#2026-09-29"
        assert o["sources_status"]["bea_release_day"] == "ok n=1 (constructed 1)"


def test_edgar_offline_and_gate():
    obj, _ = fetch()
    ed = [it for it in obj["items"] if it["source_id"] == "edgar"]
    assert [(it["headline"], it["tickers"]) for it in ed] == [
        ("8-K filed by NVIDIA CORP", ["NVDA"]), ("8-K filed by MICRON TECHNOLOGY INC", ["MU"]),
        ("Form 4 filed by NVIDIA CORP", ["NVDA"]), ("8-K/A filed by NVIDIA CORP", ["NVDA"]), ("Form 4/A filed by NVIDIA CORP", ["NVDA"])]
    k8 = ed[0]
    assert k8["url"] == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000201/nvda-20260929.htm"
    assert k8["summary"] == "EDGAR 8-K · filed 2026-09-29 · 8-K" and k8["timestamp"] == "2026-09-29T12:05:12-04:00"
    assert ed[2]["summary"] == "EDGAR 4 · filed 2026-09-28 · FORM 4"
    assert ed[1]["timestamp"] == "2026-09-29T12:00:00-04:00"                     # no acceptance time → noon ET of the filing date
    assert not any("SC 13G" in it["headline"] for it in obj["items"])            # form outside the list
    assert not any("10-Q" in it["headline"] for it in obj["items"])              # 2026-08-27: outside the stored window
    assert obj["sources_status"]["edgar"].startswith("ok n=5 (parsed 2 names")
    # the online gate: no SEC_USER_AGENT → skipped before any request, never hardcoded
    saved = os.environ.pop("SEC_USER_AGENT", None)
    try:
        ctx = fn.Context(datetime.fromisoformat(NOW).replace(tzinfo=ZoneInfo("America/New_York")), 24, 7, ["NVDA"], [], {"NVDA": []},
                         fn.DEFAULT_TOPIC_KEYWORDS, [], None)
        got, status = fn.fetch_edgar({"id": "edgar", "url": "https://data.sec.gov/submissions/CIK{cik:010d}.json"}, ctx)
        assert got == [] and status == "skipped: SEC_USER_AGENT not set"
        os.environ["SEC_USER_AGENT"] = "   "
        got, status = fn.fetch_edgar({"id": "edgar", "url": "https://data.sec.gov/submissions/CIK{cik:010d}.json"}, ctx)
        assert status == "skipped: SEC_USER_AGENT not set"
    finally:
        os.environ.pop("SEC_USER_AGENT", None)
        if saved is not None:
            os.environ["SEC_USER_AGENT"] = saved
    src = Path(SCRIPTS / "fetch_news.py").read_text()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", src)                          # no e-mail address anywhere in the module


def test_per_name_last_five():
    obj, _ = fetch()
    assert list(obj["per_name"]) == obj["universe"]["held"]
    idx = by_id(obj)
    for tk, ids in obj["per_name"].items():
        assert len(ids) <= 5
        assert all(tk in idx[i]["tickers"] for i in ids)
        assert [idx[i]["timestamp"] for i in ids] == sorted((idx[i]["timestamp"] for i in ids), reverse=True)
        expect = [it["id"] for it in obj["items"] if tk in it["tickers"]][:5]
        assert ids == expect, tk
    assert len(obj["per_name"]["NVDA"]) == 5 and len(obj["per_name"]["AVGO"]) == 0
    assert sum(1 for it in obj["items"] if "NVDA" in it["tickers"]) > 5           # depth beyond five is stored
    assert obj["counts"] == {"items": len(obj["items"]), "tier1": sum(it["tier"] == 1 for it in obj["items"]),
                             "tier2": sum(it["tier"] == 2 for it in obj["items"]), "last24h": len(obj["last24h"])}


def test_prior_merge_keeps_depth():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out = tmp / "news.json"
        cp, first = run_fetch(out, FIX, merge=True)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        d = fixture_copy_with(tmp)
        (d / "ir_nvda.xml").unlink()                                             # the feed goes away for a run
        cp, second = run_fetch(out, d, merge=True)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert second["sources_status"]["ir_nvda"] == "skipped: no offline fixture"
        assert {it["id"] for it in first["items"]} == {it["id"] for it in second["items"]}   # prior items carried over
        assert find(second, "$150 Billion Share Repurchase") is not None
        cp, later = run_fetch(out, d, now="2026-10-05T09:00", merge=True)        # 5 days on: the oldest fall out
        assert cp.returncode == 0
        assert all(ts(it) >= datetime.fromisoformat("2026-09-28T09:00:00-04:00") for it in later["items"])
        assert find(later, "$150 Billion Share Repurchase") is None
        cp, nomerge = run_fetch(out, d, merge=False)
        assert find(nomerge, "$150 Billion Share Repurchase") is None            # --no-merge ignores the prior file


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "news.json"
        cp, obj = run_fetch(out, FIX, "--dry-run")
        assert cp.returncode == 0 and obj is None and not out.exists(), cp.stdout + cp.stderr
        assert "dry run: nothing written" in cp.stdout and "tier1:" in cp.stdout
        assert "items 28 (tier1 22, tier2 6)" in cp.stdout, cp.stdout


# ─── the frozen registry ─────────────────────────────────────────────────────────────────
def test_real_registry_schema_and_language():
    p = DATA / "news_sources.json"
    raw = p.read_text()
    cfg = json.loads(raw)
    assert cfg["cadence"] == "static" and cfg["as_of"] == "2026-09-30" and cfg["rule"] == fn.RULE
    low = raw.lower()
    assert not re.search(r"\b(" + WORD_A.lower() + "|" + WORD_B.lower() + r")\b", low)
    for tok in ('"action":"buy"', '"action":"sell"', "buy now", "sell now"):
        assert tok not in low
    ids = [s["id"] for s in cfg["sources"]]
    assert len(ids) == len(set(ids))
    kinds = {"rss", "atom", "edgar_submissions", "yahoo_ticker", "bls_release_day", "bea_release_day"}
    for s in cfg["sources"]:
        for k in ("id", "tier", "kind", "url", "label", "provenance", "status"):
            assert k in s, (s["id"], k)
        assert s["tier"] in (1, 2) and s["kind"] in kinds
        if s["kind"] in ("rss", "atom") and s["status"] == "ok":
            assert str(s["url"]).startswith("https://")
        if s["id"].startswith("ir_"):
            assert s["ticker"] and s["tier"] == 1
    by = {s["id"]: s for s in cfg["sources"]}
    assert by["fed_press"]["url"] == "https://www.federalreserve.gov/feeds/press_all.xml" and by["fed_press"]["keep_without_topic"] is True
    assert by["fed_speeches"]["url"] == "https://www.federalreserve.gov/feeds/speeches.xml"
    assert by["bea"]["url"] == "https://apps.bea.gov/rss/rss.xml"
    assert by["census"]["url"] == "https://www.census.gov/economic-indicators/indicator.xml"
    assert by["dol"]["url"] == "https://www.dol.gov/rss/releases.xml"
    assert by["ir_avgo"]["url"] == "https://investors.broadcom.com/rss/news-releases.xml"
    assert by["ir_nvda"]["url"] == "https://nvidianews.nvidia.com/cats/press_release.xml"
    assert by["ir_gev"]["url"] == "https://www.gevernova.com/news/subscribe/all/rss.xml"
    assert by["ir_goog"]["status"].startswith("no feed found") and by["ir_bmnr"]["status"].startswith("no feed found")
    assert by["edgar"]["user_agent_env"] == "SEC_USER_AGENT" and set(by["edgar"]["forms"]) == set(fn.EDGAR_FORMS)
    assert "@" not in raw                                                        # no contact address in a served file
    assert by["yahoo_headlines"]["tier"] == 2
    assert set(by["bls_release_day"]["release_pages"]) == {"CPI", "NFP", "PPI", "JOLTS"}
    assert cfg["topic_keywords"] == fn.DEFAULT_TOPIC_KEYWORDS
    assert cfg["disclosure_lag_label"] == fn.DISCLOSURE_LAG_LABEL


# ─── guard ───────────────────────────────────────────────────────────────────────────────
def test_zz_repository_data_untouched():
    assert _digest(DATA / "news.json") == _GUARD["news"]
    assert _digest(DATA / "news_sources.json") == _GUARD["sources"]
    assert _digest(DATA / "holdings.json") == _GUARD["holdings"]
    assert sorted(x.name for x in DATA.glob("news*.tmp")) == _GUARD["tmp"] == []


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fnc in tests:
        try:
            fnc()
            print(f"PASS {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
