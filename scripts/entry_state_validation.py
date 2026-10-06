#!/usr/bin/env python3
"""
entry_state_validation.py — the registered validation of the entry-state indicator
(Execution Order: Entry-State Indicator, 2 October 2026, section 3; E4/E5).

Everything it does is fixed in advance by data/entry_state_validation_registration.json
(reports/entry_state_validation_registration_2026-10-02.md); this script reads those parameters and refuses to
run if the rules file no longer matches the sha256 registered beside them.

    .venv/bin/python scripts/entry_state_validation.py --stage power   # SETUP_ONLY vs BASELINE, reported first
    .venv/bin/python scripts/entry_state_validation.py --stage ready   # READY vs BASELINE; needs the committed power check
    (--registration selects the registration; default v2. A registration superseded by a later one is refused.)

Stages (output paths from the registration's "artifacts"):
  power  → the power-check JSON (v1: data/entry_state_power_check.json; v2: data/entry_state_power_check_v2.json)
  ready  → data/entry_state_validation.json (verdict PASS / FAIL / NO VERDICT, with full distributions)

Pairing: v1 "common cells" (entry month, ticker), superseded because a later entry in the same month conditions the
month-start baseline on a pullback after its entry; v2 "common names, joint months": both contestants restricted to
their common tickers, every entry counted, the months resampled jointly.

Price history: yfinance daily OHLC (auto_adjust=False) from the registered start, fetched once into the
git-ignored scratch/entry_validation/ohlc.parquet; its sha256 and fetch time go into every result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = HERE.parent
DATA = REPO / "data"
REG_DEFAULT = DATA / "entry_state_validation_registration_v2.json"
CACHE = REPO / "scratch" / "entry_validation"
PRICES = CACHE / "ohlc.parquet"
QS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]


def log(m: str) -> None:
    print(f"[entry_state_validation] {m}", flush=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── prices ────────────────────────────────────────────────────────────────────────────────────
def fetch_history(tickers: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf
    CACHE.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i + 50]
        for attempt in range(3):
            try:
                d = yf.download(batch, start=start, progress=False, auto_adjust=False, group_by="ticker", threads=True)
                break
            except Exception as e:  # noqa: BLE001
                log(f"batch {i} attempt {attempt + 1}: {type(e).__name__}: {e}"); time.sleep(5)
        else:
            continue
        for tk in batch:
            try:
                x = d[tk] if isinstance(d.columns, pd.MultiIndex) else d
            except KeyError:
                continue
            x = x.rename(columns=str.lower).rename(columns={"adj close": "adj_close"})
            x = x[["open", "high", "low", "close", "adj_close"]].dropna(subset=["close"])
            if len(x):
                x.index = pd.to_datetime(x.index).tz_localize(None)
                x = x.copy(); x["ticker"] = tk
                frames.append(x)
        log(f"fetched {min(i + 50, len(tickers))}/{len(tickers)}")
    out = pd.concat(frames).sort_index()
    out.index.name = "date"
    out.to_parquet(PRICES)
    (CACHE / "fetched_at.txt").write_text(datetime.now().astimezone().isoformat(timespec="seconds"))
    return out


def load_history(reg: dict, refetch: bool) -> tuple[pd.DataFrame, dict]:
    tickers = sorted(set(reg["universe"]["tickers"]) | {"SPY"})
    if refetch or not PRICES.exists():
        log(f"fetching {len(tickers)} tickers from {reg['window']['history_from']} into {PRICES.relative_to(REPO)}")
        fetch_history(tickers, reg["window"]["history_from"])
    px = pd.read_parquet(PRICES)
    meta = {"path": str(PRICES.relative_to(REPO)), "sha256": sha(PRICES),
            "fetched_at": (CACHE / "fetched_at.txt").read_text().strip() if (CACHE / "fetched_at.txt").exists() else None,
            "tickers_with_data": int(px["ticker"].nunique()), "first": str(px.index.min().date()), "last": str(px.index.max().date()),
            "missing_tickers": sorted(set(reg["universe"]["tickers"]) - set(px["ticker"].unique()))}
    return px, meta


# ── per-ticker states and entries ─────────────────────────────────────────────────────────────
def _one(args):
    tk, df, cfg_, reg_ = args
    import entry_state_v1 as es        # the 2-Oct rules (version 1, frozen); the registrations reference them
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if len(df) < 300:
        return tk, None
    ind = es.indicators(df, cfg_)
    ev = es.evaluate(ind, cfg_, None, None)
    f = (df["adj_close"] / df["close"]).astype(float)
    return tk, {
        "dates": df.index.to_numpy(),
        "open_adj": (df["open"] * f).to_numpy(float), "low_adj": (df["low"] * f).to_numpy(float),
        "close_adj": df["adj_close"].to_numpy(float), "close": df["close"].to_numpy(float),
        "state": ev["state"].to_numpy(object), "armed_stop": pd.to_numeric(ev["armed_stop"], errors="coerce").to_numpy(float),
        "stop": ind["stop"].to_numpy(float), "trend": ind["trend"].to_numpy(bool), "complete": ind["complete"].to_numpy(bool),
    }


def entries(series: dict, spy: pd.DataFrame, reg: dict) -> pd.DataFrame:
    """All entries of the three contestants with their metrics."""
    h_short, h_long = reg["execution"]["horizons"]
    gap = int(reg["deoverlap_sessions"])
    cost = 2 * reg["costs"]["one_way_bps"] / 10000.0
    start = pd.Timestamp(reg["window"]["entries_from"])
    spy_open = spy["open_adj"]; spy_close = spy["close_adj"]
    rows = []
    for tk, s in series.items():
        if s is None or tk == "SPY":
            continue
        d, st, n = s["dates"], s["state"], len(s["dates"])
        di = pd.DatetimeIndex(d); months = (di.year * 12 + di.month).to_numpy()
        sig = {
            "READY": [t for t in range(n - 1) if st[t] in ("READY", "READY-HALF")],
            "SETUP_ONLY": [t for t in range(1, n - 1) if st[t] == "WATCH" and st[t - 1] != "WATCH"],
            "BASELINE": [t for t in range(n - 1) if months[t + 1] != months[t] and s["complete"][t] and s["trend"][t]],
        }
        for name, ts in sig.items():
            last = -10 ** 9
            for t in ts:
                if pd.Timestamp(d[t + 1]) < start or t - last < gap:
                    continue
                e = s["open_adj"][t + 1]
                if not (e > 0) or np.isnan(e):
                    continue
                last = t
                stop = s["armed_stop"][t] if name == "READY" else s["stop"][t]
                d_in = pd.Timestamp(d[t + 1])
                if d_in not in spy_open.index:
                    continue
                es_ = spy_open.loc[d_in]
                rec = {"contestant": name, "ticker": tk, "signal_date": pd.Timestamp(d[t]), "entry_date": d_in,
                       "X20": np.nan, "X60": np.nan, "MAE20": np.nan, "STOP20": np.nan}
                for hh, key in ((h_short, "X20"), (h_long, "X60")):
                    if t + hh < n:
                        dx = pd.Timestamp(d[t + hh])
                        if dx in spy_close.index:
                            rec[key] = (s["close_adj"][t + hh] / e - 1) - (spy_close.loc[dx] / es_ - 1) - cost
                if t + h_short < n:
                    lows = s["low_adj"][t + 1:t + h_short + 1]
                    rec["MAE20"] = max(0.0, -(np.nanmin(lows) / e - 1))
                    closes = s["close"][t + 1:t + h_short + 1]
                    rec["STOP20"] = float(np.any(closes < stop)) if not np.isnan(stop) else np.nan
                rows.append(rec)
    out = pd.DataFrame(rows)
    out["month"] = out["entry_date"].dt.to_period("M").astype(str)
    return out


# ── paired statistics and the month-block bootstrap ───────────────────────────────────────────
def wmedian(v_sorted: np.ndarray, w_sorted: np.ndarray) -> float:
    """Median of the sample in which value v_sorted[i] appears w_sorted[i] times (integer weights)."""
    cw = np.cumsum(w_sorted); tot = cw[-1]
    if tot == 0:
        return float("nan")
    lo = np.searchsorted(cw, (tot + 1) // 2)            # the ((tot+1)//2)-th element (1-based)
    if tot % 2:
        return float(v_sorted[lo])
    hi = np.searchsorted(cw, tot // 2 + 1)
    return float((v_sorted[lo] + v_sorted[hi]) / 2)


def paired(ent: pd.DataFrame, a: str, b: str, reg: dict) -> dict:
    cells = ent.groupby(["contestant", "month", "ticker"])[["X20", "X60", "MAE20", "STOP20"]].mean()
    A, B = cells.loc[a], cells.loc[b]
    common = A.index.intersection(B.index)
    A, B = A.loc[common], B.loc[common]
    months_all = sorted(set(m for m, _ in common))
    rng = np.random.default_rng(int(reg["bootstrap"]["seed"]))
    nb = int(reg["bootstrap"]["resamples"])
    M = len(months_all); midx = {m: i for i, m in enumerate(months_all)}
    draws = rng.integers(0, M, size=(nb, M))
    W = np.zeros((nb, M), dtype=np.int64)
    for r in range(nb):
        W[r] = np.bincount(draws[r], minlength=M)
    out = {"pair": f"{a} vs {b}", "common_cells": int(len(common)), "months": M}

    def stat_mean(key):
        ok = A[key].notna().to_numpy() & B[key].notna().to_numpy()
        diff = (A[key] - B[key]).to_numpy()[ok]
        mi = np.array([midx[m] for m, _ in common])[ok]
        sums = np.bincount(mi, weights=diff, minlength=M); cnt = np.bincount(mi, minlength=M).astype(float)
        boot = (W @ sums) / np.where(W @ cnt == 0, np.nan, W @ cnt)
        med_pt = float(np.median(diff)) if len(diff) else float("nan")
        return {"n_cells": int(ok.sum()), "point": float(diff.mean()) if len(diff) else float("nan"), "median_of_differences": med_pt,
                "ci90": [float(np.nanpercentile(boot, 5)), float(np.nanpercentile(boot, 95))],
                "boot_percentiles": {str(q): float(np.nanpercentile(boot, q * 100)) for q in QS}}

    def stat_median_diff(key):
        ok = A[key].notna().to_numpy() & B[key].notna().to_numpy()
        va, vb = A[key].to_numpy()[ok], B[key].to_numpy()[ok]
        mi = np.array([midx[m] for m, _ in common])[ok]
        oa, ob = np.argsort(va, kind="stable"), np.argsort(vb, kind="stable")
        va_s, vb_s, ma_s, mb_s = va[oa], vb[ob], mi[oa], mi[ob]
        boot = np.empty(nb)
        for r in range(nb):
            w = W[r]
            boot[r] = wmedian(va_s, w[ma_s]) - wmedian(vb_s, w[mb_s])
        pt = float(np.median(va) - np.median(vb)) if len(va) else float("nan")
        return {"n_cells": int(ok.sum()), "point": pt, "median_contestant": float(np.median(va)), "median_baseline": float(np.median(vb)),
                "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
                "boot_percentiles": {str(q): float(np.percentile(boot, q * 100)) for q in QS}}

    out["dMAE"] = stat_median_diff("MAE20")
    out["dX60"] = stat_mean("X60")
    out["dX20"] = stat_mean("X20")
    out["dSTOP20"] = stat_mean("STOP20")
    out["dX60_median_of_medians"] = stat_median_diff("X60")
    lo, hi = out["dMAE"]["ci90"]; lx, hx = out["dX60"]["ci90"]
    out["rule"] = {"dMAE_interval_below_zero": bool(hi < 0), "dX60_lower_bound_at_least_minus_1pt": bool(lx >= -0.010),
                   "passes": bool(hi < 0 and lx >= -0.010),
                   "dMAE_excludes_zero": "below" if hi < 0 else "above" if lo > 0 else "no"}
    out["resolution"] = {"dMAE_half_width": float((hi - lo) / 2), "dX60_half_width": float((hx - lx) / 2)}
    return out


def paired_names(ent: pd.DataFrame, a: str, b: str, reg: dict) -> dict:
    """v2: both contestants on their common tickers, every entry counted; the entry months are resampled jointly
    (each drawn month brings all entries of both contestants), so the two share every resampled history."""
    A, B = ent[ent["contestant"] == a], ent[ent["contestant"] == b]
    names = sorted(set(A["ticker"]) & set(B["ticker"]))
    A, B = A[A["ticker"].isin(names)], B[B["ticker"].isin(names)]
    months_all = sorted(set(A["month"]) | set(B["month"]))
    M = len(months_all); midx = {m: i for i, m in enumerate(months_all)}
    rng = np.random.default_rng(int(reg["bootstrap"]["seed"]))
    nb = int(reg["bootstrap"]["resamples"])
    draws = rng.integers(0, M, size=(nb, M))
    W = np.zeros((nb, M), dtype=np.int64)
    for r in range(nb):
        W[r] = np.bincount(draws[r], minlength=M)
    out = {"pair": f"{a} vs {b}", "construction": "common names, joint month blocks", "common_names": len(names),
           "entries_contestant": int(len(A)), "entries_baseline": int(len(B)), "months": M}

    def arrays(X, key):
        x = X[["month", key]].dropna()
        return x[key].to_numpy(float), np.array([midx[m] for m in x["month"]])

    def mean_diff(key):
        va, ma = arrays(A, key); vb, mb = arrays(B, key)
        sa, ca = np.bincount(ma, weights=va, minlength=M), np.bincount(ma, minlength=M).astype(float)
        sb, cb = np.bincount(mb, weights=vb, minlength=M), np.bincount(mb, minlength=M).astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            boot = (W @ sa) / (W @ ca) - (W @ sb) / (W @ cb)
        return {"n_contestant": int(len(va)), "n_baseline": int(len(vb)), "point": float(va.mean() - vb.mean()),
                "mean_contestant": float(va.mean()), "mean_baseline": float(vb.mean()),
                "ci90": [float(np.nanpercentile(boot, 5)), float(np.nanpercentile(boot, 95))],
                "boot_percentiles": {str(q): float(np.nanpercentile(boot, q * 100)) for q in QS}}

    def median_diff(key):
        va, ma = arrays(A, key); vb, mb = arrays(B, key)
        oa, ob = np.argsort(va, kind="stable"), np.argsort(vb, kind="stable")
        va_s, vb_s, ma_s, mb_s = va[oa], vb[ob], ma[oa], mb[ob]
        boot = np.empty(nb)
        for r in range(nb):
            w = W[r]
            boot[r] = wmedian(va_s, w[ma_s]) - wmedian(vb_s, w[mb_s])
        return {"n_contestant": int(len(va)), "n_baseline": int(len(vb)), "point": float(np.median(va) - np.median(vb)),
                "median_contestant": float(np.median(va)), "median_baseline": float(np.median(vb)),
                "ci90": [float(np.nanpercentile(boot, 5)), float(np.nanpercentile(boot, 95))],
                "boot_percentiles": {str(q): float(np.nanpercentile(boot, q * 100)) for q in QS}}

    out["dMAE"] = median_diff("MAE20")
    out["dX60"] = mean_diff("X60")
    out["dX20"] = mean_diff("X20")
    out["dSTOP20"] = mean_diff("STOP20")
    out["dX60_median"] = median_diff("X60")
    lo, hi = out["dMAE"]["ci90"]; lx, hx = out["dX60"]["ci90"]
    out["rule"] = {"dMAE_interval_below_zero": bool(hi < 0), "dX60_lower_bound_at_least_minus_1pt": bool(lx >= -0.010),
                   "passes": bool(hi < 0 and lx >= -0.010),
                   "dMAE_excludes_zero": "below" if hi < 0 else "above" if lo > 0 else "no"}
    out["resolution"] = {"dMAE_half_width": float((hi - lo) / 2), "dX60_half_width": float((hx - lx) / 2)}
    return out


def compare(ent: pd.DataFrame, a: str, b: str, reg: dict) -> dict:
    mode = (reg.get("pairing") or {}).get("mode", "common_cells")
    return paired_names(ent, a, b, reg) if mode == "common_names_joint_months" else paired(ent, a, b, reg)


def distributions(ent: pd.DataFrame) -> dict:
    out = {}
    for c, g in ent.groupby("contestant"):
        d = {"entries": int(len(g)), "names": int(g["ticker"].nunique()), "cells": int(g.groupby(["month", "ticker"]).ngroups)}
        for k in ("X20", "X60", "MAE20"):
            x = g[k].dropna()
            d[k] = {"n": int(len(x)), "mean": float(x.mean()), **{f"p{int(q * 100)}": float(x.quantile(q)) for q in QS}}
        d["stopped_share_20"] = float(g["STOP20"].dropna().mean())
        yr = g.assign(year=g["entry_date"].dt.year).groupby("year")
        d["by_year"] = {str(y): {"entries": int(len(v)), "X20_median": float(v["X20"].median()), "X60_median": float(v["X60"].median()),
                                 "X60_mean": float(v["X60"].mean()), "MAE20_median": float(v["MAE20"].median()),
                                 "stopped_share_20": float(v["STOP20"].mean())} for y, v in yr}
        out[c] = d
    return out


def clean(o):
    """NaN/inf to None, recursively (the results are written with allow_nan=False)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if (np.isnan(o) or np.isinf(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


def committed_clean(path: Path) -> bool:
    rel = str(path.relative_to(REPO))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["power", "ready"], required=True)
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--registration", default=str(REG_DEFAULT.relative_to(REPO)))
    a = ap.parse_args()
    REG = REPO / a.registration
    reg = json.loads(REG.read_text())
    POWER_OUT = REPO / reg["artifacts"]["power_check"]
    READY_OUT = REPO / reg["artifacts"]["result"]
    rel = str(REG.relative_to(REPO))
    for other in sorted(DATA.glob("entry_state_validation_registration*.json")):
        if other != REG and (json.loads(other.read_text()).get("supersedes") or {}).get("path") == rel:
            log(f"{rel} is superseded by {other.relative_to(REPO)}: refusing"); return 2
    import entry_state_v1 as es        # the 2-Oct rules (version 1, frozen); the registrations reference them
    cfg_path = DATA / "entry_state_config_2026-10-02.json"     # version 1 (the 6-Oct revision is version 2)
    if sha(cfg_path) != reg["rules_config"]["sha256"]:
        log("the rules file no longer matches the registered sha256: refusing (a change needs a new registration)"); return 2
    if not committed_clean(REG):
        log("the registration is not committed (or has local edits): refusing (registered before any run)"); return 2
    done = POWER_OUT if a.stage == "power" else READY_OUT
    if done.exists() and committed_clean(done) and json.loads(done.read_text()).get("registration", {}).get("path") == rel:
        log(f"{done.relative_to(REPO)} is already committed for this registration: a rerun needs a new registration"); return 2
    if a.stage == "ready":
        if not POWER_OUT.exists() or not committed_clean(POWER_OUT):
            log("the power check must be run, reported and committed before READY is evaluated"); return 2
    cfg = es.load_config()
    px, pmeta = load_history(reg, a.refetch)
    groups = {tk: g.drop(columns=["ticker"]) for tk, g in px.groupby("ticker")}
    log(f"states for {len(groups)} tickers ({a.workers} workers)")
    t0 = time.time()
    with Pool(a.workers) as pool:
        series = dict(pool.map(_one, [(tk, g, cfg, reg) for tk, g in groups.items()], chunksize=4))
    log(f"states done in {time.time() - t0:.0f}s")
    spy = groups["SPY"].sort_index(); f = spy["adj_close"] / spy["close"]
    spy = pd.DataFrame({"open_adj": spy["open"] * f, "close_adj": spy["adj_close"]})
    ent = entries(series, spy, reg)
    log(f"entries: " + ", ".join(f"{k} {v}" for k, v in ent["contestant"].value_counts().items()))
    meta = {"registration": {"path": str(REG.relative_to(REPO)), "sha256": sha(REG)}, "rules_sha256": reg["rules_config"]["sha256"],
            "prices": pmeta, "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "entries_through": str(ent["entry_date"].max().date()), "label": "DIAGNOSTIC"}
    if a.stage == "power":
        res = compare(ent, "SETUP_ONLY", "BASELINE", reg)
        hp = reg["power_check"]
        has_power = res["resolution"]["dMAE_half_width"] <= 0.0025 and res["resolution"]["dX60_half_width"] <= 0.010
        out = {"cadence": "static", "as_of": meta["computed_at"][:10], **meta, "stage": "power check (SETUP_ONLY vs BASELINE)",
               "registration_version": reg.get("version", 1),
               "criterion": hp["has_power"], "has_power": bool(has_power), "result": res,
               "distributions": distributions(ent[ent["contestant"].isin(["SETUP_ONLY", "BASELINE"])])}
        POWER_OUT.write_text(json.dumps(clean(out), indent=1, allow_nan=False, default=str))
        log(f"power check: has_power={has_power}; dMAE {res['dMAE']['point']:+.4f} {res['dMAE']['ci90']}; dX60 {res['dX60']['point']:+.4f} {res['dX60']['ci90']}")
        return 0
    power = json.loads(POWER_OUT.read_text())
    res = compare(ent, "READY", "BASELINE", reg)
    if not power["has_power"]:
        verdict = "NO VERDICT"
    else:
        verdict = "PASS" if res["rule"]["passes"] else "FAIL"
    out = {"cadence": "static", "as_of": meta["computed_at"][:10], **meta, "stage": "READY vs BASELINE",
           "registration_version": reg.get("version", 1),
           "verdict": verdict, "power_check": {"has_power": power["has_power"], "path": str(POWER_OUT.relative_to(REPO))},
           "decision_rule": reg["decision_rule"], "result": res, "distributions": distributions(ent),
           "expected_result": reg["expected_result"]["READY_vs_BASELINE"]}
    READY_OUT.write_text(json.dumps(clean(out), indent=1, allow_nan=False, default=str))
    log(f"READY vs BASELINE: {verdict}; dMAE {res['dMAE']['point']:+.4f} {res['dMAE']['ci90']}; dX60 {res['dX60']['point']:+.4f} {res['dX60']['ci90']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
