#!/usr/bin/env python3
"""
candidate_list_diagnostic.py — DIAGNOSTIC: how much of the registered candidate-list result is a sector bet
(third follow-up of 7 October 2026, H3). Computed after the registered result was known; no part in any verdict;
changes nothing in the score; not on any page.

On the harness (walkforward_test.py, candidate_list_test.py), with the registered primary score — the 43 variables,
ridge penalty 100 and the boosted tree, mean of the within-month percentile ranks, 12-month horizon, 20 bps a
holding (10 bps a trade both ways), the test months 2014 to 2026 — and the provider's current sector label for each
current symbol (data/analyst/history/sectors_<date>.parquet; today's label applied to every year: Alphabet and Meta
carry Communication Services also before the 2018 reclassification):

  top tenth over the average member            the registered quantity, on the names with a sector label
  sector allocation                            the top tenth's sector weights held at sector-average returns, over
                                               the average member (gross)
  selection within sectors                     the top tenth over the members of its own sector (net of the 20 bps;
                                               allocation + selection = the first row)
  within-sector ranking, over the average      the same score ranked within each sector, the top tenth of each sector
  within-sector ranking, over its own sector
  the within-sector version by halves          2014-2019 and 2020-2025
  the registered version by halves
  the technology share of the top tenth against the members', and the top tenth's mean rank on R&D to sales,
  gross profit to assets and leverage (the [-0.5, 0.5] rank scale)
  the past placebo (every variable from 12 months earlier) for the within-sector version

Output: data/analyst/candidate_list_diagnostic.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import walkforward_test as wf      # noqa: E402
import candidate_list_test as cl   # noqa: E402

REPO = HERE.parent.parent
AN = REPO / "data" / "analyst"
OUT = AN / "candidate_list_diagnostic.json"
COST = 2 * wf.COST_BPS / 1e4           # 20 bps a holding, as the harness charges a 12-month position
TECH = "Technology"
TILT_VARS = {"f_rd_s": "R&D to sales", "f_gpa": "gross profit to assets", "f_lev": "leverage"}


def log(m: str) -> None:
    print(f"[candidate_list_diagnostic] {m}", flush=True)


def nw(series: list[float]) -> dict:
    mu, t, n = wf.newey_west_t(np.asarray(series, dtype=float), 11)
    return {"pts_per_year": round(mu * 100, 2), "t_nw": round(t, 2), "months": n, "lags": 11}


def sector_labels() -> tuple[dict, str]:
    files = sorted((AN / "history").glob("sectors_*.parquet"))
    if not files:
        raise SystemExit("no sectors_<date>.parquet in data/analyst/history (scripts/analyst/fetch_sectors.py)")
    s = pd.read_parquet(files[-1])
    return {t: v for t, v in zip(s["ticker"], s["sector"]) if isinstance(v, str) and v}, files[-1].name


def placebo_table(T: pd.DataFrame, shift: int) -> pd.DataFrame:
    """Every one of the 43 variables replaced by its value `shift` months later (+) or earlier (-), re-ranked."""
    X = T[["p", "ticker"] + [v for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS if v in T.columns]].copy()
    X["p"] = X["p"] - shift
    P = T.drop(columns=[v for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS if v in T.columns]).merge(X, on=["p", "ticker"], how="left")
    for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS:
        if v in P.columns:
            P[v + "_rk"] = P.groupby("p")[v].transform(wf.rank_scaled)
    return P


def decompose(S: pd.DataFrame, score: str) -> dict:
    """Per test month on the rows with a sector label: the registered top tenth, its sector allocation and selection,
    the within-sector top tenths, the technology shares and the variable tilts."""
    rows = []
    for p, g in S.groupby("p"):
        n = len(g); k = max(int(round(n * 0.10)), 1)
        top = g.nlargest(k, score)
        sec_mean = g.groupby("sector")["fwd12_x"].mean()
        w = top["sector"].value_counts(normalize=True)
        alloc = float(sum(w[s] * sec_mean[s] for s in w.index))
        top_x = float(top["fwd12_x"].mean())
        sel = top_x - alloc
        # the same score ranked within each sector: the top tenth of each sector
        parts = []
        for s, gs in g.groupby("sector"):
            ks = max(int(round(len(gs) * 0.10)), 1)
            parts.append(gs.nlargest(ks, score))
        ws = pd.concat(parts)
        ws_x = float(ws["fwd12_x"].mean())
        ws_own = float((ws["fwd12_x"] - ws["sector"].map(sec_mean)).mean())
        rows.append({"p": p, "year": p.year, "n": n, "k": k,
                     "top_vs_avg_net": top_x - COST, "allocation_gross": alloc, "selection_net": sel - COST,
                     "within_vs_avg_net": ws_x - COST, "within_vs_own_net": ws_own - COST,
                     "tech_share_top": float((top["sector"] == TECH).mean()), "tech_share_members": float((g["sector"] == TECH).mean()),
                     **{f"tilt_{v}": float(top[v + "_rk"].mean()) for v in TILT_VARS if v + "_rk" in top.columns}})
    return pd.DataFrame(rows)


def main() -> int:
    sectors, sec_file = sector_labels()
    stamp = wf.latest_stamp()
    T, info = wf.build_table(stamp, shift_analyst=0, hold_delisted=True, ext=True)
    T = T[T["has_fund"].fillna(False)].copy()
    feats = [v + "_rk" for v in wf.EXT_PRICE_VARS + wf.EXT_FUND_VARS if v + "_rk" in T.columns]
    score = cl.fit_scores(T, feats, "fwd12_x", cl.TRAIN_FROM["ext43"], 100.0, "diag_actual")
    T["sector"] = T["ticker"].map(sectors)
    base = T[T[score].notna() & T["fwd12_x"].notna()]
    labelled = float(base["sector"].notna().mean())
    S = base[base["sector"].notna()].copy()
    D = decompose(S, score)
    # the past placebo, within-sector version
    P = placebo_table(T.drop(columns=[c for c in T.columns if c.startswith("score_cl_") or c.startswith("pred_")], errors="ignore"), -12)
    pscore = cl.fit_scores(P, feats, "fwd12_x", cl.TRAIN_FROM["ext43"], 100.0, "diag_placebo_past")
    P["sector"] = P["ticker"].map(sectors)
    DP = decompose(P[P[pscore].notna() & P["fwd12_x"].notna() & P["sector"].notna()].copy(), pscore)
    h1 = D[D["year"] <= 2019]; h2 = D[(D["year"] >= 2020) & (D["year"] <= 2025)]
    table = [
        {"quantity": "top tenth over the average member (registered quantity; names with a sector label)", **nw(D["top_vs_avg_net"])},
        {"quantity": "the top tenth's sector weights held at sector-average returns (gross)", **nw(D["allocation_gross"])},
        {"quantity": "top tenth over the members of its own sector (net; allocation + this = the first row)", **nw(D["selection_net"])},
        {"quantity": "same score ranked within each sector, top tenth of each sector, over the average member", **nw(D["within_vs_avg_net"])},
        {"quantity": "the same, over the members of its own sector", **nw(D["within_vs_own_net"])},
        {"quantity": "within-sector version, 2014 to 2019", **nw(h1["within_vs_avg_net"])},
        {"quantity": "within-sector version, 2020 to 2025", **nw(h2["within_vs_avg_net"])},
        {"quantity": "registered version, 2014 to 2019", **nw(h1["top_vs_avg_net"])},
        {"quantity": "registered version, 2020 to 2025", **nw(h2["top_vs_avg_net"])},
        {"quantity": "past placebo (variables from 12 months earlier), within-sector version over the average member", **nw(DP["within_vs_avg_net"])},
        {"quantity": "past placebo, registered version over the average member", **nw(DP["top_vs_avg_net"])},
    ]
    alloc_share = round(float(D["allocation_gross"].mean() / D["top_vs_avg_net"].mean()), 3) if D["top_vs_avg_net"].mean() else None
    reg_path = AN / "candidate_list_test_registration.json"
    payload = {
        "cadence": "static", "as_of": datetime.now().strftime("%Y-%m-%d"), "label": "DIAGNOSTIC",
        "no_verdict": "computed after the registered result was known; no part in any verdict",
        "order": "third follow-up of 7 October 2026, H3",
        "score": "the registered primary score (43 variables, ridge penalty 100 and the boosted tree, mean of the within-month percentile ranks), refitted on the harness after H1",
        "inputs": {"raw_stamp": stamp, "table_rows": int(len(T)), "test_months": int(D["p"].nunique()), "members_per_month_with_label": round(float(D["n"].mean()), 1),
                   "share_of_test_rows_with_a_sector_label": round(labelled, 4), "sector_file": sec_file,
                   "registration_sha256": hashlib.sha256(reg_path.read_bytes()).hexdigest() if reg_path.exists() else None,
                   "table_options": info.get("options")},
        "sector_labels": "the provider's current sector for each current symbol, applied to every year: Alphabet and Meta carry Communication Services also before the 2018 reclassification; a name that left the index keeps the label the provider shows today",
        "cost": "20 bps a holding (10 bps a trade, both ways), charged to the top tenth, the selection term and the within-sector portfolios; the allocation term is gross",
        "table": table,
        "allocation_share_of_result": alloc_share,
        "technology": {"share_of_top_tenth": round(float(D["tech_share_top"].mean()), 3), "share_of_members": round(float(D["tech_share_members"].mean()), 3)},
        "top_tenth_mean_rank": {TILT_VARS[v]: round(float(D[f"tilt_{v}"].mean()), 3) for v in TILT_VARS if f"tilt_{v}" in D.columns},
        "reading": ("the past placebo stays high because R&D to sales and gross profitability change little from one year to the next: "
                    "that placebo was built to catch look-ahead in variables that change quickly; for slow characteristics it is expected to stay high and does not indicate a leak"),
    }
    OUT.write_text(json.dumps(payload, indent=1, default=str))
    for r in table:
        log(f"{r['quantity'][:80]:<80} {r['pts_per_year']:+.2f} (t {r['t_nw']:.2f}, {r['months']} months)")
    log(f"technology share top tenth {payload['technology']['share_of_top_tenth']:.3f} vs members {payload['technology']['share_of_members']:.3f}; tilts {payload['top_tenth_mean_rank']}; allocation share {alloc_share}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
