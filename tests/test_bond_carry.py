#!/usr/bin/env python3
"""
tests/test_bond_carry.py — order 1-Oct-2026 item R3: the curve-implied carry basis (interpolation, the
IG bucket, HY, TIP's real yield, the null reasons, pickup and breakeven rise) on a synthetic curve with
the 29-Sept CMT values, and the referee check bond:carry_basis firing on mutated copies of the served
fixtures and clearing on restore. Nothing under data/ is written.

    .venv/bin/python tests/test_bond_carry.py
"""
from __future__ import annotations
import copy
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "scripts" / "bonds"))
import bonds_common as bc  # noqa: E402
import audit_nightly as an  # noqa: E402

FX = REPO / "tests" / "fixtures" / "bonds"
STATES = json.loads((FX / "states_r3.json").read_text())
SM = json.loads((FX / "sleeve_metrics_r3.json").read_text())
FRED = pd.read_csv(FX / "fred_cmt_tail.csv", index_col=0, parse_dates=True)
CFG = bc.load_carry_config()
RESULTS = []

# the 29-Sept-2026 close, from FRED (DGS*, DFII*, ICE BofA OAS in percent)
D = pd.Timestamp("2026-09-29")
CURVE = pd.DataFrame({"us03m": [4.25], "us01y": [4.58], "us02y": [4.89], "us05y": [5.06], "us07y": [5.16], "us10y": [5.26],
                      "us20y": [5.64], "us30y": [5.59], "tips_real_5y": [2.72], "tips_real_7y": [2.80], "tips_real_10y": [2.91],
                      "tips_real_20y": [3.15], "tips_real_30y": [3.29], "hy_oas": [3.08], "ig_oas_1_3": [0.54], "ig_oas_3_5": [0.73],
                      "ig_oas_5_7": [0.86], "ig_oas_7_10": [1.02], "ig_oas_10_15": [1.01], "ig_oas_15p": [1.02]}, index=[D])


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def test_treasury_interpolation_matches_the_expected_values():
    ief = bc.carry_for("IEF", CURVE, D, bc.EFF_DURATION["IEF"], CFG)
    # 8.42y between the 7y (5.16) and 10y (5.26) points: 5.16 + 1.42/3 * 0.10 = 5.2073
    assert abs(ief["curve_implied_yield_pct"] - 5.207) < 0.001, ief
    assert abs(ief["pickup_bp"] - 95.7) < 0.1 and abs(ief["breakeven_rise_bp"] - 13.1) < 0.1, ief
    tlt = bc.carry_for("TLT", CURVE, D, bc.EFF_DURATION["TLT"], CFG)
    # 26.03y between 20y (5.64) and 30y (5.59): 5.64 - 6.03/10 * 0.05 = 5.6099
    assert abs(tlt["curve_implied_yield_pct"] - 5.610) < 0.001 and abs(tlt["breakeven_rise_bp"] - 8.2) < 0.1, tlt
    assert ief["inputs"]["us07y"]["series"] == "DGS7" and ief["inputs"]["us03m"]["series"] == "DGS3MO"


def test_credit_adds_the_bucket_or_hy_spread():
    vcsh = bc.carry_for("VCSH", CURVE, D, bc.EFF_DURATION["VCSH"], CFG)     # 3.1y: CMT(3.1) + the 3-5y bucket OAS
    cmt = 4.89 + (5.06 - 4.89) * (3.1 - 2) / 3
    assert abs(vcsh["curve_implied_yield_pct"] - (cmt + 0.73)) < 0.001 and vcsh["inputs"]["ig_oas_3_5"]["bucket"] == "3-5 years", vcsh
    lqd = bc.carry_for("LQD", CURVE, D, bc.EFF_DURATION["LQD"], CFG)       # 12.62y: the 10-15y bucket
    assert "ig_oas_10_15" in lqd["inputs"], lqd
    hyg = bc.carry_for("HYG", CURVE, D, bc.EFF_DURATION["HYG"], CFG)
    assert abs(hyg["curve_implied_yield_pct"] - (4.89 + (5.06 - 4.89) * (4.27 - 2) / 3 + 3.08)) < 0.001, hyg


def test_tip_is_real_and_excluded_from_nominal_comparison():
    tip = bc.carry_for("TIP", CURVE, D, bc.EFF_DURATION["TIP"], CFG)
    assert tip["curve_implied_yield_pct"] is None and tip["pickup_bp"] is None and abs(tip["real_yield_pct"] - 2.80) < 1e-9, tip
    assert abs(tip["nominal_equivalent_pct"] - 5.16) < 1e-9 and abs(tip["breakeven_at_maturity_pct"] - 2.36) < 1e-9, tip


def test_no_substitution_for_unmatched_sleeves_or_missing_inputs():
    for tk in ("EMB", "MBB", "MUB", "BKLN", "FLOT", "AGG", "BND"):
        r = bc.carry_for(tk, CURVE, D, bc.EFF_DURATION.get(tk), CFG)
        assert r["curve_implied_yield_pct"] is None and r["curve_implied_reason"], (tk, r)
    assert "no rate is assumed" in bc.carry_for("MUB", CURVE, D, 6.3, CFG)["curve_implied_reason"]
    r = bc.carry_for("IEF", CURVE.drop(columns=["us07y"]), D, 7.3, CFG)
    assert r["curve_implied_yield_pct"] is None and "missing" in r["curve_implied_reason"], r


def test_served_read_is_on_the_curve_basis():
    d = STATES["allocation_questions"]["duration"]
    assert "highest_yield_per_duration" not in d and "extension_favoured" not in d
    assert d["basis"].startswith("curve-implied") and "Bills yield" in d["read"] and "typical daily move" in d["read"], d["read"]
    assert all("yield_per_duration" not in r for r in STATES["book_integration"]["menu"]["sleeves"])
    assert SM["deprecated_fields"]["yield_per_duration"]["deprecated"] is True


def test_referee_carry_basis_fires_and_clears():
    assert an.check_bond_carry(STATES, SM, FRED) == []
    m = copy.deepcopy(STATES); d = m["allocation_questions"]["duration"]
    d["extension_favoured"] = False; d["highest_yield_per_duration"] = "SHV"              # the 16-Sept read
    f = an.check_bond_carry(m, SM, FRED)
    assert any(x[0] == "CRITICAL" for x in f), f
    m = copy.deepcopy(STATES); ief = m["allocation_questions"]["duration"]["intermediate"]
    dy = [r for r in SM["sleeves"] if r["ticker"] == "IEF"][0]["distribution_yield_pct"]
    ief["curve_implied_yield_pct"] = dy                                                  # carry from the distribution yield
    assert any(x[0] == "CRITICAL" and "equals the distribution yield" in x[2] for x in an.check_bond_carry(m, SM, FRED))
    m = copy.deepcopy(STATES); m["allocation_questions"]["duration"]["intermediate"]["pickup_bp"] = 24.0   # F4's served figure
    assert any(x[0] == "HIGH" and "outside" in x[2] for x in an.check_bond_carry(m, SM, FRED))
    m = copy.deepcopy(STATES); m["book_integration"]["menu"]["sleeves"][0]["yield_per_duration"] = 0.1066
    assert any(x[0] == "CRITICAL" and "yield_per_duration" in x[2] for x in an.check_bond_carry(m, SM, FRED))
    assert an.check_bond_carry(STATES, SM, FRED) == []                                   # restore clears


if __name__ == "__main__":
    for fn in [test_treasury_interpolation_matches_the_expected_values, test_credit_adds_the_bucket_or_hy_spread,
               test_tip_is_real_and_excluded_from_nominal_comparison, test_no_substitution_for_unmatched_sleeves_or_missing_inputs,
               test_served_read_is_on_the_curve_basis, test_referee_carry_basis_fires_and_clears]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
