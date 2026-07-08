"""
compute_thesis_daily.py — MESO layer: holdings-based thesis exposure,
concentration, basket performance, falsification auto-log, and
allocation-vs-selection attribution.

WHAT THIS IS NOT (hard constraints from the brief):
  - NO factor regressions on live data (17 sessions = vacuous). Exposure is
    HOLDINGS-BASED: position weights × registry membership weights.
  - NO rotation/timing signal. Everything here is risk accounting.
  - The registry and claims are FROZEN judgment artifacts. This script never
    edits classifications or claim text. Its only write into claims is the
    mechanical AUTO log channel: {date, event, basket 1d return} on
    scheduled-event days. No narrative generation.

Outputs:
  data/thesis_daily.json   exposure vectors, N_eff, overlap, basket returns,
                           attribution components per tier
  data/thesis_claims.json  (append-only AUTO log entries; idempotent)
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

INCEPTION = "2026-05-20"
UNCLASSIFIED = "unclassified"
DIVERGENCE_FLAG_PP = 2.0     # |basket 1w − proxy 1w| > 2pp → classification-drift smell
UNCLASSIFIED_PROMPT = 0.15   # >15% of invested weight unclassified → prompt to extend registry


def load_registry() -> dict:
    return json.load(open(DATA / "thesis_registry.json"))


def name_thesis_weights(registry: dict) -> dict[str, dict[str, float]]:
    """ticker → {thesis_id: membership_weight}. Residual to 1.0 = unclassified."""
    out: dict[str, dict[str, float]] = {}
    for tid, th in registry["theses"].items():
        for name, w in th["members"].items():
            out.setdefault(name, {})[tid] = float(w)
    return out


def basket_members(registry: dict) -> dict[str, list[str]]:
    return {tid: list(th["members"].keys()) for tid, th in registry["theses"].items()}


def equal_weight_basket_returns(prices: pd.DataFrame, members: list[str]) -> pd.Series:
    cols = [m for m in members if m in prices.columns]
    if not cols:
        return pd.Series(dtype=float)
    rets = prices[cols].pct_change()
    return rets.mean(axis=1)


def exposure_for_positions(positions: list[dict], equity: float, cash: float,
                            nw: dict) -> tuple[dict, dict, list[str]]:
    """Returns (exposure_invested, exposure_total, unclassified_names).
       exposure_invested sums to 1 over {theses..., unclassified};
       exposure_total additionally carries 'cash' and sums to 1 over NAV."""
    nav = equity + cash
    inv: dict[str, float] = {}
    uncl_names: list[str] = []
    for p in positions:
        v = p.get("value")
        if not v:
            continue
        share_inv = v / equity if equity > 0 else 0.0
        splits = nw.get(p["ticker"], {})
        assigned = 0.0
        for tid, w in splits.items():
            inv[tid] = inv.get(tid, 0.0) + share_inv * w
            assigned += w
        resid = max(0.0, 1.0 - assigned)
        if resid > 1e-9:
            inv[UNCLASSIFIED] = inv.get(UNCLASSIFIED, 0.0) + share_inv * resid
            if assigned < 1e-9:
                uncl_names.append(p["ticker"])
    total = {k: v * (equity / nav) for k, v in inv.items()} if nav > 0 else dict(inv)
    total["cash"] = cash / nav if nav > 0 else 0.0
    return inv, total, uncl_names


def n_eff(weights: dict) -> float:
    vals = [v for v in weights.values() if v > 0]
    s2 = sum(v * v for v in vals)
    return (1.0 / s2) if s2 > 0 else 0.0


def overlap(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return sum(min(a.get(k, 0.0), b.get(k, 0.0)) for k in keys)


def main():
    registry = load_registry()
    frozen = registry.get("frozen_at") is not None
    nw = name_thesis_weights(registry)
    members = basket_members(registry)

    # ── Σ weights per name ≤ 1.0 (hard registry invariant) ────────────
    for name, splits in nw.items():
        total_w = sum(splits.values())
        assert total_w <= 1.0 + 1e-9, f"registry invariant violated: {name} Σweights = {total_w}"

    prices = pd.read_parquet(SOURCE / "prices_daily.parquet")
    if "SPY_volume" in prices.columns: prices = prices.drop(columns=["SPY_volume"])
    prices.index = pd.to_datetime(prices.index)
    sect = pd.read_parquet(SOURCE / "sector_etfs.parquet")
    sect.index = pd.to_datetime(sect.index)
    vol = pd.read_parquet(SOURCE / "vol_indicators.parquet")
    vol.index = pd.to_datetime(vol.index)

    tournament = json.load(open(DATA / "tournament.json"))
    history = tournament["history"]
    as_of = history[-1]["date"]
    n_sessions = len(history)

    # ── Basket return series (equal-weight within basket) ─────────────
    basket_ret: dict[str, pd.Series] = {}
    basket_n_priced: dict[str, int] = {}
    for tid, mem in members.items():
        basket_ret[tid] = equal_weight_basket_returns(prices, mem)
        basket_n_priced[tid] = sum(1 for m in mem if m in prices.columns)

    # SPY closes live in sector_etfs.parquet (price store carries only SPY_volume)
    spy_ret = sect["spy"].pct_change()

    def period_ret(r: pd.Series, since: str) -> float | None:
        sub = r[r.index >= pd.Timestamp(since)].dropna()
        return float((1 + sub).prod() - 1) if len(sub) else None

    def proxy_series(tid: str) -> pd.Series | None:
        etf = registry["theses"][tid].get("proxy_etf", "").lower()
        if etf in sect.columns:
            return sect[etf].pct_change()
        if etf == "gld" and "gold" in vol.columns:
            return vol["gold"].pct_change()
        return None

    one_week_ago = (pd.Timestamp(as_of) - pd.tseries.offsets.BDay(5)).strftime("%Y-%m-%d")
    baskets_out = {}
    for tid, r in basket_ret.items():
        label = registry["theses"][tid]["label"]
        pr = proxy_series(tid)
        # Drawdown from peak since inception (basket cumulated)
        cum = (1 + r[r.index >= pd.Timestamp(INCEPTION)].fillna(0)).cumprod()
        dd = float(cum.iloc[-1] / cum.max() - 1) if len(cum) else None
        b1w = period_ret(r, one_week_ago)
        p1w = period_ret(pr, one_week_ago) if pr is not None else None
        div_pp = (b1w - p1w) * 100 if (b1w is not None and p1w is not None) else None
        baskets_out[tid] = {
            "label": label,
            "proxy_etf": registry["theses"][tid].get("proxy_etf"),
            "n_members_priced": basket_n_priced[tid],
            "ret_1d": round(float(r.dropna().iloc[-1]), 5) if len(r.dropna()) else None,
            "ret_1w": round(b1w, 5) if b1w is not None else None,
            "ret_inception": round(period_ret(r, INCEPTION), 5) if period_ret(r, INCEPTION) is not None else None,
            "drawdown_from_peak": round(dd, 5) if dd is not None else None,
            "proxy_ret_1d": round(float(pr.dropna().iloc[-1]), 5) if pr is not None and len(pr.dropna()) else None,
            "proxy_ret_1w": round(p1w, 5) if p1w is not None else None,
            "proxy_ret_inception": round(period_ret(pr, INCEPTION), 5) if pr is not None and period_ret(pr, INCEPTION) is not None else None,
            "divergence_1w_pp": round(div_pp, 2) if div_pp is not None else None,
            "divergence_flag": bool(div_pp is not None and abs(div_pp) > DIVERGENCE_FLAG_PP),
        }

    # ── Relative-strength ratios (descriptive context — NOT a signal) ──
    def rs_ratio(a: str, b: str, days: int = 252) -> list[dict]:
        ra, rb = basket_ret[a].fillna(0), basket_ret[b].fillna(0)
        idx = ra.index.intersection(rb.index)
        idx = idx[idx >= idx.max() - pd.Timedelta(days=days * 1.6)]
        ca, cb = (1 + ra.loc[idx]).cumprod(), (1 + rb.loc[idx]).cumprod()
        ratio = (ca / cb)
        ratio = ratio / ratio.iloc[0]
        # downsample to ~120 points
        step = max(1, len(ratio) // 120)
        pts = ratio.iloc[::step]
        if ratio.index[-1] not in pts.index:
            pts = pd.concat([pts, ratio.iloc[[-1]]])
        return [{"d": d.strftime("%Y-%m-%d"), "v": round(float(v), 4)} for d, v in pts.items()]

    rs_series = {
        "ai_infra_vs_fin_plumbing": rs_ratio("ai_infra", "fin_plumbing"),
        "ai_infra_vs_hard_assets":  rs_ratio("ai_infra", "hard_assets"),
    }

    # ── Per-tier exposure (latest snapshot) ────────────────────────────
    tiers_out = {}
    last = history[-1]
    for tid, td in last["tiers"].items():
        equity = float(td.get("equity") or 0)
        cash = float(td.get("cash") or 0)
        inv, total, uncl_names = exposure_for_positions(td.get("positions", []), equity, cash, nw)
        uncl_share = inv.get(UNCLASSIFIED, 0.0)
        tiers_out[tid] = {
            "date": last["date"],
            "invested_share": round(equity / (equity + cash), 4) if (equity + cash) > 0 else 0,
            "cash_share": round(cash / (equity + cash), 4) if (equity + cash) > 0 else 0,
            "exposure_invested": {k: round(v, 4) for k, v in sorted(inv.items(), key=lambda kv: -kv[1])},
            "exposure_total": {k: round(v, 4) for k, v in sorted(total.items(), key=lambda kv: -kv[1])},
            "n_eff": round(n_eff(inv), 2),
            "unclassified_share": round(uncl_share, 4),
            "unclassified_names": uncl_names,
            "extend_registry_prompt": bool(uncl_share > UNCLASSIFIED_PROMPT),
        }

    # Overlap matrix on invested exposure vectors
    tids = list(tiers_out.keys())
    overlap_matrix = {
        a: {b: round(overlap(tiers_out[a]["exposure_invested"], tiers_out[b]["exposure_invested"]), 3)
            for b in tids}
        for a in tids
    }

    # ── Attribution: cash | allocation | selection, daily + cumulative ──
    # Start-of-period weights (t−1 snapshot) → no look-ahead. Components are
    # defined so that cash_eff + alloc_eff + selection == active_vs_spy
    # EXACTLY (selection is the residual); the CI assert guards bookkeeping.
    attribution = {}
    for tid in tids:
        rows = []
        max_resid_bp = 0.0
        for i in range(1, len(history)):
            prev, cur = history[i - 1], history[i]
            tdp, tdc = prev["tiers"].get(tid), cur["tiers"].get(tid)
            if not tdp or not tdc: continue
            nav0, nav1 = float(tdp["nav"]), float(tdc["nav"])
            if nav0 <= 0: continue
            r_tier = nav1 / nav0 - 1
            d = pd.Timestamp(cur["date"])
            if d not in spy_ret.index: continue
            r_spy = float(spy_ret.loc[d])
            cash_rate = float(prev.get("effr_daily_pct", 4.0)) / 100.0 / 252.0
            equity0 = float(tdp.get("equity") or 0); cash0 = float(tdp.get("cash") or 0)
            inv0, total0, uncl0 = exposure_for_positions(tdp.get("positions", []), equity0, cash0, nw)
            w_cash = total0.get("cash", 0.0)
            # unclassified basket = equal-weight of the tier's own unclassified names
            uncl_ret = None
            if uncl0:
                cols = [t for t in uncl0 if t in prices.columns and d in prices.index]
                if cols:
                    uncl_ret = float(prices[cols].pct_change().loc[d].mean())
            cash_eff = w_cash * (cash_rate - r_spy)
            alloc_eff = 0.0
            implied = w_cash * cash_rate
            for theta, w in total0.items():
                if theta == "cash": continue
                if theta == UNCLASSIFIED:
                    r_theta = uncl_ret if uncl_ret is not None else r_spy
                else:
                    r_theta = float(basket_ret[theta].loc[d]) if d in basket_ret[theta].index and not math.isnan(basket_ret[theta].loc[d]) else r_spy
                alloc_eff += w * (r_theta - r_spy)
                implied += w * r_theta
            selection = r_tier - implied
            active = r_tier - r_spy
            resid = abs((cash_eff + alloc_eff + selection) - active)
            max_resid_bp = max(max_resid_bp, resid * 1e4)
            rows.append({"d": cur["date"], "active": active, "cash_eff": cash_eff,
                          "alloc_eff": alloc_eff, "selection": selection})
        cum = {k: round(sum(r[k] for r in rows), 5) for k in ("active", "cash_eff", "alloc_eff", "selection")}
        attribution[tid] = {
            "cum": cum,
            "last_day": {k: round(rows[-1][k], 5) for k in ("active", "cash_eff", "alloc_eff", "selection")} if rows else None,
            "n_days": len(rows),
            "check_max_residual_bp": round(max_resid_bp, 4),
            "method": "arithmetic sum of daily components; start-of-period weights; selection = residual",
        }

    # ── AUTO log into thesis_claims.json (mechanical channel only) ─────
    appended = []
    try:
        cal = json.load(open(DATA / "event_calendar.json"))
        events_by_date = {}
        for e in cal["events"]:
            if e["type"] in ("CPI", "FOMC", "NFP"):
                events_by_date.setdefault(e["date"], []).append(e["type"])
        claims = json.load(open(DATA / "thesis_claims.json"))
        session_dates = [h["date"] for h in history]
        for c in claims["claims"]:
            tid = c["thesis_id"]
            have = {(l.get("date"), l.get("type")) for l in c.get("log", [])}
            for d_str in session_dates:
                if d_str not in events_by_date: continue
                if (d_str, "auto") in have: continue
                dd = pd.Timestamp(d_str)
                if dd not in basket_ret[tid].index: continue
                r1d = basket_ret[tid].loc[dd]
                if math.isnan(r1d): continue
                entry = {"date": d_str, "type": "auto",
                          "event": " · ".join(events_by_date[d_str]),
                          "basket_ret_1d": round(float(r1d), 5)}
                c.setdefault("log", []).append(entry)
                appended.append({**entry, "thesis_id": tid})
        for c in claims["claims"]:
            c["log"].sort(key=lambda l: l.get("date", ""))
        with open(DATA / "thesis_claims.json", "w") as f:
            json.dump(claims, f, indent=2)
    except FileNotFoundError as e:
        print(f"  warn auto-log skipped: {e}", file=sys.stderr)

    # Kill-criteria status — MECHANICAL: only an explicit manual log entry
    # with "kill": true sets it. Never inferred from returns.
    claims = json.load(open(DATA / "thesis_claims.json"))
    kill_status = {}
    for c in claims["claims"]:
        met = [l for l in c.get("log", []) if l.get("kill") is True]
        kill_status[c["thesis_id"]] = {"met": bool(met), "date": met[0]["date"] if met else None}

    payload = {
        "updated": datetime.now().isoformat(),
        "as_of": as_of,
        "registry_version": registry["version"],
        "registry_frozen": frozen,
        "registry_frozen_at": registry.get("frozen_at"),
        "sessions_since_inception": n_sessions,
        "small_n_caveat": f"{n_sessions} sessions since inception {INCEPTION} — too short for inference; descriptive only.",
        "method_caption": (f"holdings-based; registry v{registry['version']}"
                            f"{' (PENDING APPROVAL)' if not frozen else ''}; names may split across "
                            f"theses; unclassified share shown; baskets equal-weight within basket."),
        "tiers": tiers_out,
        "overlap_matrix": overlap_matrix,
        "baskets": baskets_out,
        "rs_series": rs_series,
        "rs_caption": "descriptive context — not a rotation signal",
        "attribution": attribution,
        "kill_status": kill_status,
        "auto_log_appended_this_run": appended,
    }

    def _clean(o):
        if isinstance(o, dict):  return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, list):  return [_clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
        if isinstance(o, (np.floating,)):
            x = float(o); return None if (math.isnan(x) or math.isinf(x)) else x
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.bool_,)): return bool(o)
        return o

    with open(DATA / "thesis_daily.json", "w") as f:
        json.dump(_clean(payload), f, indent=2, allow_nan=False)

    # ── JULY AUDIT FIX 1b/c + 7: registry proposals (agent NEVER auto-merges) ──
    # For every unclassified held name, emit a PROPOSED mapping with a
    # one-line rationale. Werner approves by moving entries into the
    # registry with a version bump; nothing here touches the registry.
    # Explicit v2 proposals from the July audit for the current tier-1
    # seven; sector-heuristic proposals for anything else; plus the
    # memory_semis sub-thesis proposal (bucket-dependence demonstration).
    EXPLICIT_PROPOSALS = {
        "CME":  ({"fin_plumbing": 1.0},  "derivatives exchange — pure transaction-toll economics"),
        "MSCI": ({"fin_plumbing": 1.0},  "index/analytics licensing — financial-infrastructure fee stream"),
        "PFE":  ({"defensive_quality": 1.0}, "large-cap pharma — defensive health cash flows"),
        "GILD": ({"defensive_quality": 1.0}, "large-cap biopharma — defensive health cash flows"),
        "BSX":  ({"defensive_quality": 0.7, "ldg_ex_ai": 0.3}, "medical devices — defensive demand with a growth-multiple leg"),
        "DXCM": ({"ldg_ex_ai": 0.6, "defensive_quality": 0.4}, "CGM devices — long-duration growth on a health-staple base"),
        "IDXX": ({"defensive_quality": 0.6, "ldg_ex_ai": 0.4}, "veterinary diagnostics — recurring-revenue quality with growth multiple"),
    }
    SECTOR_HEURISTIC = {
        "Financial Services": "fin_plumbing", "Financials": "fin_plumbing",
        "Energy": "hard_assets", "Basic Materials": "hard_assets",
        "Consumer Defensive": "defensive_quality", "Healthcare": "defensive_quality",
        "Technology": "ldg_ex_ai", "Communication Services": "ldg_ex_ai",
        "Consumer Cyclical": "consumer_cyclical", "Industrials": "consumer_cyclical",
        "Utilities": "hard_assets",
    }
    try:
        fund = pd.read_parquet(SOURCE / "fundamentals_snapshot.parquet")
    except Exception:
        fund = pd.DataFrame()
    all_uncl = sorted({nm for t in tiers_out.values() for nm in t["unclassified_names"]})
    # Holdings-change detection (FIX 1d): proposals regenerate nightly; note
    # whether any tier's holdings changed vs the prior session.
    holdings_changed = []
    if len(history) >= 2:
        for tid in history[-1]["tiers"]:
            h_now = set(history[-1]["tiers"][tid].get("holdings", []))
            h_prev = set(history[-2]["tiers"].get(tid, {}).get("holdings", []))
            if h_now != h_prev:
                holdings_changed.append(tid)
    proposals = []
    for nm in all_uncl:
        if nm in EXPLICIT_PROPOSALS:
            mapping, rationale = EXPLICIT_PROPOSALS[nm]
            src = "july-audit explicit proposal"
        else:
            sector = str(fund.loc[nm, "sector"]) if (len(fund) and nm in fund.index and "sector" in fund.columns) else ""
            industry = str(fund.loc[nm, "industry"]) if (len(fund) and nm in fund.index and "industry" in fund.columns) else ""
            tid_guess = SECTOR_HEURISTIC.get(sector)
            mapping = {tid_guess: 1.0} if tid_guess else {}
            rationale = f"sector heuristic — {sector or 'unknown'}{(' · ' + industry) if industry and industry != 'nan' else ''} — review before approving"
            src = "sector heuristic"
        proposals.append({"ticker": nm, "proposed": mapping, "rationale": rationale,
                           "source": src, "status": "pending"})
    proposals.append({
        "type": "new_thesis",
        "thesis_id": "memory_semis",
        "label": "Memory semiconductors (sub-thesis of ai_infra)",
        "proposed_members": {"MU": 1.0, "SNDK": 1.0},
        "rationale": ("Bucket-dependence demonstration: with memory split out of "
                       "ai_infra, part of Tier-4 'selection' reclassifies as "
                       "allocation. Approving lets the attribution render under "
                       "both resolutions."),
        "status": "pending",
    })
    prop_payload = {
        "generated_at": datetime.now().isoformat(),
        "as_of": as_of,
        "registry_version_current": registry["version"],
        "registry_frozen": frozen,
        "holdings_changed_today": holdings_changed,
        "note": ("PROPOSALS ONLY — the agent never auto-merges. Werner approves "
                  "by moving entries into thesis_registry.json with a version "
                  "bump. Regenerated nightly; re-checked on any holdings change."),
        "proposals": proposals,
    }
    with open(DATA / "registry_proposals.json", "w") as f:
        json.dump(_clean(prop_payload), f, indent=2, allow_nan=False)
    print(f"  registry_proposals.json: {len(proposals)} proposals "
          f"({len(all_uncl)} unclassified names; holdings changed today: {holdings_changed or 'none'})")

    print(f"  as_of {as_of} · registry v{registry['version']} ({'frozen' if frozen else 'PENDING APPROVAL'})")
    for tid, t in tiers_out.items():
        top = next(iter(t["exposure_invested"].items()), ("—", 0))
        print(f"  {tid:14s} N_eff {t['n_eff']:>5.2f} · top {top[0]} {top[1]*100:.0f}% "
              f"· unclassified {t['unclassified_share']*100:.0f}%"
              f"{' · EXTEND REGISTRY' if t['extend_registry_prompt'] else ''}")
    for tid, a in attribution.items():
        c = a["cum"]
        print(f"  attr {tid:11s} active {c['active']*100:+.2f}% = cash {c['cash_eff']*100:+.2f}% "
              f"+ alloc {c['alloc_eff']*100:+.2f}% + sel {c['selection']*100:+.2f}% "
              f"(max resid {a['check_max_residual_bp']:.3f}bp)")
    if appended:
        print(f"  auto-logged {len(appended)} event-day entries into thesis_claims.json")
    print(f"  saved data/thesis_daily.json")


if __name__ == "__main__":
    main()
