#!/usr/bin/env python3
"""
tests/test_realized_gains.py — order of 30 Sept 2026, C4/D3: the tolerant realized gain/loss parser
(scripts/ingest_realized_gains.py) and the operator's one-shot (scripts/ingest_inbox.py).

Run with the venv interpreter, either way (no pytest dependency):
    .venv/bin/python tests/test_realized_gains.py
    .venv/bin/python -m pytest tests/test_realized_gains.py

Every test works on TEMPORARY copies of the synthetic fixtures under tests/fixtures/brokerage/.
Nothing under data/, inbox/ or scratch/ of the repository is written — the final test asserts it.
The only read-only touch of the repository is a copy of data/regime_daily_published.csv into a
temp data dir (the seeding step needs a published vintage) and a read of data/realized_gains.json.
"""
from __future__ import annotations

import hashlib
import json
import re
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
import ingest_realized_gains as rg  # noqa: E402

SCHWAB = FIX / "schwab_like_realized_gains.csv"
FIDELITY = FIX / "fidelity_like_realized_gains.csv"
GENERIC = FIX / "generic_realized_gains.csv"
NO_TERM = FIX / "generic_realized_gains_no_term.csv"
BROKEN = FIX / "broken_realized_gains_unmappable_qty.csv"
SCHWAB_POS, SCHWAB_TXN = FIX / "schwab_like_positions.csv", FIX / "schwab_like_transactions.csv"
VINTAGE = DATA / "regime_daily_published.csv"


# ─── guard: the repository's served files, inbox and scratch must be untouched by this run ──
def _digest(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _listing(p: Path) -> list | None:
    return sorted(x.name for x in p.iterdir()) if p.exists() else None


_GUARD = {"realized": _digest(DATA / "realized_gains.json"), "holdings": _digest(DATA / "holdings.json"),
          "holdings_export": _digest(DATA / "holdings_export.json"), "actions": _digest(DATA / "actions.jsonl"),
          "data": _listing(DATA), "inbox": _listing(REPO / "inbox"), "scratch": _listing(REPO / "scratch")}


# ─── helpers ─────────────────────────────────────────────────────────────────────────────
def run(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(SCRIPTS / script), *args], capture_output=True, text=True, cwd=str(cwd))


def gains_cli(tmp: Path, *extra: str) -> subprocess.CompletedProcess:
    return run("ingest_realized_gains.py", "--inbox", str(tmp / "inbox"), "--scratch", str(tmp / "scratch"),
               "--data-dir", str(tmp / "data"), *extra, cwd=tmp)


def inbox_cli(tmp: Path, *extra: str) -> subprocess.CompletedProcess:
    return run("ingest_inbox.py", "--inbox", str(tmp / "inbox"), "--scratch", str(tmp / "scratch"),
               "--data-dir", str(tmp / "data"), "--no-signals", *extra, cwd=tmp)


def make_inbox(tmp: Path, **files: Path) -> Path:
    """Copies fixtures under the given (misleading) names — the jobs must find them by header sniffing."""
    inbox = tmp / "inbox"
    inbox.mkdir(exist_ok=True)
    for name, src in files.items():
        shutil.copy(src, inbox / name)
    return inbox


def scratch_dirs(tmp: Path, pattern: str = "realized_gains_*") -> list[Path]:
    return sorted((tmp / "scratch").glob(pattern)) if (tmp / "scratch").exists() else []


def by_ticker(blocks: list[dict]) -> dict:
    return {b["ticker"]: b for b in blocks}


def count_lines(p: Path) -> int:
    return sum(1 for line in p.read_text().splitlines() if line.strip())


# ─── helpers of the parser ───────────────────────────────────────────────────────────────
def test_term_symbol_and_header_helpers():
    nt = rg.normalize_term
    for txt in ("Short Term", "short-term", "ST", "S", "Short", "Covered Short Term"):
        assert nt(txt) == "short", txt
    for txt in ("Long Term", "LT", "L", "long", "Noncovered Long-Term"):
        assert nt(txt) == "long", txt
    for txt in ("", None, "Stock", "--", "Equity"):
        assert nt(txt) == "unknown", txt
    dt = rg.derive_term
    assert dt("2025-03-10", "2026-03-10") == "short"        # sold ON the first anniversary: not more than one year
    assert dt("2025-03-10", "2026-03-11") == "long"         # the day after: more than one year
    assert dt("2025-01-09", "2025-03-14") == "short" and dt("2024-02-29", "2025-03-01") == "long"
    assert dt(None, "2026-01-01") == "unknown" and dt("2026-01-01", None) == "unknown"
    assert rg.lot_symbol(" zqx ") == "ZQX" and rg.lot_symbol("SPAXX**") == "SPAXX"
    assert rg.lot_symbol("ZQX  09/19/2025  100.00 C") == "ZQX 09/19/2025 100.00 C"   # options keep readable spacing
    assert rg.norm_header("Gain/Loss ($)") == "gain loss" and rg.norm_header("Gain/Loss (%)") == "gain loss pct"
    assert rg.money(Decimal("1.005")) in (1.0, 1.01) and rg.money(None) is None and rg.money(Decimal("42453.34")) == 42453.34
    # the synonym table: required fields, and no header string claimed by two fields except the wash-sale pair
    assert [c for c, (req, _) in rg.REALIZED_FIELDS.items() if req] == ["symbol", "close_date", "quantity", "proceeds", "cost_basis"]
    seen: dict[str, str] = {}
    for canon, (_r, syns) in rg.REALIZED_FIELDS.items():
        for s in syns:
            assert s not in seen or {seen[s], canon} == {"wash_sale", "wash_sale_flag"}, (s, seen.get(s), canon)
            seen.setdefault(s, canon)


# ─── the three dialects ──────────────────────────────────────────────────────────────────
def test_schwab_dialect_maps_and_totals():
    res = rg.ingest(None, file=SCHWAB)
    assert res.complete and not res.problems, (res.problems, res.realized and res.realized.unmapped_required)
    pf = res.realized
    assert pf.header_index == 2 and pf.mapping == {
        "symbol": "Symbol", "close_date": "Closed Date", "open_date": "Opened Date", "quantity": "Quantity",
        "proceeds": "Proceeds", "cost_basis": "Cost Basis (CB)", "gain_loss": "Gain/Loss ($)",
        "short_term_gain_loss": "Short Term Gain/Loss", "long_term_gain_loss": "Long Term Gain/Loss",
        "wash_sale": "Disallowed Loss", "wash_sale_flag": "Wash Sale?", "proceeds_per_share": "Proceeds Per Share",
        "cost_per_share": "Cost Per Share", "gain_loss_pct": "Gain/Loss (%)", "description": "Name"}, pf.mapping
    assert pf.unmatched_headers == [] and pf.unmapped_required == []
    assert pf.stamp["date"] == "2026-09-30" and pf.stamp["datetime"] is None
    assert len(pf.lots) == 10 and [s["reason"] for s in pf.skipped] == ["total/summary row", "free-text line (preamble/footer/disclaimer)"]
    assert pf.term_basis.startswith("short-term / long-term columns")
    rec = res.record
    assert rec["cadence"] == "on_change" and rec["source"] == "brokerage realized gain/loss export" and rec["pending_export"] is False
    assert rec["as_of"] == "2026-09-30" and rec["as_of_basis"] == "export stamp date" and rec["note"] == "descriptive; no tax computation"
    assert rec["input_file"] == {"name": SCHWAB.name, "bytes": SCHWAB.stat().st_size}
    assert rec["input_sha256"] == hashlib.sha256(SCHWAB.read_bytes()).hexdigest()
    assert sorted(rec["years"]) == ["2025", "2026"]
    y25, y26 = rec["years"]["2025"], rec["years"]["2026"]
    # the order's 2025 total: $42,453.34 net, all short-term
    assert (y25["net"], y25["short_term"], y25["long_term"], y25["unknown_term"], y25["n_lots"]) == (42453.34, 42453.34, 0.0, 0.0, 5)
    assert y25["wash_sale_disallowed"] == 0.0 and y25["year_to_date"] is False and "through" not in y25
    assert [p["ticker"] for p in y25["by_position"]] == ["QWRT", "ZQX", "VBNM", "HYUI", "PLKJ"]     # |gain_loss| desc
    q = by_ticker(y25["by_position"])["QWRT"]
    assert q == {"ticker": "QWRT", "n_lots": 1, "quantity": 154.6717, "proceeds": 92803.02, "cost_basis": 61868.68,
                 "gain_loss": 30934.34, "short_term": 30934.34, "long_term": 0.0, "wash_sale_disallowed": 0.0, "n_wash_sale_lots": 0}
    assert by_ticker(y25["by_position"])["PLKJ"]["gain_loss"] == -3100.0
    # 2026 year to date: long-term lots held > 1 year, a wash sale, a fractional lot
    assert (y26["net"], y26["short_term"], y26["long_term"], y26["n_lots"]) == (10040.5, 1440.5, 8600.0, 5)
    assert y26["year_to_date"] is True and y26["through"] == "2026-09-30" and y26["wash_sale_disallowed"] == 426.0
    b26 = by_ticker(y26["by_position"])
    assert b26["ZQX"]["long_term"] == 6000.0 and b26["ZQX"]["short_term"] == 0.0
    assert b26["PLKJ"]["quantity"] == 10.25 and b26["PLKJ"]["gain_loss"] == 61.5
    assert rec["totals_all_years"]["net"] == 52493.84 and rec["totals_all_years"]["n_lots"] == 10
    allpos = by_ticker(rec["totals_by_position_all_years"])
    assert allpos["ZQX"] == {"ticker": "ZQX", "n_lots": 2, "quantity": 150, "proceeds": 39550.0, "cost_basis": 27000.0,
                             "gain_loss": 12550.0, "short_term": 6550.0, "long_term": 6000.0, "wash_sale_disallowed": 0.0, "n_wash_sale_lots": 0}
    assert [p["ticker"] for p in rec["totals_by_position_all_years"]][0] == "QWRT"
    assert rec["mapping"]["chosen"] == pf.mapping and rec["mapping"]["unmatched_headers"] == [] and rec["mapping"]["header_row"] == 3
    # fractional quantities survive as written in the lots and the JSON text
    lot = next(l for l in pf.lots if l["ticker"] == "QWRT")
    assert lot["quantity"] == Decimal("154.6717") and lot["term"] == "short" and lot["open_date"] == "2025-06-02"
    assert '"quantity": 154.6717' in json.dumps(rec)


def test_fidelity_dialect_maps_and_totals():
    res = rg.ingest(None, file=FIDELITY)
    assert res.complete and not res.problems
    pf = res.realized
    assert pf.mapping == {"symbol": "Symbol", "close_date": "Date Sold", "open_date": "Date Acquired", "quantity": "Quantity",
                          "proceeds": "Proceeds", "cost_basis": "Cost Basis", "short_term_gain_loss": "Short Term Gain/Loss",
                          "long_term_gain_loss": "Long Term Gain/Loss", "wash_sale": "Wash Sale Loss Disallowed",
                          "description": "Description"}, pf.mapping
    assert "gain_loss" not in pf.mapping and pf.unmapped_required == []          # ST + LT columns satisfy the gain requirement
    assert pf.stamp["datetime"] == "2026-09-30T17:02:00-04:00"
    rec = res.record
    assert rec["exported_at"] == "2026-09-30T17:02:00-04:00" and rec["exported_at_basis"].startswith("export stamp")
    y25, y26 = rec["years"]["2025"], rec["years"]["2026"]
    assert (y25["net"], y25["short_term"], y25["long_term"], y25["n_lots"]) == (600.0, 600.0, 0.0, 1)
    assert (y26["net"], y26["short_term"], y26["long_term"], y26["n_lots"], y26["wash_sale_disallowed"]) == (499.0, -301.0, 800.0, 4, 341.0)
    b = by_ticker(y26["by_position"])
    assert b["LMNO"]["n_lots"] == 2 and b["LMNO"]["quantity"] == 23 and b["LMNO"]["long_term"] == 450.0 and b["LMNO"]["short_term"] == 0.0
    assert b["GHJK"]["quantity"] == 100.5 and b["GHJK"]["short_term"] == -301.0 and b["GHJK"]["wash_sale_disallowed"] == 301.0
    terms = {(l["ticker"], l["close_date"]): l["term"] for l in pf.lots}
    assert terms[("RRTQ", "2026-09-10")] == "long" and terms[("GHJK", "2026-02-20")] == "short"
    assert terms[("LMNO", "2026-05-06")] == "short"          # a $0.00 short-term cell is still the short-term column


def test_generic_dialect_maps_and_totals():
    res = rg.ingest(None, file=GENERIC)                      # BOM, preamble, parenthesised negatives, a Term column
    assert res.complete and not res.problems
    pf = res.realized
    assert pf.mapping == {"symbol": "Ticker", "close_date": "Sale Date", "open_date": "Purchase Date", "quantity": "Qty",
                          "proceeds": "Sales Proceeds", "cost_basis": "Total Cost", "gain_loss": "Gain/Loss", "term": "Term",
                          "wash_sale": "Wash Sale"}, pf.mapping
    assert pf.header_index == 2 and pf.term_basis == "term column 'Term'"
    assert pf.stamp["line"] == "Generated 2026-09-30 15:45 ET" and pf.stamp["datetime"] == "2026-09-30T15:45:00-04:00"
    assert [s["reason"] for s in pf.skipped] == ["total/summary row", "free-text line (preamble/footer/disclaimer)"]
    rec = res.record
    y25, y26 = rec["years"]["2025"], rec["years"]["2026"]
    assert (y25["net"], y25["short_term"], y25["long_term"], y25["n_lots"]) == (200.0, -100.0, 300.0, 2)
    assert (y26["net"], y26["short_term"], y26["long_term"], y26["n_lots"], y26["wash_sale_disallowed"]) == (10.0, -30.0, 40.0, 3, 80.0)
    lots = {(l["ticker"], l["year"]): l for l in pf.lots}
    assert lots[("BBYY", "2025")]["quantity"] == Decimal("3.5") and lots[("BBYY", "2025")]["gain_loss"] == Decimal("-100.00")
    assert lots[("BBYY", "2025")]["term"] == "short" and lots[("AAXX", "2025")]["term"] == "long"     # 'ST' and 'Long Term'
    assert lots[("CCZZ", "2026")]["wash_sale_flag"] is True and lots[("CCZZ", "2026")]["wash_sale_disallowed"] == Decimal("80.00")
    assert [p["ticker"] for p in y26["by_position"]] == ["CCZZ", "AAXX", "DDWW"]


# ─── term derivation, unknown term ───────────────────────────────────────────────────────
def test_term_derived_from_dates_and_unknown_bucket():
    res = rg.ingest(None, file=NO_TERM)
    assert res.complete and not res.problems
    pf = res.realized
    assert "term" not in pf.mapping and pf.term_basis.startswith("derived from 'Date Acquired' / 'Date Sold' (held > 1 year = long)")
    lots = {(l["ticker"], l["close_date"]): l for l in pf.lots}
    assert lots[("EEVV", "2026-03-10")]["term"] == "short" and lots[("EEVV", "2026-03-11")]["term"] == "long"   # the anniversary boundary
    assert lots[("GGTT", "2025-06-02")]["term"] == "short"
    fu = lots[("FFUU", "2026-05-05")]
    assert fu["term"] == "unknown" and fu["open_date"] is None and "Various" in fu["notes"]
    y26 = res.record["years"]["2026"]
    assert (y26["net"], y26["short_term"], y26["long_term"], y26["unknown_term"]) == (270.0, 100.0, 100.0, 70.0)   # never folded
    assert y26["wash_sale_disallowed"] is None                                     # no wash-sale column in this export
    assert by_ticker(y26["by_position"])["FFUU"]["unknown_term"] == 70.0
    assert any("term 'unknown'" in w for w in pf.warnings)
    assert res.record["as_of_basis"].startswith("ET ingest date")                 # no stamp line in this export
    # neither a term column nor an acquired date: every lot is term unknown, and the report says so
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.csv"
        p.write_text("Symbol,Date Sold,Quantity,Proceeds,Cost Basis,Gain/Loss\nHHSS,01/05/2026,1,10.00,5.00,5.00\nHHSS,02/05/2026,2,20.00,30.00,-10.00\n")
        r2 = rg.ingest(None, file=p)
        assert r2.complete and r2.realized.term_basis == "unknown: no term column and no acquired date in the export"
        y = r2.record["years"]["2026"]
        assert (y["net"], y["short_term"], y["long_term"], y["unknown_term"]) == (-5.0, 0.0, 0.0, -5.0)
        # a 'Type' column that is a security type, not a term: falls back to the dates and says so
        p2 = Path(td) / "y.csv"
        p2.write_text("Symbol,Type,Date Acquired,Date Sold,Quantity,Proceeds,Cost Basis,Gain/Loss\n"
                      "HHSS,Stock,01/05/2024,01/06/2026,1,10.00,5.00,5.00\nHHSS,Stock,01/05/2026,02/05/2026,2,20.00,30.00,-10.00\n")
        r3 = rg.ingest(None, file=p2)
        assert r3.realized.mapping["term"] == "Type" and r3.realized.term_basis.startswith("derived from 'Date Acquired' / 'Date Sold'")
        y = r3.record["years"]["2026"]
        assert (y["short_term"], y["long_term"], y["unknown_term"]) == (-10.0, 5.0, 0.0)


# ─── the 2025 reconciliation ─────────────────────────────────────────────────────────────
def test_reconciliation_match_and_mismatch():
    rc = rg.ingest(None, file=SCHWAB).record["reconciliation"]
    assert rc["match"] is True and rc["operator_reported_2025_net"] == 42453.34 and rc["export_2025_net"] == 42453.34
    assert rc["difference"] == 0.0 and rc["export_2025_long_term"] == 0.0 and rc["note"] == "export 2025 net equals the operator-reported total"
    rc = rg.ingest(None, file=FIDELITY).record["reconciliation"]
    assert rc["match"] is False and rc["export_2025_net"] == 600.0 and rc["difference"] == -41853.34
    assert rc["note"].startswith("MISMATCH: export 2025 net 600.00 vs operator-reported 42453.34 (difference -41853.34)")
    # an export without 2025 lots cannot confirm the figure — said so, not a silent match
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.csv"
        p.write_text("Symbol,Date Sold,Date Acquired,Quantity,Proceeds,Cost Basis,Gain/Loss\nHHSS,01/05/2026,01/02/2026,1,10.00,5.00,5.00\n")
        rc = rg.ingest(None, file=p).record["reconciliation"]
        assert rc["match"] is False and rc["export_2025_net"] is None and "no lots closed in 2025" in rc["note"]
        # the override for a different operator figure
        rc = rg.ingest(None, file=SCHWAB, expect_2025_net=Decimal("42000.00")).record["reconciliation"]
        assert rc["match"] is False and rc["difference"] == 453.34
        # the printed report warns on a mismatch and confirms a match
        tmp = Path(td)
        make_inbox(tmp, **{"positions_export.csv": FIDELITY})
        cp = gains_cli(tmp)
        assert cp.returncode == 0 and "WARNING RECONCILIATION 2025: MISMATCH" in cp.stdout, cp.stdout + cp.stderr
        shutil.rmtree(tmp / "inbox")
        make_inbox(tmp, **{"whatever.csv": SCHWAB})
        cp = gains_cli(tmp)
        assert cp.returncode == 0 and "RECONCILIATION 2025: export net 42,453.34 = operator-reported 42,453.34 — MATCH" in cp.stdout, cp.stdout


# ─── wash sales: reported, never netted ──────────────────────────────────────────────────
def test_wash_sales_reported_not_netted():
    rec = rg.ingest(None, file=SCHWAB).record
    y26 = rec["years"]["2026"]
    nnop = by_ticker(y26["by_position"])["NNOP"]
    assert nnop["gain_loss"] == -426.0 and nnop["wash_sale_disallowed"] == 426.0 and nnop["n_wash_sale_lots"] == 1
    assert y26["net"] == 10040.5 == round(y26["short_term"] + y26["long_term"], 2)     # the loss stays in net; nothing netted
    assert y26["wash_sale_disallowed"] == 426.0 and y26["n_wash_sale_lots"] == 1
    ws = rec["wash_sales"]
    assert ws == {"amount_column": "Disallowed Loss", "flag_column": "Wash Sale?", "n_lots_flagged": 1, "disallowed_total": 426.0,
                  "gain_check": {"n_lots_checked": 10, "n_mismatch": 0, "n_explained_by_wash_sale": 0},
                  "note": "reported separately; gain_loss is as the export states it — nothing is netted by this job"}
    # Fidelity: one lot's gain/loss is already wash-adjusted ($0.00 with $40 disallowed) — counted, explained, not changed
    res = rg.ingest(None, file=FIDELITY)
    ws = res.record["wash_sales"]
    assert ws["n_lots_flagged"] == 2 and ws["disallowed_total"] == 341.0
    assert ws["gain_check"] == {"n_lots_checked": 5, "n_mismatch": 1, "n_explained_by_wash_sale": 1}
    lmno = next(l for l in res.realized.lots if l["ticker"] == "LMNO" and l["close_date"] == "2026-05-06")
    assert lmno["gain_loss"] == Decimal("0.00") and lmno["wash_sale_disallowed"] == Decimal("40.00")
    assert lmno["gain_check"].startswith("proceeds − cost = -40.00 vs gain/loss 0.00: differs by the disallowed wash-sale amount")
    assert any("wash-adjusted" in w for w in res.realized.warnings)
    assert res.record["years"]["2026"]["net"] == 499.0


# ─── the CLI: sniffing, dry run, --write, exit codes ─────────────────────────────────────
def test_cli_sniffs_inbox_and_dry_run_writes_nothing_served():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # the realized-gains export saved as positions.csv, next to a real positions and a transactions export
        make_inbox(tmp, **{"positions.csv": SCHWAB, "realized_gains.csv": SCHWAB_POS, "history.csv": SCHWAB_TXN})
        (tmp / "data").mkdir()
        cp = gains_cli(tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert list((tmp / "data").iterdir()) == []                              # dry run: nothing served
        assert "[realized gain/loss] positions.csv" in cp.stdout and "mapping chosen" in cp.stdout
        assert "[not a realized gain/loss export (ignored)] realized_gains.csv" in cp.stdout
        assert "[not a realized gain/loss export (ignored)] history.csv" in cp.stdout
        assert "dry run: nothing written under data/" in cp.stdout
        sd = scratch_dirs(tmp)
        assert len(sd) == 1 and {p.name for p in sd[0].iterdir()} == {"realized_gains_candidate.json", "mapping.json", "realized_lots.csv"}
        m = json.load(open(sd[0] / "mapping.json"))
        assert m["complete"] is True and m["input_file"]["name"] == "positions.csv"
        assert m["realized_gains"]["mapping"]["close_date"] == "Closed Date"
        assert sorted(f["file"] for f in m["other_files"]) == ["history.csv", "realized_gains.csv"]
        cand = json.load(open(sd[0] / "realized_gains_candidate.json"))
        assert cand["years"]["2025"]["net"] == 42453.34 and cand["reconciliation"]["match"] is True
        assert count_lines(sd[0] / "realized_lots.csv") == 11                     # header + 10 lots


def test_cli_write_replaces_served_file_in_temp_data_dir():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        make_inbox(tmp, **{"export (3).csv": SCHWAB})
        # first the operator-report seed the order asks for, then the export replaces it entirely
        cp = run("ingest_realized_gains.py", "--seed-operator-report", "--write", "--data-dir", str(tmp / "data"), cwd=tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        served = tmp / "data" / "realized_gains.json"
        seed = json.load(open(served))
        assert seed["pending_export"] is True and seed["source"] == "operator report, pending export confirmation"
        cp = gains_cli(tmp, "--write")
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert sorted(x.name for x in (tmp / "data").iterdir()) == ["realized_gains.json"]
        h = json.load(open(served))
        for k in ("cadence", "as_of", "source", "exported_at", "input_sha256", "input_file", "ingested_at", "years",
                  "totals_by_position_all_years", "mapping", "note", "reconciliation", "pending_export"):
            assert k in h, k
        assert h["pending_export"] is False and h["source"] == "brokerage realized gain/loss export" and h["as_of"] == "2026-09-30"
        assert h["input_file"] == {"name": "export (3).csv", "bytes": SCHWAB.stat().st_size}
        assert h["input_sha256"] == hashlib.sha256(SCHWAB.read_bytes()).hexdigest()
        assert h["years"]["2025"]["net"] == 42453.34 and h["years"]["2026"]["year_to_date"] is True
        assert h["reconciliation"] == {"operator_reported_2025_net": 42453.34, "operator_reported_2025_all_short_term": True,
                                       "export_2025_net": 42453.34, "export_2025_short_term": 42453.34, "export_2025_long_term": 0.0,
                                       "difference": 0.0, "match": True, "note": "export 2025 net equals the operator-reported total"}
        assert "basis" not in h["years"]["2025"]                                   # the seed's placeholder fields are gone
        assert "served: wrote" in cp.stdout and "2025: net 42,453.34" in cp.stdout
        # --dry-run overrides --write
        shutil.rmtree(tmp / "data")
        cp = gains_cli(tmp, "--write", "--dry-run")
        assert cp.returncode == 0 and not (tmp / "data").exists(), cp.stdout + cp.stderr


def test_unmapped_required_column_exits_2_and_writes_nothing_served():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        make_inbox(tmp, **{"gains.csv": BROKEN})
        (tmp / "data").mkdir()
        cp = gains_cli(tmp, "--write")
        assert cp.returncode == 2, cp.stdout + cp.stderr
        assert list((tmp / "data").iterdir()) == []                              # nothing served, even with --write
        assert "UNMAPPED REQUIRED: ['quantity']" in cp.stdout and "Shares Sold Amt" in cp.stdout
        assert "nothing served written (exit 2)" in cp.stderr
        sd = scratch_dirs(tmp)
        assert len(sd) == 1
        m = json.load(open(sd[0] / "mapping.json"))
        assert m["complete"] is False and m["realized_gains"]["unmapped_required"] == ["quantity"]
        assert m["realized_gains"]["unmatched_headers"] == ["Shares Sold Amt"]
        cand = json.load(open(sd[0] / "realized_gains_candidate.json"))
        assert cand["_unmapped_required"] == ["quantity"] and cand["years"]["2025"]["net"] == 3450.0
        assert [p["quantity"] for p in cand["years"]["2025"]["by_position"]] == [None, None]
        # a missing gain column with no short/long pair is required too
        p = tmp / "inbox" / "gains.csv"
        p.write_text("Symbol,Date Sold,Quantity,Proceeds,Cost Basis,Net G/L\nHHSS,01/05/2026,1,10.00,5.00,5.00\n")
        cp = gains_cli(tmp, "--write")
        assert cp.returncode == 2 and "Net G/L" in cp.stdout and "gain_loss (a gain/loss column" in cp.stdout, cp.stdout + cp.stderr


def test_no_file_or_ambiguous_exits_1():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "inbox").mkdir()
        cp = gains_cli(tmp)
        assert cp.returncode == 1 and "no .csv files" in cp.stderr and not scratch_dirs(tmp), cp.stdout + cp.stderr
        make_inbox(tmp, **{"positions.csv": SCHWAB_POS, "history.csv": SCHWAB_TXN})    # no realized-gains export at all
        cp = gains_cli(tmp)
        assert cp.returncode == 1 and "no realized gain/loss CSV recognised" in cp.stderr and not scratch_dirs(tmp), cp.stdout + cp.stderr
        make_inbox(tmp, **{"a.csv": SCHWAB, "b.csv": FIDELITY})
        cp = gains_cli(tmp)
        assert cp.returncode == 1 and "ambiguous: more than one realized gain/loss CSV: a.csv, b.csv" in cp.stderr, cp.stdout + cp.stderr
        cp = run("ingest_realized_gains.py", "--inbox", str(tmp / "nowhere"), "--scratch", str(tmp / "scratch"), cwd=tmp)
        assert cp.returncode == 1 and "inbox not found" in cp.stderr


# ─── the operator-report seed ────────────────────────────────────────────────────────────
def test_seed_operator_report_matches_the_order():
    rec = rg.operator_report_record()
    assert rec["source"] == "operator report, pending export confirmation" and rec["as_of"] == "2026-09-30"
    assert rec["pending_export"] is True and rec["cadence"] == "on_change" and rec["note"] == "descriptive; no tax computation"
    assert rec["years"]["2025"] == {"net": 42453.34, "short_term": 42453.34, "long_term": 0.0, "n_lots": None, "by_position": [],
                                    "basis": "operator-reported total; per-position detail pending the export"}
    assert rec["years"]["2026"] == {"net": None, "short_term": None, "long_term": None, "year_to_date": True,
                                    "basis": "pending the realized-gains export"}
    assert rec["exported_at"] is None and rec["input_sha256"] is None and rec["input_file"] is None and rec["mapping"] is None
    assert rec["reconciliation"]["operator_reported_2025_net"] == 42453.34 and rec["reconciliation"]["match"] is None
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cp = run("ingest_realized_gains.py", "--seed-operator-report", "--data-dir", str(tmp / "data"), cwd=tmp)
        assert cp.returncode == 0 and not (tmp / "data").exists() and "dry run" in cp.stdout      # dry run by default
        cp = run("ingest_realized_gains.py", "--seed-operator-report", "--write", "--data-dir", str(tmp / "data"), cwd=tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        on_disk = json.load(open(tmp / "data" / "realized_gains.json"))
        on_disk.pop("ingested_at")
        rec.pop("ingested_at")
        assert on_disk == rec
    # the served file in the repository (read-only): the seed until the export arrives, the export's record after
    served = DATA / "realized_gains.json"
    if served.exists():
        h = json.load(open(served))
        if h.get("pending_export"):
            assert h["source"] == "operator report, pending export confirmation" and h["years"]["2025"]["net"] == 42453.34
        else:
            assert h["source"] == "brokerage realized gain/loss export" and "reconciliation" in h


# ─── the one-shot ────────────────────────────────────────────────────────────────────────
def _one_shot_setup(tmp: Path) -> Path:
    """A temp inbox with all three exports under misleading names, and a temp data dir holding a COPY of
    the published vintage (the seeding step needs it; the repository file is only read)."""
    inbox = make_inbox(tmp, **{"positions.csv": SCHWAB, "realized.csv": SCHWAB_POS, "gains.csv": SCHWAB_TXN})
    (tmp / "data").mkdir()
    shutil.copy(VINTAGE, tmp / "data" / "regime_daily_published.csv")
    return inbox


def test_ingest_inbox_dry_run_moves_nothing():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inbox = _one_shot_setup(tmp)
        before = sorted(p.name for p in inbox.iterdir())
        cp = inbox_cli(tmp, "--dry-run")
        assert cp.returncode == 0, cp.stdout + cp.stderr
        out = cp.stdout
        assert "positions.csv" in out and "→ realized_gains" in out and "→ positions" in out and "→ transactions" in out
        assert "ingest_brokerage.py" in out and "seed_actions_from_transactions.py" in out and "ingest_realized_gains.py" in out
        cmds = [l for l in out.splitlines() if l.strip().startswith("$ ")]                          # the three subprocess calls
        assert len(cmds) == 3 and not any("--write" in c for c in cmds), cmds                         # called without --write
        assert all(str(REPO / ".venv" / "bin" / "python") in c or PY in c for c in cmds), cmds          # the venv interpreter
        assert "dry run: nothing moved" in out and "steps: ran 3, skipped 0, failed 0 · dry run" in out
        assert sorted(p.name for p in inbox.iterdir()) == before and not (inbox / "archive").exists()
        assert sorted(x.name for x in (tmp / "data").iterdir()) == ["regime_daily_published.csv"]         # nothing served
        assert "[absent   ]" in out and "[changed" not in out and "[created" not in out
        assert scratch_dirs(tmp, "ingest_*") and scratch_dirs(tmp, "realized_gains_*")                     # best guesses only


def test_ingest_inbox_write_run_serves_and_archives():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inbox = _one_shot_setup(tmp)
        cp = inbox_cli(tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        out = cp.stdout
        assert sorted(x.name for x in (tmp / "data").iterdir()) == \
               ["actions.jsonl", "holdings.json", "holdings_export.json", "realized_gains.json", "regime_daily_published.csv"]
        assert count_lines(tmp / "data" / "actions.jsonl") == 3
        h = json.load(open(tmp / "data" / "holdings.json"))
        assert h["source"] == "brokerage export" and [x["ticker"] for x in h["holdings"]] == ["MU", "NVDA", "ANET"]
        g = json.load(open(tmp / "data" / "realized_gains.json"))
        assert g["years"]["2025"]["net"] == 42453.34 and g["input_file"]["name"] == "positions.csv"
        # every processed export moved to inbox/archive/<ET timestamp>/; the inbox itself is empty
        assert [p.name for p in inbox.iterdir()] == ["archive"]
        arch = list((inbox / "archive").iterdir())
        assert len(arch) == 1 and len(arch[0].name) == 15 and arch[0].name[8] == "T"
        assert sorted(p.name for p in arch[0].iterdir()) == ["gains.csv", "positions.csv", "realized.csv"]
        assert "moved positions.csv" in out and "steps: ran 3, skipped 0, failed 0" in out
        for n in ("holdings.json", "holdings_export.json", "actions.jsonl", "realized_gains.json"):
            assert f"[created  ] {tmp / 'data' / n}" in out, n
        assert "(3 lines, +3)" in out
        # second run, same files re-dropped: idempotent seeding, holdings unchanged in content, realized rewritten
        make_inbox(tmp, **{"positions.csv": SCHWAB, "realized.csv": SCHWAB_POS, "gains.csv": SCHWAB_TXN})
        cp = inbox_cli(tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert count_lines(tmp / "data" / "actions.jsonl") == 3 and "[unchanged] " + str(tmp / "data" / "actions.jsonl") in cp.stdout
        assert len(list((inbox / "archive").iterdir())) == 2


def test_ingest_inbox_tolerates_missing_file_types_and_keeps_failed_files():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inbox = make_inbox(tmp, **{"only_gains.csv": FIDELITY})                    # no positions, no transactions
        (tmp / "data").mkdir()
        cp = inbox_cli(tmp)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        out = cp.stdout
        assert "skipped — no positions CSV in the inbox" in out and "skipped — ingest_brokerage.py did not complete" in out
        assert "steps: ran 1, skipped 2, failed 0" in out
        assert sorted(x.name for x in (tmp / "data").iterdir()) == ["realized_gains.json"]
        assert [p.name for p in inbox.iterdir()] == ["archive"]
        # a broken realized-gains export (exit 2) stays in the inbox; positions + transactions still go through
        make_inbox(tmp, **{"broken.csv": BROKEN, "p.csv": SCHWAB_POS, "t.csv": SCHWAB_TXN})
        cp = inbox_cli(tmp)                                                       # vintage missing in this data dir: seeding skipped
        assert cp.returncode == 2, cp.stdout + cp.stderr
        out = cp.stdout
        assert "published regime vintage not found" in out, out
        assert re.search(r"ingest_realized_gains\.py\s+FAILED\s+exit 2", out) and re.search(r"ingest_brokerage\.py\s+ran\s+exit 0", out), out
        assert "steps: ran 1, skipped 1, failed 1" in out
        assert sorted(p.name for p in inbox.iterdir()) == ["archive", "broken.csv"] and "left in the inbox: broken.csv" in out
        assert (tmp / "data" / "holdings.json").exists()
        # two realized-gains exports: ambiguous, that step skipped, exit 1, nothing moved for it
        (inbox / "broken.csv").unlink()
        make_inbox(tmp, **{"a.csv": SCHWAB, "b.csv": FIDELITY})
        cp = inbox_cli(tmp)
        assert cp.returncode == 1 and "ambiguous: more than one realized_gains CSV: a.csv, b.csv" in cp.stdout, cp.stdout + cp.stderr
        assert sorted(p.name for p in inbox.iterdir()) == ["a.csv", "archive", "b.csv"]
        # an empty inbox
        (inbox / "a.csv").unlink()
        (inbox / "b.csv").unlink()
        cp = inbox_cli(tmp)
        assert cp.returncode == 1 and "nothing to do" in cp.stderr


# ─── guard ───────────────────────────────────────────────────────────────────────────────
def test_zz_repository_data_inbox_and_scratch_untouched():
    assert _digest(DATA / "realized_gains.json") == _GUARD["realized"]
    assert _digest(DATA / "holdings.json") == _GUARD["holdings"]
    assert _digest(DATA / "holdings_export.json") == _GUARD["holdings_export"]
    assert _digest(DATA / "actions.jsonl") == _GUARD["actions"]
    assert _listing(DATA) == _GUARD["data"]
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
