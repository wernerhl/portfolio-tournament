#!/usr/bin/env python3
"""c3_export_paths.py — P2.2 (dashboard order 9-Sept-2026): drawdown paths of the C3 contestants
(regime index with tier-4 sizing, the best one-line rule, buy-and-hold) exported from the C3 NAV
paths for the retirement panel's chart. Static artifact (declared on_change); rerun only after a
C3 rerun. Reads data/c3/nav_4_tactical.csv (git-ignored working output) and data/c3_results.json."""
import json, sys
from pathlib import Path
import pandas as pd
REPO = Path(__file__).resolve().parent.parent; DATA = REPO / "data"
LABEL = {"sma10": "10-month SMA", "tsmom_12_1": "12-1 momentum", "vol_target_10": "10% vol targeting"}
def main():
    nav = pd.read_csv(DATA / "c3" / "nav_4_tactical.csv", index_col=0, parse_dates=True)
    res = json.load(open(DATA / "c3_results.json")); best = res["decision"]["best_rule"]
    dd = (nav / nav.cummax() - 1.0)
    cols = {"regime": "regime", "best_rule": best, "buy_and_hold": "buy_and_hold"}
    wk = dd.iloc[::5]
    out = {"cadence": "on_change", "as_of": res.get("as_of"), "source": "data/c3/nav_4_tactical.csv via scripts/c3_regime_vs_rules.py (registration reports/c3_registration.md; v2 reports/c3_registration_v2.md)",
           "tier": "4_tactical", "best_rule": best, "best_rule_label": LABEL.get(best, best), "window": [str(dd.index[0].date()), str(dd.index[-1].date())],
           "sampling": "every 5th session", "dates": [str(d.date()) for d in wk.index],
           "series": {k: [round(float(v), 5) for v in wk[c]] for k, c in cols.items()},
           "min": {k: round(float(dd[c].min()), 5) for k, c in cols.items()}}
    json.dump(out, open(DATA / "c3_drawdown_paths.json", "w"), separators=(",", ":"))
    print("saved data/c3_drawdown_paths.json:", out["window"], "best rule", best, "points", len(out["dates"]), "min", out["min"])
if __name__ == "__main__": sys.exit(main())
