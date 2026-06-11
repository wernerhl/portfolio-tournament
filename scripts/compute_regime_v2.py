"""
EWS v2 — Two-layer forward-looking regime model.

Computes two regime scores from 18 indicators classified by temporal nature:

  Tier A — Forward-looking (9):  embed market expectations about the future.
           NFCI, ANFCI, yield_3m10y, breakeven_5y, baa_aaa, vix_term,
           skew, vix, vvix.

  Tier B — Contemporaneous (5):  cross-market signals that reprice faster than equities.
           hyg_lqd, gold_spx, tlt_spx, def_cyc, dxy.

  Tier C — Backward-looking (4): trailing price stats; value comes only from persistence.
           realized_vol, spx_ret_60d, spx_drawdown, oil_60d_vel.

  R_lead = mean(Tier A scores)             (forward-only early warning)
  R_full = tier-weighted mean (A:2, B:1, C:0.5)  (full regime, used for sizing)
  divergence = R_lead - R_full             (early warning when > +0.15)

Reads source parquets in data/source/; runs in ~1-2 seconds.

Outputs:
  data/regime_v2_daily.csv          full history: R_lead, R_full, divergence, regime, etc.
  data/regime_v2_risk_scores.parquet per-indicator Φ(z) scores
  data/regime_v2_zscores.parquet     per-indicator z-scores
  data/regime_indicators.json        current snapshot for the dashboard
  data/regime_daily.csv              compat shim (R_t = R_full) so v1 callers still work
"""
from __future__ import annotations
import json, math, sys, warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"
DATA.mkdir(exist_ok=True)

LOOKBACK    = 252
MIN_PERIODS = 60
MIN_LEAD    = 8    # of 14 Tier A (after addendum)
MIN_FULL    = 12   # of 23 total

TIER_WEIGHTS = {"A": 2.0, "B": 1.0, "C": 0.5}

# (key, tier, direction, source_file, source_col, label, fmt, narratives)
# narratives = [safe, neutral, elevated, crisis]
INDICATORS = [
    # ---------------- Tier A — Forward-looking ----------------
    ("nfci",         "A", "higher", "fred_indicators", "nfci",
     "NFCI",     "{v:+.2f}",
     ["Financial conditions easy",   "Conditions neutral",
      "Conditions tightening",       "Financial stress"]),
    ("anfci",        "A", "higher", "fred_indicators", "anfci",
     "ANFCI",    "{v:+.2f}",
     ["No financial stress",         "Adjusted neutral",
      "Adjusted tightening",         "Adjusted stress"]),
    ("yield_3m10y",  "A", "lower",  "fred_derived",    "yield_3m10y",
     "3m-10y",   "{v:+.2f}",
     ["Curve normal",                "Curve flattening",
      "Curve flat",                  "Curve inverted"]),
    ("breakeven_5y", "A", "higher", "fred_indicators", "breakeven_5y",
     "BE 5Y",    "{v:.2f}",
     ["Inflation expectations stable","Inflation drifting up",
      "Inflation expectations rising","Inflation expectations spiking"]),
    ("baa_aaa",      "A", "higher", "fred_derived",    "baa_aaa_spread",
     "Baa-Aaa",  "{v:.2f}",
     ["Quality spread normal",       "Spread firm",
      "Spread widening",             "Spread acute"]),
    ("vix_term",     "A", "higher", "vol_derived",     "vix_term",
     "VIX term", "{v:+.1f}",
     ["Term contango",               "Term flat",
      "Term backwardation",          "Term inverted (acute)"]),
    ("skew",         "A", "lower",  "vol_indicators",  "skew",
     "SKEW",     "{v:.0f}",
     ["Tail risk priced",            "Tail pricing normal",
      "Tail risk underpriced",       "Tail complacency"]),
    ("vix",          "A", "higher", "vol_indicators",  "vix",
     "VIX",      "{v:.2f}",
     ["Calm hedging demand",         "Hedging neutral",
      "Caution rising",              "Stress signaling"]),
    ("vvix",         "A", "higher", "vol_indicators",  "vvix",
     "VVIX",     "{v:.1f}",
     ["Tail protection cheap",       "Tail protection moderate",
      "Tail protection bid",         "Vol-of-vol stretched"]),

    # ---- v2 addendum: 5 additional Tier A forward-looking indicators ----
    ("mfg_new_orders","A","lower",  "fred_indicators", "mfg_new_orders",
     "Mfg orders","${v:,.0f}M",
     ["New orders trending up",      "Orders stable",
      "Orders softening",            "Orders contracting (recession signal)"]),
    ("kcfsi",        "A", "higher", "fred_indicators", "kcfsi",
     "KCFSI",    "{v:+.2f}",
     ["KC stress below average",     "KC stress neutral",
      "KC stress elevated",          "KC stress acute"]),
    ("stlfsi",       "A", "higher", "fred_indicators", "stlfsi",
     "STLFSI",   "{v:+.2f}",
     ["St. Louis FSI calm",          "St. Louis FSI neutral",
      "St. Louis FSI elevated",      "St. Louis FSI acute"]),
    ("loan_tightening","A","higher","fred_indicators", "loan_tightening",
     "Loan tight","{v:+.1f}%",
     ["Banks easing credit",         "Standards neutral",
      "Banks tightening credit",     "Credit crunch (leads default cycle)"]),
    ("consumer_expect","A","lower", "fred_indicators", "consumer_expect",
     "UMich Exp.","{v:.1f}",
     ["Consumers optimistic",        "Expectations neutral",
      "Consumers cautious",          "Consumers pessimistic"]),

    # ---------------- Tier B — Contemporaneous ----------------
    ("hyg_lqd",      "B", "lower",  "vol_derived", "hyg_lqd_ratio",
     "HYG/LQD",  "{v:.2f}",
     ["Credit spreads tight",        "Credit stable",
      "Credit spreads widening",     "Credit stress acute"]),
    ("gold_spx",     "B", "higher", "vol_derived", "gold_spx",
     "Gold/SPX", "{v:.2f}",
     ["No safe-haven bid",           "Mild safe-haven bid",
      "Elevated safe-haven bid",     "Heavy flight to safety"]),
    ("tlt_spx",      "B", "higher", "vol_derived", "tlt_spx",
     "TLT/SPX",  "{v:.3f}",
     ["No flight to quality",        "Bond bid neutral",
      "Bond bid rising",             "Heavy flight to quality"]),
    ("def_cyc",      "B", "higher", "_DERIVED_",  "def_cyc",
     "Def/cyc",  "{v:.2f}",
     ["Cyclical leadership",         "Sector rotation neutral",
      "Slight defensive rotation",   "Heavy defensive rotation"]),
    ("dxy",          "B", "higher", "vol_indicators", "dxy",
     "DXY",      "{v:.1f}",
     ["Dollar weak",                 "Dollar neutral",
      "Dollar strengthening",        "Dollar liquidity drain"]),

    # ---------------- Tier C — Backward-looking ----------------
    ("realized_vol", "C", "higher", "vol_derived", "spx_realized_vol_20d",
     "Real vol", "{v:.1f}%",
     ["Below-average volatility",    "Normal volatility",
      "Volatility rising",           "Volatility spike"]),
    ("spx_ret_60d",  "C", "lower",  "vol_derived", "spx_return_60d",
     "SPX 60d",  "{v:+.1f}%",
     ["Positive momentum",           "Momentum mixed",
      "Momentum negative",           "Momentum severely negative"]),
    ("spx_drawdown", "C", "lower",  "vol_derived", "spx_drawdown",
     "SPX DD",   "{v:+.1f}%",
     ["Near all-time high",          "Mild pullback",
      "In drawdown",                 "Deep drawdown"]),
    ("oil_60d_vel",  "C", "higher", "vol_derived", "oil_60d_vel",
     "Oil 60d",  "{v:+.1f}%",
     ["No supply shock",             "Oil drift",
      "Oil rallying",                "Oil shock"]),
]


def load_sources() -> dict[str, pd.DataFrame]:
    out = {}
    for stem in ["fred_indicators", "fred_derived", "vol_indicators",
                 "vol_derived", "sector_etfs", "breadth_indicators"]:
        p = SOURCE / f"{stem}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df.index = pd.to_datetime(df.index)
            out[stem] = df
    return out


def derive_series(name: str, sources: dict) -> pd.Series | None:
    """Compute on-the-fly series (e.g. def_cyc from sector ETFs)."""
    if name == "def_cyc":
        s = sources.get("sector_etfs")
        if s is None: return None
        cols = ["xlu", "xlp", "xlk", "xly"]
        if not all(c in s.columns for c in cols): return None
        defensive = s["xlu"] + s["xlp"]
        cyclical  = s["xlk"] + s["xly"]
        return (defensive / cyclical).dropna()
    return None


def load_series_dict(sources: dict) -> dict[str, pd.Series]:
    """Map each indicator key to its raw series (forward-filled to daily later)."""
    out = {}
    for key, tier, direction, src, col, *_ in INDICATORS:
        if src == "_DERIVED_":
            s = derive_series(key, sources)
        else:
            df = sources.get(src)
            if df is None or col not in df.columns:
                print(f"  warn: {key}: source {src}.{col} missing", file=sys.stderr)
                continue
            s = df[col].dropna()
        if s is None or s.empty:
            print(f"  warn: {key}: empty series", file=sys.stderr)
            continue
        out[key] = s
    return out


def build_daily_panel(series_dict: dict[str, pd.Series]) -> pd.DataFrame:
    """Align all indicator series to a daily business-day index, forward-fill weekly/monthly."""
    if not series_dict:
        return pd.DataFrame()
    all_idx = pd.DatetimeIndex(sorted({d for s in series_dict.values() for d in s.index}))
    # Build daily business-day grid spanning the union range
    start, end = all_idx.min(), all_idx.max()
    daily_idx = pd.date_range(start, end, freq="B")
    out = pd.DataFrame(index=daily_idx)
    for key, s in series_dict.items():
        out[key] = s.reindex(daily_idx).ffill()
    return out


def compute_zscores_and_risk(panel: pd.DataFrame):
    """Returns (zscores, risk_scores). risk_scores is Φ(z) in [0,1] with sign-flipped 'lower'."""
    direction_map = {key: d for key, _, d, *_ in INDICATORS}
    z_df = pd.DataFrame(index=panel.index)
    s_df = pd.DataFrame(index=panel.index)
    for col in panel.columns:
        ser = panel[col]
        m = ser.rolling(LOOKBACK, min_periods=MIN_PERIODS).mean()
        sd = ser.rolling(LOOKBACK, min_periods=MIN_PERIODS).std().replace(0, np.nan)
        z = (ser - m) / sd
        if direction_map.get(col) == "lower":
            z = -z
        z_df[col] = z
        s_df[col] = norm.cdf(z)
    return z_df, s_df


def compute_composites(risk: pd.DataFrame):
    """R_lead (Tier A only), R_full (tier-weighted), divergence."""
    tier_map = {key: tier for key, tier, *_ in INDICATORS}
    a_cols = [k for k in risk.columns if tier_map.get(k) == "A"]
    all_cols = list(risk.columns)

    # R_lead: simple mean of Tier A
    r_lead = risk[a_cols].mean(axis=1)
    n_lead = risk[a_cols].notna().sum(axis=1)
    r_lead = r_lead.where(n_lead >= MIN_LEAD)

    # R_full: tier-weighted average over all available indicators
    weights = pd.Series({c: TIER_WEIGHTS[tier_map[c]] for c in all_cols})
    available = risk[all_cols].notna().astype(float)
    weighted_num = (risk[all_cols].fillna(0) * weights).sum(axis=1)
    weighted_den = (available * weights).sum(axis=1).replace(0, np.nan)
    r_full = weighted_num / weighted_den
    n_full = available.sum(axis=1)
    r_full = r_full.where(n_full >= MIN_FULL)

    divergence = r_lead - r_full
    return r_lead, r_full, divergence, n_lead.astype(int), n_full.astype(int)


def classify(r_full, r_lead, divergence):
    regime = pd.Series("UNKNOWN", index=r_full.index, dtype=object)
    regime[r_full < 0.30] = "LOW RISK"
    regime[(r_full >= 0.30) & (r_full < 0.50)] = "ELEVATED"
    regime[(r_full >= 0.50) & (r_full < 0.70)] = "HIGH RISK"
    regime[r_full >= 0.70] = "CRISIS"

    ew = pd.Series("UNKNOWN", index=r_lead.index, dtype=object)
    ew[r_lead < 0.35] = "CLEAR"
    ew[(r_lead >= 0.35) & (r_lead < 0.55)] = "WATCH"
    ew[(r_lead >= 0.55) & (r_lead < 0.75)] = "WARNING"
    ew[r_lead >= 0.75] = "DANGER"

    div = pd.Series("CONSISTENT", index=divergence.index, dtype=object)
    div[divergence >  0.15] = "LEADING RISK"
    div[divergence < -0.15] = "RECOVERY"
    return regime, ew, div


def status_from_phi(phi: float) -> str:
    if phi < 0.40: return "safe"
    if phi < 0.60: return "neutral"
    if phi < 0.80: return "elevated"
    return "crisis"


def narrative_for(idx: int, phi: float) -> str:
    if math.isnan(phi): return "—"
    narratives = INDICATORS[idx][7]
    if phi < 0.40: return narratives[0]
    if phi < 0.60: return narratives[1]
    if phi < 0.80: return narratives[2]
    return narratives[3]


def _clean(o):
    if isinstance(o, dict):  return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):  return [_clean(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    return o


def main():
    print("Loading source parquets...")
    sources = load_sources()
    print(f"  loaded {len(sources)} source files: {list(sources)}")

    print("Mapping indicators...")
    series = load_series_dict(sources)
    print(f"  resolved {len(series)}/{len(INDICATORS)} indicators")
    missing = [k for k, *_ in INDICATORS if k not in series]
    if missing:
        print(f"  missing: {missing}")

    print("Building daily panel + z-scores...")
    panel = build_daily_panel(series)
    z_df, s_df = compute_zscores_and_risk(panel)

    print("Computing composites...")
    r_lead, r_full, div_s, n_lead, n_full = compute_composites(s_df)
    regime, ew, divalert = classify(r_full, r_lead, div_s)

    # ---- Build the daily summary CSV (full history) ----
    out_df = pd.DataFrame({
        "R_lead":           r_lead.round(4),
        "R_full":           r_full.round(4),
        "divergence":       div_s.round(4),
        "n_lead_indicators": n_lead,
        "n_full_indicators": n_full,
        "regime":           regime,
        "early_warning":    ew,
        "divergence_alert": divalert,
    })
    out_df.index.name = "date"
    out_df.to_csv(DATA / "regime_v2_daily.csv")
    print(f"  saved regime_v2_daily.csv ({len(out_df)} rows)")

    # ---- Parquet artifacts (per-indicator) ----
    s_df.to_parquet(DATA / "regime_v2_risk_scores.parquet")
    z_df.to_parquet(DATA / "regime_v2_zscores.parquet")
    print(f"  saved regime_v2_{{risk_scores,zscores}}.parquet ({s_df.shape})")

    # ---- v1 compat shim so compute_nav.py still finds R_t ----
    compat = pd.DataFrame({"R_t": r_full.round(4), "n_indicators": n_full})
    compat.index.name = "date"
    compat.dropna(subset=["R_t"]).to_csv(DATA / "regime_daily.csv")
    print(f"  saved regime_daily.csv (compat shim: R_t = R_full — REVISED vintage; "
          f"recomputed under current inputs every run)")

    # ---- PUBLISHED vintage (AUDIT FIX 4) ----
    # regime_daily.csv above is the REVISED series: a full recompute under
    # today's (possibly revised/backfilled) inputs. The PUBLISHED series is
    # append-only — each date's R_t frozen at the value the system first
    # printed for it. FRED series revise and publish T+1; the published
    # vintage is what the system actually knew in real time, and it is the
    # only legitimate series for real-time performance claims.
    pub_path = DATA / "regime_daily_published.csv"
    if pub_path.exists():
        pub = pd.read_csv(pub_path, index_col="date")
        pub.index = pub.index.astype(str)
    else:
        # Seed from tournament.json history — those rows were written
        # nightly at publish time and never recomputed.
        pub = pd.DataFrame(columns=["R_t_published"])
        pub.index.name = "date"
        try:
            tj = json.load(open(DATA / "tournament.json"))
            seed = {h["date"]: h["R_t"] for h in tj.get("history", []) if h.get("R_t") is not None}
            pub = pd.DataFrame({"R_t_published": pd.Series(seed)})
            pub.index.name = "date"
            print(f"  seeded regime_daily_published.csv from tournament.json ({len(pub)} as-published rows)")
        except Exception as e:
            print(f"  warn publish-seed: {e}")
    _latest_pub = out_df.dropna(subset=["R_full"]).iloc[-1]
    today_key = _latest_pub.name.strftime("%Y-%m-%d")
    # Append-only: NEVER overwrite an existing date. AND never freeze a value
    # for an in-progress session — only append once the session is complete
    # (as_of strictly before today, or today after ~21:30 UTC ≈ 16:30 ET).
    from datetime import datetime as _dtt, timezone as _tz
    _now = _dtt.now(_tz.utc)
    _session_complete = (today_key < _now.strftime("%Y-%m-%d")) or \
                        (_now.hour > 21 or (_now.hour == 21 and _now.minute >= 30))
    if today_key not in pub.index and _session_complete:
        pub.loc[today_key, "R_t_published"] = round(float(_latest_pub["R_full"]), 4)
        print(f"  appended published vintage: {today_key} R_t = {float(_latest_pub['R_full']):.4f}")
    elif today_key not in pub.index:
        print(f"  published vintage: session {today_key} not complete — not freezing a partial value")
    pub.sort_index().to_csv(pub_path)
    print(f"  saved regime_daily_published.csv ({len(pub)} frozen rows)")

    # ---- Dashboard snapshot JSON ----
    latest_row = out_df.dropna(subset=["R_full"]).iloc[-1]
    asof = latest_row.name
    print(f"\n=== LATEST STATE ({asof.date()}) ===")
    print(f"  R_lead = {latest_row['R_lead']:.3f}  ({latest_row['early_warning']})")
    print(f"  R_full = {latest_row['R_full']:.3f}  ({latest_row['regime']})")
    print(f"  divergence = {latest_row['divergence']:+.3f}  ({latest_row['divergence_alert']})")
    n_tier_a = sum(1 for spec in INDICATORS if spec[1] == "A")
    print(f"  Tier A: {latest_row['n_lead_indicators']}/{n_tier_a} · Total: {latest_row['n_full_indicators']}/{len(INDICATORS)}")

    indicator_payload = []
    for idx, spec in enumerate(INDICATORS):
        key, tier, direction, _src, _col, label, fmt, _narrs = spec
        if key not in s_df.columns: continue
        s_series = s_df[key].dropna()
        if s_series.empty: continue
        d_last = s_series.index[-1]
        phi_v = float(s_series.iloc[-1])
        z_v   = float(z_df[key].dropna().iloc[-1]) if not z_df[key].dropna().empty else None
        raw_v = float(panel[key].dropna().iloc[-1]) if not panel[key].dropna().empty else None
        status = status_from_phi(phi_v)
        narr   = narrative_for(idx, phi_v)
        try:
            value_str = fmt.format(v=raw_v) if raw_v is not None else "—"
        except Exception:
            value_str = f"{raw_v:.2f}" if raw_v is not None else "—"
        indicator_payload.append({
            "key":       key,
            "label":     label,
            "tier":      tier,
            "weight":    TIER_WEIGHTS[tier],
            "value":     raw_v,
            "value_str": value_str,
            "z":         z_v,
            "phi":       phi_v,
            "status":    status,
            "narrative": narr,
            "direction": direction,
            "as_of":     d_last.strftime("%Y-%m-%d"),
        })

    n_by_status = {"safe":0, "neutral":0, "elevated":0, "crisis":0}
    for i in indicator_payload: n_by_status[i["status"]] += 1
    # AUDIT FIX 3: keep neutral as its own bucket — folding it into n_safe makes
    # the header claim "X safe" while X−N of those cards render BLUE (neutral),
    # not green. Header now surfaces 4 buckets and matches card colors.
    n_safe = n_by_status["safe"]
    n_neu  = n_by_status["neutral"]
    n_ele  = n_by_status["elevated"]
    n_cri  = n_by_status["crisis"]

    R_lead_v = float(latest_row["R_lead"])
    R_full_v = float(latest_row["R_full"])
    divv     = float(latest_row["divergence"])

    # ── Complacency flag — AUDIT FIX 4: align with indicator encoding ──────
    # The SKEW indicator uses direction='lower', so HIGH SKEW = active tail
    # hedging = SAFE in the card narratives. The old flag fired on HIGH SKEW
    # + LOW VIX, which directly contradicted the card. Resolution: complacency
    # is when NO ONE is pricing tails AND no one is hedging — i.e. LOW SKEW
    # AND LOW VIX. Both encodings now agree.
    raw_lookup = {i["key"]: i for i in indicator_payload}
    skew_raw = (raw_lookup.get("skew") or {}).get("value")
    vix_raw  = (raw_lookup.get("vix")  or {}).get("value")
    complacency_flag = bool(skew_raw is not None and vix_raw is not None
                            and skew_raw < 130 and vix_raw < 15)
    complacency_reason = (f"SKEW {skew_raw:.0f} < 130 and VIX {vix_raw:.1f} < 15 — "
                          f"no tail premium and no hedging — market complacent"
                          ) if complacency_flag else None
    R_lead_displayed = round(min(1.0, R_lead_v + (0.05 if complacency_flag else 0.0)), 4)

    # AUDIT FIX 6: verdict was a deployment recommendation that didn't know about
    # intraday shocks, so the dashboard ignored it (built its own via
    # headlineVerdict). Now we keep it as a NEUTRAL channel-state description —
    # no deployment claim — so the field is informative not contradictory.
    if divv > 0.15:
        verdict = (f"Forward layer ({R_lead_v:.2f}) pricing risk above equities ({R_full_v:.2f}). "
                   f"Divergence +{divv:.2f}.")
    elif divv < -0.15:
        verdict = (f"Forward layer ({R_lead_v:.2f}) normalizing below equities ({R_full_v:.2f}). "
                   f"Divergence {divv:.2f}.")
    else:
        verdict = (f"{n_safe} safe · {n_neu} neutral · {n_ele} elevated · {n_cri} crisis "
                   f"of {len(indicator_payload)} channels. R_full {R_full_v:.2f}.")

    # Prepend the complacency callout so it's the first thing the user reads.
    if complacency_flag:
        verdict = f"COMPLACENCY FLAG — {complacency_reason}. " + verdict

    payload = {
        "updated":      datetime.now().isoformat(),
        "as_of":        asof.strftime("%Y-%m-%d"),
        # v2 fields
        "R_lead":       round(R_lead_v, 4),
        "R_lead_displayed": R_lead_displayed,
        "R_full":       round(R_full_v, 4),
        "divergence":   round(divv, 4),
        "regime":       str(latest_row["regime"]),
        "early_warning": str(latest_row["early_warning"]),
        "divergence_alert": str(latest_row["divergence_alert"]),
        "n_lead_indicators": int(latest_row["n_lead_indicators"]),
        "n_full_indicators": int(latest_row["n_full_indicators"]),
        # complacency flag
        "complacency_flag":   complacency_flag,
        "complacency_reason": complacency_reason,
        # v1 compatibility (dashboard's renderRegimeCommandCenter reads R_t)
        "R_t":          round(R_full_v, 4),
        # status counts — AUDIT FIX 3: neutral is its own bucket
        "n_indicators": len(indicator_payload),
        "n_safe":       n_safe,
        "n_neutral":    n_neu,
        "n_elevated":   n_ele,
        "n_crisis":     n_cri,
        "verdict":      verdict,
        "indicators":   indicator_payload,
    }
    with open(DATA / "regime_indicators.json", "w") as f:
        json.dump(_clean(payload), f, indent=2, default=str, allow_nan=False)
    print(f"  saved regime_indicators.json")
    print(f"  verdict: {verdict}")

    print(f"\nPer-indicator state (latest):")
    for i in indicator_payload:
        z_str = f"{i['z']:+.2f}" if i["z"] is not None else "  -- "
        print(f"  [{i['tier']}] {i['label']:<10} s={i['phi']:.3f}  z={z_str}  → {i['status']:>8}  ({i['narrative']})")


if __name__ == "__main__":
    main()
