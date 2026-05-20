"""Daily pipeline wrapper. Called by GitHub Actions.

Order: compute_regime → compute_nav → build_ticker_data
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

scripts = [
    "compute_regime.py",
    "compute_nav.py",
    "build_ticker_data.py",
]

for script in scripts:
    print(f"\n{'='*60}\nRunning {script}\n{'='*60}")
    rc = subprocess.call([sys.executable, str(HERE / script)])
    if rc != 0:
        print(f"WARNING: {script} exited with code {rc}", file=sys.stderr)
        # Continue instead of failing the whole pipeline — we want partial updates
print("\nDaily update complete.")
