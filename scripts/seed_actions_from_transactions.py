#!/usr/bin/env python3
"""
seed_actions_from_transactions.py — holdings order Phase 2, item (2.2): brokerage transactions →
data/actions.jsonl (append-only), tier 5_werner.

The execution order, quoted verbatim:

    "For each transaction, append an entry to actions.jsonl: date, action, ticker, quantity,
    price, the regime index and label on that date from the published vintage, and the
    system's signal record for that ticker on that date where one exists. ... Entries carry
    source: "brokerage transactions"; no entry is fabricated for a trade the export does not
    contain."

Usage
    seed_actions_from_transactions.py [--parsed FILE | --scratch DIR | --inbox DIR]
        [--actions data/actions.jsonl] [--vintage data/regime_daily_published.csv] [--repo REPO]
        [--dry-run] [--write] [--no-signals] [--include-reinvest]
        [--skip-seen-in-other-exports] [--export-sha256 HEX]

  * Input: the ingest job's transactions_parsed.csv (+ mapping.json for the export hash) —
    by default the newest scratch/ingest_*/ — or the raw CSVs in inbox/ (re-parsed in memory
    with ingest_brokerage.py; nothing is written by that path).
  * One entry per BUY / SELL transaction.  Dividends, interest, fees, transfers and dividend
    reinvestments are skipped, counted and reported (--include-reinvest seeds 'Reinvest
    Shares' / 'REINVESTMENT' purchases as buys, flagged in `note`).
  * Idempotent: an entry already present with the same date, ticker, action, quantity, price
    is not appended twice — whatever export it came from (a trade is one fact; the lead's
    decision 2026-09-16).  --append-seen-in-other-exports restores the per-hash behaviour.
  * Default is a dry run that prints the entries.  --write appends to data/actions.jsonl.
  * Git history is read (git log / git show, read-only) to find the ticker_signals.json the
    system published for the trade's session.  --no-signals skips that lookup.

Entry shape (keys in this order, matching scripts/compute_nav.py log_actions conventions):
    session_date  the ET session the trade printed on — a weekend/holiday trade date maps to
                  the NEXT session and both dates are kept (`session_note` says so)
    date          the trade date as exported (ISO; `date_raw` keeps the export's text when
                  it differs, e.g. Schwab's 'MM/DD/YYYY as of MM/DD/YYYY')
    tier          "5_werner"       source  "brokerage transactions"
    action        ["buy"] | ["sell"]      ticker · quantity · price · amount (as exported)
    regime        label of the published R on that session (thresholds as
                  compute_nav.regime_label: <0.30 LOW RISK, <0.50 ELEVATED, <0.70 HIGH RISK,
                  else CRISIS)
    R_full        the published R (data/regime_daily_published.csv) on that session, or null
                  with `regime_note` = "no published vintage for this session" or
                  "no_publish_reason: <as the CSV records>"
    signal        that ticker's record from the ticker_signals.json committed for that
                  session, or null; `signal_source` "data/ticker_signals.json@<short sha>";
                  `signal_match` says which rule found the commit (the file whose top-level
                  session_date == the session, else the last nightly '📊' commit at or before
                  23:59 ET of that date); `signal_note` when the file has no record for the
                  ticker or the lookup was disabled/unavailable
    export_sha256 the ingest hash (positions bytes + transactions bytes)
    action_raw · fees · note · logged_at
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
SCRATCH = REPO / "scratch"
INBOX = REPO / "inbox"
ET = ZoneInfo("America/New_York")
SIGNALS_PATH = "data/ticker_signals.json"
NIGHTLY_SUBJECT = re.compile(r"^\s*\U0001F4CA\s*\d{4}-\d{2}-\d{2}")   # "📊 2026-09-11"
TIER = "5_werner"
SOURCE = "brokerage transactions"

sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day, now_et  # noqa: E402
import ingest_brokerage as ib  # noqa: E402


# ─── regime: the published vintage ───────────────────────────────────────────────────────
def regime_label(R: float) -> str:
    """Identical to scripts/compute_nav.py regime_label (edges 0.30 / 0.50 / 0.70)."""
    return "LOW RISK" if R < 0.30 else "ELEVATED" if R < 0.50 else "HIGH RISK" if R < 0.70 else "CRISIS"


class PublishedVintage:
    """data/regime_daily_published.csv: date, R_t_published, no_publish_reason — the R the system
    actually printed for each session (append-only, never recomputed)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.rows: dict[str, dict] = {}
        with open(self.path, newline="") as f:
            for r in csv.DictReader(f):
                self.rows[(r.get("date") or "").strip()[:10]] = r

    def lookup(self, session: str) -> tuple[float | None, str | None, str | None]:
        """(R_full, label, note)."""
        r = self.rows.get(session)
        if r is None:
            return None, None, "no published vintage for this session"
        v = (r.get("R_t_published") or "").strip()
        if not v:
            reason = (r.get("no_publish_reason") or "").strip() or "blank R_t_published"
            return None, None, f"no_publish_reason: {reason}"
        R = float(v)
        return R, regime_label(R), None


# ─── session mapping ─────────────────────────────────────────────────────────────────────
def session_for(trade_date: str) -> tuple[str, str | None]:
    """The ET session a trade printed on: the trade date itself when it is a session; a weekend
    or holiday date maps to the NEXT session (the trade cannot have printed before it opened)."""
    if is_trading_day(trade_date):
        return trade_date, None
    d = date.fromisoformat(trade_date)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d.isoformat(), (f"trade date {trade_date} is not a session (weekend/holiday); "
                           f"mapped to the next session {d.isoformat()}")


# ─── signals: the nightly file from git history ──────────────────────────────────────────
class SignalIndex:
    """Read-only git lookups of data/ticker_signals.json by session.

    Rule (execution order): the commit whose file carries top-level session_date == the session
    (the latest such commit — the final version published for that session); else the last
    nightly ('📊 YYYY-MM-DD') commit at or before 23:59 ET of that date (older files carry only
    `updated`)."""

    def __init__(self, repo: Path, path: str = SIGNALS_PATH):
        self.repo, self.path = Path(repo), path
        self.commits: list[tuple[str, datetime, str]] = []   # newest first: (sha, committed ET, subject)
        self._files: dict[str, dict | None] = {}
        self.error: str | None = None
        try:
            out = subprocess.run(["git", "-C", str(self.repo), "log", "--format=%H%x1f%cI%x1f%s", "--", path],
                                 capture_output=True, text=True, check=True, encoding="utf-8")
        except (OSError, subprocess.CalledProcessError) as e:
            self.error = f"git history unavailable: {getattr(e, 'stderr', None) or e}"
            return
        for line in out.stdout.splitlines():
            parts = line.split("\x1f", 2)
            if len(parts) != 3:
                continue
            sha, ci, subj = parts
            try:
                dt = datetime.fromisoformat(ci).astimezone(ET)
            except ValueError:
                continue
            self.commits.append((sha, dt, subj))
        if not self.commits:
            self.error = f"no commits touch {path}"

    def file_at(self, sha: str) -> dict | None:
        if sha not in self._files:
            try:
                out = subprocess.run(["git", "-C", str(self.repo), "show", f"{sha}:{self.path}"],
                                     capture_output=True, check=True)
                self._files[sha] = json.loads(out.stdout.decode("utf-8"))
            except (OSError, subprocess.CalledProcessError, ValueError):
                self._files[sha] = None
        return self._files[sha]

    def find(self, session: str) -> tuple[str | None, dict | None, str]:
        """(sha, file, match note) for the session, or (None, None, why)."""
        if self.error:
            return None, None, self.error
        s0 = datetime.fromisoformat(session).replace(tzinfo=ET)
        s_end = s0 + timedelta(days=1) - timedelta(seconds=1)      # 23:59:59 ET of the session
        # rule 1: file whose session_date == session (committed on the session or within a week after)
        for sha, dt, subj in self.commits:                          # newest first
            if s0 <= dt <= s0 + timedelta(days=8):
                f = self.file_at(sha)
                if f and str(f.get("session_date", ""))[:10] == session:
                    return sha, f, f"session_date == {session} ({subj}, committed {dt.isoformat(timespec='seconds')})"
        # rule 2: last nightly commit at or before 23:59 ET of that date
        for sha, dt, subj in self.commits:
            if dt <= s_end and NIGHTLY_SUBJECT.match(subj):
                f = self.file_at(sha)
                if f is None:
                    continue
                stamp = f.get("session_date") or f.get("updated")
                return sha, f, (f"last nightly commit at or before {session}T23:59 ET ({subj}, committed "
                                f"{dt.isoformat(timespec='seconds')}; file stamp {stamp})")
        return None, None, f"no nightly ticker_signals.json commit at or before {session}T23:59 ET"

    def lookup(self, session: str, ticker: str) -> tuple[dict | None, str | None, str, str | None]:
        """(signal record, signal_source, signal_match, signal_note)."""
        sha, f, note = self.find(session)
        if f is None:
            return None, None, note, "no signal file for this session"
        src = f"{self.path}@{sha[:7]}"
        sigs = f.get("signals")
        rec = None
        if isinstance(sigs, dict):
            rec = sigs.get(ticker)
        elif isinstance(sigs, list):
            rec = next((r for r in sigs if isinstance(r, dict) and r.get("ticker") == ticker), None)
        if rec is None:
            return None, src, note, f"no record for {ticker} in that file ({(len(sigs) if sigs else 0)} tickers)"
        return rec, src, note, None


# ─── inputs ──────────────────────────────────────────────────────────────────────────────
def _num(x):
    if x is None or x == "":
        return None
    try:
        return ib.num_as_given(Decimal(str(x)))
    except Exception:
        return None


def load_parsed_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("quantity", "quantity_as_given", "price", "amount", "fees"):
            r[k] = _num(r.get(k))
        for k in ("date", "date_raw", "action_raw", "category", "ticker", "ticker_raw", "description"):
            r[k] = (r.get(k) or "").strip()
    return rows


def newest_ingest_dir(scratch_root: Path) -> Path | None:
    cands = [p for p in Path(scratch_root).glob("ingest_*") if (p / "transactions_parsed.csv").exists()]
    return max(cands, key=lambda p: p.name) if cands else None


def load_transactions(args) -> tuple[list[dict], str | None, str]:
    """(rows, export_sha256, description of where they came from)."""
    if args.inbox:
        res = ib.ingest(Path(args.inbox))
        if res.positions is None or res.problems:
            raise SystemExit("inbox ingest failed: " + "; ".join(res.problems or ["no positions CSV"]))
        if res.transactions is None:
            raise SystemExit(f"no transactions CSV recognised in {args.inbox}")
        if res.transactions.unmapped_required:
            raise SystemExit(f"transactions CSV has unmapped required columns: {res.transactions.unmapped_required}")
        rows = json.loads(json.dumps(res.transactions_rows, default=ib._json_default))
        return rows, res.input_sha256, f"inbox {args.inbox} ({res.transactions.path.name}, parsed in memory)"
    parsed = Path(args.parsed) if args.parsed else None
    if parsed is None:
        d = Path(args.scratch) if args.scratch else None
        if d and d.name.startswith("ingest_") and (d / "transactions_parsed.csv").exists():
            parsed = d / "transactions_parsed.csv"
        else:
            nd = newest_ingest_dir(d or SCRATCH)
            if nd is None:
                raise SystemExit(f"no scratch/ingest_*/transactions_parsed.csv under {d or SCRATCH}; run ingest_brokerage.py first or pass --inbox")
            parsed = nd / "transactions_parsed.csv"
    if not parsed.exists():
        raise SystemExit(f"not found: {parsed}")
    sha = args.export_sha256
    mp = parsed.parent / "mapping.json"
    if sha is None and mp.exists():
        sha = json.load(open(mp)).get("input_sha256")
    if sha is None:
        raise SystemExit(f"no export hash: {mp} missing input_sha256 and no --export-sha256 given")
    return load_parsed_csv(parsed), sha, str(parsed)


def existing_keys(actions_path: Path) -> tuple[set, set, int]:
    """Keys of brokerage entries already in actions.jsonl: full (with export hash) and loose."""
    full, loose, n = set(), set(), 0
    if not actions_path.exists():
        return full, loose, 0
    with open(actions_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("source") != SOURCE:
                continue
            k = key_of(rec)
            loose.add(k)
            full.add(k + (rec.get("export_sha256"),))
    return full, loose, n


def _r6(x):
    return None if x is None else round(float(x), 6)


def key_of(rec: dict) -> tuple:
    act = rec.get("action")
    act = act[0] if isinstance(act, list) and act else act
    return (rec.get("date"), rec.get("ticker"), act, _r6(rec.get("quantity")), _r6(rec.get("price")))


# ─── entries ─────────────────────────────────────────────────────────────────────────────
def build_entry(txn: dict, vintage: PublishedVintage, signals: SignalIndex | None,
                export_sha: str, include_reinvest: bool) -> dict | None:
    cat = txn.get("category") or ib.classify_action(txn.get("action_raw", ""))
    note = None
    if cat == "buy":
        action = "buy"
    elif cat == "sell":
        action = "sell"
    elif cat == "reinvest_shares" and include_reinvest:
        action, note = "buy", f"dividend reinvestment (export action: {txn.get('action_raw')})"
    else:
        return None
    trade_date = txn["date"]
    session, session_note = session_for(trade_date)
    R, label, regime_note = vintage.lookup(session)
    rec = {"session_date": session, "date": trade_date}
    if txn.get("date_raw") and txn["date_raw"] != trade_date:
        rec["date_raw"] = txn["date_raw"]
    if session_note:
        rec["session_note"] = session_note
    rec.update({"tier": TIER, "source": SOURCE, "action": [action], "ticker": txn["ticker"],
                "quantity": txn.get("quantity"), "price": txn.get("price"), "amount": txn.get("amount"),
                "regime": label, "R_full": R})
    if regime_note:
        rec["regime_note"] = regime_note
    if signals is not None:
        sig, src, match, snote = signals.lookup(session, txn["ticker"])
        rec["signal"], rec["signal_source"], rec["signal_match"] = sig, src, match
        if snote:
            rec["signal_note"] = snote
    else:
        rec["signal"], rec["signal_source"] = None, None
        rec["signal_note"] = "signal lookup disabled (--no-signals)"
    rec["export_sha256"] = export_sha
    rec["action_raw"] = txn.get("action_raw")
    if txn.get("fees") not in (None, 0):
        rec["fees"] = txn["fees"]
    if note:
        rec["note"] = note
    rec["logged_at"] = now_et().isoformat(timespec="seconds")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("Usage")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--parsed", help="transactions_parsed.csv written by ingest_brokerage.py")
    src.add_argument("--scratch", help="scratch root (newest ingest_*/ is used) or one ingest_*/ directory")
    src.add_argument("--inbox", help="re-parse the raw CSVs in this inbox directory (nothing written)")
    ap.add_argument("--actions", default=str(DATA / "actions.jsonl"), help="action log to append to")
    ap.add_argument("--vintage", default=str(DATA / "regime_daily_published.csv"), help="published regime vintage CSV")
    ap.add_argument("--repo", default=str(REPO), help="git repository holding data/ticker_signals.json history")
    ap.add_argument("--write", action="store_true", help="append the new entries to --actions")
    ap.add_argument("--dry-run", action="store_true", help="print the entries, write nothing (default; overrides --write)")
    ap.add_argument("--no-signals", action="store_true", help="skip the git lookup of ticker_signals.json")
    ap.add_argument("--include-reinvest", action="store_true", help="seed dividend-reinvestment share purchases as buys")
    ap.add_argument("--skip-seen-in-other-exports", action="store_true", default=True,
                    help="(default) skip a trade already logged from a different export (same date/ticker/action/quantity/price) — a trade is one fact however many exports carry it")
    ap.add_argument("--append-seen-in-other-exports", dest="skip_seen_in_other_exports", action="store_false",
                    help="append a trade again when a later export carries it under a new hash")
    ap.add_argument("--export-sha256", help="override the export hash (when mapping.json is absent)")
    args = ap.parse_args(argv)

    rows, export_sha, where = load_transactions(args)
    vintage = PublishedVintage(Path(args.vintage))
    signals = None if args.no_signals else SignalIndex(Path(args.repo))
    if signals is not None and signals.error:
        print(f"warn: {signals.error} — signal fields will be null", file=sys.stderr)
    actions_path = Path(args.actions)
    full, loose, n_lines = existing_keys(actions_path)

    print(f"transactions: {len(rows)} rows from {where}")
    print(f"export_sha256: {export_sha}")
    print(f"action log: {actions_path} ({n_lines} lines, {len(full)} brokerage entries already present)")

    new, dup_same, dup_other, skipped = [], [], [], {}
    for txn in rows:
        rec = build_entry(txn, vintage, signals, export_sha, args.include_reinvest)
        if rec is None:
            cat = txn.get("category") or "other"
            skipped[cat] = skipped.get(cat, 0) + 1
            continue
        k = key_of(rec)
        if k + (export_sha,) in full:
            dup_same.append(rec)
            continue
        if k in loose:
            dup_other.append(rec)
            if args.skip_seen_in_other_exports:
                continue
        full.add(k + (export_sha,))
        loose.add(k)
        new.append(rec)

    print(f"skipped (not trades): {skipped or '—'}")
    print(f"already present from this export: {len(dup_same)}")
    if dup_other:
        print(f"seen in an earlier export (same date/ticker/action/quantity/price, other hash): {len(dup_other)}"
              + (" — skipped (default; --append-seen-in-other-exports appends them)" if args.skip_seen_in_other_exports else " — appended again (--append-seen-in-other-exports)"))
    print(f"new entries: {len(new)}")
    for rec in new:
        print(f"  {rec['session_date']}  {rec['action'][0]:4s} {rec['ticker']:6s} qty {rec['quantity']!s:>10} @ {rec['price']!s:>9}"
              f"  regime {rec['regime']} R {rec['R_full']}  signal {rec.get('signal_source') or '—'}"
              + (f"  [{rec['session_note']}]" if rec.get("session_note") else "")
              + (f"  [{rec['regime_note']}]" if rec.get("regime_note") else ""))

    if args.write and not args.dry_run:
        if new:
            actions_path.parent.mkdir(parents=True, exist_ok=True)
            with open(actions_path, "a") as f:
                for rec in new:
                    f.write(json.dumps(rec, default=str) + "\n")
        print(f"appended {len(new)} entries to {actions_path}")
    else:
        print("\ndry run — the entries that --write would append:")
        for rec in new:
            print(json.dumps(rec, default=str))
        print(f"\ndry run: nothing written ({len(new)} entries would be appended to {actions_path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
