"""Daily pipeline wrapper. Called by GitHub Actions.

Order (v3):
  1. refresh_data.py        — pull latest prices + FRED into data/source/
  2. compute_regime_v2.py   — read source parquets, compute R_lead/R_full + complacency
  3. compute_nav.py         — inception-anchored benchmarks + tier NAVs
  4. build_ticker_data.py   — per-ticker drill-down JSON
  5. build_indicator_series — per-indicator history JSON
  6. compute_signals.py     — per-ticker signals (position vs entry mode)
  7. compute_intraday.py    — best-effort intraday snapshot
  8. validate_outputs()     — fail loud on frozen benchmark / missing TLT nav
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"

scripts = [
    "refresh_data.py",
    "compute_regime_v2.py",
    "compute_nav.py",
    "build_ticker_data.py",
    "build_indicator_series.py",
    "compute_signals.py",
    "compute_intraday.py",         # best-effort; OK to fail (yfinance flake)
    "compute_vol_regime.py",       # VIX term-structure regime + attribution
    "compute_conditional_scores.py", # regime-conditional sleeve scores (JS-shrunk)
]

for script in scripts:
    print(f"\n{'='*60}\nRunning {script}\n{'='*60}")
    rc = subprocess.call([sys.executable, str(HERE / script)])
    if rc != 0:
        print(f"WARNING: {script} exited with code {rc}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────
# Post-run validation — fail the workflow loudly on the bugs we just fixed.
# These assertions would have caught the silent benchmark freeze and the
# missing TLT NAV the moment they appeared.
# ─────────────────────────────────────────────────────────────────────
def validate_outputs() -> None:
    errors: list[str] = []
    tjson = DATA / "tournament.json"
    if not tjson.exists():
        errors.append("data/tournament.json missing")
    else:
        t = json.load(open(tjson))
        history = t.get("history", [])
        if len(history) > 1:
            last = history[-1]
            bms  = last.get("benchmarks", {}) or {}

            # A1: benchmarks must not be frozen at exactly 100000 after day 1
            for b in ["spy", "qqq", "sso"]:
                nav = (bms.get(b) or {}).get("nav")
                if nav == 100000.0:
                    errors.append(f"BENCHMARK {b} frozen at $100,000 — NAV not computed from price")

            # A2: TLT (with a price) must have a nav
            tlt = bms.get("tlt") or {}
            if tlt.get("price") and "nav" not in tlt:
                errors.append("TLT has price but no nav field")

            # A3: at least one benchmark should differ from start by >0.1% after 2 weeks
            navs = [(bms.get(b) or {}).get("nav") for b in ["spy", "qqq", "sso"]
                    if (bms.get(b) or {}).get("nav") is not None]
            if navs and all(abs(n - 100000) < 100 for n in navs) and len(history) > 5:
                errors.append("All benchmarks within $100 of start across >5 days — likely frozen")

            # A4: 60/40 should be present when both SPY and TLT have NAVs
            if (bms.get("spy") or {}).get("nav") and (bms.get("tlt") or {}).get("nav") and "60_40" not in bms:
                errors.append("60/40 composite missing despite SPY + TLT being available")

    # B1: intraday file freshness (warn only — separate workflow)
    intra = DATA / "intraday.json"
    if not intra.exists():
        print("  note: data/intraday.json absent (intraday workflow may not have run yet)")

    if errors:
        print("\n" + "="*60 + "\nVALIDATION FAILED:")
        for e in errors:
            print(f"  -  {e}")
        print("="*60)
        raise SystemExit(1)
    print("\nValidation passed.")


validate_outputs()
print("\nDaily update complete.")
