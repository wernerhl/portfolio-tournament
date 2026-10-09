#!/usr/bin/env python3
"""
strat_holdings.py — the holdings of the STRATIFIED paper tier (6_strat; execution order of 8 October 2026, J6).

The candidate-list score failed its registered test (data/analyst/candidate_list_test_registration.json, result
data/analyst/candidate_list_test_result.json, 8 October 2026). The owner keeps a live record of it anyway, apart
from the four tiers. This script computes, for one month-end, the top tenth of that month's S&P 500 members with
prices and fundamentals by the registered score — the 43 variables, the mean of the within-month percentile ranks
of the ridge (penalty 100, features and target ranked) and the harness's boosted tree, refitted each January on
month-ends whose 12-month outcome ended before that year — and writes

    data/tournament/strat_holdings/<month_end>.json

ONCE. An existing file is never rewritten (the script says so and exits 0). The score comes from the registered
code path itself (candidate_list_test.fit_scores on walkforward_test.build_table), with walkforward_test.TEST_YEARS
restricted to the month-end's year so only the model that year uses is fitted (January of that year; training
month-ends from June 2010 whose 12-month outcome ended before the year).

The nightly runs it before compute_nav.py every session: the target month-end is the latest quarter-end month-end
at or before the publish session (March, June, September, December), so on every other night the file already
exists and nothing is computed. When the extended panel does not yet cover the month-end (the panel is rebuilt by
the analyst chain fetch_history -> build_panel -> features_ext, not by the nightly), the script exits 2 with a clear
line and writes nothing; compute_nav holds the previous holdings until the file appears.

Usage:  python scripts/analyst/strat_holdings.py [--month-end 2026-09-30] [--out-dir DIR] [--dry-run] [--any-month]
Exit codes: 0 written or already present; 2 the panel does not cover the month-end; 1 any other error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
REPO = HERE.parent.parent
AN = REPO / "data" / "analyst"
REG = AN / "candidate_list_test_registration.json"
OUT_DIR = REPO / "data" / "tournament" / "strat_holdings"
TIER_ID = "6_strat"
LABEL = "paper tier · DIAGNOSTIC · its registered test failed on 8 October 2026"
WEIGHTS = "equal weights, fully invested, no regime cash"
TOP_SHARE = 0.10
RIDGE_PENALTY = 100.0
QUARTER_MONTHS = (3, 6, 9, 12)


def log(m: str) -> None:
    print(f"[strat_holdings] {m}", flush=True)


def registration_record(path: Path = REG) -> dict:
    """The registration's path (relative to the repository) and the sha256 of its bytes — computed, never typed."""
    return {"path": str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def latest_quarter_end_month_end(session: str) -> str:
    """The last calendar month-end of a quarter-end month at or before `session` (YYYY-MM-DD)."""
    d = pd.Timestamp(session)
    p = d.to_period("M")
    while p.month not in QUARTER_MONTHS or p.to_timestamp("M").normalize() > d.normalize():
        p = p - 1
    return str(p.to_timestamp("M").date())


def publish_session() -> str:
    """The session the nightly is publishing (PUBLISH_SESSION from update_daily's run guard), else the last completed one."""
    s = os.environ.get("PUBLISH_SESSION")
    if s:
        return s[:10]
    from trading_calendar import last_completed_session
    return last_completed_session()


def holdings_path(month_end: str, out_dir: Path = OUT_DIR) -> Path:
    return Path(out_dir) / f"{month_end}.json"


def write_once(payload: dict, month_end: str, out_dir: Path = OUT_DIR) -> Path:
    """Write the holdings file for `month_end` once. A file that exists is left untouched: FileExistsError."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    p = holdings_path(month_end, out_dir)
    if p.exists():
        raise FileExistsError(f"{p} exists; holdings files are immutable (written once, never rewritten)")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str))
    os.replace(tmp, p)
    return p


def build_payload(month_end: str, ranked: list[dict], n_scored: int, model: dict, table: dict, registration: dict,
                  written_at: str | None = None) -> dict:
    """The file's content: names in rank order with the score, the count scored, the model's training window, the
    registration and its sha256, the tier's label and the weighting rule."""
    k = len(ranked)
    return {
        "cadence": "static",
        "as_of": month_end,
        "tier": TIER_ID,
        "name": "STRATIFIED",
        "label": LABEL,
        "month_end": month_end,
        "weights": WEIGHTS,
        "rule": ("the top tenth of the month-end's S&P 500 members with prices and fundamentals by the registered score "
                 "(43 variables; the mean of the within-month percentile ranks of the ridge with penalty 100 and the "
                 "harness's boosted tree)"),
        "count_scored": int(n_scored),
        "top_share": TOP_SHARE,
        "count_selected": k,
        "names": ranked,
        "model": model,
        "table": table,
        "registration": registration,
        "immutable": "written once by scripts/analyst/strat_holdings.py; never rewritten",
        "written_at": written_at or datetime.now().isoformat(timespec="seconds"),
    }


def compute_holdings(month_end: str) -> tuple[list[dict], int, dict, dict]:
    """Rank the month-end's cross-section with the registered score. Returns (ranked names, count scored, model record,
    table record). Raises LookupError when the panel does not cover the month-end."""
    import walkforward_test as wf
    import candidate_list_test as cl
    P = pd.Period(month_end, freq="M")
    Y = P.year
    stamp = wf.latest_stamp()
    T, info = wf.build_table(stamp, shift_analyst=0, hold_delisted=True, ext=True)
    T = T[T["has_fund"].fillna(False)].copy()                                   # members with prices AND fundamentals
    feats = [v + "_rk" for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS if v + "_rk" in T.columns]
    if not (T["p"] == P).any():
        raise LookupError(f"the extended panel has no {month_end} rows for members with fundamentals "
                          f"(table ends {info.get('last')}); rebuild the panel (fetch_history -> build_panel -> features_ext) first")
    train_from = cl.TRAIN_FROM["ext43"]
    saved = wf.TEST_YEARS
    try:
        wf.TEST_YEARS = [Y]                                                     # the model this year uses, nothing else
        col = cl.fit_scores(T, feats, "fwd12_x", train_from, RIDGE_PENALTY, f"strat_{Y}")
    finally:
        wf.TEST_YEARS = saved
    # the training window, exactly as walkforward_test.walk_forward selects it
    cutoff = pd.Period(f"{Y - 1}-12", freq="M") - 12
    Tt = T[T["p"] >= pd.Period(train_from, freq="M")]
    tr = Tt[(Tt["p"] <= cutoff) & Tt["fwd12"].notna() & Tt["fwd12_x"].notna()]
    cross = T[(T["p"] == P) & T[col].notna()]
    n = int(len(cross))
    if n == 0:
        raise LookupError(f"no member of {month_end} received a score (training rows {len(tr)}; the walk-forward needs 500)")
    k = max(int(round(n * TOP_SHARE)), 1)
    cross = cross.sort_values([col, "ticker"], ascending=[False, True]).reset_index(drop=True)
    rcol, gcol = f"score_cl_ridge_strat_{Y}", f"score_cl_gbm_strat_{Y}"
    ranked = [{"ticker": str(r["ticker"]), "rank": i + 1, "score": round(float(r[col]), 6),
               "ridge_prediction": round(float(r[rcol]), 6) if rcol in cross.columns and pd.notna(r[rcol]) else None,
               "tree_prediction": round(float(r[gcol]), 6) if gcol in cross.columns and pd.notna(r[gcol]) else None}
              for i, r in cross.head(k).iterrows()]
    model = {
        "fitted": f"{Y}-01",
        "test_year": Y,
        "retrain_rule": "each January on month-ends whose 12-month outcome ended before the test year (walkforward_test.walk_forward)",
        "training_window": {"first_month_end": str(tr["p"].min().to_timestamp("M").date()) if len(tr) else None,
                            "last_month_end": str(tr["p"].max().to_timestamp("M").date()) if len(tr) else None,
                            "cutoff_month": str(cutoff), "rows": int(len(tr)), "train_from": train_from},
        "features": len(feats),
        "ridge": {"penalty": RIDGE_PENALTY, "ranked_features_and_target": True},
        "boosted_tree": "walkforward_test.gbm_fit (sklearn HistGradientBoostingRegressor, frozen)",
        "score": "the mean of the within-month percentile ranks of the two predictions (candidate_list_test.fit_scores)",
        "target": "the within-month percentile rank of the 12-month return",
    }
    table = {"raw_stamp": stamp, **{k_: v for k_, v in info.items() if k_ != "options"}, "options": info.get("options"),
             "filter": "has_fund (members with fundamentals)"}
    return ranked, n, model, table


def main() -> int:
    ap = argparse.ArgumentParser(description="the STRATIFIED paper tier's holdings for one month-end (written once)")
    ap.add_argument("--month-end", default=None, help="YYYY-MM-DD (default: the latest quarter-end month-end at or before the publish session)")
    ap.add_argument("--out-dir", default=str(OUT_DIR), help="holdings directory (a dry run elsewhere: never under data/)")
    ap.add_argument("--dry-run", action="store_true", help="compute and print; write nothing")
    ap.add_argument("--any-month", action="store_true", help="allow a month-end that is not a quarter-end")
    a = ap.parse_args()
    month_end = a.month_end or latest_quarter_end_month_end(publish_session())
    me = pd.Timestamp(month_end)
    if me != me.to_period("M").to_timestamp("M").normalize():
        log(f"{month_end} is not a calendar month-end"); return 1
    if me.month not in QUARTER_MONTHS and not a.any_month:
        log(f"{month_end} is not a quarter-end month-end (March, June, September, December); pass --any-month to override"); return 1
    out_dir = Path(a.out_dir)
    p = holdings_path(month_end, out_dir)
    if p.exists() and not a.dry_run:
        log(f"{p.relative_to(REPO) if p.is_relative_to(REPO) else p} exists; holdings files are immutable — nothing written"); return 0
    reg = registration_record()
    log(f"month-end {month_end}; registration {reg['path']} sha256 {reg['sha256'][:16]}…")
    try:
        ranked, n, model, table = compute_holdings(month_end)
    except LookupError as e:
        log(f"NOT WRITTEN: {e}"); return 2
    payload = build_payload(month_end, ranked, n, model, table, reg)
    tw = model["training_window"]
    log(f"{n} members scored; top tenth = {len(ranked)} names; model fitted {model['fitted']} on {tw['rows']} month-end rows "
        f"{tw['first_month_end']} to {tw['last_month_end']}")
    log("names: " + ", ".join(f"{r['rank']}.{r['ticker']} {r['score']:.3f}" for r in ranked))
    if a.dry_run:
        log("dry run: nothing written"); return 0
    try:
        written = write_once(payload, month_end, out_dir)
    except FileExistsError as e:
        log(str(e)); return 0
    log(f"wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
