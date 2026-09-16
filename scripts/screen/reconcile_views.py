"""
reconcile_views.py — reconciliation panel between the two scoring views
(order 6.2, 2026-09-16).

    "a reconciliation panel showing the rank correlation between the two scoring
     views and the ten largest divergences with attributed cause"

Tournament view  data/scored_universe.csv
    composite (0–50) = tech_score (0–25, cross-sectional rank average of
    ma200 / rsi / rs6m) + fund_score (0–25, rank average of six fundamentals);
    rebuilt monthly (monthly_rebalance.yml).
Screen view      data/screen/scored_universe.csv
    composite (0–75) = fundamental (0–25, threshold ladders) + technical (0–25,
    ladders; broken-base cap) + visibility (0–25, registry override or the
    capped sector fallback) + corr_penalty (0 to −10) + leverage_penalty
    (0 to −5); rebuilt nightly.

Method (also written into the JSON):
  1. On the common names, Spearman rank correlation of the two composites, of
     the two technical scores and of the two fundamental scores.
  2. Percentile rank in each view = native rank / native n (× 100). The
     divergence of a name is pct_screen − pct_tournament (positive: the screen
     ranks it further DOWN the board than the tournament; negative: further UP).
     The ten largest |divergence| are reported.
  3. Cause, attributed mechanically. Each screen-only component is converted
     into rank points by a counterfactual re-rank inside the screen view:
     remove the component's contribution from the name's composite, re-rank it
     against the other screen composites (method 'min'), and take the change in
     percentile rank. Components:
        visibility_override_excess  = visibility − fallback, where fallback =
                                      min(sector_prior, visibility_fallback_cap);
                                      sector_prior from the registry entry when the
                                      name has one, else SECTOR_VIS_PRIORS[sector]
                                      (12.5 when the sector is unknown)
        correlation_penalty         = corr_penalty (null → 0)
        leverage_penalty            = leverage_penalty (null → 0)
        broken_base_cap             = technical − technical_precap
     The technical and fundamental DISAGREEMENTS are the percentile gaps of the
     factor scores between the views (ranked on the common names; the screen's
     technical taken pre-cap so the broken-base cap is counted once). The cause
     is the candidate with the largest magnitude among those pushing in the
     direction of the divergence; if none does, the largest overall is named and
     flagged. Every number behind the choice is written per name.

Output: data/screen/reconciliation.json — cadence "daily"; session_date = the
screen view's session_date (data/screen/scores.json).

Usage:  python scripts/screen/reconcile_views.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
SCREEN = DATA / "screen"

TOURNAMENT_CSV = DATA / "scored_universe.csv"
SCREEN_CSV = SCREEN / "scored_universe.csv"
SCREEN_SCORES = SCREEN / "scores.json"
REGISTRY = SCREEN / "visibility_registry.json"
CONFIG = Path(__file__).resolve().parent / "config.json"
OUT = SCREEN / "reconciliation.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score_universe as su  # noqa: E402  (SECTOR_VIS_PRIORS — the one source of the priors)

N_DIVERGENCES = 10

COMPONENTS = ("visibility_override_excess", "correlation_penalty",
              "leverage_penalty", "broken_base_cap")
DISAGREEMENTS = ("technical_disagreement", "fundamental_disagreement")


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def pct_rank_desc(s: pd.Series) -> pd.Series:
    """Percentile rank (0–100, lower = better) of a score among its peers, rank method 'min'."""
    return s.rank(ascending=False, method="min") / s.notna().sum() * 100.0


def main() -> None:
    t = pd.read_csv(TOURNAMENT_CSV)
    s = pd.read_csv(SCREEN_CSV)
    scores = json.loads(SCREEN_SCORES.read_text())
    session_date = scores.get("session_date")
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    entries = reg.get("entries") or {}
    cfg = json.loads(CONFIG.read_text())
    cap = float(cfg.get("visibility_fallback_cap", su.VISIBILITY_FALLBACK_CAP))

    for col in ("ticker", "tech_score", "fund_score", "composite", "composite_rank"):
        if col not in t.columns:
            sys.exit(f"tournament view lacks column {col}")
    for col in ("ticker", "fundamental", "technical", "visibility", "composite", "rank",
                "technical_precap", "corr_penalty", "leverage_penalty"):
        if col not in s.columns:
            sys.exit(f"screen view lacks column {col}")

    n_t, n_s = len(t), len(s)
    t = t.set_index("ticker")
    s = s.set_index("ticker")
    common = sorted(set(t.index) & set(s.index))
    if len(common) < 50:
        sys.exit(f"only {len(common)} common names — refusing to reconcile")
    tc, sc = t.loc[common], s.loc[common]

    # 1. Spearman on the common names
    rho = {
        "composite": float(num(tc["composite"]).corr(num(sc["composite"]), method="spearman")),
        "technical": float(num(tc["tech_score"]).corr(num(sc["technical"]), method="spearman")),
        "fundamental": float(num(tc["fund_score"]).corr(num(sc["fundamental"]), method="spearman")),
    }

    # 2. Percentile ranks (native rank / native n) and divergences
    pct_t = num(tc["composite_rank"]) / n_t * 100.0
    pct_s = num(sc["rank"]) / n_s * 100.0
    gap = (pct_s - pct_t)
    top = gap.abs().sort_values(ascending=False).head(N_DIVERGENCES).index.tolist()

    # factor-score percentiles on the common set (for the disagreement causes).
    # The screen's technical is taken PRE-cap so the broken-base cap is counted
    # exactly once, as the broken_base_cap component, never also as disagreement.
    p_tech_t, p_tech_s = pct_rank_desc(num(tc["tech_score"])), pct_rank_desc(num(sc["technical_precap"]))
    p_fund_t, p_fund_s = pct_rank_desc(num(tc["fund_score"])), pct_rank_desc(num(sc["fundamental"]))

    # 3. Counterfactual re-rank inside the FULL screen view
    comp_all = num(s["composite"]).to_numpy(dtype=float)
    idx_of = {tk: i for i, tk in enumerate(s.index)}

    def rank_min(i: int, value: float) -> int:
        """Rank (method 'min') the i-th screen name would hold at composite `value`, others unchanged."""
        greater = int((comp_all > value).sum()) - int(comp_all[i] > value)
        return 1 + greater

    def fallback_for(tk: str, row: pd.Series) -> tuple[float, float, str]:
        e = entries.get(tk)
        sector = row.get("sector") if isinstance(row.get("sector"), str) else ""
        if e and e.get("sector_prior") is not None:
            prior, src = float(e["sector_prior"]), "registry entry sector_prior"
        else:
            prior, src = float(su.SECTOR_VIS_PRIORS.get(sector, 12.5)), "SECTOR_VIS_PRIORS[sector]"
        return min(prior, cap), prior, src

    divergences = []
    for tk in top:
        r_s, r_t = s.loc[tk], t.loc[tk]
        i = idx_of[tk]
        g = float(gap[tk])
        direction = "screen ranks it lower (further down the board) than the tournament" if g > 0 else \
                    "screen ranks it higher (further up the board) than the tournament"

        vis = float(num(pd.Series([r_s["visibility"]])).iloc[0] or 0.0)
        fallback, prior, prior_src = fallback_for(tk, r_s)
        corr = num(pd.Series([r_s["corr_penalty"]])).fillna(0.0).iloc[0]
        lev = num(pd.Series([r_s["leverage_penalty"]])).fillna(0.0).iloc[0]
        tech, tech_pre = float(r_s["technical"]), float(r_s["technical_precap"])
        contributions = {
            "visibility_override_excess": round(vis - fallback, 2),
            "correlation_penalty": round(float(corr), 2),
            "leverage_penalty": round(float(lev), 2),
            "broken_base_cap": round(tech - tech_pre, 2),
        }

        base_rank = rank_min(i, comp_all[i])
        components = {}
        for name in COMPONENTS:
            c = contributions[name]
            if abs(c) < 1e-9:
                components[name] = {"contribution_pts": 0.0, "counterfactual_rank": base_rank,
                                    "rank_points": 0.0}
                continue
            cf_rank = rank_min(i, comp_all[i] - c)
            # rank points = change in percentile rank the component caused (negative: it lifted the name)
            rank_points = (base_rank - cf_rank) / n_s * 100.0
            components[name] = {"contribution_pts": c, "counterfactual_rank": int(cf_rank),
                                "rank_points": round(float(rank_points), 2)}
        components["technical_disagreement"] = {
            "tournament_pct": round(float(p_tech_t[tk]), 2), "screen_pct": round(float(p_tech_s[tk]), 2),
            "rank_points": round(float(p_tech_s[tk] - p_tech_t[tk]), 2)}
        components["fundamental_disagreement"] = {
            "tournament_pct": round(float(p_fund_t[tk]), 2), "screen_pct": round(float(p_fund_s[tk]), 2),
            "rank_points": round(float(p_fund_s[tk] - p_fund_t[tk]), 2)}

        # pick the cause: largest magnitude among candidates pushing in the divergence direction
        sign = 1.0 if g > 0 else -1.0
        cands = {k: v["rank_points"] for k, v in components.items()}
        aligned = {k: v for k, v in cands.items() if v * sign > 0}
        if aligned:
            cause = max(aligned, key=lambda k: abs(aligned[k]))
            flag = None
        else:
            cause = max(cands, key=lambda k: abs(cands[k]))
            flag = "sign mismatch — no component pushes in the divergence direction; largest magnitude named"
        share = (cands[cause] / g) if g else None

        entry = entries.get(tk) or {}
        divergences.append({
            "ticker": tk,
            "name": r_s.get("name") if isinstance(r_s.get("name"), str) else (r_t.get("shortName") if isinstance(r_t.get("shortName"), str) else tk),
            "sector": r_s.get("sector") if isinstance(r_s.get("sector"), str) else "",
            "divergence_pct_points": round(g, 2),
            "direction": direction,
            "tournament": {"rank": int(r_t["composite_rank"]), "n": n_t, "pct": round(float(pct_t[tk]), 2),
                           "composite": round(float(r_t["composite"]), 2),
                           "tech_score": round(float(r_t["tech_score"]), 2),
                           "fund_score": round(float(r_t["fund_score"]), 2)},
            "screen": {"rank": int(r_s["rank"]), "n": n_s, "pct": round(float(pct_s[tk]), 2),
                       "rank_method_min": int(base_rank),
                       "composite": round(float(r_s["composite"]), 1),
                       "fundamental": round(float(r_s["fundamental"]), 1),
                       "technical": round(tech, 1), "technical_precap": round(tech_pre, 1),
                       "visibility": round(vis, 1), "visibility_fallback": round(fallback, 1),
                       "sector_prior": prior, "sector_prior_source": prior_src,
                       "visibility_legacy": (round(float(r_s["visibility_legacy"]), 1)
                                             if "visibility_legacy" in s.columns and pd.notna(r_s["visibility_legacy"]) else None),
                       "registry_override": bool(entry), "override_rationale": entry.get("rationale"),
                       "corr_penalty": (round(float(corr), 1) if pd.notna(r_s["corr_penalty"]) else None),
                       "leverage_penalty": (round(float(lev), 1) if pd.notna(r_s["leverage_penalty"]) else None),
                       "broken_base": bool(r_s.get("broken_base", False))},
            "components": components,
            "cause": cause,
            "cause_rank_points": cands[cause],
            "cause_share_of_divergence": round(share, 2) if share is not None else None,
            "cause_flag": flag,
        })

    now_et = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    t_mtime = datetime.fromtimestamp(TOURNAMENT_CSV.stat().st_mtime, ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    out = {
        "cadence": "daily",
        "session_date": session_date,
        "computed_at": now_et,
        "built_by": "scripts/screen/reconcile_views.py (order 6.2, 2026-09-16)",
        "inputs": {
            "tournament": {"path": "data/scored_universe.csv", "n": n_t, "file_mtime": t_mtime,
                           "composite": "tech_score + fund_score (0–50), rank-based factor scores; rebuilt monthly"},
            "screen": {"path": "data/screen/scored_universe.csv", "n": n_s, "session_date": session_date,
                       "composite": "fundamental + technical + visibility + corr_penalty + leverage_penalty (0–75); rebuilt nightly",
                       "data_source": (scores.get("provenance") or {}).get("data_source")},
            "visibility_registry": {"path": "data/screen/visibility_registry.json",
                                    "version": reg.get("version"), "frozen_at": reg.get("frozen_at"),
                                    "n_entries": len(entries), "fallback_cap": cap},
        },
        "n_common": len(common),
        "only_tournament": sorted(set(t.index) - set(s.index)),
        "only_screen": sorted(set(s.index) - set(t.index)),
        "spearman": {k: round(v, 4) for k, v in rho.items()},
        "method": {
            "correlation": "Spearman rank correlation on the common names: composite vs composite, "
                           "tech_score vs technical, fund_score vs fundamental",
            "divergence": "percentile rank = native rank / native n × 100 in each view; divergence = "
                          "pct_screen − pct_tournament (positive: the screen ranks the name further down the "
                          "board than the tournament); the ten largest |divergence| are listed",
            "attribution": "each screen-only component (visibility override excess over the capped sector "
                           "fallback, correlation penalty, leverage penalty, broken-base cap) is converted into "
                           "rank points by removing its contribution from the name's screen composite and "
                           "re-ranking it against the other screen composites (method 'min'); the technical and "
                           "fundamental disagreements are the factor-score percentile gaps between the views on "
                           "the common names (screen technical pre-cap, so the broken-base cap counts once); the "
                           "cause is the largest-magnitude candidate pushing in the divergence direction "
                           "(flagged when none does)",
            "visibility_fallback": "min(sector_prior, visibility_fallback_cap); sector_prior from the registry "
                                   "entry when present, else SECTOR_VIS_PRIORS[sector] (12.5 if unknown)",
        },
        "divergences": divergences,
    }
    OUT.write_text(json.dumps(out, indent=1, allow_nan=False) + "\n")

    print(f"reconciliation: {len(common)} common names (tournament {n_t}, screen {n_s}); "
          f"session {session_date}")
    print(f"  Spearman composite {rho['composite']:.4f} | technical {rho['technical']:.4f} | "
          f"fundamental {rho['fundamental']:.4f}")
    print(f"  {'ticker':<6} {'gap':>7} {'t.rank':>6} {'s.rank':>6}  cause (rank points)")
    for d in divergences:
        print(f"  {d['ticker']:<6} {d['divergence_pct_points']:>+7.2f} {d['tournament']['rank']:>6} "
              f"{d['screen']['rank']:>6}  {d['cause']} ({d['cause_rank_points']:+.2f})"
              + (f"  [{d['cause_flag']}]" if d['cause_flag'] else ""))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
