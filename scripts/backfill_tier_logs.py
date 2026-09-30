#!/usr/bin/env python3
"""
backfill_tier_logs.py — order of 30 September 2026, 4.3: the monthly tiers' trade and spell logs.

From data/tournament.json history, every share change of tiers 1–4 (the inception seeding of
2026-05-20 and each monthly reconstitution) becomes a trade row in data/tournament/trades.jsonl:
  shares = Δshares; price = the row's position price (a name that left the tier has no row price on
  the exit row: the close from the price store on that date); cost = C1 (10 bps × |Δweight| in NAV
  space, the weight from the row NAV); reason RECONSTITUTION (SEED on the inception row).
  Scores at decision: data/scored_universe.csv from git history at the nearest commit on or before
  the session (ranked per tier exactly as select_tiers does); Business Quality from the screen's dated
  vintage (data/screen/vintages/<session>/) when one exists, else data/screen/scores.json from git
  history at the nearest commit on or before the session; Trade-Now from data/ticker_signals.json at
  the same rule. Anything unavailable is null with a scores_note.
Every holding spell → data/tournament/spells.jsonl (opened with the entry trade; closed with the exit
trade, excess returns against SPY and the name's thesis basket; follow-ups at +20/+60 sessions after
exit when those sessions have elapsed). Still-open spells carry only their `opened` event.

Idempotent: trades keyed by trade_id (tier, session, ticker, action), spell events by (spell_id,
event); a re-run appends only what is new — so it can run nightly after compute_nav to pick up each
new reconstitution and the follow-ups as they come due. The 5_werner tier is NOT logged here.
Shares the engine's helpers (scripts/compute_twins.py). Nothing here is a recommendation.
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import compute_twins as tw  # noqa: E402

MONTHLY_TIERS = ("1_cap_pres", "2_balanced", "3_aggressive", "4_tactical")


# ──────────────────────────────────────────────────────────────────────────────
# git history lookups (read-only)
# ──────────────────────────────────────────────────────────────────────────────
def git_commit_on_or_before(repo: Path, rel_path: str, session: str) -> tuple[str | None, str | None]:
    """(sha, commit date) of the last commit touching rel_path on or before the session's end (ET)."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--format=%H %cs", f"--before={session}T23:59:59-04:00", "-1", "--", rel_path],
            cwd=repo, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None, None
    if not out:
        return None, None
    sha, cdate = out.split()[0], out.split()[1]
    return sha, cdate


def git_show(repo: Path, sha: str, rel_path: str) -> bytes | None:
    try:
        return subprocess.check_output(["git", "show", f"{sha}:{rel_path}"], cwd=repo, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def score_book_for(session: str, repo: Path, data_dir: Path, tier_specs: dict, use_git: bool) -> tw.ScoreBook:
    """The ScoreBook at decision for a session (see the module docstring for the lookup order)."""
    notes, scored = [], None
    if use_git:
        sha, cdate = git_commit_on_or_before(repo, "data/scored_universe.csv", session)
        if sha:
            raw = git_show(repo, sha, "data/scored_universe.csv")
            if raw:
                scored = pd.read_csv(io.BytesIO(raw))
                if cdate != session:
                    notes.append(f"scores from scored_universe.csv @ {sha[:8]} ({cdate}; nearest commit on or before {session})")
        if scored is None:
            notes.append(f"no scored_universe.csv commit on or before {session}: tier/composite scores null")
    else:
        notes.append("git history not consulted (--no-git): scores null")
    # Business Quality: the screen's dated vintage first (it IS that session's scores.json), then git
    bq, bq_note = {}, None
    vint = data_dir / "screen" / "vintages" / session
    if (vint / "scores.json").exists() or (vint / "scored_universe.csv").exists():
        bq = tw.load_bq(vint / "scores.json", vint / "scored_universe.csv")
        if bq:
            notes.append(f"Business Quality from the screen vintage {session}")
    if not bq and use_git:
        sha, cdate = git_commit_on_or_before(repo, "data/screen/scores.json", session)
        if sha:
            raw = git_show(repo, sha, "data/screen/scores.json")
            if raw:
                with tempfile.TemporaryDirectory() as td:      # never a scratch file under data/
                    tmpp = Path(td) / "scores.json"
                    tmpp.write_bytes(raw)
                    bq = tw.load_bq(tmpp, None)
                if bq:
                    notes.append(f"Business Quality from scores.json @ {sha[:8]} ({cdate})")
    if not bq:
        bq_note = f"Business Quality: no screen vintage or scores.json commit on or before {session}"
    # Trade-Now
    tn, tn_note = {}, None
    if use_git:
        sha, cdate = git_commit_on_or_before(repo, "data/ticker_signals.json", session)
        if sha:
            raw = git_show(repo, sha, "data/ticker_signals.json")
            if raw:
                with tempfile.TemporaryDirectory() as td:
                    tmpp = Path(td) / "ticker_signals.json"
                    tmpp.write_bytes(raw)
                    tn = tw.load_tn(tmpp)
                if tn and cdate != session:
                    notes.append(f"Trade-Now from ticker_signals.json @ {sha[:8]} ({cdate})")
    if not tn:
        tn_note = f"Trade-Now: no ticker_signals.json commit on or before {session}"
    return tw.ScoreBook(scored, tier_specs, bq, tn, note="; ".join(notes) if notes else None,
                        bq_note=bq_note, tn_note=tn_note)


def corridor_labels(data_dir: Path) -> dict:
    """{date: corrected hysteresis label} from regime_v2_daily.csv (the corridor is shaped over the
    whole history each night; the row's own `regime` field is compute_nav's threshold label)."""
    p = data_dir / "regime_v2_daily.csv"
    if not p.exists():
        return {}
    try:
        v = pd.read_csv(p, usecols=["date", "regime"])
        return {str(d)[:10]: str(r) for d, r in zip(v["date"], v["regime"]) if isinstance(r, str)}
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# the backfill
# ──────────────────────────────────────────────────────────────────────────────
def row_weights(td: dict | None) -> dict:
    """A tournament row's NAV-weight vector (positions' value / nav, cash = the remainder); an absent
    row is all cash (the inception's pre-state)."""
    if not td or not float(td.get("nav") or 0.0) > 0:
        return {"_cash": 1.0}
    nav = float(td["nav"])
    w = {p["ticker"]: float(p["value"]) / nav for p in (td.get("positions") or []) if p.get("value")}
    w["_cash"] = max(0.0, 1.0 - sum(w.values()))
    return w


def session_cost(td: dict, prev_td: dict | None, nav_pre: float, cost_rate: float) -> tuple[float, float, str]:
    """(cost, one-way turnover, source): the row's own C1 figure (compute_nav's `rebalance.cost_pct` × the
    pre-rebalance NAV) when the row carries it; else 10 bps × the one-way turnover between the two
    rows' weight vectors (names and cash) on the pre-rebalance NAV — the same convention."""
    turnover = tw.one_way_turnover(row_weights(prev_td), row_weights(td))
    reb = td.get("rebalance") or {}
    if reb.get("cost_pct") is not None:
        return float(reb["cost_pct"]) / 100.0 * nav_pre, float(reb.get("turnover_one_way") or turnover), "tournament.json rebalance.cost_pct"
    return cost_rate * turnover * nav_pre, turnover, "one-way turnover of the two rows' position weights"


def build(history: list[dict], tiers: tuple, store: tw.PriceStore, registry: dict | None, tier_specs: dict,
          cost_rate: float, labels: dict, score_book_fn, existing_trade_ids: set, existing_spell_keys: set,
          as_of_session: str, initial_capital: float = 100000.0) -> tuple[list[dict], list[dict], dict]:
    trades, spells, summary = [], [], {"reconstitution_dates": {}, "open_spells": {}, "closed_spells": {}, "cost": {}}
    books = {}
    for tid in tiers:
        prev_shares: dict[str, float] = {}
        prev_td: dict | None = None
        open_spells: dict[str, dict] = {}
        first = True
        for row in history:
            td = (row.get("tiers") or {}).get(tid)
            if not td or not td.get("shares"):
                continue
            session = str(row["date"])[:10]
            shares = {t: float(s) for t, s in (td.get("shares") or {}).items()}
            changed = sorted(t for t in set(shares) | set(prev_shares) if abs(shares.get(t, 0.0) - prev_shares.get(t, 0.0)) > tw.EPS_SHARES)
            if not changed:
                prev_shares, prev_td = shares, td
                continue
            reason = "SEED" if first else "RECONSTITUTION"
            summary["reconstitution_dates"].setdefault(tid, []).append(session)
            if session not in books:
                books[session] = score_book_fn(session)
            book = books[session]
            nav = float(td.get("nav") or 0.0)
            nav_pre = float(prev_td["nav"]) if (prev_td and prev_td.get("nav")) else initial_capital
            row_px = {p["ticker"]: float(p["price"]) for p in (td.get("positions") or []) if p.get("price")}
            R = row.get("R_t")
            label = labels.get(session) or row.get("regime")
            ids_here: set = set()                     # ids minted on this row (a name has one Δ per row)
            rows_here: list[dict] = []                # every trade row of this session (new or already logged)
            for tk in changed:
                d = shares.get(tk, 0.0) - prev_shares.get(tk, 0.0)
                action = "buy" if d > 0 else "sell"
                price, pnote = row_px.get(tk), None
                if price is None:
                    price, bar = store.close(tk, session)
                    if price is None:
                        print(f"  warn {tid} {session} {tk}: no price anywhere — trade skipped", file=sys.stderr)
                        continue
                    pnote = f"price from the price store ({'bar ' + bar if bar == session else 'last close ' + str(bar)}; name not in the row's positions)"
                scores = book.scores_for(tk, tid)
                if pnote:
                    scores["scores_note"] = "; ".join(x for x in (scores.get("scores_note"), pnote) if x)
                rec = tw.trade_row(tid, session, tk, action, d, price, reason, scores, R, label, "monthly_backfill",
                                   nav_pre, existing_ids=ids_here)
                rows_here.append(rec)
                is_new = rec["trade_id"] not in existing_trade_ids
                if is_new:
                    trades.append(rec)
                    existing_trade_ids.add(rec["trade_id"])
                # spells: 0 → + opens, + → 0 closes
                if prev_shares.get(tk, 0.0) <= tw.EPS_SHARES and shares.get(tk, 0.0) > tw.EPS_SHARES:
                    sid = f"{tid}-{tk}-{session}"
                    sp = {"spell_id": sid, "tier": tid, "ticker": tk, "entry_session": session, "entry_trade_id": rec["trade_id"],
                          "entry_price": rec["price"],
                          "scores_at_entry": {k: rec.get(k) for k in ("tier_composite", "tier_rank", "composite_rank", "bq_score", "tn_score")}}
                    open_spells[tk] = sp
                    if (sid, "opened") not in existing_spell_keys:
                        spells.append(tw.spell_event(sid, "opened", tid, tk, session, rec["trade_id"], rec["price"], sp["scores_at_entry"]))
                        existing_spell_keys.add((sid, "opened"))
                elif prev_shares.get(tk, 0.0) > tw.EPS_SHARES and shares.get(tk, 0.0) <= tw.EPS_SHARES:
                    sp = open_spells.pop(tk, None)
                    if sp is not None and (sp["spell_id"], "closed") not in existing_spell_keys:
                        spells.append(tw.closed_spell_event(sp, session, rec["trade_id"], rec["price"], reason, store, registry,
                                                            detail="left the tier at the monthly reconstitution"))
                        existing_spell_keys.add((sp["spell_id"], "closed"))
            # the session's C1 charge (the row's own figure, else the same one-way turnover), pro rata
            cost, turnover, src = session_cost(td, prev_td, nav_pre, cost_rate)
            tw.allocate_session_cost(rows_here, cost, source=src)
            summary["cost"].setdefault(tid, []).append({"session": session, "nav_pre": round(nav_pre, 2), "turnover_one_way": round(turnover, 6),
                                                        "cost": round(cost, 4), "source": src, "n_rows": len(rows_here)})
            prev_shares, prev_td = shares, td
            first = False
        summary["open_spells"][tid] = sorted(open_spells)
    return trades, spells, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="monthly tiers' trade and spell logs from tournament.json (idempotent)")
    ap.add_argument("--tournament", default=None)
    ap.add_argument("--data-dir", default=None, help="root for regime_v2_daily.csv, screen vintages, thesis registry (default <repo>/data)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--rules", default=None)
    ap.add_argument("--trades", default=None)
    ap.add_argument("--spells", default=None)
    ap.add_argument("--prices", default=None)
    ap.add_argument("--etfs", default=None)
    ap.add_argument("--thesis", default=None)
    ap.add_argument("--repo", default=None, help="git repository for the score history (default: the repo of this script)")
    ap.add_argument("--no-git", action="store_true", help="do not consult git history (scores at decision null)")
    ap.add_argument("--session", default=None, help="as-of session for follow-ups (default: last completed)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else REPO / "data"
    tdir = data_dir / "tournament"
    repo = Path(args.repo) if args.repo else REPO
    cfg = json.load(open(Path(args.config) if args.config else REPO / "config.json"))
    tier_specs = cfg["tier_specs"]
    rules, rules_path = tw.load_rules(Path(args.rules) if args.rules else (tdir / "continuous_rules.json" if args.data_dir else None), cfg)
    cost_rate = float(rules["cost_bps_one_way"]) / 10000.0
    tourn_p = Path(args.tournament) if args.tournament else data_dir / "tournament.json"
    trades_p = Path(args.trades) if args.trades else tdir / "trades.jsonl"
    spells_p = Path(args.spells) if args.spells else tdir / "spells.jsonl"
    prices_p = Path(args.prices) if args.prices else data_dir / "source" / "prices_daily.parquet"
    etfs_p = Path(args.etfs) if args.etfs else data_dir / "source" / "sector_etfs.parquet"
    thesis_p = Path(args.thesis) if args.thesis else data_dir / "thesis_registry.json"
    session = args.session or tw.last_completed_session()

    t = json.load(open(tourn_p))
    history = t.get("history") or []
    store = tw.PriceStore(prices_p, etfs_p)
    registry = json.load(open(thesis_p)) if thesis_p.exists() else None
    labels = corridor_labels(data_dir)
    existing_trades = tw.read_jsonl(trades_p)
    existing_spells = tw.read_jsonl(spells_p)
    existing_ids = {x["trade_id"] for x in existing_trades}
    existing_keys = {(x["spell_id"], x["event"]) for x in existing_spells}

    def book_fn(s):
        return score_book_for(s, repo, data_dir, tier_specs, use_git=not args.no_git)

    initial_capital = float((cfg.get("system_settings") or {}).get("inception_capital_per_tier", rules["start_capital"]))
    trades, spells, summary = build(history, MONTHLY_TIERS, store, registry, tier_specs, cost_rate, labels, book_fn,
                                    existing_ids, existing_keys, session, initial_capital=initial_capital)
    fu = tw.followup_events(existing_spells + spells, session, store, registry, tiers=set(MONTHLY_TIERS))
    spells += fu

    # summary
    print(f"[backfill_tier_logs] tournament rows {len(history)} ({history[0]['date'] if history else '-'} → {history[-1]['date'] if history else '-'}); "
          f"rules {rules_path.name}; as-of {session}")
    for tid in MONTHLY_TIERS:
        print(f"  {tid}: change dates {summary['reconstitution_dates'].get(tid)}")
        for c in summary["cost"].get(tid, []):
            print(f"      {c['session']}: nav_pre {c['nav_pre']:,.2f}  turnover {c['turnover_one_way']:.4f}  cost {c['cost']:.2f}  ({c['source']}; {c['n_rows']} rows)")
        print(f"      total cost {sum(c['cost'] for c in summary['cost'].get(tid, [])):.2f}  total turnover {sum(c['turnover_one_way'] for c in summary['cost'].get(tid, [])):.4f}")
    by = {}
    for r in trades:
        by.setdefault((r["tier"], r["session"]), [0, 0, 0])
        by[(r["tier"], r["session"])][0 if r["action"] == "buy" else 1] += 1
        by[(r["tier"], r["session"])][2] += 1 if r["tier_composite"] is not None else 0
    for (tid, s), (b, sl, sc) in sorted(by.items()):
        print(f"    {tid} {s}: {b} buys, {sl} sells, {sc}/{b+sl} with tier scores")
    ev = {}
    for e in spells:
        ev[e["event"]] = ev.get(e["event"], 0) + 1
    print(f"  new trades {len(trades)} (existing {len(existing_trades)}); new spell events {ev} (existing {len(existing_spells)})")
    if args.dry_run:
        print("  dry run — nothing written")
        return 0
    tw.append_jsonl(trades_p, trades)
    tw.append_jsonl(spells_p, spells)
    print(f"  appended → {trades_p} (+{len(trades)}), {spells_p} (+{len(spells)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
