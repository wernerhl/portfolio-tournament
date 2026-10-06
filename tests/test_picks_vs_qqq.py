#!/usr/bin/env python3
"""
tests/test_picks_vs_qqq.py — the picks-against-QQQ comparison (revised order of 6 October 2026, section 6b), on a
synthetic record whose answers are computed by hand: the same dollars in and out of QQQ on the same dates, a resize
mirrored in the shadow, the beta-scaled shadow, exits priced at the exit session's close, the log's trade rows
replacing the holdings-snapshot change they explain, positions the log cannot place in time, the exclusions, and the
count of independent decisions.

    .venv/bin/python tests/test_picks_vs_qqq.py
"""
from __future__ import annotations
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import picks_vs_qqq as pq  # noqa: E402

RESULTS = []
S = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09"]


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


class StubBetas:
    def __init__(self, beta=1.0, closes=None):
        self.beta, self.closes = beta, closes or {}

    def at(self, tk, start):
        return (self.beta, 252, "stub")

    def close(self, tk, d):
        return self.closes.get((tk, d))


def record(op_positions: dict, qqq: list[float], tier_positions: dict | None = None) -> dict:
    """op_positions[session] = {ticker: (shares, close)}"""
    hist = []
    for i, d in enumerate(S):
        tiers = {"5_werner": {"positions": [{"ticker": k, "shares": v[0], "price": v[1]} for k, v in op_positions.get(d, {}).items()]}}
        for tid, tp in (tier_positions or {}).items():
            tiers[tid] = {"positions": [{"ticker": k, "shares": v[0], "price": v[1]} for k, v in tp.get(d, {}).items()]}
        hist.append({"date": d, "tiers": tiers, "benchmarks": {"qqq": {"price": qqq[i]}}})
    return {"history": hist}


def measure(rec, t0, T, rows=None, beta=1.0, closes=None, excluded=None, book="5_werner"):
    sessions, pos, qqq = pq.load_record(rec)
    tr = pq.snapshot_trades(pos.get(book, {}), sessions, "holdings snapshot")
    if rows:
        tr = pq.overlay_log_trades(tr, rows)
    return pq.measure(book, pos.get(book, {}), tr, sessions, qqq, t0, T, StubBetas(beta, closes), excluded or {})


def test_held_position_against_flat_qqq():
    """$1,000 held from the window's opening close, the stock +10%, QQQ flat: difference +$100."""
    pos = {d: {"AAA": (10, 100.0 if d <= S[1] else 110.0)} for d in S}
    sp, bad, _ = measure(record(pos, [500.0] * 6), S[1], S[-1])
    s = sp[0]
    assert not bad and s["dollars_in"] == 1000.0 and abs(s["diff_usd"] - 100.0) < 1e-6 and not s["closed"], s
    assert abs(s["diff_pct"] - 0.10) < 1e-9


def test_closed_position_same_dollars_out():
    """Bought $1,000 at the close of S[1]; sold at S[3] for $1,200 (stock +20%); QQQ +5% over the same dates: the shadow
    takes the same $1,200 out and is left with 1,050 - 1,200 = -$150, so the difference is +$150 = 1,000 x (20% - 5%)."""
    pos = {S[0]: {}, S[1]: {"AAA": (10, 100.0)}, S[2]: {"AAA": (10, 110.0)}, S[3]: {}, S[4]: {}, S[5]: {}}
    q = [400.0, 400.0, 410.0, 420.0, 430.0, 440.0]
    sp, bad, _ = measure(record(pos, q), S[0], S[-1], closes={("AAA", S[3]): 120.0})
    s = sp[0]
    assert s["closed"] and s["end"] == S[3] and abs(s["diff_usd"] - 150.0) < 1e-6 and s["beat"], s
    assert s["trades"][-1]["price"] == 120.0, "the exit is priced at the exit session's close, not the prior close"


def test_resize_is_mirrored():
    """10 shares at 100 (S[1]), 10 more at 110 (S[2]), stock 121 at S[3]; QQQ flat. Position 20 x 121 = 2,420 against
    2,100 put in: difference +320."""
    pos = {S[0]: {}, S[1]: {"AAA": (10, 100.0)}, S[2]: {"AAA": (20, 110.0)}, S[3]: {"AAA": (20, 121.0)}}
    rec = record(pos, [500.0] * 6)
    sp, bad, _ = measure(rec, S[0], S[3])
    s = sp[0]
    assert abs(s["dollars_in"] - 2100.0) < 1e-6 and abs(s["diff_usd"] - 320.0) < 1e-6, s


def test_beta_scaled_shadow():
    """Held $1,000, stock +10%, QQQ +4%, beta 2: plain difference 1,000 x (10% - 4%) = 60; risk-adjusted
    1,000 x (10% - 2 x 4%) = 20."""
    pos = {d: {"AAA": (10, 100.0 if d <= S[1] else 110.0)} for d in S}
    q = [500.0, 500.0, 520.0, 520.0, 520.0, 520.0]
    sp, _, _ = measure(record(pos, q), S[1], S[2], beta=2.0)
    s = sp[0]
    assert abs(s["diff_usd"] - 60.0) < 1e-6 and abs(s["riskadj_usd"] - 20.0) < 1e-6, s


def test_reported_sale_replaces_the_snapshot_and_its_price():
    """The snapshot shows the sale at S[4]; the log reports it on S[3] at 130: the exit moves to S[3] at 130."""
    pos = {S[0]: {}, S[1]: {"AAA": (10, 100.0)}, S[2]: {"AAA": (10, 110.0)}, S[3]: {"AAA": (10, 125.0)}, S[4]: {}, S[5]: {}}
    rows = [{"tier": "5_werner", "ticker": "AAA", "action": ["sell"], "quantity": 10, "price": 130.0, "date": S[3],
             "session_date": S[3], "source": "operator report, pending export confirmation"}]
    sp, bad, _ = measure(record(pos, [500.0] * 6), S[0], S[-1], rows=rows)
    s = sp[0]
    assert not bad and s["end"] == S[3] and s["trades"][-1]["price"] == 130.0 and abs(s["diff_usd"] - 300.0) < 1e-6, s


def test_not_measurable_when_the_log_cannot_place_the_position():
    """A sale reported before the first snapshot that shows the purchase, and a purchase and sale in one session, enter
    no figure and are listed with the reason."""
    pos = {S[0]: {}, S[1]: {}, S[2]: {}, S[3]: {"ANET": (100, 150.0), "MU": (50, 1000.0)}, S[4]: {}, S[5]: {}}
    rows = [{"tier": "5_werner", "ticker": "ANET", "action": ["sell"], "quantity": 100, "price": None, "date": None,
             "date_range": [S[1], S[2]], "session_date": S[2], "source": "operator report, pending export confirmation"},
            {"tier": "5_werner", "ticker": "MU", "action": ["sell"], "quantity": 50, "price": 1010.0, "date": S[3],
             "session_date": S[3], "source": "operator report, pending export confirmation"}]
    sp, bad, _ = measure(record(pos, [500.0] * 6), S[0], S[-1], rows=rows, closes={("ANET", S[2]): 149.0})
    assert not sp, sp
    why = {b["ticker"]: b["reason"] for b in bad}
    assert "before the first holdings snapshot" in why["ANET"] and "same session" in why["MU"], why


def test_exclusions_listed_not_compared():
    pos = {d: {"AAA": (10, 100.0), "GLD": (5, 300.0)} for d in S}
    sp, _, ex = measure(record(pos, [500.0] * 6), S[0], S[-1], excluded={"GLD": "gold"})
    assert [s["ticker"] for s in sp] == ["AAA"] and ex == [{"book": "5_werner", "ticker": "GLD", "category": "gold"}]


def test_decisions_are_distinct_entry_dates():
    """Two names held since the record began count as one decision; two names bought on S[2] as one more; one bought
    on S[3] as a third."""
    pos = {S[0]: {"A": (1, 10.0), "B": (1, 10.0)}, S[1]: {"A": (1, 10.0), "B": (1, 10.0)},
           S[2]: {"A": (1, 10.0), "B": (1, 10.0), "C": (1, 10.0), "D": (1, 10.0)},
           S[3]: {"A": (1, 10.0), "B": (1, 10.0), "C": (1, 10.0), "D": (1, 10.0), "E": (1, 10.0)}}
    sp, _, _ = measure(record(pos, [500.0] * 6), S[1], S[3])
    assert pq.summarize(sp)["decisions"] == 3, [(s["ticker"], s["entry_date"], s["held_before_record"]) for s in sp]


def test_first_logged_trade_takes_the_first_day_of_a_range():
    rows = [{"tier": "5_werner", "action": ["sizing change"], "session_date": S[0]},
            {"tier": "5_werner", "action": ["sell"], "ticker": "X", "date": None, "date_range": [S[2], S[3]], "session_date": S[3]},
            {"tier": "5_werner", "action": ["entry", "exit"], "entries": ["Y"], "exits": [], "session_date": S[4]},
            {"tier": "2_balanced", "action": ["entry"], "entries": ["Z"], "session_date": S[1]}]
    assert pq.first_logged_trade(rows, "5_werner") == S[2]


def test_summary_is_the_sum_of_positions():
    pos = {d: {"AAA": (10, 100.0 + i), "BBB": (5, 200.0 - i)} for i, d in enumerate(S)}
    sp, _, _ = measure(record(pos, [500.0 + i for i in range(6)]), S[0], S[-1])
    m = pq.summarize(sp)
    assert abs(m["diff_usd"] - sum(s["diff_usd"] for s in sp)) < 0.02 and abs(m["diff_pct"] - m["diff_usd"] / m["dollars_in"]) < 1e-5


if __name__ == "__main__":
    for fn in [test_held_position_against_flat_qqq, test_closed_position_same_dollars_out, test_resize_is_mirrored,
               test_beta_scaled_shadow, test_reported_sale_replaces_the_snapshot_and_its_price,
               test_not_measurable_when_the_log_cannot_place_the_position, test_exclusions_listed_not_compared,
               test_decisions_are_distinct_entry_dates, test_first_logged_trade_takes_the_first_day_of_a_range,
               test_summary_is_the_sum_of_positions]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
