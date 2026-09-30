#!/usr/bin/env python3
"""
monthly_review.py — order 30-Sept-2026, section 5: the monthly review written from the ledgers.

The order, quoted:
    "Each month the system writes a review from the ledgers: the five worst spells per tier with
    their scores at entry, the operator's trades against their not-traded alternatives, and every
    new system failure with its fix. Findings are stated with the effective sample size (decision
    dates, not spells) and a date-block bootstrap interval. A lesson becomes a rule only through a
    registration and a prospective test; a lesson is never applied retroactively to history. The
    review is generated, stored, and never edited."

What it writes
    reports/reviews/review_<YYYY-MM>.md     the review — the previous calendar month by default,
                                            --month YYYY-MM to choose
    data/tournament/reviews.jsonl           one appended index line per review written:
        {"month", "file", "generated_at", "sha256", "effective_samples": {tier: decision dates},
         "n_spells", "version", "earlier_reviews", "reason"}

Never edited
    A review file that exists is never overwritten. A second run for the same month refuses and
    writes nothing (exit code 2). --force-new writes review_<YYYY-MM>_v2.md (then _v3, ...) whose
    header names the earlier file(s), their hashes and the stated --reason; the earlier files are
    untouched.

Inputs (each optional — an absent file is reported as absent with 0 rows and its section says so)
    data/tournament/spells.jsonl    one line per spell EVENT (opened | closed | followup_20 |
                                    followup_60). A spell's state is its latest event; its
                                    realised figures are those of its "closed" event.
    data/tournament/trades.jsonl    the tiers' trades; scores at entry come from the spell event,
                                    else from the entry trade found by entry_trade_id
    data/mistakes.jsonl             the mistakes ledger: kind failure | operator_decision |
                                    outcome | correction
    data/actions.jsonl              the action log; source "brokerage transactions" = the
                                    operator's export-confirmed trades; source "operator report,
                                    pending export confirmation" = provisional entries
    data/source/prices_daily.parquet, data/source/sector_etfs.parquet (column "spy")
                                    closes, used only to mark spells open at month end
                                    (.csv with a date index is accepted for the same role)

The sample for a tier's month: spells CLOSED in the month (exit_session inside it) plus spells
OPEN at month end (entered on or before the month's last session and not closed by then), the
latter marked at the last session of the month that has a price row and labelled as open.
Return figures in the ledger are read as fractions of the entry price (0.05 = 5 percent).

Effective sample size = the number of distinct entry sessions (decision dates) in the sample —
never the spell count. The 90 percent interval for the hit rate vs SPY and for the mean excess
comes from a date-block bootstrap: decision dates are resampled with replacement, each drawn
date carrying ALL its spells; 2000 resamples; seed 20260930; percentiles 5 and 95. With fewer
than 5 decision dates the interval is printed with the caption that it is not informative.

Vocabulary: the two words the brief validator prohibits (daily_brief.PROHIBITED) are withheld
from quoted ledger text ("[word withheld]", counted in the header); the review's own prose uses
neither them nor the projection verbs the brief validator rejects (data/brief_rules.json).

Usage
    python scripts/monthly_review.py [--month YYYY-MM] [--force-new --reason "..."] [--dry-run]
        [--repo DIR] [--spells F] [--trades F] [--mistakes F] [--actions F] [--prices F]
        [--etfs F] [--out-dir DIR] [--index F]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day, now_et  # noqa: E402

SEED = 20260930
N_RESAMPLES = 2000
CI_LEVEL = 0.90
MIN_DATES_INFORMATIVE = 5
N_WORST = 5
MAX_LESSONS = 3
MONTHLY_TIERS = ["1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"]
TWIN_OF = {"1c": "1_cap_pres", "2c": "2_balanced", "3c": "3_aggressive", "4c": "4_tactical"}
TIER_NAMES = {"1_cap_pres": "Capital preservation", "2_balanced": "Balanced",
              "3_aggressive": "Aggressive", "4_tactical": "Tactical"}
EVENT_RANK = {"opened": 0, "closed": 1, "followup_20": 2, "followup_60": 3}
SCORE_KEYS = ("tier_composite", "tier_rank", "composite_rank", "bq_score", "tn_score")
SOURCE_EXPORT = "brokerage transactions"
SOURCE_PROVISIONAL = "operator report, pending export confirmation"
OUTCOME_HORIZONS = (20, 60)
# candidate-lesson thresholds (stated in section 5 of every review)
LESSON_MIN_EVALUATED = 6          # spells with a figure before a split is examined
LESSON_MIN_SIDE = 3               # spells on each side of a split
LESSON_MIN_HIT_GAP = 0.25         # hit-rate difference between the two sides
LESSON_EXIT_REASON_MIN = 3        # of the five worst sharing one exit reason
LESSON_OPERATOR_MIN = 2           # operator decisions with a +60 outcome, all on one side

DEFAULT_PATHS = {
    "spells": "data/tournament/spells.jsonl", "trades": "data/tournament/trades.jsonl",
    "mistakes": "data/mistakes.jsonl", "actions": "data/actions.jsonl",
    "prices": "data/source/prices_daily.parquet", "etfs": "data/source/sector_etfs.parquet",
    "out_dir": "reports/reviews", "index": "data/tournament/reviews.jsonl",
}


# ─── vocabulary ──────────────────────────────────────────────────────────────────────────
def prohibited_words() -> tuple:
    """The brief validator's two prohibited words, taken from its module — never spelled here."""
    try:
        from daily_brief import PROHIBITED  # noqa: WPS433
        return tuple(PROHIBITED)
    except Exception:  # noqa: BLE001
        return ()


def projection_words(rules_path: Path | None = None) -> tuple:
    """The verbs the brief validator rejects, from data/brief_rules.json (narrative section)."""
    p = Path(rules_path) if rules_path else DATA / "brief_rules.json"
    try:
        with open(p, encoding="utf-8") as f:
            return tuple(json.load(f)["narrative"]["forecast_words"])
    except Exception:  # noqa: BLE001
        return ()


def word_hits(text: str, words) -> dict:
    """Whole-word, case-insensitive counts of each word in `text` (only the words found)."""
    out = {}
    for w in words:
        n = len(re.findall(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", text, flags=re.IGNORECASE))
        if n:
            out[w] = n
    return out


def withhold(text, words) -> tuple:
    """Replace each whole-word occurrence of `words` in quoted ledger text; returns (text, n replaced)."""
    if text is None:
        return None, 0
    s, n = str(text), 0
    for w in words:
        s, k = re.subn(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", "[word withheld]", s, flags=re.IGNORECASE)
        n += k
    return s, n


# ─── loading ─────────────────────────────────────────────────────────────────────────────
def load_jsonl(path) -> tuple:
    """(rows, meta) — meta: exists, rows, bad lines."""
    p = Path(path)
    rows, bad = [], 0
    if not p.exists():
        return rows, {"path": str(p), "exists": False, "rows": 0, "bad": 0}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                bad += 1
    return rows, {"path": str(p), "exists": True, "rows": len(rows), "bad": bad}


def load_closes(path):
    """Closes by ticker with a DatetimeIndex, from .parquet or .csv (first column = date)."""
    p = Path(path)
    if not p.exists():
        return None
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p, index_col=0)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def closes_meta(df, path) -> dict:
    if df is None:
        return {"path": str(path), "exists": False, "rows": 0, "columns": 0, "last": None}
    return {"path": str(path), "exists": True, "rows": int(df.shape[0]), "columns": int(df.shape[1]),
            "last": df.index[-1].strftime("%Y-%m-%d") if len(df.index) else None}


def close_on(df, ticker, session):
    """The close of `ticker` on `session` (exact date row), or None."""
    if df is None or not ticker or not session:
        return None
    col = None
    for cand in (ticker, str(ticker).upper(), str(ticker).lower()):
        if cand in df.columns:
            col = cand
            break
    if col is None:
        return None
    try:
        v = df.at[pd.Timestamp(session[:10]), col]
    except KeyError:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


# ─── calendar ────────────────────────────────────────────────────────────────────────────
def month_bounds(month: str) -> tuple:
    y, m = int(month[:4]), int(month[5:7])
    first = date(y, m, 1)
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return first, nxt - timedelta(days=1)


def month_sessions(month: str) -> list:
    first, last = month_bounds(month)
    d, out = first, []
    while d <= last:
        if is_trading_day(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def nth_session_after(session: str, n: int) -> str:
    d, k = date.fromisoformat(session[:10]), 0
    while k < n:
        d += timedelta(days=1)
        if is_trading_day(d):
            k += 1
    return d.isoformat()


def sessions_between(a: str, b: str) -> int:
    """Trading sessions in (a, b]."""
    if not a or not b or b[:10] <= a[:10]:
        return 0
    d, end, k = date.fromisoformat(a[:10]), date.fromisoformat(b[:10]), 0
    while d < end:
        d += timedelta(days=1)
        if is_trading_day(d):
            k += 1
    return k


def previous_month(today: date) -> str:
    first = today.replace(day=1)
    prev = first - timedelta(days=1)
    return prev.strftime("%Y-%m")


# ─── spells ──────────────────────────────────────────────────────────────────────────────
def spell_states(events: list) -> dict:
    """spell_id → {opened, closed, latest, n_events, tier, ticker, entry_session}."""
    by_id = defaultdict(list)
    for e in events:
        sid = e.get("spell_id")
        if sid is None:
            continue
        by_id[sid].append(e)
    states = {}
    for sid, evs in by_id.items():
        evs = sorted(evs, key=lambda e: (EVENT_RANK.get(e.get("event"), 9), str(e.get("logged_at") or "")))
        opened = next((e for e in evs if e.get("event") == "opened"), evs[0])
        closed = next((e for e in reversed(evs) if e.get("event") == "closed"), None)
        if closed is None and opened.get("exit_session"):
            closed = opened      # a single-line spell that already carries its exit
        states[sid] = {"spell_id": sid, "opened": opened, "closed": closed, "latest": evs[-1], "n_events": len(evs),
                       "tier": opened.get("tier") or evs[-1].get("tier"), "ticker": opened.get("ticker") or evs[-1].get("ticker"),
                       "entry_session": str(opened.get("entry_session") or evs[-1].get("entry_session") or "")[:10] or None}
    return states


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def scores_for(event: dict, trade: dict | None) -> dict:
    s = event.get("scores_at_entry") or {}
    out = {}
    for k in SCORE_KEYS:
        v = s.get(k)
        if v is None and trade is not None:
            v = trade.get(k)
        out[k] = v
    return out


def build_sample(states: dict, month: str, prices, etfs, trades_by_id: dict) -> tuple:
    """Rows of the month's sample across tiers, and the marking context."""
    first, last = month_bounds(month)
    sessions = month_sessions(month)
    last_session = sessions[-1] if sessions else last.isoformat()
    first_iso, last_iso = first.isoformat(), last.isoformat()
    mark_session, mark_available = last_session, False
    if prices is not None and len(prices.index):
        in_month = prices.index[(prices.index >= pd.Timestamp(first_iso)) & (prices.index <= pd.Timestamp(last_iso))]
        if len(in_month):
            mark_session, mark_available = in_month[-1].strftime("%Y-%m-%d"), True
    rows = []
    for st in states.values():
        entry = st["entry_session"]
        closed = st["closed"]
        exit_s = str(closed.get("exit_session") or "")[:10] if closed else ""
        if closed is not None and exit_s:
            if first_iso <= exit_s <= last_iso:
                status = "closed"
            elif exit_s > last_iso and entry and entry <= last_session:
                status = "open"
            else:
                continue
        else:
            if entry and entry <= last_session:
                status = "open"
            else:
                continue
        ev = closed if status == "closed" else st["opened"]
        trade = trades_by_id.get(ev.get("entry_trade_id")) if ev.get("entry_trade_id") is not None else None
        row = {"spell_id": st["spell_id"], "tier": st["tier"], "ticker": st["ticker"], "status": status,
               "entry_session": entry, "entry_price": _f(ev.get("entry_price")), "entry_trade_id": ev.get("entry_trade_id"),
               "exit_session": None, "exit_price": None, "exit_reason": None, "sessions_held": None,
               "ret": None, "spy_ret": None, "excess_spy": None, "basket_ret": None, "excess_basket": None,
               "basket_thesis": ev.get("basket_thesis"), "scores": scores_for(ev, trade),
               "regime_label": (trade or {}).get("regime_label"), "note": None, "n_events": st["n_events"]}
        if status == "closed":
            row.update({"exit_session": exit_s, "exit_price": _f(ev.get("exit_price")), "exit_reason": ev.get("exit_reason"),
                        "sessions_held": ev.get("sessions_held"), "ret": _f(ev.get("return")), "spy_ret": _f(ev.get("spy_return")),
                        "excess_spy": _f(ev.get("excess_vs_spy")), "basket_ret": _f(ev.get("basket_return")),
                        "excess_basket": _f(ev.get("excess_vs_basket"))})
            if row["excess_spy"] is None and row["ret"] is not None and row["spy_ret"] is not None:
                row["excess_spy"] = row["ret"] - row["spy_ret"]
            if row["excess_spy"] is None:
                row["note"] = "closed event carries no excess vs SPY; not evaluated"
        else:
            row["exit_reason"] = "open at month end"
            if not mark_available:
                row["note"] = "open at month end; no price row in the month, not marked"
            else:
                px_entry = row["entry_price"] if row["entry_price"] else close_on(prices, st["ticker"], entry)
                px_mark = close_on(prices, st["ticker"], mark_session)
                spy_entry = close_on(etfs, "spy", entry)
                spy_mark = close_on(etfs, "spy", mark_session)
                if px_entry and px_mark and spy_entry and spy_mark:
                    row["ret"] = px_mark / px_entry - 1.0
                    row["spy_ret"] = spy_mark / spy_entry - 1.0
                    row["excess_spy"] = row["ret"] - row["spy_ret"]
                    row["exit_session"] = mark_session
                    row["exit_price"] = px_mark
                    row["sessions_held"] = sessions_between(entry, mark_session)
                    row["note"] = f"open at month end; marked at the {mark_session} close"
                else:
                    missing = [n for n, v in (("entry price", px_entry), (f"{st['ticker']} close", px_mark),
                                              ("SPY at entry", spy_entry), ("SPY at mark", spy_mark)) if not v]
                    row["note"] = "open at month end; not marked (" + ", ".join(missing) + " unavailable)"
        rows.append(row)
    rows.sort(key=lambda r: (str(r["tier"]), str(r["entry_session"]), str(r["spell_id"])))
    ctx = {"first_session": sessions[0] if sessions else None, "last_session": last_session, "n_sessions": len(sessions),
           "mark_session": mark_session, "mark_available": mark_available}
    return rows, ctx


# ─── statistics ──────────────────────────────────────────────────────────────────────────
def date_block_bootstrap(groups: dict, n_resamples: int = N_RESAMPLES, seed: int = SEED,
                         level: float = CI_LEVEL, keep_draws: bool = False) -> dict:
    """Resample decision DATES with replacement (each drawn date carries all its spells) and read
    the hit rate (excess > 0) and the mean excess of the pooled draw; percentile interval."""
    dates = sorted(groups)
    n_dates = len(dates)
    n_spells = int(sum(len(groups[d]) for d in dates))
    out = {"n_dates": n_dates, "n_spells": n_spells, "n_resamples": n_resamples, "seed": seed, "level": level,
           "hit_rate_ci": None, "mean_excess_ci": None, "informative": n_dates >= MIN_DATES_INFORMATIVE}
    if n_dates == 0 or n_spells == 0:
        return out
    arrays = [np.asarray(groups[d], dtype=float) for d in dates]
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_dates, size=(n_resamples, n_dates))
    hits = np.empty(n_resamples)
    means = np.empty(n_resamples)
    for i in range(n_resamples):
        pooled = np.concatenate([arrays[j] for j in draws[i]])
        hits[i] = float(np.mean(pooled > 0))
        means[i] = float(pooled.mean())
    lo, hi = (1.0 - level) / 2.0 * 100.0, (1.0 + level) / 2.0 * 100.0
    out["hit_rate_ci"] = [float(np.percentile(hits, lo)), float(np.percentile(hits, hi))]
    out["mean_excess_ci"] = [float(np.percentile(means, lo)), float(np.percentile(means, hi))]
    if keep_draws:
        out["draws"] = draws
        out["hits"] = hits
        out["means"] = means
    return out


def tier_result(tier: str, rows: list) -> dict:
    evaluated = [r for r in rows if r["excess_spy"] is not None]
    worst = sorted(evaluated, key=lambda r: (r["excess_spy"], str(r["spell_id"])))[:N_WORST]
    groups = defaultdict(list)
    for r in evaluated:
        groups[r["entry_session"]].append(r["excess_spy"])
    decision_sessions = sorted({r["entry_session"] for r in rows if r["entry_session"]})
    n_hit = sum(1 for r in evaluated if r["excess_spy"] > 0)
    exc = [r["excess_spy"] for r in evaluated]
    return {"tier": tier, "n_spells": len(rows), "n_closed": sum(1 for r in rows if r["status"] == "closed"),
            "n_open_marked": sum(1 for r in rows if r["status"] == "open" and r["excess_spy"] is not None),
            "n_not_evaluated": len(rows) - len(evaluated), "n_evaluated": len(evaluated),
            "hits": n_hit, "hit_rate": (n_hit / len(evaluated)) if evaluated else None,
            "mean_excess": float(np.mean(exc)) if exc else None, "median_excess": float(np.median(exc)) if exc else None,
            "decision_sessions": decision_sessions, "effective_sample": len(decision_sessions),
            "bootstrap": date_block_bootstrap(dict(groups)), "worst": worst,
            "exit_reasons": dict(Counter(str(r["exit_reason"]) for r in evaluated))}


# ─── the operator and the system ─────────────────────────────────────────────────────────
def _in_month(s, month) -> bool:
    return bool(s) and str(s)[:7] == month


def operator_section(mistakes: list, actions: list, month: str, mark_session: str | None) -> dict:
    decisions = [m for m in mistakes if m.get("kind") == "operator_decision" and _in_month(m.get("session"), month)]
    outcomes = defaultdict(dict)
    for m in mistakes:
        if m.get("kind") == "outcome" and m.get("refers_to") is not None:
            try:
                h = int(m.get("horizon"))
            except (TypeError, ValueError):
                continue
            outcomes[m["refers_to"]][h] = m
    export = [a for a in actions if a.get("source") == SOURCE_EXPORT and _in_month(a.get("session_date"), month)]
    provisional = [a for a in actions if a.get("source") == SOURCE_PROVISIONAL and _in_month(a.get("session_date"), month)]

    def act_of(a):
        x = a.get("action")
        return x[0] if isinstance(x, list) and x else x

    def match_export(d):
        for a in export:
            if a.get("ticker") == d.get("ticker") and str(a.get("session_date") or "")[:10] == str(d.get("session") or "")[:10] \
                    and (d.get("action") is None or act_of(a) == d.get("action")):
                return a
        return None

    rows = []
    for d in decisions:
        outs = outcomes.get(d.get("entry_id"), {})
        sess = str(d.get("session") or "")[:10]
        due = {h: nth_session_after(sess, h) for h in OUTCOME_HORIZONS} if sess else {}
        rows.append({"entry_id": d.get("entry_id"), "session": sess, "ticker": d.get("ticker"), "action": d.get("action"),
                     "stated_reason": d.get("stated_reason"), "outcomes": {h: outs.get(h) for h in OUTCOME_HORIZONS},
                     "due": due, "export": match_export(d), "found": d.get("found")})
    matched_ids = {id(r["export"]) for r in rows if r["export"] is not None}
    unmatched_export = [a for a in export if id(a) not in matched_ids]
    return {"decisions": rows, "export_trades": export, "unmatched_export": unmatched_export, "provisional": provisional,
            "n_export": len(export), "n_decisions": len(decisions), "mark_session": mark_session}


def failures_section(mistakes: list, month: str) -> dict:
    new = [m for m in mistakes if m.get("kind") == "failure" and _in_month(m.get("found"), month)]
    earlier = [m for m in mistakes if m.get("kind") == "failure" and m.get("found") and str(m["found"])[:7] < month]
    corrections = [m for m in mistakes if m.get("kind") == "correction" and _in_month(m.get("found") or m.get("logged_at"), month)]

    def norm(s):
        return re.sub(r"\s+", " ", str(s or "").strip().lower())[:60]

    recurrences = []
    for f in new:
        key = norm(f.get("error"))
        if not key:
            continue
        for e in earlier:
            if norm(e.get("error")) == key:
                recurrences.append({"new": f, "earlier": e})
                break
    return {"failures": new, "n_failures": len(new), "corrections": corrections, "recurrences": recurrences}


# ─── candidate lessons (hypotheses for registration; never applied) ──────────────────────
def _hit(rows):
    n = len(rows)
    k = sum(1 for r in rows if r["excess_spy"] > 0)
    return k, n


def candidate_lessons(tiers: dict, sample_rows: list, operator: dict, failures: dict) -> list:
    cands = []
    for tier, tr in tiers.items():
        evaluated = [r for r in sample_rows if r["tier"] == tier and r["excess_spy"] is not None]
        if len(evaluated) < LESSON_MIN_EVALUATED:
            continue
        n_dates = len({r["entry_session"] for r in evaluated})
        ci = tr["bootstrap"]["hit_rate_ci"]
        # (a) exit-reason concentration among the five worst
        reasons = Counter(str(r["exit_reason"]) for r in tr["worst"])
        if reasons:
            reason, k = reasons.most_common(1)[0]
            if k >= LESSON_EXIT_REASON_MIN:
                a, b = _hit([r for r in evaluated if str(r["exit_reason"]) == reason])
                c, d = _hit([r for r in evaluated if str(r["exit_reason"]) != reason])
                cands.append({"kind": "exit_reason", "tier": tier, "n_spells": len(evaluated), "n_dates": n_dates, "ci": ci,
                              "text": (f"tier {tier}: the exit reason '{reason}' accounts for {k} of the five worst spells. "
                                       f"Over the tier's month, spells exiting by '{reason}' had hit rate vs SPY {a} of {b}; "
                                       f"the other exit reasons {c} of {d}. A registration names this comparison in advance "
                                       f"and tests it on spells entered after the registration date.")})
        # (b) tier_rank at entry, split at the median
        ranked = [r for r in evaluated if _f(r["scores"].get("tier_rank")) is not None]
        if len(ranked) >= LESSON_MIN_EVALUATED:
            med = float(np.median([_f(r["scores"]["tier_rank"]) for r in ranked]))
            top = [r for r in ranked if _f(r["scores"]["tier_rank"]) <= med]
            rest = [r for r in ranked if _f(r["scores"]["tier_rank"]) > med]
            if len(top) >= LESSON_MIN_SIDE and len(rest) >= LESSON_MIN_SIDE:
                a, b = _hit(top)
                c, d = _hit(rest)
                gap = a / b - c / d
                if abs(gap) >= LESSON_MIN_HIT_GAP:
                    better, worse = ("ranked at or better than", "ranked worse than") if gap > 0 else ("ranked worse than", "ranked at or better than")
                    x, y = ((a, b), (c, d)) if gap > 0 else ((c, d), (a, b))
                    cands.append({"kind": "rank_split", "tier": tier, "n_spells": len(ranked), "n_dates": len({r["entry_session"] for r in ranked}), "ci": ci,
                                  "text": (f"tier {tier}: split at the median tier_rank at entry ({med:g}), spells {better} the median "
                                           f"had hit rate vs SPY {x[0]} of {x[1]}; spells {worse} the median {y[0]} of {y[1]} "
                                           f"(gap {gap * 100:+.0f} points). A registration fixes the split and the horizon in advance "
                                           f"and tests it on spells entered after the registration date.")})
    # (c) operator decisions with +60 outcomes all on one side
    with60 = [r for r in operator["decisions"] if r["outcomes"].get(60) and _f(r["outcomes"][60].get("difference")) is not None]
    if len(with60) >= LESSON_OPERATOR_MIN:
        diffs = [_f(r["outcomes"][60]["difference"]) for r in with60]
        if all(v > 0 for v in diffs) or all(v < 0 for v in diffs):
            side = "above" if diffs[0] > 0 else "below"
            sessions = len({r["session"] for r in with60})
            cands.append({"kind": "operator", "tier": "operator", "n_spells": len(with60), "n_dates": sessions, "ci": None,
                          "text": (f"operator: {len(with60)} of {len(with60)} decisions with a +60 outcome in the ledger came out {side} "
                                   f"their not-traded alternative (differences " + ", ".join(f"{v * 100:+.2f}%" for v in diffs) + "). "
                                   f"A registration states the comparison and the horizon in advance and tests it on decisions "
                                   f"made after the registration date.")})
    # (d) a failure that repeats an earlier ledger entry
    for rc in failures["recurrences"]:
        f, e = rc["new"], rc["earlier"]
        cands.append({"kind": "recurrence", "tier": "system", "n_spells": 2, "n_dates": 2, "ci": None,
                      "text": (f"system: failure {f.get('entry_id')} (found {str(f.get('found'))[:10]}) repeats the error of "
                               f"{e.get('entry_id')} (found {str(e.get('found'))[:10]}); the referee check registered then "
                               f"({e.get('referee_check') or 'none recorded'}) did not stop the recurrence. "
                               f"A registration names the check that is meant to catch it and the test of that check.")})
    cands.sort(key=lambda c: (-c["n_dates"], -c["n_spells"], c["kind"], str(c["tier"])))
    return cands[:MAX_LESSONS]


# ─── build ───────────────────────────────────────────────────────────────────────────────
def build(paths: dict, month: str, generated_at: str, repo: Path | None = None) -> dict:
    spells, m_spells = load_jsonl(paths["spells"])
    trades, m_trades = load_jsonl(paths["trades"])
    mistakes, m_mist = load_jsonl(paths["mistakes"])
    actions, m_act = load_jsonl(paths["actions"])
    prices = load_closes(paths["prices"])
    etfs = load_closes(paths["etfs"])
    m_prices, m_etfs = closes_meta(prices, paths["prices"]), closes_meta(etfs, paths["etfs"])
    if repo is not None:   # paths inside the repository print relative to it, as every report here does
        for m in (m_spells, m_trades, m_mist, m_act, m_prices, m_etfs):
            m["path"] = relpath(Path(m["path"]), repo)
    trades_by_id = {t.get("trade_id"): t for t in trades if t.get("trade_id") is not None}
    states = spell_states(spells)
    m_spells["spells"] = len(states)
    m_spells["events_by_kind"] = dict(Counter(str(e.get("event")) for e in spells))
    sample, ctx = build_sample(states, month, prices, etfs, trades_by_id)
    present = {r["tier"] for r in sample} | {st["tier"] for st in states.values()}
    twins = [t for t in ("1c", "2c", "3c", "4c") if t in present]
    other = sorted(t for t in present if t not in MONTHLY_TIERS and t not in TWIN_OF and t is not None)
    tier_order = MONTHLY_TIERS + twins + other
    tiers = {t: tier_result(t, [r for r in sample if r["tier"] == t]) for t in tier_order}
    operator = operator_section(mistakes, actions, month, ctx["mark_session"])
    failures = failures_section(mistakes, month)
    lessons = candidate_lessons(tiers, sample, operator, failures)
    return {"month": month, "generated_at": generated_at, "ctx": ctx,
            "inputs": {"spells": m_spells, "trades": m_trades, "mistakes": m_mist, "actions": m_act,
                       "prices": m_prices, "etfs": m_etfs},
            "tiers": tiers, "tier_order": tier_order, "sample": sample, "operator": operator, "failures": failures,
            "lessons": lessons, "n_spells": len(sample),
            "effective_samples": {t: tiers[t]["effective_sample"] for t in tier_order}}


# ─── render ──────────────────────────────────────────────────────────────────────────────
def pct(x, signed=True):
    if x is None:
        return "—"
    return f"{x * 100:+.2f}%" if signed else f"{x * 100:.2f}%"


def ci_pct(ci, signed=True):
    return "—" if not ci else f"[{pct(ci[0], signed)}, {pct(ci[1], signed)}]"


def num(x, nd=2):
    v = _f(x)
    if v is None:
        return "—" if x in (None, "") else str(x)
    return f"{v:.{nd}f}" if nd else f"{v:g}"


def tier_title(t: str) -> str:
    if t in TIER_NAMES:
        return f"{t} — {TIER_NAMES[t]}"
    if t in TWIN_OF:
        return f"{t} — continuous twin of {TWIN_OF[t]}"
    return str(t)


def _cell(s):
    return str(s if s is not None else "—").replace("|", "/").replace("\n", " ")


def render(res: dict, prohibited=(), earlier: list | None = None, reason: str | None = None) -> str:
    month, ctx, inp = res["month"], res["ctx"], res["inputs"]
    withheld = 0
    L = []
    L.append(f"# Monthly review — {month}")
    L.append("")
    L.append(f"Generated {res['generated_at']} by scripts/monthly_review.py. Month reviewed: {month} "
             f"(sessions {ctx['first_session'] or '—'} to {ctx['last_session'] or '—'}, {ctx['n_sessions']} sessions). "
             + (f"Spells open at month end are marked at the {ctx['mark_session']} close, the last session of the month with a price row."
                if ctx["mark_available"] else "No price row inside the month: spells open at month end are listed without a mark."))
    L.append("")
    L.append("This review is generated from the ledgers, stored, and never edited. No rule is changed by it. "
             "A lesson becomes a rule only through a registration and a prospective test; a lesson is never applied "
             "retroactively to history. Every figure below is an observation of the month's record.")
    if earlier:
        L.append("")
        L.append(f"**Second review for this month (--force-new).** Earlier file(s), unchanged: "
                 + "; ".join(f"{e['file']} (sha256 {e['sha256'][:12]}…)" for e in earlier)
                 + f". Stated reason for this file: {reason or 'none given'}.")
    L.append("")
    L.append("## 1. Inputs")
    L.append("")
    L.append("| input | rows | note |")
    L.append("|---|---:|---|")
    sp = inp["spells"]
    L.append(f"| {sp['path']} | {sp['rows']} | " + (f"events for {sp['spells']} spells; by kind " + ", ".join(f"{k} {v}" for k, v in sorted(sp['events_by_kind'].items())) if sp["exists"] else "absent") + " |")
    for key, label in (("trades", "trade rows"), ("mistakes", "ledger entries"), ("actions", "action-log entries")):
        m = inp[key]
        L.append(f"| {m['path']} | {m['rows']} | " + (label + (f"; {m['bad']} unparsable line(s)" if m["bad"] else "") if m["exists"] else "absent") + " |")
    for key in ("prices", "etfs"):
        m = inp[key]
        L.append(f"| {m['path']} | {m['rows']} | " + (f"{m['columns']} columns, last row {m['last']}" if m["exists"] else "absent") + " |")
    L.append("")
    L.append(f"Sample: {res['n_spells']} spells across all tiers (closed in the month, or open at month end). "
             "Return figures in the ledger are read as fractions of the entry price and shown in percent.")
    L.append("")
    L.append("## 2. Spells by tier")
    L.append("")
    L.append("Per tier: the five worst spells by excess return vs SPY among spells closed in the month (or open at month end, "
             "marked and labelled), then the tier's month with its effective sample size — the number of distinct decision "
             "sessions (entry sessions), stated beside the spell count — and a date-block bootstrap interval "
             f"({int(CI_LEVEL * 100)} percent: decision dates resampled with replacement, each date carrying all its spells, "
             f"{N_RESAMPLES} resamples, seed {SEED}).")
    if not inp["spells"]["exists"]:
        L.append("")
        L.append(f"The spells ledger is absent ({inp['spells']['path']}): no spell figures this month.")
    for t in res["tier_order"]:
        tr = res["tiers"][t]
        L.append("")
        L.append(f"### {tier_title(t)}")
        L.append("")
        if tr["n_spells"] == 0:
            L.append("No spells in the sample for this tier this month (0 spells, 0 decision sessions).")
            continue
        if tr["worst"]:
            L.append("| # | ticker | entry | exit | held | return | vs SPY | vs basket | exit reason | tier comp | tier rank | comp rank | BQ | TN | regime at entry |")
            L.append("|---:|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|")
            for i, r in enumerate(tr["worst"], 1):
                s = r["scores"]
                reason_txt = r["exit_reason"] if r["status"] == "closed" else "open at month end (marked)"
                reason_txt, k = withhold(reason_txt, prohibited)
                withheld += k
                L.append(f"| {i} | {_cell(r['ticker'])} | {_cell(r['entry_session'])} | {_cell(r['exit_session'])} | {_cell(r['sessions_held'])} | "
                         f"{pct(r['ret'])} | {pct(r['excess_spy'])} | {pct(r['excess_basket'])} | {_cell(reason_txt)} | "
                         f"{num(s.get('tier_composite'))} | {num(s.get('tier_rank'), 0)} | {num(s.get('composite_rank'), 0)} | "
                         f"{num(s.get('bq_score'))} | {num(s.get('tn_score'))} | {_cell(r['regime_label'])} |")
            baskets = sorted({str(r["basket_thesis"]) for r in tr["worst"] if r["basket_thesis"]})
            if baskets:
                L.append("")
                L.append("Thesis baskets among the five: " + ", ".join(baskets) + ".")
        else:
            L.append("No spell in this tier carries an excess-vs-SPY figure this month; nothing to rank.")
        L.append("")
        parts = [f"{tr['n_spells']} spells ({tr['n_closed']} closed in the month, {tr['n_open_marked']} open at month end and marked"
                 + (f", {tr['n_not_evaluated']} without a figure" if tr["n_not_evaluated"] else "") + ")"]
        if tr["n_evaluated"]:
            parts.append(f"hit rate vs SPY {tr['hits']} of {tr['n_evaluated']} ({pct(tr['hit_rate'], False)})")
            parts.append(f"mean excess vs SPY {pct(tr['mean_excess'])} (median {pct(tr['median_excess'])})")
        L.append("The tier's month: " + "; ".join(parts) + ".")
        L.append("")
        L.append(f"**Effective sample size: {tr['effective_sample']} decision session(s)** "
                 f"({', '.join(tr['decision_sessions']) or '—'}) beside {tr['n_spells']} spells.")
        b = tr["bootstrap"]
        L.append("")
        if b["hit_rate_ci"]:
            L.append(f"Date-block bootstrap, {int(b['level'] * 100)}% interval ({b['n_resamples']} resamples of {b['n_dates']} decision dates, "
                     f"seed {b['seed']}): hit rate {ci_pct(b['hit_rate_ci'], False)}; mean excess {ci_pct(b['mean_excess_ci'])}."
                     + ("" if b["informative"] else f" Caption: fewer than {MIN_DATES_INFORMATIVE} decision dates — the interval is not informative."))
        else:
            L.append("Date-block bootstrap: no evaluated spell, no interval.")
        if tr["exit_reasons"]:
            L.append("")
            L.append("Exit reasons across the evaluated spells: " + ", ".join(f"{withhold(k, prohibited)[0]} {v}" for k, v in sorted(tr["exit_reasons"].items())) + ".")
    # ── operator
    op = res["operator"]
    L.append("")
    L.append("## 3. The operator's trades")
    L.append("")
    L.append(f"From data/mistakes.jsonl (kind operator_decision, {op['n_decisions']} in the month) and data/actions.jsonl "
             f"(source \"{SOURCE_EXPORT}\", {op['n_export']} in the month). Outcomes are the ledger's kind-outcome entries at "
             "+20 and +60 sessions: the trade's return against the not-traded alternative.")
    if op["decisions"] or op["export_trades"]:
        L.append("")
        L.append("| session | ticker | action | qty | price | regime | stated reason | export | +20: trade / not traded / difference | +60: trade / not traded / difference |")
        L.append("|---|---|---|---:|---:|---|---|---|---|---|")
        for r in op["decisions"]:
            e = r["export"] or {}
            reason_txt, k = withhold(r["stated_reason"], prohibited)
            withheld += k
            cells = []
            for h in OUTCOME_HORIZONS:
                o = r["outcomes"].get(h)
                if o:
                    cells.append(f"{pct(_f(o.get('trade_return')))} / {pct(_f(o.get('not_traded_return')))} / {pct(_f(o.get('difference')))}")
                else:
                    cells.append(f"not yet in the ledger (session +{h} = {r['due'].get(h, '—')})")
            L.append(f"| {_cell(r['session'])} | {_cell(r['ticker'])} | {_cell(r['action'])} | {_cell(e.get('quantity'))} | {num(e.get('price'))} | "
                     f"{_cell(e.get('regime'))} | {_cell(reason_txt or 'no stated reason recorded')} | "
                     f"{'confirmed' if r['export'] else 'no export entry'} | {cells[0]} | {cells[1]} |")
        for a in op["unmatched_export"]:
            act = a.get("action")
            act = act[0] if isinstance(act, list) and act else act
            sig = a.get("signal") or {}
            sig_txt = sig.get("signal") or sig.get("state") if isinstance(sig, dict) else None
            sess = str(a.get("session_date") or "")[:10]
            due = {h: nth_session_after(sess, h) for h in OUTCOME_HORIZONS} if sess else {}
            L.append(f"| {sess} | {_cell(a.get('ticker'))} | {_cell(act)} | {_cell(a.get('quantity'))} | {num(a.get('price'))} | "
                     f"{_cell(a.get('regime'))} | no operator_decision entry in the mistakes ledger"
                     + (f" (signal at the time: {_cell(sig_txt)})" if sig_txt else "") + " | confirmed | "
                     f"not yet in the ledger (session +20 = {due.get(20, '—')}) | not yet in the ledger (session +60 = {due.get(60, '—')}) |")
    if op["n_export"] == 0:
        L.append("")
        L.append("No export-confirmed operator trades in the month" + (" (and no operator_decision entries)." if not op["decisions"] else "."))
    if op["provisional"]:
        L.append("")
        L.append("Provisional operator-report entries — pending export confirmation, not evaluated:")
        L.append("")
        for a in op["provisional"]:
            act = a.get("action")
            act = act[0] if isinstance(act, list) and act else act
            note, k = withhold(a.get("date_note"), prohibited)
            withheld += k
            L.append(f"- {str(a.get('session_date') or '')[:10]} {_cell(a.get('ticker'))} {_cell(act)} qty {_cell(a.get('quantity'))} "
                     f"price {num(a.get('price'))} ({_cell(a.get('price_basis') or 'price basis not stated')}) — pending export confirmation, not evaluated"
                     + (f"; {note}" if note else ""))
    elif op["n_export"] == 0:
        L.append("No provisional operator-report entries either.")
    # ── failures
    fl = res["failures"]
    L.append("")
    L.append("## 4. New system failures")
    L.append("")
    L.append(f"From data/mistakes.jsonl, kind failure, found within {month}: {fl['n_failures']} entries"
             + (f"; {len(fl['corrections'])} correction entries in the month" if fl["corrections"] else "") + ".")
    if fl["failures"]:
        L.append("")
        L.append("| entry | found | who | error | detected by | cost | fix | referee check that catches a recurrence |")
        L.append("|---|---|---|---|---|---|---|---|")
        for f in fl["failures"]:
            vals = []
            for key in ("error", "detected_by", "cost", "fix", "referee_check"):
                v, k = withhold(f.get(key), prohibited)
                withheld += k
                vals.append(_cell(v if v is not None else ("none recorded" if key == "referee_check" else "—")))
            L.append(f"| {_cell(f.get('entry_id'))} | {_cell(str(f.get('found') or '')[:10])} | {_cell(f.get('who'))} | " + " | ".join(vals) + " |")
        if fl["recurrences"]:
            L.append("")
            L.append("Recurrences: " + "; ".join(f"{rc['new'].get('entry_id')} repeats {rc['earlier'].get('entry_id')} (found {str(rc['earlier'].get('found'))[:10]})"
                                                 for rc in fl["recurrences"]) + ".")
    else:
        L.append("")
        L.append("No new system failure recorded in the month" + ("" if inp["mistakes"]["exists"] else " (the mistakes ledger is absent)") + ".")
    # ── what this review does not do
    L.append("")
    L.append("## 5. What this review does not do")
    L.append("")
    L.append("No rule is changed here. Nothing in this file alters a threshold, a weight, a sizing rule or a registry entry, "
             "and nothing in it is applied to history. The candidate lessons below are hypotheses stated with the sample they "
             "rest on; each is listed for registration and a prospective test, never applied.")
    L.append("")
    if res["lessons"]:
        for i, c in enumerate(res["lessons"], 1):
            sample_txt = f"Sample: {c['n_spells']} " + ("entries" if c["kind"] == "recurrence" else "decisions" if c["kind"] == "operator" else "spells") \
                + f" over {c['n_dates']} " + ("ledger entries" if c["kind"] == "recurrence" else "sessions" if c["kind"] == "operator" else "decision dates")
            if c["ci"]:
                sample_txt += f"; the tier's hit-rate interval {ci_pct(c['ci'], False)}"
            if c["n_dates"] < MIN_DATES_INFORMATIVE:
                sample_txt += f" — fewer than {MIN_DATES_INFORMATIVE} decision dates, not informative"
            txt, k = withhold(c["text"], prohibited)
            withheld += k
            L.append(f"{i}. Hypothesis, not a rule — {txt} {sample_txt}.")
    else:
        L.append("No candidate lesson met the listing thresholds this month.")
    L.append("")
    L.append(f"Listing thresholds (fixed in scripts/monthly_review.py): a split is examined only with at least {LESSON_MIN_EVALUATED} evaluated spells "
             f"and {LESSON_MIN_SIDE} on each side, and listed only when the hit-rate gap is at least {int(LESSON_MIN_HIT_GAP * 100)} points; an exit reason "
             f"is listed when it accounts for at least {LESSON_EXIT_REASON_MIN} of the five worst; operator decisions when at least {LESSON_OPERATOR_MIN} "
             f"+60 outcomes fall on one side; a failure when its error text repeats an earlier ledger entry. At most {MAX_LESSONS} are listed, "
             "largest sample first. A hypothesis listed here is tested only on decisions made after its registration date.")
    if withheld:   # L[0] title, L[1] blank, L[2] generated-line, L[3] blank, L[4] the never-edited statement
        L.insert(3, "")
        L.insert(4, f"Vocabulary rule: {withheld} word(s) withheld from quoted ledger text ([word withheld]); the ledger entries themselves are unchanged.")
    return "\n".join(L).rstrip() + "\n"


# ─── writing ─────────────────────────────────────────────────────────────────────────────
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def existing_reviews(out_dir: Path, month: str) -> list:
    """The review files already on disk for the month, base file first, then _v2, _v3, ..."""
    base = out_dir / f"review_{month}.md"
    found = []
    if base.exists():
        found.append(base)
    n = 2
    while (out_dir / f"review_{month}_v{n}.md").exists():
        found.append(out_dir / f"review_{month}_v{n}.md")
        n += 1
    return found


def next_version_path(out_dir: Path, month: str) -> tuple:
    """(path, version) for the next review file of the month: the base name, else _v2, _v3, ..."""
    base = out_dir / f"review_{month}.md"
    if not base.exists():
        return base, 1
    n = 2
    while (out_dir / f"review_{month}_v{n}.md").exists():
        n += 1
    return out_dir / f"review_{month}_v{n}.md", n


def relpath(p: Path, repo: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(repo).resolve()))
    except ValueError:
        return str(p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("Usage")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month", help="YYYY-MM to review (default: the previous calendar month, ET)")
    ap.add_argument("--force-new", action="store_true", help="when a review for the month exists, write review_<month>_v2.md (v3, ...) instead of refusing")
    ap.add_argument("--reason", help="why a second review is generated (recorded in its header and in the index line)")
    ap.add_argument("--dry-run", action="store_true", help="print the review, write nothing")
    ap.add_argument("--repo", default=str(REPO), help="repository root the default paths hang off")
    for key in ("spells", "trades", "mistakes", "actions", "prices", "etfs", "out_dir", "index"):
        ap.add_argument("--" + key.replace("_", "-"), dest=key, help=f"default {DEFAULT_PATHS[key]}")
    args = ap.parse_args(argv)

    repo = Path(args.repo)
    paths = {k: str(Path(getattr(args, k)) if getattr(args, k) else repo / DEFAULT_PATHS[k]) for k in DEFAULT_PATHS}
    month = args.month or previous_month(now_et().date())
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        print(f"monthly_review: --month must be YYYY-MM, got {month!r}", file=sys.stderr)
        return 2
    out_dir, index_path = Path(paths["out_dir"]), Path(paths["index"])
    generated_at = now_et().isoformat(timespec="seconds")

    earlier_files = existing_reviews(out_dir, month)
    if earlier_files and not args.force_new and not args.dry_run:
        print(f"monthly_review: a review for {month} already exists and is never edited: "
              + ", ".join(relpath(p, repo) for p in earlier_files)
              + ". Nothing written. Pass --force-new --reason \"...\" to write a further file as review_{month}_v<n>.md.", file=sys.stderr)
        return 2
    earlier = [{"file": relpath(p, repo), "sha256": sha256_text(p.read_text(encoding="utf-8"))} for p in earlier_files] if (earlier_files and args.force_new) else []

    res = build(paths, month, generated_at, repo=repo)
    prohibited = prohibited_words()
    text = render(res, prohibited=prohibited, earlier=earlier or None, reason=args.reason if earlier else None)
    hits = word_hits(text, prohibited)
    if hits:   # cannot happen after withholding; a guard, never a silent pass
        print(f"monthly_review: prohibited vocabulary in the rendered review: {hits}; nothing written", file=sys.stderr)
        return 3

    if args.dry_run:
        sys.stdout.write(text)
        print(f"\n[dry run] {len(text)} characters; nothing written", file=sys.stderr)
        return 0

    out_path, version = next_version_path(out_dir, month)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "x", encoding="utf-8") as f:   # "x": never overwrite, whatever the race
        f.write(text)
    line = {"month": month, "file": relpath(out_path, repo), "generated_at": generated_at, "sha256": sha256_text(text),
            "effective_samples": res["effective_samples"], "n_spells": res["n_spells"], "version": version,
            "earlier_reviews": [e["file"] for e in earlier], "reason": args.reason if earlier else None}
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    print(f"wrote {relpath(out_path, repo)} ({len(text)} characters, sha256 {line['sha256'][:12]}…)")
    print(f"index line appended to {relpath(index_path, repo)}: " + json.dumps(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
