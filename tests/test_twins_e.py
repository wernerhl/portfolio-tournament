#!/usr/bin/env python3
"""
tests/test_twins_e.py — order of 8 October 2026, J7 (item 8): the entry-state twins (scripts/compute_twins.py,
mode "entry_state") and their registered comparison (scripts/twins_e_report.py).

Run with the venv interpreter (no pytest dependency):
    .venv/bin/python tests/test_twins_e.py

A synthetic scored universe, price series and entry-state file drive one c twin (tc) and one e twin (te) of the
same test tier (K=3, δ=2.0, 2K=6, cash 0.10+0.5R = 0.20) through: nothing for the e twin before first_session;
the seed that skips WATCH/AVOID names and takes the next READY names, READY-HALF at half weight with the other
half in cash; the cash the entry rule leaves is not re-invested by the cash-gap or drift rules; STOP_EXIT on a
close below the stop recorded at purchase (the file's later stop is irrelevant; a close AT the stop does not
fire) with no re-entry on the stop session; re-entry only after a later READY session (a WATCH session does
not clear it); stale / changed entry-state inputs sit the e twin out while the c twin proceeds, and a rerun of
the session restarts it from its saved stops and flags; the c twin is byte-for-byte the same with and without
the e block (a second run set B carries no block); --out-dir never writes under data/; the report with no e
data and on synthetic NAVs (Newey-West t against the analyst module's function, drawdowns, the 12- and 24-month
verdict sessions and rules, the power statement after three months, a missing session skipped on both sides);
the live registration is consistent (pinned sha256 = the frozen config's). Everything is written under a
temporary directory; the last test asserts that nothing under data/ changed.
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

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
DATA = REPO / "data"
TDIR = DATA / "tournament"
PY = sys.executable
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "analyst"))
import compute_twins as tw  # noqa: E402
import twins_e_report as rp  # noqa: E402
from trading_calendar import is_trading_day  # noqa: E402


# ─── guard: nothing under data/ may change ───────────────────────────────────────────────
def _digest(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _listing(p: Path):
    return sorted(x.name for x in p.iterdir()) if p.exists() else None


_GUARD = {"data": _listing(DATA), "tdir": _listing(TDIR),
          "files": {n: _digest(TDIR / n) for n in ("trades.jsonl", "spells.jsonl", "twins_state.json", "twins.json",
                                                    "continuous_rules.json", "twins_e_comparison.json")},
          "entry": {n: _digest(DATA / n) for n in ("entry_state.json", "entry_state_config.json")}}

# ─── the synthetic environment ───────────────────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="twins_e_test_"))
ENV = TMP / "data"
NAMES = list("ABCDEFGH")
START_CAP = 100000.0
RATE = 0.001
K = 3
CP = 0.20                                  # 0.10 + 0.5 × R, R = 0.2
SLOT = (1 - CP) / K                        # 26.667 % of NAV per slot


def sessions_from(start: str, n: int) -> list[str]:
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if is_trading_day(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


S = sessions_from("2026-03-02", 30)
PX = pd.DataFrame(100.0, index=pd.to_datetime(S), columns=NAMES)
SPY = pd.Series(505.0, index=pd.to_datetime(S), name="spy")
SCORES = {"A": 40, "B": 39, "C": 38, "D": 37, "E": 36, "F": 35, "G": 34, "H": 33}      # ranks 1..8, 2K = 6


def write_env():
    (ENV / "source").mkdir(parents=True, exist_ok=True)
    (ENV / "screen").mkdir(exist_ok=True)
    (ENV / "tournament").mkdir(exist_ok=True)
    PX.to_parquet(ENV / "source" / "prices_daily.parquet")
    SPY.to_frame().to_parquet(ENV / "source" / "sector_etfs.parquet")
    pd.DataFrame({"date": S, "R_t": [0.2] * len(S)}).to_csv(ENV / "regime_daily.csv", index=False)
    pd.DataFrame({"date": S, "R_full": [0.2] * len(S), "regime": ["LOW RISK"] * len(S)}).to_csv(ENV / "regime_v2_daily.csv", index=False)
    json.dump({"history": [{"date": s, "effr_daily_pct": 2.52} for s in S]}, open(ENV / "tournament.json", "w"))
    json.dump({"theses": {}}, open(ENV / "thesis_registry.json", "w"))
    json.dump({"watchlist": []}, open(ENV / "screen" / "scores.json", "w"))
    json.dump({"signals": {}}, open(ENV / "ticker_signals.json", "w"))
    json.dump({"tier_specs": {"t_test": {"short": "TEST", "color": "#000000", "n_holdings": K, "cash_floor": 0.10, "cash_slope": 0.5,
                                         "cash_max": 0.60, "universe_filter": None,
                                         "factor_weights": {"ma200": 1, "rsi": 1, "rs6m": 1}}},
               "system_settings": {"inception_capital_per_tier": 100000}}, open(TMP / "config.json", "w"))
    write_entry_config({"version": 3, "note": "test configuration of the entry-state rules"})
    rules = json.load(open(TDIR / "continuous_rules.json"))
    rules["twins"] = {"tc": "t_test"}
    rules_b = {k: v for k, v in rules.items() if k != tw.E_BLOCK}                 # run set B: no e block at all
    json.dump(rules_b, open(TMP / "rules_B.json", "w"), indent=1)
    rules[tw.E_BLOCK] = {**rules[tw.E_BLOCK], "first_session": S[1], "twins": {"te": "t_test"}, "twin_of": {"te": "tc"},
                         "entry_state_rules_version": 3, "entry_state_file": "entry_state.json",
                         "entry_state_config_file": "entry_state_config.json",
                         "entry_state_config_sha256": _digest(ENV / "entry_state_config.json")}
    json.dump(rules, open(TMP / "rules_A.json", "w"), indent=1)


def write_entry_config(obj: dict):
    json.dump(obj, open(ENV / "entry_state_config.json", "w"))


def write_scores(comps: dict):
    rows = []
    order = sorted(comps, key=lambda t: -comps[t])
    for t, c in comps.items():
        rows.append({"ticker": t, "sector": "Technology", "grossMargins": 0.5, "freeCashflow": 1.0,
                     "ma200_rank": c / 25, "rsi_rank": c / 25, "rs6m_rank": c / 25, "fund_score": 0.0,
                     "composite": c, "composite_rank": order.index(t) + 1})
    pd.DataFrame(rows).to_csv(ENV / "scored_universe.csv", index=False)


def write_entry_states(session: str, states: dict, file_session: str | None = None, version: int = 3):
    """states: {ticker: (state, stop)}; the close is the price store's close on the session."""
    names = {}
    for t, (st, stop) in states.items():
        names[t] = {"state": st, "stop": stop, "close": float(PX.loc[pd.Timestamp(session), t]),
                    "size_factor": {"READY": 1.0, "READY-HALF": 0.5}.get(st)}
    json.dump({"cadence": "daily", "session_date": file_session or session, "rules_version": version,
               "config_frozen_at": "2026-10-06", "names": names}, open(ENV / "entry_state.json", "w"))


STATES_1 = {"A": ("READY", 90.0), "B": ("WATCH", 80.0), "C": ("AVOID", 70.0), "D": ("READY-HALF", 92.0),
            "E": ("READY", 95.0), "F": ("READY", 93.0), "G": ("AVOID", 60.0), "H": ("READY", 50.0)}


def run(session: str, tag: str = "A", *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(SCRIPTS / "compute_twins.py"), "--session", session, "--data-dir", str(ENV),
                           "--config", str(TMP / "config.json"), "--rules", str(TMP / f"rules_{tag}.json"),
                           "--state", str(TMP / f"state_{tag}.json"), "--out", str(TMP / f"twins_{tag}.json"),
                           "--trades", str(TMP / f"trades_{tag}.jsonl"), "--spells", str(TMP / f"spells_{tag}.jsonl"),
                           "--prices", str(ENV / "source" / "prices_daily.parquet"),
                           "--tournament", str(ENV / "tournament.json"), *extra],
                          capture_output=True, text=True, cwd=str(TMP))


def ok(cp: subprocess.CompletedProcess) -> str:
    assert cp.returncode == 0, cp.stdout + cp.stderr
    return cp.stdout


def run_both(session: str) -> str:
    out = ok(run(session, "A"))
    ok(run(session, "B"))
    return out


def trades(session=None, tier="te", tag="A") -> list[dict]:
    rows = tw.read_jsonl(TMP / f"trades_{tag}.jsonl")
    return [r for r in rows if (session is None or r["session"] == session) and (tier is None or r["tier"] == tier)]


def spells(event=None, tier="te", tag="A") -> list[dict]:
    rows = tw.read_jsonl(TMP / f"spells_{tag}.jsonl")
    return [r for r in rows if (event is None or r["event"] == event) and (tier is None or r["tier"] == tier)]


def state(tier="te", tag="A") -> dict | None:
    return json.load(open(TMP / f"state_{tag}.json"))["twins"].get(tier)


def twins_json(tag="A") -> dict:
    return json.load(open(TMP / f"twins_{tag}.json"))


def e_served(tag="A") -> dict:
    return twins_json(tag)[tw.E_BLOCK]["twins"]["te"]


# ─── tests (sequential: the state carries from one to the next) ──────────────────────────
def test_01_before_first_session_the_e_twin_produces_nothing():
    write_env()
    write_scores(SCORES)
    write_entry_states(S[0], STATES_1)
    out = run_both(S[0])
    assert "tc (TEST)" in out and "te (TEST)" not in out and "entry states" not in out, out
    assert state("tc") is not None and state("te") is None
    assert trades(tier="te") == [] and [t["ticker"] for t in trades(S[0], tier="tc")] == ["A", "B", "C"]
    tj = twins_json()
    assert set(tj["twins"]) == {"tc"} and "mode" not in tj["twins"]["tc"]
    blk = tj[tw.E_BLOCK]
    assert blk["active"] is False and blk["twins"] == {} and blk["first_session"] == S[1] and blk["check"]["reason"] == "before first_session"
    assert blk["entry_state_config_sha256"] == _digest(ENV / "entry_state_config.json")
    assert "STOP_EXIT" in tj["reason_codes"] and "STOP_EXIT" in tw.REASONS
    assert tw.E_BLOCK not in twins_json("B")


def test_02_seed_skips_watch_and_avoid_takes_the_next_ready_half_weight_for_ready_half():
    write_entry_states(S[1], STATES_1)
    out = run_both(S[1])
    assert "entry states: entry_state.json" in out and "[entry rule: 3 taken, 2 replacements, 1 half; 2 skipped" in out, out
    tr = trades(S[1])
    assert [(t["ticker"], t["action"], t["reason"]) for t in tr] == [("A", "buy", "SEED"), ("D", "buy", "SEED"), ("E", "buy", "SEED")], tr
    a, d, e = tr
    full = START_CAP * SLOT
    assert abs(a["value"] - full) < 0.01 and abs(e["value"] - full) < 0.01 and abs(d["value"] - full / 2) < 0.01, (a["value"], d["value"])
    assert a["trade_id"] == f"te-{S[1]}-A-buy" and a["tier"] == "te" and a["tier_rank"] == 1 and d["tier_rank"] == 4 and e["tier_rank"] == 5
    assert "entry state READY" in a["detail"] and "stop 90.00" in a["detail"] and "replaces" not in a["detail"]
    assert "READY-HALF" in d["detail"] and "half the slot" in d["detail"] and "replaces a top-K name" in d["detail"] and "stop 92.00" in d["detail"]
    assert "replaces a top-K name" in e["detail"]
    assert trades(S[1], tier="tc") == []                                           # the c twin: nothing to do
    st = state()
    assert st["mode"] == "entry_state" and st["start_date"] == S[1] and set(st["positions"]) == {"A", "D", "E"}
    assert st["entry_stops"] == {"A": {"stop": 90.0, "entry_session": S[1], "size_factor": 1.0, "state": "READY"},
                                 "D": {"stop": 92.0, "entry_session": S[1], "size_factor": 0.5, "state": "READY-HALF"},
                                 "E": {"stop": 95.0, "entry_session": S[1], "size_factor": 1.0, "state": "READY"}}, st["entry_stops"]
    assert st["stopped_out"] == {}
    h = st["history"][-1]
    assert h["target_cash_pct"] == 33.3 and h["formula_cash_pct"] == 20.0 and h["n_half_slots"] == 1 and h["n_positions"] == 3
    cost = RATE * (2.5 * SLOT) * START_CAP                                          # 10 bps × one-way turnover × NAV
    assert abs(st["cash"] - (START_CAP - 2.5 * full - cost)) < 0.02, (st["cash"], cost)
    assert abs(h["cost"] - cost) < 1e-3
    assert "mode" not in state("tc") and "entry_stops" not in state("tc")
    sv = e_served()
    assert sv["mode"] == "entry_state" and sv["twin_of"] == "tc" and sv["n_half_slots"] == 1 and sv["n_empty_slots"] == 0
    assert sv["formula_cash_pct"] == 20.0 and sv["target_cash_pct"] == 33.3 and abs(sv["slot_weight_pct"] - 26.67) < 0.01
    pos = {p["ticker"]: p for p in sv["positions"]}
    assert pos["D"]["size_factor"] == 0.5 and pos["D"]["entry_stop"] == 92.0 and pos["D"]["entry_state_at_entry"] == "READY-HALF"
    assert abs(pos["D"]["target_weight"] - 13.33) < 0.01 and abs(pos["A"]["target_weight"] - 26.67) < 0.01
    lg = sv["entry_log_session"]
    assert [(x["ticker"], x["state"], x["rank"]) for x in lg["skipped"]] == [("B", "WATCH", 2), ("C", "AVOID", 3)], lg["skipped"]
    assert [(x["ticker"], x["slot"], x["size_factor"]) for x in lg["taken"]] == [("A", "top_k", 1.0), ("D", "replacement", 0.5), ("E", "replacement", 1.0)]
    blk = twins_json()[tw.E_BLOCK]
    assert blk["active"] is True and blk["check"] == {"ok": True, "reason": None} and blk["entry_state_session"] == S[1]
    assert blk["entry_state_config_sha256_at_run"] == blk["entry_state_config_sha256"] == _digest(ENV / "entry_state_config.json")
    assert json.load(open(TMP / "state_A.json"))["entry_state_config_sha256"] == blk["entry_state_config_sha256"]
    op = spells("opened")
    assert [s["ticker"] for s in op] == ["A", "D", "E"] and "stop 92.00" in op[1]["detail"] and "size factor 0.5" in op[1]["detail"]
    assert st["open_spells"]["D"]["stop"] == 92.0 and st["open_spells"]["D"]["size_factor"] == 0.5
    # no page shows the e twin: it is not in the map the tournament page renders
    assert "te" not in twins_json()["twins"]


def test_03_cash_left_by_the_entry_rule_is_not_reinvested_and_the_files_later_stop_is_ignored():
    cash0 = state()["cash"]
    st2 = dict(STATES_1); st2["A"] = ("READY", 99.0)                                # the file's stop moves; the recorded 90 stays
    write_entry_states(S[2], st2)
    run_both(S[2])
    assert trades(S[2]) == [] and trades(S[2], tier="tc") == []
    st = state()
    assert abs(st["cash"] - cash0 * 1.0001) < 1e-6 and st["entry_stops"]["A"]["stop"] == 90.0
    h = st["history"][-1]
    assert h["target_cash_pct"] == 33.3 and abs(h["actual_cash_pct"] - 33.3) < 0.15 and h["n_trades"] == 0, h


def test_04_stop_exit_fires_below_the_recorded_stop_not_at_it_and_no_re_entry_on_the_stop_session():
    PX.loc[pd.Timestamp(S[3]):, "A"] = 89.99                                        # below A's recorded stop 90
    PX.loc[pd.Timestamp(S[3]), "E"] = 95.0                                          # exactly at E's stop: no exit
    write_env()
    st3 = dict(STATES_1); st3["A"] = ("READY", 80.0)                                # A still READY, rank 1; the file's stop is lower
    write_entry_states(S[3], st3)
    out = run_both(S[3])
    tr = trades(S[3])
    assert [(t["ticker"], t["action"], t["reason"]) for t in tr] == [("A", "sell", "STOP_EXIT"), ("F", "buy", "RANK_ENTRY")], tr
    a, f = tr
    assert a["price"] == 89.99 and f"close 89.99 below the entry-state stop 90.00 recorded at entry on {S[1]}" == a["detail"], a["detail"]
    assert abs(a["shares"] - START_CAP * SLOT / 100) < 1e-4
    assert f["tier_rank"] == 6 and "open slot" in f["detail"] and "replaces a top-K name" in f["detail"] and "stop 93.00" in f["detail"]
    st = state()
    assert set(st["positions"]) == {"D", "E", "F"} and "A" not in st["entry_stops"]
    assert st["stopped_out"] == {"A": {"session": S[3], "close": 89.99, "stop": 90.0}}, st["stopped_out"]
    assert st["entry_stops"]["F"] == {"stop": 93.0, "entry_session": S[3], "size_factor": 1.0, "state": "READY"}
    cl = spells("closed")
    assert len(cl) == 1 and cl[0]["ticker"] == "A" and cl[0]["exit_reason"] == "STOP_EXIT" and cl[0]["exit_trade_id"] == a["trade_id"]
    assert abs(cl[0]["return"] - (89.99 / 100 - 1)) < 1e-9 and cl[0]["sessions_held"] == 2
    lg = e_served()["entry_log_session"]
    assert [x["ticker"] for x in lg["stops"]] == ["A"]
    skipped = {x["ticker"]: x for x in lg["skipped"]}
    assert "A" in skipped and "sold at its stop" in skipped["A"]["reason"], skipped
    assert "1 stops" in out and trades(S[3], tier="tc") == []
    assert state()["history"][-1]["n_stopped_out"] == 1


def test_05_re_entry_only_after_a_later_ready_session_a_watch_session_does_not_clear_it():
    PX.loc[pd.Timestamp(S[4]):, "A"] = 100.0
    write_env()
    st4 = dict(STATES_1); st4["A"] = ("WATCH", 93.0)
    write_entry_states(S[4], st4)
    run_both(S[4])
    assert trades(S[4]) == [] and state()["stopped_out"] == {"A": {"session": S[3], "close": 89.99, "stop": 90.0}}
    assert e_served()["entry_log_session"]["cleared"] == []
    st5 = dict(STATES_1); st5["A"] = ("READY", 93.0)                                # a later READY session clears the flag
    write_entry_states(S[5], st5)
    out = run_both(S[5])
    tr = trades(S[5])
    assert [(t["ticker"], t["action"], t["reason"]) for t in tr] == [("F", "sell", "RANK_EXIT"), ("A", "buy", "RANK_ENTRY")], tr
    assert "displaced by A" in tr[0]["detail"] and "displaces F" in tr[1]["detail"] and "entry state READY" in tr[1]["detail"] and "stop 93.00" in tr[1]["detail"]
    st = state()
    assert st["stopped_out"] == {} and st["entry_stops"]["A"] == {"stop": 93.0, "entry_session": S[5], "size_factor": 1.0, "state": "READY"}
    assert set(st["positions"]) == {"A", "D", "E"}
    assert e_served()["entry_log_session"]["cleared"] == [{"ticker": "A", "stopped_on": S[3], "state": "READY"}]
    assert "may be bought again" in out


def test_06_stale_or_changed_entry_inputs_sit_the_e_twin_out_and_a_rerun_restarts_it():
    write_entry_states(S[6], STATES_1, file_session=S[5])                           # the file is for the previous session
    out = run_both(S[6])
    assert "entry_state_stale" in out and "te: not processed" in out and "tc (TEST)" in out, out
    assert state()["last_session"] == S[5] and state("tc")["last_session"] == S[6]
    tj = twins_json()
    assert tj[tw.E_BLOCK]["check"]["ok"] is False and "entry_state_stale" in tj[tw.E_BLOCK]["check"]["reason"]
    assert "entry_state_stale" in tj[tw.E_BLOCK]["twins"]["te"]["not_processed"] and tj["twins"]["tc"]["last_session"] == S[6]
    n_tr, n_sp = len(trades(tier=None)), len(spells(tier=None))
    # the frozen config changed → not processed either; the registered sha is still reported
    write_entry_states(S[6], STATES_1)
    write_entry_config({"version": 3, "note": "test configuration of the entry-state rules", "changed": True})
    out = ok(run(S[6], "A"))
    assert "entry_state_config_changed" in out and "te: not processed" in out and "tc: already at" in out, out
    assert state()["last_session"] == S[5]
    write_entry_config({"version": 3, "note": "test configuration of the entry-state rules"})
    assert _digest(ENV / "entry_state_config.json") == json.load(open(TMP / "rules_A.json"))[tw.E_BLOCK]["entry_state_config_sha256"]
    # another rules version → not processed
    write_entry_states(S[6], STATES_1, version=4)
    out = ok(run(S[6], "A"))
    assert "entry_state_rules_version" in out and "te: not processed" in out, out
    # the right file → processed on the rerun; the c twin is skipped but still served; the stops carried over
    write_entry_states(S[6], STATES_1)
    out = ok(run(S[6], "A"))
    assert "tc: already at" in out and "te (TEST)" in out, out
    st = state()
    assert st["last_session"] == S[6] and st["history"][-1]["date"] == S[6] and st["entry_stops"]["A"]["stop"] == 93.0
    tj = twins_json()
    assert tj["twins"]["tc"]["last_session"] == S[6] and tj["twins"]["tc"]["nav"] > 0 and tj[tw.E_BLOCK]["check"]["ok"] is True
    assert "not_processed" not in tj[tw.E_BLOCK]["twins"]["te"]
    assert len(trades(tier=None)) == n_tr and len(spells(tier=None)) == n_sp              # a quiet session: no rows
    out = ok(run(S[6], "A"))
    assert "already processed" in out, out


def test_07_the_c_twin_is_the_same_with_and_without_the_e_block():
    def strip(rows):
        return [{k: v for k, v in r.items() if k != "logged_at"} for r in rows]
    assert strip(trades(tier="tc", tag="A")) == strip(trades(tier="tc", tag="B")) and trades(tier="tc", tag="A")
    assert strip(spells(tier="tc", tag="A")) == strip(spells(tier="tc", tag="B"))
    assert state("tc", "A") == state("tc", "B")
    assert twins_json("A")["twins"]["tc"] == twins_json("B")["twins"]["tc"]
    assert not any(t["reason"] == "STOP_EXIT" for t in trades(tier="tc", tag="A"))
    assert "te" not in json.load(open(TMP / "state_B.json"))["twins"]


def test_08_out_dir_writes_elsewhere_and_never_under_data():
    write_entry_states(S[7], STATES_1)
    before = (_digest(TMP / "state_A.json"), _digest(TMP / "trades_A.jsonl"), _digest(TMP / "spells_A.jsonl"), _digest(TMP / "twins_A.json"))
    od = TMP / "preview"
    out = ok(run(S[7], "A", "--out-dir", str(od)))
    assert "out-dir run" in out and before == (_digest(TMP / "state_A.json"), _digest(TMP / "trades_A.jsonl"), _digest(TMP / "spells_A.jsonl"), _digest(TMP / "twins_A.json"))
    assert (od / "twins.json").exists() and (od / "twins_state.json").exists() and (od / "trades.jsonl").exists()
    assert json.load(open(od / "twins_state.json"))["twins"]["te"]["last_session"] == S[7]
    assert all(r["session"] == S[7] for r in tw.read_jsonl(od / "trades.jsonl"))
    bad = TDIR / "_twins_e_test_out"
    cp = run(S[7], "A", "--out-dir", str(bad))
    assert cp.returncode != 0 and "out_dir_under_data" in (cp.stdout + cp.stderr) and not bad.exists()
    run_both(S[7])


def test_09_report_with_no_e_data_reports_no_sessions_yet():
    cp = subprocess.run([PY, str(SCRIPTS / "twins_e_report.py"), "--twins", str(TMP / "twins_B.json"),
                         "--out", str(TMP / "report_none.json")], capture_output=True, text=True, cwd=str(TMP))
    assert cp.returncode == 0 and "no sessions yet" in cp.stdout, cp.stdout + cp.stderr
    r = json.load(open(TMP / "report_none.json"))
    assert r["status"] == "no sessions yet" and r["window"]["sessions"] == 0 and r["verdicts"]["12m"]["status"] == "pending"
    assert r["registered_first_session"] == "2026-10-09" and r["registration_sha256"] == _digest(TDIR / "twins_e_comparison.json")
    cp = subprocess.run([PY, str(SCRIPTS / "twins_e_report.py"), "--twins", str(TMP / "absent.json"), "--no-write"],
                        capture_output=True, text=True, cwd=str(TMP))
    assert cp.returncode == 0 and "no sessions yet" in cp.stdout


def _synthetic_twins(drift: float, n: int = 540, drop_e_session: int | None = None) -> dict:
    """Eight twins over real NYSE sessions from 2026-10-09: the c twins ride a sinusoid, the e twins the
    same plus a daily drift (per tier scaled 0.5, 1, 1.5, 2); a session may be dropped from one e twin."""
    sess = sessions_from("2026-10-09", n)
    t = np.arange(n)
    rc = 0.003 * np.sin(t / 3.0)
    twins, etw = {}, {}
    for i, (c_id, e_id) in enumerate(zip(("1c", "2c", "3c", "4c"), ("1e", "2e", "3e", "4e"))):
        navc = 100000.0 * np.cumprod(1 + np.r_[0.0, rc[1:]])
        re_ = rc + drift * (0.5 + 0.5 * i) + 0.0005 * np.cos(t / 5.0)
        nave = 100000.0 * np.cumprod(1 + np.r_[0.0, re_[1:]])
        hc = [{"date": s, "nav": round(float(v), 2)} for s, v in zip(sess, navc)]
        he = [{"date": s, "nav": round(float(v), 2)} for s, v in zip(sess, nave)]
        if drop_e_session is not None and e_id == "1e":
            he = [h for j, h in enumerate(he) if j != drop_e_session]
        twins[c_id] = {"history": [{"date": "2026-09-29", "nav": 100000.0}] + hc}      # the c twins started earlier
        etw[e_id] = {"history": he}
    return {"session_date": sess[-1], "twins": twins,
            tw.E_BLOCK: {"first_session": "2026-10-09", "active": True, "twin_of": {"1e": "1c", "2e": "2c", "3e": "3c", "4e": "4c"}, "twins": etw}}


def test_10_report_statistics_verdict_sessions_and_power_on_synthetic_navs():
    from walkforward_test import newey_west_t
    reg = json.load(open(TDIR / "twins_e_comparison.json"))
    tj = _synthetic_twins(0.0004)
    rep = rp.build(tj, reg)
    assert rep["start"]["base_session"] == "2026-10-09" and rep["window"]["from"] == "2026-10-09" and rep["start"]["note"] is None
    sess = sessions_from("2026-10-09", 540)
    assert rep["window"]["sessions"] == 539 and rep["pooled"]["n"] == 539 and rep["window"]["through"] == sess[-1]
    # per-tier series = e − c daily returns from the base session; t from the analyst module's function
    for e_id, c_id in (("1e", "1c"), ("4e", "4c")):
        e_nav = np.array([h["nav"] for h in tj[tw.E_BLOCK]["twins"][e_id]["history"]])
        c_nav = np.array([h["nav"] for h in tj["twins"][c_id]["history"] if h["date"] >= "2026-10-09"])
        d = (e_nav[1:] / e_nav[:-1] - 1) - (c_nav[1:] / c_nav[:-1] - 1)
        mu, t_, n_ = newey_west_t(d, 5)
        pr = rep["pairs"][e_id]
        assert pr["c"] == c_id and pr["n"] == n_ == 539 and abs(pr["ann_diff_pct"] - mu * 252 * 100) < 1e-3 and abs(pr["t_nw5"] - t_) < 2e-3, pr
    # the pooled series is the average of the four differences; the drawdowns are peak-to-trough on the window
    ds = []
    for e_id, c_id in rep["pairs_registered"].items():
        e_nav = np.array([h["nav"] for h in tj[tw.E_BLOCK]["twins"][e_id]["history"]])
        c_nav = np.array([h["nav"] for h in tj["twins"][c_id]["history"] if h["date"] >= "2026-10-09"])
        ds.append((e_nav[1:] / e_nav[:-1] - 1) - (c_nav[1:] / c_nav[:-1] - 1))
    pooled = np.mean(ds, axis=0)
    mu, t_, _ = newey_west_t(pooled, 5)
    assert abs(rep["pooled"]["ann_diff_pct"] - mu * 252 * 100) < 1e-3 and abs(rep["pooled"]["t_nw5"] - t_) < 2e-3
    assert abs(rep["pooled"]["tracking_vol_pct"] - pooled.std(ddof=1) * np.sqrt(252) * 100) < 1e-3
    c1 = np.array([h["nav"] for h in tj["twins"]["1c"]["history"] if h["date"] >= "2026-10-09"])
    dd = float(np.min(c1 / np.maximum.accumulate(c1) - 1))
    assert abs(rep["largest_drawdown"]["1c"] - dd) < 1e-4 and rep["largest_drawdown"]["pooled_c"] is not None
    assert rep["largest_drawdown"]["pooled_e"] >= rep["largest_drawdown"]["pooled_c"]        # the drift makes the e index shallower
    # the verdict sessions: the NYSE session nearest 12 and 24 months after the start
    def nearest(target):
        for k in range(0, 10):
            for c in (target - timedelta(days=k), target + timedelta(days=k)):
                if is_trading_day(c):
                    return c.isoformat()
    v12, v24 = rep["verdicts"]["12m"], rep["verdicts"]["24m"]
    assert v12["target_date"] == "2027-10-09" and v12["verdict_session"] == nearest(date(2027, 10, 9)) == "2027-10-08"
    assert v24["target_date"] == "2028-10-09" and v24["verdict_session"] == nearest(date(2028, 10, 9)) and v24["final"] is True
    assert v12["status"] == "applied" and v12["through"] == v12["verdict_session"] and v12["verdict"] == "help", v12
    assert v24["status"] == "applied" and v24["verdict"] == "help"
    # the 12-month verdict uses the sessions through the verdict session and later data does not change it
    rep12 = rp.build(tj, reg, as_of=v12["verdict_session"])
    assert rep12["verdicts"]["12m"]["basis"] == v12["basis"] and rep12["verdicts"]["24m"]["status"] == "pending"
    assert rep12["pooled"]["n"] == v12["sessions_through"] and rep12["window"]["through"] == v12["verdict_session"]
    assert rep12["verdicts"]["12m"]["basis"]["pooled_t_nw5"] > 2 and rep12["pooled"]["t_nw5"] > 2
    # the day before the verdict session: still pending, no verdict
    rep_b = rp.build(tj, reg, as_of="2027-10-07")
    assert rep_b["verdicts"]["12m"]["status"] == "pending" and rep_b["verdicts"]["12m"]["verdict"] is None and "no verdict" in rep_b["status"]
    # hurt and no difference
    rep_h = rp.build(_synthetic_twins(-0.0004), reg)
    assert rep_h["verdicts"]["12m"]["verdict"] == "hurt" and rep_h["pooled"]["t_nw5"] < -2
    rep_0 = rp.build(_synthetic_twins(0.0), reg)
    assert rep_0["verdicts"]["12m"]["verdict"] == "no difference shown" and abs(rep_0["pooled"]["t_nw5"]) < 2
    # the power statement: absent before three months, then the smallest detectable annual difference
    rep_2m = rp.build(tj, reg, as_of="2026-12-31")
    assert rep_2m["window"]["months_elapsed"] == 2 and rep_2m["power"]["reported"] is False and "tracking_vol_pct" not in rep_2m["power"]
    rep_3m = rp.build(tj, reg, as_of="2027-01-11")
    assert rep_3m["window"]["months_elapsed"] == 3 and rep_3m["power"]["reported"] is True
    pw = rep_3m["power"]
    lr = pw["lr_sd_ann_pct"]
    assert abs(pw["min_annual_diff_for_t2_pct"]["12m"] - 2 * lr) < 1e-3 and abs(pw["min_annual_diff_for_t2_pct"]["24m"] - 2 * lr / np.sqrt(2)) < 1e-3
    assert pw["tracking_vol_pct"] == rep_3m["pooled"]["tracking_vol_pct"]
    # by_month: one row per month-end session, the first month included
    bm = rep_3m["by_month"]
    assert [r["month"] for r in bm] == ["2026-10", "2026-11", "2026-12", "2027-01"] and bm[0]["session"] == "2026-10-30" and bm[-1]["session"] == "2027-01-11"
    assert bm[0]["n"] == len([s for s in sess if "2026-10-09" < s <= "2026-10-30"])
    # a session missing on one side is skipped on both: the next common session's return spans the gap
    tj_gap = _synthetic_twins(0.0004, drop_e_session=10)
    rep_g = rp.build(tj_gap, reg)
    assert rep_g["pairs"]["1e"]["n"] == 538 and rep_g["pairs"]["2e"]["n"] == 539
    e_nav = {h["date"]: h["nav"] for h in tj_gap[tw.E_BLOCK]["twins"]["1e"]["history"]}
    c_nav = {h["date"]: h["nav"] for h in tj_gap["twins"]["1c"]["history"]}
    p = rp.pair_series(e_nav, c_nav)
    assert sess[10] not in [r["session"] for r in p["rows"]]
    r11 = next(r for r in p["rows"] if r["session"] == sess[11])
    assert abs(r11["e"] - (e_nav[sess[11]] / e_nav[sess[9]] - 1)) < 1e-12 and abs(r11["c"] - (c_nav[sess[11]] / c_nav[sess[9]] - 1)) < 1e-12
    # the script end to end on a file
    (TMP / "synthetic_twins.json").write_text(json.dumps(tj))
    cp = subprocess.run([PY, str(SCRIPTS / "twins_e_report.py"), "--twins", str(TMP / "synthetic_twins.json"),
                         "--out", str(TMP / "report_synth.json")], capture_output=True, text=True, cwd=str(TMP))
    assert cp.returncode == 0 and "verdict at 12 months: the entry rules help" in cp.stdout, cp.stdout + cp.stderr
    assert json.load(open(TMP / "report_synth.json"))["verdicts"]["12m"]["verdict"] == "help"


def test_11_live_registration_is_consistent():
    rules = json.load(open(TDIR / "continuous_rules.json"))
    blk = rules[tw.E_BLOCK]
    assert blk["twins"] == {"1e": "1_cap_pres", "2e": "2_balanced", "3e": "3_aggressive", "4e": "4_tactical"}
    assert blk["twin_of"] == {"1e": "1c", "2e": "2c", "3e": "3c", "4e": "4c"} and rules["twins"] == {"1c": "1_cap_pres", "2c": "2_balanced", "3c": "3_aggressive", "4c": "4_tactical"}
    assert blk["first_session"] == "2026-10-09" and is_trading_day(date.fromisoformat(blk["first_session"]))
    assert blk["entry_state_rules_version"] == 3
    cfg = DATA / blk["entry_state_config_file"]
    assert _digest(cfg) == blk["entry_state_config_sha256"] == "962fe81cf48b33370e1caf85e28f15a0413b9a8029f4ca031373fb8ebd87cdf0"
    assert json.load(open(cfg))["version"] == 3
    v4 = json.load(open(DATA / "entry_state_validation_registration_v4.json"))
    assert v4["rules"]["a_revised"]["sha256"] == blk["entry_state_config_sha256"]
    live = json.load(open(DATA / blk["entry_state_file"]))
    assert live["rules_version"] == 3 and set(live["names"]) and all(v.get("state") in (None, "READY", "READY-HALF", "WATCH", "AVOID") for v in live["names"].values())
    reg = json.load(open(TDIR / "twins_e_comparison.json"))
    assert reg["twins"]["pairs"] == blk["twin_of"] and reg["start"]["registered_first_session"] == blk["first_session"]
    assert reg["verdict"]["no_verdict_before_months"] == 12 and reg["power_statement"]["after_months"] == 3 and reg["cadence"] == "static"
    assert "STOP_EXIT" in rules["reason_codes"]
    for p in (TDIR / "continuous_rules.json", TDIR / "twins_e_comparison.json", SCRIPTS / "compute_twins.py", SCRIPTS / "twins_e_report.py"):
        blob = p.read_text().lower()
        import re
        assert not re.search(r"\bedge\b", blob) and not re.search(r"\balpha\b", blob), p.name
    # the e twins are not in the c twins' live state or served map before their first session
    st = json.load(open(TDIR / "twins_state.json"))
    tj = json.load(open(TDIR / "twins.json"))
    if tj["session_date"] < blk["first_session"]:
        assert not any(t.endswith("e") for t in st["twins"]) and not any(t.endswith("e") for t in tj["twins"])


# ─── guard ───────────────────────────────────────────────────────────────────────────────
def test_zz_repository_data_untouched():
    assert _listing(DATA) == _GUARD["data"] and _listing(TDIR) == _GUARD["tdir"]
    for n, d in _GUARD["files"].items():
        assert _digest(TDIR / n) == d, n
    for n, d in _GUARD["entry"].items():
        assert _digest(DATA / n) == d, n


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
