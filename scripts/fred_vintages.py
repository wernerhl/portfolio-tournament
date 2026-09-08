#!/usr/bin/env python3
"""fred_vintages.py — point-in-time (ALFRED) inputs for the regime index (order 9-Sept, C2).

For every FRED series the 24-indicator v2 index consumes (directly or through a
derived spread), pull ALL releases from ALFRED and build the value that was
actually KNOWN on each calendar day: the latest observation published by that
day, at its latest revision published by that day. This captures both release
lag (a July print published in late August is not known in July) and revisions.

Before a series' first ALFRED vintage, two cases are distinguished (documented
per series in fred_vintage_meta.json):
  * the series did not yet exist as a published product (NFCI/ANFCI 2011,
    KCFSI 2010, STLFSI4 2022): the point-in-time value is NaN — nobody could
    have used it on that date;
  * the series existed but ALFRED only started tracking it later (Treasury
    yields, HY OAS, SLOOS, ...): the revised value shifted by the series'
    MEASURED publication lag (median first-release lag over its vintage
    history) — release lag honoured, revisions (negligible for these) ignored.

ALFRED limits handled: 2,000 vintage dates and 100,000 rows per request →
recursive window splitting on either signal.

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
# Did the series exist as published data before its first ALFRED vintage?
# False = the product was created at (about) its first vintage; its earlier
# history is retroactive back-fill that no one could have used at the time.
EXISTED_BEFORE_VINTAGES = {
    "nfci": False, "anfci": False,          # Chicago Fed NFCI/ANFCI launched 2011
    "kcfsi": False,                         # Kansas City Fed FSI launched 2009/10
    "stlfsi": False,                        # STLFSI4 (this construction) launched Nov 2022
    "breakeven_5y": True, "mfg_new_orders": True, "loan_tightening": True,
    "consumer_expect": True, "hy_oas": True, "us10y": True, "us03m": True,
    "baa_yield": True, "aaa_yield": True,
}
ROW_CAP = 100_000
VINTAGE_START = "1990-01-01"


def fetch_all_releases(fred, sid: str, start: str, end: str, _depth: int = 0) -> pd.DataFrame:
    """All releases in [start, end], splitting the real-time window whenever
    ALFRED refuses (>2000 vintage dates) or silently truncates (100k rows)."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    try:
        rel = fred.get_series_all_releases(sid, realtime_start=s.strftime("%Y-%m-%d"), realtime_end=e.strftime("%Y-%m-%d"))
        time.sleep(0.3)
        if rel is None:
            rel = pd.DataFrame(columns=["date", "realtime_start", "value"])
        if len(rel) < ROW_CAP or (e - s).days <= 3:
            return rel
    except ValueError as err:
        msg = str(err)
        if "vintage dates" not in msg and "exceeds the maximum" not in msg:
            raise
        if (e - s).days <= 3:
            raise
    mid = s + (e - s) / 2
    left = fetch_all_releases(fred, sid, s.strftime("%Y-%m-%d"), mid.strftime("%Y-%m-%d"), _depth + 1)
    right = fetch_all_releases(fred, sid, (mid + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"), _depth + 1)
    return pd.concat([left, right], ignore_index=True)


def pit_from_releases(rel: pd.DataFrame) -> pd.Series:
    """rel: columns date (observation period), realtime_start (vintage), value.
    Returns 'latest observation known, at its latest known revision' indexed
    by vintage dates (forward-fill downstream)."""
    rel = rel.dropna(subset=["value"]).copy()
    rel["date"] = pd.to_datetime(rel["date"]); rel["realtime_start"] = pd.to_datetime(rel["realtime_start"])
    rel = rel.drop_duplicates(subset=["date", "realtime_start"]).sort_values(["realtime_start", "date"])
    known: dict[pd.Timestamp, float] = {}
    out_idx, out_val = [], []
    for v, g in rel.groupby("realtime_start", sort=True):
        for d, val in zip(g["date"], g["value"]):
            known[d] = float(val)
        latest_obs = max(known)                      # most recent period known by vintage v
        out_idx.append(v); out_val.append(known[latest_obs])
    return pd.Series(out_val, index=pd.DatetimeIndex(out_idx)).sort_index()


def publication_lag_days(rel: pd.DataFrame) -> int:
    """Median (first vintage − observation date) in days over the first two
    years of vintage history — the lag a user experienced at the time."""
    r = rel.dropna(subset=["value"]).copy()
    r["date"] = pd.to_datetime(r["date"]); r["realtime_start"] = pd.to_datetime(r["realtime_start"])
    first = r.groupby("date")["realtime_start"].min()
    v0 = first.min()
    first = first[(first >= v0) & (first <= v0 + pd.Timedelta(days=730))]
    first = first[first.index >= v0 - pd.Timedelta(days=400)]   # exclude the back-filled history in the first vintage
    lag = (first - first.index.to_series()).dt.days
    return int(max(lag.median(), 0)) if len(lag) else 0


def lag_only_series(revised: pd.Series, lag_days: int, daily_idx: pd.DatetimeIndex) -> pd.Series:
    """Revised values, each becoming known lag_days after its observation date."""
    r = revised.dropna().copy()
    r.index = pd.to_datetime(r.index) + pd.Timedelta(days=lag_days)
    return r.reindex(daily_idx.union(r.index)).sort_index().ffill().reindex(daily_idx)


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
    today = pd.Timestamp.today().normalize()

    revised = pd.read_parquet(SOURCE / "fred_indicators.parquet")
    revised.index = pd.to_datetime(revised.index)
    daily_idx = pd.date_range(min(revised.index.min(), pd.Timestamp("1990-01-01")), max(revised.index.max(), today), freq="D")

    pit = revised.copy()
    meta = {"built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "method": ("ALFRED all releases; PIT value on day t = latest observation whose vintage "
                       "realtime_start <= t, at its latest revision with realtime_start <= t; forward-"
                       "filled daily. Before a series' first vintage: NaN if the series did not yet "
                       "exist as a published product, else the revised value shifted by the measured "
                       "publication lag (release lag honoured, revisions ignored)."),
            "limits": "2000 vintage dates / 100000 rows per request → recursive window splitting",
            "series": {}}
    for name, sid in PIT_SERIES.items():
        t0 = time.time()
        try:
            rel = fetch_all_releases(fred, sid, VINTAGE_START, today.strftime("%Y-%m-%d"))
        except Exception as e:
            print(f"  {name} ({sid}): FAILED — {str(e)[:160]}", file=sys.stderr)
            meta["series"][name] = {"id": sid, "status": "failed", "error": str(e)[:160]}
            continue
        rel = rel.drop_duplicates(subset=["date", "realtime_start"])
        s = pit_from_releases(rel)
        first_vintage = s.index.min()
        lag = publication_lag_days(rel)
        s_daily = s.reindex(daily_idx.union(s.index)).sort_index().ffill().reindex(daily_idx)
        rev = revised[name] if name in revised.columns else pd.Series(dtype=float)
        existed = EXISTED_BEFORE_VINTAGES[name]
        if existed and len(rev):
            pre = lag_only_series(rev, lag, daily_idx)
            s_daily = s_daily.where(daily_idx >= first_vintage, pre)
            treatment = f"revised shifted by measured publication lag ({lag}d) before first vintage"
        else:
            treatment = "unavailable (NaN) before first vintage — series did not yet exist as published data"
        pit[name] = s_daily.reindex(pit.index)
        both = pd.concat([pit[name].rename("pit"), rev.rename("rev")], axis=1).dropna()
        diff_share = float((~np.isclose(both["pit"], both["rev"], rtol=1e-6, atol=1e-9)).mean()) if len(both) else None
        lagonly = lag_only_series(rev, lag, daily_idx).reindex(pit.index) if len(rev) else pd.Series(dtype=float)
        post = pd.concat([pit[name].rename("pit"), lagonly.rename("lag")], axis=1).loc[pit.index >= first_vintage].dropna()
        rev_effect = float((~np.isclose(post["pit"], post["lag"], rtol=1e-6, atol=1e-9)).mean()) if len(post) else None
        meta["series"][name] = {
            "id": sid, "status": "ok", "n_release_rows": int(len(rel)),
            "first_vintage": str(first_vintage)[:10], "measured_publication_lag_days": lag,
            "existed_before_vintages": existed, "pre_vintage_treatment": treatment,
            "obs_range": [str(pd.to_datetime(rel["date"]).min())[:10], str(pd.to_datetime(rel["date"]).max())[:10]],
            "pit_first_day": str(pit[name].first_valid_index())[:10] if pit[name].notna().any() else None,
            "share_days_pit_differs_from_revised": round(diff_share, 4) if diff_share is not None else None,
            "share_days_revision_effect_after_first_vintage": round(rev_effect, 4) if rev_effect is not None else None,
            "fetch_seconds": round(time.time() - t0, 1),
        }
        m = meta["series"][name]
        print(f"  {name:16} {sid:12} rows {len(rel):>8}  first vintage {m['first_vintage']}  lag {lag:>3}d  "
              f"PIT≠revised {diff_share*100 if diff_share is not None else float('nan'):5.1f}%  "
              f"revision effect {rev_effect*100 if rev_effect is not None else float('nan'):5.1f}%  ({m['fetch_seconds']}s)")

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
