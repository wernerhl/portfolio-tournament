#!/usr/bin/env python3
"""mistakes_ledger.py — the mistakes ledger, data/mistakes.jsonl, append-only, one entry per error by
anyone in the loop: the system, the agent, the operator, or the advisory model that writes the orders
(Tournament Audit and Execution Order of 30 September 2026, section 3 / T6).

Fields: date found, who, what was wrong, how it was detected, what it cost (dollars, sessions or
credibility), the fix, and the referee check that now catches a recurrence. No entry is ever edited; a
correction is a new entry referencing the old (kind "correction", refers_to). Operator decisions enter
from the brokerage transactions export (kind "operator_decision") with the stated reason at the time,
and 20 and 60 sessions later their outcome against the alternative of not trading (kind "outcome").
Every entry carries its own sha256; the referee raises CRITICAL when an entry no longer matches it.

  python scripts/mistakes_ledger.py seed                      # the verified seed entries of the order (idempotent)
  python scripts/mistakes_ledger.py append --who … --error … --detected-by … --cost … --fix … --check … [--kind …] [--refers-to ID]
  python scripts/mistakes_ledger.py verify                    # hashes and references
  python scripts/mistakes_ledger.py test-append              # acceptance 7.6: appends a test entry to a COPY and shows prior entries unchanged
  python scripts/mistakes_ledger.py from-trades [--write]     # operator decisions and their +20/+60 outcomes from the export-based ledger
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
LEDGER = DATA / "mistakes.jsonl"
sys.path.insert(0, str(HERE))
from trading_calendar import now_et, is_trading_day  # noqa: E402

WHO = ("system", "agent", "operator", "advisor")
KINDS = ("failure", "operator_decision", "outcome", "correction", "test")

# The seed entries, verified (section 3 of the order); fix and referee check as they stand today.
SEED = [
    ("2026-09-30", "system", "Operator tier never matched the account; the 27.9% re-seed step of 29 September read as return",
     "this audit (order 30-Sept, 2.1)",
     "credibility: every comparison of the operator's picks against the algorithms since the operator's first summer trade is invalid; 27.9 points of spurious return on 29 September",
     "the tier is marked not comparable and excluded from rankings; the re-seed is recorded as an event; a comparable series excludes the step; the tier will be rebuilt from the brokerage transactions export ([T3], order 4.4)",
     "tournament:werner_comparable (the block must exist and the tier stay excluded until rebuilt); book:holdings_mismatch (CRITICAL)"),
    ("2026-09-30", "system", "12 sessions missing from the tournament history (24 and 26 June, 27 August, 16–28 September); the HIGH finding left unresolved",
     "referee (tournament:gaps), then this audit (2.2)",
     "12 sessions of history; the whole MU trade window unobserved by the tournament",
     "backfilled under the as-published convention and marked; compute_nav backfills before it appends; the vintage records no-publish rows on its own ([T1])",
     "tournament:gaps (CRITICAL for any future gap)"),
    ("2026-09-30", "system", "Regime label enters ELEVATED below the corridor's 0.32 (0.3173, 0.3198, 0.3022 and three more); 17 label changes in four months",
     "this audit (2.3)",
     "17 label changes where the corridor gives 5; under the brief's colour rules the one-session flip of 10 September would have painted the log red",
     "one label function with the hysteresis corridor (scripts/regime_label.py) in every consumer — the tournament rows, the brief, the action ledger — from 30 September ([T3])",
     "label:corridor (CRITICAL on a row whose label is not the corridor's), label:hysteresis"),
    ("2026-09-30", "system", "GOOG and GOOGL held together in tier 2 (6.9 percent combined): one company counted as two names",
     "this audit (2.4)",
     "one issuer counted twice in a 20-name tier",
     "the union universe keeps one class per dual-class issuer (data/share_classes.json, the more liquid class); a guard in tier selection; applies at the 1 October reconstitution ([T3])",
     "tournament:issuer_dup (a tier holding two classes of one issuer)"),
    ("2026-09-30", "system", "Daily cash targets computed from the regime index but never executed between month-start trades (tier 4: 11.0 points on 3 June; mean gap 2.5, maximum 14.2)",
     "this audit (1)",
     "the dashboard presented a daily regime-sized strategy whose net asset values were those of a monthly one",
     "continuous twins 1c–4c with banded execution run as a live contest; the monthly tiers stay as controls; replacement only after the registered comparison ([T4], [T5])",
     "twins:cash_gap (a twin's cash gap above 5 points after execution), twins:freshness"),
    ("2026-09-30", "advisor", "The 16 September holdings order did not specify how the operator tier absorbs a holdings change, producing the re-seed step (2.1)",
     "this audit",
     "same as the re-seed entry: an invalid comparison and a 27.9-point artifact",
     "order 30-Sept 4.4: the operator tier from trades only; not comparable until then; the step recorded",
     "tournament:werner_comparable"),
    ("2026-09-30", "advisor", "The 26 September lens specification defined the event variance against a back month, which collapses for distant events (GEV read 2.9%, NVDA 2.2%)",
     "output review",
     "the event board understated held-name event risk by four to seven points for four sessions",
     "the bracketing method: the last expiry before the release against the first after it ([C1], order 30-Sept)",
     "options:event_method"),
    ("2026-09-25", "advisor", "Stated that MU's earnings were past when they were five days ahead",
     "the operator's chart",
     "credibility; the lens's own event line, built on the provider's date, was right",
     "earnings dates come from the provider's calendar into the event calendar and the event board; the advisor reads the served date",
     "options:next_earnings (a held name without a next-earnings date)"),
    ("2026-09-16", "advisor", "Called 33 percent cash defensive; in risk terms the book was the most aggressive posture tested",
     "the beta computation",
     "a wrong reading of the book's posture on the day the order was written",
     "the book-aware sizing panel translates every rule to the book's beta (comparators.json) so posture is read in risk terms",
     "comparators freshness (tournament:freshness on comparators.json)"),
    ("2026-09-09", "advisor", "Stated that BMNR was absent from the book; the account held it",
     "brokerage screenshot",
     "credibility; a holdings diff built on a wrong premise",
     "data/holdings.json as the only holdings source (P3.1); the ingestion job from the brokerage export",
     "book:holdings_mismatch, book:holdings_age"),
    ("2026-09-08", "advisor", "Registered a decision rule with no discriminating power (ledger Failure 14)",
     "the result",
     "one retirement-test run judged by a rule no contestant could satisfy",
     "the v2 registration applies the discriminating-power check first (C3 v2); the same convention in C6 ([T5])",
     "registration convention: a power check reported before the real comparison (c6_power_check.json)"),
    ("2026-09-07", "advisor", "Reported a frozen v4 series that was isotonic step behaviour; inferred a seven-week outage that lasted one run",
     "code and git history",
     "credibility; a remediation order built on a misread symptom",
     "the referee's frozen-row check exempts isotonic and step-mapped columns; symptoms are checked against code and history before they are named",
     "tournament:frozen with the isotonic exemption"),
    ("2026-07-29", "advisor", "Claimed value-score saturation and 'every name below entry' (27 of 40)",
     "agent verification",
     "credibility",
     "claims about served data are verified against the files before they are stated",
     "none mechanical; recorded"),
]


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def read(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def entry_hash(e: dict) -> str:
    return sha({k: v for k, v in e.items() if k != "entry_sha256"})


def make(found: str, who: str, error: str, detected_by: str, cost: str, fix: str, check: str, kind: str = "failure",
         refers_to: str | None = None, seq: int | None = None, extra: dict | None = None, existing: list | None = None) -> dict:
    assert who in WHO, f"who must be one of {WHO}"
    assert kind in KINDS, f"kind must be one of {KINDS}"
    existing = existing if existing is not None else read()
    n = seq or (1 + sum(1 for e in existing if e.get("found") == found))
    e = {"entry_id": f"mistake-{found}-{n}", "found": found, "who": who, "kind": kind, "error": error, "detected_by": detected_by,
         "cost": cost, "fix": fix, "referee_check": check, "refers_to": refers_to,
         "logged_at": now_et().isoformat(timespec="seconds")}
    if extra:
        e.update(extra)
    e["entry_sha256"] = entry_hash(e)
    return e


def append(e: dict, path: Path = LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")


def verify(path: Path = LEDGER) -> list[str]:
    problems = []
    entries = read(path); ids = {e.get("entry_id") for e in entries}
    for e in entries:
        if entry_hash(e) != e.get("entry_sha256"):
            problems.append(f"{e.get('entry_id')}: content does not match its hash (edited)")
        if e.get("refers_to") and e["refers_to"] not in ids:
            problems.append(f"{e.get('entry_id')}: refers to unknown entry {e['refers_to']}")
        if e.get("who") not in WHO or e.get("kind") not in KINDS:
            problems.append(f"{e.get('entry_id')}: who/kind outside the vocabulary")
    if len(ids) != len(entries):
        problems.append("duplicate entry ids")
    return problems


def cmd_seed(args) -> int:
    existing = read()
    keys = {(e.get("found"), e.get("who"), e.get("error")) for e in existing}
    n = 0
    for found, who, err, det, cost, fix, check in SEED:
        if (found, who, err) in keys:
            continue
        e = make(found, who, err, det, cost, fix, check, existing=existing)
        append(e); existing.append(e); n += 1
    print(f"[mistakes_ledger] seeded {n} entr{'y' if n == 1 else 'ies'} ({len(existing)} in the ledger)")
    return 0


def cmd_append(args) -> int:
    e = make(args.found or now_et().strftime("%Y-%m-%d"), args.who, args.error, args.detected_by, args.cost, args.fix, args.check,
             kind=args.kind, refers_to=args.refers_to)
    if args.refers_to and args.refers_to not in {x.get("entry_id") for x in read()}:
        raise SystemExit(f"[mistakes_ledger] refers_to {args.refers_to} is not in the ledger")
    append(e)
    print(f"[mistakes_ledger] appended {e['entry_id']}")
    return 0


def cmd_verify(args) -> int:
    p = verify()
    print("[mistakes_ledger] " + ("ledger intact: every entry matches its hash" if not p else "PROBLEMS: " + "; ".join(p)))
    return 0 if not p else 2


def cmd_test_append(args) -> int:
    """Acceptance 7.6: one test entry appends without altering prior entries — on a COPY."""
    with tempfile.TemporaryDirectory() as td:
        cp = Path(td) / "mistakes.jsonl"
        if LEDGER.exists():
            shutil.copy2(LEDGER, cp)
        before = read(cp); hashes_before = [e["entry_sha256"] for e in before]
        e = make(now_et().strftime("%Y-%m-%d"), "agent", "test entry — acceptance 7.6 of the order of 30 September", "the test itself",
                 "none", "none", "brief/mistakes hash chain", kind="test", existing=before)
        append(e, cp)
        after = read(cp)
        ok = (len(after) == len(before) + 1 and [x["entry_sha256"] for x in after[:-1]] == hashes_before and not verify(cp))
        print(f"[mistakes_ledger] test append on a copy: {len(before)} → {len(after)} entries; prior entries unchanged: {ok}; chain verifies: {not verify(cp)}")
        return 0 if ok else 2


def sessions_after(d: str, n: int) -> str | None:
    from datetime import date, timedelta
    cur = date.fromisoformat(d); k = 0
    while k < n:
        cur += timedelta(days=1)
        if is_trading_day(cur.isoformat()):
            k += 1
    return cur.isoformat()


def cmd_from_trades(args) -> int:
    """Operator decisions from the export-based action ledger (source "brokerage transactions"), each
    with the stated reason at the time (the export carries none; the operator's note in the entry, else
    "no reason recorded at the time"); +20/+60 outcomes against not trading as separate entries."""
    import pandas as pd
    acts = read(DATA / "actions.jsonl")
    trades = [a for a in acts if a.get("source") == "brokerage transactions" and a.get("ticker")]
    if not trades:
        print("[mistakes_ledger] no export-based operator trades in actions.jsonl (operator reports pending export confirmation are not evaluated)")
        return 0
    existing = read(); have = {(e.get("ticker"), e.get("session"), tuple(e.get("action") or [])) for e in existing if e.get("kind") == "operator_decision"}
    px = pd.read_parquet(DATA / "source" / "prices_daily.parquet"); px.index = pd.to_datetime(px.index)
    last = str(px.index[-1].date()); n = 0
    def close(tk, d):
        s = px[tk].dropna() if tk in px.columns else None
        if s is None: return None
        s = s[s.index <= pd.Timestamp(d)]; return float(s.iloc[-1]) if len(s) else None
    for t in trades:
        key = (t["ticker"], t.get("session_date"), tuple(t.get("action") or []))
        if key in have:
            continue
        reason = t.get("stated_reason") or t.get("note") or "no reason recorded at the time (the export carries none)"
        e = make(t.get("session_date"), "operator", f"{'/'.join(t.get('action') or [])} {t.get('quantity')} {t['ticker']} at {t.get('price')}", "brokerage transactions export",
                 "to be evaluated at 20 and 60 sessions against not trading", "none (a decision, not an error, until the outcome is known)", "mistakes:outcomes_due",
                 kind="operator_decision", extra={"ticker": t["ticker"], "session": t.get("session_date"), "action": t.get("action"), "quantity": t.get("quantity"),
                                                  "price": t.get("price"), "stated_reason": reason, "outcomes_due": [sessions_after(t.get("session_date"), 20), sessions_after(t.get("session_date"), 60)]},
                 existing=existing)
        if args.write: append(e)
        existing.append(e); n += 1
    # outcomes: for each decision whose +20/+60 session has passed and has no outcome entry yet
    decisions = [e for e in existing if e.get("kind") == "operator_decision"]
    outcomes = {(e.get("refers_to"), e.get("horizon")) for e in existing if e.get("kind") == "outcome"}
    for d in decisions:
        for hz in (20, 60):
            due = sessions_after(d["session"], hz)
            if (d["entry_id"], hz) in outcomes or due is None or due > last:
                continue
            p0, p1 = close(d["ticker"], d["session"]), close(d["ticker"], due)
            if not p0 or not p1:
                continue
            r = p1 / p0 - 1
            sold = "sell" in (d.get("action") or [])
            trade_ret = -r if sold else r          # a sale is judged by what the position would have done
            e = make(due, "operator", f"outcome at +{hz} sessions of the {'/'.join(d.get('action') or [])} of {d['ticker']} on {d['session']}", "price store",
                     f"{'the name moved ' + f'{r*100:+.1f}%' } after the trade: {'avoided' if (sold and r < 0) or (not sold and r > 0) else 'forgone'} {abs(r)*100:.1f}% against not trading",
                     "none (an outcome, not a rule change; a lesson becomes a rule only through a registration and a prospective test)", "mistakes:outcomes_due",
                     kind="outcome", refers_to=d["entry_id"], extra={"ticker": d["ticker"], "horizon": hz, "trade_return": round(trade_ret, 5), "not_traded_return": round(r, 5),
                                                                     "difference": round(trade_ret - r, 5) if not sold else round(-r - 0.0, 5)}, existing=existing)
            if args.write: append(e)
            existing.append(e); n += 1
    print(f"[mistakes_ledger] {'appended' if args.write else 'would append'} {n} entr{'y' if n == 1 else 'ies'} from trades")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed"); sub.add_parser("verify"); sub.add_parser("test-append")
    a = sub.add_parser("append")
    a.add_argument("--found", default=None); a.add_argument("--who", required=True, choices=WHO); a.add_argument("--error", required=True)
    a.add_argument("--detected-by", required=True); a.add_argument("--cost", required=True); a.add_argument("--fix", required=True)
    a.add_argument("--check", required=True); a.add_argument("--kind", default="failure", choices=KINDS); a.add_argument("--refers-to", default=None)
    f = sub.add_parser("from-trades"); f.add_argument("--write", action="store_true")
    ap.add_argument("--allow-non-trading", action="store_true")
    args = ap.parse_args()
    return {"seed": cmd_seed, "append": cmd_append, "verify": cmd_verify, "test-append": cmd_test_append, "from-trades": cmd_from_trades}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
