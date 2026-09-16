#!/usr/bin/env python3
"""
tests/test_ingest_brokerage.py — holdings order Phase 2 tests: (2.1) brokerage CSV ingestion and
(2.2) action seeding from the parsed transactions.

Run with the venv interpreter, either way (no pytest dependency):
    .venv/bin/python tests/test_ingest_brokerage.py
    .venv/bin/python -m pytest tests/test_ingest_brokerage.py

Every test works on TEMPORARY copies of the synthetic fixtures under tests/fixtures/brokerage/.
Nothing under data/, inbox/ or scratch/ of the repository is written — the final test asserts it.
Read-only lookups against the real repository (data/regime_daily_published.csv, git history of
data/ticker_signals.json) are used for the regime / signal tests.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import traceback
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
FIX = REPO / "tests" / "fixtures" / "brokerage"
DATA = REPO / "data"
PY = sys.executable

sys.path.insert(0, str(SCRIPTS))
import ingest_brokerage as ib  # noqa: E402
import seed_actions_from_transactions as seed  # noqa: E402

SCHWAB_POS, SCHWAB_TXN = FIX / "schwab_like_positions.csv", FIX / "schwab_like_transactions.csv"
FID_POS, FID_TXN = FIX / "fidelity_like_positions.csv", FIX / "fidelity_like_history.csv"
BROKEN_POS = FIX / "broken_positions_unmappable_qty.csv"


# ─── guard: the repository's served files and inbox must be untouched by this run ───────
def _digest(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _listing(p: Path) -> list | None:
    return sorted(x.name for x in p.iterdir()) if p.exists() else None


_GUARD = {"holdings": _digest(DATA / "holdings.json"), "actions": _digest(DATA / "actions.jsonl"),
          "inbox": _listing(REPO / "inbox"), "scratch": _listing(REPO / "scratch")}


# ─── helpers ─────────────────────────────────────────────────────────────────────────────
def run(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(SCRIPTS / script), *args], capture_output=True, text=True, cwd=str(cwd))


def make_inbox(tmp: Path, positions: Path, transactions: Path | None,
               pos_name: str = "history.csv", txn_name: str = "positions.csv") -> Path:
    """Copies the fixtures under MISLEADING names — the jobs must find them by header sniffing."""
    inbox = tmp / "inbox"
    inbox.mkdir()
    shutil.copy(positions, inbox / pos_name)
    if transactions is not None:
        shutil.copy(transactions, inbox / txn_name)
    return inbox


def ingest_cli(tmp: Path, *extra: str) -> subprocess.CompletedProcess:
    return run("ingest_brokerage.py", "--inbox", str(tmp / "inbox"), "--scratch", str(tmp / "scratch"),
               "--data-dir", str(tmp / "data"), *extra, cwd=tmp)


def scratch_dir(tmp: Path) -> Path:
    dirs = sorted((tmp / "scratch").glob("ingest_*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def count_lines(p: Path) -> int:
    return sum(1 for line in p.read_text().splitlines() if line.strip())


def brokerage_entries(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()
            and json.loads(l).get("source") == "brokerage transactions"]


# ─── (2.1) parsing primitives ────────────────────────────────────────────────────────────
def test_number_and_date_parsing():
    pn = ib.parse_number
    assert pn("$45,500.00") == Decimal("45500.00")
    assert pn("(1,234.5)") == Decimal("-1234.5")
    assert pn("-$12.00") == Decimal("-12.00") and pn("$-1500.00") == Decimal("-1500.00")
    assert pn("+$10.00") == Decimal("10.00")
    assert pn("37.2%") == Decimal("37.2")
    assert pn("100.1509") == Decimal("100.1509")
    for tok in ("--", "N/A", "", None, "-", "$-"):
        assert pn(tok) is None, tok
    assert ib.num_as_given(Decimal("50")) == 50 and isinstance(ib.num_as_given(Decimal("50")), int)
    assert ib.num_as_given(Decimal("100.1509")) == 100.1509

    pd_ = ib.parse_date
    for txt in ("2026-09-16", "09/16/2026", "9/16/26", "2026/09/16", "16-Sep-2026", "Sep 16, 2026",
                "20260916", "09/16/2026 4:33 pm ET", " 09/16/2026"):
        assert pd_(txt) == "2026-09-16", txt
    assert pd_("08/28/2026 as of 08/27/2026") == "2026-08-27"     # Schwab posting 'as of' effective date
    assert pd_("") is None and pd_("not a date") is None

    st = ib.parse_stamp("Positions for account Individual ...XXX as of 04:33 PM ET, 2026/09/16")
    assert st["date"] == "2026-09-16" and st["datetime"] == "2026-09-16T16:33:00-04:00"
    st = ib.parse_stamp("Date downloaded 09/16/2026 4:33 pm ET")
    assert st["date"] == "2026-09-16" and st["datetime"] == "2026-09-16T16:33:00-04:00"
    assert ib.parse_stamp("MU,MICRON TECHNOLOGY INC,50") is None

    assert ib.norm_ticker(" ANET ") == "ANET" and ib.norm_ticker("SPAXX**") == "SPAXX" and ib.norm_ticker("brk/b") == "BRK/B"
    assert ib.classify_action("Buy") == "buy" and ib.classify_action("YOU SOLD X (Cash)") == "sell"
    assert ib.classify_action("Reinvest Shares") == "reinvest_shares" and ib.classify_action("Reinvest Dividend") == "dividend"
    assert ib.classify_action("REINVESTMENT GE VERNOVA") == "reinvest_shares"
    assert ib.classify_action("Bank Interest") == "interest" and ib.classify_action("MoneyLink Transfer") == "transfer"


# ─── (2.1) header mapping per dialect ────────────────────────────────────────────────────
def test_schwab_dialect_mapping():
    res = ib.ingest(None, positions=SCHWAB_POS, transactions=SCHWAB_TXN)
    assert res.complete and not res.problems, (res.problems, res.unmapped_required)
    pm = res.positions.mapping
    assert pm["symbol"] == "Symbol" and pm["quantity"] == "Quantity" and pm["market_value"] == "Market Value"
    assert pm["cost_basis_total"] == "Cost Basis" and "cost_basis_per_share" not in pm
    assert pm["price"] == "Price" and pm["security_type"] == "Security Type"
    assert "Price Change $" in res.positions.unmatched_headers and "Ratings" in res.positions.unmatched_headers
    assert res.positions.stamp["date"] == "2026-09-16"
    tm = res.transactions.mapping
    assert tm == {"date": "Date", "action": "Action", "symbol": "Symbol", "quantity": "Quantity", "price": "Price",
                  "amount": "Amount", "fees": "Fees & Comm", "description": "Description"}, tm
    assert res.transactions.unmatched_headers == []
    h = res.holdings
    assert h["cadence"] == "on_change" and h["source"] == "brokerage export"
    assert h["as_of"] == "2026-09-16" and h["exported_at"] == "2026-09-16T16:33:00-04:00"
    assert [x["ticker"] for x in h["holdings"]] == ["MU", "NVDA", "ANET"]       # padded ' ANET ' normalised
    cats = [t["category"] for t in res.transactions_rows]
    assert cats == ["buy", "sell", "buy", "reinvest_shares", "dividend", "interest", "dividend", "transfer"], cats
    assert res.transactions_rows[2]["date"] == "2026-08-27" and res.transactions_rows[2]["date_raw"] == "08/28/2026 as of 08/27/2026"


def test_fidelity_dialect_mapping():
    res = ib.ingest(None, positions=FID_POS, transactions=FID_TXN)
    assert res.complete and not res.problems, (res.problems, res.unmapped_required)
    pm = res.positions.mapping
    assert pm["symbol"] == "Symbol" and pm["quantity"] == "Quantity" and pm["market_value"] == "Current Value"
    assert pm["cost_basis_per_share"] == "Average Cost Basis" and pm["cost_basis_total"] == "Cost Basis Total"
    assert pm["price"] == "Last Price" and pm["security_type"] == "Type" and pm["account"] == "Account Number"
    assert "Today's Gain/Loss Dollar" in res.positions.unmatched_headers
    tm = res.transactions.mapping
    assert tm["date"] == "Run Date" and tm["settlement_date"] == "Settlement Date"       # not confused
    assert tm["action"] == "Action" and tm["fees"] == "Fees" and tm["amount"] == "Amount"
    assert "Type" in res.transactions.unmatched_headers
    h = res.holdings
    assert [x["ticker"] for x in h["holdings"]] == ["GEV", "BMNR"]      # Type = 'Cash' equities are NOT cash; SPAXX is
    gev = h["holdings"][0]
    assert gev["cost_basis"] == 914.0 and "Average Cost Basis" in gev["cost_basis_basis"]
    assert h["as_of"] == "2026-09-16" and h["exported_at"] == "2026-09-16T16:33:00-04:00"
    rows = res.transactions_rows
    sell = next(r for r in rows if r["category"] == "sell")
    assert sell["ticker"] == "BMNR" and sell["quantity"] == Decimal("25") and sell["quantity_as_given"] == Decimal("-25")
    assert sell["settlement_date"] == "2026-09-10" and sell["date"] == "2026-09-09"
    buy = next(r for r in rows if r["category"] == "buy")
    assert buy["ticker"] == "GEV" and buy["quantity"] == Decimal("5") and buy["price"] == Decimal("990.00")
    assert sorted(r["category"] for r in rows) == ["buy", "dividend", "interest", "reinvest_shares", "sell"]


def test_fractional_shares_preserved():
    res = ib.ingest(None, positions=SCHWAB_POS, transactions=SCHWAB_TXN)
    by = {x["ticker"]: x for x in res.holdings["holdings"]}
    assert by["NVDA"]["shares"] == 100.1509
    assert by["MU"]["shares"] == 50 and isinstance(by["MU"]["shares"], int)
    text = json.dumps(res.holdings, default=ib._json_default)
    assert '"shares": 100.1509' in text
    res2 = ib.ingest(None, positions=FID_POS, transactions=FID_TXN)
    assert {x["ticker"]: x["shares"] for x in res2.holdings["holdings"]}["BMNR"] == 200.0702
    reinvest = next(r for r in res.transactions_rows if r["category"] == "reinvest_shares")
    assert reinvest["quantity"] == Decimal("0.1509")


def test_cash_taken_from_cash_line():
    res = ib.ingest(None, positions=SCHWAB_POS, transactions=SCHWAB_TXN)
    assert res.holdings["cash"] == 12345.67 and "Cash & Cash Investments" in res.holdings["cash_source"]
    assert len(res.positions.cash_lines) == 1 and res.positions.cash_lines[0]["value"] == 12345.67
    res2 = ib.ingest(None, positions=FID_POS, transactions=FID_TXN)
    assert res2.holdings["cash"] == 54321 and "SPAXX" in res2.holdings["cash_source"]
    assert len(res2.positions.cash_lines) == 1
    # 'Pending Activity' and 'Account Total' rows are neither cash nor holdings
    skipped = [s["reason"] for s in res2.positions.skipped] + [s["reason"] for s in res.positions.skipped]
    assert sum("total/summary row" in r for r in skipped) == 2


def test_total_cost_divided_to_per_share():
    res = ib.ingest(None, positions=SCHWAB_POS, transactions=SCHWAB_TXN)
    by = {x["ticker"]: x for x in res.holdings["holdings"]}
    assert by["MU"]["cost_basis"] == 910.0 and by["MU"]["cost_basis_basis"].startswith("total cost ('Cost Basis') / shares")
    assert by["NVDA"]["cost_basis"] == round(8695.10 / 100.1509, 4) == 86.82
    assert by["ANET"]["cost_basis"] == 160.0


# ─── (2.1) the CLI: sniffing, dry run, --write to a temp data dir, exit 2 ────────────────
def test_cli_dry_run_finds_files_by_header_not_name():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        make_inbox(tmp, SCHWAB_POS, SCHWAB_TXN)          # positions saved as history.csv, transactions as positions.csv
        (tmp / "data").mkdir()
        cp = ingest_cli(tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert list((tmp / "data").iterdir()) == []                      # dry run: nothing served
        sd = scratch_dir(tmp)
        assert {p.name for p in sd.iterdir()} == {"holdings_candidate.json", "mapping.json", "transactions_parsed.csv"}
        m = json.load(open(sd / "mapping.json"))
        assert m["complete"] is True
        assert [(f["name"], f["role"]) for f in m["input_files"]] == [("history.csv", "positions"), ("positions.csv", "transactions")]
        assert "mapping chosen" in cp.stdout and "unmatched headers" in cp.stdout and "cash: 12345.67" in cp.stdout
        cand = json.load(open(sd / "holdings_candidate.json"))
        assert cand["source"] == "brokerage export" and cand["holdings"][1]["shares"] == 100.1509
        assert count_lines(sd / "transactions_parsed.csv") == 9          # header + 8 rows


def test_cli_write_writes_holdings_json_to_temp_data_dir():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inbox = make_inbox(tmp, SCHWAB_POS, SCHWAB_TXN)
        cp = ingest_cli(tmp, "--write")
        assert cp.returncode == 0, cp.stdout + cp.stderr
        hp = tmp / "data" / "holdings.json"
        # the served book and, beside it, the export record the referee compares against (order 16-Sept 2.3)
        assert hp.exists() and sorted(x.name for x in (tmp / "data").iterdir()) == ["holdings.json", "holdings_export.json"]
        ex = json.loads((tmp / "data" / "holdings_export.json").read_text())
        assert ex["input_sha256"] == json.loads(hp.read_text())["input_sha256"] and ex["cash"] == json.loads(hp.read_text())["cash"]
        assert [x["ticker"] for x in ex["positions"]] == [x["ticker"] for x in json.loads(hp.read_text())["holdings"]]
        h = json.load(open(hp))
        for k in ("cadence", "as_of", "source", "exported_at", "input_sha256", "input_files", "cash", "holdings"):
            assert k in h, k
        assert h["cadence"] == "on_change" and h["source"] == "brokerage export" and h["as_of"] == "2026-09-16"
        expect = hashlib.sha256((inbox / "history.csv").read_bytes() + (inbox / "positions.csv").read_bytes()).hexdigest()
        assert h["input_sha256"] == expect
        assert h["input_files"][0]["bytes"] == (inbox / "history.csv").stat().st_size
        assert h["cash"] == 12345.67
        assert [(x["ticker"], x["shares"], x["cost_basis"]) for x in h["holdings"]] == \
               [("MU", 50, 910.0), ("NVDA", 100.1509, 86.82), ("ANET", 100, 160.0)]
        assert all("cost_basis_basis" in x for x in h["holdings"])
        # --dry-run overrides --write
        shutil.rmtree(tmp / "data")
        cp = ingest_cli(tmp, "--write", "--dry-run")
        assert cp.returncode == 0 and not (tmp / "data").exists()


def test_unmapped_header_exits_2_and_writes_nothing_served():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        make_inbox(tmp, BROKEN_POS, SCHWAB_TXN)
        (tmp / "data").mkdir()
        cp = ingest_cli(tmp, "--write")
        assert cp.returncode == 2, cp.stdout + cp.stderr
        assert list((tmp / "data").iterdir()) == []                      # nothing served, even with --write
        assert "UNMAPPED REQUIRED" in cp.stdout + cp.stderr and "Holding Amt" in cp.stdout
        sd = scratch_dir(tmp)
        m = json.load(open(sd / "mapping.json"))
        assert m["complete"] is False
        assert m["positions"]["unmapped_required"] == ["quantity"]
        assert m["positions"]["unmatched_headers"] == ["Holding Amt"]
        cand = json.load(open(sd / "holdings_candidate.json"))
        assert cand["_unmapped_required"] == {"positions": ["quantity"]}
        assert [x["shares"] for x in cand["holdings"]] == [None, None] and cand["cash"] == 12345.67


# ─── (2.2) session mapping, published-vintage regime, signal lookup ─────────────────────
def test_session_mapping_for_non_session_dates():
    assert seed.session_for("2026-08-07") == ("2026-08-07", None)
    s, note = seed.session_for("2026-08-08")                     # Saturday → Monday
    assert s == "2026-08-10" and "not a session" in note and "2026-08-08" in note
    assert seed.session_for("2026-09-07")[0] == "2026-09-08"     # Labor Day → Tuesday
    assert seed.session_for("2026-07-03")[0] == "2026-07-06"     # July 4 observed (Fri) → Monday


def test_regime_lookup_from_published_vintage():
    v = seed.PublishedVintage(DATA / "regime_daily_published.csv")
    assert v.lookup("2026-08-07") == (0.2467, "LOW RISK", None)
    R, label, note = v.lookup("2026-08-27")                      # published row with a no_publish_reason
    assert R is None and label is None and note.startswith("no_publish_reason: run guard refused")
    assert v.lookup("2026-01-02") == (None, None, "no published vintage for this session")
    assert v.lookup("2026-08-08") == (None, None, "no published vintage for this session")   # Saturday: never a row
    for R, lab in ((0.0, "LOW RISK"), (0.2999, "LOW RISK"), (0.30, "ELEVATED"), (0.4999, "ELEVATED"),
                   (0.50, "HIGH RISK"), (0.6999, "HIGH RISK"), (0.70, "CRISIS"), (0.95, "CRISIS")):
        assert seed.regime_label(R) == lab, R
    try:                                                          # drift guard against the NAV job's labeller
        from compute_nav import regime_label as nav_label
    except Exception:
        nav_label = None
    if nav_label is not None:
        for R in (0.0, 0.1, 0.2999, 0.3, 0.45, 0.5, 0.65, 0.7, 0.9):
            assert seed.regime_label(R) == nav_label(R), R


def test_signal_lookup_from_git_history():
    idx = seed.SignalIndex(REPO)
    assert idx.error is None, idx.error
    # 2026-08-07: files of that era carry only `updated` → rule 2, the last nightly commit ≤ 23:59 ET
    sha, f, note = idx.find("2026-08-07")
    assert sha is not None and sha.startswith("634037e"), (sha, note)
    assert "last nightly commit" in note and f.get("session_date") is None and f["updated"].startswith("2026-08-07")
    rec, src, match, snote = idx.lookup("2026-08-07", "NVDA")
    assert src == "data/ticker_signals.json@634037e" and rec["ticker"] == "NVDA" and snote is None
    rec, src, match, snote = idx.lookup("2026-08-07", "ZZZZ")
    assert rec is None and src == "data/ticker_signals.json@634037e" and snote.startswith("no record for ZZZZ")
    # 2026-09-15: the file carries session_date → rule 1
    sha, f, note = idx.find("2026-09-15")
    assert f["session_date"] == "2026-09-15" and note.startswith("session_date == 2026-09-15"), note
    # before the first nightly commit there is nothing
    sha, f, note = idx.find("2026-05-20")
    assert sha is None and f is None and "no nightly" in note


def test_build_entry_shape_with_real_regime_and_signal():
    v = seed.PublishedVintage(DATA / "regime_daily_published.csv")
    idx = seed.SignalIndex(REPO)
    txn = {"date": "2026-08-07", "date_raw": "08/07/2026", "action_raw": "Buy", "category": "buy", "ticker": "NVDA",
           "quantity": 10, "price": 220.5, "amount": -2205.0, "fees": None}
    rec = seed.build_entry(txn, v, idx, "0" * 64, include_reinvest=False)
    assert list(rec)[:2] == ["session_date", "date"]
    assert rec["session_date"] == "2026-08-07" and rec["date"] == "2026-08-07" and rec["date_raw"] == "08/07/2026"
    assert rec["tier"] == "5_werner" and rec["source"] == "brokerage transactions" and rec["action"] == ["buy"]
    assert rec["ticker"] == "NVDA" and rec["quantity"] == 10 and rec["price"] == 220.5 and rec["amount"] == -2205.0
    assert rec["regime"] == "LOW RISK" and rec["R_full"] == 0.2467 and "regime_note" not in rec
    assert rec["signal"]["ticker"] == "NVDA" and rec["signal_source"] == "data/ticker_signals.json@634037e"
    assert rec["export_sha256"] == "0" * 64 and rec["action_raw"] == "Buy" and "logged_at" in rec
    # a dividend is never an entry
    assert seed.build_entry({**txn, "category": "dividend", "action_raw": "Qualified Dividend"}, v, None, "x", False) is None
    # reinvestment only with the flag, and flagged
    rv = {**txn, "category": "reinvest_shares", "action_raw": "Reinvest Shares", "quantity": 0.1509}
    assert seed.build_entry(rv, v, None, "x", False) is None
    r2 = seed.build_entry(rv, v, None, "x", True)
    assert r2["action"] == ["buy"] and r2["note"].startswith("dividend reinvestment") and r2["signal_note"].startswith("signal lookup disabled")


# ─── (2.2) idempotent seeding on a temp copy of the action log ───────────────────────────
def test_seed_actions_idempotent_on_temp_copy():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        make_inbox(tmp, SCHWAB_POS, SCHWAB_TXN)
        cp = ingest_cli(tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        sd = scratch_dir(tmp)
        export_sha = json.load(open(sd / "mapping.json"))["input_sha256"]
        log = tmp / "actions_copy.jsonl"
        if (DATA / "actions.jsonl").exists():
            shutil.copy(DATA / "actions.jsonl", log)             # a COPY of the real log — the real one is never touched
        else:
            log.write_text("")
        n0 = count_lines(log)

        def seed_cli(*extra):
            return run("seed_actions_from_transactions.py", "--scratch", str(tmp / "scratch"), "--actions", str(log),
                       "--no-signals", *extra, cwd=tmp)

        # dry run (default): nothing written
        cp = seed_cli()
        assert cp.returncode == 0 and "dry run: nothing written" in cp.stdout and count_lines(log) == n0, cp.stdout + cp.stderr
        # first write: one entry per BUY/SELL (3 in the fixture); non-trades counted, not seeded
        cp = seed_cli("--write")
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert count_lines(log) == n0 + 3 and "appended 3 entries" in cp.stdout
        assert "'reinvest_shares': 1" in cp.stdout and "'dividend': 2" in cp.stdout and "'interest': 1" in cp.stdout and "'transfer': 1" in cp.stdout
        # second write: idempotent
        cp = seed_cli("--write")
        assert cp.returncode == 0 and count_lines(log) == n0 + 3, cp.stdout + cp.stderr
        assert "already present from this export: 3" in cp.stdout and "new entries: 0" in cp.stdout
        ents = brokerage_entries(log)
        assert len(ents) == 3
        nvda, mu, anet = ents
        for e in ents:
            assert e["tier"] == "5_werner" and e["source"] == "brokerage transactions" and e["export_sha256"] == export_sha
            assert e["signal"] is None and e["signal_source"] is None
            for k in ("session_date", "date", "action", "ticker", "quantity", "price", "amount", "regime", "R_full", "logged_at"):
                assert k in e, k
        assert (nvda["date"], nvda["session_date"], nvda["action"], nvda["quantity"], nvda["price"]) == ("2026-08-07", "2026-08-07", ["buy"], 10, 220.5)
        assert nvda["regime"] == "LOW RISK" and nvda["R_full"] == 0.2467 and nvda["amount"] == -2205.0
        assert mu["date"] == "2026-08-08" and mu["session_date"] == "2026-08-10" and "not a session" in mu["session_note"]
        assert mu["action"] == ["sell"] and mu["quantity"] == 5 and mu["fees"] == 0.03 and mu["R_full"] == 0.258 and mu["regime"] == "LOW RISK"
        assert anet["date"] == "2026-08-27" and anet["date_raw"] == "08/28/2026 as of 08/27/2026" and anet["session_date"] == "2026-08-27"
        assert anet["R_full"] is None and anet["regime"] is None and anet["regime_note"].startswith("no_publish_reason:")
        # every appended line is valid JSON and the pre-existing lines are byte-identical
        if (DATA / "actions.jsonl").exists():
            assert log.read_bytes().startswith((DATA / "actions.jsonl").read_bytes())
        # --include-reinvest adds the reinvestment purchase once
        cp = seed_cli("--write", "--include-reinvest")
        assert count_lines(log) == n0 + 4 and "appended 1 entries" in cp.stdout, cp.stdout
        assert brokerage_entries(log)[-1]["note"].startswith("dividend reinvestment")
        cp = seed_cli("--write", "--include-reinvest")
        assert count_lines(log) == n0 + 4
        # the same trades from a DIFFERENT export hash: a trade is one fact — reported and SKIPPED by default
        # (lead's decision 2026-09-16); --append-seen-in-other-exports restores the per-hash behaviour
        parsed = sd / "transactions_parsed.csv"
        cp = run("seed_actions_from_transactions.py", "--parsed", str(parsed), "--export-sha256", "f" * 64,
                 "--actions", str(log), "--no-signals", "--write", cwd=tmp)
        assert count_lines(log) == n0 + 4 and "seen in an earlier export" in cp.stdout and "new entries: 0" in cp.stdout, cp.stdout + cp.stderr
        cp = run("seed_actions_from_transactions.py", "--parsed", str(parsed), "--export-sha256", "e" * 64,
                 "--actions", str(log), "--no-signals", "--write", "--append-seen-in-other-exports", cwd=tmp)
        assert count_lines(log) == n0 + 7 and "seen in an earlier export" in cp.stdout, cp.stdout + cp.stderr


def test_seed_from_inbox_and_fidelity_dialect():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inbox = make_inbox(tmp, FID_POS, FID_TXN)
        log = tmp / "actions.jsonl"
        log.write_text("")
        cp = run("seed_actions_from_transactions.py", "--inbox", str(inbox), "--actions", str(log), "--no-signals", "--write", cwd=tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        ents = brokerage_entries(log)
        assert [(e["session_date"], e["action"][0], e["ticker"], e["quantity"], e["price"]) for e in ents] == \
               [("2026-09-08", "buy", "GEV", 5, 990.0), ("2026-09-09", "sell", "BMNR", 25, 41.1)]
        assert ents[0]["R_full"] == 0.2233 and ents[0]["regime"] == "LOW RISK"
        assert ents[1]["R_full"] == 0.2555 and ents[1]["fees"] == 0.02 and ents[1]["amount"] == 1027.48
        expect = hashlib.sha256((inbox / "history.csv").read_bytes() + (inbox / "positions.csv").read_bytes()).hexdigest()
        assert ents[0]["export_sha256"] == expect
        assert not (tmp / "scratch").exists() and not (tmp / "data").exists()   # the inbox path writes nothing else


# ─── guard ───────────────────────────────────────────────────────────────────────────────
def test_zz_repository_data_and_inbox_untouched():
    assert _digest(DATA / "holdings.json") == _GUARD["holdings"]
    assert _digest(DATA / "actions.jsonl") == _GUARD["actions"]
    assert _listing(REPO / "inbox") == _GUARD["inbox"]
    assert _listing(REPO / "scratch") == _GUARD["scratch"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
