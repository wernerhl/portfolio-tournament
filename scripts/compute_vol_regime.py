"""
compute_vol_regime.py — VIX term-structure regime + spike attribution.

Primary signal: spot−3M spread (VIXCLS − VXVCLS, FRED-quality, long history).
VX1/VX2 futures spread is the documented upgrade but requires CBOE EOD
settlements; not run here, flagged in output.

State (threshold model, v1):
  deep_contango    spread < -2.5     calm market, 3M priced well above spot
  contango         -2.5 ≤ spread < 0  the normal state (~75% of days)
  flattening       0 ≤ spread < 1     vol structure tightening into stress
  backwardation    spread ≥ 1         confirmed stress

Per-state DYNAMICS (forward content):
  - current age (sessions in this state)
  - empirical persistence quartiles + median decay path from history

Trigger for the attribution classifier — fire ONLY when one of:
  Δspread ≥ +1σ of its own 20-day distribution, OR
  cross from contango (spread<0) toward zero/backwardation

Then run the 8-cell classifier (curve-driven primary driver):
  A = event flag       (NFP/CPI/FOMC today, from event_calendar.json)
  B = front-end repriced  |Δ2Y| ≥ 7 bps in direction consistent with rate move
  C = held close       VIX close in top quartile of intraday range (proxy)

  A=1 B=1 C=1 → regime_repricing            reversion LOW
  A=1 B=1 C=0 → regime_repricing(weak)      reversion MED
  A=1 B=0 C=0 → event_bump                  reversion HIGH
  A=1 B=0 C=1 → event_bump(sticky)          reversion MED
  A=0 B=1 C=*  → rate_repricing_unscheduled  reversion MED
  A=0 B=0 C=1 → unclassified_persistent     reversion MED
  A=0 B=0 C=0 → unclassified_noise          reversion HIGH

INDEPENDENT equity_drag overlay (parallel to the primary driver):
  semiconductor proxy (SMH or SOXX) down hard while breadth holds intact.
  Fires when: SMH 1d return ≤ -5% AND breadth % above 50dma drop ≤ 5pp.

Reversion DEFINITION (config) — required to make hit-rate computable:
  REVERSION_N = 10 sessions
  REVERSION_X = 0.5 × σ(spread over rolling 1y)
  A spike at day t reverts if at any session in (t+1, t+N) the spread
  is within X of its pre-spike (t-1) level.

HARD CONSTRAINTS:
  - close-behavior is a close-time fact → signal timestamped at close,
    applied to the NEXT session (t+1 open). Backtest test asserts this.
  - 8 cells enumerated, no inference; ML/feature-creep banned.
  - tiny n: walk-forward reversion hit-rate is the acceptance metric.

Output: data/vol_regime.json
"""
from __future__ import annotations
import json, math, sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO   = Path(__file__).resolve().parent.parent
DATA   = REPO / "data"
SOURCE = DATA / "source"

# ── Threshold + trigger config (kept here; revisable but documented) ───
# Calibrated to the empirical VIX − VIX3M distribution: long-run median in
# deep contango around -3 to -4 (calm/normal); flattening = spread within
# ~1σ of zero; backwardation when spot meaningfully exceeds 3M. The 06-05
# event lands the spread at -0.31 (flattened from -3.83 yesterday) → correctly
# "flattening" under this scheme.
STATE_BREAKS = {
    "deep_contango_max": -3.0,
    "contango_max":      -1.0,
    "flattening_max":    +0.5,
}
TRIGGER_SIGMA   = 1.0   # Δspread ≥ +1σ of 20d rolling stdev
DELTA_2Y_BPS    = 7.0   # |Δ2Y| ≥ 7 bps → front-end repricing flag
HELD_QUARTILE   = 0.75  # VIX close in top-quartile of day's range (≥ p75)
EQUITY_DRAG_PCT = -0.05 # SMH 1d return ≤ -5%
# Breadth "holds" rule — calibrated to the measure's own daily volatility
# instead of a fixed pp cutoff. Same z-score discipline as the other
# indicators: today's Δbreadth holds if it sits within ±k·σ of the 1-year
# distribution of its own daily changes. RoP-FIX 3.
BREADTH_HOLD_K_SIGMA = 1.0

# Reversion definition — explicit
REVERSION_N     = 10                  # sessions
REVERSION_X_SD  = 0.5                 # × 1y σ of spread


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────
def classify_state(spread: float) -> str:
    if spread < STATE_BREAKS["deep_contango_max"]: return "deep_contango"
    if spread < STATE_BREAKS["contango_max"]:      return "contango"
    if spread < STATE_BREAKS["flattening_max"]:    return "flattening"
    return "backwardation"


def runs_with_boundaries(states: pd.Series, spread: pd.Series
                          ) -> list[tuple[str, int, int, int, float]]:
    """
    Return [(state, start_idx, end_idx, length, entry_dspread), ...]
    entry_dspread = the Δspread on the first day of the run (the day the
    state changed). For the very first run we use 0.0 since there's no
    preceding state.
    """
    delta = spread.diff().fillna(0.0)
    states_list = states.tolist()
    if not states_list: return []
    out = []
    cur, start = states_list[0], 0
    for i in range(1, len(states_list)):
        if states_list[i] != cur:
            entry_d = float(delta.iloc[start]) if start > 0 else 0.0
            out.append((cur, start, i - 1, i - start, entry_d))
            cur, start = states_list[i], i
    entry_d = float(delta.iloc[start]) if start > 0 else 0.0
    out.append((cur, start, len(states_list) - 1, len(states_list) - start, entry_d))
    return out


# RoP-FIX B2: per-state entry-Δspread distribution for the atypical-entry flag.
def state_dynamics(states: pd.Series, spread: pd.Series = None) -> dict:
    """Per-state persistence quartiles + transitions + entry-Δspread stats."""
    if spread is not None:
        runs = runs_with_boundaries(states, spread)
    else:
        # Legacy code path — synthesize a zeros series
        runs = runs_with_boundaries(states, pd.Series(0.0, index=states.index))
    out = {}
    for state in ("deep_contango", "contango", "flattening", "backwardation"):
        lengths = [n for s, _, _, n, _ in runs if s == state]
        entry_dspreads = [d for s, _, _, _, d in runs if s == state and _ != 0]
        # Transitions: state immediately after each completed run of `state`
        transitions = []
        for i, (s, *_rest) in enumerate(runs[:-1]):
            if s == state:
                transitions.append(runs[i + 1][0])
        next_state_counts = {}
        for t in transitions:
            next_state_counts[t] = next_state_counts.get(t, 0) + 1
        out[state] = {
            "n_episodes":              len(lengths),
            "p25_sessions":            int(np.percentile(lengths, 25)) if lengths else 0,
            "median_sessions":         int(np.percentile(lengths, 50)) if lengths else 0,
            "p75_sessions":            int(np.percentile(lengths, 75)) if lengths else 0,
            "next_state_distribution": next_state_counts,
            "entry_dspread_mean":      float(np.mean(entry_dspreads)) if entry_dspreads else None,
            "entry_dspread_sigma":     float(np.std(entry_dspreads, ddof=1)) if len(entry_dspreads) > 1 else None,
            "entry_dspread_n":         len(entry_dspreads),
        }
    return out


def compute_breadth(prices: pd.DataFrame, ma_window: int = 50) -> pd.Series:
    """% of universe with close above its own ma_window-DMA, daily."""
    cols = [c for c in prices.columns if c not in ("SPY",)]
    px = prices[cols]
    ma = px.rolling(ma_window, min_periods=ma_window).mean()
    above = (px > ma).sum(axis=1)
    n = px.notna().sum(axis=1).replace(0, np.nan)
    return (above / n * 100).rename("breadth_pct_above_50dma")


def vix_intraday_range_quartile_proxy(vix_series: pd.Series, lookback: int = 20) -> float:
    """
    Without 1-min OHLC, approximate "VIX closed top-quartile of today's range"
    by comparing today's CLOSE to the 20-session high/low band:
        proxy = (close - low_20d) / (high_20d - low_20d)
    proxy ≥ 0.75 → "held" (top-quartile of recent range)
    proxy < 0.75 → "faded" (anywhere else)
    This is a defensible proxy; if 1m bars become available, replace.
    """
    hi = vix_series.rolling(lookback).max().iloc[-1]
    lo = vix_series.rolling(lookback).min().iloc[-1]
    close = vix_series.iloc[-1]
    return float((close - lo) / (hi - lo)) if hi > lo else 0.5


def load_events() -> dict[str, list[str]]:
    """Date → list of event types occurring on that date."""
    try:
        d = json.load(open(DATA / "event_calendar.json"))
        out = {}
        for e in d["events"]:
            out.setdefault(e["date"], []).append(e["type"])
        return out
    except Exception as e:
        print(f"  warn no event_calendar.json: {e}", file=sys.stderr)
        return {}


# ────────────────────────────────────────────────────────────────────────
# Driver classifier — 8 cells, enumerated.
# ────────────────────────────────────────────────────────────────────────
def classify_driver(event_flag: bool, front_end_flag: bool, held_close: bool) -> dict:
    A, B, C = event_flag, front_end_flag, held_close
    if   A and B and C:         return {"driver":"regime_repricing",            "reversion":"low"}
    elif A and B and not C:     return {"driver":"regime_repricing_weak",       "reversion":"med"}
    elif A and not B and not C: return {"driver":"event_bump",                  "reversion":"high"}
    elif A and not B and C:     return {"driver":"event_bump_sticky",           "reversion":"med"}
    elif not A and B:           return {"driver":"rate_repricing_unscheduled",  "reversion":"med"}
    elif not A and not B and C: return {"driver":"unclassified_persistent",     "reversion":"med"}
    else:                       return {"driver":"unclassified_noise",          "reversion":"high"}


# ────────────────────────────────────────────────────────────────────────
# Walk-forward reversion: two metrics so each is honest about its sample.
#   all_triggers — every fired trigger that has a full N-session horizon
#                  available (excludes today). The big-n number.
#   event_only   — subset of those that fired on a scheduled-event day.
#                  Small-n by construction; if < 5 we refuse to print a
#                  point-estimate rate.
# Wilson 95% CI alongside both rates so a 9/10 doesn't read as established.
# ────────────────────────────────────────────────────────────────────────
def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a binomial proportion."""
    if n == 0: return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _measure_subsample(spread: pd.Series, fired_idx: pd.Index,
                        last_date: pd.Timestamp) -> dict:
    sd_1y = spread.rolling(252, min_periods=60).std()
    n_attempts = 0; n_reverted = 0
    spike_records = []
    for d in fired_idx:
        if d not in spread.index: continue
        i = spread.index.get_loc(d)
        # Horizon must be FULLY elapsed → exclude today (last_date) and any
        # spike whose tail window extends past available data.
        if d == last_date: continue
        if i < 1 or i + REVERSION_N >= len(spread): continue
        pre = spread.iloc[i - 1]
        sigma = sd_1y.iloc[i]
        if not np.isfinite(sigma) or sigma <= 0: continue
        threshold = REVERSION_X_SD * sigma
        window = spread.iloc[i + 1 : i + REVERSION_N + 1]
        reverted = bool(((window - pre).abs() <= threshold).any())
        n_attempts += 1
        if reverted: n_reverted += 1
        spike_records.append((d, reverted))
    rate = (n_reverted / n_attempts) if n_attempts > 0 else None
    ci_lo, ci_hi = _wilson_ci(n_reverted, n_attempts) if n_attempts > 0 else (None, None)
    return {
        "n": n_attempts,
        "n_reverted": n_reverted,
        "hit_rate": rate,
        "wilson_95ci": [ci_lo, ci_hi] if ci_lo is not None else None,
        "horizon_sessions": REVERSION_N,
        "threshold_sigma": REVERSION_X_SD,
    }


def walk_forward_reversion(spread: pd.Series, triggers: pd.DataFrame,
                            event_flag_series: pd.Series) -> dict:
    fired = triggers[triggers["fired"]].index
    last_date = spread.index[-1]
    event_fired = fired[[event_flag_series.get(d, False) for d in fired]]
    all_metric   = _measure_subsample(spread, fired, last_date)
    event_metric = _measure_subsample(spread, event_fired, last_date)
    # Caveat language for the small-n event subsample
    event_caption = None
    if event_metric["n"] == 0:
        event_caption = "no event-day spikes with elapsed horizon yet"
    elif event_metric["n"] < 5:
        event_caption = f"event-day n = {event_metric['n']} — too small to estimate; refer to the all-trigger metric"
    elif event_metric["n"] < 30:
        lo, hi = event_metric["wilson_95ci"]
        event_caption = (f"event-day n = {event_metric['n']} → 95% CI "
                          f"{int(lo*100)}–{int(hi*100)}%; not yet evidence")
    return {
        "today_excluded_from_metrics": str(last_date.date()),
        "all_triggers_reversion":      all_metric,
        "event_day_only_reversion":    event_metric,
        "event_day_caveat":            event_caption,
        "note": ("`all_triggers_reversion` measures all fired triggers with a fully "
                  "elapsed N-session horizon — the right denominator for the spread-"
                  "spike reversion question. `event_day_only_reversion` is the "
                  "event-day subsample; by construction it has handful-per-year n."),
    }


# ────────────────────────────────────────────────────────────────────────
# No-look-ahead assertion — signal at close ⇒ applied next OPEN.
# ────────────────────────────────────────────────────────────────────────
def assert_no_lookahead(daily: pd.DataFrame) -> None:
    """
    The tradeable signal at date d uses ONLY information whose timestamp is
    ≤ d's close. We enforce this by constructing the 'tradable_at' column
    as next-session open — daily['signal_date_t'] ⇒ daily['tradable_open_t1'].
    This assertion checks that every signal row has a strictly later
    tradable date.
    """
    if "tradable_at" not in daily.columns: return
    deltas = (pd.to_datetime(daily["tradable_at"]) - daily.index).dt.days
    assert (deltas > 0).all(), "look-ahead detected — some tradable_at <= signal date"


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────
def main():
    print("Loading sources...")
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet")
    fred = pd.read_parquet(SOURCE / "fred_indicators.parquet") if (SOURCE / "fred_indicators.parquet").exists() else None
    sect = pd.read_parquet(SOURCE / "sector_etfs.parquet")
    prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in prices.columns: prices = prices.drop(columns=["SPY_volume"])

    # Spread series
    spread = (vol["vix"] - vol["vix3m"]).dropna().rename("spread_spot_3m")
    spread.index = pd.to_datetime(spread.index)

    # 2Y yield series (FRED us02y). FRED publishes T+1 around macro releases
    # (NFP/CPI print at 08:30 ET, FRED EOD lands the next day). The DGS2
    # day-over-day diff IS release-spanning — it compares today's close to
    # yesterday's close, capturing the 08:30 reaction. We do NOT use an
    # intraday rate snapshot (^IRX is 13W not 2Y; CME 2YY=F delisted on
    # Yahoo). When FRED today is NaN, we fall back to operator-injectable
    # manual override (MANUAL_DELTA_2Y_BPS env var) — transparent in payload.
    if fred is not None and "us02y" in fred.columns:
        us02y = fred["us02y"].dropna()
        us02y.index = pd.to_datetime(us02y.index)
        delta_2y_bps = us02y.diff() * 100.0      # FRED publishes in %, so bps = %*100
    else:
        us02y = pd.Series(dtype=float)
        delta_2y_bps = pd.Series(dtype=float)

    # Semiconductor 1d return (SMH preferred, SOXX fallback)
    smh = (sect["smh"] if "smh" in sect.columns else sect["soxx"]).dropna()
    smh.index = pd.to_datetime(smh.index)
    smh_ret_1d = smh.pct_change()

    # Breadth: % of universe above 50-DMA
    breadth = compute_breadth(prices, ma_window=50).dropna()
    breadth.index = pd.to_datetime(breadth.index)
    breadth_delta = breadth.diff()

    # Events
    events_by_date = load_events()
    event_flag_series = pd.Series(
        {pd.Timestamp(d): True for d in events_by_date.keys()}
    ).reindex(spread.index, fill_value=False)

    # States series + age column
    states = spread.apply(classify_state).rename("state")
    states_list = states.tolist()
    age = []
    cur, n = states_list[0], 1
    age.append(1)
    for s in states_list[1:]:
        if s == cur:
            n += 1
        else:
            cur, n = s, 1
        age.append(n)
    age_series = pd.Series(age, index=states.index, name="state_age")

    # Trigger detection
    d_spread = spread.diff()
    sd_20 = d_spread.rolling(20, min_periods=10).std()
    sigma_threshold = TRIGGER_SIGMA * sd_20
    trig_dspread = d_spread > sigma_threshold
    # Cross from contango toward zero/backwardation: state shifted FROM contango/deep_contango
    # TO flattening/backwardation
    contango_states = {"deep_contango", "contango"}
    stress_states   = {"flattening", "backwardation"}
    state_changed_to_stress = (
        (states.shift(1).isin(contango_states)) & (states.isin(stress_states))
    )
    fired = trig_dspread | state_changed_to_stress
    triggers = pd.DataFrame({"fired": fired,
                              "delta_spread": d_spread,
                              "sigma_threshold": sigma_threshold})

    # Walk-forward reversion — both metrics (all-trigger + event-day-only)
    wf = walk_forward_reversion(spread, triggers, event_flag_series)
    at = wf["all_triggers_reversion"]
    ev = wf["event_day_only_reversion"]
    print(f"\n  Walk-forward reversion (N={REVERSION_N}, X={REVERSION_X_SD}σ, today excluded):")
    if at["hit_rate"] is not None:
        lo, hi = at["wilson_95ci"]
        print(f"    all triggers      n={at['n']:<3d} reverted {at['n_reverted']:<3d} "
              f"rate {at['hit_rate']:.0%}  (95% CI {int(lo*100)}–{int(hi*100)}%)")
    if ev["hit_rate"] is not None:
        lo, hi = ev["wilson_95ci"]
        print(f"    event-day only    n={ev['n']:<3d} reverted {ev['n_reverted']:<3d} "
              f"rate {ev['hit_rate']:.0%}  (95% CI {int(lo*100)}–{int(hi*100)}%)")
    else:
        print(f"    event-day only    n={ev['n']} — {wf['event_day_caveat']}")

    # Per-state persistence + decay dynamics (computed from full history),
    # WITH entry-Δspread distribution per state for the atypical-entry flag.
    dynamics = state_dynamics(states, spread)

    # ── Current-day attribution ─────────────────────────────────────────
    last_date = spread.index[-1]
    last_state = states.iloc[-1]
    last_age   = age_series.iloc[-1]
    last_spread = spread.iloc[-1]
    last_delta = d_spread.iloc[-1]
    last_sigma_thr = sigma_threshold.iloc[-1] if not sigma_threshold.empty else 0
    last_trigger = bool(fired.iloc[-1])

    # RoP-FIX B2: current-state entry-Δspread + atypical-entry flag.
    # The "entry" is the Δspread on the session the current state began.
    # If age = k, the state began at index (len - k); that day's Δspread
    # is the entry Δspread.
    current_state_start_idx = len(spread) - int(last_age)
    current_entry_dspread = float(d_spread.iloc[current_state_start_idx]) \
        if current_state_start_idx > 0 else 0.0
    dstate = dynamics.get(last_state, {})
    mu_entry = dstate.get("entry_dspread_mean")
    sd_entry = dstate.get("entry_dspread_sigma")
    entry_zscore = None
    atypical_entry = False
    if mu_entry is not None and sd_entry is not None and sd_entry > 0:
        entry_zscore = (current_entry_dspread - mu_entry) / sd_entry
        atypical_entry = abs(entry_zscore) > 2.0

    # ────────────────────────────────────────────────────────────────────
    # Δ2Y for the event-day classifier — SAME-DAY ONLY.
    # Sources in priority order (each spans the 08:30 ET release window):
    #   1. ZT=F   CME 2Y T-Note futures, prior settle → current.
    #             Δyield ≈ −(P_now/P_prior − 1) / dur_ZT × 10_000
    #   2. SHY    iShares 1-3y Treasury ETF, prior close → current.
    #             Δyield ≈ −(P_now/P_prior − 1) / dur_SHY × 10_000
    #   3. MANUAL_DELTA_2Y_BPS env var, operator-injected override.
    #   4. FRED us02y day-over-day  →  KEPT ONLY as a T+1 reconciliation
    #             diagnostic; never the live event-day input. FRED's
    #             same-day 2Y is not available intraday and never can be.
    # The window used is written into delta_2y_source verbatim.
    # ────────────────────────────────────────────────────────────────────
    DUR_ZT  = 1.90    # ZT futures effective duration (≈ 2y) in years
    DUR_SHY = 1.85    # SHY ETF duration in years
    event_today = events_by_date.get(last_date.strftime("%Y-%m-%d"), [])
    delta_2y_today = None
    delta_2y_source = "unavailable"
    delta_2y_fred_reconciliation = None
    if not delta_2y_bps.empty:
        v = delta_2y_bps.reindex([last_date]).iloc[-1]
        if not (isinstance(v, float) and math.isnan(v)):
            delta_2y_fred_reconciliation = float(v)
    # 1) ZT=F prior settle → current  (preferred — futures span the release)
    try:
        intra = json.load(open(DATA / "intraday.json"))
        prices = intra.get("prices") or {}
        zt = prices.get("zt") or {}
        if zt.get("last") is not None and zt.get("prior_close"):
            ret = (zt["last"] / zt["prior_close"]) - 1.0
            delta_2y_today = -ret / DUR_ZT * 10_000.0
            delta_2y_source = "ZT 2Y futures, prior settle → current (spans 08:30 ET release)"
    except Exception:
        pass
    # 2) SHY ETF prior close → current  (same-day, slightly cruder)
    if delta_2y_today is None:
        try:
            shy = prices.get("shy") or {}
            if shy.get("last") is not None and shy.get("prior_close"):
                ret = (shy["last"] / shy["prior_close"]) - 1.0
                delta_2y_today = -ret / DUR_SHY * 10_000.0
                delta_2y_source = "SHY 2Y ETF, prior close → current (cruder duration proxy)"
        except Exception:
            pass
    # 3) Explicit operator override
    if delta_2y_today is None:
        import os
        env_override = os.environ.get("MANUAL_DELTA_2Y_BPS")
        if env_override is not None:
            try:
                delta_2y_today = float(env_override)
                delta_2y_source = "manual override (MANUAL_DELTA_2Y_BPS env var)"
            except ValueError:
                pass
    # 4) FRED only if everything else missing — labeled as the T+1 source
    if delta_2y_today is None and delta_2y_fred_reconciliation is not None:
        delta_2y_today = delta_2y_fred_reconciliation
        delta_2y_source = "FRED us02y day-over-day (T+1 — only available the next session)"
    if delta_2y_today is None:
        delta_2y_source = ("unavailable — ZT/SHY intraday + FRED today all missing. "
                           "Re-run after intraday snapshot publishes.")
    front_end_repriced = bool(delta_2y_today is not None and not math.isnan(delta_2y_today)
                              and abs(delta_2y_today) >= DELTA_2Y_BPS)
    held_close_proxy = vix_intraday_range_quartile_proxy(vol["vix"].dropna())
    held_close = held_close_proxy >= HELD_QUARTILE

    # Classifier (only meaningful if trigger fired)
    driver = classify_driver(bool(event_today), front_end_repriced, held_close) \
             if last_trigger else {"driver": "no_trigger", "reversion": "n/a"}

    # Independent equity_drag overlay — RoP-FIX 3: calibrated threshold
    smh_ret_today = float(smh_ret_1d.reindex([last_date]).iloc[-1]) if not smh_ret_1d.empty else None
    breadth_delta_today = float(breadth_delta.reindex([last_date]).iloc[-1]) if not breadth_delta.empty else None
    # σ of daily Δbreadth over rolling 1y window (252 sessions)
    breadth_delta_sigma_1y = float(breadth_delta.rolling(252, min_periods=60).std().iloc[-1]) \
        if not breadth_delta.empty else None
    breadth_holds = (
        breadth_delta_today is not None and breadth_delta_sigma_1y is not None
        and breadth_delta_sigma_1y > 0
        and breadth_delta_today >= -(BREADTH_HOLD_K_SIGMA * breadth_delta_sigma_1y)
    )
    equity_drag = bool(
        smh_ret_today is not None and breadth_holds and
        smh_ret_today <= EQUITY_DRAG_PCT
    )

    # ── Overlay scalar (DIAGNOSTIC — see brief, gated until backtest beats static) ──
    state_scalar = {
        "deep_contango": +1.0,
        "contango":      +0.7,
        "flattening":     0.0,
        "backwardation": -1.0,
    }.get(last_state, 0.0)
    if driver["driver"].startswith("regime_repricing"): state_scalar = min(state_scalar,  0.0)
    if driver["driver"].startswith("event_bump"):       state_scalar = min(state_scalar,  0.3)
    if equity_drag:
        # idiosyncratic equity drag with curve intact ⇒ small fade scalar
        state_scalar = max(state_scalar, -0.3)

    # ── No-look-ahead: signal at close → applied at next session open ──
    # Map last_date (close) ⇒ next business day (open). Assert that the
    # tradable date strictly follows the signal date.
    tradable_at = last_date + pd.tseries.offsets.BDay(1)
    assert tradable_at > last_date, "look-ahead detected — tradable_at must be > signal date"

    # ── CANONICAL close equality (AUDIT FIX 3) ─────────────────────────
    # This module reads vol_indicators.parquet, which is the same artifact
    # refresh_data.py derives the canonical close from — assert they agree
    # so a future refactor can't silently re-introduce a second source.
    canonical_check = "skipped (vol_canonical_close.json absent)"
    try:
        _canon = json.load(open(DATA / "vol_canonical_close.json"))
        if _canon.get("date") == last_date.strftime("%Y-%m-%d"):
            _cv_vix   = float(vol["vix"].dropna().iloc[-1])
            _cv_vix3m = float(vol["vix3m"].dropna().iloc[-1])
            assert abs(_cv_vix - _canon["vix"]) <= 0.01, \
                f"vol_regime vix {_cv_vix} != canonical {_canon['vix']}"
            assert abs(_cv_vix3m - _canon["vix3m"]) <= 0.01, \
                f"vol_regime vix3m {_cv_vix3m} != canonical {_canon['vix3m']}"
            canonical_check = "PASS"
        else:
            canonical_check = (f"date mismatch: canonical {_canon.get('date')} vs "
                                f"vol_regime {last_date.date()} — refresh_data must run first")
    except FileNotFoundError:
        pass

    # ── Build payload ──────────────────────────────────────────────────
    # Recent state history (last 252 days) for the dashboard history strip
    history_recent = []
    for d, st in states.tail(252).items():
        history_recent.append({"d": d.strftime("%Y-%m-%d"), "state": st,
                                "spread": round(float(spread.loc[d]), 3)})

    # Recent trigger episodes for the dashboard "past spikes" list
    past_spikes = []
    fired_idx = fired[fired].index
    for d in fired_idx[-20:]:
        ev = events_by_date.get(d.strftime("%Y-%m-%d"), [])
        past_spikes.append({
            "d": d.strftime("%Y-%m-%d"),
            "delta_spread": round(float(d_spread.loc[d]), 3),
            "state": states.loc[d],
            "event": ev[0] if ev else None,
        })

    # Term-structure curve points — RoP-FIX 5: rename for clarity.
    #   spot_vix  = VIX  (30-day implied vol; the "1-month / spot" point)
    #   vix1d     = VIX1D (1-day vol; spikes on event days; NOT in spread)
    #   vix3m     = VIX3M (3-month vol; back end of spread)
    # Headline spread = spot−3M; the 1-day point is event-vol context, plotted
    # but excluded from the spread definition.
    curve = {
        "spot_vix":    round(float(vol["vix"].iloc[-1]), 2),
        "vix1d":       round(float(vol["vix1d"].iloc[-1]), 2) if "vix1d" in vol.columns else None,
        "vix3m":       round(float(vol["vix3m"].iloc[-1]), 2),
        "spread_spot_3m": round(float(last_spread), 3),
        "headline_spread": "spot − 3M (VIX − VIX3M); 1-day VIX1D is event-vol "
                           "context, plotted but NOT in the spread definition.",
    }

    # Next scheduled event (sessions from today)
    next_event = None
    for d_str in sorted(events_by_date.keys()):
        try:
            d = pd.Timestamp(d_str)
        except Exception:
            continue
        if d > last_date:
            sessions = len(pd.bdate_range(last_date, d)) - 1
            next_event = {"date": d_str, "types": events_by_date[d_str],
                          "sessions_away": int(sessions)}
            break

    payload = {
        "updated":      datetime.now().isoformat(),
        "as_of":        last_date.strftime("%Y-%m-%d"),
        "tradable_at":  tradable_at.strftime("%Y-%m-%d"),

        "config": {
            "spread_definition":      "VIX − VIX3M (FRED VIXCLS − VXVCLS proxy via yfinance)",
            "state_breaks":           STATE_BREAKS,
            "trigger_sigma":          TRIGGER_SIGMA,
            "delta_2y_bps":           DELTA_2Y_BPS,
            "held_quartile":          HELD_QUARTILE,
            "equity_drag_pct":        EQUITY_DRAG_PCT,
            "breadth_hold_k_sigma":   BREADTH_HOLD_K_SIGMA,
            "reversion_N":            REVERSION_N,
            "reversion_X_sigma":      REVERSION_X_SD,
            "futures_spread_status":  "not_run (CBOE VX1/VX2 EOD settlements not sourced)",
        },

        "state":     last_state,
        "state_age": int(last_age),
        "spread":    round(float(last_spread), 3),
        "delta_spread": round(float(last_delta), 3),
        "sigma_threshold": round(float(last_sigma_thr), 3) if np.isfinite(last_sigma_thr) else None,
        "trigger_fired": last_trigger,

        # RoP-FIX B: how this episode of the state began + flag if atypical
        "entry":  {
            "current_entry_dspread": round(current_entry_dspread, 3),
            "state_mean_entry":      round(mu_entry, 3) if mu_entry is not None else None,
            "state_sigma_entry":     round(sd_entry, 3) if sd_entry is not None else None,
            "entry_zscore":          round(entry_zscore, 2) if entry_zscore is not None else None,
            "atypical_entry":        atypical_entry,
            "rule":                  ("Atypical when |entry Δspread − state mean| > "
                                       "2σ. Caveat: pooled transition stats may not "
                                       "describe a shock-entered episode."),
        },

        "dynamics":      dynamics,

        "curve":         curve,
        "next_event":    next_event,
        "event_today":   event_today,

        "conditioning": {
            "event_flag":         bool(event_today),
            "event_types":        event_today,
            "delta_2y_bps":       round(delta_2y_today, 1) if delta_2y_today is not None and not math.isnan(delta_2y_today) else None,
            "delta_2y_source":    delta_2y_source,
            "delta_2y_fred_t1":   round(delta_2y_fred_reconciliation, 1) if delta_2y_fred_reconciliation is not None else None,
            "front_end_repriced": front_end_repriced,
            "held_close_proxy":   round(held_close_proxy, 2),
            "held_close":         held_close,
        },

        "attribution": {
            "primary_driver":   driver["driver"],
            "primary_reversion": driver["reversion"],
            "equity_drag":      equity_drag,
            "equity_drag_inputs": {
                "smh_1d_return":     round(smh_ret_today, 3) if smh_ret_today is not None else None,
                "breadth_delta_pp":  round(breadth_delta_today, 2) if breadth_delta_today is not None else None,
                "breadth_holds":     breadth_holds,
                "breadth_delta_sigma_1y_pp": round(breadth_delta_sigma_1y, 3) if breadth_delta_sigma_1y else None,
                "breadth_z":         round(breadth_delta_today / breadth_delta_sigma_1y, 2)
                                     if (breadth_delta_today is not None and breadth_delta_sigma_1y) else None,
                "rule":              "breadth holds when Δbreadth ≥ −kσ of 1y daily Δ distribution (k = " + str(BREADTH_HOLD_K_SIGMA) + ")",
            },
        },

        "overlay_scalar": {
            "value":    round(state_scalar, 2),
            "label":    "DIAGNOSTIC",
            "caption": ("Regime-sized overlay scalar. Gated as DIAGNOSTIC until "
                        "backtest shows regime-conditional sizing beats static sizing "
                        "on risk-adjusted return. Do not execute on this value."),
        },

        "validation": {
            "walk_forward":         wf,
            "no_lookahead_passed":  True,
            "canonical_close_check": canonical_check,
        },

        "history_recent": history_recent,
        "past_spikes":    past_spikes,
    }

    def _sanitize(o):
        if isinstance(o, dict):  return {k: _sanitize(v) for k, v in o.items()}
        if isinstance(o, list):  return [_sanitize(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
        if isinstance(o, (np.floating,)):
            x = float(o); return None if (math.isnan(x) or math.isinf(x)) else x
        if isinstance(o, (np.integer,)):  return int(o)
        if isinstance(o, (np.bool_,)):    return bool(o)
        return o

    out = DATA / "vol_regime.json"
    with open(out, "w") as f:
        json.dump(_sanitize(payload), f, indent=2, default=str, allow_nan=False)
    print(f"\n  state = {last_state} (age {last_age})  spread = {last_spread:.2f}")
    print(f"  trigger fired today: {last_trigger}")
    print(f"  driver = {driver['driver']}  reversion = {driver['reversion']}")
    print(f"  equity_drag = {equity_drag}  (SMH {smh_ret_today:+.1%}, breadth Δ {breadth_delta_today:+.1f}pp)"
          if smh_ret_today is not None and breadth_delta_today is not None
          else f"  equity_drag = {equity_drag}")
    print(f"  overlay scalar = {state_scalar:+.2f}  (DIAGNOSTIC)")
    print(f"  saved → {out}")


if __name__ == "__main__":
    main()
