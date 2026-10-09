#!/usr/bin/env python3
"""
tests/test_strat_tier.py — the STRATIFIED paper tier (execution order of 8 October 2026, J6): equal weights and
full investment; no action before the first session; the quarter-end rebalance picks the holdings file of that
month-end (a late file applies on the first session it exists); a holdings file is never rewritten; the C1 cost is
charged on every trade; the registration's sha256 is recorded; the backfill carry-forward matches the marking; the
action log keeps the paper tier apart; the quarter report runs before any session exists.

    .venv/bin/python tests/test_strat_tier.py
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "scripts" / "analyst"))
import strat_tier as st   # noqa: E402
import strat_holdings as sh   # noqa: E402
import strat_quarter_report as sq   # noqa: E402

RESULTS = []
SPEC = {**st.DEFAULT_SPEC, "first_session": "2026-10-09"}
COST = 0.0010
COST_LABEL = "3 bps half-spread + 7 bps impact = 10 bps one-way on NAV-weight turnover"


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def holdings_dir(files: dict) -> Path:
    td = Path(tempfile.mkdtemp())
    for me, names in files.items():
        (td / f"{me}.json").write_text(json.dumps({"tier": "6_strat", "month_end": me,
                                                   "names": [{"ticker": t, "rank": i + 1, "score": round(1 - i * 0.01, 3)} for i, t in enumerate(names)]}))
    return td


def row(date: str, tier=None, bench=None) -> dict:
    return {"date": date, "tiers": ({"6_strat": tier} if tier else {}), "benchmarks": bench or {}}


def test_equal_weights_and_full_investment():
    hdir = holdings_dir({"2026-09-30": ["AAA", "BBB", "CCC", "DDD"]})
    prices = {"AAA": 10.0, "BBB": 20.0, "CCC": 50.0, "DDD": 100.0}
    t = st.compute_row([], "2026-10-09", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    assert t is not None and t["holdings"] == ["AAA", "BBB", "CCC", "DDD"]
    nav_after = 100000.0 * (1 - COST)
    assert abs(t["nav"] - nav_after) < 0.005, t["nav"]
    assert all(abs(p["value"] - nav_after / 4) < 0.01 for p in t["positions"]), t["positions"]
    assert all(abs(p["weight"] - 25.0) < 0.05 for p in t["positions"])
    assert 0.0 <= t["cash"] < 0.01 and t["target_cash_pct"] == 0.0 and t["actual_cash_pct"] == 0.0
    assert abs(t["equity"] + t["cash"] - t["nav"]) < 0.005
    assert t["first_session"] == "2026-10-09" and t["rebalance"]["kind"] == "seed" and t["holdings_month_end"] == "2026-09-30"
    assert t["paper_tier"] is True and t["label"] == st.LABEL and t["weights"] == st.WEIGHTS
    assert t["rebalance"]["holdings_file"].endswith("2026-09-30.json")


def test_no_action_before_first_session():
    hdir = holdings_dir({"2026-09-30": ["AAA", "BBB"]})
    prices = {"AAA": 1.0, "BBB": 1.0}
    assert st.compute_row([], "2026-10-08", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir) is None
    assert st.names_for_session([], "2026-10-08", SPEC, holdings_dir=hdir) == []
    assert st.names_for_session([], "2026-10-09", SPEC, holdings_dir=hdir) == ["AAA", "BBB"]
    # a later configured first session moves the seed
    later = {**SPEC, "first_session": "2026-10-12"}
    assert st.compute_row([], "2026-10-09", prices, later, COST, COST_LABEL, 0.0, holdings_dir=hdir) is None
    assert st.compute_row([], "2026-10-12", prices, later, COST, COST_LABEL, 0.0, holdings_dir=hdir)["first_session"] == "2026-10-12"
    # no holdings file at all: nothing written, no crash
    assert st.compute_row([], "2026-10-09", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=holdings_dir({})) is None
    # the block absent from config: the tier is off
    assert st.load_spec({"tier_specs": {}}) is None and st.compute_row([], "2026-10-09", prices, None, COST, COST_LABEL, 0.0) is None


def test_quarter_end_rebalance_picks_the_file_of_that_month_end():
    hdir = holdings_dir({"2026-09-30": ["AAA", "BBB"], "2026-12-31": ["BBB", "CCC"]})
    prices = {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0}
    seed = st.compute_row([], "2026-10-09", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    hist = [row("2026-10-09", seed)]
    carry = st.compute_row(hist, "2026-12-30", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    assert "rebalance" not in carry and carry["holdings"] == ["AAA", "BBB"] and carry["holdings_month_end"] == "2026-09-30"
    hist.append(row("2026-12-30", carry))
    assert st.is_quarter_end_session("2026-12-31") and not st.is_quarter_end_session("2026-12-30") and not st.is_quarter_end_session("2026-11-30")
    assert st.names_for_session(hist, "2026-12-31", SPEC, holdings_dir=hdir) == ["AAA", "BBB", "CCC"]
    reb = st.compute_row(hist, "2026-12-31", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    r = reb["rebalance"]
    assert r["kind"] == "quarter-end rebalance" and r["month_end"] == "2026-12-31" and r["on_time"] is True and r["due_session"] == "2026-12-31"
    assert r["holdings_file"].endswith("2026-12-31.json") and reb["holdings"] == ["BBB", "CCC"] and reb["holdings_month_end"] == "2026-12-31"
    # the file for the month-end is missing on the quarter-end session: the tier holds; the file applies on the first session it exists
    hdir2 = holdings_dir({"2026-09-30": ["AAA", "BBB"]})
    hold = st.compute_row(hist, "2026-12-31", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir2)
    assert "rebalance" not in hold and hold["holdings_month_end"] == "2026-09-30"
    hist2 = hist + [row("2026-12-31", hold)]
    (hdir2 / "2026-12-31.json").write_text(json.dumps({"names": [{"ticker": "CCC", "rank": 1, "score": 1.0}]}))
    late = st.compute_row(hist2, "2027-01-04", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir2)
    assert late["rebalance"]["on_time"] is False and late["rebalance"]["due_session"] == "2026-12-31" and late["holdings"] == ["CCC"]
    # a file for a month that is not a quarter-end is ignored
    hdir3 = holdings_dir({"2026-09-30": ["AAA", "BBB"], "2026-11-30": ["CCC"]})
    assert "rebalance" not in st.compute_row(hist, "2026-12-01", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir3)
    # a re-run on a session already published uses the row before it, not the row itself
    hist3 = hist + [row("2026-12-31", reb)]
    again = st.compute_row(hist3, "2026-12-31", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    assert again["nav"] == reb["nav"] and again["rebalance"]["turnover_one_way"] == r["turnover_one_way"]


def test_holdings_file_is_never_rewritten():
    td = Path(tempfile.mkdtemp())
    payload = sh.build_payload("2026-09-30", [{"ticker": "AAA", "rank": 1, "score": 0.9}], 10, {"fitted": "2026-01"}, {},
                               {"path": "x", "sha256": "y"}, written_at="t")
    p = sh.write_once(payload, "2026-09-30", td)
    before = p.read_bytes()
    try:
        sh.write_once({**payload, "names": []}, "2026-09-30", td)
        raise AssertionError("a second write must be refused")
    except FileExistsError:
        pass
    assert p.read_bytes() == before
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "analyst" / "strat_holdings.py"), "--month-end", "2026-09-30", "--out-dir", str(td)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "immutable" in r.stdout, (r.returncode, r.stdout, r.stderr)
    assert p.read_bytes() == before
    assert sh.latest_quarter_end_month_end("2026-10-08") == "2026-09-30"
    assert sh.latest_quarter_end_month_end("2026-12-31") == "2026-12-31" and sh.latest_quarter_end_month_end("2027-01-04") == "2026-12-31"


def test_c1_cost_is_charged_on_every_trade():
    hdir = holdings_dir({"2026-09-30": ["AAA", "BBB"], "2026-12-31": ["BBB", "CCC"]})
    prices = {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0}
    seed = st.compute_row([], "2026-10-09", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    assert seed["rebalance"]["turnover_one_way"] == 1.0 and seed["rebalance"]["cost_pct"] == 0.1 and seed["rebalance"]["cost_model"] == COST_LABEL
    assert abs(seed["nav"] - 99900.0) < 0.005
    hist = [row("2026-10-09", seed)]
    reb = st.compute_row(hist, "2026-12-31", prices, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    # AAA (50%) sold, CCC (50%) bought: one-way turnover 0.5, cost 5 bps on the marked NAV
    assert reb["rebalance"]["turnover_one_way"] == 0.5 and reb["rebalance"]["cost_pct"] == 0.05
    assert abs(reb["nav"] - 99900.0 * (1 - 0.0005)) < 0.01, reb["nav"]
    # the day's move on the old names counts: AAA doubles on the rebalance session
    reb2 = st.compute_row(hist, "2026-12-31", {"AAA": 20.0, "BBB": 20.0, "CCC": 30.0}, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    assert abs(reb2["rebalance"]["nav_before_cost"] - 149850.0) < 0.01, reb2["rebalance"]
    # a non-rebalance session charges nothing: cash accrues at EFFR, positions ride
    carry = st.compute_row(hist, "2026-10-12", {"AAA": 11.0, "BBB": 20.0}, SPEC, COST, COST_LABEL, 0.0001, holdings_dir=hdir)
    assert "rebalance" not in carry and abs(carry["nav"] - (4995.0 * 11.0 + 2497.5 * 20.0 + seed["cash"] * 1.0001)) < 0.01


def test_registration_sha256_is_recorded():
    reg_path = REPO / "data" / "analyst" / "candidate_list_test_registration.json"
    reg = sh.registration_record()
    assert reg["path"] == "data/analyst/candidate_list_test_registration.json"
    assert reg["sha256"] == hashlib.sha256(reg_path.read_bytes()).hexdigest()
    payload = sh.build_payload("2026-09-30", [{"ticker": "AAA", "rank": 1, "score": 0.9}], 10,
                               {"fitted": "2026-01", "training_window": {"first_month_end": "2010-06-30", "last_month_end": "2024-12-31"}},
                               {}, reg, written_at="t")
    assert payload["registration"] == reg and payload["label"] == st.LABEL and payload["weights"] == st.WEIGHTS
    assert payload["tier"] == "6_strat" and payload["model"]["training_window"]["last_month_end"] == "2024-12-31"
    f = REPO / "data" / "tournament" / "strat_holdings" / "2026-09-30.json"
    if f.exists():   # the seeding file, written once by the script
        j = json.load(open(f))
        assert j["registration"]["sha256"] == reg["sha256"] and j["model"]["fitted"] == "2026-01"
        assert j["count_selected"] == len(j["names"]) == max(int(round(j["count_scored"] * 0.10)), 1)
        assert [n["rank"] for n in j["names"]] == list(range(1, len(j["names"]) + 1))
        assert all(j["names"][i]["score"] >= j["names"][i + 1]["score"] for i in range(len(j["names"]) - 1))


def test_backfill_carry_forward_matches_the_marking():
    hdir = holdings_dir({"2026-09-30": ["AAA", "BBB"]})
    seed = st.compute_row([], "2026-10-09", {"AAA": 10.0, "BBB": 20.0}, SPEC, COST, COST_LABEL, 0.0, holdings_dir=hdir)
    px = {"AAA": 12.0, "BBB": 19.0}
    marked = st.compute_row([row("2026-10-09", seed)], "2026-10-12", px, SPEC, COST, COST_LABEL, 0.0002, holdings_dir=hdir)
    carried = st.carry_forward_row(seed, "2026-10-12", lambda tk, d: px.get(tk), 0.0002)
    assert carried["nav"] == marked["nav"] and carried["holdings"] == marked["holdings"] and carried["holdings_month_end"] == "2026-09-30"
    # a name without a close keeps its shares for the next published row and is noted
    part = st.carry_forward_row(seed, "2026-10-12", lambda tk, d: px.get(tk) if tk == "AAA" else None, 0.0)
    assert part["names_without_close"] == ["BBB"] and set(part["shares"]) == {"AAA", "BBB"} and part["holdings"] == ["AAA"]


def test_action_log_keeps_the_paper_tier_apart():
    try:
        import compute_nav   # noqa: F401  (pulls in the provider client; skip when absent)
    except ImportError:
        print("  (compute_nav not importable here; skipped)"); return
    assert "6_strat" not in compute_nav.ACTION_LOG_TIERS and "2_balanced" in compute_nav.ACTION_LOG_TIERS
    td = Path(tempfile.mkdtemp())
    saved = compute_nav.DATA; compute_nav.DATA = td
    try:
        pos = lambda tk, v, w: {"ticker": tk, "shares": 1, "price": v, "value": v, "weight": w}   # noqa: E731
        prev = {"date": "2026-12-30", "tiers": {"2_balanced": {"positions": [pos("AAA", 50, 50.0)], "target_cash_pct": 50, "actual_cash_pct": 50},
                                                "6_strat": {"positions": [pos("AAA", 50, 50.0), pos("BBB", 50, 50.0)], "target_cash_pct": 0, "actual_cash_pct": 0}}}
        cur = {"date": "2026-12-31", "tiers": {"2_balanced": {"positions": [pos("CCC", 50, 50.0)], "target_cash_pct": 50, "actual_cash_pct": 50},
                                               "6_strat": {"positions": [pos("CCC", 100, 100.0)], "target_cash_pct": 0, "actual_cash_pct": 0}}}
        n = compute_nav.log_actions([prev], cur, "deadbeef")
        lines = [json.loads(l) for l in (td / "actions.jsonl").read_text().splitlines()]
        assert n == 1 and [l["tier"] for l in lines] == ["2_balanced"], lines
    finally:
        compute_nav.DATA = saved


def test_quarter_report_runs_before_any_session_and_at_quarter_ends():
    bench = lambda s, q: {"spy": {"nav": s}, "qqq": {"nav": q}}   # noqa: E731
    empty = {"history": [row("2026-10-08", None, bench(100.0, 100.0))]}
    rep = sq.build_report(empty, SPEC, computed_at="t")
    assert rep["status"] == "no session yet" and rep["first_session_planned"] == "2026-10-09" and rep["quarters"] == [] and rep["latest"] is None
    assert rep["cadence"] == "daily" and rep["session_date"] == "2026-10-08"
    seed = {"nav": 99900.0, "n_positions": 2, "holdings_month_end": "2026-09-30", "holdings_file": "x/2026-09-30.json"}
    hist = [row("2026-10-09", seed, bench(100.0, 100.0)), row("2026-12-31", {**seed, "nav": 109890.0}, bench(110.0, 105.0)),
            row("2027-01-04", {**seed, "nav": 99900.0}, bench(100.0, 100.0))]
    rep = sq.build_report({"history": hist}, SPEC, computed_at="t")
    assert rep["status"] == "live" and rep["first_session"] == "2026-10-09" and len(rep["quarters"]) == 1
    q = rep["quarters"][0]
    assert q["quarter_end_session"] == "2026-12-31" and q["session"] == "2026-12-31" and q["sessions"] == 2
    assert q["tier"]["return_pct"] == 10.0 and q["SPY"]["difference_pts"] == 0.0 and q["QQQ"]["difference_pts"] == 5.0
    assert q["RSP"]["return_pct"] is None and "not in the price store" in q["RSP"]["note"]
    assert rep["latest"]["session"] == "2027-01-04" and rep["latest"]["tier"]["return_pct"] == 0.0 and rep["latest"]["sessions"] == 3
    # the script itself, on a scratch tournament with no session: exit 0 and a file
    td = Path(tempfile.mkdtemp()); tp = td / "t.json"; tp.write_text(json.dumps(empty)); out = td / "r.json"
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "strat_quarter_report.py"), "--tournament", str(tp), "--out", str(out)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and json.loads(out.read_text())["status"] == "no session yet", (r.returncode, r.stdout, r.stderr)


if __name__ == "__main__":
    for fn in [test_equal_weights_and_full_investment, test_no_action_before_first_session,
               test_quarter_end_rebalance_picks_the_file_of_that_month_end, test_holdings_file_is_never_rewritten,
               test_c1_cost_is_charged_on_every_trade, test_registration_sha256_is_recorded,
               test_backfill_carry_forward_matches_the_marking, test_action_log_keeps_the_paper_tier_apart,
               test_quarter_report_runs_before_any_session_and_at_quarter_ends]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
