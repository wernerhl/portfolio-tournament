#!/usr/bin/env python3
"""
tests/test_twins.py — order of 30 Sept 2026, 4.1–4.3: the twin engine (scripts/compute_twins.py) and the
monthly tiers' log backfill (scripts/backfill_tier_logs.py).

Run with the venv interpreter (no pytest dependency):
    .venv/bin/python tests/test_twins.py

A synthetic scored universe and price series drive one twin (K=3, δ=2.0, 2K=6, cash 0.10+0.5R capped
0.60) through SEED, RANK_ENTRY on an open slot, displacement by δ (fires at ≥ δ, not below), RANK_EXIT
(rank > 2K, not at 2K), REGIME_CASH (gap > 5 fires, 4.9 does not; the corridor label is recorded),
DRIFT (26 % fires, 24 % does not), idempotency, the cost charge, spells with excess returns and the
+20/+60 follow-ups (a longer series). The backfill runs on a COPY of data/tournament.json with the
logs in a temp dir. Everything is written under a temporary directory; the last test asserts that
nothing under data/ changed (read-only touches: the price stores, scored_universe.csv, config.json).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
DATA = REPO / "data"
TDIR = DATA / "tournament"
PY = sys.executable
sys.path.insert(0, str(SCRIPTS))
import compute_twins as tw  # noqa: E402
from trading_calendar import is_trading_day  # noqa: E402


# ─── guard: nothing under data/ may change ───────────────────────────────────────────────
def _digest(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _listing(p: Path):
    return sorted(x.name for x in p.iterdir()) if p.exists() else None


_GUARD = {"data": _listing(DATA), "tdir": _listing(TDIR),
          "files": {n: _digest(TDIR / n) for n in ("trades.jsonl", "spells.jsonl", "twins_state.json", "twins.json", "continuous_rules.json")},
          "tournament": _digest(DATA / "tournament.json"), "scored": _digest(DATA / "scored_universe.csv")}

# ─── the synthetic environment (one temp dir shared by the sequential twin tests) ─────────
TMP = Path(tempfile.mkdtemp(prefix="twins_test_"))
ENV = TMP / "data"
NAMES = list("ABCDEFGH")
START_CAP = 100000.0
RATE = 0.001
K = 3


def sessions_from(start: str, n: int) -> list[str]:
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if is_trading_day(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


S = sessions_from("2026-03-02", 80)          # S[0] … S[79], all real NYSE sessions
PX = pd.DataFrame(100.0, index=pd.to_datetime(S), columns=NAMES)   # the price store (mutated by tests)
SPY = pd.Series(505.0, index=pd.to_datetime(S), name="spy")
SPY.iloc[0] = 500.0
R_BY = {s: 0.2 for s in S}                    # cp = 0.1 + 0.5 R → 0.20
LABEL_BY = {s: "LOW RISK" for s in S}


def write_env():
    (ENV / "source").mkdir(parents=True, exist_ok=True)
    (ENV / "screen").mkdir(exist_ok=True)
    (ENV / "tournament").mkdir(exist_ok=True)
    PX.to_parquet(ENV / "source" / "prices_daily.parquet")
    SPY.to_frame().to_parquet(ENV / "source" / "sector_etfs.parquet")
    pd.DataFrame({"date": S, "R_t": [R_BY[s] for s in S]}).to_csv(ENV / "regime_daily.csv", index=False)
    pd.DataFrame({"date": S, "R_full": [R_BY[s] for s in S], "regime": [LABEL_BY[s] for s in S]}).to_csv(ENV / "regime_v2_daily.csv", index=False)
    json.dump({"history": [{"date": s, "effr_daily_pct": 2.52} for s in S]}, open(ENV / "tournament.json", "w"))   # 2.52 %/yr → 0.0001/day
    # C's largest weight is th1 → basket [A]; D → th2 → basket [C]; B and F carry no thesis
    json.dump({"theses": {"th1": {"members": {"C": 1.0, "A": {"weight": 1.0, "sub": "x"}}},
                          "th2": {"members": {"C": 0.4, "D": 1.0}}}}, open(ENV / "thesis_registry.json", "w"))
    json.dump({"watchlist": [{"ticker": "A", "composite": 55.0, "rank": 1}]}, open(ENV / "screen" / "scores.json", "w"))
    json.dump({"signals": {"A": {"trade_now_strength": 80, "signal_strength": 90},
                           "B": {"trade_now_strength": 60, "signal_strength": 70},
                           "C": {"trade_now_strength": None, "signal_strength": None}}}, open(ENV / "ticker_signals.json", "w"))
    json.dump({"tier_specs": {"t_test": {"short": "TEST", "color": "#000000", "n_holdings": K, "cash_floor": 0.10, "cash_slope": 0.5,
                                         "cash_max": 0.60, "universe_filter": None,
                                         "factor_weights": {"ma200": 1, "rsi": 1, "rs6m": 1}}},
               "system_settings": {"inception_capital_per_tier": 100000}}, open(TMP / "config.json", "w"))
    rules = json.load(open(TDIR / "continuous_rules.json"))
    rules["twins"] = {"tc": "t_test"}
    json.dump(rules, open(TMP / "rules.json", "w"), indent=1)


def write_scores(comps: dict):
    """tier_composite = tier_tech + fund_score; with the three ranks = c/25 and fund_score 0, tier_composite = c."""
    rows = []
    order = sorted(comps, key=lambda t: -comps[t])
    for t, c in comps.items():
        rows.append({"ticker": t, "sector": "Technology", "grossMargins": 0.5, "freeCashflow": 1.0,
                     "ma200_rank": c / 25, "rsi_rank": c / 25, "rs6m_rank": c / 25, "fund_score": 0.0,
                     "composite": c, "composite_rank": order.index(t) + 1})
    pd.DataFrame(rows).to_csv(ENV / "scored_universe.csv", index=False)


def run_twin(session: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(SCRIPTS / "compute_twins.py"), "--session", session, "--data-dir", str(ENV),
                           "--config", str(TMP / "config.json"), "--rules", str(TMP / "rules.json"),
                           "--state", str(TMP / "state.json"), "--out", str(TMP / "twins.json"),
                           "--trades", str(TMP / "trades.jsonl"), "--spells", str(TMP / "spells.jsonl"),
                           "--prices", str(ENV / "source" / "prices_daily.parquet"),
                           "--tournament", str(ENV / "tournament.json"), *extra],
                          capture_output=True, text=True, cwd=str(TMP))


def trades(session=None) -> list[dict]:
    rows = tw.read_jsonl(TMP / "trades.jsonl")
    return [r for r in rows if session is None or r["session"] == session]


def spells(event=None) -> list[dict]:
    rows = tw.read_jsonl(TMP / "spells.jsonl")
    return [r for r in rows if event is None or r["event"] == event]


def state() -> dict:
    return json.load(open(TMP / "state.json"))["twins"]["tc"]


def ok(cp: subprocess.CompletedProcess):
    assert cp.returncode == 0, cp.stdout + cp.stderr
    return cp.stdout


# ─── tests (sequential: the state carries from one to the next) ──────────────────────────
def test_01_seed_buys_top_k_at_equal_weight_from_all_cash():
    write_env()
    write_scores({"A": 40, "B": 39, "C": 38, "D": 37, "E": 36, "F": 35, "G": 34, "H": 33})
    out = ok(run_twin(S[0]))
    assert "SEED" in out, out
    tr = trades(S[0])
    assert [t["ticker"] for t in tr] == ["A", "B", "C"] and all(t["reason"] == "SEED" and t["action"] == "buy" for t in tr)
    per = START_CAP * (1 - 0.20) / K                       # 26,666.67 each
    for t in tr:
        assert abs(t["value"] - per) < 0.01 and abs(t["shares"] - per / 100) < 1e-4 and abs(t["cost"] - RATE * per) < 1e-3
        assert t["source"] == "twin_engine" and t["tier"] == "tc" and t["regime_R"] == 0.2 and t["regime_label"] == "LOW RISK"
        assert t["trade_id"] == f"tc-{S[0]}-{t['ticker']}-buy"
    assert [t["tier_rank"] for t in tr] == [1, 2, 3] and [t["tier_composite"] for t in tr] == [40.0, 39.0, 38.0]
    assert [t["composite_rank"] for t in tr] == [1, 2, 3]
    a, b, c = tr
    assert a["bq_score"] == 55.0 and a["bq_rank"] == 1 and b["bq_score"] is None and "Business Quality" in b["scores_note"]
    assert a["tn_score"] == 80 and a["tn_rank"] == 1 and b["tn_score"] == 60 and b["tn_rank"] == 2
    assert c["tn_score"] is None and "Trade-Now" in c["scores_note"]
    st = state()
    assert abs(st["cash"] - (START_CAP - 3 * per * (1 + RATE))) < 1e-6, st["cash"]
    assert st["last_session"] == S[0] and st["start_date"] == S[0] and set(st["positions"]) == {"A", "B", "C"}
    assert st["history"][-1]["nav"] == round(START_CAP - 3 * per * RATE, 2)
    op = spells("opened")
    assert [s["ticker"] for s in op] == ["A", "B", "C"] and all(s["entry_price"] == 100 and s["entry_session"] == S[0] for s in op)
    assert op[0]["scores_at_entry"] == {"tier_composite": 40.0, "tier_rank": 1, "composite_rank": 1, "bq_score": 55.0, "tn_score": 80}
    tj = json.load(open(TMP / "twins.json"))
    assert tj["cadence"] == "daily" and tj["session_date"] == S[0] and tj["start_date"] == S[0]
    assert tj["rules_sha256"] == hashlib.sha256((TMP / "rules.json").read_bytes()).hexdigest()
    assert tj["twins"]["tc"]["parent_tier"] == "t_test" and tj["twins"]["tc"]["n_positions"] == 3
    assert tj["twins"]["tc"]["trade_counts"] == {"SEED": 3}
    assert all(abs(p["weight"] - p["target_weight"]) < 0.05 for p in tj["twins"]["tc"]["positions"])


def test_02_same_session_twice_is_a_noop():
    before = (_digest(TMP / "state.json"), _digest(TMP / "trades.jsonl"), _digest(TMP / "spells.jsonl"), _digest(TMP / "twins.json"))
    out = ok(run_twin(S[0]))
    assert "already processed" in out, out
    after = (_digest(TMP / "state.json"), _digest(TMP / "trades.jsonl"), _digest(TMP / "spells.jsonl"), _digest(TMP / "twins.json"))
    assert before == after
    # and a non-session is refused outright
    cp = run_twin("2026-03-07")                                            # a Saturday
    assert cp.returncode != 0 and "non_session" in (cp.stdout + cp.stderr)


def test_03_rank_exit_on_dropout_then_rank_entry_fills_the_slot():
    cash0 = state()["cash"]
    write_scores({"A": 40, "B": 39, "D": 38.5, "E": 36, "F": 35, "G": 34, "H": 33})      # C left the scored file
    ok(run_twin(S[1]))
    tr = trades(S[1])
    assert [(t["ticker"], t["action"], t["reason"]) for t in tr] == [("C", "sell", "RANK_EXIT"), ("D", "buy", "RANK_ENTRY")], tr
    c, d = tr
    assert abs(c["shares"] - START_CAP * 0.8 / K / 100) < 1e-4 and "left the scored file" in c["detail"]
    assert c["tier_rank"] is None and "not in scored_universe.csv" in c["scores_note"]
    # D is sized at (1 − cp)/K of the NAV at decision
    assert abs(d["weight_delta"] - 0.8 / K) < 1e-6 and abs(d["value"] - 0.8 / K * d["nav_at_decision"]) < 0.02
    assert d["tier_rank"] == 3 and d["tier_composite"] == 38.5 and "open slot" in d["detail"]
    st = state()
    assert set(st["positions"]) == {"A", "B", "D"}
    # cash: one day of EFFR (0.0001) on the opening cash, plus the C sale net of cost, less D's buy plus cost
    exp = cash0 * 1.0001 + c["value"] - c["cost"] - d["value"] - d["cost"]
    assert abs(st["cash"] - exp) < 0.02, (st["cash"], exp)                    # value is logged at 2 dp
    cl = spells("closed")
    assert len(cl) == 1 and cl[0]["ticker"] == "C" and cl[0]["exit_reason"] == "RANK_EXIT" and cl[0]["exit_trade_id"] == c["trade_id"]
    assert cl[0]["return"] == 0.0 and abs(cl[0]["spy_return"] - 0.01) < 1e-9 and abs(cl[0]["excess_vs_spy"] + 0.01) < 1e-9
    assert cl[0]["basket_thesis"] == "th1" and cl[0]["basket_return"] == 0.0 and cl[0]["excess_vs_basket"] == 0.0
    assert cl[0]["sessions_held"] == 1 and cl[0]["spell_id"] == f"tc-C-{S[0]}"
    assert [s["ticker"] for s in spells("opened")] == ["A", "B", "C", "D"]


def test_04_displacement_below_delta_does_not_fire_and_cash_accrues_effr():
    cash0 = state()["cash"]
    LABEL_BY[S[2]] = "ELEVATED"                                  # corridor label differs from the threshold label at R=0.2
    write_env()
    write_scores({"A": 40, "B": 39, "E": 38.9, "D": 37.0, "F": 35, "G": 34, "H": 33})   # E − D = 1.9 < δ
    ok(run_twin(S[2]))
    assert trades(S[2]) == []
    st = state()
    assert abs(st["cash"] - cash0 * 1.0001) < 1e-6
    assert st["history"][-1]["regime"] == "ELEVATED" and st["history"][-1]["n_trades"] == 0


def test_05_displacement_at_delta_fires_once():
    write_scores({"A": 40, "B": 39, "E": 39.0, "D": 37.0, "F": 35, "G": 34, "H": 33})   # E − D = 2.0 ≥ δ
    ok(run_twin(S[3]))
    tr = trades(S[3])
    assert [(t["ticker"], t["action"], t["reason"]) for t in tr] == [("D", "sell", "RANK_EXIT"), ("E", "buy", "RANK_ENTRY")], tr
    assert "displaced by E" in tr[0]["detail"] and "displaces D" in tr[1]["detail"]
    assert set(state()["positions"]) == {"A", "B", "E"}
    cl = [s for s in spells("closed") if s["ticker"] == "D"]
    assert len(cl) == 1 and cl[0]["exit_reason"] == "RANK_EXIT" and cl[0]["basket_thesis"] == "th2" and cl[0]["sessions_held"] == 2
    assert cl[0]["basket_return"] == 0.0                                         # D's basket = [C], flat


def test_06_rank_exit_beyond_2k_not_at_2k():
    # B at rank 6 = 2K stays (and F − B = 1.5 < δ: no displacement)
    write_scores({"A": 40, "E": 39, "F": 36.5, "G": 36, "H": 35.5, "B": 35, "D": 34, "C": 33})
    ok(run_twin(S[4]))
    assert trades(S[4]) == [], trades(S[4])
    # B at rank 7 > 2K exits; the slot is filled with the best-ranked top-K name not held (F)
    write_scores({"A": 40, "E": 39, "F": 36.5, "G": 36, "H": 35.5, "D": 35.2, "B": 35, "C": 33})
    ok(run_twin(S[5]))
    tr = trades(S[5])
    assert [(t["ticker"], t["action"], t["reason"]) for t in tr] == [("B", "sell", "RANK_EXIT"), ("F", "buy", "RANK_ENTRY")], tr
    assert "rank 7 > 2K=6" in tr[0]["detail"] and tr[0]["tier_rank"] == 7
    assert set(state()["positions"]) == {"A", "E", "F"}
    cl = [s for s in spells("closed") if s["ticker"] == "B"]
    assert len(cl) == 1 and cl[0]["basket_thesis"] is None and "no thesis" in cl[0]["basket_note"] and cl[0]["excess_vs_basket"] is None


def _actual_cash_next(st: dict) -> float:
    """actual cash share the engine will see next session (one day of EFFR, flat prices at 100)."""
    cash = st["cash"] * 1.0001
    eq = sum(st["positions"].values()) * 100.0
    return cash / (cash + eq)


def test_07_regime_cash_gap_5_1_fires_4_9_does_not_and_records_the_corridor_label():
    st = state()
    actual = _actual_cash_next(st)
    R_BY[S[6]] = ((actual + 0.049) - 0.10) / 0.5                                  # target = actual + 4.9 pts
    write_env()
    ok(run_twin(S[6]))
    assert trades(S[6]) == [], trades(S[6])
    row = state()["history"][-1]
    assert abs(row["target_cash_pct"] - row["actual_cash_pct"] - 4.9) < 0.15, row
    st = state()
    actual = _actual_cash_next(st)
    cp = actual + 0.051                                                             # gap 5.1 pts
    R_BY[S[7]] = (cp - 0.10) / 0.5
    LABEL_BY[S[7]] = "HIGH RISK"                                                    # the corridor label, not the threshold's
    write_env()
    ok(run_twin(S[7]))
    tr = trades(S[7])
    assert len(tr) == 3 and all(t["reason"] == "REGIME_CASH" and t["action"] == "sell" for t in tr), tr
    assert all(t["regime_label"] == "HIGH RISK" and abs(t["regime_R"] - R_BY[S[7]]) < 1e-9 for t in tr)
    # pro rata: every position sells the same fraction of its value; the gap closes (to within the costs)
    fr = [t["value"] / (st["positions"][t["ticker"]] * 100.0) for t in tr]
    assert max(fr) - min(fr) < 1e-5, fr
    row = state()["history"][-1]
    assert abs(row["actual_cash_pct"] - row["target_cash_pct"]) < 0.1, row
    st2 = state()
    nav = st2["cash"] + sum(st2["positions"].values()) * 100
    assert abs(st2["cash"] / nav - cp) < 0.0005


def _price_for_deviation(st: dict, tk: str, dev: float, cp: float) -> float:
    """price of tk next session such that its weight = (1 + dev) × target, flat 100 elsewhere."""
    cash = st["cash"] * 1.0001
    others = sum(s for t, s in st["positions"].items() if t != tk) * 100.0
    tw_ = (1 - cp) / len(st["positions"])
    g = (1 + dev) * tw_ * (cash + others) / (st["positions"][tk] * 100.0 * (1 - (1 + dev) * tw_))
    return 100.0 * g


def test_08_drift_26_pct_fires_24_pct_does_not():
    cp = 0.10 + 0.5 * R_BY[S[7]]
    R_BY[S[8]] = R_BY[S[9]] = R_BY[S[7]]                                           # same target; gap stays small
    st = state()
    p24 = _price_for_deviation(st, "F", 0.24, cp)
    PX.loc[pd.Timestamp(S[8]):, "F"] = p24
    write_env()
    ok(run_twin(S[8]))
    assert trades(S[8]) == [], trades(S[8])
    st = state()
    p26 = _price_for_deviation(st, "F", 0.26, cp)
    PX.loc[pd.Timestamp(S[9]):, "F"] = p26                                         # F stays there afterwards
    write_env()
    ok(run_twin(S[9]))
    tr = trades(S[9])
    assert len(tr) == 1 and tr[0]["ticker"] == "F" and tr[0]["reason"] == "DRIFT" and tr[0]["action"] == "sell", tr
    assert "+26.0% of target" in tr[0]["detail"], tr[0]["detail"]
    tj = json.load(open(TMP / "twins.json"))
    f = next(p for p in tj["twins"]["tc"]["positions"] if p["ticker"] == "F")
    assert abs(f["weight"] - f["target_weight"]) < 0.05, f


def test_09_cost_is_10_bps_of_session_one_way_turnover_allocated_pro_rata():
    tr = trades()
    assert tr and all(t["reason"] in tw.REASONS for t in tr) and len({t["trade_id"] for t in tr}) == len(tr)
    assert all(t["cost_basis"] == "session one-way turnover, allocated pro rata" for t in tr)
    st = state()
    hist = {h["date"]: h for h in st["history"]}
    by_session = {}
    for t in tr:
        by_session.setdefault(t["session"], []).append(t)
    for s, rows in by_session.items():
        h = hist[s]
        assert abs(h["cost"] - RATE * h["turnover_one_way"] * h["nav_pre"]) < 1e-3, h          # 10 bps × turnover × pre-trade NAV (6-dp turnover)
        assert abs(sum(r["cost"] for r in rows) - h["cost"]) < 1e-3 * len(rows), (s, h["cost"])    # allocated in full
        ratio = h["cost"] / sum(r["value"] for r in rows)
        assert all(abs(r["cost"] - ratio * r["value"]) < 2e-4 for r in rows), (s, rows)             # pro rata to traded value (4-dp costs; a per-trade 10 bps would be off by dollars)
    assert all(h["turnover_one_way"] == 0.0 and h["cost"] == 0.0 for h in st["history"] if h["n_trades"] == 0)
    # SEED from all cash: turnover = equity share 0.8 → cost = 10 bps × 80,000
    assert abs(hist[S[0]]["turnover_one_way"] - 0.8) < 1e-9 and abs(hist[S[0]]["cost"] - RATE * 0.8 * START_CAP) < 1e-6
    # a swap of C for D of (almost) equal value x turns over x: cost = 10 bps × x, not 2x
    c_sell = next(t for t in by_session[S[1]] if t["ticker"] == "C")
    assert abs(hist[S[1]]["cost"] - RATE * c_sell["value"]) < 0.03, (hist[S[1]]["cost"], c_sell["value"])
    assert abs(st["cost_paid_total"] - sum(h["cost"] for h in st["history"])) < 1e-3
    assert st["trade_counts"] == {"SEED": 3, "RANK_EXIT": 3, "RANK_ENTRY": 3, "REGIME_CASH": 3, "DRIFT": 1}


def test_10_followups_at_20_and_60_sessions_after_exit():
    # C left at S[1]: +20 → S[21], +60 → S[61]. C's later closes: 110 from S[21], 120 from S[61].
    PX.loc[pd.Timestamp(S[21]):, "C"] = 110.0
    PX.loc[pd.Timestamp(S[61]):, "C"] = 120.0
    R_BY[S[70]] = R_BY[S[9]]
    write_env()
    write_scores({"A": 40, "E": 39, "F": 36.5, "G": 36, "H": 35.5, "D": 35.2, "B": 35, "C": 33})
    out = ok(run_twin(S[70]))
    assert "follow-up events appended: 6" in out, out
    fu = {(s["spell_id"], s["event"]): s for s in spells() if s["event"].startswith("followup")}
    assert len(fu) == 6
    c20 = fu[(f"tc-C-{S[0]}", "followup_20")]
    assert c20["horizon"] == 20 and c20["horizon_session"] == S[21]
    assert abs(c20["return"] - 0.10) < 1e-9 and abs(c20["spy_return"] - 0.01) < 1e-9 and abs(c20["excess_vs_spy"] - 0.09) < 1e-9
    assert c20["basket_return"] == 0.0 and abs(c20["excess_vs_basket"] - 0.10) < 1e-9
    assert abs(c20["post_exit_return"] - 0.10) < 1e-9 and c20["post_exit_spy_return"] == 0.0 and abs(c20["post_exit_excess_vs_spy"] - 0.10) < 1e-9
    c60 = fu[(f"tc-C-{S[0]}", "followup_60")]
    assert c60["horizon_session"] == S[61] and abs(c60["return"] - 0.20) < 1e-9
    d20 = fu[(f"tc-D-{S[1]}", "followup_20")]                                      # D left at S[3]: +20 → S[23]; basket [C]: 100 → 110 over (S[3], S[23]]
    assert d20["horizon_session"] == S[23] and d20["return"] == 0.0 and abs(d20["basket_return"] - 0.10) < 1e-9 and abs(d20["excess_vs_basket"] + 0.10) < 1e-9
    b20 = fu[(f"tc-B-{S[0]}", "followup_20")]
    assert b20["basket_return"] is None and "no thesis" in b20["basket_note"]
    # a later run appends no duplicate follow-ups
    out = ok(run_twin(S[71]))
    assert "follow-up events appended" not in out, out
    assert len([s for s in spells() if s["event"].startswith("followup")]) == 6


def test_11_backfill_is_idempotent_and_finds_the_four_reconstitutions():
    bt = TMP / "backfill"
    bt.mkdir(exist_ok=True)
    shutil.copy(DATA / "tournament.json", bt / "tournament.json")
    args = [PY, str(SCRIPTS / "backfill_tier_logs.py"), "--tournament", str(bt / "tournament.json"),
            "--trades", str(bt / "trades.jsonl"), "--spells", str(bt / "spells.jsonl"), "--no-git", "--session", "2026-09-29"]
    cp = subprocess.run(args, capture_output=True, text=True, cwd=str(TMP))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    tr = tw.read_jsonl(bt / "trades.jsonl")
    sp = tw.read_jsonl(bt / "spells.jsonl")
    assert tr and len({t["trade_id"] for t in tr}) == len(tr)
    for tid in ("1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"):
        dates = sorted({t["session"] for t in tr if t["tier"] == tid})
        assert dates == ["2026-05-20", "2026-06-01", "2026-07-01", "2026-08-03", "2026-09-01"], (tid, dates)
        seed = [t for t in tr if t["tier"] == tid and t["session"] == "2026-05-20"]
        assert all(t["reason"] == "SEED" and t["action"] == "buy" for t in seed)
        assert all(t["reason"] == "RECONSTITUTION" for t in tr if t["tier"] == tid and t["session"] != "2026-05-20")
    assert all(t["source"] == "monthly_backfill" and t["cost_basis"] == "session one-way turnover, allocated pro rata" for t in tr)
    # the session's C1 charge is allocated pro rata; at inception it is 10 bps × the equity share × $100k
    tj = json.load(open(bt / "tournament.json"))
    for tid in ("1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"):
        for s in ("2026-05-20", "2026-06-01", "2026-07-01", "2026-08-03", "2026-09-01"):
            rows = [t for t in tr if t["tier"] == tid and t["session"] == s]
            ratio = sum(t["cost"] for t in rows) / sum(t["value"] for t in rows)
            assert ratio > 0 and all(abs(t["cost"] - ratio * t["value"]) < 2e-4 for t in rows), (tid, s)   # 4-dp costs
        row0 = next(h for h in tj["history"] if h["date"] == "2026-05-20")["tiers"][tid]
        ep = row0["equity"] / row0["nav"]
        seed_cost = sum(t["cost"] for t in tr if t["tier"] == tid and t["session"] == "2026-05-20")
        assert abs(seed_cost - RATE * ep * 100000.0) < 0.05, (tid, seed_cost, RATE * ep * 100000.0)
    assert all(t["tier_composite"] is None and "--no-git" in t["scores_note"] for t in tr)
    assert not any(t["tier"] == "5_werner" for t in tr)
    opened = [s for s in sp if s["event"] == "opened"]
    entries = [t for t in tr if t["action"] == "buy" and t["trade_id"] in {s["entry_trade_id"] for s in opened}]
    assert len(opened) == len(entries) and len({s["spell_id"] for s in opened}) == len(opened)
    closed = [s for s in sp if s["event"] == "closed"]
    assert closed and all(s["exit_reason"] == "RECONSTITUTION" and s["return"] is not None and s["excess_vs_spy"] is not None for s in closed)
    assert any(s["event"] == "followup_20" for s in sp) and any(s["event"] == "followup_60" for s in sp)
    n_tr, n_sp = len(tr), len(sp)
    cp = subprocess.run(args, capture_output=True, text=True, cwd=str(TMP))
    assert cp.returncode == 0 and "new trades 0" in cp.stdout, cp.stdout + cp.stderr
    assert len(tw.read_jsonl(bt / "trades.jsonl")) == n_tr and len(tw.read_jsonl(bt / "spells.jsonl")) == n_sp


def test_12_cash_formula_and_ranking_match_the_monthly_pipeline():
    try:
        import compute_nav  # noqa: F401  (pulls in the provider client; skip the comparison if absent)
        for spec in ({"cash_floor": 0.25, "cash_slope": 0.75, "cash_max": 1.0}, {"cash_floor": 0.0, "cash_slope": 1.0, "cash_max": 1.0},
                     {"cash_floor": 0.1, "cash_slope": 0.4, "cash_max": 0.5}):
            for R in (0.0, 0.1, 0.29, 0.5, 0.9, 1.2):
                assert tw.cash_pct_from_formula(R, spec) == compute_nav.cash_pct_from_formula(R, spec)
    except ImportError:
        pass
    from select_tiers import select_for_tier
    cfg = json.load(open(REPO / "config.json"))
    scored = pd.read_csv(DATA / "scored_universe.csv")
    for tid, spec in cfg["tier_specs"].items():
        ranked = tw.rank_universe(scored, spec)
        assert ranked["ticker"].head(spec["n_holdings"]).tolist() == select_for_tier(scored, spec), tid
        assert ranked["tier_rank"].tolist() == list(range(1, len(ranked) + 1))


# ─── guard ───────────────────────────────────────────────────────────────────────────────
def test_zz_repository_data_untouched():
    assert _listing(DATA) == _GUARD["data"] and _listing(TDIR) == _GUARD["tdir"]
    for n, d in _GUARD["files"].items():
        assert _digest(TDIR / n) == d, n
    assert _digest(DATA / "tournament.json") == _GUARD["tournament"] and _digest(DATA / "scored_universe.csv") == _GUARD["scored"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    try:
        for name, fn in tests:
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
