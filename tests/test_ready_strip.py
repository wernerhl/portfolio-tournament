#!/usr/bin/env python3
"""
test_ready_strip.py — the READY block of the Screen page lists exactly the board's READY and READY-HALF rows, in rank
order, from the two files the page loads (fourth follow-up of 8 October 2026, J5).

    python tests/test_ready_strip.py
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts" / "screen"))
import ready_strip as rs   # noqa: E402


def _served():
    scores = json.loads((REPO / "data" / "screen" / "scores.json").read_text())
    es = json.loads((REPO / "data" / "entry_state.json").read_text())
    return scores, es


def test_block_matches_the_boards_ready_rows_in_names_and_order():
    scores, es = _served()
    b = rs.build(scores, es)
    if b["stale"]:
        print(f"  (served files carry different sessions: entry {b['session_entry']}, board {b['session_scores']}; the block lists nothing)")
        assert b["full"] == [] and b["half"] == []
        return
    full = [x["ticker"] for x in b["full"]]; half = [x["ticker"] for x in b["half"]]
    assert full == rs.board_ready_rows(scores, es, "READY"), f"full {full} != board READY rows {rs.board_ready_rows(scores, es, 'READY')}"
    assert half == rs.board_ready_rows(scores, es, "READY-HALF"), f"half {half} != board READY-HALF rows {rs.board_ready_rows(scores, es, 'READY-HALF')}"
    assert sorted(full + half) == sorted(rs.board_ready_rows(scores, es))
    # every full-size name is READY, every half-size name READY-HALF, ranks ascend within each list
    assert all(x["state"] == "READY" for x in b["full"]) and all(x["state"] == "READY-HALF" for x in b["half"])
    for lst in (b["full"], b["half"]):
        ranks = [x["rank"] for x in lst if x["rank"] is not None]
        assert ranks == sorted(ranks), ranks
    print(f"  {len(b['full'])} full size, {len(b['half'])} half size, {len(b['changed'])} changed · session {b['session_scores']}")


def test_stale_when_the_sessions_differ():
    scores = {"session_date": "2026-10-07", "watchlist": [{"rank": 1, "ticker": "AAA", "current_price": 10.0}]}
    es = {"session_date": "2026-10-06", "names": {"AAA": {"state": "READY", "close": 10.0, "stop": 9.0}}, "transitions_today": [{"ticker": "AAA", "from": "WATCH", "to": "READY", "reason": "x"}]}
    b = rs.build(scores, es)
    assert b["stale"] and b["full"] == [] and b["half"] == [] and b["changed"] == []


def test_half_size_carries_the_sessions_to_earnings_and_the_stop_distance():
    scores = {"session_date": "2026-10-07", "watchlist": [{"rank": 2, "ticker": "BBB", "current_price": 100.0, "held": True}, {"rank": 1, "ticker": "AAA", "current_price": 50.0}, {"rank": 3, "ticker": "CCC", "current_price": 20.0}]}
    es = {"session_date": "2026-10-07", "names": {"AAA": {"state": "READY-HALF", "close": 50.0, "stop": 45.0, "sessions_to_earnings": 12},
                                                   "BBB": {"state": "READY", "close": 100.0, "stop": 86.4}, "CCC": {"state": "WATCH", "close": 20.0, "stop": 18.0}},
          "transitions_today": [{"ticker": "CCC", "from": "READY", "to": "WATCH", "reason": "ceiling"}, {"ticker": "ZZZ", "from": "WATCH", "to": "READY", "reason": "not on the board"}]}
    b = rs.build(scores, es)
    assert [x["ticker"] for x in b["full"]] == ["BBB"] and b["full"][0]["held"] and round(b["full"][0]["dist_pct"], 1) == -13.6
    assert [x["ticker"] for x in b["half"]] == ["AAA"] and b["half"][0]["sessions_to_earnings"] == 12 and round(b["half"][0]["dist_pct"], 1) == -10.0
    assert [t["ticker"] for t in b["changed"]] == ["CCC"], b["changed"]
    assert rs.board_ready_rows(scores, es) == ["AAA", "BBB"] and rs.board_ready_rows(scores, es, "READY") == ["BBB"]


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except Exception:
                print(f"FAIL {name}\n{traceback.format_exc()}"); fails += 1
    n = sum(1 for k, v in globals().items() if k.startswith("test_") and callable(v))
    print(f"\n{n - fails} passed, {fails} failed")
    sys.exit(1 if fails else 0)
