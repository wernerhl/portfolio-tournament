"""Daily pipeline wrapper. Called by GitHub Actions.

Order (v3):
  1. refresh_data.py        — pull latest prices + FRED into data/source/
  2. compute_regime_v2.py   — read source parquets, compute R_lead/R_full + complacency
  3. compute_nav.py         — inception-anchored benchmarks + tier NAVs
  4. build_ticker_data.py   — per-ticker drill-down JSON
  5. build_indicator_series — per-indicator history JSON
  6. compute_signals.py     — per-ticker signals (position vs entry mode)
  7. compute_intraday.py    — best-effort intraday snapshot
  8. validate_outputs()     — fail loud on frozen benchmark / missing TLT nav
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"

scripts = [
    "refresh_data.py",
    "compute_regime_v2.py",
    "score_regime_v4_daily.py",    # AUDIT FIX 2a: v4 was never in the daily
                                   # pipeline (CI lacked scikit-learn), so
                                   # regime_v4_daily.csv froze at its last
                                   # manual run while the headline kept
                                   # quoting it. Light numpy-only scorer —
                                   # bit-compatible isotonic via saved knots;
                                   # full regime_v4_ml.py recalibrates monthly.
    "compute_nav.py",
    "build_ticker_data.py",
    "build_indicator_series.py",
    "compute_signals.py",
    "compute_intraday.py",         # best-effort; OK to fail (yfinance flake)
    "compute_vol_regime.py",       # VIX term-structure regime + attribution
    "compute_conditional_scores.py", # regime-conditional sleeve scores (JS-shrunk)
    "compute_thesis_daily.py",     # MESO layer: thesis exposure + attribution + auto-log
    "build_canonical.py",          # #92 canonical artifact: ONE fundamentals fetch
                                   # for both repos (screener consumes at 23:15 UTC).
                                   # Best-effort by position: a canonical failure never
                                   # blocks the tournament's own outputs above; the
                                   # screener's freshness assert catches staleness.
]

# ─────────────────────────────────────────────────────────────────────
# [5] Run guard (written instruction 2026-07-29): this pipeline writes the
# served close-of-day artifacts, so it may run only after the close
# (>= 16:15 ET) on trading sessions, or under --force-publish REASON.
# The guard refuses BEFORE any sub-script writes — served data stays intact.
# The intraday/market-open bots are intentionally exempt (session-scoped,
# separate workflows). Non-trading days pass (no mid-session hazard).
# ─────────────────────────────────────────────────────────────────────
def _run_guard():
    import argparse
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-publish", metavar="REASON", default=None,
                    help="run despite the session guard; reason recorded in status.json")
    args, _ = ap.parse_known_args()
    now_et = datetime.now(ZoneInfo("America/New_York"))
    try:
        from trading_calendar import is_trading_day
        trading = is_trading_day(now_et.date())
    except Exception:
        trading = now_et.weekday() < 5
    after_close = (now_et.hour, now_et.minute) >= (16, 15)
    if trading and not after_close and args.force_publish is None:
        print(f"[5] RUN GUARD: {now_et:%H:%M} ET is pre-close on a trading session and no "
              "--force-publish REASON was given — refusing to run the publish pipeline. "
              "Nothing was written.")
        sys.exit(78)
    return args.force_publish, now_et

FORCE_REASON, NOW_ET = _run_guard()

for script in scripts:
    print(f"\n{'='*60}\nRunning {script}\n{'='*60}")
    rc = subprocess.call([sys.executable, str(HERE / script)])
    if rc != 0:
        print(f"WARNING: {script} exited with code {rc}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────
# Post-run validation — fail the workflow loudly on the bugs we just fixed.
# These assertions would have caught the silent benchmark freeze and the
# missing TLT NAV the moment they appeared.
# ─────────────────────────────────────────────────────────────────────
def validate_outputs() -> None:
    errors: list[str] = []
    tjson = DATA / "tournament.json"
    if not tjson.exists():
        errors.append("data/tournament.json missing")
    else:
        t = json.load(open(tjson))
        history = t.get("history", [])
        if len(history) > 1:
            last = history[-1]
            bms  = last.get("benchmarks", {}) or {}

            # A1: benchmarks must not be frozen at exactly 100000 after day 1
            for b in ["spy", "qqq", "sso"]:
                nav = (bms.get(b) or {}).get("nav")
                if nav == 100000.0:
                    errors.append(f"BENCHMARK {b} frozen at $100,000 — NAV not computed from price")

            # A2: TLT (with a price) must have a nav
            tlt = bms.get("tlt") or {}
            if tlt.get("price") and "nav" not in tlt:
                errors.append("TLT has price but no nav field")

            # A3: at least one benchmark should differ from start by >0.1% after 2 weeks
            navs = [(bms.get(b) or {}).get("nav") for b in ["spy", "qqq", "sso"]
                    if (bms.get(b) or {}).get("nav") is not None]
            if navs and all(abs(n - 100000) < 100 for n in navs) and len(history) > 5:
                errors.append("All benchmarks within $100 of start across >5 days — likely frozen")

            # A4: 60/40 should be present when both SPY and TLT have NAVs
            if (bms.get("spy") or {}).get("nav") and (bms.get("tlt") or {}).get("nav") and "60_40" not in bms:
                errors.append("60/40 composite missing despite SPY + TLT being available")

    # B1: intraday file freshness (warn only — separate workflow)
    intra = DATA / "intraday.json"
    if not intra.exists():
        print("  note: data/intraday.json absent (intraday workflow may not have run yet)")

    # ── AUDIT FIX 2b: per-file freshness — every published artifact with a
    # date axis must cover the last trading session. The v4 freeze (stuck at
    # 06-02 while the headline kept quoting it) died silently because only
    # intraday.json had a staleness watch.
    from datetime import datetime, timedelta, timezone

    def last_trading_session():
        now = datetime.now(timezone.utc)
        d = now.date()
        # Before ~21:30 UTC a weekday's close data can't exist yet.
        if not (d.weekday() < 5 and now.hour >= 21 and (now.hour > 21 or now.minute >= 30)):
            d = d - timedelta(days=1)
        while d.weekday() >= 5:
            d = d - timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    session = last_trading_session()

    def check_fresh(label, last_date_str):
        if last_date_str is None:
            errors.append(f"FRESHNESS {label}: no date found")
        elif str(last_date_str)[:10] < session:
            errors.append(f"FRESHNESS {label}: max date {str(last_date_str)[:10]} < last session {session}")

    try:
        import pandas as _pd
        t2 = json.load(open(DATA / "tournament.json"))
        check_fresh("tournament.json", t2["history"][-1]["date"] if t2.get("history") else None)
        for csv_name, date_col in [("regime_daily.csv", "date"),
                                    ("regime_v2_daily.csv", "date"),
                                    ("regime_daily_published.csv", "date"),
                                    ("regime_v4_daily.csv", "date")]:
            p = DATA / csv_name
            if not p.exists():
                errors.append(f"FRESHNESS {csv_name}: file missing")
                continue
            df = _pd.read_csv(p)
            col = date_col if date_col in df.columns else df.columns[0]
            check_fresh(csv_name, df[col].dropna().astype(str).max())
        vr = json.load(open(DATA / "vol_regime.json"))
        check_fresh("vol_regime.json", vr.get("as_of"))

        # ── THESIS layer validations ──────────────────────────────────
        td_p = DATA / "thesis_daily.json"
        if td_p.exists():
            td = json.load(open(td_p))
            check_fresh("thesis_daily.json", td.get("as_of"))
            reg = json.load(open(DATA / "thesis_registry.json"))
            if td.get("registry_version") != reg.get("version"):
                errors.append(f"THESIS: thesis_daily registry v{td.get('registry_version')} "
                              f"!= registry file v{reg.get('version')}")
            # Σ thesis weights per name ≤ 1.0
            per_name = {}
            for _t, _th in reg["theses"].items():
                for nm, w in _th["members"].items():
                    per_name[nm] = per_name.get(nm, 0.0) + float(w)
            for nm, tot in per_name.items():
                if tot > 1.0 + 1e-9:
                    errors.append(f"THESIS REGISTRY: {nm} Σweights = {tot:.2f} > 1.0")
            # exposure_total must sum to 1 (every held name maps or counts unclassified)
            for tid, t in td.get("tiers", {}).items():
                s = sum(t.get("exposure_total", {}).values())
                if abs(s - 1.0) > 0.02:
                    errors.append(f"THESIS COVERAGE {tid}: exposure_total sums to {s:.3f} != 1")
            # attribution components must reconstruct active return (≤1bp/day)
            for tid, a in td.get("attribution", {}).items():
                if a.get("check_max_residual_bp", 0) > 1.0:
                    errors.append(f"THESIS ATTRIBUTION {tid}: max daily residual "
                                  f"{a['check_max_residual_bp']}bp > 1bp")
        else:
            errors.append("FRESHNESS thesis_daily.json: file missing")

        # AUDIT FIX 2b, calibrated by diagnosis: the audit proposed "no two
        # consecutive identical rows", but isotonic calibration quantizes
        # every probability column into 8-19 step values, so LEGITIMATE
        # consecutive repeats are pervasive (893 of 5330 historical rows are
        # identical to t-1). The actual freeze symptom is the date axis
        # (covered by the freshness assert above) plus a fully-flat TAIL:
        # assert the trailing 10 rows contain at least 2 distinct
        # probability rows — a constant 10-row run never happens under
        # live inputs but is exactly what frozen features produce.
        v4 = _pd.read_csv(DATA / "regime_v4_daily.csv")
        prob_cols = [c for c in v4.columns if c.startswith("p_")]
        tail = v4[prob_cols].tail(10).reset_index(drop=True)
        if len(tail) >= 10 and all((tail.iloc[i] == tail.iloc[0]).all() for i in range(1, len(tail))):
            errors.append("V4 FLAT TAIL: trailing 10 rows identical across all "
                          "probability columns — frozen-feature symptom")

        # JULY AUDIT FIX 3c: canonical close equality ENFORCED for BOTH
        # consumers — vol_regime.curve AND the post-close intraday snapshot.
        canon_p = DATA / "vol_close_canonical.json"
        if not canon_p.exists():
            canon_p = DATA / "vol_canonical_close.json"
        if canon_p.exists():
            canon = json.load(open(canon_p))
            curve = vr.get("curve", {})
            if canon.get("date") == vr.get("as_of"):
                for k_vr, k_c in [("spot_vix", "vix"), ("vix3m", "vix3m")]:
                    a, b = curve.get(k_vr), canon.get(k_c)
                    if a is not None and b is not None and abs(a - b) > 0.01:
                        errors.append(f"VOL SOURCE SPLIT: vol_regime.curve.{k_vr}={a} "
                                      f"!= canonical.{k_c}={b}")
            # Intraday post-close snapshot must reconcile to canonical
            intra_p = DATA / "intraday.json"
            if intra_p.exists():
                intra = json.load(open(intra_p))
                if intra.get("reconciled_to_canonical") == canon.get("date"):
                    for k_i, k_c in [("vix_now", "vix"), ("vix3m", "vix3m"), ("skew", "skew")]:
                        a, b = intra.get(k_i), canon.get(k_c)
                        if a is not None and b is not None and abs(a - b) > 0.01:
                            errors.append(f"VOL SOURCE SPLIT: intraday.{k_i}={a} "
                                          f"!= canonical.{k_c}={b}")

        # JULY AUDIT FIX 5c: every date in every published time series must be
        # a trading day (shared calendar). Weekday-only before 2025.
        sys.path.insert(0, str(HERE))
        from trading_calendar import is_trading_day
        for csv_name in ["regime_daily.csv", "regime_v2_daily.csv",
                          "regime_daily_published.csv", "regime_v4_daily.csv"]:
            p2 = DATA / csv_name
            if not p2.exists(): continue
            df2 = _pd.read_csv(p2)
            col2 = "date" if "date" in df2.columns else df2.columns[0]
            bad = [d for d in df2[col2].dropna().astype(str)
                   if d >= "2025-01-01" and not is_trading_day(d)]
            if bad:
                errors.append(f"PHANTOM DATES in {csv_name}: {bad[:5]}"
                              f"{' (+' + str(len(bad)-5) + ' more)' if len(bad) > 5 else ''}")
        for h2 in json.load(open(DATA / 'tournament.json')).get("history", []):
            if h2["date"] >= "2025-01-01" and not is_trading_day(h2["date"]):
                errors.append(f"PHANTOM DATE in tournament.json: {h2['date']}")
    except Exception as e:
        errors.append(f"FRESHNESS CHECK CRASHED: {e}")

    if errors:
        print("\n" + "="*60 + "\nVALIDATION FAILED:")
        for e in errors:
            print(f"  -  {e}")
        print("="*60)
        raise SystemExit(1)
    print("\nValidation passed.")


# [5] status.json on BOTH outcomes — the pipeline-level session stamp.
# (Per-artifact session stamps live in the artifacts themselves: thesis_daily
# carries as_of/updated; status.json is the tournament's pipeline equivalent
# of the screener's scores.json session_date/computed_at fields.)
def _write_status(ok: bool, reason) -> None:
    try:
        from trading_calendar import last_trading_session
        session = last_trading_session()
    except Exception:
        session = None
    path = DATA / "status.json"
    prev = {}
    try:
        prev = json.load(open(path))
    except Exception:
        pass
    computed_at = NOW_ET.isoformat(timespec="seconds")
    json.dump({
        "last_attempt": computed_at,
        "last_success": computed_at if ok else prev.get("last_success"),
        "failure_reason": None if ok else str(reason),
        "session_date": session,
        "forced_publish_reason": FORCE_REASON,
    }, open(path, "w"), indent=1)

try:
    validate_outputs()
except SystemExit as e:
    _write_status(False, f"validation failed (exit {e.code})")
    raise
_write_status(True, None)
print("\nDaily update complete.")
