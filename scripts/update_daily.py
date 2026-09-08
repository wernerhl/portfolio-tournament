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
    from trading_calendar import is_trading_day, now_et as _now_et, last_completed_session
    now_et = _now_et()          # honors NOW_ET_OVERRIDE for the [2.3] verification
    trading = is_trading_day(now_et.date())
    # SEPT AUDIT [2.3]: a non-trading day is not a failure. Exit 0 with the
    # standard line BEFORE any sub-script runs — nothing written, no
    # failure notification. (Labor Day 2026-09-07 ran the full pipeline,
    # got rejected by validation, and paged as a failure.)
    if not trading and args.force_publish is None:
        print(f"[update_daily] market closed, nothing to do ({now_et:%Y-%m-%d})", flush=True)
        sys.exit(0)
    # Reconciliation memo 8-Sept, decision 3 (mechanics): the guard keys on the
    # SESSION being published, not on the wall-clock date. A run may publish
    # session S when S is the most recent completed trading session and the
    # clock is past S's close + 15 min — regardless of the calendar day. The
    # old pre-close refusal compared against the wall-clock date: a cron
    # throttled past 00:00 UTC (02:02 ET 2026-08-28) saw "Aug 28 pre-close",
    # exited 78, and Aug 27's session was never published. The data layer
    # computes as of S (drop_partial_today; session-labelled rows).
    import os as _os
    S = last_completed_session(now_et)
    _os.environ["PUBLISH_SESSION"] = S
    print(f"[5] RUN GUARD: publishing session {S}  (clock {now_et:%Y-%m-%d %H:%M} ET)", flush=True)
    return args.force_publish, now_et

FORCE_REASON, NOW_ET = _run_guard()

for script in ([] if "--validate-only" in sys.argv else scripts):   # [8.2] test hook
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
    import os as _os
    if _os.environ.get("FORCE_VALIDATION_FAIL"):   # SEPT AUDIT [8.2] test hook
        errors.append("forced_test_failure: FORCE_VALIDATION_FAIL set")
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

    # The freshness reference is the SESSION the run guard decided to publish
    # (PUBLISH_SESSION, holiday-aware, close+15 min), never a private weekday-
    # only clock. The Labor Day 2026-09-07 run (pre-remediation code) labelled
    # every artifact 2026-09-04 correctly and was then rejected here against
    # "last session 2026-09-07" — a NYSE holiday the old helper did not know.
    from trading_calendar import last_completed_session as _last_completed_session
    session = _os.environ.get("PUBLISH_SESSION") or _last_completed_session()

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

        # SEPT AUDIT [1.3]: the canonical vol close must be the last session's
        # and carry the required fields. refresh_data refuses the write when
        # they're null (previous record retained); this names the assertion
        # in status.json so the failure is legible, not "exit 1".
        cj = json.load(open(DATA / "vol_close_canonical.json"))
        if cj.get("date") != session:
            errors.append(f"canonical_vol_close_stale: canonical date {cj.get('date')} "
                          f"!= last session {session}")
        _miss = [f for f in ("vix", "vix3m", "skew") if cj.get(f) is None]
        if _miss:
            errors.append(f"canonical_vol_close_required_nonnull: {_miss} null for "
                          f"session {cj.get('date')}")
        for f in ("vvix", "vix1d"):
            if cj.get(f) is None and not (cj.get("null_reasons") or {}).get(f):
                errors.append(f"canonical_vol_close_optional_needs_reason: {f} null "
                              f"without a recorded reason")

        # SEPT AUDIT [5.1]: every served JSON declares its date — daily files
        # a session_date, static/on_change/weekly files cadence + as_of.
        for fname, cadence in SERVED_CADENCE.items():
            p3 = DATA / fname
            if not p3.exists():
                continue
            try:
                dj = json.load(open(p3))
            except Exception:
                errors.append(f"served_json_unparseable: {fname}")
                continue
            if not isinstance(dj, dict):
                continue
            if cadence == "daily" and not dj.get("session_date"):
                errors.append(f"served_json_missing_session_date: {fname}")
            if cadence != "daily" and not (dj.get("cadence") and dj.get("as_of")):
                errors.append(f"served_json_missing_cadence_as_of: {fname}")

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
        # SEPT AUDIT [8.1]: the exit carries the failing check identifiers so
        # status.json names them, not "exit 1".
        raise SystemExit("; ".join(errors[:4]) + (f" (+{len(errors)-4} more)" if len(errors) > 4 else ""))
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

# ─────────────────────────────────────────────────────────────────────
# SEPT AUDIT [5.1]: declared dates on EVERY served JSON, in one place.
# Daily files carry session_date (the completed session the pipeline just
# produced); static / on_change / weekly files carry cadence + as_of so a
# stale-badge or audit check can tell "old by design" from "stale". Writers
# that already stamp themselves (intraday, vol_regime, canonical) are left
# as-is; this pass is idempotent and never changes any data field.
# ─────────────────────────────────────────────────────────────────────
SERVED_CADENCE = {
    # daily pipeline outputs → session_date
    "indicator_series.json": "daily", "regime_indicators.json": "daily",
    "thesis_daily.json": "daily", "ticker_indicators.json": "daily",
    "ticker_signals.json": "daily", "tournament.json": "daily",
    "v4_delta_attribution.json": "daily", "regime_conditional_scores.json": "daily",
    "intraday.json": "daily", "vol_regime.json": "daily", "vol_close_canonical.json": "daily",
    # on-change / static artifacts → cadence + as_of
    "thesis_registry.json": "on_change", "thesis_claims.json": "on_change",
    "registry_proposals.json": "on_change", "tier_holdings.json": "on_change",
    "thesis_backtest.json": "on_change", "backtest_metrics.json": "on_change",
    "backtest_drawdown.json": "on_change",                                     # P2.1 companion (dashboard order 9-Sept)
    "v4_calibration.json": "on_change", "v4_scoring_params.json": "on_change",
    "v4_model_results.json": "on_change", "event_calendar.json": "weekly",
    "benchmark_inception.json": "static", "regime_comparison.json": "static",
    "regime_v2_auc.json": "static", "regime_v2_divergence_test.json": "static",
    "vol_canonical_close.json": "static",   # legacy pre-July filename, superseded
}

def stamp_served_json() -> None:
    import subprocess
    from trading_calendar import served_meta, last_trading_session
    session = last_trading_session()
    for fname, cadence in SERVED_CADENCE.items():
        p = DATA / fname
        if not p.exists():
            continue
        try:
            d = json.load(open(p))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if cadence == "daily":
            meta = served_meta("daily", session_date=d.get("session_date") or d.get("as_of") or session)
        else:
            as_of = (d.get("as_of") or d.get("frozen_at") or d.get("generated_at")
                     or d.get("approved_at") or d.get("updated") or "")
            as_of = str(as_of)[:10] if as_of else None
            if not as_of:   # fall back to the file's last git change date
                try:
                    as_of = subprocess.check_output(
                        ["git", "log", "-1", "--format=%ad", "--date=short", "--", str(p)],
                        cwd=ROOT, text=True).strip() or None
                except Exception:
                    as_of = None
            meta = served_meta(cadence, as_of=as_of)
        changed = False
        for k, v in meta.items():
            if k == "computed_at":      # never churn a file only to bump a clock
                continue
            if d.get(k) != v:
                d[k] = v; changed = True
        if fname == "vol_canonical_close.json" and not d.get("superseded_by"):
            d["superseded_by"] = "vol_close_canonical.json"; changed = True
        if changed:
            with open(p, "w") as f:
                json.dump(d, f, indent=2, default=str)
    print("  served-JSON date stamps: OK")

stamp_served_json()

try:
    validate_outputs()
except SystemExit as e:
    # SEPT AUDIT [8.2]: a rejected run writes NOTHING to any served file. The
    # sub-scripts already wrote into data/ before validation ran, so restore
    # every tracked served file to the last good commit and drop untracked
    # run outputs (a rejected run's vintage dir, scratch). ONLY status.json,
    # written below, records the rejection — with the check names ([8.1]).
    import subprocess as _sp
    _sp.run(["git", "checkout", "--", "data/"], cwd=ROOT, check=False)
    _sp.run(["git", "clean", "-fdq", "data/"], cwd=ROOT, check=False)
    _write_status(False, str(e.code) if isinstance(e.code, str) else "validation failed (unnamed)")
    raise
_write_status(True, None)
print("\nDaily update complete.")
