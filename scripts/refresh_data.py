"""
Targeted data refresh — re-fetches just the parquet files needed to extend the
tournament backtest. Skips Phase 1's quarterly + technicals + fundamentals
(those don't materially change in a few days and aren't read by backtest.py).

Updates in place in data/source/:
  prices_daily.parquet      — extends history through latest available date
  returns_daily.parquet     — recomputed from prices
  fred_indicators.parquet   — refreshes the 22 FRED series
  vol_indicators.parquet    — refreshes 12 vol/macro Yahoo series
  vol_derived.parquet       — recomputed from vol_indicators
  sector_etfs.parquet       — refreshes 17 sector/style ETFs

Usage:
  export FRED_API_KEY=...
  python scripts/refresh_data.py
"""
from __future__ import annotations
import os, sys, time, warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

REPO   = Path(__file__).resolve().parent.parent
SOURCE = REPO / "data" / "source"

T0 = time.time()
def log(msg): print(f"[{time.time()-T0:6.1f}s] {msg}", flush=True)


def drop_partial_today(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns a PARTIAL daily bar for the in-progress session when
    fetched during market hours. Every downstream artifact treats the last
    row as a settled close (canonical vol close, regime as_of, published
    vintage), so a partial bar poisons the whole chain. Keep only COMPLETE
    sessions: drop today's row before ~16:20 ET (close + settle buffer)."""
    from datetime import datetime as _dt, timedelta as _td
    et = _dt.utcnow() - _td(hours=4)   # approx ET; ±1h at DST is harmless here
    if et.hour < 16 or (et.hour == 16 and et.minute < 20):
        today = pd.Timestamp(et.date())
        if len(df) and pd.Timestamp(df.index[-1]).normalize() == today:
            return df.iloc[:-1]
    return df


def download_close(tickers, start, end=None) -> pd.DataFrame:
    """Returns DataFrame of close prices, columns=tickers, index=date."""
    end = end or datetime.now()
    out = {}
    BATCH = 50
    failed = []
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i:i+BATCH]
        try:
            data = yf.download(batch, start=start, end=end, progress=False, auto_adjust=True, threads=True)
            if data is None or data.empty: continue
            closes = data["Close"]
            if isinstance(closes, pd.Series):
                out[batch[0]] = closes
            else:
                for t in closes.columns:
                    s = closes[t].dropna()
                    if not s.empty: out[t] = s
        except Exception as e:
            failed.extend(batch)
            log(f"  warn batch {i}: {e}")
    if failed:
        log(f"  {len(failed)} tickers failed: {failed[:10]}...")
    return pd.DataFrame(out)


# ── SEPT AUDIT [1]: Cboe official-close history, per-index schema ────────
# The July build used cdn.cboe.com/api/global/delayed_quotes/charts/historical/
# {sym}.json with "_"-prefixed symbols; it returned nothing for 4 of 5
# indices. The us_indices/daily_prices/{SYM}_History.csv files serve all
# five — but their schemas DIFFER per index: VIX/VIX3M/VIX1D carry
# OPEN,HIGH,LOW,CLOSE; VVIX and SKEW carry a single value column named after
# the index. One parser, per-file column selection; never assume one pattern
# fits all. Full history is served, which also lets vol_indicators be
# overlaid with official closes (backfill source for SEPT AUDIT [3]).
CBOE_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv"
CBOE_SYMBOLS = {"vix": "VIX", "vix3m": "VIX3M", "vvix": "VVIX", "vix1d": "VIX1D", "skew": "SKEW"}
YF_SYMBOLS   = {"vix": "^VIX", "vix3m": "^VIX3M", "vvix": "^VVIX", "vix1d": "^VIX1D", "skew": "^SKEW"}
CANONICAL_REQUIRED = ("vix", "vix3m", "skew")   # write-time assertion set
CANONICAL_OPTIONAL = ("vvix", "vix1d")           # may be null, WITH a reason
CANONICAL_REFUSED = False                        # set by main(); drives the exit code


def cboe_history(sym: str) -> pd.Series:
    """Full daily official-close history for one Cboe index (see schema note above)."""
    import io, urllib.request as _url
    req = _url.Request(CBOE_HISTORY_URL.format(sym=sym), headers={"User-Agent": "Mozilla/5.0"})
    with _url.urlopen(req, timeout=20) as r:
        txt = r.read().decode()
    df = pd.read_csv(io.StringIO(txt))
    df.columns = [c.strip().upper() for c in df.columns]
    col = "CLOSE" if "CLOSE" in df.columns else sym.upper()
    if col not in df.columns:
        raise ValueError(f"{sym}_History.csv: no CLOSE or {sym} column (cols={list(df.columns)})")
    s = pd.Series(pd.to_numeric(df[col], errors="coerce").values,
                  index=pd.to_datetime(df["DATE"]), name=sym).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def build_canonical_close(vol_df: pd.DataFrame, canon_date: str | None = None) -> bool:
    """Write data/vol_close_canonical.json for the last completed session and
    OVERLAY Cboe official history onto vol_df in place (then re-save the
    parquet). Provider chain per field, recorded:
        1. Cboe official close (History CSV)         → "cboe"
        2. yfinance daily bar already in vol_df       → "yfinance"
        3. direct yfinance pull for that session      → "yfinance_direct"
        4. nothing                                    → "unavailable" + reason
    Write-time assertion (SEPT AUDIT [1.3]): on a trading day vix, vix3m and
    skew must be non-null or the write is REFUSED and the previous record
    retained (returns False; the orchestrator's validation names the
    assertion in status.json). vvix/vix1d may be null but carry a reason."""
    import json as _json
    from trading_calendar import last_trading_session, is_trading_day
    canon_date = canon_date or last_trading_session()
    ts = pd.Timestamp(canon_date)

    series, sources = {}, {}
    for name, sym in CBOE_SYMBOLS.items():
        try:
            series[name] = cboe_history(sym)
            sources[name] = {"provider": "cboe",
                             "from": str(series[name].index.min().date()),
                             "to": str(series[name].index.max().date()),
                             "n": int(len(series[name]))}
        except Exception as e:
            sources[name] = {"provider": "unavailable", "error": f"{type(e).__name__}: {e}"}
            log(f"  cboe {sym}: {type(e).__name__}: {e}")
        # Series fallback: a field with NO usable column at all (Cboe failed and
        # no yfinance column present) gets a direct yfinance history, recorded.
        if name not in series and (name not in vol_df.columns or vol_df[name].dropna().empty):
            try:
                d = yf.download(YF_SYMBOLS[name], start="2005-01-01", progress=False, auto_adjust=True)
                c = d["Close"]; c = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
                c.index = pd.to_datetime(c.index)
                vol_df[name] = c.reindex(vol_df.index)
                sources[name]["series_fallback"] = "yfinance_history"
            except Exception as e:
                sources[name]["series_fallback"] = f"failed: {type(e).__name__}"

    # Overlay: every date Cboe serves becomes the value of record.
    for name, s in series.items():
        if name not in vol_df.columns:
            vol_df[name] = np.nan
        idx = s.index.intersection(vol_df.index)
        vol_df.loc[idx, name] = s.loc[idx].values
        extra = s.index.difference(vol_df.index)
        extra = extra[(extra >= vol_df.index.min()) & (extra <= ts)]
        for d in extra:
            vol_df.loc[d, name] = float(s.loc[d])
    vol_df.sort_index(inplace=True)

    def _yf_direct(name):
        try:
            d = yf.download(YF_SYMBOLS[name],
                            start=(ts - pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
                            end=(ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                            progress=False, auto_adjust=True)
            if d is None or len(d) == 0:
                return None
            c = d["Close"]; c = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
            c.index = pd.to_datetime(c.index)
            return round(float(c.loc[ts]), 4) if ts in c.index else None
        except Exception:
            return None

    canonical = {"date": canon_date, "session_date": canon_date,
                 "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                 "provider_chain": "Cboe official close (us_indices/daily_prices/*_History.csv) → yfinance daily bar",
                 "providers": {}, "null_reasons": {}}
    for name in CBOE_SYMBOLS:
        v, prov = None, "unavailable"
        if name in series and ts in series[name].index:
            v, prov = round(float(series[name].loc[ts]), 4), "cboe"
        elif name in vol_df.columns and ts in vol_df.index and pd.notna(vol_df.loc[ts, name]):
            v, prov = round(float(vol_df.loc[ts, name]), 4), "yfinance"
        else:
            v = _yf_direct(name)
            prov = "yfinance_direct" if v is not None else "unavailable"
        canonical[name] = v
        canonical["providers"][name] = prov
        if v is None:
            canonical["null_reasons"][name] = (f"no Cboe row for {canon_date} "
                                               f"(cboe series: {sources.get(name, {}).get('provider')}) "
                                               f"and no yfinance bar")
    canonical["spread_spot_3m"] = (round(canonical["vix"] - canonical["vix3m"], 4)
                                   if canonical["vix"] is not None and canonical["vix3m"] is not None
                                   else None)
    canonical["series_sources"] = sources
    canonical["source"] = ("CANONICAL close for the vol complex — the single close of "
                           "record. intraday.json is a live snapshot; post-close it "
                           "reconciles to this file.")

    missing = [f for f in CANONICAL_REQUIRED if canonical[f] is None]
    if is_trading_day(canon_date) and missing:
        msg = (f"ASSERTION canonical_vol_close_required_nonnull: {missing} null for "
               f"session {canon_date} — write refused, previous record retained")
        log("  " + msg); print(msg, file=sys.stderr, flush=True)
        vol_df.to_parquet(SOURCE / "vol_indicators.parquet")   # overlay still valid
        return False
    with open(SOURCE.parent / "vol_close_canonical.json", "w") as f:
        _json.dump(canonical, f, indent=2)
    vol_df.to_parquet(SOURCE / "vol_indicators.parquet")
    log(f"  saved vol_close_canonical.json ({canon_date}: " +
        ", ".join(f"{k} {canonical[k]} [{canonical['providers'][k]}]" for k in CBOE_SYMBOLS) + ")")
    return True


def main():
    # ---- PRICES (universe from existing prices_daily) ----
    log("loading existing universe...")
    existing = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in existing.columns:
        spy_vol_old = existing["SPY_volume"]
        existing = existing.drop(columns=["SPY_volume"])
    else:
        spy_vol_old = None
    existing.index = pd.to_datetime(existing.index)
    universe = list(existing.columns)
    last_existing = existing.index.max()
    log(f"  {len(universe)} tickers, existing last date {last_existing.date()}")

    # Fetch from a buffer before last_existing to allow merge alignment
    fetch_start = (last_existing - timedelta(days=10)).strftime("%Y-%m-%d")
    log(f"fetching prices from {fetch_start} for {len(universe)} tickers...")
    new = download_close(universe, fetch_start)
    log(f"  fetched {new.shape}")
    new.index = pd.to_datetime(new.index)

    # Merge: existing rows + new rows for dates AFTER last_existing,
    # plus overwrite the recent overlap (in case there were stale values)
    cutoff = last_existing  # keep existing up through here, new after
    merged = pd.concat([
        existing.loc[existing.index <= cutoff],
        new.loc[new.index > cutoff].reindex(columns=universe),
    ])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    merged = drop_partial_today(merged)
    new_last = merged.index.max()
    log(f"  merged: {merged.shape}, new last date {new_last.date()}")

    # Save prices
    if spy_vol_old is not None:
        merged["SPY_volume"] = spy_vol_old.reindex(merged.index).ffill()
    merged.to_parquet(SOURCE / "prices_daily.parquet")
    log(f"  saved prices_daily.parquet")

    # Returns
    if "SPY_volume" in merged.columns:
        merged_no_vol = merged.drop(columns=["SPY_volume"])
    else:
        merged_no_vol = merged
    returns = merged_no_vol.pct_change()
    returns.to_parquet(SOURCE / "returns_daily.parquet")
    log(f"  saved returns_daily.parquet")

    # ---- VOL / MACRO ----
    log("fetching vol/macro series...")
    vol_tickers = {
        "vix":  "^VIX",  "vvix": "^VVIX", "vix3m": "^VIX3M", "vix1d": "^VIX1D",
        "skew": "^SKEW", "spx":  "^GSPC", "dxy":  "DX-Y.NYB",
        "oil":  "CL=F",  "gold": "GC=F",  "tlt":  "TLT",
        "hyg":  "HYG",   "lqd":  "LQD",
    }
    vol_data = {}
    for name, tk in vol_tickers.items():
        try:
            df = yf.download(tk, start="2005-01-01", progress=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                c = df["Close"]
                if isinstance(c, pd.DataFrame): c = c.iloc[:, 0]
                vol_data[name] = c
        except Exception as e:
            log(f"  warn {name}: {e}")
    vol_df = pd.DataFrame(vol_data)
    vol_df = drop_partial_today(vol_df)
    vol_df.to_parquet(SOURCE / "vol_indicators.parquet")
    log(f"  saved vol_indicators.parquet ({vol_df.shape})")

    # ── CANONICAL vol-complex close (JULY AUDIT FIX 3 · SEPT AUDIT [1]) ──
    # ONE fetcher writes data/vol_close_canonical.json once after each close;
    # intraday.json (post-close reconcile) and vol_regime.json READ from it,
    # and CI asserts equality ≤ 0.01. See build_canonical_close() for the
    # pinned per-field provider chain, the Cboe history overlay onto the
    # parquet, and the write-time assertion (a refusal retains the previous
    # record; the orchestrator's validation names the assertion in
    # status.json and this process exits non-zero).
    global CANONICAL_REFUSED
    try:
        CANONICAL_REFUSED = not build_canonical_close(vol_df)
    except Exception as e:
        log(f"  warn vol_close_canonical: {type(e).__name__}: {e}")
        CANONICAL_REFUSED = True

    # vol_derived
    log("computing vol_derived...")
    vd = pd.DataFrame(index=vol_df.index)
    if "vvix" in vol_df and "vix" in vol_df:
        vd["vvix_vix"] = vol_df["vvix"] / vol_df["vix"]
    if "vix3m" in vol_df and "vix" in vol_df:
        vd["vix_term"] = vol_df["vix"] - vol_df["vix3m"]   # negative = backwardation = stress
    if "oil" in vol_df:
        vd["oil_60d_vel"] = vol_df["oil"].pct_change(60) * 100
        vd["oil_20d_vel"] = vol_df["oil"].pct_change(20) * 100
    if "spx" in vol_df:
        spx = vol_df["spx"]
        vd["spx_drawdown"]        = (spx / spx.cummax() - 1) * 100
        vd["spx_return_20d"]      = spx.pct_change(20) * 100
        vd["spx_return_60d"]      = spx.pct_change(60) * 100
        vd["spx_realized_vol_20d"] = spx.pct_change().rolling(20).std() * np.sqrt(252) * 100
    if "hyg" in vol_df and "lqd" in vol_df:
        vd["hyg_lqd_ratio"] = vol_df["hyg"] / vol_df["lqd"]
    if "gold" in vol_df and "spx" in vol_df:
        vd["gold_spx"] = vol_df["gold"] / vol_df["spx"]
    if "tlt" in vol_df and "spx" in vol_df:
        vd["tlt_spx"] = vol_df["tlt"] / vol_df["spx"]
    vd.to_parquet(SOURCE / "vol_derived.parquet")
    log(f"  saved vol_derived.parquet ({vd.shape})")

    # ---- SECTOR ETFs ----
    log("fetching sector ETFs...")
    sector_tickers = ["XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY","IGV","GLD",
                      "SPY","QQQ","DIA","IWM","SMH","SOXX"]
    sect_data = {}
    for tk in sector_tickers:
        try:
            df = yf.download(tk, start="2005-01-01", progress=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                c = df["Close"]
                if isinstance(c, pd.DataFrame): c = c.iloc[:, 0]
                sect_data[tk.lower()] = c
        except Exception as e:
            log(f"  warn {tk}: {e}")
    sect_df = pd.DataFrame(sect_data)
    sect_df = drop_partial_today(sect_df)
    sect_df.to_parquet(SOURCE / "sector_etfs.parquet")
    log(f"  saved sector_etfs.parquet ({sect_df.shape})")

    # ---- FRED ----
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        log("  no FRED_API_KEY — skipping FRED refresh (keeping existing)")
    else:
        log("fetching FRED...")
        try:
            from fredapi import Fred
            fred = Fred(api_key=api_key)
            fred_series = {
                "hy_oas":"BAMLH0A0HYM2", "ig_oas":"BAMLC0A0CM",
                "us02y":"DGS2", "us10y":"DGS10", "us03m":"DGS3MO",
                "sofr":"SOFR", "effr":"EFFR", "ted_spread":"TEDRATE",
                "claims_weekly":"ICSA", "claims_4wk":"IC4WSA", "continued_claims":"CCSA",
                "fed_balance_sheet":"WALCL", "rrp":"RRPONTSYD",
                "nfci":"NFCI", "anfci":"ANFCI",
                "breakeven_5y":"T5YIE", "breakeven_10y":"T10YIE",
                "baa_yield":"BAA", "aaa_yield":"AAA",
                "mortgage_30y":"MORTGAGE30US",
                "umich_sentiment":"UMCSENT", "ism_mfg":"BUSLOANS",
                # v2 addendum: additional Tier A forward-looking indicators (5 working)
                # Note: USSLIND (Philly Fed LEI) and NAPMNOI (ISM new orders) are no longer
                # maintained on FRED. NEWORDER (durable goods orders) substitutes for ISM.
                # No reliable free leading-indicator composite available — Tier A grows to 14.
                "mfg_new_orders":  "NEWORDER", # monthly: durable goods new orders ($M)
                "kcfsi":           "KCFSI",    # monthly: Kansas City Fed financial stress index
                "stlfsi":          "STLFSI4",  # weekly:  St. Louis Fed FSI (v4 supersedes STLFSI2)
                "loan_tightening": "DRTSCILM", # quarterly: SLOOS net % tightening C&I std
                "consumer_expect": "MICH",     # monthly: Michigan consumer expectations (1-5Y)
            }
            # Fetch with retry. If a series fails twice, we'll preserve any existing values
            # for that column by merging into the pre-existing parquet at save time.
            fred_data = {}
            failed = []
            for name, sid in fred_series.items():
                last_err = None
                for attempt in range(2):
                    try:
                        s = fred.get_series(sid, observation_start="2005-01-01")
                        fred_data[name] = s.dropna()
                        break
                    except Exception as e:
                        last_err = e
                        time.sleep(0.6)
                else:
                    failed.append(name)
                    log(f"  warn FRED {name}: {last_err}")
            log(f"  fetched FRED: {len(fred_data)}/{len(fred_series)} series ok"
                + (f"; failed: {failed}" if failed else ""))

            fred_df = pd.DataFrame(fred_data)
            # MERGE into existing fred_indicators.parquet so a transient FRED hiccup
            # doesn't wipe out columns that haven't been refetched this run.
            fpath = SOURCE / "fred_indicators.parquet"
            if fpath.exists():
                existing = pd.read_parquet(fpath)
                existing.index = pd.to_datetime(existing.index)
                all_idx = existing.index.union(fred_df.index)
                merged = pd.DataFrame(index=all_idx)
                # Start with existing columns, reindexed
                for c in existing.columns:
                    merged[c] = existing[c].reindex(all_idx)
                # Overlay fresh values where available (extends history forward)
                for c in fred_df.columns:
                    incoming = fred_df[c].reindex(all_idx)
                    if c in merged.columns:
                        merged[c] = incoming.combine_first(merged[c])
                    else:
                        merged[c] = incoming
                fred_df = merged.sort_index()
            fred_df.to_parquet(fpath)
            log(f"  saved fred_indicators.parquet ({fred_df.shape}, {len(failed)} preserved from prior fetch)")

            # fred_derived (recompute from the MERGED fred_df, so derived series
            # also survive a partial fetch as long as their inputs exist in the merge)
            fdr = pd.DataFrame(index=fred_df.index)
            if "us02y" in fred_df and "us10y" in fred_df:
                fdr["yield_2s10s"] = fred_df["us10y"] - fred_df["us02y"]
            if "us03m" in fred_df and "us10y" in fred_df:
                fdr["yield_3m10y"] = fred_df["us10y"] - fred_df["us03m"]
            if "sofr" in fred_df and "effr" in fred_df:
                fdr["sofr_ff_bps"] = (fred_df["sofr"] - fred_df["effr"]) * 100
            if "baa_yield" in fred_df and "aaa_yield" in fred_df:
                fdr["baa_aaa_spread"] = (fred_df["baa_yield"] - fred_df["aaa_yield"]) * 100
            if "fed_balance_sheet" in fred_df:
                fdr["fed_bs_T"] = fred_df["fed_balance_sheet"] / 1e6   # millions → trillions
            if "claims_weekly" in fred_df:
                rolling_low = fred_df["claims_weekly"].rolling(52, min_periods=10).min()
                fdr["claims_dist_from_low"] = (fred_df["claims_weekly"] / rolling_low - 1) * 100
            fdr.to_parquet(SOURCE / "fred_derived.parquet")
            log(f"  saved fred_derived.parquet ({fdr.shape})")
        except Exception as e:
            log(f"  FRED refresh failed: {e}")

    log(f"\nDone. New last date in prices: {new_last.date()}")
    log(f"total elapsed: {time.time() - T0:.1f}s")


if __name__ == "__main__":
    if "--canonical-only" in sys.argv:
        # SEPT AUDIT [1]: regenerate the canonical close + Cboe overlay from
        # the existing parquet without a full refresh (no FRED key needed).
        # Optional --date=YYYY-MM-DD targets a specific completed session.
        _v = pd.read_parquet(SOURCE / "vol_indicators.parquet")
        _v.index = pd.to_datetime(_v.index)
        _date = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--date=")), None)
        sys.exit(0 if build_canonical_close(_v, _date) else 1)
    main()
    sys.exit(1 if CANONICAL_REFUSED else 0)
