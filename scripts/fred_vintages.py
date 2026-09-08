#!/usr/bin/env python3
"""fred_vintages.py — point-in-time (ALFRED) inputs for the regime index (order 9-Sept, C2).

For every FRED series the 24-indicator v2 index consumes (directly or through a
derived spread), pull ALL releases from ALFRED and build the value that was
actually KNOWN on each calendar day: the latest observation published by that
day, at its latest revision published by that day. This captures both release
lag (a July print published in late August is not known in July) and revisions.

Writes (source data, never served):
  data/source/fred_indicators_pit.parquet   — revised parquet with the index's
                                              inputs overwritten by PIT series
  data/source/fred_derived_pit.parquet      — derived spreads from PIT components
  data/source/fred_vintage_meta.json        — per-series vintage coverage

Requires FRED_API_KEY (repository secret; run via .github/workflows/vintage_rebuild.yml).
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "data" / "source"

# name → FRED id, for every series the v2 index touches (see compute_regime_v2 INDICATORS)
PIT_SERIES = {
    "nfci": "NFCI", "anfci": "ANFCI", "breakeven_5y": "T5YIE",
    "mfg_new_orders": "NEWORDER", "kcfsi": "KCFSI", "stlfsi": "STLFSI4",
    "loan_tightening": "DRTSCILM", "consumer_expect": "MICH",
    "hy_oas": "BAMLH0A0HYM2",
    "us10y": "DGS10", "us03m": "DGS3MO",          # → yield_3m10y
    "baa_yield": "BAA", "aaa_yield": "AAA",        # → baa_aaa_spread
}


def pit_from_releases(rel: pd.DataFrame) -> pd.Series:
    """rel: columns date (observation period), realtime_start (vintage), value.
    Returns the daily series of 'latest observation known, at its latest known
    revision' indexed by vintage dates (forward-fill downstream)."""
    rel = rel.dropna(subset=["value"]).copy()
    rel["date"] = pd.to_datetime(rel["date"]); rel["realtime_start"] = pd.to_datetime(rel["realtime_start"])
    rel = rel.sort_values(["realtime_start", "date"])
    known: dict[pd.Timestamp, float] = {}
    out_idx, out_val = [], []
    for v, g in rel.groupby("realtime_start", sort=True):
        for d, val in zip(g["date"], g["value"]):
            known[d] = float(val)
        latest_obs = max(known)                      # most recent period known by vintage v
        out_idx.append(v); out_val.append(known[latest_obs])
    return pd.Series(out_val, index=pd.DatetimeIndex(out_idx)).sort_index()


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from trading_calendar import require_trading_day
    require_trading_day("fred_vintages")
    key = os.environ.get("FRED_API_KEY")
    if not key:
        print("FRED_API_KEY missing — run via the vintage_rebuild workflow", file=sys.stderr)
        return 1
    from fredapi import Fred
    fred = Fred(api_key=key)

    revised = pd.read_parquet(SOURCE / "fred_indicators.parquet")
    revised.index = pd.to_datetime(revised.index)
    daily_idx = pd.date_range(revised.index.min(), max(revised.index.max(), pd.Timestamp.today().normalize()), freq="D")

    pit = revised.copy()
    meta = {"built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "method": ("ALFRED all releases; PIT value on day t = latest observation whose vintage "
                       "realtime_start <= t, at its latest revision with realtime_start <= t; "
                       "forward-filled daily. Before a series' first vintage the PIT value is NaN "
                       "(the series did not exist as published data)."),
            "series": {}}
    for name, sid in PIT_SERIES.items():
        for attempt in range(3):
            try:
                rel = fred.get_series_all_releases(sid)
                break
            except Exception as e:
                err = e; time.sleep(2 + 2 * attempt)
        else:
            print(f"  {name} ({sid}): FAILED — {err}", file=sys.stderr)
            meta["series"][name] = {"id": sid, "status": "failed", "error": str(err)[:120]}
            continue
        s = pit_from_releases(rel)
        s_daily = s.reindex(daily_idx.union(s.index)).sort_index().ffill().reindex(daily_idx)
        pit[name] = s_daily.reindex(pit.index)
        rev = revised[name] if name in revised.columns else pd.Series(dtype=float)
        both = pd.concat([pit[name].rename("pit"), rev.rename("rev")], axis=1).dropna()
        diff_share = float((~np.isclose(both["pit"], both["rev"], rtol=1e-6, atol=1e-9)).mean()) if len(both) else None
        meta["series"][name] = {
            "id": sid, "status": "ok", "n_release_rows": int(len(rel)),
            "first_vintage": str(rel["realtime_start"].min())[:10],
            "obs_range": [str(rel["date"].min())[:10], str(rel["date"].max())[:10]],
            "pit_first_day": str(pit[name].first_valid_index())[:10] if pit[name].notna().any() else None,
            "share_days_pit_differs_from_revised": round(diff_share, 4) if diff_share is not None else None,
        }
        print(f"  {name:16} {sid:12} releases {len(rel):>6}  first vintage {meta['series'][name]['first_vintage']}  "
              f"PIT≠revised on {diff_share*100 if diff_share is not None else float('nan'):.1f}% of overlapping days")

    pit.to_parquet(SOURCE / "fred_indicators_pit.parquet")
    # derived spreads from PIT components; the other derived columns are not index inputs → copied
    try:
        der = pd.read_parquet(SOURCE / "fred_derived.parquet"); der.index = pd.to_datetime(der.index)
    except Exception:
        der = pd.DataFrame(index=pit.index)
    der_pit = der.copy()
    der_pit["yield_3m10y"] = pit["us10y"] - pit["us03m"]
    der_pit["baa_aaa_spread"] = pit["baa_yield"] - pit["aaa_yield"]
    der_pit.to_parquet(SOURCE / "fred_derived_pit.parquet")
    with open(SOURCE / "fred_vintage_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    ok = sum(1 for v in meta["series"].values() if v["status"] == "ok")
    print(f"saved fred_indicators_pit.parquet, fred_derived_pit.parquet, fred_vintage_meta.json ({ok}/{len(PIT_SERIES)} series)")
    return 0 if ok == len(PIT_SERIES) else 1


if __name__ == "__main__":
    sys.exit(main())
