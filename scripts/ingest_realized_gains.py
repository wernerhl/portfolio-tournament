#!/usr/bin/env python3
"""
ingest_realized_gains.py — order of 30 Sept 2026, items C4 (the realized-gains half of the tolerant
brokerage parser) and D3 (realized gain and loss by position and by year, short- and long-term).

The order, quoted verbatim:

    "C4. Holdings ingestion (still pending from the fix-and-merge order). The account is at a
    brokerage that exports positions and realized gains as CSV. Complete the tolerant parser
    against that export; the operator drops the files in inbox/."
    "D3. Realized gains. From the realized-gains export: realized gain and loss by position and
    by year, short-term and long-term, with the 2025 total ($42,453.34 net, all short-term) and
    2026 year to date. Descriptive; no tax computation."

Usage
    ingest_realized_gains.py [--inbox inbox | --file FILE] [--write] [--dry-run]
                             [--data-dir data] [--scratch scratch] [--expect-2025-net 42453.34]
    ingest_realized_gains.py --seed-operator-report [--write] [--data-dir data]

  * The realized gain/loss CSV is found in inbox/ by HEADER SNIFFING (a header row that maps a
    symbol column, a closing/sale date column and at least one money column — proceeds, cost
    basis or gain/loss), never by file name.  Positions and transactions exports sitting in the
    same inbox are listed and ignored (they have no closing-date column).
  * Without --write (or with --dry-run) nothing under data/ is touched.  The full best guess goes
    to scratch/realized_gains_<ET timestamp>/ : realized_gains_candidate.json, mapping.json (the
    chosen header mapping, the unmatched headers, the input hash), realized_lots.csv (one row per
    closed lot as parsed).
  * With --write AND a complete mapping, data/realized_gains.json is written as well, replacing
    whatever was there (the operator-report seed included).
  * Exit codes, as ingest_brokerage.py: 0 ok · 2 a required column could not be mapped (nothing
    served is written; the best guess and the unmatched headers are reported) · 1 anything else
    (no CSV recognised, ambiguous files, unreadable input).
  * --seed-operator-report writes the served file from the order's stated figures alone (2025 net
    $42,453.34, all short-term; 2026 pending) with source "operator report, pending export
    confirmation" and pending_export true — the placeholder the export later replaces.

Header detection is the synonym table REALIZED_FIELDS below: extend it by adding strings.  Headers
are normalised (lower-case, '&' → 'and', '%' → 'pct', punctuation → space, collapsed) and matched
EXACTLY against the synonyms, most-preferred synonym first.

Term (short/long) per lot, in this order of preference:
    1. separate short-term / long-term gain-loss columns (Schwab, Fidelity): whichever is non-empty;
    2. a term column ('Term', 'Holding Period', 'LT/ST', ...);
    3. derived from the acquired and closed dates: held MORE than one year = long (IRS Pub 550:
       sold on the first anniversary is short; the day after is long) — the report says so;
    4. otherwise "unknown" (carried in its own bucket, never silently folded into short or long).

Wash sales are reported SEPARATELY (wash_sale_disallowed per year / position, the flagged lot
count) and never netted into gain_loss by this job; gain_loss is what the export states per lot.
Each lot's proceeds − cost basis is checked against its gain/loss and the differences are
counted — those equal to the lot's disallowed amount show the export's gain/loss is already
wash-adjusted; the count is reported, nothing is changed.

Served output, data/realized_gains.json:
    cadence "on_change" · as_of (the export's stamp date, else the ET ingest date) · source
    "brokerage realized gain/loss export" · exported_at (the export stamp's time if present, else
    the file's mtime) · input_sha256 · input_file {name, bytes} · ingested_at · pending_export
    false · years {"2025": {net, short_term, long_term, unknown_term, n_lots,
    wash_sale_disallowed, by_position [{ticker, n_lots, quantity, proceeds, cost_basis,
    gain_loss, short_term, long_term}] sorted by |gain_loss| desc, year_to_date}, "2026": {...
    year_to_date true, through}} · totals_all_years · totals_by_position_all_years · term_basis ·
    wash_sales · reconciliation {operator_reported_2025_net 42453.34, export_2025_net, match} ·
    mapping {header_row, chosen, unmatched_headers, ...} · note "descriptive; no tax computation".
    Years come from the closing date.  Money is rounded to cents; quantities are kept as exported
    (fractional shares included).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
INBOX = REPO / "inbox"
SCRATCH = REPO / "scratch"
ET = ZoneInfo("America/New_York")

sys.path.insert(0, str(HERE))
import ingest_brokerage as ib  # noqa: E402
from ingest_brokerage import (norm_text, norm_ticker, num_as_given, parse_date,  # noqa: E402
                              parse_number, parse_stamp, read_csv_rows)
from trading_calendar import now_et  # noqa: E402

SERVED_NAME = "realized_gains.json"
SOURCE_EXPORT = "brokerage realized gain/loss export"
SOURCE_OPERATOR = "operator report, pending export confirmation"
NOTE = "descriptive; no tax computation"
# The order (30 Sept 2026): "the 2025 total ($42,453.34 net, all short-term)".
OPERATOR_REPORTED_2025_NET = Decimal("42453.34")
OPERATOR_REPORT_AS_OF = "2026-09-30"
CENT = Decimal("0.01")
HALF_CENT = Decimal("0.005")
ZERO = Decimal("0")

# ─── synonym table ───────────────────────────────────────────────────────────────────────
# canonical field → (required?, [normalised header synonyms, most preferred first]).
# A header is claimed by the first canonical field (in table order) whose synonym list contains
# it; each header is claimed at most once.  Add a string to extend.  A gain/loss column OR the
# short-term + long-term pair is additionally required (checked in map_realized).
REALIZED_FIELDS: dict[str, tuple[bool, list[str]]] = {
    "symbol":               (True,  ib.POSITION_FIELDS["symbol"][1] + ["symbol s", "symbols", "security id"]),
    "close_date":           (True,  ["closed date", "date sold", "sale date", "close date", "date closed", "sell date",
                                     "disposition date", "closing date", "sold date", "date of sale",
                                     "date sold or disposed", "sold or disposed date", "date disposed", "closed", "sold",
                                     "date"]),
    "open_date":            (False, ["opened date", "date acquired", "acquisition date", "open date", "purchase date",
                                     "opening date", "date opened", "date purchased", "acquired date", "date bought",
                                     "bought date", "acquired", "opened"]),
    "quantity":             (True,  ["quantity", "shares", "qty", "quantity sold", "shares sold", "share quantity",
                                     "number of shares", "units", "quantity closed"]),
    "proceeds":             (True,  ["proceeds", "sales proceeds", "amount sold", "total proceeds", "net proceeds",
                                     "sale proceeds", "gross proceeds", "proceeds amount", "sale amount", "sales amount"]),
    "cost_basis":           (True,  ["cost basis", "cost", "total cost", "adjusted cost basis", "cost basis cb",
                                     "cost basis total", "total cost basis", "adjusted cost", "cost amount", "basis",
                                     "cost basis usd"]),
    "gain_loss":            (False, ["gain loss", "realized gain loss", "gain or loss", "net gain loss", "realized p l",
                                     "profit loss", "realized gain or loss", "total gain loss", "gain loss amount",
                                     "net gain or loss", "realized gain", "realized profit loss", "realized pnl",
                                     "net realized gain loss", "gain loss usd", "p l", "pnl"]),
    "short_term_gain_loss": (False, ["short term gain loss", "short term gain or loss", "st gain loss",
                                     "short term realized gain loss", "st gain or loss", "short term gain",
                                     "short term g l", "short term", "st"]),
    "long_term_gain_loss":  (False, ["long term gain loss", "long term gain or loss", "lt gain loss",
                                     "long term realized gain loss", "lt gain or loss", "long term gain",
                                     "long term g l", "long term", "lt"]),
    "term":                 (False, ["term", "holding period", "long short", "lt st", "short term long term",
                                     "st lt", "long term short term", "holding term", "gain type", "term type",
                                     "short long", "type"]),
    # the disallowed AMOUNT is claimed first; a Yes/No flag column ('Wash Sale?') falls to wash_sale_flag
    "wash_sale":            (False, ["wash sale loss disallowed", "disallowed loss", "wash sale disallowed",
                                     "wash sale adjustment", "wash sale loss", "disallowed wash sale loss",
                                     "wash sale amount", "wash sale adj", "wash sale"]),
    "wash_sale_flag":       (False, ["wash sale", "wash sale flag", "wash", "wash sale indicator"]),
    "proceeds_per_share":   (False, ["proceeds per share", "sale price", "sale price per share", "price sold",
                                     "sell price", "close price", "closing price"]),
    "cost_per_share":       (False, ["cost per share", "cost basis per share", "unit cost", "purchase price",
                                     "price acquired", "buy price", "open price", "opening price", "price paid"]),
    "gain_loss_pct":        (False, ["gain loss pct", "gain loss percent", "percent gain loss", "gain loss percentage",
                                     "pct gain loss", "return pct"]),
    "description":          (False, ["description", "security description", "security name", "name", "company",
                                     "instrument name"]),
    "account":              (False, ["account number", "account", "account name"]),
}
GAIN_FIELDS = ("gain_loss", "short_term_gain_loss", "long_term_gain_loss")
MONEY_FIELDS = ("proceeds", "cost_basis") + GAIN_FIELDS
YES_TOKENS = {"y", "yes", "true", "x", "w", "ws", "wash", "wash sale"}


# ─── small parsers ───────────────────────────────────────────────────────────────────────
def norm_header(h: str | None) -> str:
    """ingest_brokerage.norm_text after '%' → 'pct', so 'Gain/Loss (%)' and 'Gain/Loss ($)' stay distinct."""
    return norm_text((h or "").replace("%", " pct "))


def normalize_term(text: str | None) -> str:
    """'Short Term' / 'ST' / 'S' → 'short' · 'Long Term' / 'LT' / 'L' → 'long' · anything else → 'unknown'."""
    t = norm_text(text)
    if not t:
        return "unknown"
    if t in ("s", "st") or t.startswith("short") or " short" in f" {t}":
        return "short"
    if t in ("l", "lt") or t.startswith("long") or " long" in f" {t}":
        return "long"
    return "unknown"


def derive_term(open_iso: str | None, close_iso: str | None) -> str:
    """Held MORE than one year → 'long'.  IRS Pub 550: the holding period starts the day after the
    acquisition, so a sale ON the first anniversary is short and the day after is long."""
    if not open_iso or not close_iso:
        return "unknown"
    o, c = date.fromisoformat(open_iso), date.fromisoformat(close_iso)
    try:
        anniversary = o.replace(year=o.year + 1)
    except ValueError:                      # 29 Feb acquisition
        anniversary = o.replace(year=o.year + 1, day=28)
    return "long" if c > anniversary else "short"


def lot_symbol(raw: str) -> str:
    """Plain tickers through ingest_brokerage.norm_ticker; a multi-token symbol (an option: 'ZQX 09/19/2025
    100.00 C') keeps single inner spaces so it stays readable."""
    s = (raw or "").replace("﻿", "").strip().rstrip("*").strip()
    if " " in s:
        return " ".join(s.upper().split())
    return norm_ticker(s)


def money(d: Decimal | None) -> float | None:
    return None if d is None else float(d.quantize(CENT))


def _is_yes(text: str) -> bool:
    return norm_text(text) in YES_TOKENS


# ─── header mapping ──────────────────────────────────────────────────────────────────────
def map_realized(headers: list[str]) -> tuple[dict, list, list]:
    """(mapping canonical→header as written, unmatched headers, unmapped required fields).
    Same algorithm as ingest_brokerage.map_headers, with norm_header."""
    normed = [(h, norm_header(h)) for h in headers]
    claimed: set[str] = set()
    mapping: dict[str, str] = {}
    for canon, (_req, synonyms) in REALIZED_FIELDS.items():
        for syn in synonyms:
            hit = next((h for h, n in normed if n == syn and h not in claimed), None)
            if hit is not None:
                mapping[canon] = hit
                claimed.add(hit)
                break
    unmatched = [h for h in headers if h not in claimed and norm_header(h)]
    unmapped = [c for c, (req, _) in REALIZED_FIELDS.items() if req and c not in mapping]
    if not any(k in mapping for k in GAIN_FIELDS):
        unmapped.append("gain_loss (a gain/loss column, or short-term + long-term gain/loss columns)")
    return mapping, unmatched, unmapped


def is_realized_header(mapping: dict, cells: list[str]) -> bool:
    """A realized gain/loss header maps a symbol, a closing/sale date and at least one money column.
    A bare 'Date' beside an action/activity column is a transactions export, not ours."""
    if "symbol" not in mapping or "close_date" not in mapping:
        return False
    if not any(k in mapping for k in MONEY_FIELDS):
        return False
    if norm_header(mapping["close_date"]) == "date":
        mp_t, _um, _ur = ib.map_transactions(cells)
        if "action" in mp_t:
            return False
    return True


def sniff_header(rows: list[list[str]]) -> tuple[int, dict, list, list] | None:
    """Pick the header row: among the first 60 rows with ≥3 non-empty cells, the realized-gains header
    whose mapped canonical fields score highest."""
    best = None
    for i, row in enumerate(rows[:60]):
        cells = [c.strip() for c in row]
        if sum(1 for c in cells if c) < 3:
            continue
        mp, um, ur = map_realized(cells)
        if not is_realized_header(mp, cells):
            continue
        cand = (len(mp), i, mp, um, ur)
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None:
        return None
    _score, i, mp, um, ur = best
    return i, mp, um, ur


# ─── file model ──────────────────────────────────────────────────────────────────────────
@dataclass
class RealizedFile:
    path: Path
    size: int
    recognised: bool = False
    header_index: int = -1
    headers: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)
    unmatched_headers: list = field(default_factory=list)
    unmapped_required: list = field(default_factory=list)
    lots: list = field(default_factory=list)          # one dict per closed lot, Decimals inside
    skipped: list = field(default_factory=list)       # [{row, reason, text}]
    warnings: list = field(default_factory=list)
    stamp: dict | None = None
    term_basis: str = ""
    gain_check: dict = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.recognised and not self.unmapped_required


def _cell(rowmap: dict, header: str | None) -> str:
    if not header:
        return ""
    return (rowmap.get(header) or "").strip()


def _is_total_symbol(sym_raw: str) -> bool:
    n = norm_text(sym_raw)
    if not n:
        return False
    return (n in ib.TOTAL_ROW_NAMES or n.startswith("total") or n.startswith("subtotal")
            or n.startswith("grand total") or n.endswith(" total") or n.endswith(" totals"))


def parse_lots(pf: RealizedFile, rows: list[list[str]]) -> None:
    m = pf.mapping
    has_term, has_open = "term" in m, "open_date" in m
    has_stlt = "short_term_gain_loss" in m or "long_term_gain_loss" in m
    normed_headers = [norm_header(h) for h in pf.headers]
    n_mismatch = n_explained = 0
    for k, row in enumerate(rows[pf.header_index + 1:], start=pf.header_index + 2):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        text = " | ".join(c for c in cells if c)[:120]
        if [norm_header(c) for c in cells] == normed_headers:
            pf.skipped.append({"row": k, "reason": "repeated header row", "text": text})
            continue
        rm = dict(zip(pf.headers, cells + [""] * (len(pf.headers) - len(cells))))
        sym_raw = _cell(rm, m.get("symbol"))
        close_raw = _cell(rm, m.get("close_date"))
        populated = sum(1 for c in cells if c)
        if populated < 3 and not (sym_raw and close_raw):
            pf.skipped.append({"row": k, "reason": "free-text line (preamble/footer/disclaimer)", "text": text})
            continue
        if _is_total_symbol(sym_raw):
            pf.skipped.append({"row": k, "reason": "total/summary row", "text": text})
            continue
        if not sym_raw:
            pf.skipped.append({"row": k, "reason": "no symbol (unlabelled total/summary or continuation row)", "text": text})
            continue
        close_iso = parse_date(close_raw)
        if close_iso is None:
            reason = "blank close date" if not close_raw else f"unparseable close date '{close_raw}'"
            pf.skipped.append({"row": k, "reason": reason, "text": text})
            continue
        qty = parse_number(_cell(rm, m.get("quantity")))
        proceeds = parse_number(_cell(rm, m.get("proceeds")))
        cost = parse_number(_cell(rm, m.get("cost_basis")))
        gl = parse_number(_cell(rm, m.get("gain_loss")))
        st = parse_number(_cell(rm, m.get("short_term_gain_loss")))
        lt = parse_number(_cell(rm, m.get("long_term_gain_loss")))
        if qty is None and proceeds is None and cost is None and gl is None and st is None and lt is None:
            pf.skipped.append({"row": k, "reason": "no amounts (not a lot row)", "text": text})
            continue
        open_raw = _cell(rm, m.get("open_date")) if has_open else ""
        open_iso = parse_date(open_raw) if open_raw else None
        term_raw = _cell(rm, m.get("term")) if has_term else ""
        lot_notes: list[str] = []
        if has_open and open_raw and open_iso is None:
            lot_notes.append(f"open date '{open_raw}' is not a date (aggregated lots?)")

        # ── gain and term ──
        gain_basis = "as exported"
        if st is not None or lt is not None:
            gain = (st if st is not None else ZERO) + (lt if lt is not None else ZERO)
            gain_basis = "short-term + long-term columns"
            if gl is not None and abs(gl - gain) > HALF_CENT:
                lot_notes.append(f"gain/loss column {gl} differs from short-term + long-term {gain}")
            s_nz, l_nz = st is not None and st != 0, lt is not None and lt != 0
            if s_nz and l_nz:
                term, term_basis = "mixed", "short-term and long-term columns both non-zero"
            elif s_nz or (st is not None and lt is None):
                term, term_basis = "short", "short-term column"
            elif l_nz or (lt is not None and st is None):
                term, term_basis = "long", "long-term column"
            elif has_term and normalize_term(term_raw) != "unknown":
                term, term_basis = normalize_term(term_raw), "term column"
            else:
                term = derive_term(open_iso, close_iso)
                term_basis = "derived from dates" if term != "unknown" else "unknown"
            short_c = st if st is not None else ZERO
            long_c = lt if lt is not None else ZERO
            unknown_c = ZERO
        else:
            if gl is None:
                if proceeds is not None and cost is not None:
                    gain, gain_basis = proceeds - cost, "derived: proceeds − cost basis (gain/loss cell blank)"
                else:
                    pf.skipped.append({"row": k, "reason": "no gain/loss amount and not derivable", "text": text})
                    continue
            else:
                gain = gl
            if has_term and term_raw:
                term, term_basis = normalize_term(term_raw), "term column"
                if term == "unknown":
                    term_basis = f"term column value '{term_raw}' not recognised"
            elif has_open:
                term = derive_term(open_iso, close_iso)
                term_basis = "derived from dates" if term != "unknown" else "unknown (open date missing)"
            else:
                term, term_basis = "unknown", "unknown (no term column, no acquired date)"
            short_c = gain if term == "short" else ZERO
            long_c = gain if term == "long" else ZERO
            unknown_c = gain if term == "unknown" else ZERO

        # ── wash sale: reported, never netted ──
        wash_raw = _cell(rm, m.get("wash_sale")) if "wash_sale" in m else ""
        wash = parse_number(wash_raw) if wash_raw else None
        flag_raw = _cell(rm, m.get("wash_sale_flag")) if "wash_sale_flag" in m else ""
        wash_flag = bool((wash is not None and wash != 0) or _is_yes(flag_raw) or (wash_raw and wash is None and _is_yes(wash_raw)))

        # ── consistency: proceeds − cost vs gain/loss (counted, not corrected) ──
        check = None
        if proceeds is not None and cost is not None:
            diff = (proceeds - cost) - gain
            if abs(diff) > HALF_CENT:
                n_mismatch += 1
                if wash is not None and abs(abs(diff) - abs(wash)) <= CENT:
                    n_explained += 1
                    check = f"proceeds − cost = {proceeds - cost} vs gain/loss {gain}: differs by the disallowed wash-sale amount {wash}"
                else:
                    check = f"proceeds − cost = {proceeds - cost} vs gain/loss {gain}: unexplained difference {diff}"

        pf.lots.append({
            "row": k, "ticker": lot_symbol(sym_raw), "ticker_raw": sym_raw,
            "description": _cell(rm, m.get("description")),
            "open_date": open_iso, "open_date_raw": open_raw, "close_date": close_iso, "close_date_raw": close_raw,
            "year": close_iso[:4], "quantity": qty, "proceeds": proceeds, "cost_basis": cost,
            "gain_loss": gain, "gain_loss_basis": gain_basis, "term": term, "term_basis": term_basis,
            "short_term": short_c, "long_term": long_c, "unknown_term": unknown_c,
            "wash_sale_disallowed": wash, "wash_sale_flag": wash_flag,
            "gain_check": check, "notes": "; ".join(lot_notes),
        })

    # the file-level term basis: what decided the term on the lots
    bases = sorted({l["term_basis"] for l in pf.lots})
    if has_stlt:
        pf.term_basis = (f"short-term / long-term columns ('{m.get('short_term_gain_loss')}' / "
                         f"'{m.get('long_term_gain_loss')}'): a lot's term is whichever is non-empty")
    elif has_term:
        pf.term_basis = f"term column '{m['term']}'"
        if pf.lots and all(l["term"] == "unknown" for l in pf.lots):
            # the 'type' synonym can catch a security-type column: fall back to the dates, and say so
            if has_open and any(l["open_date"] for l in pf.lots):
                for l in pf.lots:
                    t = derive_term(l["open_date"], l["close_date"])
                    l["term"] = t
                    l["term_basis"] = "derived from dates" if t != "unknown" else "unknown (open date missing)"
                    l["short_term"] = l["gain_loss"] if t == "short" else ZERO
                    l["long_term"] = l["gain_loss"] if t == "long" else ZERO
                    l["unknown_term"] = l["gain_loss"] if t == "unknown" else ZERO
                pf.term_basis = (f"derived from '{m['open_date']}' / '{m['close_date']}' (held > 1 year = long); "
                                 f"the term column '{m['term']}' carries no short/long values")
                pf.warnings.append(f"term column '{m['term']}' has no short/long values on any lot — term derived from dates instead")
            else:
                pf.warnings.append(f"term column '{m['term']}' has no short/long values on any lot — every lot is term 'unknown'")
    elif has_open:
        pf.term_basis = f"derived from '{m['open_date']}' / '{m['close_date']}' (held > 1 year = long); no term column in the export"
    else:
        pf.term_basis = "unknown: no term column and no acquired date in the export"
    n_unknown = sum(1 for l in pf.lots if l["term"] == "unknown")
    if n_unknown:
        pf.warnings.append(f"{n_unknown} lot(s) with term 'unknown' (carried in unknown_term, not folded into short or long): "
                           + ", ".join(sorted({l["term_basis"] for l in pf.lots if l["term"] == "unknown"})))
    if bases and has_stlt and any(b.startswith("derived") for b in bases):
        pf.warnings.append("some lots have neither short-term nor long-term amount — their term was derived from dates")
    pf.gain_check = {"n_lots_checked": sum(1 for l in pf.lots if l["proceeds"] is not None and l["cost_basis"] is not None),
                     "n_mismatch": n_mismatch, "n_explained_by_wash_sale": n_explained}
    if n_mismatch:
        pf.warnings.append(f"gain/loss ≠ proceeds − cost basis on {n_mismatch} lot(s); {n_explained} of them by exactly the lot's "
                           "disallowed wash-sale amount (the export's gain/loss is wash-adjusted there); nothing netted by this job")


def parse_file(path: Path) -> RealizedFile:
    raw = path.read_bytes()
    rows = read_csv_rows(raw)
    pf = RealizedFile(path=path, size=len(raw))
    hit = sniff_header(rows)
    if hit is None:
        pf.warnings.append("no header row maps symbol + closing/sale date + a money column (not a realized gain/loss export)")
        return pf
    pf.recognised = True
    pf.header_index, pf.mapping, pf.unmatched_headers, pf.unmapped_required = hit
    pf.headers = [c.strip() for c in rows[pf.header_index]]
    for row in rows:                       # the export's own stamp lives in preamble/footer lines
        if sum(1 for c in row if c.strip()) < 3:
            st = parse_stamp(" ".join(c for c in row if c.strip()))
            if st:
                pf.stamp = st
                break
    parse_lots(pf, rows)
    return pf


# ─── aggregation ─────────────────────────────────────────────────────────────────────────
def _new_agg(ticker: str) -> dict:
    return {"ticker": ticker, "n_lots": 0, "quantity": ZERO, "proceeds": ZERO, "cost_basis": ZERO, "gain_loss": ZERO,
            "short_term": ZERO, "long_term": ZERO, "unknown_term": ZERO, "wash_sale_disallowed": ZERO,
            "n_wash_sale_lots": 0, "quantity_known": True, "proceeds_known": True, "cost_known": True}


def _add(agg: dict, lot: dict) -> None:
    agg["n_lots"] += 1
    for k, known in (("quantity", "quantity_known"), ("proceeds", "proceeds_known"), ("cost_basis", "cost_known")):
        if lot[k] is None:
            agg[known] = False
        else:
            agg[k] += lot[k]
    for k in ("gain_loss", "short_term", "long_term", "unknown_term"):
        agg[k] += lot[k]
    if lot["wash_sale_disallowed"] is not None:
        agg["wash_sale_disallowed"] += lot["wash_sale_disallowed"]
    if lot["wash_sale_flag"]:
        agg["n_wash_sale_lots"] += 1


def _position_block(agg: dict, wash_mapped: bool) -> dict:
    out = {"ticker": agg["ticker"], "n_lots": agg["n_lots"],
           "quantity": num_as_given(agg["quantity"]) if agg["quantity_known"] else None,
           "proceeds": money(agg["proceeds"]) if agg["proceeds_known"] else None,
           "cost_basis": money(agg["cost_basis"]) if agg["cost_known"] else None,
           "gain_loss": money(agg["gain_loss"]), "short_term": money(agg["short_term"]), "long_term": money(agg["long_term"])}
    if agg["unknown_term"] != 0:
        out["unknown_term"] = money(agg["unknown_term"])
    if wash_mapped:
        out["wash_sale_disallowed"] = money(agg["wash_sale_disallowed"])
        out["n_wash_sale_lots"] = agg["n_wash_sale_lots"]
    return out


def _positions(lots: list[dict], wash_mapped: bool) -> list[dict]:
    by: dict[str, dict] = {}
    for l in lots:
        by.setdefault(l["ticker"], _new_agg(l["ticker"]))
        _add(by[l["ticker"]], l)
    blocks = [_position_block(a, wash_mapped) for a in by.values()]
    return sorted(blocks, key=lambda p: (-abs(p["gain_loss"]), p["ticker"]))


def _totals(lots: list[dict], wash_mapped: bool) -> dict:
    a = _new_agg("*")
    for l in lots:
        _add(a, l)
    out = {"net": money(a["gain_loss"]), "short_term": money(a["short_term"]), "long_term": money(a["long_term"]),
           "unknown_term": money(a["unknown_term"]), "n_lots": a["n_lots"],
           "wash_sale_disallowed": money(a["wash_sale_disallowed"]) if wash_mapped else None,
           "n_wash_sale_lots": a["n_wash_sale_lots"] if wash_mapped else None}
    return out


def summarise(lots: list[dict], as_of: str, wash_mapped: bool) -> tuple[dict, dict, list]:
    """(years, totals_all_years, totals_by_position_all_years).  Years come from the closing date."""
    years: dict[str, dict] = {}
    for y in sorted({l["year"] for l in lots}):
        ylots = [l for l in lots if l["year"] == y]
        block = _totals(ylots, wash_mapped)
        block["by_position"] = _positions(ylots, wash_mapped)
        block["year_to_date"] = y == as_of[:4]
        if block["year_to_date"]:
            block["through"] = as_of
        years[y] = block
    return years, _totals(lots, wash_mapped), _positions(lots, wash_mapped)


def reconcile(years: dict, expect_2025_net: Decimal) -> dict:
    """The order states the 2025 total ($42,453.34 net, all short-term); the export must agree or the
    difference is reported — in the printed report and in the served file."""
    y = years.get("2025")
    out = {"operator_reported_2025_net": float(expect_2025_net), "operator_reported_2025_all_short_term": True,
           "export_2025_net": None, "export_2025_short_term": None, "export_2025_long_term": None,
           "difference": None, "match": False, "note": None}
    if y is None:
        out["note"] = "the export has no lots closed in 2025 — the operator-reported 2025 total could not be checked"
        return out
    net = Decimal(str(y["net"]))
    out["export_2025_net"] = y["net"]
    out["export_2025_short_term"], out["export_2025_long_term"] = y["short_term"], y["long_term"]
    out["difference"] = money(net - expect_2025_net)
    out["match"] = abs(net - expect_2025_net) <= HALF_CENT
    if out["match"]:
        out["note"] = "export 2025 net equals the operator-reported total"
        if y["long_term"] not in (None, 0, 0.0) or (y.get("unknown_term") not in (None, 0, 0.0)):
            out["note"] += "; NOTE the export shows long-term or unknown-term amounts in 2025 where the operator reported all short-term"
    else:
        out["note"] = (f"MISMATCH: export 2025 net {net:.2f} vs operator-reported {expect_2025_net:.2f} "
                       f"(difference {net - expect_2025_net:+.2f})")
    return out


# ─── assembling the result ───────────────────────────────────────────────────────────────
@dataclass
class IngestResult:
    realized: RealizedFile | None
    files: list                       # every RealizedFile seen
    problems: list                    # fatal (exit 1) problems
    input_sha256: str | None = None
    input_file: dict | None = None
    record: dict = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.realized is not None and self.realized.complete


def ingest(inbox: Path | None, file: Path | None = None,
           expect_2025_net: Decimal = OPERATOR_REPORTED_2025_NET) -> IngestResult:
    """Pure: reads the CSV(s), writes nothing.  The realized-gains file is found by header sniffing."""
    files: list[Path] = []
    if file:
        files.append(Path(file))
    else:
        if inbox is None or not Path(inbox).is_dir():
            return IngestResult(None, [], [f"inbox not found: {inbox}"])
        files = sorted({p.resolve() for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() == ".csv"},
                       key=lambda p: p.name)
    parsed = [parse_file(p) for p in files]
    problems: list[str] = []
    cands = [p for p in parsed if p.recognised]
    if not files:
        problems.append(f"no .csv files in {inbox}")
    elif not cands:
        problems.append("no realized gain/loss CSV recognised (a header row with symbol + closed/sold date + "
                        "proceeds/cost basis/gain-loss columns)" + (f" in {inbox}" if inbox else f": {file}"))
    elif len(cands) > 1:
        problems.append("ambiguous: more than one realized gain/loss CSV: " + ", ".join(p.path.name for p in cands))
    res = IngestResult(cands[0] if len(cands) == 1 else None, parsed, problems)
    if res.realized is None:
        return res
    pf = res.realized
    res.input_sha256 = hashlib.sha256(pf.path.read_bytes()).hexdigest()
    res.input_file = {"name": pf.path.name, "bytes": pf.size}
    et_now = now_et()
    as_of = pf.stamp["date"] if pf.stamp else et_now.strftime("%Y-%m-%d")
    if pf.stamp and pf.stamp.get("datetime"):
        exported_at, exported_basis = pf.stamp["datetime"], "export stamp: " + pf.stamp["line"]
    else:
        exported_at = datetime.fromtimestamp(pf.path.stat().st_mtime, tz=ET).isoformat(timespec="seconds")
        exported_basis = "file mtime (no time stamp in the export)" + (f"; stamp line: {pf.stamp['line']}" if pf.stamp else "")
    wash_mapped = "wash_sale" in pf.mapping or "wash_sale_flag" in pf.mapping
    years, totals, by_pos = summarise(pf.lots, as_of, wash_mapped)
    res.record = {
        "cadence": "on_change",
        "as_of": as_of,
        "as_of_basis": ("export stamp date" if pf.stamp else "ET ingest date (no stamp in the export)"),
        "source": SOURCE_EXPORT,
        "exported_at": exported_at,
        "exported_at_basis": exported_basis,
        "input_sha256": res.input_sha256,
        "input_file": res.input_file,
        "ingested_at": et_now.isoformat(timespec="seconds"),
        "pending_export": False,
        "years": years,
        "totals_all_years": totals,
        "totals_by_position_all_years": by_pos,
        "term_basis": pf.term_basis,
        "wash_sales": {
            "amount_column": pf.mapping.get("wash_sale"),
            "flag_column": pf.mapping.get("wash_sale_flag"),
            "n_lots_flagged": sum(1 for l in pf.lots if l["wash_sale_flag"]),
            "disallowed_total": totals["wash_sale_disallowed"],
            "gain_check": pf.gain_check,
            "note": "reported separately; gain_loss is as the export states it — nothing is netted by this job",
        },
        "reconciliation": reconcile(years, expect_2025_net),
        "mapping": {
            "header_row": pf.header_index + 1,
            "headers": pf.headers,
            "chosen": pf.mapping,
            "unmatched_headers": pf.unmatched_headers,
            "unmapped_required": pf.unmapped_required,
            "stamp": pf.stamp,
            "n_lots": len(pf.lots),
            "n_skipped_rows": len(pf.skipped),
            "warnings": pf.warnings,
        },
        "note": NOTE,
    }
    if not pf.complete:
        res.record["_unmapped_required"] = list(pf.unmapped_required)
        res.record["_note"] = "BEST GUESS ONLY — a required column is unmapped; nothing served was written"
    return res


def operator_report_record() -> dict:
    """The seed the order states, served until the export arrives (and replaced by it)."""
    net = float(OPERATOR_REPORTED_2025_NET)
    return {
        "cadence": "on_change",
        "as_of": OPERATOR_REPORT_AS_OF,
        "source": SOURCE_OPERATOR,
        "exported_at": None,
        "input_sha256": None,
        "input_file": None,
        "ingested_at": now_et().isoformat(timespec="seconds"),
        "pending_export": True,
        "years": {
            "2025": {"net": net, "short_term": net, "long_term": 0.0, "n_lots": None, "by_position": [],
                     "basis": "operator-reported total; per-position detail pending the export"},
            "2026": {"net": None, "short_term": None, "long_term": None, "year_to_date": True,
                     "basis": "pending the realized-gains export"},
        },
        "totals_by_position_all_years": [],
        "reconciliation": {"operator_reported_2025_net": net, "export_2025_net": None, "match": None,
                           "note": "no export ingested yet"},
        "mapping": None,
        "note": NOTE,
    }


# ─── writers ─────────────────────────────────────────────────────────────────────────────
LOT_COLUMNS = ["row", "ticker", "ticker_raw", "description", "open_date", "open_date_raw", "close_date", "close_date_raw",
               "year", "quantity", "proceeds", "cost_basis", "gain_loss", "gain_loss_basis", "term", "term_basis",
               "short_term", "long_term", "unknown_term", "wash_sale_disallowed", "wash_sale_flag", "gain_check", "notes"]


def mapping_report(res: IngestResult) -> dict:
    def fileblock(pf: RealizedFile | None):
        if pf is None:
            return None
        return {"file": pf.path.name, "bytes": pf.size, "recognised": pf.recognised, "header_row": pf.header_index + 1,
                "headers": pf.headers, "mapping": pf.mapping, "unmatched_headers": pf.unmatched_headers,
                "unmapped_required": pf.unmapped_required, "stamp": pf.stamp, "n_lots": len(pf.lots),
                "term_basis": pf.term_basis, "gain_check": pf.gain_check, "skipped_rows": pf.skipped, "warnings": pf.warnings}
    return {"created_at": now_et().isoformat(timespec="seconds"),
            "complete": res.complete, "problems": res.problems,
            "input_sha256": res.input_sha256, "input_file": res.input_file,
            "realized_gains": fileblock(res.realized),
            "other_files": [fileblock(p) for p in res.files if p is not res.realized],
            "reconciliation": res.record.get("reconciliation")}


def write_scratch(res: IngestResult, scratch_root: Path) -> Path:
    stamp = now_et().strftime("%Y%m%dT%H%M%S")
    out = scratch_root / f"realized_gains_{stamp}"
    n = 1
    while out.exists():
        n += 1
        out = scratch_root / f"realized_gains_{stamp}_{n}"
    out.mkdir(parents=True)
    with open(out / "realized_gains_candidate.json", "w") as f:
        json.dump(res.record, f, indent=2, default=ib._json_default)
        f.write("\n")
    with open(out / "mapping.json", "w") as f:
        json.dump(mapping_report(res), f, indent=2, default=ib._json_default)
        f.write("\n")
    with open(out / "realized_lots.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for l in (res.realized.lots if res.realized else []):
            w.writerow({k: ("" if l.get(k) is None else l.get(k)) for k in LOT_COLUMNS})
    return out


def write_served(record: dict, data_dir: Path) -> Path:
    if record.get("_unmapped_required"):
        raise RuntimeError("refusing to write served realized gains from an incomplete mapping")
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / SERVED_NAME
    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(record, f, indent=2, default=ib._json_default)
        f.write("\n")
    tmp.replace(target)
    return target


# ─── CLI ─────────────────────────────────────────────────────────────────────────────────
def _fmt(x) -> str:
    return "—" if x is None else (f"{x:,.2f}" if isinstance(x, float) else str(x))


def print_report(res: IngestResult) -> None:
    for pf in res.files:
        kind = "realized gain/loss" if pf.recognised else "not a realized gain/loss export (ignored)"
        print(f"\n[{kind}] {pf.path.name} ({pf.size} bytes)" + (f" header row {pf.header_index + 1}" if pf.recognised else ""))
        if not pf.recognised:
            for w in pf.warnings:
                print(f"  ! {w}")
            continue
        print("  mapping chosen:")
        for canon, hdr in pf.mapping.items():
            print(f"    {canon:22s} ← '{hdr}'")
        print(f"  unmatched headers (ignored): {pf.unmatched_headers or '—'}")
        if pf.unmapped_required:
            print(f"  UNMAPPED REQUIRED: {pf.unmapped_required}")
        if pf.stamp:
            print(f"  export stamp: {pf.stamp['line']} → date {pf.stamp['date']} datetime {pf.stamp['datetime']}")
        print(f"  term basis: {pf.term_basis}")
        print(f"  lots parsed: {len(pf.lots)}")
        if pf.skipped:
            print(f"  skipped rows: {len(pf.skipped)}")
            for s in pf.skipped[:12]:
                print(f"    row {s['row']}: {s['reason']} — {s['text']}")
        for w in pf.warnings:
            print(f"  warn: {w}")
    if res.realized and res.record:
        rec = res.record
        print("\nrealized gain/loss by year (from the closing date):")
        for y, blk in rec["years"].items():
            ytd = f" (year to date through {blk['through']})" if blk.get("year_to_date") else ""
            print(f"  {y}{ytd}: net {_fmt(blk['net'])}  short-term {_fmt(blk['short_term'])}  long-term {_fmt(blk['long_term'])}"
                  f"  unknown-term {_fmt(blk['unknown_term'])}  lots {blk['n_lots']}  wash-sale disallowed {_fmt(blk['wash_sale_disallowed'])}")
            for p in blk["by_position"][:15]:
                print(f"      {p['ticker']:10s} lots {p['n_lots']:>3}  qty {p['quantity']!s:>12}  proceeds {_fmt(p['proceeds']):>14}"
                      f"  cost {_fmt(p['cost_basis']):>14}  gain/loss {_fmt(p['gain_loss']):>13}  ST {_fmt(p['short_term']):>12}  LT {_fmt(p['long_term']):>12}")
            if len(blk["by_position"]) > 15:
                print(f"      … {len(blk['by_position']) - 15} more positions")
        t = rec["totals_all_years"]
        print(f"  all years: net {_fmt(t['net'])}  short-term {_fmt(t['short_term'])}  long-term {_fmt(t['long_term'])}  lots {t['n_lots']}")
        ws = rec["wash_sales"]
        print(f"wash sales: {ws['n_lots_flagged']} lot(s) flagged, disallowed total {_fmt(ws['disallowed_total'])} "
              f"(amount column {ws['amount_column']!r}, flag column {ws['flag_column']!r}) — reported separately, never netted")
        rc = rec["reconciliation"]
        if rc["match"]:
            print(f"RECONCILIATION 2025: export net {_fmt(rc['export_2025_net'])} = operator-reported {_fmt(rc['operator_reported_2025_net'])} — MATCH"
                  + ("" if rc["note"].endswith("total") else f" ({rc['note']})"))
        else:
            print(f"WARNING RECONCILIATION 2025: {rc['note']} (operator-reported {_fmt(rc['operator_reported_2025_net'])}, "
                  f"export {_fmt(rc['export_2025_net'])})")
        print(f"as_of {rec['as_of']} ({rec['as_of_basis']}) · exported_at {rec['exported_at']} · input_sha256 {rec['input_sha256']}")
    for p in res.problems:
        print(f"PROBLEM: {p}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("Usage")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inbox", default=str(INBOX), help="directory holding the exported CSVs (default: repo inbox/)")
    ap.add_argument("--file", help="the realized gain/loss CSV itself (skips inbox sniffing)")
    ap.add_argument("--write", action="store_true", help="write data/realized_gains.json (only with a complete mapping)")
    ap.add_argument("--dry-run", action="store_true", help="never write under data/ (default behaviour; overrides --write)")
    ap.add_argument("--data-dir", default=str(DATA), help="served data directory (default: repo data/)")
    ap.add_argument("--scratch", default=str(SCRATCH), help="scratch root for the best-guess output (default: repo scratch/)")
    ap.add_argument("--expect-2025-net", default=str(OPERATOR_REPORTED_2025_NET),
                    help="the operator-reported 2025 net the export is reconciled against (default: the order's 42453.34)")
    ap.add_argument("--seed-operator-report", action="store_true",
                    help="write the served file from the order's stated figures alone (pending_export true); no CSV read")
    args = ap.parse_args(argv)

    if args.seed_operator_report:
        rec = operator_report_record()
        print(json.dumps(rec, indent=2))
        if args.write and not args.dry_run:
            target = write_served(rec, Path(args.data_dir))
            print(f"served: wrote {target} (source {rec['source']!r}, pending_export true)")
        else:
            print("dry run: nothing written under data/ (pass --write to publish the operator-report seed)")
        return 0

    res = ingest(Path(args.inbox) if not args.file else None, file=Path(args.file) if args.file else None,
                 expect_2025_net=Decimal(args.expect_2025_net))
    print_report(res)
    if res.realized is None or res.problems:
        for p in res.problems:
            print(f"error: {p}", file=sys.stderr)
        print("nothing written.", file=sys.stderr)
        return 1
    out = write_scratch(res, Path(args.scratch))
    print(f"\nbest guess written to {out}/ (realized_gains_candidate.json, mapping.json, realized_lots.csv)")
    if not res.complete:
        sys.stdout.flush()
        print(f"UNMAPPED REQUIRED COLUMNS {json.dumps(res.realized.unmapped_required)} — nothing served written (exit 2)", file=sys.stderr)
        return 2
    if args.write and not args.dry_run:
        target = write_served(res.record, Path(args.data_dir))
        yrs = ", ".join(f"{y}: net {_fmt(b['net'])}" for y, b in res.record["years"].items())
        print(f"served: wrote {target} ({len(res.realized.lots)} lots; {yrs})")
        if not res.record["reconciliation"]["match"]:
            print(f"WARNING: served file's 2025 net does not match the operator-reported {OPERATOR_REPORTED_2025_NET} — see reconciliation", file=sys.stderr)
    else:
        print(f"dry run: nothing written under data/ (pass --write to publish {SERVED_NAME})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
