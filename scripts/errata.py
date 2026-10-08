#!/usr/bin/env python3
"""
errata.py — corrections to published values (follow-up order of 7 October 2026, F2).

As-published files are never rewritten. When a published value is wrong, the correction goes to data/errata.json
(append-only, one entry per wrong value: file, tier, date, field, the ticker for a position field, the published
and the corrected value, the reason, the ledger id, the date added, and the entry's sha256) and every computation
that reads the tier history uses the corrected value through apply_history(). The pages mark the date with a
footnote that links to the entry.

    import errata
    history = errata.apply_history(tournament["history"])      # a deep copy with the corrected values and a per-row
                                                               # tiers[tid]["errata"] list of the entry ids applied

Usage (command line):  python scripts/errata.py verify | list
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ERRATA = REPO / "data" / "errata.json"
TOURNAMENT = "data/tournament.json"


def _sha(entry: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in entry.items() if k != "sha256"}, sort_keys=True,
                                     separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def load() -> dict:
    if not ERRATA.exists():
        return {"entries": []}
    return json.loads(ERRATA.read_text())


def entries(file: str | None = None) -> list[dict]:
    es = load().get("entries") or []
    return [e for e in es if file is None or e.get("file") == file]


def verify() -> list[str]:
    """Every entry matches its hash and the ids are unique (append-only: an edited entry is a finding)."""
    es = entries()
    problems = [f"{e.get('id')}: content does not match its sha256 (edited)" for e in es if _sha(e) != e.get("sha256")]
    ids = [e.get("id") for e in es]
    if len(set(ids)) != len(ids):
        problems.append("duplicate entry ids")
    return problems


def make(file: str, tier: str, date: str, field: str, published, corrected, reason: str, ledger_id: str | None,
         added: str, ticker: str | None = None, seq: int | None = None, existing: list | None = None) -> dict:
    ex = existing if existing is not None else entries()
    n = seq or (1 + sum(1 for e in ex if e.get("date") == date and e.get("tier") == tier))
    e = {"id": f"erratum-{date}-{tier}-{n}", "file": file, "tier": tier, "date": date, "field": field}
    if ticker:
        e["ticker"] = ticker
    e.update({"published": published, "corrected": corrected, "reason": reason, "ledger_id": ledger_id, "added": added})
    e["sha256"] = _sha(e)
    return e


def append(new: list[dict]) -> None:
    d = load()
    d.setdefault("cadence", "static"); d.setdefault("note", "append-only: one entry per wrong published value; the published file keeps its bytes and every computation reading it applies the corrected value (scripts/errata.py)")
    d.setdefault("entries", [])
    d["entries"] += new
    d["as_of"] = max(e["added"] for e in d["entries"])
    ERRATA.parent.mkdir(parents=True, exist_ok=True)
    ERRATA.write_text(json.dumps(d, indent=1, ensure_ascii=False))


def corrections(file: str = TOURNAMENT) -> dict[tuple[str, str], list[dict]]:
    """{(date, tier): [entries]} for one published file."""
    out: dict[tuple[str, str], list[dict]] = {}
    for e in entries(file):
        out.setdefault((str(e["date"])[:10], e["tier"]), []).append(e)
    return out


def apply_history(history: list, file: str = TOURNAMENT) -> list:
    """A deep copy of the tournament history with every errata correction applied: tier fields (nav, equity,
    cash, ...) and position fields (price, value, weight for the entry's ticker). Each corrected tier dict carries
    `errata`: the ids applied. The input list is not modified."""
    corr = corrections(file)
    if not corr:
        return copy.deepcopy(history)
    out = copy.deepcopy(history)
    for row in out:
        d = str(row.get("date"))[:10]
        for tid, td in (row.get("tiers") or {}).items():
            es = corr.get((d, tid))
            if not es:
                continue
            for e in es:
                if e.get("ticker"):
                    for p in td.get("positions") or []:
                        if str(p.get("ticker")).upper() == str(e["ticker"]).upper():
                            p[e["field"]] = e["corrected"]
                else:
                    td[e["field"]] = e["corrected"]
            td["errata"] = [e["id"] for e in es]
    return out


def dates(file: str = TOURNAMENT) -> dict[str, list[str]]:
    """{date: [tiers]} with a correction, for footnotes and the referee."""
    out: dict[str, list[str]] = {}
    for (d, tid) in corrections(file):
        out.setdefault(d, []).append(tid)
    return out


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "verify":
        p = verify()
        print("errata intact: every entry matches its sha256" if not p else "PROBLEMS: " + "; ".join(p))
        return 0 if not p else 2
    for e in entries():
        print(f"{e['id']}: {e['file']} {e['tier']} {e['date']} {e.get('ticker', '')} {e['field']}: {e['published']} -> {e['corrected']} ({e['reason'][:80]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
