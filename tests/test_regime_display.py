#!/usr/bin/env python3
"""
tests/test_regime_display.py — order 1-Oct-2026 item R1: the regime cards' units, narratives and scale
fields, against a fixture built from the 30-Sept served snapshot (tests/fixtures/regime_indicators_
2026-09-30_served.json, before) and the same inputs through the new display layer (…_r1.json, after);
plus the referee checks regime:unit and regime:narrative_level, each firing on a mutated copy and
clearing on restore. Nothing under data/ is read or written.

    .venv/bin/python tests/test_regime_display.py
"""
from __future__ import annotations
import copy
import json
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import regime_display as rd  # noqa: E402
import audit_nightly as an  # noqa: E402

FX = REPO / "tests" / "fixtures"
BEFORE = json.loads((FX / "regime_indicators_2026-09-30_served.json").read_text())
AFTER = json.loads((FX / "regime_indicators_2026-09-30_r1.json").read_text())
RESULTS = []


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def by_key(j):
    return {i["key"]: i for i in j["indicators"]}


def test_units_from_the_served_values():
    b = by_key(BEFORE)
    assert rd.value_str("hy_oas", b["hy_oas"]["value"]) == "308bp"          # stored 3.08 percent
    assert rd.value_str("baa_aaa", b["baa_aaa"]["value"]) == "43bp"         # stored in basis points
    assert rd.value_str("vix_term", b["vix_term"]["value"]) == "-2.0 pts"
    assert rd.value_str("yield_3m10y", b["yield_3m10y"]["value"]) == "+1.01pp"
    assert rd.value_str("breakeven_5y", b["breakeven_5y"]["value"]) == "2.36%"
    assert rd.value_str("consumer_expect", b["consumer_expect"]["value"]) == "4.2%"
    assert rd.value_str("mfg_new_orders", b["mfg_new_orders"]["value"]) == "$86,261M"
    # every indicator in the sweep has a display spec
    assert set(by_key(BEFORE)) <= set(rd.DISPLAY), set(by_key(BEFORE)) - set(rd.DISPLAY)


def test_level_phrases_follow_the_sign():
    assert "contango" in rd.level_phrase("vix_term", -2.03) and "backwardation" in rd.level_phrase("vix_term", 1.5)
    assert "inverted" in rd.level_phrase("yield_3m10y", -0.2) and "inverted" not in rd.level_phrase("yield_3m10y", 1.01)
    assert rd.level_phrase("spx_ret_60d", 2.26).startswith("S&P 500 up") and "down" in rd.level_phrase("spx_ret_60d", -4.0)
    assert "oil down" in rd.level_phrase("oil_60d_vel", -3.0)
    assert "easing" in rd.level_phrase("loan_tightening", -5.0) and "tightening" in rd.level_phrase("loan_tightening", 8.1)
    assert "looser" in rd.level_phrase("nfci", -0.55) and "tighter" in rd.level_phrase("nfci", 0.3)
    assert "1.9% below its high" in rd.level_phrase("spx_drawdown", -1.89)


def test_relative_phrases_name_the_window_and_flip_for_lower_channels():
    assert rd.relative_phrase("elevated", "higher", 70) == "above its past-year norm"
    assert rd.relative_phrase("elevated", "lower", 30) == "below its past-year norm"
    assert rd.relative_phrase("neutral", "higher", 50) == "near its past-year norm"
    assert "top decile of the trailing 252 sessions" in rd.relative_phrase("crisis", "higher", 95)
    assert "85th percentile of the trailing 252 sessions" in rd.relative_phrase("crisis", "higher", 85)


def test_after_narratives_carry_no_severity_word_and_match_the_signs():
    for i in AFTER["indicators"]:
        nar = i["narrative"].lower()
        assert not any(w in nar for w in rd.SEVERITY_WORDS), (i["key"], i["narrative"])
    a = by_key(AFTER)
    assert "contango" in a["vix_term"]["narrative"] and "up 2.3%" in a["spx_ret_60d"]["narrative"]
    assert a["hy_oas"]["value_str"] == "308bp" and a["hy_oas"]["pctile_10y"] is not None and a["hy_oas"]["z_window"] == "252 sessions"


def test_model_fields_identical_before_and_after():
    """Acceptance 2 on the fixtures: every numeric field and status is unchanged."""
    b, a = by_key(BEFORE), by_key(AFTER)
    for k in b:
        for f in ("value", "z", "phi", "status", "tier", "weight", "direction", "as_of", "label"):
            x, y = b[k][f], a[k][f]
            if isinstance(x, float) and isinstance(y, float):
                # the served file was computed on the CI runner (Python 3.11); the fixture's "after" on this
                # machine (3.12) — they agree to ~1e-13, while before/after on ONE machine are byte-identical
                # (the acceptance-2 diff in the report)
                assert abs(x - y) < 1e-9, (k, f, x, y)
            else:
                assert x == y, (k, f, x, y)
    for f in ("R_lead", "R_full", "divergence", "regime", "early_warning", "n_crisis", "n_safe", "n_elevated", "n_neutral"):
        assert BEFORE[f] == AFTER[f] or (isinstance(BEFORE[f], float) and abs(BEFORE[f] - AFTER[f]) < 1e-9), f


def test_referee_regime_unit_fires_and_clears():
    assert not [x for x in an.check_regime_display(AFTER) if x[1] == "regime:unit"]
    m = copy.deepcopy(AFTER)
    for i in m["indicators"]:
        if i["key"] == "hy_oas": i["value_str"] = "3bp"          # the F1 defect, reintroduced
        if i["key"] == "breakeven_5y": i["value_str"] = "2.36"   # unit dropped
    f = [x for x in an.check_regime_display(m) if x[1] == "regime:unit"]
    assert len(f) == 2 and all(x[0] == "HIGH" for x in f), f
    assert not [x for x in an.check_regime_display(AFTER) if x[1] == "regime:unit"]   # restore clears


def test_referee_narrative_level_fires_and_clears():
    assert not [x for x in an.check_regime_display(AFTER) if x[1] == "regime:narrative_level"]
    m = copy.deepcopy(AFTER)
    for i in m["indicators"]:
        if i["key"] == "vix_term": i["narrative"] = "Term backwardation"          # F2, contango value
        if i["key"] == "spx_ret_60d": i["narrative"] = "Momentum negative"        # F2, positive return
        if i["key"] == "hy_oas": i["narrative"] = "Credit stress acute"           # severity at the 47th 10y pctile
    f = [x for x in an.check_regime_display(m) if x[1] == "regime:narrative_level"]
    assert len(f) == 3, f
    # the served 30-Sept file (before) fires on every F2 instance
    fb = [x for x in an.check_regime_display(BEFORE) if x[1] == "regime:narrative_level"]
    assert any("vix_term" in x[2] for x in fb) and any("spx_ret_60d" in x[2] for x in fb) and any("hy_oas" in x[2] for x in fb)


if __name__ == "__main__":
    for fn in [test_units_from_the_served_values, test_level_phrases_follow_the_sign,
               test_relative_phrases_name_the_window_and_flip_for_lower_channels,
               test_after_narratives_carry_no_severity_word_and_match_the_signs, test_model_fields_identical_before_and_after,
               test_referee_regime_unit_fires_and_clears, test_referee_narrative_level_fires_and_clears]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
