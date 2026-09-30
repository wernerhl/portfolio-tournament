#!/usr/bin/env python3
"""
tests/test_ownership.py — ownership module (order 30-Sept-2026, E1 insider purchases and E2 13F
context): Form 4 parsing, the Cohen–Malloy–Pomorski classification, the cluster flag, the sales
rule, the 13F top-10 / change / new / exit / $1B screen with as-of and disclosure dates on every
figure, and the SEC access contract (no SEC_USER_AGENT → exit 3, nothing written, no network).

Run with the venv interpreter, either way (no pytest dependency):
    .venv/bin/python tests/test_ownership.py
    .venv/bin/python -m pytest tests/test_ownership.py

Every test reads the SYNTHETIC fixtures under tests/fixtures/ownership/ and writes only into
temporary directories. Nothing under data/ or scratch/ of the repository is written — the final
test asserts it. No test opens a network connection: the one network function is replaced.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
OWNS = SCRIPTS / "ownership"
FIX = REPO / "tests" / "fixtures" / "ownership"
DATA = REPO / "data"
PY = sys.executable

sys.path.insert(0, str(OWNS))
sys.path.insert(0, str(SCRIPTS))
import edgar_common as ec  # noqa: E402
import insiders as ins  # noqa: E402
import holders_13f as h13  # noqa: E402

AS_OF = "2026-09-30"
NOW = "2026-09-30T18:00"          # NOW_ET_OVERRIDE for the subprocesses: session 2026-09-30 is complete at 18:00 ET
FAKE_UA = "TEST-UA-NO-NETWORK"    # in-process only, with the network function replaced; never a real contact


# ─── guard: the repository's served files must be untouched by this run ────────────────
def _digest(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _listing(p: Path) -> list | None:
    return sorted(x.name for x in p.iterdir()) if p.exists() else None


_GUARD = {"data": _listing(DATA), "own": _listing(DATA / "ownership"),
          "own_files": {n: _digest(DATA / "ownership" / n) for n in (_listing(DATA / "ownership") or [])},
          "scratch": _listing(REPO / "scratch"), "holdings": _digest(DATA / "holdings.json")}


# ─── helpers ─────────────────────────────────────────────────────────────────────────────
def env_without_ua(**extra) -> dict:
    env = dict(os.environ)
    env.pop("SEC_USER_AGENT", None)
    env["NOW_ET_OVERRIDE"] = NOW
    env.update(extra)
    return env


def run_cli(script: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(OWNS / script), *args], capture_output=True, text=True, env=env_without_ua(), cwd=str(cwd or REPO))


class _NoNetwork(AssertionError):
    pass


def _raise_on_network(url, ua, timeout=None):
    raise _NoNetwork("network call attempted: " + url)


class _Ns:
    def __init__(self, **kw):
        self.offline = None
        self.cache_dir = None
        self.dry_run = False
        self.as_of = AS_OF
        self.data_dir = None
        self.history_store = None
        self.max_age_days = 0
        self.__dict__.update(kw)


def offline_insiders(tmp: Path) -> dict:
    cp = run_cli("insiders.py", "--offline", str(FIX), "--data-dir", str(tmp), "--as-of", AS_OF)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    return json.load(open(tmp / "ownership" / "insiders.json"))


def offline_13f(tmp: Path) -> dict:
    cp = run_cli("holders_13f.py", "--offline", str(FIX), "--data-dir", str(tmp), "--as-of", AS_OF)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    return json.load(open(tmp / "ownership" / "holders_13f.json"))


# ─── SEC access contract ──────────────────────────────────────────────────────────────────
def test_no_user_agent_raises_before_any_network_use():
    saved = os.environ.pop("SEC_USER_AGENT", None)
    real_get = ec.http_get
    ec.http_get = _raise_on_network
    try:
        try:
            ec.user_agent()
            assert False, "user_agent() must raise when SEC_USER_AGENT is unset"
        except RuntimeError as e:
            assert str(e) == "SEC_USER_AGENT not set: the SEC requires a declared contact for automated access"
        try:
            ec.EdgarClient(cache_dir=tempfile.mkdtemp())
            assert False, "EdgarClient() must refuse without the declared contact"
        except RuntimeError as e:
            assert "SEC_USER_AGENT not set" in str(e)
        # a UA-less live run of either job returns 3 and never reaches the network function
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()) as out:
            rc, payload = ins.run(_Ns(data_dir=td, history_store=str(Path(td) / "store.parquet")))
            assert rc == 3 and payload is None
            rc, payload = h13.run(_Ns(data_dir=td))
            assert rc == 3 and payload is None
            assert list(Path(td).iterdir()) == []
        assert out.getvalue().count("SEC_USER_AGENT not set") == 2 and "would fetch" in out.getvalue()
    finally:
        ec.http_get = real_get
        if saved is not None:
            os.environ["SEC_USER_AGENT"] = saved


def test_cli_exits_3_and_writes_nothing_without_user_agent():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for script in ("insiders.py", "holders_13f.py"):
            cp = run_cli(script, "--data-dir", str(tmp), *(["--history-store", str(tmp / "s.parquet")] if script == "insiders.py" else []))
            assert cp.returncode == 3, (script, cp.returncode, cp.stdout + cp.stderr)
            assert "SEC_USER_AGENT not set: the SEC requires a declared contact for automated access" in cp.stdout
            assert "would fetch https://www.sec.gov/files/company_tickers.json" in cp.stdout
            assert "nothing written" in cp.stdout
            assert list(tmp.iterdir()) == [], list(tmp.iterdir())
        assert "insider-transactions-data-sets/2023q1_form345.zip" in run_cli("insiders.py", "--data-dir", str(tmp), "--history-store", str(tmp / "s.parquet"), "--as-of", AS_OF).stdout
        assert "form-13f-data-sets/01jun2026-31aug2026_form13f.zip" in run_cli("holders_13f.py", "--data-dir", str(tmp), "--as-of", AS_OF).stdout
        assert list(tmp.iterdir()) == []


def test_http_layer_retry_gzip_and_rate_limit():
    """The client retries once on 503/429 after 2 s, decodes gzip, caches, and spaces requests at
    no more than 8 per second — all against a replaced network function."""
    saved = os.environ.get("SEC_USER_AGENT")
    os.environ["SEC_USER_AGENT"] = FAKE_UA
    real_get = ec.http_get
    calls, sleeps = [], []
    body = json.dumps({"ok": 1}).encode()

    def fake_get(url, ua, timeout=None):
        calls.append((url, ua))
        if len(calls) == 1:
            return 503, {}, b""
        return 200, {"content-encoding": "gzip"}, gzip.compress(body)

    clock = {"t": 0.0}
    ec.http_get = fake_get
    try:
        with tempfile.TemporaryDirectory() as td:
            c = ec.EdgarClient(cache_dir=td, sleep=lambda s: (sleeps.append(s), clock.__setitem__("t", clock["t"] + s)), clock=lambda: clock["t"])
            assert c.get_json("https://data.sec.gov/x.json") == {"ok": 1}
            assert len(calls) == 2 and all(ua == FAKE_UA for _, ua in calls)      # one retry, the declared UA on both
            assert 2.0 in sleeps                                                  # the 2 s wait before the retry
            assert c.requests_made == 2
            assert c.get_json("https://data.sec.gov/x.json") == {"ok": 1} and len(calls) == 2 and c.cache_hits == 1   # cached
            # rate limit: three fresh URLs → at least 1/8 s between consecutive requests
            calls.clear(); sleeps.clear()
            for i in range(3):
                c.get("https://data.sec.gov/y%d.json" % i)
            gaps = [s for s in sleeps if s != 2.0]
            assert all(g >= 0.125 - 1e-9 for g in gaps) and len(gaps) >= 2, sleeps
            # 404 with allow_404 → None; without → EdgarHTTPError
            ec.http_get = lambda url, ua, timeout=None: (404, {}, b"")
            assert c.get("https://www.sec.gov/missing.zip", allow_404=True) is None
            try:
                c.get("https://www.sec.gov/missing2.zip")
                assert False
            except ec.EdgarHTTPError as e:
                assert e.status == 404
            # deflate decoding
            import zlib
            assert ec.decode_body({"content-encoding": "deflate"}, zlib.compress(b"abc")) == b"abc"
            assert ec.decode_body({}, b"raw") == b"raw"
    finally:
        ec.http_get = real_get
        if saved is None:
            os.environ.pop("SEC_USER_AGENT", None)
        else:
            os.environ["SEC_USER_AGENT"] = saved


# ─── primitives ───────────────────────────────────────────────────────────────────────────
def test_dates_numbers_quarters_and_windows():
    for s in ("2025-09-15", "15-SEP-2025", "20250915", "09/15/2025", "2025-09-15T00:00:00", " 15-sep-2025 "):
        assert ec.parse_sec_date(s) == "2025-09-15", s
    assert ec.parse_sec_date("") is None and ec.parse_sec_date("31-FEB-2025") is None and ec.parse_sec_date("n/a") is None
    assert ec.num("1,250.50") == 1250.5 and ec.num("") is None and ec.num("abc") is None
    assert ec.cik10("1045810") == "0001045810" and ec.cik10(1045810) == "0001045810" and ec.cik10("") == ""
    assert ec.quarters_between(date(2025, 11, 3), date(2026, 4, 1)) == [(2025, 4), (2026, 1), (2026, 2)]
    assert ec.quarter_end(2026, 2) == date(2026, 6, 30) and ec.quarter_end(2025, 4) == date(2025, 12, 31)
    assert ins.required_quarters(date(2026, 7, 2), date(2026, 9, 30)) == ["%dq%d" % (y, q) for y in (2023, 2024, 2025) for q in (1, 2, 3, 4)]
    assert ins.required_quarters(date(2026, 10, 17), date(2027, 1, 15))[-1] == "2026q4"
    c = ec.insider_dataset_candidates(2026, 2)
    assert c == ["https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2026q2_form345.zip",
                 "https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/2026q2_form345.zip"]
    assert ec.f13_window_for(date(2026, 6, 30))[2] == "01jun2026-31aug2026"
    assert ec.f13_window_for(date(2026, 3, 31))[2] == "01mar2026-31may2026"
    assert ec.f13_window_for(date(2025, 12, 31))[2] == "01dec2025-28feb2026"
    assert ec.f13_quarter_ends_available(date(2026, 9, 30), 2) == [date(2026, 6, 30), date(2026, 3, 31)]
    assert ec.f13_quarter_ends_available(date(2026, 8, 15), 1) == [date(2026, 3, 31)]        # the Jun window closes 31 Aug
    cands = ec.f13_dataset_candidates(date(2026, 6, 30))
    assert cands[0].endswith("/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip")
    assert any(u.endswith("/structureddata/data/form-13f-data-sets/2026q2_form13f.zip") for u in cands)
    assert ec.archive_folder_url("0001045810", "0001045810-26-000101") == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000101/"


def test_universe_from_holdings_and_top40_rows():
    holdings = {"holdings": [{"ticker": "mu", "shares": 50}, {"ticker": "NVDA", "shares": 100.15}, {"ticker": "OLD", "shares": 0}]}
    scores = {"watchlist": [{"ticker": "AVGO", "on_board_as": "top40"}, {"ticker": "MU", "on_board_as": "held"},
                            {"ticker": "LMT", "on_board_as": "top40"}, {"ticker": "AVGO", "on_board_as": "top40"}]}
    u = ec.universe_from(holdings, scores)
    assert u == {"held": ["MU", "NVDA"], "board": ["AVGO", "LMT"]}, u
    assert ec.universe_from(None, None) == {"held": [], "board": []}
    real = ec.universe()                                          # read-only look at the repository's files
    assert isinstance(real["held"], list) and len(real["board"]) <= 40
    if (DATA / "screen" / "scores.json").exists():
        rows = {r["ticker"]: r for r in json.load(open(DATA / "screen" / "scores.json")).get("watchlist", [])}
        assert all(rows[t]["on_board_as"] == "top40" for t in real["board"])


# ─── Form 4 parsing ───────────────────────────────────────────────────────────────────────
def test_form4_parsing_p_s_dollars_and_ignored_codes():
    d = ins.parse_form4((FIX / "form4" / "0001045810-26-000102.xml").read_bytes())
    assert d["issuer_cik"] == "0001045810" and d["symbol"] == "NVDA" and d["period_of_report"] == "2026-09-05"
    assert [o["name"] for o in d["owners"]] == ["Opportune Oscar"] and d["owners"][0]["role"] == "Chief Financial Officer"
    assert len(d["transactions"]) == 1                                    # the F row and the derivative M row are ignored
    t = d["transactions"][0]
    assert (t["code"], t["shares"], t["price"], t["acq_disp"], t["ownership"], t["date"]) == ("P", 1000.0, 120.5, "A", "D", "2026-09-05")
    assert d["ignored"] == {"F": 1, "derivative": 1}
    rows = ins.trades_from_form4(d, "0001045810-26-000102", "2026-09-08", "https://x/", "NVDA", "form4")
    assert len(rows) == 1 and rows[0]["dollars"] == 120500.0 and rows[0]["insider_cik"] == "0000002002" and rows[0]["ticker"] == "NVDA"
    # a filing with only non-open-market codes yields nothing
    d2 = ins.parse_form4((FIX / "form4" / "0001045810-26-000105.xml").read_bytes())
    assert d2["transactions"] == [] and d2["ignored"] == {"M": 1, "A": 1, "derivative": 1}
    # a sale: code S, disposed, dollars = shares × price
    d3 = ins.parse_form4((FIX / "form4" / "0001652044-26-000301.xml").read_bytes())
    r3 = ins.trades_from_form4(d3, "0001652044-26-000301", "2026-09-03", None, "GOOG", "form4")[0]
    assert (r3["code"], r3["acq_disp"], r3["dollars"], r3["security"]) == ("S", "D", 380000.0, "Class C Capital Stock")
    # joint filing: attributed to the first-listed owner, the co-owner recorded; roles
    d4 = ins.parse_form4((FIX / "form4" / "0000723125-26-000501.xml").read_bytes())
    r4 = ins.trades_from_form4(d4, "0000723125-26-000501", "2026-08-04", None, "MU", "form4")[0]
    assert r4["insider"] == "Micron Mike" and r4["co_owners"] == ["Mike Family Trust"] and r4["owner_ciks"] == ["0000006001", "0000006002"]
    assert r4["ownership"] == "I" and d4["owners"][1]["role"] == "Trust"
    assert ins.parse_form4((FIX / "form4" / "0001730168-26-000201.xml").read_bytes())["owners"][0]["role"] == "Chief Executive Officer, Director"
    assert ins.parse_form4((FIX / "form4" / "0001652044-26-000303.xml").read_bytes())["owners"][0]["role"] == "10% owner"
    assert ins.role_text(False, False, False, False) == "reporting owner"


def test_dataset_extraction_form_filter_and_date_format():
    ciks = {"0001045810", "0001652044"}
    rows = ins.extract_quarter(FIX / "datasets" / "2023q3_form345", "2023q3", ciks, {"0001045810": "NVDA", "0001652044": "GOOG"})
    got = sorted((r["ticker"], r["insider"], r["date"], r["code"]) for r in rows)
    # Tina's M row (not open-market), Ned's 4/A (amendment) and the noise issuer are excluded; DD-MON-YYYY parsed
    assert got == [("GOOG", "Routine Rob", "2023-09-20", "S"), ("NVDA", "Routine Rita", "2023-09-12", "P")], got
    r = next(x for x in rows if x["ticker"] == "NVDA")
    assert r["insider_cik"] == "0000002001" and r["role"] == "Director" and r["dollars"] == 4500.0 and r["source"] == "dataset:2023q3"
    assert r["filing_url"] == "https://www.sec.gov/Archives/edgar/data/1045810/000104581023000031/"
    assert ins.extract_quarter(FIX / "datasets" / "2023q1_form345", "2023q1", {"0000999999"}, {})[0]["insider"] == "Noise Nell"
    assert ins.extract_quarter(FIX / "datasets" / "2023q1_form345", "2023q1", {"0000000001"}, {}) == []


def test_history_store_roundtrip():
    rows = ins.extract_quarter(FIX / "datasets" / "2024q3_form345", "2024q3", {"0001045810"}, {"0001045810": "NVDA"})
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "insider_history.parquet"
        ins.save_store(p, rows, {"quarters": {"2024q3": {"rows": len(rows)}}, "universe_ciks": ["0001045810"]})
        back, meta = ins.load_store(p)
        assert meta["quarters"]["2024q3"]["rows"] == 3 and len(back) == 3
        a, b = sorted(rows, key=lambda r: r["accession"]), sorted(back, key=lambda r: r["accession"])
        for x, y in zip(a, b):
            for k in ("accession", "insider_cik", "insider", "date", "code", "shares", "price", "dollars", "owner_ciks", "co_owners", "ticker", "role"):
                assert x[k] == y[k], (k, x[k], y[k])


# ─── the rule ─────────────────────────────────────────────────────────────────────────────
def test_routine_vs_opportunistic_on_constructed_histories():
    def idx_for(months):
        return {("0000000001", "0000000009"): set(months)}
    trade = {"issuer_cik": "0000000001", "insider_cik": "0000000009", "date": "2026-09-05", "code": "P"}
    # traded every September for three years → routine
    lab, basis = ins.classify(trade, idx_for([(2023, 9), (2024, 9), (2025, 9)]))
    assert lab == "routine" and basis == "routine: traded in September of 2023, 2024, 2025 (same calendar month in each of the three prior years)"
    # three years of history, one September missed → opportunistic
    lab, basis = ins.classify(trade, idx_for([(2023, 3), (2024, 9), (2025, 9)]))
    assert lab == "opportunistic" and basis.startswith("opportunistic: no open-market trade in September of 2023")
    # only two prior years of history → opportunistic by the rule, and the basis says so
    lab, basis = ins.classify(trade, idx_for([(2024, 9), (2025, 9)]))
    assert lab == "opportunistic" and basis.startswith("opportunistic by the rule: 2 prior year(s) of trading history at the company (2024, 2025)")
    # no history at all → opportunistic by the rule
    lab, basis = ins.classify(trade, {})
    assert lab == "opportunistic" and "0 prior year(s)" in basis
    # trades in the same year (2026) and four years back do not count as prior-year history
    lab, basis = ins.classify(trade, idx_for([(2026, 9), (2022, 9), (2021, 9)]))
    assert lab == "opportunistic" and "0 prior year(s)" in basis
    # the fixture histories, end to end through the index builder
    hist = []
    for q in ("2023q1", "2023q3", "2024q3", "2025q3"):
        hist += ins.extract_quarter(FIX / "datasets" / ("%s_form345" % q), q, {"0001045810", "0001652044"}, {"0001045810": "NVDA", "0001652044": "GOOG"})
    idx = ins.history_index(hist)
    def t(cik, d="2026-09-10", issuer="0001045810"):
        return {"issuer_cik": issuer, "insider_cik": cik, "date": d, "code": "P"}
    assert ins.classify(t("0000002001"), idx)[0] == "routine"                      # Rita
    assert ins.classify(t("0000002002"), idx)[1].startswith("opportunistic: no open-market trade in September of 2023")   # Oscar
    assert ins.classify(t("0000002003"), idx)[1].startswith("opportunistic by the rule: 2 prior year(s)")                # Tina (her 2023 M row does not count)
    assert ins.classify(t("0000002004"), idx)[1].startswith("opportunistic by the rule: 0 prior year(s)")                # Ned (his 2023 row is a 4/A)
    assert ins.classify(t("0000004004", issuer="0001652044"), idx)[0] == "routine"  # Rob sells every September
    assert ins.classify(t("0000002001", d="2026-10-10"), idx)[0] == "opportunistic"  # Rita in October: not her month


def test_cluster_flag_fires_for_three_distinct_buyers_not_for_one_insider():
    def buy(cik, name, d):
        return {"insider_cik": cik, "insider": name, "date": d, "code": "P"}
    three = [buy("1", "One", "2026-09-05"), buy("2", "Two", "2026-09-12"), buy("3", "Three", "2026-09-25")]
    c = ins.cluster_of(three, "buyers")
    assert c["flag"] is True and c["n_distinct_buyers_30d"] == 3 and c["buyers"] == ["One", "Three", "Two"]
    assert (c["window_start"], c["window_end"]) == ("2026-09-05", "2026-09-25")
    one = [buy("1", "One", "2026-09-03"), buy("1", "One", "2026-09-10"), buy("1", "One", "2026-09-17")]
    c1 = ins.cluster_of(one, "buyers")
    assert c1["flag"] is False and c1["n_distinct_buyers_30d"] == 1 and c1["buyers"] == ["One"]
    assert (c1["window_start"], c1["window_end"]) == ("2026-09-03", "2026-09-17")
    # exactly 30 days apart fires; 31 does not
    assert ins.cluster_of([buy("1", "A", "2026-08-01"), buy("2", "B", "2026-08-15"), buy("3", "C", "2026-08-31")], "buyers")["flag"] is True
    assert ins.cluster_of([buy("1", "A", "2026-08-01"), buy("2", "B", "2026-08-15"), buy("3", "C", "2026-09-01")], "buyers")["flag"] is False
    two = ins.cluster_of([buy("1", "A", "2026-08-01"), buy("2", "B", "2026-08-02")], "sellers")
    assert two["flag"] is False and two["n_distinct_sellers_30d"] == 2
    empty = ins.cluster_of([], "buyers")
    assert empty["flag"] is False and empty["n_distinct_buyers_30d"] == 0 and empty["window_start"] is None


# ─── E1 end to end (offline fixtures) ─────────────────────────────────────────────────────
def test_e1_offline_run_cards_clusters_and_sales_rule():
    with tempfile.TemporaryDirectory() as td:
        d = offline_insiders(Path(td))
        # header: served-file contract
        assert d["cadence"] == "daily" and d["session_date"] == "2026-09-30" and d["as_of"] == AS_OF
        assert d["fetched_at"] is None and d["status"] == "offline_fixture" and d["source"]["mode"] == "offline_fixture"
        assert "Decoding Inside Information" in d["method"]["citation"] and "Journal of Finance" in d["method"]["citation"]
        assert "same calendar month in each of the three prior calendar years" in d["method"]["rule"]
        assert d["history_coverage"]["quarters_loaded"] == ["2023q1", "2023q3", "2024q3", "2025q3"] and d["history_coverage"]["complete"] is False
        assert d["history_coverage"]["years_required"] == [2023, 2024, 2025]
        assert d["window"] == {"start": "2026-07-02", "end": AS_OF, "days": 90, "cluster_days": 30, "cluster_min_distinct": 3}
        assert d["universe"] == {"held": ["NVDA", "AVGO", "GOOG", "GEV", "MU"], "board": ["NVDA", "AVGO", "GOOG", "GEV", "LMT", "TSM"]}
        assert d["signal_registration"]["document"] == "reports/insider_signal_registration_2026-09-30.md"
        assert d["source"]["feed"]["ignored_rows"] == {"F": 1, "derivative": 2, "M": 1, "A": 1}
        n = d["names"]
        assert sorted(n) == ["AVGO", "GEV", "GOOG", "LMT", "MU", "NVDA", "TSM"]
        # NVDA: Rita (routine) excluded; Oscar, Tina, Ned listed with the classification stated; cluster fires
        nv = n["NVDA"]
        assert nv["card"] is True and nv["roles"] == ["held", "board"] and nv["window_trades"] == 4      # Ned's June trade is outside the window
        rows = nv["opportunistic_purchases_90d"]
        assert [(r["insider"], r["role"], r["shares"], r["dollars"], r["date"]) for r in rows] == [
            ("Opportune Oscar", "Chief Financial Officer", 1000.0, 120500.0, "2026-09-05"),
            ("Twoyear Tina", "Director", 200.0, 24200.0, "2026-09-12"),
            ("Newcomer Ned", "EVP, Operations", 300.0, 37500.0, "2026-09-25")]
        assert all(r["classification"] == "opportunistic" and r["classification_basis"] for r in rows)
        assert rows[0]["classification_basis"].startswith("opportunistic: no open-market trade in September of 2023")
        assert rows[1]["classification_basis"].startswith("opportunistic by the rule: 2 prior year(s)")
        assert rows[2]["classification_basis"].startswith("opportunistic by the rule: 0 prior year(s)")
        assert rows[0]["filing_url"] == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000102/" and rows[0]["filing_date"] == "2026-09-08"
        assert rows[1]["ownership"] == "indirect" and rows[0]["price"] == 120.5
        assert nv["cluster"]["flag"] is True and nv["cluster"]["n_distinct_buyers_30d"] == 3
        assert nv["cluster"]["buyers"] == ["Newcomer Ned", "Opportune Oscar", "Twoyear Tina"]          # Rita is not a buyer here
        assert (nv["cluster"]["window_start"], nv["cluster"]["window_end"]) == ("2026-09-05", "2026-09-25")
        assert nv["counts"]["purchases_90d"] == {"opportunistic": 3, "routine": 1, "distinct_opportunistic_buyers": 3}
        assert nv["routine_excluded"] == {"purchases": 1, "sales": 0} and nv["sales_shown"] == []
        # AVGO: three buys by ONE insider — no cluster
        av = n["AVGO"]
        assert len(av["opportunistic_purchases_90d"]) == 3 and av["cluster"]["flag"] is False and av["cluster"]["n_distinct_buyers_30d"] == 1
        assert av["counts"]["purchases_90d"]["distinct_opportunistic_buyers"] == 1
        # GOOG: three distinct opportunistic sellers within 30 days → sales shown with the label; the routine seller excluded
        go = n["GOOG"]
        assert go["sales_cluster"]["flag"] is True and go["sales_cluster"]["n_distinct_sellers_30d"] == 3
        assert [s["insider"] for s in go["sales_shown"]] == ["Seller Sam", "Seller Sue", "Seller Sid"]
        assert all(s["classification"] == "opportunistic" for s in go["sales_shown"])
        assert go["sales_shown_label"] == "sales are mostly compensation or diversification" == d["method"]["sales_label"]
        assert go["routine_excluded"]["sales"] == 1 and go["counts"]["sales_90d"] == {"opportunistic": 3, "routine": 1, "distinct_opportunistic_sellers": 3}
        assert go["opportunistic_purchases_90d"] == [] and go["cluster"]["flag"] is False
        # GEV: two opportunistic sellers → not clustered → nothing shown
        ge = n["GEV"]
        assert ge["counts"]["sales_90d"]["opportunistic"] == 2 and ge["sales_cluster"]["flag"] is False and ge["sales_shown"] == []
        assert ge["sales_shown_reason"].startswith("not shown")
        # MU: joint filing attributed once, co-owner recorded
        mu = n["MU"]
        assert len(mu["opportunistic_purchases_90d"]) == 1 and mu["opportunistic_purchases_90d"][0]["co_owners"] == ["Mike Family Trust"]
        assert mu["cluster"]["n_distinct_buyers_30d"] == 1 and mu["roles"] == ["held"]
        # LMT: board only — the flag and counts, no card fields
        lm = n["LMT"]
        assert lm["card"] is False and lm["roles"] == ["board"] and "opportunistic_purchases_90d" not in lm and "sales_shown" not in lm
        assert lm["cluster"]["flag"] is True and lm["cluster"]["n_distinct_buyers_30d"] == 3
        assert d["board"]["LMT"]["cluster_flag"] is True and d["board"]["LMT"]["held"] is False and d["board"]["LMT"]["cluster_window"] == ["2026-08-20", "2026-09-15"]
        assert d["board"]["NVDA"]["cluster_flag"] is True and d["board"]["NVDA"]["held"] is True and d["board"]["AVGO"]["cluster_flag"] is False
        assert "MU" not in d["board"] and sorted(d["board"]) == ["AVGO", "GEV", "GOOG", "LMT", "NVDA", "TSM"]
        # TSM: nothing filed
        assert n["TSM"]["window_trades"] == 0 and "no open-market Form 4" in n["TSM"]["note"] and n["TSM"]["cluster"]["flag"] is False
        # language and directive rules on the served text
        blob = json.dumps(d).lower()
        import re
        assert not re.search(r"\bedge\b", blob) and not re.search(r"\balpha\b", blob)
        for tok in ('"action":', '"recommendation":', "buy now", "sell now"):
            assert tok not in blob, tok


def test_e1_offline_refuses_repo_data_dir_and_dry_run_writes_nothing():
    cp = run_cli("insiders.py", "--offline", str(FIX), "--as-of", AS_OF)
    assert cp.returncode == 2 and "--offline needs --data-dir or --dry-run" in cp.stdout, cp.stdout + cp.stderr
    cp = run_cli("holders_13f.py", "--offline", str(FIX), "--as-of", AS_OF)
    assert cp.returncode == 2 and "--offline needs --data-dir or --dry-run" in cp.stdout, cp.stdout + cp.stderr
    with tempfile.TemporaryDirectory() as td:
        for script in ("insiders.py", "holders_13f.py"):
            cp = run_cli(script, "--offline", str(FIX), "--dry-run", "--as-of", AS_OF, "--data-dir", td)
            assert cp.returncode == 0 and "dry run: nothing written" in cp.stdout, cp.stdout + cp.stderr
        assert list(Path(td).iterdir()) == []
    # the same window through the in-process entry point (dry run)
    with contextlib.redirect_stdout(io.StringIO()):
        rc, payload = ins.run(_Ns(offline=str(FIX), dry_run=True))
    assert rc == 0 and payload["names"]["NVDA"]["cluster"]["flag"] is True


# ─── submissions feed helpers against canned pages (no network) ──────────────────────────
def test_form4_filings_pagination_and_document_url():
    recent = {"accessionNumber": ["0001045810-26-000104", "0001045810-26-000103", "0001045810-26-000200", "0001045810-26-000102"],
              "filingDate": ["2026-09-28", "2026-09-14", "2026-09-10", "2026-09-08"],
              "reportDate": ["2026-09-25", "2026-09-12", "2026-09-09", "2026-09-05"],
              "form": ["4", "4", "4/A", "4"],
              "primaryDocument": ["xslF345X05/a.xml", "b.xml", "c.xml", "d.htm"], "primaryDocDescription": ["", "", "", ""]}
    older = {"accessionNumber": ["0001045810-26-000101", "0001045810-26-000090"], "filingDate": ["2026-09-03", "2026-06-22"],
             "reportDate": ["2026-09-02", "2026-06-20"], "form": ["4", "4"], "primaryDocument": ["e.xml", "f.xml"], "primaryDocDescription": ["", ""]}
    pages = {ec.submissions_url("0001045810"): {"filings": {"recent": recent, "files": [{"name": "CIK0001045810-submissions-001.json", "filingFrom": "2026-01-01", "filingTo": "2026-09-05"}]}},
             "https://data.sec.gov/submissions/CIK0001045810-submissions-001.json": older,
             "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000102/index.json": {"directory": {"item": [{"name": "d.htm"}, {"name": "xslF345X05/d.xml"}, {"name": "wk-form4_1.xml"}]}}}

    class Fake:
        def __init__(self):
            self.urls = []

        def get_json(self, url, **kw):
            self.urls.append(url)
            return pages[url]

    fk = Fake()
    rows, counts = ec.form4_filings(fk, "0001045810", "2026-07-02")
    assert [r["accessionNumber"] for r in rows] == ["0001045810-26-000101", "0001045810-26-000102", "0001045810-26-000103", "0001045810-26-000104"]
    assert counts["form4"] == 4 and counts["form4_amendments_skipped"] == 1 and counts["pages_followed"] == 1
    assert ec.form4_document_url(fk, "0001045810", "0001045810-26-000104", "xslF345X05/a.xml") == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000104/a.xml"
    assert ec.form4_document_url(fk, "0001045810", "0001045810-26-000102", "d.htm") == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000102/wk-form4_1.xml"
    assert ec.flatten_filings({}) == [] and ec.flatten_filings({"accessionNumber": ["x"], "form": ["4"]}) == [{"accessionNumber": "x", "form": "4"}]


# ─── E2: 13F context ──────────────────────────────────────────────────────────────────────
def test_13f_name_matching_and_windows():
    assert h13.core_name("NVIDIA CORP") == "NVIDIA" and h13.core_name("Broadcom Inc.") == "BROADCOM"
    assert h13.core_name("GE Vernova Inc.") == "GE VERNOVA" and h13.core_name("Alphabet Inc.") == "ALPHABET"
    assert h13.core_name("MICRON TECHNOLOGY INC") == "MICRON" and h13.core_name("Arista Networks, Inc.") == "ARISTA"
    assert h13.matcher_for("GOOG", "Alphabet Inc.") == ("ALPHABET", "C") and h13.matcher_for("GOOGL", None) == ("ALPHABET", "A")
    assert h13.matcher_for("ZZZZ", "Zeta Zero Holdings Corp") == ("ZETA ZERO", None)
    assert h13.class_of("CAP STK CL C") == "C" and h13.class_of("CLASS A COMMON") == "A" and h13.class_of("COM") is None
    assert h13.name_matches("NVIDIA CORP", "NVIDIA") and not h13.name_matches("NVIDIANA HOLDINGS LTD", "NVIDIA")
    assert h13._window_of("01jun2026-31aug2026_form13f.zip") == "01jun2026..31aug2026" and h13._window_of("2024q1_form13f.zip") == "2024q1"
    assert h13._prev_quarter("2026-06-30") == (2026, 1) and h13._prev_quarter("2026-03-31") == (2025, 4)


def test_13f_top10_change_new_exit_screen_and_dates_on_every_figure():
    with tempfile.TemporaryDirectory() as td:
        d = offline_13f(Path(td))
        assert d["cadence"] == "weekly" and d["as_of"] == AS_OF and d["status"] == "offline_fixture"
        assert d["quarters"] == {"latest": "2026-06-30", "prior": "2026-03-31"}
        assert [u["file"] for u in d["datasets_used"]] == ["01jun2026-31aug2026_form13f", "01mar2026-31may2026_form13f"]
        assert d["datasets_used"][0]["filing_window"] == "01jun2026..31aug2026"
        cm = d["cusip_map"]
        assert cm["NVDA"]["cusip"] == "67066G104" and "NVIDIA" in cm["NVDA"]["provenance"] and cm["NVDA"]["distinct_filings"] == 26
        assert cm["GOOG"]["cusip"] == "02079K107" and cm["GOOG"]["class"] == "C"              # class C, never class A (02079K305)
        assert cm["AVGO"]["cusip"] == "11135F101" and cm["GEV"]["cusip"] is None and cm["MU"]["cusip"] is None
        assert all("warning" not in cm[t] for t in ("NVDA", "GOOG", "AVGO"))
        nv = d["names"]["NVDA"]
        assert nv["caption"] == "positions as of 2026-06-30, disclosed 2026-08-20; long positions only; no hedges shown."
        assert nv["as_of_quarter_end"] == "2026-06-30" and nv["prior_quarter_end"] == "2026-03-31" and nv["disclosed_latest"] == "2026-08-20"
        top = nv["top_holders"]
        assert len(top) == 10 and [h["manager"] for h in top][:4] == ["Aurora Capital LP", "Fir Tree Holdings", "Dover Asset Management", "Nova Point Capital"]
        assert "Oak Ridge Partners" not in [h["manager"] for h in top]                     # 11th by shares
        a = top[0]
        assert (a["shares"], a["prior_shares"], a["share_change"], a["share_change_pct"]) == (1250000.0, 1000000.0, 250000.0, 25.0)   # the RESTATEMENT wins
        assert a["disclosed"] == "2026-08-20" and a["filings_used"] == ["13F-HR/A RESTATEMENT"] and a["value_usd"] == 187500000.0 and a["aum_usd"] == 5.25e9
        dv = top[2]
        assert dv["prior_status"] == "none" and dv["prior_shares"] == 0.0 and dv["share_change"] == 300000.0 and dv["share_change_pct"] is None
        nova = top[3]
        assert nova["prior_status"] == "no prior filing" and nova["prior_shares"] is None and nova["share_change"] == 80000.0
        inlet = next(h for h in top if h["manager"] == "Inlet Fund I")
        assert inlet["share_change"] == -5000.0 and inlet["share_change_pct"] == -16.67 and inlet["prior_disclosed"] == "2026-05-03"
        assert [x["manager"] for x in nv["new_positions_over_1b"]] == ["Dover Asset Management", "Nova Point Capital"]   # Cedar ($550M) screened out
        assert [x["manager"] for x in nv["full_exits_over_1b"]] == ["Birch Partners LLC", "Pine Valley Management"]     # Kestrel ($200M) screened out
        pine = nv["full_exits_over_1b"][1]
        assert pine["prior_shares"] == 100000.0 and pine["prior_disclosed"] == "2026-06-05" and pine["disclosed"] == "2026-08-13" and pine["aum_usd"] == 1.15e9
        assert [x["manager"] for x in nv["prior_holders_without_current_filing"]] == ["Maple Grove Advisors"]            # not an exit
        assert nv["counts"]["holders_latest"] == 11 and nv["counts"]["holders_prior"] == 12                             # the PUT-only fund is never a holder
        assert nv["counts"]["new_positions_below_1b"] == 1 and nv["counts"]["full_exits_below_1b"] == 1
        assert nv["counts"]["shares_reported_latest"] == 2542000.0                                                     # the PRN row is excluded
        # every figure carries as_of_quarter_end and disclosed
        for name, sec in d["names"].items():
            for key in ("top_holders", "new_positions_over_1b", "full_exits_over_1b", "prior_holders_without_current_filing"):
                for fig in sec.get(key, []):
                    assert fig.get("as_of_quarter_end") and fig.get("disclosed"), (name, key, fig)
            assert sec["caption"].startswith("positions as of %s, disclosed " % sec["as_of_quarter_end"]) and sec["caption"].endswith("; long positions only; no hedges shown.")
        # Alphabet class C only: 210,000 shares, not 260,000 with class A
        go = d["names"]["GOOG"]
        assert len(go["top_holders"]) == 1 and go["top_holders"][0]["shares"] == 210000.0 and go["top_holders"][0]["share_change"] == 10000.0
        av = d["names"]["AVGO"]
        assert [h["manager"] for h in av["top_holders"]][:2] == ["Aurora Capital LP", "Dover Asset Management"] and av["counts"]["holders_latest"] == 6
        assert [x["manager"] for x in av["new_positions_over_1b"]] == ["Birch Partners LLC", "Pine Valley Management"]
        # names without rows are reported, not invented
        assert d["names"]["GEV"]["top_holders"] == [] and "no INFOTABLE row" in d["names"]["GEV"]["note"] and any(w.startswith("GEV:") for w in d["warnings"])
        blob = json.dumps(d).lower()
        import re
        assert not re.search(r"\bedge\b", blob) and not re.search(r"\balpha\b", blob)
        for tok in ('"action":', '"recommendation":', "buy now", "sell now"):
            assert tok not in blob, tok


def test_13f_effective_filings_rules():
    orig = {"accession": "a", "filing_date": "2026-08-10", "type": "13F-HR", "is_amendment": False, "amendment_type": None}
    rest = {"accession": "b", "filing_date": "2026-08-20", "type": "13F-HR/A", "is_amendment": True, "amendment_type": "RESTATEMENT"}
    add = {"accession": "c", "filing_date": "2026-08-25", "type": "13F-HR/A", "is_amendment": True, "amendment_type": "NEW HOLDINGS"}
    early_add = {"accession": "d", "filing_date": "2026-08-15", "type": "13F-HR/A", "is_amendment": True, "amendment_type": "NEW HOLDINGS"}
    used, base = h13.effective_filings([orig, rest, add, early_add])
    assert base is rest and [u["accession"] for u in used] == ["b", "c"]          # the restatement replaces; only later additions count
    used, base = h13.effective_filings([orig, early_add])
    assert base is orig and [u["accession"] for u in used] == ["a", "d"]
    used, base = h13.effective_filings([add])
    assert base is add and used == [add]
    assert h13.effective_filings([]) == ([], None)


# ─── the live code path against a fake EDGAR (canned responses through the one network function) ──
def _zip_dir(src: Path, dst: Path) -> Path:
    import zipfile
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.iterdir()):
            z.write(p, p.name)
    return dst


def test_live_path_end_to_end_against_fake_edgar():
    """The nightly's live path — company_tickers, the submissions feed, Form 4 documents, the
    quarterly data-set zips, the history store, the 13F zips — served by a router in place of
    http_get. Never touches the network; asserts the store is built once and reused."""
    import zipfile
    saved = os.environ.get("SEC_USER_AGENT")
    os.environ["SEC_USER_AGENT"] = FAKE_UA
    real_get, real_uni, real_union = ec.http_get, ec.universe, ec.union_universe
    fx_uni = json.loads((FIX / "universe.json").read_text())
    filings = json.loads((FIX / "form4" / "filings.json").read_text())
    ct = json.loads((FIX / "company_tickers.json").read_text())
    cik_of = {r["ticker"]: "%010d" % r["cik_str"] for r in ct.values()}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        zips = {}
        for q in ("2023q1", "2023q3", "2024q3", "2025q3"):
            zips["%s_form345.zip" % q] = _zip_dir(FIX / "datasets" / ("%s_form345" % q), tmp / ("%s_form345.zip" % q))
        for w in ("01mar2026-31may2026", "01jun2026-31aug2026"):
            zips["%s_form13f.zip" % w] = _zip_dir(FIX / "13f" / ("%s_form13f" % w), tmp / ("%s_form13f.zip" % w))
        served = []

        def router(url, ua, timeout=None):
            assert ua == FAKE_UA
            served.append(url)
            tail = url.rsplit("/", 1)[-1]
            if url == ec.COMPANY_TICKERS_URL:
                return 200, {}, json.dumps(ct).encode()
            if url.startswith(ec.HOST_DATA + "/submissions/CIK"):
                cik = tail[3:13]
                accs = sorted((a for a in filings if ins.parse_form4((FIX / "form4" / (a + ".xml")).read_bytes())["issuer_cik"] == cik),
                              key=lambda a: filings[a]["filingDate"], reverse=True)
                recent = {"accessionNumber": accs, "filingDate": [filings[a]["filingDate"] for a in accs], "reportDate": ["" for _ in accs],
                          "form": ["4" for _ in accs], "primaryDocument": [filings[a]["primaryDocument"] for a in accs], "primaryDocDescription": ["" for _ in accs]}
                return 200, {}, json.dumps({"cik": cik, "filings": {"recent": recent, "files": []}}).encode()
            if "/Archives/edgar/data/" in url and url.endswith(".xml"):
                acc_nd = url.rsplit("/", 2)[-2]
                acc = "%s-%s-%s" % (acc_nd[:10], acc_nd[10:12], acc_nd[12:])
                return 200, {"content-encoding": "gzip"}, gzip.compress((FIX / "form4" / (acc + ".xml")).read_bytes())
            if tail in zips and ("datastandardsinnovation" in url or "structureddata" in url):
                if tail.endswith("_form13f.zip") and "datastandardsinnovation" not in url:
                    return 404, {}, b""            # the 13F sets live under the newer prefix in this fake
                return 200, {}, zips[tail].read_bytes()
            return 404, {}, b""

        ec.http_get = router
        ec.universe = lambda data_dir=None: fx_uni
        ec.union_universe = lambda data_dir=None: sorted(set(fx_uni["held"]) | set(fx_uni["board"]))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc, d = ins.run(_Ns(cache_dir=str(tmp / "cache"), data_dir=str(tmp / "data"), history_store=str(tmp / "store" / "insider_history.parquet")))
            assert rc == 0 and d["status"] == "partial" and d["source"]["mode"] == "live" and d["fetched_at"]        # partial: 8 quarters are 404 in the fake
            assert d["history_coverage"]["quarters_loaded"] == ["2023q1", "2023q3", "2024q3", "2025q3"] and len(d["history_coverage"]["quarters_missing"]) == 8
            assert d["history_coverage"]["fetched_this_run"] == ["2023q1", "2023q3", "2024q3", "2025q3"] and d["history_coverage"]["store"].endswith("insider_history.parquet")
            assert d["names"]["NVDA"]["cluster"]["flag"] is True and d["names"]["NVDA"]["routine_excluded"]["purchases"] == 1
            assert [r["insider"] for r in d["names"]["NVDA"]["opportunistic_purchases_90d"]] == ["Opportune Oscar", "Twoyear Tina", "Newcomer Ned"]
            assert d["names"]["NVDA"]["opportunistic_purchases_90d"][0]["filing_url"].endswith("/000104581026000102/synthetic-form4_000104581026000102.xml")
            assert d["names"]["GOOG"]["sales_cluster"]["flag"] is True and d["names"]["LMT"]["card"] is False and d["board"]["LMT"]["cluster_flag"] is True
            assert d["source"]["per_name"]["TSM"]["filings"] == 0 and d["source"]["per_name"]["NVDA"] == {"cik": "0001045810", "filings": 5, "parsed": 5, "amendments_skipped": 0}
            assert d["names"]["NVDA"]["window_trades"] == 4                     # the June filing is before the window and is not fetched
            assert (tmp / "data" / "ownership" / "insiders.json").exists() and (tmp / "store" / "insider_history.parquet").exists()
            meta = json.loads((tmp / "store" / "insider_history_meta.json").read_text())
            assert sorted(meta["quarters"]) == ["2023q1", "2023q3", "2024q3", "2025q3"] and meta["cadence"] == "on_change" and cik_of["NVDA"] in meta["universe_ciks"]
            assert not any(u for u in served if u.endswith("_form13f.zip"))
            n_first = len(served)
            # second run: the store and the document cache are reused — no data-set zip and no Form 4 document is fetched again
            with contextlib.redirect_stdout(io.StringIO()):
                rc, d2 = ins.run(_Ns(cache_dir=str(tmp / "cache"), data_dir=str(tmp / "data"), history_store=str(tmp / "store" / "insider_history.parquet")))
            again = served[n_first:]
            assert rc == 0 and d2["history_coverage"]["fetched_this_run"] == [] and d2["names"]["NVDA"]["cluster"]["flag"] is True
            assert not any(u.endswith("_form345.zip") and "2023q1" in u or u.endswith(".xml") for u in again), again
            # the 13F job on the same fake
            with contextlib.redirect_stdout(io.StringIO()):
                rc, h = h13.run(_Ns(cache_dir=str(tmp / "cache"), data_dir=str(tmp / "data")))
            assert rc == 0 and h["quarters"] == {"latest": "2026-06-30", "prior": "2026-03-31"}
            assert h["status"] == "partial" and sorted(w[:3] for w in h["warnings"]) == ["GEV", "MU:"]     # held names without INFOTABLE rows are flagged, not invented
            assert [u["file"] for u in h["datasets_used"]] == ["01jun2026-31aug2026_form13f.zip", "01mar2026-31may2026_form13f.zip"]
            assert all(u["sha256"] and "datastandardsinnovation" in u["source_url"] for u in h["datasets_used"])
            assert h["names"]["NVDA"]["top_holders"][0]["shares"] == 1250000.0 and h["names"]["NVDA"]["caption"].startswith("positions as of 2026-06-30, disclosed 2026-08-20")
            assert (tmp / "data" / "ownership" / "holders_13f.json").exists()
            assert all(u.startswith("https://") for u in served)
            # the weekly gate: with a served file 0 days old a live run does nothing and fetches nothing
            n_before = len(served)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc, h2 = h13.run(_Ns(cache_dir=str(tmp / "cache"), data_dir=str(tmp / "data"), max_age_days=7))
            assert rc == 0 and h2 is None and len(served) == n_before and "weekly cadence, nothing to do" in out.getvalue()
            with contextlib.redirect_stdout(io.StringIO()):
                rc, h3 = h13.run(_Ns(cache_dir=str(tmp / "cache"), data_dir=str(tmp / "data"), max_age_days=7, as_of="2026-10-08"))
            assert rc == 0 and h3 is not None and h3["as_of"] == "2026-10-08"       # 8 days later it refreshes (from the cache)
            assert len(served) == n_before
        finally:
            ec.http_get, ec.universe, ec.union_universe = real_get, real_uni, real_union
            if saved is None:
                os.environ.pop("SEC_USER_AGENT", None)
            else:
                os.environ["SEC_USER_AGENT"] = saved


# ─── guard ───────────────────────────────────────────────────────────────────────────────
def test_zz_repository_data_untouched():
    assert _listing(DATA) == _GUARD["data"]
    assert _listing(DATA / "ownership") == _GUARD["own"]
    assert {n: _digest(DATA / "ownership" / n) for n in (_listing(DATA / "ownership") or [])} == _GUARD["own_files"]
    assert _listing(REPO / "scratch") == _GUARD["scratch"]
    assert _digest(DATA / "holdings.json") == _GUARD["holdings"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS %s" % name)
        except Exception:
            failed += 1
            print("FAIL %s" % name)
            traceback.print_exc()
    print("\n%d passed, %d failed" % (len(tests) - failed, failed))
    sys.exit(1 if failed else 0)
