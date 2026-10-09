#!/usr/bin/env python3
"""
ready_strip.py — the READY block of the Screen page, built from the two files the page already loads
(fourth follow-up of 8 October 2026, J5). The same rule as common.js readyStrip(); used by tests/test_ready_strip.py
and by the referee (screen:ready_strip, HIGH when the block's names differ from the board's READY rows or the two
files carry different session dates).

  full     the board rows (data/screen/scores.json watchlist, rank order) whose state in data/entry_state.json is READY
  half     the same for READY-HALF (earnings within 20 sessions), with the sessions to earnings
  changed  transitions_today restricted to board names, where the name entered or left a READY state
  stale    the two files carry different session dates: nothing is listed

Usage:  python scripts/screen/ready_strip.py        prints the block for the served files
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
READY = ("READY", "READY-HALF")


def build(scores: dict, es: dict) -> dict:
    W = (scores or {}).get("watchlist") or []
    names = (es or {}).get("names") or {}
    sd, ed = (scores or {}).get("session_date"), (es or {}).get("session_date")
    stale = (not sd) or (not ed) or sd != ed
    rows = [] if stale else sorted([r for r in W if (names.get(r.get("ticker")) or {}).get("state") in READY],
                                   key=lambda r: (r.get("rank") is None, r.get("rank") if r.get("rank") is not None else 0))

    def item(r):
        e = names[r["ticker"]]
        close = e.get("close") if e.get("close") is not None else r.get("current_price")
        stop = e.get("stop")
        return {"rank": r.get("rank"), "ticker": r["ticker"], "held": bool(r.get("held")), "state": e.get("state"), "close": close, "stop": stop,
                "dist_pct": ((stop / close - 1) * 100 if close and stop else None), "sessions_to_earnings": e.get("sessions_to_earnings")}
    full = [item(r) for r in rows if names[r["ticker"]]["state"] == "READY"]
    half = [item(r) for r in rows if names[r["ticker"]]["state"] == "READY-HALF"]
    board = {r.get("ticker") for r in W}
    changed = [] if stale else [{"ticker": t.get("ticker"), "from": t.get("from"), "to": t.get("to"), "reason": t.get("reason") or ""}
                                for t in ((es or {}).get("transitions_today") or []) if t.get("ticker") in board and (t.get("to") in READY or t.get("from") in READY)]
    return {"session_scores": sd, "session_entry": ed, "stale": stale, "full": full, "half": half, "changed": changed,
            "label": (es or {}).get("label") or "DIAGNOSTIC", "rules_version": (es or {}).get("rules_version")}


def board_ready_rows(scores: dict, es: dict, state: str | None = None) -> list[str]:
    """The board's READY and READY-HALF rows in rank order (what the block must match), regardless of staleness;
    `state` restricts to one of the two (the block's two lines are compared one by one)."""
    names = (es or {}).get("names") or {}
    want = READY if state is None else (state,)
    rows = [r for r in ((scores or {}).get("watchlist") or []) if (names.get(r.get("ticker")) or {}).get("state") in want]
    return [r["ticker"] for r in sorted(rows, key=lambda r: (r.get("rank") is None, r.get("rank") if r.get("rank") is not None else 0))]


def render_text(b: dict) -> str:
    fmt = lambda x, half: f"#{x['rank'] if x['rank'] is not None else '—'} {x['ticker']}{' HELD' if x['held'] else ''} {x['close']:.2f} · stop {x['stop']:.2f}" + (f" ({x['dist_pct']:+.1f}%)" if x['dist_pct'] is not None else "") + (f" · earnings in {x['sessions_to_earnings'] if x['sessions_to_earnings'] is not None else '?'} sessions" if half else "")
    if b["stale"]:
        return f"READY ON THE BOARD · stale: entry states {b['session_entry']}, board {b['session_scores']} · nothing listed"
    out = [f"READY ON THE BOARD · close of {b['session_scores']} · {b['label']}",
           "Full size: " + ("; ".join(fmt(x, False) for x in b["full"]) or "none"),
           "Half size (earnings within 20 sessions): " + ("; ".join(fmt(x, True) for x in b["half"]) or "none"),
           "Changed since the previous session: " + ("; ".join(f"{t['ticker']} {t['from']} → {t['to']} ({t['reason']})" for t in b["changed"]) or "none")]
    return "\n".join(out)


def main() -> int:
    scores = json.loads((REPO / "data" / "screen" / "scores.json").read_text())
    es = json.loads((REPO / "data" / "entry_state.json").read_text())
    print(render_text(build(scores, es)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
