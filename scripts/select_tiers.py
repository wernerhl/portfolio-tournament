"""
Read data/scored_universe.csv. Apply per-tier universe filter + factor reweighting.
Pick top-N per tier. Write data/tier_holdings.json (with previous + turnover).
Runs after score_universe.py.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def apply_filter(df: pd.DataFrame, f: dict | None) -> pd.DataFrame:
    if not f: return df
    out = df.copy()
    if "sectors" in f:
        out = out[out["sector"].isin(f["sectors"])]
    if "min_gross_margin" in f:
        out = out[out["grossMargins"].fillna(-1) >= f["min_gross_margin"]]
    if f.get("require_positive_fcf"):
        out = out[out["freeCashflow"].fillna(0) > 0]
    return out


def select_for_tier(scored: pd.DataFrame, spec: dict) -> list[str]:
    cand = apply_filter(scored, spec.get("universe_filter"))
    if cand.empty:
        return []
    w = spec["factor_weights"]
    total_w = w["ma200"] + w["rsi"] + w["rs6m"]
    cand = cand.assign(
        tier_tech = (
            cand["ma200_rank"].fillna(0.5) * w["ma200"] +
            cand["rsi_rank"].fillna(0.5)   * w["rsi"] +
            cand["rs6m_rank"].fillna(0.5)  * w["rs6m"]
        ) / total_w * 25,
    )
    cand["tier_composite"] = cand["tier_tech"] + cand["fund_score"].fillna(cand["fund_score"].median())
    picks = cand.nlargest(spec["n_holdings"], "tier_composite")["ticker"].tolist()
    return picks


def main():
    with open(REPO / "config.json") as f:
        cfg = json.load(f)
    tier_specs = cfg["tier_specs"]
    scored = pd.read_csv(DATA / "scored_universe.csv")
    print(f"Loaded {len(scored)} scored tickers")

    # Previous holdings, if any
    prev_path = DATA / "tier_holdings.json"
    prev = {}
    if prev_path.exists():
        try:
            prev = json.load(open(prev_path)).get("tiers", {})
        except Exception:
            prev = {}

    new_holdings = {}
    turnover_map = {}
    for tier_id, spec in tier_specs.items():
        picks = select_for_tier(scored, spec)
        new_holdings[tier_id] = picks
        # turnover = symmetric difference / (2 × N)
        old = set(prev.get(tier_id, []))
        new = set(picks)
        if old:
            sym = len(old ^ new)
            turn = sym / (2 * len(new)) if new else 0
        else:
            turn = 1.0
        turnover_map[tier_id] = round(turn, 4)
        print(f"  {spec['short']:11s}  {len(picks):2d} holdings (turnover {turn*100:4.0f}%): "
              f"{', '.join(picks[:6])}{'…' if len(picks) > 6 else ''}")

    out = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "tiers": new_holdings,
        "previous_holdings": prev,
        "turnover": turnover_map,
    }
    with open(prev_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved → {prev_path}")


if __name__ == "__main__":
    main()
