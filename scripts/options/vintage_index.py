#!/usr/bin/env python3
"""vintage_index.py — the record of captured and missed option-chain snapshots
(Execution Order: Make the Daily Options Snapshot Reliable, 5 October 2026, item 2.3).

Writes data/options/vintages/_index.json with one entry per trading day from the first vintage
(25 September 2026) through the last decided day: today once it is 16:05 ET on a trading day,
otherwise the previous trading day.

  captured  the day's vintage exists (its _meta.json); the entry carries the snapshot timestamp
            (pulled_at) and the kind (scheduled; the 25-Sept seed is a flagged backfill)
  missing   no vintage, with a reason read from the options-snapshot workflow's run history:
              runner_failure    a run active in the 15:30–16:00 ET window failed before a runner took it
              provider_error    a run in the window reached the snapshot step and that step failed
              push_conflict     a run in the window pushed nothing because it lost a push race, and no
                                vintage exists
              no_run_in_window  no run of the workflow was active inside the window

Missed days are never backfilled with after-hours data. Once a missing day's reason is recorded it is
kept. A day becomes captured only if a vintage pulled inside the window appears later, e.g. a
push that landed after 16:05. The IV-rank and percentile archive uses captured days only
(options_common.captured_sessions).

Runs in the 16:05 ET check (options_snapshot_check.yml, dispatched by the external scheduler) and in
the nightly (update_daily.py). The run history is read with `gh api`, which authenticates itself
(in CI with the job token, permissions actions: read). The script never handles a token.

Usage:  python scripts/options/vintage_index.py [--now YYYY-MM-DDTHH:MM]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import options_common as oc                                     # noqa: E402
from trading_calendar import is_trading_day, now_et, prev_trading_day   # noqa: E402

ET = ZoneInfo("America/New_York")
FIRST_DAY = "2026-09-25"
WORKFLOW = "options_snapshot.yml"
REPO_SLUG = "wernerhl/portfolio-tournament"
INDEX = oc.VINTAGES / "_index.json"
REASONS = ("no_run_in_window", "runner_failure", "provider_error", "push_conflict")


def log(m: str) -> None:
    print(f"[vintage_index] {m}", flush=True)


def decided_through(now: datetime) -> str:
    d = now.date()
    if is_trading_day(d) and (now.hour, now.minute) >= (16, 5):
        return d.isoformat()
    return prev_trading_day(d)


def trading_days(a: str, b: str) -> list[str]:
    out, cur, end = [], date.fromisoformat(a), date.fromisoformat(b)
    while cur <= end:
        if is_trading_day(cur):
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def gh_json(path: str):
    try:
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(ET) if s else None


def classify(day: str, runs: list[dict] | None) -> tuple[str, str]:
    """The reason a trading day has no vintage, from the workflow's runs on that day."""
    if runs is None:
        return "no_run_in_window", "run history not readable; no run evidence in the window"
    d = date.fromisoformat(day)
    w0 = datetime(d.year, d.month, d.day, 15, 30, tzinfo=ET); w1 = datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET)
    covered = []
    for r in runs:
        c, u = _ts(r.get("created_at")), _ts(r.get("updated_at"))
        if c and c.date() == d and c < w1 and (u is None or u >= w0):
            covered.append(r)
    if not covered:
        first = min((_ts(r.get("created_at")) for r in runs if _ts(r.get("created_at")) and _ts(r.get("created_at")).date() == d), default=None)
        return "no_run_in_window", (f"first run of the day created {first:%H:%M} ET" if first else "no run of the workflow that day")
    for r in covered:
        jobs = (gh_json(f"repos/{REPO_SLUG}/actions/runs/{r['id']}/jobs") or {}).get("jobs") or []
        steps = [s for j in jobs for s in (j.get("steps") or [])]
        if r.get("conclusion") in ("failure", "cancelled", "startup_failure", "timed_out") and (not steps or not any(j.get("runner_name") for j in jobs)):
            return "runner_failure", f"run {r.get('run_number')} ({r.get('conclusion')}) never reached a runner"
        snap = [s for s in steps if str(s.get("name", "")).startswith("Snapshot chains")]
        if any(s.get("conclusion") == "failure" for s in snap):
            return "provider_error", f"run {r.get('run_number')}: the snapshot step failed"
        if any(s.get("conclusion") == "success" for s in snap):
            return "push_conflict", f"run {r.get('run_number')}: the snapshot step ran in the window but no vintage exists"
    return "no_run_in_window", f"{len(covered)} run(s) overlapped the window without reaching the snapshot step"


def runs_around(day: str) -> list[dict] | None:
    d = date.fromisoformat(day)
    q = f"repos/{REPO_SLUG}/actions/workflows/{WORKFLOW}/runs?per_page=100&created={d.isoformat()}..{(d + timedelta(days=1)).isoformat()}"
    j = gh_json(q)
    return None if j is None else (j.get("workflow_runs") or [])


def build(now: datetime) -> dict:
    prev = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    prev_days = {e["date"]: e for e in prev.get("days", [])}
    through = decided_through(now)
    days = []
    for day in trading_days(FIRST_DAY, through):
        meta_p = oc.vintage_dir(day) / "_meta.json"
        if meta_p.exists():
            m = json.loads(meta_p.read_text())
            e = {"date": day, "status": "captured", "snapshot_at": m.get("pulled_at"), "kind": m.get("snapshot_kind"),
                 "tickers": len(m.get("tickers") or {})}
            if m.get("snapshot_kind") == "backfill":
                e["note"] = "seeded once, 26 Sept, from the provider's retained close (flagged); after-hours backfills are prohibited"
        elif prev_days.get(day, {}).get("status") == "missing" and prev_days[day].get("reason") in REASONS:
            e = prev_days[day]                                   # a recorded miss keeps its reason
        else:
            reason, evidence = classify(day, runs_around(day))
            e = {"date": day, "status": "missing", "reason": reason, "evidence": evidence,
                 "recorded_at": now.isoformat(timespec="seconds")}
        days.append(e)
    cap = [e for e in days if e["status"] == "captured"]
    last20 = days[-20:]
    share20 = (sum(1 for e in last20 if e["status"] == "captured") / len(last20)) if last20 else None
    return {
        "cadence": "daily", "as_of": through, "session_date": through, "computed_at": now.isoformat(timespec="seconds"),
        "order": "Execution Order: Make the Daily Options Snapshot Reliable (5 October 2026), item 2.3",
        "window_et": "15:30–16:00", "first_day": FIRST_DAY, "decided_through": through,
        "policy": "missed days are never backfilled with after-hours data; IV rank and percentile use captured days only",
        "counts": {"days": len(days), "captured": len(cap), "missing": len(days) - len(cap)},
        "captured_share_last_20": round(share20, 4) if share20 is not None else None,
        "days": days,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", default=None, help="evaluate as of this ET time (tests)")
    a = ap.parse_args()
    now = datetime.fromisoformat(a.now).replace(tzinfo=ET) if a.now else now_et()
    idx = build(now)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx, indent=1))
    miss = [f"{e['date']} ({e['reason']})" for e in idx["days"] if e["status"] == "missing"]
    log(f"through {idx['decided_through']}: {idx['counts']['captured']} of {idx['counts']['days']} trading days captured; "
        f"last-20 share {idx['captured_share_last_20']}; missing: {', '.join(miss) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
