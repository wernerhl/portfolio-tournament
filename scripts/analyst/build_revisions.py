#!/usr/bin/env python3
"""
build_revisions.py — the consensus-revision variables from the repository's own snapshots (free-analyst-data
order, 7 October 2026, task C), and the dated consensus history they rest on.

From data/analyst/snapshots/YYYY-MM-DD.json (one per session, immutable):
  consensus_history.parquet   one row per (date, ticker, period): the consensus EPS and revenue means, the number
                              of analysts, the up/down revision counts. source = "observed" for a snapshot's own
                              current values; "provider-reported" for the 7-, 30-, 60- and 90-day-ago values of the
                              FIRST snapshot only, dated back by that many calendar days (one extra dated observation
                              per horizon, as the order allows; nothing later is backdated)
  revisions.json              the three variables once 30 days of snapshots exist, for the current fiscal year (0y):
      an_eps_rev_30      consensus EPS today / its value in the snapshot 30 days earlier - 1 (the latest snapshot at or
                         before today - 30 calendar days, observed values only)
      an_eps_breadth_30  (upward - downward revisions over 30 days) / the number of analysts, from today's snapshot
      an_rev_rev_30      the same as an_eps_rev_30 for revenue
  Until 12 months of snapshots exist the variables carry the DIAGNOSTIC label and enter no score (in_score false);
  until 30 days exist the file states how many days there are and carries no values.

Usage:  python scripts/analyst/build_revisions.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
AN = REPO / "data" / "analyst"
SNAPS = AN / "snapshots"
HIST = AN / "consensus_history.parquet"
OUT = AN / "revisions.json"
MIN_DAYS, MIN_MONTHS = 30, 12
LAGS = {"d7": 7, "d30": 30, "d60": 60, "d90": 90}


def log(m: str) -> None:
    print(f"[build_revisions] {m}", flush=True)


def load_snapshots() -> list[tuple[str, dict]]:
    out = []
    for p in sorted(SNAPS.glob("20??-??-??.json")) if SNAPS.exists() else []:
        try:
            out.append((p.name[:10], json.loads(p.read_text())))
        except ValueError:
            log(f"{p.name}: unreadable, skipped")
    return out


def history(snaps: list[tuple[str, dict]]) -> pd.DataFrame:
    rows = []
    for i, (day, j) in enumerate(snaps):
        for tk, rec in (j.get("names") or {}).items():
            for per, p in (rec.get("periods") or {}).items():
                eps, rev, ee, re_ = p.get("eps") or {}, p.get("rev") or {}, p.get("eps_est") or {}, p.get("rev_est") or {}
                rows.append({"date": day, "ticker": tk, "period": per, "period_end": p.get("end"), "source": "observed",
                             "eps_consensus": eps.get("current"), "eps_mean": ee.get("avg"), "eps_n": ee.get("n"),
                             "rev_mean": re_.get("avg"), "rev_n": re_.get("n"),
                             "up7": rev.get("up7"), "up30": rev.get("up30"), "down7": rev.get("down7"), "down30": rev.get("down30")})
                if i == 0 and j.get("first_run"):
                    for k, lag in LAGS.items():
                        if eps.get(k) is not None:
                            rows.append({"date": (date.fromisoformat(day) - timedelta(days=lag)).isoformat(), "ticker": tk, "period": per,
                                         "period_end": p.get("end"), "source": "provider-reported",
                                         "eps_consensus": eps.get(k), "eps_mean": None, "eps_n": None, "rev_mean": None, "rev_n": None,
                                         "up7": None, "up30": None, "down7": None, "down30": None})
    df = pd.DataFrame(rows)
    if len(df):
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["ticker", "period", "date", "source"]).reset_index(drop=True)
    return df


def variables(snaps: list[tuple[str, dict]]) -> dict:
    days = [d for d, _ in snaps]
    today, j = snaps[-1]
    t_lag = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    base_day = max([d for d in days if d <= t_lag], default=None)
    base = dict(snaps)[base_day]["names"] if base_day else {}
    names = {}
    for tk, rec in (j.get("names") or {}).items():
        p = (rec.get("periods") or {}).get("0y") or {}
        b = ((base.get(tk) or {}).get("periods") or {}).get("0y") or {}
        eps_now, eps_then = (p.get("eps") or {}).get("current"), (b.get("eps") or {}).get("current")
        rev_now, rev_then = (p.get("rev_est") or {}).get("avg"), (b.get("rev_est") or {}).get("avg")
        n = (p.get("eps_est") or {}).get("n")
        up30, down30 = (p.get("rev") or {}).get("up30"), (p.get("rev") or {}).get("down30")
        same_fy = (p.get("end") == b.get("end")) if (p.get("end") and b.get("end")) else True
        rec_out = {
            "an_eps_rev_30": round(eps_now / eps_then - 1, 5) if (eps_now is not None and eps_then not in (None, 0) and same_fy and base_day) else None,
            "an_eps_breadth_30": round((up30 - down30) / n, 4) if (up30 is not None and down30 is not None and n) else None,
            "an_rev_rev_30": round(rev_now / rev_then - 1, 5) if (rev_now is not None and rev_then not in (None, 0) and same_fy and base_day) else None,
            "fiscal_year_end": p.get("end"), "analysts": n, "base_snapshot": base_day,
        }
        if not same_fy:
            rec_out["note"] = "the fiscal year rolled between the two snapshots; the revision is not comparable"
        names[tk] = rec_out
    return {"base_snapshot": base_day, "names": names}


def main() -> int:
    snaps = load_snapshots()
    AN.mkdir(parents=True, exist_ok=True)
    h = history(snaps)
    h.to_parquet(HIST, index=False)
    days = [d for d, _ in snaps]
    span_days = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1 if days else 0
    months = span_days / 30.4375
    ready = len(days) >= MIN_DAYS and span_days >= MIN_DAYS
    payload = {
        "cadence": "daily", "session_date": days[-1] if days else None, "as_of": days[-1] if days else None,
        "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "order": "free-analyst-data order (7 October 2026), task C",
        "label": "DIAGNOSTIC", "in_score": False,
        "label_reason": (f"{len(days)} snapshot day(s) spanning {span_days} calendar days; the variables need 30 days to exist and 12 months "
                         f"({MIN_MONTHS}) before the registered test can judge them; until then they are description, not a score input"),
        "snapshots": {"first": days[0] if days else None, "latest": days[-1] if days else None, "n": len(days), "span_days": span_days,
                      "months": round(months, 2)},
        "status": "values" if ready else f"waiting: {len(days)} of {MIN_DAYS} days of snapshots",
        "definitions": {
            "an_eps_rev_30": "consensus EPS for the current fiscal year today / its value in the snapshot 30 days earlier - 1",
            "an_eps_breadth_30": "(upward - downward revisions in 30 days) / the number of analysts, current fiscal year",
            "an_rev_rev_30": "the same as an_eps_rev_30 for revenue",
            "history": "data/analyst/consensus_history.parquet: observed values per snapshot; the first snapshot's 7/30/60/90-day-ago values dated back and marked provider-reported",
        },
        "names": variables(snaps)["names"] if ready else {},
    }
    if ready:
        payload["base_snapshot"] = variables(snaps)["base_snapshot"]
    OUT.write_text(json.dumps(payload, indent=1, allow_nan=False))
    log(f"{len(days)} snapshot days ({days[0] if days else '—'}..{days[-1] if days else '—'}); history rows {len(h)}; status: {payload['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
