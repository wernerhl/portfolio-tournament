#!/usr/bin/env python3
"""tournament_audit.py — what the tournament actually does, computed from served data
(Tournament Audit and Execution Order of 30 September 2026, sections 1–2, acceptance 7.2).

From data/tournament.json (every tier's holdings per session) this reproduces, and keeps
reproducing nightly for the tournament page:
  * the reconstitution dates per algorithmic tier and the count of intra-month trades;
  * the gap between each tier's target cash share (recomputed every session from the regime
    index) and the cash it actually held (the month-start trade's residue);
  * the operator tier's re-seed step (NAV before/after, names before/after);
  * the sessions missing from the history (now backfilled and marked) and any missing now;
  * the regime label's changes and its entries into ELEVATED below the corridor's 0.32, against
    the corridor's own count;
  * share classes of one issuer held together;
  * month-to-month name retention per tier (the noise indicator);
  * holding spells per tier with the share that beat SPY over the same window, Wilson intervals,
    the mean excess, and the EFFECTIVE sample — decision dates, not spells.

Spell convention (the one that reproduces the audit's tier-1 figure exactly): entry at the
tier's position price on the first row the name is held; exit at the position price on the
last row it is held (the row before the reconstitution that dropped it), or the last row for
a spell still open; SPY from the rows' benchmark prices over the same window. The price-store
variant (entry-row close to exit-row close) is reported beside it.

Writes data/tournament/audit.json (cadence daily). --report also writes the markdown report.
Usage:  python scripts/tournament_audit.py [--report PATH] [--print] [--allow-non-trading]
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day, now_et  # noqa: E402
from regime_label import corridor_series, ENTRY_EDGES  # noqa: E402

TIERS = ["1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"]
OUT = DATA / "tournament" / "audit.json"


def log(m: str) -> None:
    print(f"[tournament_audit] {m}", flush=True)


def r4(x, nd=4):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else round(f, nd)


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None, None
    p = k / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den; hw = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return r4(c - hw), r4(c + hw)


def positions(h: dict, tid: str) -> dict:
    return {p["ticker"]: p for p in (h["tiers"].get(tid) or {}).get("positions", []) if float(p.get("shares") or 0) > 0}


def share_classes() -> dict:
    p = DATA / "share_classes.json"
    if not p.exists():
        return {}
    j = json.load(open(p))
    out = {}
    for issuer, spec in (j.get("issuers") or {}).items():
        for tk in spec.get("classes", []):
            out[tk] = issuer
    return out


def build(history: list) -> dict:
    H = history
    dates = [h["date"] for h in H]
    # 1. reconstitutions and intra-month trades
    recon, intra = {}, {}
    for tid in TIERS:
        changes, prev = [], None
        for h in H:
            sm = {k: float(v["shares"]) for k, v in positions(h, tid).items()}
            if prev is not None and (set(sm) != set(prev) or any(abs(sm.get(k, 0) - prev.get(k, 0)) > 1e-9 for k in set(sm) | set(prev))):
                changes.append(h["date"])
            prev = sm
        recon[tid] = [d for d in changes if date.fromisoformat(d).day <= 3]
        intra[tid] = [d for d in changes if date.fromisoformat(d).day > 3]
    # 2. cash gaps
    gaps = {}
    for tid in TIERS:
        g = [(h["date"], float(h["tiers"][tid]["target_cash_pct"]) - float(h["tiers"][tid]["actual_cash_pct"])) for h in H]
        absg = [abs(x) for _, x in g]
        worst = max(g, key=lambda t: abs(t[1]))
        gaps[tid] = {"mean_abs_points": r4(float(np.mean(absg)), 1), "max_abs_points": r4(max(absg), 1), "max_on": worst[0],
                     "sessions_over_5_points": int(sum(1 for x in absg if x > 5)), "n_sessions": len(absg),
                     "on_2026-06-03": next((r4(x, 1) for d, x in g if d == "2026-06-03"), None),
                     "on_2026-07-29": next((r4(x, 1) for d, x in g if d == "2026-07-29"), None)}
    all_abs = [abs(float(h["tiers"][tid]["target_cash_pct"]) - float(h["tiers"][tid]["actual_cash_pct"])) for h in H for tid in TIERS]
    gaps["all_tiers"] = {"mean_abs_points": r4(float(np.mean(all_abs)), 1), "max_abs_points": r4(max(all_abs), 1)}
    # 3. operator tier
    w = [(h["date"], h["tiers"]["5_werner"]["nav"], sorted(positions(h, "5_werner"))) for h in H if h["tiers"].get("5_werner")]
    reseeds = []
    for i in range(1, len(w)):
        if w[i][2] != w[i - 1][2]:
            reseeds.append({"date": w[i][0], "nav_before": w[i - 1][1], "nav_after": w[i][1], "step_pct": r4((w[i][1] / w[i - 1][1] - 1) * 100, 2),
                            "names_before": w[i - 1][2], "names_after": w[i][2]})
    nav_on = lambda d: next((x[1] for x in w if x[0] == d), None)
    n15, n29 = nav_on("2026-09-15"), nav_on("2026-09-29")
    operator = {"nav_2026-09-15": n15, "nav_2026-09-29": n29,
                "step_2026-09-15_to_29_pct": r4((n29 / n15 - 1) * 100, 2) if (n15 and n29) else None,
                "step_note": "the order's 27.9 percent compares the published rows of 15 and 29 September; the re-seed event's own step is measured against the backfilled 28 September row",
                "reseed_events": reseeds,
                "comparable": False, "note": "the tier held the configuration's picks until 29 September, then was re-seeded from the holdings file; not comparable until rebuilt from the brokerage transactions export (order 30-Sept 4.4)"}
    # 4. missing sessions
    d0, d1 = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1]); exp = []; d = d0
    while d <= d1:
        if is_trading_day(d.isoformat()):
            exp.append(d.isoformat())
        d += timedelta(days=1)
    missing_now = [x for x in exp if x not in set(dates)]
    backfilled = [h["date"] for h in H if h.get("backfilled")]
    # 5. regime label
    labs = [(h["date"], float(h["R_t"]), h["regime"]) for h in H]
    flips = [{"date": labs[i][0], "R": labs[i][1], "from": labs[i - 1][2], "to": labs[i][2]} for i in range(1, len(labs)) if labs[i][2] != labs[i - 1][2]]
    entries_elev = [f for f in flips if f["to"] == "ELEVATED" and f["from"] == "LOW RISK"]
    below = [f for f in entries_elev if f["R"] < ENTRY_EDGES[0]]
    corr = corridor_series([x[1] for x in labs])
    corr_flips = sum(1 for i in range(1, len(corr)) if corr[i] != corr[i - 1])
    corr_entries = [{"date": labs[i][0], "R": labs[i][1]} for i in range(1, len(corr)) if corr[i] == "ELEVATED" and corr[i - 1] == "LOW RISK"]
    by_month = {}
    for f in flips:
        by_month[f["date"][:7]] = by_month.get(f["date"][:7], 0) + 1
    regime = {"label_changes_published": len(flips), "changes_by_month": by_month, "entries_into_elevated": entries_elev,
              "entries_below_corridor_0_32": below, "corridor_label_changes_same_history": corr_flips, "corridor_entries_into_elevated": corr_entries,
              "corridor_in_force_from": "2026-09-30 (rows from this date carry the corridor label; earlier labels are as published)"}
    # 6. share classes held together (last row)
    sc = share_classes()
    last = H[-1]; dup = []
    for tid in TIERS + ["5_werner"]:
        by_issuer = {}
        for tk, p in positions(last, tid).items():
            if tk in sc:
                by_issuer.setdefault(sc[tk], []).append((tk, float(p.get("weight") or 0)))
        for issuer, lst in by_issuer.items():
            if len(lst) > 1:
                dup.append({"tier": tid, "issuer": issuer, "classes": [t for t, _ in lst], "combined_weight_pct": r4(sum(x for _, x in lst), 1)})
    # 7. retention
    retention = {}
    for tid in TIERS:
        prev, out = None, []
        for h in H:
            n = set(positions(h, tid))
            if prev is not None and n != prev:
                out.append({"date": h["date"], "kept": len(n & prev), "of": len(prev), "retention": r4(len(n & prev) / len(prev), 3) if prev else None})
            prev = n
        retention[tid] = out
    # 8. spells (V1 convention) and the store variant
    px = pd.read_parquet(DATA / "source" / "prices_daily.parquet"); px.index = pd.to_datetime(px.index)
    etf = pd.read_parquet(DATA / "source" / "sector_etfs.parquet"); etf.index = pd.to_datetime(etf.index)
    spy_row = {h["date"]: float(h["benchmarks"]["spy"]["price"]) for h in H if (h.get("benchmarks") or {}).get("spy", {}).get("price")}
    def close_store(tk, d):
        if tk not in px.columns:
            return None
        s = px[tk].dropna(); s = s[s.index <= pd.Timestamp(d)]; return float(s.iloc[-1]) if len(s) else None
    def spy_store(d):
        s = etf["spy"].dropna(); s = s[s.index <= pd.Timestamp(d)]; return float(s.iloc[-1])
    spells, per_tier = [], {}
    for tid in TIERS:
        open_, prev = {}, None
        for i, h in enumerate(H):
            n = set(positions(h, tid))
            if prev is None:
                for tk in n: open_[tk] = i
            else:
                for tk in n - prev: open_[tk] = i
                for tk in prev - n: spells.append((tid, tk, open_.pop(tk), i, "closed"))
            prev = n
        for tk, e in open_.items(): spells.append((tid, tk, e, len(H) - 1, "open"))
    rows = []
    for tid, tk, e, x, st in spells:
        xe = x if st == "open" else x - 1
        p0 = float(positions(H[e], tid)[tk]["price"]); p1 = positions(H[xe], tid).get(tk, {}).get("price")
        rec = {"tier": tid, "ticker": tk, "entry": H[e]["date"], "exit": H[x]["date"] if st == "closed" else None, "last_held": H[xe]["date"], "status": st}
        if p1 and spy_row.get(H[e]["date"]) and spy_row.get(H[xe]["date"]):
            rec["excess_vs_spy"] = r4((float(p1) / p0 - 1) - (spy_row[H[xe]["date"]] / spy_row[H[e]["date"]] - 1))
        s0, s1 = close_store(tk, H[e]["date"]), close_store(tk, H[x]["date"])
        if s0 and s1:
            rec["excess_vs_spy_store"] = r4((s1 / s0 - 1) - (spy_store(H[x]["date"]) / spy_store(H[e]["date"]) - 1))
        rows.append(rec)
    for tid in TIERS:
        a = np.array([r["excess_vs_spy"] for r in rows if r["tier"] == tid and r.get("excess_vs_spy") is not None])
        b = np.array([r["excess_vs_spy_store"] for r in rows if r["tier"] == tid and r.get("excess_vs_spy_store") is not None])
        k = int((a > 0).sum()); lo, hi = wilson(k, len(a))
        dec = sorted({r["entry"] for r in rows if r["tier"] == tid})
        best = sorted([r for r in rows if r["tier"] == tid and r.get("excess_vs_spy") is not None], key=lambda r: -r["excess_vs_spy"])[:3]
        per_tier[tid] = {"n_spells": int(len(a)), "beat_spy": k, "share_beat_spy": r4(k / len(a), 3) if len(a) else None,
                         "wilson_95": [lo, hi], "mean_excess": r4(float(a.mean())) if len(a) else None,
                         "effective_sample_decision_dates": len(dec), "decision_dates": dec,
                         "store_variant": {"n": int(len(b)), "share_beat_spy": r4(float((b > 0).mean()), 3) if len(b) else None, "mean_excess": r4(float(b.mean())) if len(b) else None},
                         "best_spells": [{"ticker": r["ticker"], "entry": r["entry"], "excess_vs_spy": r["excess_vs_spy"]} for r in best]}
    spells_block = {"n_spells": len(rows), "convention": "entry at the tier's position price on the first held row; exit at the position price on the last held row (open spells: the last row); SPY from the rows' benchmark prices",
                    "per_tier": per_tier, "spells": rows,
                    "note": "the spells were chosen on a handful of dates and share factor exposure; the effective sample is the number of decision dates, not spells; no inference is possible from these intervals"}
    return {"cadence": "daily", "session_date": H[-1]["date"], "as_of": H[-1]["date"], "computed_at": now_et().isoformat(timespec="seconds"),
            "rows": len(H), "first": dates[0], "last": dates[-1],
            "reconstitutions": recon, "intra_month_trades": {k: len(v) for k, v in intra.items()}, "intra_month_trade_dates": intra,
            "cash_gap": gaps, "operator_tier": operator, "missing_sessions_now": missing_now, "backfilled_sessions": backfilled,
            "regime_label": regime, "share_classes_held_together": dup, "retention": retention, "spells": spells_block,
            "note": "descriptive audit of served data; nothing here is a recommendation"}


def markdown(a: dict) -> str:
    L = [f"# Tournament audit — reproduced from served data ({a['session_date']})", "",
         f"`data/tournament.json`: {a['rows']} rows, {a['first']} → {a['last']} ({len(a['backfilled_sessions'])} backfilled: {', '.join(a['backfilled_sessions'])}; missing now: {a['missing_sessions_now'] or 'none'}).", "",
         "## Reconstitution dates and intra-month trades", "", "| tier | reconstitutions | intra-month trades |", "|---|---|---|"]
    for tid in TIERS:
        L.append(f"| {tid} | {', '.join(a['reconstitutions'][tid])} | {a['intra_month_trades'][tid]} |")
    L += ["", "## Cash gap (target − actual, points)", "", "| tier | mean abs | max abs (on) | sessions > 5 | 3 June | 29 July |", "|---|---|---|---|---|---|"]
    for tid in TIERS:
        g = a["cash_gap"][tid]
        L.append(f"| {tid} | {g['mean_abs_points']} | {g['max_abs_points']} ({g['max_on']}) | {g['sessions_over_5_points']} of {g['n_sessions']} | {g['on_2026-06-03']} | {g['on_2026-07-29']} |")
    L.append(f"| all | {a['cash_gap']['all_tiers']['mean_abs_points']} | {a['cash_gap']['all_tiers']['max_abs_points']} | | | |")
    o = a["operator_tier"]
    L += ["", "## Operator tier", "", f"NAV 2026-09-15 ${o['nav_2026-09-15']:,.2f}; 2026-09-29 ${o['nav_2026-09-29']:,.2f}."]
    for e in o["reseed_events"]:
        L.append(f"Re-seed {e['date']}: ${e['nav_before']:,.2f} → ${e['nav_after']:,.2f} ({e['step_pct']:+.1f}%); {', '.join(e['names_before'])} → {', '.join(e['names_after'])}.")
    r = a["regime_label"]
    L += ["", "## Regime label", "", f"Published label changes: {r['label_changes_published']} ({', '.join(f'{k} {v}' for k, v in sorted(r['changes_by_month'].items()))}). Entries into ELEVATED below 0.32: " +
          (", ".join(f"{f['date']} at {f['R']}" for f in r["entries_below_corridor_0_32"]) or "none") +
          f". The corridor over the same history: {r['corridor_label_changes_same_history']} changes; entries into ELEVATED at " + ", ".join(f"{e['date']} ({e['R']})" for e in r["corridor_entries_into_elevated"]) + "."]
    L += ["", "## Share classes held together", ""] + ([f"- {d['tier']}: {', '.join(d['classes'])} ({d['issuer']}) {d['combined_weight_pct']}% combined" for d in a["share_classes_held_together"]] or ["none"])
    L += ["", "## Name retention per reconstitution (kept / previous N)", "", "| tier | " + " | ".join(x["date"] for x in a["retention"][TIERS[0]]) + " |", "|---|" + "---|" * len(a["retention"][TIERS[0]])]
    for tid in TIERS:
        L.append(f"| {tid} | " + " | ".join(f"{x['kept']}/{x['of']}" for x in a["retention"][tid]) + " |")
    s = a["spells"]
    L += ["", f"## Holding spells ({s['n_spells']}) — share that beat SPY over the same window", "", "| tier | spells | beat SPY | Wilson 95% | mean excess | decision dates | store variant |", "|---|---|---|---|---|---|---|"]
    for tid in TIERS:
        p = s["per_tier"][tid]; sv = p["store_variant"]
        L.append(f"| {tid} | {p['n_spells']} | {p['share_beat_spy']*100:.0f}% | [{p['wilson_95'][0]*100:.0f}, {p['wilson_95'][1]*100:.0f}] | {p['mean_excess']*100:+.1f}% | {p['effective_sample_decision_dates']} | {sv['share_beat_spy']*100:.0f}%, {sv['mean_excess']*100:+.1f}% |")
    L += ["", s["convention"] + ".", "", s["note"] + "."]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None)
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--allow-non-trading", action="store_true")
    args = ap.parse_args()
    import errata
    H = errata.apply_history(json.load(open(DATA / "tournament.json"))["history"])   # F2 (7-Oct-2026): corrected values
    a = build(H)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(a, indent=1, default=str) + "\n")
    log(f"wrote {OUT.relative_to(REPO)}: {a['rows']} rows, {a['spells']['n_spells']} spells, {len(a['backfilled_sessions'])} backfilled, {len(a['missing_sessions_now'])} missing now")
    if args.report:
        Path(args.report).write_text(markdown(a))
        log(f"wrote {args.report}")
    if args.do_print:
        print(markdown(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
