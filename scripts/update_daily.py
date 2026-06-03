"""Daily pipeline wrapper. Called by GitHub Actions.

Order (v2):
  1. refresh_data.py       — pull latest prices + FRED into data/source/
  2. compute_regime_v2.py  — read source parquets, compute R_lead/R_full/divergence
  3. compute_nav.py        — apply regime to tier NAVs, tier_holdings → tournament.json
  4. build_ticker_data.py  — refresh per-ticker drill-down JSON
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

scripts = [
    "refresh_data.py",
    "compute_regime_v2.py",
    "compute_nav.py",
    "build_ticker_data.py",
]

for script in scripts:
    print(f"\n{'='*60}\nRunning {script}\n{'='*60}")
    rc = subprocess.call([sys.executable, str(HERE / script)])
    if rc != 0:
        print(f"WARNING: {script} exited with code {rc}", file=sys.stderr)
print("\nDaily update complete.")
