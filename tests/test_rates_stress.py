#!/usr/bin/env python3
"""
tests/test_rates_stress.py — order 1-Oct-2026 item R5: the rates-stress block (DIAGNOSTIC) as served on
1 Oct (MOVE 110.45 on 30 Sept, 70.25 sixty sessions earlier; DFII10 2.91% +67bp; DGS10 5.26% +78bp) and
the gate check bond:rates_stress_gate firing when the label changes or when any consumer that sizes,
labels or colours reads the block (mutated copies of the real sources), and clearing on restore.

    .venv/bin/python tests/test_rates_stress.py
"""
from __future__ import annotations
import copy
import json
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import audit_nightly as an  # noqa: E402

STATES = json.loads((REPO / "tests" / "fixtures" / "bonds" / "states_r5.json").read_text())
SOURCES = an.rates_stress_sources(str(REPO))
RESULTS = []


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def test_block_matches_the_30_sept_readings():
    rs = STATES["rates_stress"]
    assert rs["label"] == "DIAGNOSTIC" and "not read by R" in rs["gate"]
    assert rs["move"]["level"] == 110.45 and rs["move"]["level_60_sessions_earlier"] == 70.25 and rs["move"]["pctile_1y"] >= 98.5
    assert rs["real_10y"]["level_pct"] == 2.91 and rs["real_10y"]["change_60_bp"] == 67.0
    assert rs["nominal_10y"]["level_pct"] == 5.26 and rs["nominal_10y"]["change_60_bp"] == 78.0
    assert abs(rs["real_share_of_nominal_change"] - 67 / 78) < 0.001


def test_every_consumer_source_is_found():
    assert all(v for v in SOURCES.values()), {k: bool(v) for k, v in SOURCES.items()}
    assert "function headlineVerdict" in SOURCES["app.js#headlineVerdict"]


def test_gate_clears_on_the_real_sources():
    assert an.check_rates_stress_gate(STATES, SOURCES) == []


def test_gate_fires_on_a_label_change():
    m = copy.deepcopy(STATES); m["rates_stress"]["label"] = "ACTIVE"
    f = an.check_rates_stress_gate(m, SOURCES)
    assert len(f) == 1 and f[0][0] == "CRITICAL", f


def test_gate_fires_when_any_consumer_reads_the_block():
    injections = {
        "app.js#headlineVerdict": ("consider(reg.regime);", "consider(reg.regime); if (S.bondsStates.rates_stress.move.pctile_1y > 95) consider(\"CAUTIOUS\");"),
        "scripts/daily_brief.py": ("def evaluate_rules(", "RS = 'rates_stress'\ndef evaluate_rules("),
        "scripts/compute_nav.py": ("def ", "MOVE_SRC = '^MOVE'\ndef ", ),
        "scripts/compute_regime_v2.py": ("INDICATORS = [", "INDICATORS = [\n    (\"move\", \"B\", \"higher\", \"vol_indicators\", \"move\", \"MOVE\", \"{v:.0f}\", []),"),
    }
    for name, (old, new) in injections.items():
        m = dict(SOURCES); assert old in m[name], (name, old)
        m[name] = m[name].replace(old, new, 1)
        f = an.check_rates_stress_gate(STATES, m)
        assert any(x[0] == "CRITICAL" and name in x[2] for x in f), (name, f)
    assert an.check_rates_stress_gate(STATES, SOURCES) == []          # restore clears


if __name__ == "__main__":
    for fn in [test_block_matches_the_30_sept_readings, test_every_consumer_source_is_found, test_gate_clears_on_the_real_sources,
               test_gate_fires_on_a_label_change, test_gate_fires_when_any_consumer_reads_the_block]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
