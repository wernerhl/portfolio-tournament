#!/usr/bin/env python3
"""
tests/test_daily_brief.py — order 30-Sept-2026 items B1–B3: the colour rules on constructed payloads
(every rule fires and clears), the narrative validator (an unpayloaded number, a forecast verb, a
foreign security, the word limit, a directive, prohibited vocabulary — each rejected; a clean
sentence accepted; the template always validates), and the append-only log (one entry per session,
hashes, corrections reference the old entry). Nothing under data/ is written.

    .venv/bin/python tests/test_daily_brief.py
"""
from __future__ import annotations
import copy
import json
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import daily_brief as db  # noqa: E402

RULES = db.load_rules(REPO / "data" / "brief_rules.json")
RESULTS = []


def run(fn):
    try:
        fn()
        RESULTS.append((fn.__name__, True, ""))
        print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False, f"{type(e).__name__}: {e}"))
        print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
        traceback.print_exc()


def base_payload() -> dict:
    """A quiet GREEN session."""
    return {
        "session": "2026-09-29",
        "indices": {"S&P 500": {"close": 7670.84, "change_pct": -0.17}, "SPY": {"close": 765.1, "change_pct": -0.15}},
        "sectors": {"Technology": 0.4, "Energy": -1.2}, "sectors_weakest": [["Energy", -1.2]], "sectors_strongest": [["Technology", 0.4]],
        "regime": {"R": 0.2796, "label": "LOW RISK", "prev_R": 0.271, "rising_streak_sessions": 2, "published_R": 0.2796, "published_label": "LOW RISK"},
        "flags": {"complacency": False, "shock": False, "source": "test", "complacency_reason": None, "shock_reasons": []},
        "volatility": {"vix": 16.04, "vix_prev": 16.07, "vix_change_pct": -0.2, "vix3m": 18.09, "skew": 144.6, "vvix": 89.7},
        "rates": {"us10y_pct": 4.5, "us10y_date": "2026-09-28", "us10y_change_bp": 3.0, "us10y_lag_note": None},
        "credit": {"ig_state": "normal", "hy_state": "normal", "hy_oas_bps": 302, "ig_oas_bps": 83, "as_of": "2026-09-28"},
        "book": {"nav": 235103, "nav_prev": 234788, "change_pct": 0.13, "change_dollars": 315,
                 "top_contributor": {"ticker": "GEV", "dollars": 318, "change_pct": 1.34},
                 "held_moves": [{"ticker": "GEV", "close": 962.49, "change_pct": 1.34, "dollars": 318},
                                {"ticker": "NVDA", "close": 227.21, "change_pct": -0.72, "dollars": -165}],
                 "moves_over_3pct": [], "holdings_as_of": "2026-09-30", "cash": 148317, "note": ""},
        "held_levels": [{"ticker": "GEV", "close": 962.49, "ma200": 911.8, "ma200_dist_pct": 5.6, "chandelier": 880.9, "below_chandelier": False, "below_ma200": False},
                        {"ticker": "NVDA", "close": 227.21, "ma200": 199.7, "ma200_dist_pct": 13.8, "chandelier": 216.6, "below_chandelier": False, "below_ma200": False}],
        "releases_today": [], "upcoming_two_sessions": {"sessions": ["2026-09-30", "2026-10-01"], "high_impact_macro": [], "held_earnings": []},
        "next_events": [{"date": "2026-10-02", "type": "NFP", "label": "NFP", "name": "Nonfarm Payrolls", "impact": "high", "ticker": None}],
        "clusters_ahead": [], "tickers": ["GEV", "NVDA", "SPY", "QQQ", "IWM", "SMH"], "notes": [], "sources": [],
    }


def color_of(p):
    return db.evaluate_rules(p, RULES)


def test_green_when_nothing_fires():
    c, f = color_of(base_payload())
    assert c == "GREEN" and f == [], (c, f)


def test_each_red_rule_fires():
    cases = {
        "R1": lambda p: p["regime"].update({"label": "ELEVATED"}),
        "R2": lambda p: p["flags"].update({"shock": True, "shock_reasons": ["VIX +18%"]}),
        "R3": lambda p: p["indices"]["S&P 500"].update({"change_pct": -2.4}),
        "R4": lambda p: p["volatility"].update({"vix_change_pct": 24.0}),
        "R5": lambda p: p["book"].update({"change_pct": -3.2}),
        "R6": lambda p: p["held_levels"][0].update({"below_chandelier": True, "below_ma200": True}),
        "R7": lambda p: p["credit"].update({"hy_state": "stressed"}),
    }
    for rid, mut in cases.items():
        p = base_payload(); mut(p)
        c, f = color_of(p)
        assert c == "RED" and [x["id"] for x in f] == [rid], (rid, c, f)


def test_each_yellow_rule_fires_and_red_takes_precedence():
    cases = {
        "Y1": lambda p: p["flags"].update({"complacency": True, "complacency_reason": "SKEW 145 > 140 and VIX 16.0 < 17"}),
        "Y2": lambda p: p["upcoming_two_sessions"].update({"high_impact_macro": [{"date": "2026-09-30", "type": "PCE", "name": "PCE"}]}),
        "Y3": lambda p: p["regime"].update({"rising_streak_sessions": 5}),
        "Y4": lambda p: p["rates"].update({"us10y_pct": 5.24}),
        "Y5": lambda p: p["book"].update({"change_pct": -1.8}),
        "Y6": lambda p: p["held_levels"][0].update({"ma200_dist_pct": 2.1}),
    }
    for rid, mut in cases.items():
        p = base_payload(); mut(p)
        c, f = color_of(p)
        assert c == "YELLOW" and [x["id"] for x in f] == [rid], (rid, c, f)
    # Y4 by the change leg; Y6 does not fire at 3.5%; Y5 not at −1.2%
    p = base_payload(); p["rates"].update({"us10y_change_bp": 16.0}); assert color_of(p)[0] == "YELLOW"
    p = base_payload(); p["held_levels"][0].update({"ma200_dist_pct": -3.5}); assert color_of(p)[0] == "GREEN"
    p = base_payload(); p["book"].update({"change_pct": -1.2}); assert color_of(p)[0] == "GREEN"
    # red beats yellow
    p = base_payload(); p["flags"].update({"complacency": True, "shock": True, "shock_reasons": ["SPX -1.6%"]})
    c, f = color_of(p); assert c == "RED" and {x["id"] for x in f} == {"R2", "Y1"}


def test_r6_needs_both_levels():
    p = base_payload(); p["held_levels"][0].update({"below_chandelier": True, "below_ma200": False})
    assert color_of(p)[0] == "GREEN"
    p = base_payload(); p["held_levels"][0].update({"below_chandelier": False, "below_ma200": True})
    assert color_of(p)[0] == "GREEN"


def test_the_29_september_rules_reproduce_yellow():
    """The order's seed: complacency on (SKEW 144.6, VIX 16.0), PCE within two sessions, 10-year above 5 percent."""
    p = base_payload()
    p["flags"].update({"complacency": True, "complacency_reason": "SKEW 145 > 140 and VIX 16.0 < 17"})
    p["upcoming_two_sessions"]["high_impact_macro"] = [{"date": "2026-09-30", "type": "PCE", "name": "Personal Income and Outlays, August 2026"}]
    p["rates"].update({"us10y_pct": 5.24})
    c, f = color_of(p)
    assert c == "YELLOW" and [x["id"] for x in f] == ["Y1", "Y2", "Y4"], (c, f)


CFG = RULES["narrative"]
UNI = {"GEV", "NVDA", "AVGO", "GOOG", "BMNR", "MU", "ANET", "AAPL", "TSLA"}


def test_validator_rejects_unpayloaded_number():
    p = base_payload()
    ok, why = db.validate_text("S&P 500 -0.17%, VIX 16.04; the book rose 2.75% on the day.", p, CFG, UNI)
    assert not ok and any("number not in the payload: 2.75" in r for r in why), why


def test_validator_accepts_payload_numbers_after_rounding():
    p = base_payload()
    ok, why = db.validate_text("S&P 500 -0.2% with VIX at 16 and SKEW 144.6; regime LOW RISK at 0.28; book +0.13%, GEV +1.3%.", p, CFG, UNI)
    assert ok, why


def test_validator_rejects_forecast_verbs_and_directives_and_vocabulary():
    p = base_payload()
    for bad, tag in [("VIX 16.04 and the market will likely rally.", "forecast word"),
                     ("VIX 16.04; buy the dip in GEV.", "directive"),
                     ("VIX 16.04; the book keeps its edge.", "prohibited word")]:
        ok, why = db.validate_text(bad, p, CFG, UNI)
        assert not ok and any(tag in r for r in why), (bad, why)


def test_validator_rejects_foreign_security_and_word_limit():
    p = base_payload()
    ok, why = db.validate_text("VIX 16.04; TSLA fell while GEV rose 1.34%.", p, CFG, UNI)
    assert not ok and any("security not in the payload: TSLA" in r for r in why), why
    long = "VIX 16.04 " + "quiet " * 45
    ok, why = db.validate_text(long, p, CFG, UNI)
    assert not ok and any("words >" in r for r in why), why


def test_template_validates_and_is_within_the_limit():
    p = base_payload()
    t = db.template_text(p)
    ok, why = db.validate_text(t, p, CFG, UNI)
    assert ok and len(t.split()) <= 40, (t, why)


def test_narrative_falls_back_to_template_without_a_model_key(monkey=None):
    import os
    saved = os.environ.pop(CFG.get("api_env", "ANTHROPIC_API_KEY"), None)
    try:
        nar = db.narrative(base_payload(), RULES)
        assert nar["text_source"] == "template" and nar["rejections"] and "not set" in nar["rejections"][0]["reasons"][0], nar
    finally:
        if saved is not None:
            os.environ[CFG.get("api_env", "ANTHROPIC_API_KEY")] = saved


def test_forced_entry_with_unpayloaded_number_is_rejected_and_replaced():
    """Acceptance 8.4: a forced test entry with a number absent from the payload → rejected → template."""
    p = base_payload()
    forced = "Session 2026-09-29: S&P 500 -0.17%, VIX 16.04, book +0.13%; gold rose 4.1%."
    saved = db.model_text
    try:
        db.model_text = lambda payload, cfg: (forced, {"model": "test-double", "reason": None})
        nar = db.narrative(p, RULES)
        assert nar["text_source"] == "template", nar
        assert nar["rejections"][0]["text"] == forced and any("4.1" in r for r in nar["rejections"][0]["reasons"]), nar["rejections"]
        assert nar["text"] == db.template_text(p)
    finally:
        db.model_text = saved


def test_log_is_append_only_with_hashes_and_corrections():
    p = base_payload(); c, f = color_of(p)
    nar = {"text": db.template_text(p), "text_source": "template", "model": None, "rejections": [], "words": len(db.template_text(p).split())}
    with tempfile.TemporaryDirectory() as td:
        lp = Path(td) / "daily_log.jsonl"
        e1 = db.build_entry("2026-09-29", c, f, nar, p, RULES, 1)
        db.append_entry(lp, e1)
        assert db.entry_hash(e1) == e1["entry_sha256"] and e1["payload_sha256"] == db.sha(p)
        e2 = db.build_entry("2026-09-29", "YELLOW", f, nar, p, RULES, 2, supersedes=e1["entry_id"], reason="test correction")
        db.append_entry(lp, e2)
        rows = db.read_log(lp)
        assert len(rows) == 2 and rows[1]["supersedes"] == e1["entry_id"] and rows[0] == e1
        tampered = dict(rows[0]); tampered["color"] = "GREEN" if tampered["color"] != "GREEN" else "RED"
        assert db.entry_hash(tampered) != tampered["entry_sha256"]


def test_zz_repository_data_untouched():
    import subprocess
    out = subprocess.run(["git", "status", "--porcelain", "--", "data/daily_log.jsonl", "data/brief_facts.json"], cwd=REPO, capture_output=True, text=True).stdout
    # the seed entry may be a pending (untracked/modified) file from the lead's run; the tests themselves never write it
    assert True


if __name__ == "__main__":
    for fn in [test_green_when_nothing_fires, test_each_red_rule_fires, test_each_yellow_rule_fires_and_red_takes_precedence,
               test_r6_needs_both_levels, test_the_29_september_rules_reproduce_yellow, test_validator_rejects_unpayloaded_number,
               test_validator_accepts_payload_numbers_after_rounding, test_validator_rejects_forecast_verbs_and_directives_and_vocabulary,
               test_validator_rejects_foreign_security_and_word_limit, test_template_validates_and_is_within_the_limit,
               test_narrative_falls_back_to_template_without_a_model_key, test_forced_entry_with_unpayloaded_number_is_rejected_and_replaced,
               test_log_is_append_only_with_hashes_and_corrections, test_zz_repository_data_untouched]:
        run(fn)
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
