"""
Daily update wrapper — runs compute_regime.py then compute_nav.py in order.
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

def run(script: str):
    print(f"\n>>> {script}")
    rc = subprocess.call([sys.executable, str(HERE / script)])
    if rc != 0:
        print(f"!! {script} exited {rc}", file=sys.stderr)
        sys.exit(rc)

if __name__ == "__main__":
    run("compute_regime.py")
    run("compute_nav.py")
    print("\nUpdate complete.")
