#!/usr/bin/env python3
"""fetch_sleeves.py — canonical price provider fetch for the bond sleeves (order 1.1/1.3).

Prices from the system's canonical provider (yfinance, the same provider refresh_data.py
uses), fetched here as part of the nightly pipeline. The sleeves are kept in a DEDICATED
source store, data/source/bond_sleeves.parquet, NOT the equity price store — so they never
enter the equity universe, the tournament scoring, the union-universe referee check, or
build_universe.py. Distribution yield per sleeve is read from the provider's fund data,
with the field name and the retrieval date recorded (order 1.3); a missing yield is marked
unavailable, never substituted (order §7).

Writes (source; bond_sleeves.parquet is never served, sleeve_yields.json feeds the metrics):
  data/source/bond_sleeves.parquet   — adjusted-close history, columns = sleeve tickers
  data/bonds/sleeve_yields.json      — {field, retrieved_at, yields:{ticker: fraction|null}}
"""
from __future__ import annotations
import json, sys, time, warnings
from datetime import date

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import bonds_common as bc

warnings.filterwarnings("ignore")


def log(m: str) -> None:
    print(m, flush=True)


def download_close(tickers: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 25):
        batch = tickers[i:i + 25]
        for attempt in range(2):
            try:
                raw = yf.download(batch, start=start, auto_adjust=True, progress=False, threads=True)
                px = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": batch[0]})
                for t in batch:
                    if t in px.columns and not px[t].dropna().empty:
                        out[t] = px[t].dropna()
                break
            except Exception as e:
                if attempt == 1:
                    log(f"  warn download {batch}: {str(e)[:80]}")
                time.sleep(0.8)
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def fetch_yields(tickers: list[str]) -> dict:
    import yfinance as yf
    ys = {}
    for t in tickers:
        val = None
        try:
            info = yf.Ticker(t).info
            y = info.get("yield")
            if y is not None and float(y) > 0:
                val = round(float(y), 6)      # provider returns the yield as a fraction
        except Exception as e:
            log(f"  warn yield {t}: {str(e)[:60]}")
        ys[t] = val
        if val is None:
            log(f"  {t}: distribution yield unavailable (not substituted)")
    return ys


def main() -> int:
    tickers = bc.sleeve_tickers()
    log(f"fetching {len(tickers)} sleeve prices...")
    fresh = download_close(tickers, "2005-01-01")
    if fresh.empty:
        log("  no sleeve prices fetched — keeping existing store")
    else:
        bc.SLEEVE_PRICES.parent.mkdir(parents=True, exist_ok=True)
        if bc.SLEEVE_PRICES.exists():
            existing = pd.read_parquet(bc.SLEEVE_PRICES); existing.index = pd.to_datetime(existing.index)
            idx = existing.index.union(fresh.index)
            merged = pd.DataFrame(index=idx)
            for c in set(existing.columns) | set(fresh.columns):
                a = existing[c].reindex(idx) if c in existing.columns else pd.Series(index=idx, dtype=float)
                b = fresh[c].reindex(idx) if c in fresh.columns else pd.Series(index=idx, dtype=float)
                merged[c] = b.combine_first(a)         # fresh overlays, extends history forward
            fresh = merged.sort_index()
        fresh = fresh.reindex(columns=sorted(fresh.columns))
        fresh.to_parquet(bc.SLEEVE_PRICES)
        log(f"  saved bond_sleeves.parquet {fresh.shape}, through {fresh.index.max().date()}")

    log("fetching distribution yields...")
    ys = fetch_yields(tickers)
    payload = {"field": "yield", "field_note": "provider fund distribution yield (fraction)",
               "retrieved_at": date.today().isoformat(), "provider": "yfinance",
               "yields": ys,
               "unavailable": sorted([t for t, v in ys.items() if v is None])}
    bc.SLEEVE_YIELDS.parent.mkdir(parents=True, exist_ok=True)
    bc.SLEEVE_YIELDS.write_text(json.dumps(payload, indent=2))
    have = sum(1 for v in ys.values() if v is not None)
    log(f"  saved sleeve_yields.json ({have}/{len(tickers)} yields; {len(payload['unavailable'])} unavailable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
