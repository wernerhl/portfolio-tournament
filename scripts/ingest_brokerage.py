#!/usr/bin/env python3
"""
ingest_brokerage.py — holdings order Phase 2, item (2.1): brokerage CSV export → data/holdings.json.

The execution order, quoted verbatim:

    "A job reads a positions CSV and a transactions CSV dropped into inbox/ and writes
    holdings.json with source: "brokerage export", exported_at, and a hash of the input.
    The parser is tolerant: it detects columns by header names (symbol, quantity or shares,
    price, cost basis or average cost, market value; for transactions: date, action, symbol,
    quantity, price, amount) and reports the header mapping it chose. If a header cannot be
    mapped, the job writes nothing served, places its best guess in scratch/, and reports the
    unmatched headers. Fractional shares are kept as given. Cash is taken from the export's
    cash line."

Usage
    ingest_brokerage.py [--inbox inbox] [--write] [--dry-run]
                        [--data-dir data] [--scratch scratch] [--cash-names "name,name"]
                        [--positions FILE] [--transactions FILE]

  * The positions CSV and the transactions CSV are found in inbox/ by HEADER SNIFFING
    (which canonical fields the header row maps to), never by file name.
  * Without --write (or with --dry-run) nothing under data/ is touched.  The full best guess
    goes to scratch/ingest_<ET timestamp>/ : holdings_candidate.json, mapping.json (the chosen
    header mapping, the unmatched headers, the input hash), transactions_parsed.csv.
  * With --write AND a complete mapping, data/holdings.json is written as well.  The scratch
    copy is still produced (seed_actions_from_transactions.py reads it).
  * Exit codes: 0 ok · 2 a required column could not be mapped (nothing served is written,
    the best guess and the unmatched headers are reported) · 1 anything else (no CSV found,
    ambiguous files, unreadable input).

Served output, data/holdings.json:
    cadence "on_change" · as_of (the export date, else today's ET date) · source
    "brokerage export" · exported_at (the export's own stamp if present, else the positions
    file's mtime; ISO 8601 with offset) · input_sha256 (sha256 over the bytes of the positions
    CSV followed by the bytes of the transactions CSV, in that order) · input_files (names +
    sizes) · cash · holdings [{ticker, shares, cost_basis (PER-SHARE average cost),
    cost_basis_basis (how it was obtained: exported per-share, or total cost / shares)}].

Header detection is the synonym table below (POSITION_FIELDS / TRANSACTION_FIELDS): extend it
by adding strings.  Headers are normalised (lower-case, '&' → 'and', punctuation → space,
collapsed) and matched EXACTLY against the synonyms, most-preferred synonym first.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
INBOX = REPO / "inbox"
SCRATCH = REPO / "scratch"
ET = ZoneInfo("America/New_York")

sys.path.insert(0, str(HERE))
from trading_calendar import now_et  # noqa: E402

# ─── synonym table ───────────────────────────────────────────────────────────────────────
# canonical field → (required?, [normalised header synonyms, most preferred first]).
# A header is claimed by the first canonical field (in table order) whose synonym list
# contains it; each header is claimed at most once.  Add a string to extend.
POSITION_FIELDS: dict[str, tuple[bool, list[str]]] = {
    "symbol":               (True,  ["symbol", "ticker", "ticker symbol", "security symbol", "stock symbol",
                                     "instrument", "security", "sym"]),
    "quantity":             (True,  ["quantity", "shares", "qty", "share quantity", "quantity held",
                                     "shares held", "number of shares", "units", "position"]),
    "market_value":         (True,  ["market value", "current value", "mkt value", "mkt val", "market val",
                                     "position value", "total value", "value"]),
    # per-share average cost is preferred over the total when both are present
    "cost_basis_per_share": (False, ["average cost basis", "average cost", "avg cost basis", "avg cost",
                                     "average price", "avg price", "cost per share", "cost basis per share",
                                     "average cost per share", "unit cost", "cost share"]),
    "cost_basis_total":     (False, ["cost basis total", "total cost basis", "cost basis", "total cost",
                                     "cost", "book value", "cost value"]),
    "price":                (False, ["price", "last price", "last", "market price", "current price",
                                     "last trade price", "close", "closing price"]),
    "description":          (False, ["description", "security description", "security name", "name", "company"]),
    "security_type":        (False, ["security type", "asset type", "asset class", "instrument type", "type"]),
    "account":              (False, ["account number", "account", "account name"]),
}
# positions additionally need ONE of cost_basis_per_share / cost_basis_total (checked below)

TRANSACTION_FIELDS: dict[str, tuple[bool, list[str]]] = {
    "date":            (True,  ["date", "trade date", "transaction date", "run date", "activity date",
                                "date of transaction", "process date"]),
    "action":          (True,  ["action", "transaction type", "activity type", "activity", "transaction",
                                "trans type", "type"]),
    "symbol":          (True,  POSITION_FIELDS["symbol"][1]),
    "quantity":        (True,  POSITION_FIELDS["quantity"][1]),
    "price":           (True,  ["price", "trade price", "price per share", "unit price", "execution price",
                                "fill price"]),
    "amount":          (False, ["amount", "net amount", "amount usd", "total amount", "net cash amount",
                                "proceeds", "net", "total"]),
    "fees":            (False, ["fees and comm", "fees and commissions", "commissions and fees", "fees", "fee",
                                "commission", "commissions", "comm"]),
    "description":     (False, ["description", "security description", "security name", "name"]),
    "settlement_date": (False, ["settlement date", "settle date"]),
    "account":         (False, ["account number", "account", "account name"]),
}

# The export's cash line, matched case-insensitively against the symbol cell (equality), the
# security-type cell (equality) and the description cell (phrase containment; the bare word
# "cash" is NOT matched inside descriptions so "CASH AMERICA INTL" stays a stock).
# Extend with --cash-names "name,name".
CASH_LINE_NAMES = ["cash & cash investments", "cash and cash investments", "cash", "money market",
                   "sweep", "core position", "cash and money market", "cash & sweep vehicle"]

TOTAL_ROW_NAMES = {"account total", "total", "totals", "grand total", "subtotal", "pending activity"}

NULL_TOKENS = {"", "-", "--", "---", "n/a", "na", "null", "none", "nan", "—", "–"}

TZ_ABBREV = {"ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York",
             "CT": "America/Chicago", "CST": "America/Chicago", "CDT": "America/Chicago",
             "MT": "America/Denver", "MST": "America/Denver", "MDT": "America/Denver",
             "PT": "America/Los_Angeles", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
             "UTC": "UTC", "GMT": "UTC", "Z": "UTC"}


# ─── small parsers ───────────────────────────────────────────────────────────────────────
def norm_text(h: str | None) -> str:
    """lower-case, BOM stripped, '&' → 'and', punctuation → space, whitespace collapsed."""
    h = (h or "").replace("﻿", "").replace("&", " and ").lower()
    return re.sub(r"[^a-z0-9]+", " ", h).strip()


def parse_number(text) -> Decimal | None:
    """'$45,500.00' → 45500.00 · '(1,234.5)' → -1234.5 · '-$12.00' / '$-12.00' → -12 · '37.2%' → 37.2 ·
    '--', 'N/A', '' → None.  Decimal, so a fractional share count stays exactly as written."""
    if text is None:
        return None
    s = str(text).strip().replace(" ", " ")
    if s.lower() in NULL_TOKENS:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = re.sub(r"(?i)\s*usd$", "", s)
    s = s.replace("$", "").replace(",", "").replace("%", "").replace(" ", "")
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        neg, s = (not neg), s[1:]
    if not re.fullmatch(r"\d+\.?\d*|\.\d+", s):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if neg else d


def num_as_given(d: Decimal | None):
    """JSON number that reads like the export wrote it: 50 → 50, 100.1509 → 100.1509."""
    if d is None:
        return None
    if d == d.to_integral_value():
        return int(d)
    return float(d)


_DATE_PATTERNS = [
    (r"\d{4}-\d{2}-\d{2}",                     ["%Y-%m-%d"]),
    (r"\d{4}/\d{2}/\d{2}",                     ["%Y/%m/%d"]),
    (r"\d{1,2}/\d{1,2}/\d{4}",                 ["%m/%d/%Y"]),
    (r"\d{1,2}/\d{1,2}/\d{2}(?!\d)",           ["%m/%d/%y"]),
    (r"\d{1,2}-\d{1,2}-\d{4}",                 ["%m-%d-%Y"]),
    (r"\d{1,2}-[A-Za-z]{3}-\d{4}",             ["%d-%b-%Y"]),
    (r"\d{1,2}-[A-Za-z]{3}-\d{2}(?!\d)",       ["%d-%b-%y"]),
    (r"[A-Za-z]{3,9}\.? \d{1,2}, \d{4}",       ["%b %d, %Y", "%B %d, %Y"]),
    (r"[A-Za-z]{3,9}\.? \d{1,2} \d{4}",        ["%b %d %Y", "%B %d %Y"]),
    (r"\d{1,2} [A-Za-z]{3,9}\.? \d{4}",        ["%d %b %Y", "%d %B %Y"]),
    (r"(?<!\d)\d{8}(?!\d)",                    ["%Y%m%d"]),
]


def parse_date(text) -> str | None:
    """ISO date from the ways exports write one (2026-09-16, 09/16/2026, 9/16/26, 2026/09/16,
    16-Sep-2026, Sep 16, 2026, 20260916, with or without a trailing time/zone).  Numeric forms are
    read month-first (US brokerages).  Schwab's 'MM/DD/YYYY as of MM/DD/YYYY' (posting date 'as of'
    effective date) yields the EFFECTIVE date — the day the trade actually printed."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    m = re.search(r"(?i)\bas of\b\s*(.+)$", s)
    if m:
        s = m.group(1).strip()
    for pat, fmts in _DATE_PATTERNS:
        m = re.search(pat, s)
        if not m:
            continue
        tok = m.group(0).replace(".", "")
        for f in fmts:
            try:
                return datetime.strptime(tok, f).date().isoformat()
            except ValueError:
                continue
    try:  # last resort: dateutil (present in the venv), month-first, fuzzy
        from dateutil import parser as _dp
        return _dp.parse(s, dayfirst=False, fuzzy=True).date().isoformat()
    except Exception:
        return None


def parse_stamp(line: str) -> dict | None:
    """The export's own date/time stamp, e.g. 'Positions for account ... as of 04:33 PM ET, 2026/09/16',
    'Date downloaded 09/16/2026 4:33 pm ET', 'Transactions for ... as of 09/16/2026 16:33:07 ET'.
    Returns {date, datetime (ISO with offset, or None when the line has no time), line}."""
    if not re.search(r"(?i)\b(as of|downloaded|exported|generated|export date|run date)\b", line):
        return None
    d = parse_date(line)
    if not d:
        return None
    out = {"date": d, "datetime": None, "line": line.strip()}
    t = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?\s*([A-Za-z]{1,4})?", line)
    if t:
        hh, mm = int(t.group(1)), int(t.group(2))
        ss = int(t.group(3) or 0)
        ampm = (t.group(4) or "").replace(".", "").lower()
        if ampm == "pm" and hh < 12:
            hh += 12
        if ampm == "am" and hh == 12:
            hh = 0
        tz = ZoneInfo(TZ_ABBREV.get((t.group(5) or "").upper(), "America/New_York"))
        if 0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60:
            dt = datetime.fromisoformat(d).replace(hour=hh, minute=mm, second=ss, tzinfo=tz)
            out["datetime"] = dt.isoformat(timespec="seconds")
    return out


def norm_ticker(raw: str) -> str:
    """Strip padding, trailing asterisks (Fidelity core positions 'SPAXX**'), inner spaces; upper-case.
    Suffix characters ('.', '/', '-') are kept as exported."""
    t = (raw or "").replace("﻿", "").strip().upper()
    t = t.rstrip("*").strip()
    return re.sub(r"\s+", "", t)


# ─── header mapping ──────────────────────────────────────────────────────────────────────
def map_headers(headers: list[str], table: dict) -> tuple[dict, list, list]:
    """(mapping canonical→header as written, unmatched headers, unmapped required fields)."""
    normed = [(h, norm_text(h)) for h in headers]
    claimed: set[str] = set()
    mapping: dict[str, str] = {}
    for canon, (_req, synonyms) in table.items():
        for syn in synonyms:
            hit = next((h for h, n in normed if n == syn and h not in claimed), None)
            if hit is not None:
                mapping[canon] = hit
                claimed.add(hit)
                break
    unmatched = [h for h in headers if h not in claimed and norm_text(h)]
    unmapped = [c for c, (req, _) in table.items() if req and c not in mapping]
    return mapping, unmatched, unmapped


def map_positions(headers: list[str]) -> tuple[dict, list, list]:
    mapping, unmatched, unmapped = map_headers(headers, POSITION_FIELDS)
    if "cost_basis_per_share" not in mapping and "cost_basis_total" not in mapping:
        unmapped.append("cost_basis (per-share average cost or total cost)")
    return mapping, unmatched, unmapped


def map_transactions(headers: list[str]) -> tuple[dict, list, list]:
    return map_headers(headers, TRANSACTION_FIELDS)


# ─── file model ──────────────────────────────────────────────────────────────────────────
@dataclass
class ParsedFile:
    path: Path
    kind: str                       # "positions" | "transactions" | "unrecognised"
    size: int
    header_index: int = -1
    headers: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)
    unmatched_headers: list = field(default_factory=list)
    unmapped_required: list = field(default_factory=list)
    records: list = field(default_factory=list)      # positions rows or transaction rows
    cash_lines: list = field(default_factory=list)
    skipped: list = field(default_factory=list)      # [{row, reason}]
    warnings: list = field(default_factory=list)
    stamp: dict | None = None

    @property
    def complete(self) -> bool:
        return self.kind in ("positions", "transactions") and not self.unmapped_required


def read_csv_rows(raw: bytes) -> list[list[str]]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        text = raw.decode("utf-8", errors="replace")
    text = text.replace("﻿", "")
    return [row for row in csv.reader(io.StringIO(text, newline=""))]


def sniff_header(rows: list[list[str]]) -> tuple[int, str, dict, list, list] | None:
    """Pick the header row: among the first 60 rows with ≥3 non-empty cells, the one whose mapped
    canonical fields score highest (transactions when date+action map, else positions)."""
    best = None
    for i, row in enumerate(rows[:60]):
        cells = [c.strip() for c in row]
        if sum(1 for c in cells if c) < 3:
            continue
        mp_t, um_t, ur_t = map_transactions(cells)
        mp_p, um_p, ur_p = map_positions(cells)
        if "date" in mp_t and "action" in mp_t:
            cand = (len(mp_t), i, "transactions", mp_t, um_t, ur_t)
        elif "symbol" in mp_p or "quantity" in mp_p:
            cand = (len(mp_p), i, "positions", mp_p, um_p, ur_p)
        else:
            continue
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None:
        return None
    _score, i, kind, mp, um, ur = best
    return i, kind, mp, um, ur


def _cell(rowmap: dict, header: str | None) -> str:
    if not header:
        return ""
    return (rowmap.get(header) or "").strip()


def is_cash_line(symbol: str, description: str, sectype: str, names: list[str]) -> bool:
    """symbol cell == a name (any name); security-type cell == a MULTI-word name (Schwab's 'Cash and
    Money Market' — a bare 'Cash' type is Fidelity's account type on every equity, so it never counts);
    description or symbol CONTAINS a multi-word name or 'sweep'."""
    n_sym, n_desc, n_type = norm_text(symbol), norm_text(description), norm_text(sectype)
    n_names = [norm_text(n) for n in names if norm_text(n)]
    if n_sym and n_sym in n_names:
        return True
    multi = [n for n in n_names if " " in n]
    if n_type and n_type in multi:
        return True
    for n in multi + [n for n in n_names if n == "sweep"]:
        if f" {n} " in f" {n_desc} " or f" {n} " in f" {n_sym} ":
            return True
    return False


def parse_positions(pf: ParsedFile, rows: list[list[str]], cash_names: list[str]) -> None:
    m = pf.mapping
    for k, row in enumerate(rows[pf.header_index + 1:], start=pf.header_index + 2):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        rm = dict(zip(pf.headers, cells + [""] * (len(pf.headers) - len(cells))))
        sym_raw = _cell(rm, m.get("symbol"))
        desc = _cell(rm, m.get("description"))
        stype = _cell(rm, m.get("security_type"))
        if not sym_raw and not desc:
            pf.skipped.append({"row": k, "reason": "blank symbol and description", "text": " | ".join(c for c in cells if c)[:120]})
            continue
        if norm_text(sym_raw) in TOTAL_ROW_NAMES or norm_text(sym_raw).startswith("total "):
            pf.skipped.append({"row": k, "reason": "total/summary row", "text": sym_raw[:120]})
            continue
        if is_cash_line(sym_raw, desc, stype, cash_names):
            val = parse_number(_cell(rm, m.get("market_value")))
            basis = f"{m.get('market_value')} of cash line"
            if val is None:
                q = parse_number(_cell(rm, m.get("quantity")))
                p = parse_number(_cell(rm, m.get("price")))
                if q is not None and p is not None:
                    val, basis = q * p, "quantity × price of cash line"
                elif q is not None:
                    val, basis = q, "quantity of cash line (no value column)"
            pf.cash_lines.append({"row": k, "symbol": sym_raw, "description": desc, "security_type": stype,
                                  "value": num_as_given(val), "basis": basis})
            continue
        qty = parse_number(_cell(rm, m.get("quantity")))
        if qty is None and (sum(1 for c in cells if c) <= 2 or len(sym_raw) > 60):
            pf.skipped.append({"row": k, "reason": "free-text line (disclaimer/preamble)", "text": (sym_raw or desc)[:120]})
            continue
        ticker = norm_ticker(sym_raw)
        if not ticker:
            pf.skipped.append({"row": k, "reason": "no symbol", "text": desc[:120]})
            continue
        if qty is None and m.get("quantity"):
            pf.skipped.append({"row": k, "reason": f"no quantity in '{m['quantity']}' (pending/non-position row)", "text": f"{sym_raw} {desc}"[:120]})
            continue
        price = parse_number(_cell(rm, m.get("price")))
        mval = parse_number(_cell(rm, m.get("market_value")))
        cost_ps = parse_number(_cell(rm, m.get("cost_basis_per_share")))
        cost_tot = parse_number(_cell(rm, m.get("cost_basis_total")))
        pf.records.append({"row": k, "ticker": ticker, "ticker_raw": sym_raw, "description": desc,
                           "security_type": stype, "shares": qty, "price": price, "market_value": mval,
                           "cost_per_share": cost_ps, "cost_total": cost_tot})


def classify_action(action_raw: str) -> str:
    """buy | sell | reinvest_shares | dividend | interest | fee | transfer | other."""
    a = norm_text(action_raw)
    if "reinvest" in a:
        # Schwab: 'Reinvest Dividend' (the cash leg) vs 'Reinvest Shares' (the share purchase);
        # Fidelity: 'REINVESTMENT ...' (the share purchase).
        return "dividend" if ("dividend" in a and "share" not in a) else "reinvest_shares"
    if re.search(r"\b(buy|bought|purchased?)\b", a):
        return "buy"
    if re.search(r"\b(sell|sold)\b", a):
        return "sell"
    if re.search(r"\b(dividend|div|distribution|capital gain|cap gain|lt cap|st cap)\b", a):
        return "dividend"
    if "interest" in a:
        return "interest"
    if re.search(r"\b(fee|fees|commission|adr mgmt|service charge)\b", a):
        return "fee"
    if re.search(r"\b(transfer|journal|journaled|wire|moneylink|deposit|withdrawal|contribution|eft|ach|funds received|funds paid)\b", a):
        return "transfer"
    return "other"


def parse_transactions(pf: ParsedFile, rows: list[list[str]]) -> None:
    m = pf.mapping
    for k, row in enumerate(rows[pf.header_index + 1:], start=pf.header_index + 2):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        rm = dict(zip(pf.headers, cells + [""] * (len(pf.headers) - len(cells))))
        date_raw = _cell(rm, m.get("date"))
        action_raw = _cell(rm, m.get("action"))
        if sum(1 for c in cells if c) <= 2 and not (date_raw and action_raw):
            pf.skipped.append({"row": k, "reason": "free-text line (disclaimer/preamble)", "text": " ".join(c for c in cells if c)[:120]})
            continue
        d = parse_date(date_raw)
        if d is None:
            pf.skipped.append({"row": k, "reason": f"unparseable date '{date_raw}'", "text": " | ".join(c for c in cells if c)[:120]})
            continue
        if not action_raw:
            pf.skipped.append({"row": k, "reason": "blank action", "text": " | ".join(c for c in cells if c)[:120]})
            continue
        qty = parse_number(_cell(rm, m.get("quantity")))
        sym_raw = _cell(rm, m.get("symbol"))
        pf.records.append({
            "row": k, "date": d, "date_raw": date_raw, "action_raw": action_raw,
            "category": classify_action(action_raw),
            "ticker": norm_ticker(sym_raw), "ticker_raw": sym_raw,
            "quantity": abs(qty) if qty is not None else None,       # direction lives in the action
            "quantity_as_given": qty,
            "price": parse_number(_cell(rm, m.get("price"))),
            "amount": parse_number(_cell(rm, m.get("amount"))),
            "fees": parse_number(_cell(rm, m.get("fees"))),
            "description": _cell(rm, m.get("description")),
            "settlement_date": parse_date(_cell(rm, m.get("settlement_date"))) if m.get("settlement_date") else None,
        })


def parse_file(path: Path, cash_names: list[str]) -> ParsedFile:
    raw = path.read_bytes()
    rows = read_csv_rows(raw)
    pf = ParsedFile(path=path, kind="unrecognised", size=len(raw))
    hit = sniff_header(rows)
    if hit is None:
        pf.warnings.append("no header row maps to symbol/quantity or date/action")
        return pf
    pf.header_index, pf.kind, pf.mapping, pf.unmatched_headers, pf.unmapped_required = hit
    pf.headers = [c.strip() for c in rows[pf.header_index]]
    # the export's own stamp lives in preamble/footer lines (rows with <3 populated cells)
    for row in rows:
        if sum(1 for c in row if c.strip()) < 3:
            st = parse_stamp(" ".join(c for c in row if c.strip()))
            if st:
                pf.stamp = st
                break
    if pf.kind == "positions":
        parse_positions(pf, rows, cash_names)
    else:
        parse_transactions(pf, rows)
    return pf


# ─── assembling the result ───────────────────────────────────────────────────────────────
@dataclass
class IngestResult:
    positions: ParsedFile | None
    transactions: ParsedFile | None
    files: list                       # every ParsedFile seen
    problems: list                    # fatal (exit 1) problems
    input_sha256: str | None = None
    input_files: list = field(default_factory=list)
    holdings: dict = field(default_factory=dict)
    transactions_rows: list = field(default_factory=list)
    cash: Decimal | None = None
    cash_source: str | None = None

    @property
    def complete(self) -> bool:
        return (self.positions is not None and self.positions.complete
                and (self.transactions is None or self.transactions.complete))

    @property
    def unmapped_required(self) -> dict:
        out = {}
        if self.positions and self.positions.unmapped_required:
            out["positions"] = list(self.positions.unmapped_required)
        if self.transactions and self.transactions.unmapped_required:
            out["transactions"] = list(self.transactions.unmapped_required)
        return out


def build_holdings(pos: ParsedFile) -> tuple[list[dict], Decimal | None, str | None, list[str]]:
    """Aggregate positions by ticker.  cost_basis is PER-SHARE: the exported average cost when the
    export has one, else total cost / shares (said so in cost_basis_basis)."""
    warnings: list[str] = []
    agg: dict[str, dict] = {}
    order: list[str] = []
    for r in pos.records:
        t = r["ticker"]
        if t not in agg:
            agg[t] = {"ticker": t, "ticker_raw": r["ticker_raw"], "shares": Decimal(0), "cost_total": Decimal(0),
                      "cost_known": True, "shares_known": True, "lines": 0, "basis": None, "price": r["price"]}
            order.append(t)
        a = agg[t]
        a["lines"] += 1
        if r["shares"] is None:
            a["shares_known"] = False        # quantity column unmapped/blank: best guess carries null
        sh = r["shares"] if r["shares"] is not None else Decimal(0)
        a["shares"] += sh
        if r["cost_per_share"] is not None:
            a["cost_total"] += r["cost_per_share"] * sh
            a["basis"] = a["basis"] or f"per-share average cost as exported ('{pos.mapping['cost_basis_per_share']}')"
        elif r["cost_total"] is not None:
            a["cost_total"] += r["cost_total"]
            a["basis"] = a["basis"] or f"total cost ('{pos.mapping['cost_basis_total']}') / shares"
        else:
            a["cost_known"] = False
    holdings = []
    for t in order:
        a = agg[t]
        h = {"ticker": t, "shares": num_as_given(a["shares"]) if a["shares_known"] else None}
        if a["cost_known"] and a["shares_known"] and a["shares"] != 0:
            cps = a["cost_total"] / a["shares"]
            h["cost_basis"] = round(float(cps), 4)
            h["cost_basis_basis"] = a["basis"] + (f", aggregated over {a['lines']} lines" if a["lines"] > 1 else "")
            if a["price"] is not None and a["price"] > 0 and (cps > 20 * a["price"] or cps < a["price"] / 50):
                warnings.append(f"{t}: cost basis {cps:.2f}/share vs price {a['price']} — check per-share vs total mapping")
        else:
            h["cost_basis"] = None
            h["cost_basis_basis"] = ("no cost basis in export" if not a["cost_known"]
                                     else "quantity unmapped" if not a["shares_known"] else "zero shares")
            warnings.append(f"{t}: cost basis not derivable ({h['cost_basis_basis']})")
        if a["ticker_raw"].strip() != t:
            h["ticker_raw"] = a["ticker_raw"]
        holdings.append(h)
    cash = None
    cash_source = None
    if pos.cash_lines:
        vals = [Decimal(str(c["value"])) for c in pos.cash_lines if c["value"] is not None]
        cash = sum(vals, Decimal(0)) if vals else None
        cash_source = "; ".join(f"'{c['symbol'] or c['description']}' ({c['basis']})" for c in pos.cash_lines)
        if len(pos.cash_lines) > 1:
            warnings.append(f"cash summed over {len(pos.cash_lines)} cash lines")
    else:
        warnings.append("no cash line found in the positions export (cash_names: " + ", ".join(CASH_LINE_NAMES) + ")")
    return holdings, cash, cash_source, warnings


def ingest(inbox: Path | None, positions: Path | None = None, transactions: Path | None = None,
           cash_names: list[str] | None = None) -> IngestResult:
    """Pure: reads the CSVs, writes nothing.  Files are classified by header sniffing."""
    cash_names = list(cash_names or CASH_LINE_NAMES)
    files: list[Path] = []
    if positions:
        files.append(Path(positions))
    if transactions:
        files.append(Path(transactions))
    if not files:
        if inbox is None or not Path(inbox).is_dir():
            return IngestResult(None, None, [], [f"inbox not found: {inbox}"])
        files = sorted({p.resolve() for p in Path(inbox).iterdir() if p.is_file() and p.suffix.lower() == ".csv"},
                       key=lambda p: p.name)
    parsed = [parse_file(p, cash_names) for p in files]
    problems: list[str] = []
    pos_files = [p for p in parsed if p.kind == "positions"]
    txn_files = [p for p in parsed if p.kind == "transactions"]
    for p in parsed:
        if p.kind == "unrecognised":
            problems.append(f"{p.path.name}: unrecognised CSV (no header row maps to symbol/quantity or date/action)")
    if not files:
        problems.append(f"no .csv files in {inbox}")
    if len(pos_files) > 1:
        problems.append("ambiguous: more than one positions CSV: " + ", ".join(p.path.name for p in pos_files))
    if len(txn_files) > 1:
        problems.append("ambiguous: more than one transactions CSV: " + ", ".join(p.path.name for p in txn_files))
    if not pos_files and files:
        problems.append("no positions CSV recognised (a header row with symbol + quantity + market value)")
    res = IngestResult(pos_files[0] if len(pos_files) == 1 else None,
                       txn_files[0] if len(txn_files) == 1 else None, parsed, problems)
    if res.positions is None:
        return res
    pos, txn = res.positions, res.transactions
    if txn is None:
        pos.warnings.append("no transactions CSV in inbox — hash covers the positions CSV only")
    # hash: positions bytes then transactions bytes, in that order
    h = hashlib.sha256()
    h.update(pos.path.read_bytes())
    res.input_files = [{"name": pos.path.name, "role": "positions", "bytes": pos.size}]
    if txn is not None:
        h.update(txn.path.read_bytes())
        res.input_files.append({"name": txn.path.name, "role": "transactions", "bytes": txn.size})
    res.input_sha256 = h.hexdigest()
    holdings, cash, cash_source, warns = build_holdings(pos)
    pos.warnings.extend(warns)
    res.cash, res.cash_source = cash, cash_source
    stamp = pos.stamp or (txn.stamp if txn else None)
    et_now = now_et()
    as_of = stamp["date"] if stamp else et_now.strftime("%Y-%m-%d")
    if stamp and stamp.get("datetime"):
        exported_at = stamp["datetime"]
    else:
        exported_at = datetime.fromtimestamp(pos.path.stat().st_mtime, tz=ET).isoformat(timespec="seconds")
    res.holdings = {
        "cadence": "on_change",
        "as_of": as_of,
        "source": "brokerage export",
        "exported_at": exported_at,
        "exported_at_basis": ("export stamp: " + stamp["line"]) if (stamp and stamp.get("datetime"))
                             else "positions file mtime (no time stamp in the export)",
        "input_sha256": res.input_sha256,
        "input_files": res.input_files,
        "ingested_at": et_now.isoformat(timespec="seconds"),
        "cash": num_as_given(cash),
        "cash_source": cash_source,
        "holdings": holdings,
    }
    if not res.complete:
        res.holdings["_unmapped_required"] = res.unmapped_required
        res.holdings["_note"] = "BEST GUESS ONLY — a required column is unmapped; nothing served was written"
    if txn is not None:
        res.transactions_rows = txn.records
    return res


# ─── writers ─────────────────────────────────────────────────────────────────────────────
TXN_COLUMNS = ["date", "date_raw", "action_raw", "category", "ticker", "ticker_raw", "quantity",
               "quantity_as_given", "price", "amount", "fees", "description", "settlement_date", "row"]


def _json_default(o):
    if isinstance(o, Decimal):
        return num_as_given(o)
    if isinstance(o, Path):
        return str(o)
    return str(o)


def mapping_report(res: IngestResult, cash_names: list[str]) -> dict:
    def fileblock(pf: ParsedFile | None):
        if pf is None:
            return None
        return {"file": pf.path.name, "bytes": pf.size, "kind": pf.kind, "header_row": pf.header_index + 1,
                "headers": pf.headers, "mapping": pf.mapping, "unmatched_headers": pf.unmatched_headers,
                "unmapped_required": pf.unmapped_required, "stamp": pf.stamp, "n_records": len(pf.records),
                "cash_lines": pf.cash_lines, "skipped_rows": pf.skipped, "warnings": pf.warnings}
    return {"created_at": now_et().isoformat(timespec="seconds"),
            "complete": res.complete, "problems": res.problems,
            "input_sha256": res.input_sha256, "input_files": res.input_files,
            "cash": num_as_given(res.cash), "cash_source": res.cash_source, "cash_names": cash_names,
            "positions": fileblock(res.positions), "transactions": fileblock(res.transactions),
            "other_files": [fileblock(p) for p in res.files if p not in (res.positions, res.transactions)]}


def write_scratch(res: IngestResult, scratch_root: Path, cash_names: list[str]) -> Path:
    stamp = now_et().strftime("%Y%m%dT%H%M%S")
    out = scratch_root / f"ingest_{stamp}"
    n = 1
    while out.exists():
        n += 1
        out = scratch_root / f"ingest_{stamp}_{n}"
    out.mkdir(parents=True)
    with open(out / "holdings_candidate.json", "w") as f:
        json.dump(res.holdings, f, indent=2, default=_json_default)
        f.write("\n")
    with open(out / "mapping.json", "w") as f:
        json.dump(mapping_report(res, cash_names), f, indent=2, default=_json_default)
        f.write("\n")
    with open(out / "transactions_parsed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TXN_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in res.transactions_rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in TXN_COLUMNS})
    return out


def write_served(res: IngestResult, data_dir: Path) -> Path:
    if not res.complete:
        raise RuntimeError("refusing to write served holdings from an incomplete mapping")
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "holdings.json"
    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(res.holdings, f, indent=2, default=_json_default)
        f.write("\n")
    tmp.replace(target)
    # Order 16-Sept 2.3: the export's own positions and cash, served beside holdings.json so the
    # referee can compare the served book with the latest export (set equality → CRITICAL, cash
    # within 1 percent → HIGH). Same information as holdings.json; no account identifiers.
    export_rec = {
        "cadence": "on_change", "as_of": res.holdings["as_of"], "source": "brokerage export (parsed positions)",
        "exported_at": res.holdings["exported_at"], "input_sha256": res.input_sha256, "input_files": res.input_files,
        "cash": res.holdings["cash"],
        "positions": [{"ticker": h["ticker"], "shares": h["shares"]} for h in res.holdings["holdings"]],
    }
    with open(data_dir / "holdings_export.json", "w") as f:
        json.dump(export_rec, f, indent=2, default=_json_default)
        f.write("\n")
    return target


# ─── CLI ─────────────────────────────────────────────────────────────────────────────────
def print_report(res: IngestResult) -> None:
    for pf in res.files:
        print(f"\n[{pf.kind}] {pf.path.name} ({pf.size} bytes) header row {pf.header_index + 1}")
        if pf.kind == "unrecognised":
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
        if pf.skipped:
            print(f"  skipped rows: {len(pf.skipped)}")
            for s in pf.skipped[:12]:
                print(f"    row {s['row']}: {s['reason']} — {s['text']}")
        for w in pf.warnings:
            print(f"  warn: {w}")
    if res.positions:
        print("\nparsed positions:")
        for h in res.holdings.get("holdings", []):
            print(f"  {h['ticker']:8s} shares {h['shares']!s:>12}  cost_basis {h.get('cost_basis')!s:>10}  ({h.get('cost_basis_basis')})")
        print(f"cash: {res.holdings.get('cash')}  ← {res.cash_source}")
        print(f"as_of {res.holdings.get('as_of')} · exported_at {res.holdings.get('exported_at')} · input_sha256 {res.input_sha256}")
    if res.transactions:
        cats: dict[str, int] = {}
        for r in res.transactions_rows:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        print(f"\nparsed transactions: {len(res.transactions_rows)} rows by category {cats}")
    for p in res.problems:
        print(f"PROBLEM: {p}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("Usage")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inbox", default=str(INBOX), help="directory holding the exported CSVs (default: repo inbox/)")
    ap.add_argument("--write", action="store_true", help="write data/holdings.json (only with a complete mapping)")
    ap.add_argument("--dry-run", action="store_true", help="never write under data/ (default behaviour; overrides --write)")
    ap.add_argument("--data-dir", default=str(DATA), help="served data directory (default: repo data/)")
    ap.add_argument("--scratch", default=str(SCRATCH), help="scratch root for the best-guess output (default: repo scratch/)")
    ap.add_argument("--cash-names", default="", help="comma-separated extra names for the cash line")
    ap.add_argument("--positions", help="positions CSV (skips inbox sniffing for this role)")
    ap.add_argument("--transactions", help="transactions CSV (skips inbox sniffing for this role)")
    args = ap.parse_args(argv)

    cash_names = CASH_LINE_NAMES + [s.strip() for s in args.cash_names.split(",") if s.strip()]
    res = ingest(Path(args.inbox) if not (args.positions or args.transactions) else None,
                 positions=Path(args.positions) if args.positions else None,
                 transactions=Path(args.transactions) if args.transactions else None,
                 cash_names=cash_names)
    print_report(res)
    if res.positions is None or res.problems:
        for p in res.problems:
            print(f"error: {p}", file=sys.stderr)
        print("nothing written.", file=sys.stderr)
        return 1
    out = write_scratch(res, Path(args.scratch), cash_names)
    print(f"\nbest guess written to {out}/ (holdings_candidate.json, mapping.json, transactions_parsed.csv)")
    if not res.complete:
        sys.stdout.flush()
        print(f"UNMAPPED REQUIRED COLUMNS {json.dumps(res.unmapped_required)} — nothing served written (exit 2)", file=sys.stderr)
        return 2
    if args.write and not args.dry_run:
        target = write_served(res, Path(args.data_dir))
        print(f"served: wrote {target} ({len(res.holdings['holdings'])} holdings, cash {res.holdings['cash']})")
    else:
        print("dry run: nothing written under data/ (pass --write to publish holdings.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
