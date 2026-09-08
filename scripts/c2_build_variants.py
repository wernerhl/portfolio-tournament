#!/usr/bin/env python3
"""c2_build_variants.py — decomposition variants for C2 (order 9-Sept), built locally
from committed data (no API key):
  fred_*_lag.parquet      revised values shifted by each series' MEASURED publication
                          lag (release lag only; no revisions; every series treated as
                          existing throughout)
  fred_*_pitfill.parquet  true ALFRED vintages after a series' first vintage (the _pit
                          parquet), lag-only before it (every series treated as existing)
Together with fred_*_pit.parquet (strict: unavailable before the series existed) the
successive differences isolate release lag, revisions, and series existence.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "data" / "source"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fred_vintages import lag_only_series, PIT_SERIES  # noqa: E402


def main() -> int:
    rev = pd.read_parquet(SOURCE / "fred_indicators.parquet"); rev.index = pd.to_datetime(rev.index)
    pit = pd.read_parquet(SOURCE / "fred_indicators_pit.parquet"); pit.index = pd.to_datetime(pit.index)
    meta = json.load(open(SOURCE / "fred_vintage_meta.json"))["series"]
    daily = pd.date_range(min(rev.index.min(), pd.Timestamp("1990-01-01")), rev.index.max(), freq="D")
    lag, fill = rev.copy(), pit.copy()
    for name in PIT_SERIES:
        L = meta[name]["measured_publication_lag_days"]
        lo = lag_only_series(rev[name], L, daily).reindex(rev.index)
        lag[name] = lo
        fill[name] = pit[name].where(pit[name].notna(), lo)      # only NaN-before-first-vintage gets filled
        print(f"  {name:16} lag {L:>3}d  first vintage {meta[name]['first_vintage']}  "
              f"pit NaN days filled: {int((pit[name].isna() & lo.notna()).sum())}")
    der = pd.read_parquet(SOURCE / "fred_derived.parquet"); der.index = pd.to_datetime(der.index)
    for tag, df in (("_lag", lag), ("_pitfill", fill)):
        df.to_parquet(SOURCE / f"fred_indicators{tag}.parquet")
        d = der.copy()
        d["yield_3m10y"] = df["us10y"] - df["us03m"]
        d["baa_aaa_spread"] = df["baa_yield"] - df["aaa_yield"]
        d.to_parquet(SOURCE / f"fred_derived{tag}.parquet")
    print("saved fred_{indicators,derived}_{lag,pitfill}.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
