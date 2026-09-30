#!/usr/bin/env python3
"""
tests/fixtures/review/make_fixtures.py — writes the fixtures tests/test_monthly_review.py reads.
Deterministic, no randomness: every figure is chosen by hand so the tests can state the answers.

    spells.jsonl       24 spell events-worth of spells: tiers 2_balanced and 3_aggressive, ten spells
                       each over the SAME four decision dates (2026-09-01, -08, -15, -22); a twin 2c
                       with two spells; two spells outside the month (closed in August, opened in
                       October) that the review has to leave out. One spell (SP-B01) carries a
                       followup_20 event whose "return" differs from its closed event.
    trades.jsonl       three entry trades (scores and regime label); SP-B08's event carries no
                       scores_at_entry so the review has to take them from trade T-0008.
    mistakes.jsonl     one failure found in the month (repeating an August entry's error text),
                       one operator decision with its +20 and +60 outcomes.
    actions.jsonl      two export-confirmed operator trades (one matching the decision, one without a
                       decision entry), one provisional operator-report entry, one August export
                       entry (outside the month) and one tier sizing entry (not the operator's).
    prices_daily.csv   closes 2026-08-20 .. 2026-09-30 for every fixture ticker except WWW; HHH ends
                       at 95 and JJJ at 51.5 on 2026-09-30 (the month-end marks).
    sector_etfs.csv    "spy": 755 to 2026-09-14, 760 from 09-15, 765 from 09-22, 767.6 on 09-30.

Run:  .venv/bin/python tests/fixtures/review/make_fixtures.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from trading_calendar import is_trading_day  # noqa: E402

LOGGED = "2026-09-30T20:00:00-04:00"


def sessions(a: str, b: str) -> list:
    d, end, out = date.fromisoformat(a), date.fromisoformat(b), []
    while d <= end:
        if is_trading_day(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def held(a: str, b: str) -> int:
    return len(sessions(a, b)) - 1


# (spell_id, tier, ticker, entry, entry_price, exit, exit_price, ret, spy_ret, excess_spy, basket_ret, exit_reason, scores or None, trade_id)
CLOSED = [
    ("SP-B01", "2_balanced", "AAA", "2026-09-01", 100.0, "2026-09-10", 92.0, -0.080, 0.002, -0.082, -0.030, "stop", (61.2, 3, 12, 7.1, 6.4), "T-0001"),
    ("SP-B02", "2_balanced", "BBB", "2026-09-01", 50.0, "2026-09-11", 51.7, 0.034, 0.003, 0.031, 0.010, "target", (63.0, 2, 9, 7.4, 6.9), "T-0002"),
    ("SP-B03", "2_balanced", "CCC", "2026-09-01", 80.0, "2026-09-18", 79.2, -0.010, 0.005, -0.015, 0.004, "time", (58.4, 5, 20, 6.2, 6.0), "T-0003"),
    ("SP-B04", "2_balanced", "DDD", "2026-09-08", 40.0, "2026-09-17", 38.0, -0.050, 0.004, -0.054, -0.020, "stop", (55.1, 8, 31, 5.8, 5.5), "T-0004"),
    ("SP-B05", "2_balanced", "EEE", "2026-09-08", 120.0, "2026-09-24", 122.0, 0.017, 0.005, 0.012, 0.008, "time", (64.5, 1, 6, 7.9, 7.2), "T-0005"),
    ("SP-B06", "2_balanced", "FFF", "2026-09-08", 30.0, "2026-09-29", 26.5, -0.117, 0.004, -0.121, -0.060, "stop", (57.0, 6, 24, 6.0, 5.9), "T-0006"),
    ("SP-B07", "2_balanced", "GGG", "2026-09-15", 200.0, "2026-09-25", 209.6, 0.048, 0.004, 0.044, 0.020, "target", (60.3, 4, 15, 6.8, 6.6), "T-0007"),
    ("SP-B09", "2_balanced", "III", "2026-09-22", 70.0, "2026-09-29", 67.8, -0.031, 0.002, -0.033, -0.010, "stop", (54.0, 9, 35, 5.5, 5.4), "T-0009"),
    ("SP-A01", "3_aggressive", "NNN", "2026-09-01", 25.0, "2026-09-03", 25.5, 0.020, 0.000, 0.020, 0.010, "target", (70.1, 2, 4, 7.0, 8.2), "T-0101"),
    ("SP-A02", "3_aggressive", "OOO", "2026-09-01", 60.0, "2026-09-04", 55.8, -0.070, 0.000, -0.070, -0.040, "stop", (62.0, 9, 22, 6.1, 7.0), "T-0102"),
    ("SP-A03", "3_aggressive", "PPP", "2026-09-01", 15.0, "2026-09-09", 14.3, -0.047, -0.002, -0.045, -0.030, "stop", (61.5, 10, 25, 6.0, 6.9), "T-0103"),
    ("SP-A04", "3_aggressive", "QQQ", "2026-09-01", 90.0, "2026-09-16", 87.6, -0.027, 0.003, -0.030, -0.010, "time", (63.2, 8, 19, 6.3, 7.1), "T-0104"),
    ("SP-A05", "3_aggressive", "RRR", "2026-09-08", 45.0, "2026-09-18", 47.7, 0.060, 0.005, 0.055, 0.030, "target", (72.4, 1, 2, 7.5, 8.6), "T-0105"),
    ("SP-A06", "3_aggressive", "SSS", "2026-09-08", 33.0, "2026-09-21", 33.7, 0.021, 0.003, 0.018, 0.012, "time", (68.0, 4, 8, 7.1, 7.9), "T-0106"),
    ("SP-A07", "3_aggressive", "TTT", "2026-09-15", 110.0, "2026-09-23", 120.4, 0.095, 0.005, 0.090, 0.050, "target", (69.3, 3, 6, 7.2, 8.0), "T-0107"),
    ("SP-A08", "3_aggressive", "UUU", "2026-09-15", 20.0, "2026-09-28", 19.8, -0.010, 0.002, -0.012, -0.005, "time", (64.0, 7, 16, 6.5, 7.3), "T-0108"),
    ("SP-A09", "3_aggressive", "VVV", "2026-09-22", 75.0, "2026-09-30", 77.1, 0.028, 0.003, 0.025, 0.015, "target", (66.7, 5, 11, 6.9, 7.6), "T-0109"),
    ("SP-C01", "2c", "AAA", "2026-09-01", 100.0, "2026-09-10", 92.3, -0.077, 0.002, -0.079, -0.028, "stop", (61.2, 3, 12, 7.1, 6.4), "T-0201"),
    ("SP-C02", "2c", "DDD", "2026-09-08", 40.0, "2026-09-17", 38.2, -0.046, 0.004, -0.050, -0.018, "stop", (55.1, 8, 31, 5.8, 5.5), "T-0202"),
    # outside the month: closed in August; and SP-B10 closed in October (open at month end → marked)
    ("SP-B11", "2_balanced", "KKK", "2026-08-20", 10.0, "2026-08-28", 10.4, 0.040, 0.010, 0.030, 0.020, "target", (59.0, 5, 18, 6.4, 6.1), "T-0011"),
    ("SP-B10", "2_balanced", "JJJ", "2026-09-22", 50.0, "2026-10-02", 52.0, 0.040, 0.006, 0.034, 0.020, "target", (56.2, 10, 40, 5.7, 5.6), "T-0010"),
]
# open spells (opened event only): SP-B08 without scores (from trade T-0008); SP-A10 WWW has no price series; SP-B12 opened in October
OPEN = [
    ("SP-B08", "2_balanced", "HHH", "2026-09-15", 100.0, None, "T-0008"),
    ("SP-A10", "3_aggressive", "WWW", "2026-09-22", 12.0, (60.0, 6, 14, 6.6, 7.4), "T-0110"),
    ("SP-B12", "2_balanced", "LLL", "2026-10-01", 20.0, (58.0, 4, 17, 6.3, 6.2), "T-0012"),
]


def scores(t):
    if t is None:
        return None
    return {"tier_composite": t[0], "tier_rank": t[1], "composite_rank": t[2], "bq_score": t[3], "tn_score": t[4]}


def event(spell_id, ev, tier, ticker, entry, entry_price, trade_id, **kw):
    base = {"spell_id": spell_id, "event": ev, "tier": tier, "ticker": ticker, "entry_session": entry, "entry_trade_id": trade_id,
            "entry_price": entry_price, "exit_session": None, "exit_trade_id": None, "exit_price": None, "exit_reason": None,
            "sessions_held": None, "return": None, "spy_return": None, "excess_vs_spy": None, "basket_return": None,
            "excess_vs_basket": None, "basket_thesis": "fixture basket", "horizon": None, "scores_at_entry": None, "logged_at": LOGGED}
    base.update(kw)
    return base


def write_jsonl(path: Path, rows: list):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main() -> int:
    spells = []
    for sid, tier, tk, entry, px, ex, expx, ret, spy, exc, bret, reason, sc, tid in CLOSED:
        spells.append(event(sid, "opened", tier, tk, entry, px, tid, scores_at_entry=scores(sc), logged_at=entry + "T20:00:00-04:00"))
        spells.append(event(sid, "closed", tier, tk, entry, px, tid, exit_session=ex, exit_trade_id=tid.replace("T-", "X-"), exit_price=expx,
                            exit_reason=reason, sessions_held=held(entry, ex), **{"return": ret}, spy_return=spy, excess_vs_spy=exc,
                            basket_return=bret, excess_vs_basket=round(ret - bret, 6), scores_at_entry=scores(sc), logged_at=ex + "T20:00:00-04:00"))
    # a followup on SP-B01 with figures that differ from its closed event
    b01 = next(e for e in spells if e["spell_id"] == "SP-B01" and e["event"] == "closed")
    fu = dict(b01)
    fu.update({"event": "followup_20", "horizon": 20, "return": -0.020, "excess_vs_spy": -0.025, "logged_at": "2026-10-09T20:00:00-04:00"})
    spells.append(fu)
    for sid, tier, tk, entry, px, sc, tid in OPEN:
        spells.append(event(sid, "opened", tier, tk, entry, px, tid, scores_at_entry=scores(sc), logged_at=entry + "T20:00:00-04:00"))
    write_jsonl(HERE / "spells.jsonl", spells)

    trades = [
        {"trade_id": "T-0001", "session": "2026-09-01", "tier": "2_balanced", "ticker": "AAA", "action": "buy", "shares": 10, "price": 100.0, "value": 1000.0,
         "cost": 0.5, "reason": "monthly selection", "tier_composite": 61.2, "tier_rank": 3, "composite": 58.0, "composite_rank": 12, "bq_score": 7.1,
         "bq_rank": 14, "tn_score": 6.4, "tn_rank": 20, "regime_R": 0.24, "regime_label": "LOW RISK", "source": "fixture", "logged_at": LOGGED},
        {"trade_id": "T-0008", "session": "2026-09-15", "tier": "2_balanced", "ticker": "HHH", "action": "buy", "shares": 10, "price": 100.0, "value": 1000.0,
         "cost": 0.5, "reason": "monthly selection", "tier_composite": 56.8, "tier_rank": 7, "composite": 52.0, "composite_rank": 28, "bq_score": 5.9,
         "bq_rank": 30, "tn_score": 5.7, "tn_rank": 33, "regime_R": 0.27, "regime_label": "LOW RISK", "source": "fixture", "logged_at": LOGGED},
        {"trade_id": "T-0102", "session": "2026-09-01", "tier": "3_aggressive", "ticker": "OOO", "action": "buy", "shares": 20, "price": 60.0, "value": 1200.0,
         "cost": 0.6, "reason": "monthly selection", "tier_composite": 62.0, "tier_rank": 9, "composite": 60.1, "composite_rank": 22, "bq_score": 6.1,
         "bq_rank": 25, "tn_score": 7.0, "tn_rank": 9, "regime_R": 0.24, "regime_label": "LOW RISK", "source": "fixture", "logged_at": LOGGED},
    ]
    write_jsonl(HERE / "trades.jsonl", trades)

    def sha(d):
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()

    fail_error = "options lens: no chain vintage for the session; lens.json served from the previous vintage without a stale mark"
    mist = [
        {"entry_id": "F-2026-08-14-01", "found": "2026-08-14", "who": "system", "error": fail_error, "detected_by": "referee sweep",
         "cost": "one session of an unmarked stale lens", "fix": "vintage-age gate before serving", "referee_check": "lens_vintage_age_sessions <= 1",
         "kind": "failure", "refers_to": None, "logged_at": "2026-08-14T21:00:00-04:00"},
        {"entry_id": "OD-2026-09-10-01", "found": "2026-09-10", "who": "operator", "error": None, "detected_by": None, "cost": None, "fix": None,
         "referee_check": None, "kind": "operator_decision", "refers_to": None, "ticker": "XYZ", "action": "sell", "session": "2026-09-10",
         "stated_reason": "position above 20 percent of the book; trimmed to the sizing rule", "logged_at": "2026-09-10T21:00:00-04:00"},
        {"entry_id": "F-2026-09-12-01", "found": "2026-09-12", "who": "system", "error": fail_error, "detected_by": "referee sweep",
         "cost": "one session of an unmarked stale lens", "fix": "the gate now reads the vintage stamp from the chain file, not the served json",
         "referee_check": "lens_vintage_age_sessions <= 1 AND chain_file_stamp == lens.vintage", "kind": "failure", "refers_to": "F-2026-08-14-01",
         "logged_at": "2026-09-12T21:00:00-04:00"},
        {"entry_id": "OUT-2026-09-10-01-20", "found": "2026-10-08", "who": "system", "error": None, "detected_by": None, "cost": None, "fix": None,
         "referee_check": None, "kind": "outcome", "refers_to": "OD-2026-09-10-01", "horizon": 20, "trade_return": 0.0, "not_traded_return": 0.031,
         "difference": -0.031, "logged_at": "2026-10-08T21:00:00-04:00"},
        {"entry_id": "OUT-2026-09-10-01-60", "found": "2026-12-04", "who": "system", "error": None, "detected_by": None, "cost": None, "fix": None,
         "referee_check": None, "kind": "outcome", "refers_to": "OD-2026-09-10-01", "horizon": 60, "trade_return": 0.0, "not_traded_return": -0.045,
         "difference": 0.045, "logged_at": "2026-12-04T21:00:00-04:00"},
    ]
    for m in mist:
        m["entry_sha256"] = sha({k: v for k, v in m.items() if k != "entry_sha256"})
    write_jsonl(HERE / "mistakes.jsonl", mist)

    actions = [
        {"session_date": "2026-08-21", "date": "2026-08-21", "tier": "5_werner", "source": "brokerage transactions", "action": ["buy"], "ticker": "XYZ",
         "quantity": 40, "price": 190.0, "amount": -7600.0, "regime": "LOW RISK", "R_full": 0.22, "signal": None, "signal_source": None,
         "signal_note": "no record", "export_sha256": "f" * 64, "action_raw": "Buy", "logged_at": LOGGED},
        {"session_date": "2026-09-08", "tier": "1_cap_pres", "action": ["sizing change"], "entries": [], "exits": [], "regime": "LOW RISK", "R_full": 0.2233,
         "logged_at": "2026-09-08T23:59:32"},
        {"session_date": "2026-09-10", "date": "2026-09-10", "tier": "5_werner", "source": "brokerage transactions", "action": ["sell"], "ticker": "XYZ",
         "quantity": 40, "price": 212.5, "amount": 8500.0, "regime": "LOW RISK", "R_full": 0.25,
         "signal": {"ticker": "XYZ", "signal": "ABOVE TRAILING LEVEL", "state": "above_trailing_level"}, "signal_source": "data/ticker_signals.json@abc1234",
         "signal_match": "session_date == 2026-09-10", "export_sha256": "f" * 64, "action_raw": "Sell", "logged_at": LOGGED},
        {"session_date": "2026-09-24", "date": "2026-09-24", "tier": "5_werner", "source": "brokerage transactions", "action": ["buy"], "ticker": "ZZZ",
         "quantity": 10, "price": 30.0, "amount": -300.0, "regime": "LOW RISK", "R_full": 0.26, "signal": None, "signal_source": "data/ticker_signals.json@abc1235",
         "signal_match": "session_date == 2026-09-24", "signal_note": "no record for ZZZ in that file", "export_sha256": "f" * 64, "action_raw": "Buy", "logged_at": LOGGED},
        {"session_date": "2026-09-29", "date": "2026-09-29", "date_note": "on or about 29 September 2026 per the operator; pending the brokerage export",
         "tier": "5_werner", "source": "operator report, pending export confirmation", "action": ["sell"], "ticker": "YYY", "quantity": 50, "price": None,
         "price_basis": "unknown until the export", "amount": None, "regime": "LOW RISK", "R_full": 0.28, "signal": None, "logged_at": LOGGED},
    ]
    write_jsonl(HERE / "actions.jsonl", actions)

    days = sessions("2026-08-20", "2026-09-30")
    tickers = sorted({r[2] for r in CLOSED} | {r[2] for r in OPEN} - {"WWW"})
    base_px = {r[2]: r[4] for r in CLOSED}
    base_px.update({r[2]: r[4] for r in OPEN})
    with open(HERE / "prices_daily.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + tickers)
        for d in days:
            row = [d]
            for tk in tickers:
                px = base_px[tk]
                if d == "2026-09-30":
                    px = {"HHH": 95.0, "JJJ": 51.5}.get(tk, px)
                row.append(f"{px:.4f}")
            w.writerow(row)
    with open(HERE / "sector_etfs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "spy", "qqq"])
        for d in days:
            spy = 755.0 if d < "2026-09-15" else 760.0 if d < "2026-09-22" else 765.0 if d < "2026-09-30" else 767.6
            w.writerow([d, f"{spy:.2f}", f"{spy * 0.8:.2f}"])
    print(f"fixtures written under {HERE}: {len(spells)} spell events, {len(trades)} trades, {len(mist)} ledger entries, "
          f"{len(actions)} actions, {len(days)} price days x {len(tickers)} tickers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
