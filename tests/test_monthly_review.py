#!/usr/bin/env python3
"""
tests/test_monthly_review.py — order 30-Sept-2026 section 5 (acceptance 7): the monthly review.

On the fixtures under tests/fixtures/review/ (two tiers, ten spells each over the SAME four decision
dates, a twin, two out-of-month spells, three trades, a mistakes ledger with one failure and one
operator decision with its outcomes, an action log with export-confirmed and provisional entries):
the five worst are the five worst (computed independently here); the effective sample is the number
of distinct entry sessions, not spells; the bootstrap resamples DATES (every resample statistic is
one a date-level draw can produce, and a spell count larger than the date count does not widen the
effective sample); intervals reproduce with the seed; the never-edited rule (a second run refuses,
--force-new writes _v2); the index line; and no forbidden vocabulary. Nothing under data/ or
reports/ is written — every run goes to a temporary directory.

    .venv/bin/python tests/test_monthly_review.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import traceback
from datetime import date
from itertools import combinations_with_replacement
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import monthly_review as mr  # noqa: E402
from daily_brief import PROHIBITED  # noqa: E402  (the two words, never spelled in this file)

FIX = REPO / "tests" / "fixtures" / "review"
MONTH = "2026-09"
GENERATED = "2026-09-30T20:00:00-04:00"
RESULTS = []
_BUILD = None
_STATUS_BEFORE = subprocess.run(["git", "status", "--porcelain", "--", "reports/reviews", "data/tournament/reviews.jsonl"],
                                cwd=REPO, capture_output=True, text=True).stdout


def run(fn):
    try:
        fn()
        RESULTS.append((fn.__name__, True, ""))
        print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False, f"{type(e).__name__}: {e}"))
        print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
        traceback.print_exc()


def fixture_paths(tmp: Path) -> dict:
    return {"spells": str(FIX / "spells.jsonl"), "trades": str(FIX / "trades.jsonl"), "mistakes": str(FIX / "mistakes.jsonl"),
            "actions": str(FIX / "actions.jsonl"), "prices": str(FIX / "prices_daily.csv"), "etfs": str(FIX / "sector_etfs.csv"),
            "out_dir": str(tmp / "reviews"), "index": str(tmp / "reviews.jsonl")}


def argv_for(tmp: Path, extra=()) -> list:
    p = fixture_paths(tmp)
    argv = ["--month", MONTH, "--repo", str(REPO)]
    for k, v in p.items():
        argv += ["--" + k.replace("_", "-"), v]
    return argv + list(extra)


def built() -> dict:
    global _BUILD
    if _BUILD is None:
        _BUILD = mr.build(fixture_paths(Path(tempfile.mkdtemp())), MONTH, GENERATED)
    return _BUILD


def rendered() -> str:
    return mr.render(built(), prohibited=PROHIBITED)


def expected_excess_by_spell() -> dict:
    """Independent of the module: spells closed in the month take the closed event's excess_vs_spy;
    spells open at month end are marked from the fixture CSVs at the 2026-09-30 close."""
    events, _ = mr.load_jsonl(FIX / "spells.jsonl")
    prices = pd.read_csv(FIX / "prices_daily.csv", index_col=0)
    etfs = pd.read_csv(FIX / "sector_etfs.csv", index_col=0)
    by = {}
    for e in events:
        by.setdefault(e["spell_id"], {})[e["event"]] = e
    out = {}
    for sid, evs in by.items():
        op, cl = evs["opened"], evs.get("closed")
        if cl and "2026-09-01" <= cl["exit_session"] <= "2026-09-30":
            out[sid] = (op["tier"], op["ticker"], cl["excess_vs_spy"], "closed")
        elif op["entry_session"] <= "2026-09-30" and (cl is None or cl["exit_session"] > "2026-09-30"):
            tk = op["ticker"]
            if tk not in prices.columns:
                out[sid] = (op["tier"], tk, None, "open")
                continue
            r = prices.loc["2026-09-30", tk] / op["entry_price"] - 1.0
            s = etfs.loc["2026-09-30", "spy"] / etfs.loc[op["entry_session"], "spy"] - 1.0
            out[sid] = (op["tier"], tk, r - s, "open")
    return out


# ─── the sample ──────────────────────────────────────────────────────────────────────────
def test_month_sample_excludes_other_months_and_marks_open_spells():
    rows = {r["spell_id"]: r for r in built()["sample"]}
    exp = expected_excess_by_spell()
    assert set(rows) == set(exp) and len(rows) == 22, (sorted(rows), sorted(exp))
    assert "SP-B11" not in rows and "SP-B12" not in rows          # closed in August; opened in October
    for sid, (tier, tk, x, status) in exp.items():
        r = rows[sid]
        assert r["tier"] == tier and r["ticker"] == tk and r["status"] == status, sid
        if x is None:
            assert r["excess_spy"] is None and "not marked" in r["note"], sid
        else:
            assert abs(r["excess_spy"] - x) < 1e-9, (sid, r["excess_spy"], x)
    # the marks, by hand: HHH 95/100 vs SPY 767.6/760; JJJ (closed 2 Oct) 51.5/50 vs SPY 767.6/765
    assert abs(rows["SP-B08"]["excess_spy"] - (-0.05 - 0.01)) < 1e-9 and rows["SP-B08"]["exit_session"] == "2026-09-30"
    assert abs(rows["SP-B10"]["excess_spy"] - (0.03 - (767.6 / 765.0 - 1.0))) < 1e-9 and rows["SP-B10"]["exit_reason"] == "open at month end"
    assert rows["SP-B08"]["sessions_held"] == 11         # sessions in (2026-09-15, 2026-09-30]
    # the closed event's figure is used, not the followup's
    assert rows["SP-B01"]["excess_spy"] == -0.082 and rows["SP-B01"]["n_events"] == 3
    # scores fall back to the entry trade when the event carries none
    assert rows["SP-B08"]["scores"]["tier_rank"] == 7 and rows["SP-B08"]["scores"]["tier_composite"] == 56.8 and rows["SP-B08"]["regime_label"] == "LOW RISK"
    assert built()["ctx"] == {"first_session": "2026-09-01", "last_session": "2026-09-30", "n_sessions": 21, "mark_session": "2026-09-30", "mark_available": True}


def test_five_worst_are_the_five_worst():
    exp = expected_excess_by_spell()
    for tier in ("2_balanced", "3_aggressive", "2c"):
        want = [tk for x, tk in sorted((x, tk) for t, tk, x, _ in exp.values() if t == tier and x is not None)][:5]
        got = [r["ticker"] for r in built()["tiers"][tier]["worst"]]
        assert got == want, (tier, got, want)
        xs = [r["excess_spy"] for r in built()["tiers"][tier]["worst"]]
        assert xs == sorted(xs)
    assert [r["ticker"] for r in built()["tiers"]["2_balanced"]["worst"]] == ["FFF", "AAA", "HHH", "DDD", "III"]
    assert [r["ticker"] for r in built()["tiers"]["3_aggressive"]["worst"]] == ["OOO", "PPP", "QQQ", "UUU", "SSS"]
    assert built()["tiers"]["2_balanced"]["worst"][2]["status"] == "open"     # the marked open spell ranks among them
    assert built()["tier_order"] == ["1_cap_pres", "2_balanced", "3_aggressive", "4_tactical", "2c"]
    text = rendered()
    assert "| 1 | FFF | 2026-09-08 | 2026-09-29 | 15 | -11.70% | -12.10% | -5.70% | stop | 57.00 | 6 | 24 | 6.00 | 5.90 |" in text
    assert "| 3 | HHH | 2026-09-15 | 2026-09-30 | 11 | -5.00% | -6.00% | — | open at month end (marked) |" in text


def test_tier_month_figures():
    t = built()["tiers"]["2_balanced"]
    assert (t["n_spells"], t["n_closed"], t["n_open_marked"], t["n_not_evaluated"], t["hits"]) == (10, 8, 2, 0, 4)
    assert abs(t["hit_rate"] - 0.4) < 1e-12
    t3 = built()["tiers"]["3_aggressive"]
    assert (t3["n_spells"], t3["n_closed"], t3["n_open_marked"], t3["n_not_evaluated"], t3["hits"], t3["n_evaluated"]) == (10, 9, 0, 1, 5, 9)
    assert built()["tiers"]["1_cap_pres"]["n_spells"] == 0 and built()["tiers"]["4_tactical"]["n_spells"] == 0
    text = rendered()
    assert "No spells in the sample for this tier this month (0 spells, 0 decision sessions)." in text
    assert "hit rate vs SPY 4 of 10 (40.00%)" in text and "1 without a figure" in text


# ─── effective sample and the bootstrap ──────────────────────────────────────────────────
def test_effective_sample_is_distinct_entry_sessions_not_spells():
    t = built()["tiers"]["2_balanced"]
    assert t["n_spells"] == 10 and t["effective_sample"] == 4 and t["bootstrap"]["n_dates"] == 4 and t["bootstrap"]["n_spells"] == 10
    assert t["decision_sessions"] == ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"]
    assert built()["effective_samples"] == {"1_cap_pres": 0, "2_balanced": 4, "3_aggressive": 4, "4_tactical": 0, "2c": 2}
    # thirty spells on three dates: the spell count does not widen the effective sample or the draw
    g = {"2026-09-01": [0.01] * 10, "2026-09-02": [-0.01] * 10, "2026-09-03": [0.02] * 10}
    b = mr.date_block_bootstrap(g, keep_draws=True)
    assert b["n_dates"] == 3 and b["n_spells"] == 30 and b["draws"].shape == (2000, 3)
    text = rendered()
    assert "**Effective sample size: 4 decision session(s)** (2026-09-01, 2026-09-08, 2026-09-15, 2026-09-22) beside 10 spells." in text
    assert "**Effective sample size: 2 decision session(s)** (2026-09-01, 2026-09-08) beside 2 spells." in text


def test_bootstrap_resamples_dates_each_carrying_all_its_spells():
    groups = {r["entry_session"]: [] for r in built()["sample"] if r["tier"] == "2_balanced"}
    for r in built()["sample"]:
        if r["tier"] == "2_balanced":
            groups[r["entry_session"]].append(r["excess_spy"])
    dates = sorted(groups)
    b = mr.date_block_bootstrap(groups, keep_draws=True)
    assert b["draws"].shape == (2000, 4) and b["draws"].min() >= 0 and b["draws"].max() <= 3
    # every resample statistic is one that drawing four dates with replacement can produce (35 multisets)
    ok_hit, ok_mean = set(), set()
    for combo in combinations_with_replacement(range(4), 4):
        pooled = np.concatenate([np.asarray(groups[dates[i]]) for i in combo])
        ok_hit.add(round(float(np.mean(pooled > 0)), 9))
        ok_mean.add(round(float(pooled.mean()), 9))
    assert all(round(float(h), 9) in ok_hit for h in b["hits"])
    assert all(round(float(m), 9) in ok_mean for m in b["means"])
    # each fixture date has a hit rate in [1/3, 1/2], so a date-block draw cannot leave that range; a per-spell draw does
    assert b["hits"].min() >= 1 / 3 - 1e-12 and b["hits"].max() <= 0.5 + 1e-12
    assert b["hit_rate_ci"][0] >= 1 / 3 - 1e-12 and b["hit_rate_ci"][1] <= 0.5 + 1e-12
    rng = np.random.default_rng(1)
    vals = np.concatenate([groups[d] for d in dates])
    per_spell = [float(np.mean(rng.choice(vals, size=len(vals)) > 0)) for _ in range(2000)]
    assert min(per_spell) < 1 / 3 - 1e-12 or max(per_spell) > 0.5 + 1e-12
    # the actual resample is the pooled draw: check one row by hand
    row = b["draws"][7]
    pooled = np.concatenate([np.asarray(groups[dates[i]]) for i in row])
    assert abs(b["means"][7] - pooled.mean()) < 1e-12 and abs(b["hits"][7] - np.mean(pooled > 0)) < 1e-12


def test_bootstrap_intervals_reproduce_with_the_seed():
    g = {"2026-09-01": [-0.082, 0.031, -0.015], "2026-09-08": [-0.054, 0.012, -0.121], "2026-09-15": [0.044, -0.06], "2026-09-22": [-0.033, 0.0266]}
    a, b = mr.date_block_bootstrap(g, keep_draws=True), mr.date_block_bootstrap(g, keep_draws=True)
    assert a["hit_rate_ci"] == b["hit_rate_ci"] and a["mean_excess_ci"] == b["mean_excess_ci"] and np.array_equal(a["draws"], b["draws"])
    assert a["seed"] == 20260930 and a["n_resamples"] == 2000 and a["level"] == 0.90
    c = mr.date_block_bootstrap(g, seed=1, keep_draws=True)
    assert not np.array_equal(a["draws"], c["draws"])
    r1 = mr.build(fixture_paths(Path(tempfile.mkdtemp())), MONTH, GENERATED)
    r2 = mr.build(fixture_paths(Path(tempfile.mkdtemp())), MONTH, GENERATED)
    for t in r1["tiers"]:
        assert r1["tiers"][t]["bootstrap"] == r2["tiers"][t]["bootstrap"], t
    assert mr.render(r1, prohibited=PROHIBITED) == mr.render(r2, prohibited=PROHIBITED)


def test_interval_caption_when_fewer_than_five_dates():
    text = rendered()
    assert text.count("Caption: fewer than 5 decision dates — the interval is not informative.") == 3   # 2_balanced, 3_aggressive, 2c
    assert "Date-block bootstrap, 90% interval (2000 resamples of 4 decision dates, seed 20260930)" in text
    six = {f"2026-09-{d:02d}": [0.01, -0.02, 0.03] for d in (1, 2, 3, 4, 8, 9)}
    assert mr.date_block_bootstrap(six)["informative"] is True
    assert mr.date_block_bootstrap({"2026-09-01": [0.01] * 40})["informative"] is False
    empty = mr.date_block_bootstrap({})
    assert empty["hit_rate_ci"] is None and empty["n_dates"] == 0


# ─── the operator, the failures, the lessons ─────────────────────────────────────────────
def test_operator_trades_with_outcomes_and_provisional_entries():
    op = built()["operator"]
    assert op["n_decisions"] == 1 and op["n_export"] == 2 and len(op["provisional"]) == 1
    d = op["decisions"][0]
    assert d["ticker"] == "XYZ" and d["session"] == "2026-09-10" and d["export"] is not None and d["export"]["price"] == 212.5
    assert d["outcomes"][20]["difference"] == -0.031 and d["outcomes"][60]["difference"] == 0.045
    assert [a["ticker"] for a in op["unmatched_export"]] == ["ZZZ"]
    assert all(str(a["session_date"])[:7] == MONTH for a in op["export_trades"])      # the August export entry is out
    assert mr.nth_session_after("2026-09-24", 20) == "2026-10-22" and mr.nth_session_after("2026-09-24", 60) == "2026-12-18"
    text = rendered()
    assert "| 2026-09-10 | XYZ | sell | 40 | 212.50 | LOW RISK | position above 20 percent of the book; trimmed to the sizing rule | confirmed | +0.00% / +3.10% / -3.10% | +0.00% / -4.50% / +4.50% |" in text
    assert "not yet in the ledger (session +20 = 2026-10-22)" in text and "not yet in the ledger (session +60 = 2026-12-18)" in text
    assert "- 2026-09-29 YYY sell qty 50 price — (unknown until the export) — pending export confirmation, not evaluated" in text
    # an action log with only the provisional entry: the review says there are no export-confirmed trades
    tmp = Path(tempfile.mkdtemp())
    rows, _ = mr.load_jsonl(FIX / "actions.jsonl")
    with open(tmp / "actions.jsonl", "w") as f:
        for a in rows:
            if a.get("source") == mr.SOURCE_PROVISIONAL:
                f.write(json.dumps(a) + "\n")
    p = fixture_paths(tmp)
    p["actions"] = str(tmp / "actions.jsonl")
    p["mistakes"] = str(tmp / "no_such_ledger.jsonl")
    t2 = mr.render(mr.build(p, MONTH, GENERATED), prohibited=PROHIBITED)
    assert "No export-confirmed operator trades in the month (and no operator_decision entries)." in t2
    assert "pending export confirmation, not evaluated" in t2 and "YYY" in t2
    assert "No new system failure recorded in the month (the mistakes ledger is absent)." in t2
    assert "| " + str(tmp / "no_such_ledger.jsonl") + " | 0 | absent |" in t2


def test_new_failures_with_fix_and_referee_check():
    fl = built()["failures"]
    assert fl["n_failures"] == 1 and fl["failures"][0]["entry_id"] == "F-2026-09-12-01"
    assert len(fl["recurrences"]) == 1 and fl["recurrences"][0]["earlier"]["entry_id"] == "F-2026-08-14-01"
    text = rendered()
    sec = text.split("## 4. New system failures")[1].split("## 5.")[0]
    assert "found within 2026-09: 1 entries" in sec
    assert sec.count("\n| F-") == 1 and "| F-2026-09-12-01 | 2026-09-12 | system |" in sec
    assert "the gate now reads the vintage stamp from the chain file, not the served json" in sec
    assert "lens_vintage_age_sessions <= 1 AND chain_file_stamp == lens.vintage" in sec
    assert "Recurrences: F-2026-09-12-01 repeats F-2026-08-14-01 (found 2026-08-14)." in sec


def test_candidate_lessons_are_capped_hypotheses_never_rules():
    res = built()
    assert 1 <= len(res["lessons"]) <= 3
    saved = mr.MAX_LESSONS
    try:
        mr.MAX_LESSONS = 50
        all_c = mr.candidate_lessons(res["tiers"], res["sample"], res["operator"], res["failures"])
    finally:
        mr.MAX_LESSONS = saved
    kinds = sorted((c["kind"], c["tier"]) for c in all_c)
    assert kinds == [("exit_reason", "2_balanced"), ("exit_reason", "3_aggressive"), ("rank_split", "2_balanced"), ("rank_split", "3_aggressive"), ("recurrence", "system")], kinds
    assert len(res["lessons"]) == 3 and all(c["kind"] != "recurrence" for c in res["lessons"])   # smallest sample dropped by the cap
    assert all(c["n_dates"] == 4 for c in res["lessons"])
    text = rendered()
    sec = text.split("## 5. What this review does not do")[1]
    assert sec.count("Hypothesis, not a rule") == 3
    assert "No rule is changed here." in sec and "never applied" in sec and "listed for registration" in sec
    assert "Sample: 10 spells over 4 decision dates" in sec and "fewer than 5 decision dates, not informative" in sec
    assert "At most 3 are listed" in sec


# ─── the never-edited rule, the index, the CLI ───────────────────────────────────────────
def test_never_edited_second_run_refuses_and_force_new_writes_v2():
    tmp = Path(tempfile.mkdtemp())
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        assert mr.main(argv_for(tmp)) == 0
        f1 = tmp / "reviews" / f"review_{MONTH}.md"
        assert f1.exists()
        b1 = f1.read_bytes()
        assert mr.main(argv_for(tmp)) == 2                                    # refuses
        assert sorted(p.name for p in (tmp / "reviews").iterdir()) == [f"review_{MONTH}.md"]
        assert f1.read_bytes() == b1
        assert len(open(tmp / "reviews.jsonl").read().splitlines()) == 1     # nothing appended by the refusal
        assert "already exists and is never edited" in err.getvalue()
        assert mr.main(argv_for(tmp, ["--force-new", "--reason", "fixture: a second review to exercise the versioning"])) == 0
        f2 = tmp / "reviews" / f"review_{MONTH}_v2.md"
        assert f2.exists() and f1.read_bytes() == b1
        t2 = f2.read_text(encoding="utf-8")
        assert "**Second review for this month (--force-new).**" in t2 and f"review_{MONTH}.md" in t2
        assert "fixture: a second review to exercise the versioning" in t2 and hashlib.sha256(b1).hexdigest()[:12] in t2
        idx = [json.loads(l) for l in open(tmp / "reviews.jsonl")]
        assert len(idx) == 2 and idx[0]["version"] == 1 and idx[1]["version"] == 2
        assert idx[1]["earlier_reviews"] == [idx[0]["file"]] and idx[1]["reason"].startswith("fixture:")
        assert mr.main(argv_for(tmp, ["--force-new", "--reason", "third"])) == 0
        assert (tmp / "reviews" / f"review_{MONTH}_v3.md").exists()
        assert sorted(p.name for p in (tmp / "reviews").iterdir()) == [f"review_{MONTH}.md", f"review_{MONTH}_v2.md", f"review_{MONTH}_v3.md"]


def test_index_line_schema_and_hash():
    tmp = Path(tempfile.mkdtemp())
    with contextlib.redirect_stdout(io.StringIO()):
        assert mr.main(argv_for(tmp)) == 0
    line = json.loads(open(tmp / "reviews.jsonl").readline())
    assert {"month", "file", "generated_at", "sha256", "effective_samples", "n_spells"} <= set(line)
    assert line["month"] == MONTH and line["n_spells"] == 22 and line["effective_samples"]["2_balanced"] == 4 and line["effective_samples"]["2c"] == 2
    body = Path(line["file"]).read_bytes()
    assert line["sha256"] == hashlib.sha256(body).hexdigest()
    text = body.decode("utf-8")
    assert text.startswith(f"# Monthly review — {MONTH}\n") and "This review is generated from the ledgers, stored, and never edited." in text
    assert "A lesson becomes a rule only through a registration and a prospective test" in text
    assert "## 1. Inputs" in text and "## 2. Spells by tier" in text and "## 3. The operator's trades" in text
    assert "## 4. New system failures" in text and "## 5. What this review does not do" in text
    assert text.index("## 1.") < text.index("## 2.") < text.index("## 3.") < text.index("## 4.") < text.index("## 5.")


def test_dry_run_writes_nothing_and_cli_runs():
    tmp = Path(tempfile.mkdtemp())
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        assert mr.main(argv_for(tmp, ["--dry-run"])) == 0
    assert "# Monthly review — 2026-09" in out.getvalue()
    assert not (tmp / "reviews").exists() and not (tmp / "reviews.jsonl").exists()
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "monthly_review.py")] + argv_for(tmp), capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "wrote " in r.stdout and "index line appended" in r.stdout, r.stderr
    r2 = subprocess.run([sys.executable, str(REPO / "scripts" / "monthly_review.py")] + argv_for(tmp), capture_output=True, text=True, cwd=REPO)
    assert r2.returncode == 2 and "never edited" in r2.stderr
    r3 = subprocess.run([sys.executable, str(REPO / "scripts" / "monthly_review.py"), "--month", "2026-9"], capture_output=True, text=True, cwd=REPO)
    assert r3.returncode == 2 and "YYYY-MM" in r3.stderr


def test_default_month_is_the_previous_calendar_month():
    assert mr.previous_month(date(2026, 9, 30)) == "2026-08"
    assert mr.previous_month(date(2026, 1, 15)) == "2025-12"
    assert mr.month_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert mr.month_sessions("2026-09")[0] == "2026-09-01" and len(mr.month_sessions("2026-09")) == 21 and "2026-09-07" not in mr.month_sessions("2026-09")


# ─── vocabulary ──────────────────────────────────────────────────────────────────────────
def test_output_contains_no_forbidden_vocabulary():
    assert len(PROHIBITED) == 2
    text = rendered()
    assert mr.word_hits(text, PROHIBITED) == {}, mr.word_hits(text, PROHIBITED)
    proj = mr.projection_words(REPO / "data" / "brief_rules.json")
    assert len(proj) >= 10
    assert mr.word_hits(text, proj) == {}, mr.word_hits(text, proj)
    for src in (REPO / "scripts" / "monthly_review.py", Path(__file__), FIX / "make_fixtures.py"):
        assert mr.word_hits(src.read_text(encoding="utf-8"), PROHIBITED) == {}, src
    # a quoted ledger word that breaks the rule is withheld, counted, and the guard in main() never trips
    tmp = Path(tempfile.mkdtemp())
    rows, _ = mr.load_jsonl(FIX / "mistakes.jsonl")
    for m in rows:
        if m["kind"] == "operator_decision":
            m["stated_reason"] = "the " + PROHIBITED[0] + " was gone, " + PROHIBITED[1].upper() + " too"
    with open(tmp / "mistakes.jsonl", "w") as f:
        for m in rows:
            f.write(json.dumps(m) + "\n")
    p = fixture_paths(tmp)
    p["mistakes"] = str(tmp / "mistakes.jsonl")
    t2 = mr.render(mr.build(p, MONTH, GENERATED), prohibited=PROHIBITED)
    assert mr.word_hits(t2, PROHIBITED) == {} and "the [word withheld] was gone, [word withheld] too" in t2
    assert "Vocabulary rule: 2 word(s) withheld from quoted ledger text" in t2
    assert t2.split("\n")[4].startswith("Vocabulary rule:") and t2.split("\n")[6].startswith("This review is generated")


def test_zz_repository_untouched():
    after = subprocess.run(["git", "status", "--porcelain", "--", "reports/reviews", "data/tournament/reviews.jsonl"],
                           cwd=REPO, capture_output=True, text=True).stdout
    assert after == _STATUS_BEFORE, (after, _STATUS_BEFORE)


if __name__ == "__main__":
    for fn in [test_month_sample_excludes_other_months_and_marks_open_spells, test_five_worst_are_the_five_worst, test_tier_month_figures,
               test_effective_sample_is_distinct_entry_sessions_not_spells, test_bootstrap_resamples_dates_each_carrying_all_its_spells,
               test_bootstrap_intervals_reproduce_with_the_seed, test_interval_caption_when_fewer_than_five_dates,
               test_operator_trades_with_outcomes_and_provisional_entries, test_new_failures_with_fix_and_referee_check,
               test_candidate_lessons_are_capped_hypotheses_never_rules, test_never_edited_second_run_refuses_and_force_new_writes_v2,
               test_index_line_schema_and_hash, test_dry_run_writes_nothing_and_cli_runs, test_default_month_is_the_previous_calendar_month,
               test_output_contains_no_forbidden_vocabulary, test_zz_repository_untouched]:
        run(fn)
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
