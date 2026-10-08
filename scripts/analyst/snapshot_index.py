#!/usr/bin/env python3
"""
snapshot_index.py — the record of captured and missed analyst-estimate snapshots (free-analyst-data order,
7 October 2026, task C), the design of the options vintage index (scripts/options/vintage_index.py).

Writes data/analyst/snapshots/_index.json with one entry per trading day from the first snapshot (7 October 2026)
through the last decided day. A session is decided at 09:30 ET on the next trading day: the nightly that captures
it runs after the close and has its retries until 06:41 ET the next morning.

  captured  the session's file exists; the entry carries the capture time, the names captured, the coverage of the
            universe and the file's sha256 (the file is immutable; the referee compares)
  missing   no file, with a reason read from the nightly's run history between the close and 09:30 ET the next
            trading day (gh api, the job token in CI; never a token of its own):
              no_nightly_run   no run of the nightly in that window
              runner_failure   every run in the window failed before reaching the pipeline step
              snapshot_error   a run reached the pipeline step and still no snapshot exists
              unknown          the run history was not readable

A recorded miss keeps its reason. A day becomes captured only if its file appears later (a retry that landed
after the decision); nothing is backfilled from a later day's values.

Usage:  python scripts/analyst/snapshot_index.py [--now YYYY-MM-DDTHH:MM]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
from trading_calendar import is_trading_day, last_completed_session, now_et, prev_trading_day   # noqa: E402

ET = ZoneInfo("America/New_York")
REPO = HERE.parent.parent
SNAPS = REPO / "data" / "analyst" / "snapshots"
INDEX = SNAPS / "_index.json"
FIRST_DAY = "2026-10-06"
WORKFLOW = "nightly.yml"
REPO_SLUG = "wernerhl/portfolio-tournament"
REASONS = ("no_nightly_run", "runner_failure", "snapshot_error", "unknown")


def log(m: str) -> None:
    print(f"[analyst_snapshot_index] {m}", flush=True)


def next_trading_day(d: date) -> date:
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def decided(day: str, now: datetime) -> bool:
    n = next_trading_day(date.fromisoformat(day))
    return now >= datetime(n.year, n.month, n.day, 9, 30, tzinfo=ET)


def decided_through(now: datetime) -> str | None:
    s = last_completed_session(now)
    while s >= FIRST_DAY and not decided(s, now):
        s = prev_trading_day(date.fromisoformat(s))
    return s if s >= FIRST_DAY else None


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


def classify(day: str) -> tuple[str, str]:
    d = date.fromisoformat(day); n = next_trading_day(d)
    w0 = datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET); w1 = datetime(n.year, n.month, n.day, 9, 30, tzinfo=ET)
    q = f"repos/{REPO_SLUG}/actions/workflows/{WORKFLOW}/runs?per_page=100&created={d.isoformat()}..{(n + timedelta(days=1)).isoformat()}"
    j = gh_json(q)
    if j is None:
        return "unknown", "run history not readable"
    runs = [r for r in (j.get("workflow_runs") or []) if _ts(r.get("created_at")) and w0 <= _ts(r.get("created_at")) < w1]
    if not runs:
        return "no_nightly_run", f"no nightly run created between {w0:%Y-%m-%d %H:%M} and {w1:%Y-%m-%d %H:%M} ET"
    reached = []
    for r in runs:
        jobs = (gh_json(f"repos/{REPO_SLUG}/actions/runs/{r['id']}/jobs") or {}).get("jobs") or []
        steps = [s for j_ in jobs for s in (j_.get("steps") or [])]
        if any(str(s.get("name", "")).startswith("Run the nightly pipeline") and s.get("conclusion") in ("success", "failure") for s in steps):
            reached.append(r)
    if reached:
        return "snapshot_error", f"run {reached[0].get('run_number')} reached the pipeline step; no snapshot was written"
    return "runner_failure", f"{len(runs)} run(s) in the window, none reached the pipeline step ({', '.join(str(r.get('conclusion')) for r in runs)})"


def file_entry(day: str) -> dict:
    p = SNAPS / f"{day}.json"
    body = p.read_bytes()
    try:
        j = json.loads(body)
    except ValueError:
        j = {}
    from snapshot_common import snapshot_available_from
    return {"date": day, "status": "captured", "captured_at": j.get("captured_at"), "available_from": snapshot_available_from(j) if j.get("captured_at") else None,
            "available_from_stored": j.get("available_from"),
            "tickers": j.get("captured"),
            "universe": (j.get("universe") or {}).get("n"), "coverage": j.get("coverage"), "first_run": bool(j.get("first_run")),
            "sha256": hashlib.sha256(body).hexdigest(), "size_kb": round(len(body) / 1024, 1)}


def build(now: datetime) -> dict:
    prev = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    prev_days = {e["date"]: e for e in prev.get("days", [])}
    through = decided_through(now)
    days = []
    present = {p.name[:10] for p in SNAPS.glob("20??-??-??.json")} if SNAPS.exists() else set()
    for day in sorted(present | set(trading_days(FIRST_DAY, through) if through else [])):
        if day in present:
            days.append(file_entry(day))
        elif prev_days.get(day, {}).get("status") == "missing" and prev_days[day].get("reason") in REASONS and prev_days[day]["reason"] != "unknown":
            days.append(prev_days[day])
        else:
            reason, evidence = classify(day)
            days.append({"date": day, "status": "missing", "reason": reason, "evidence": evidence,
                         "recorded_at": now.isoformat(timespec="seconds")})
    cap = [e for e in days if e["status"] == "captured"]
    last20 = days[-20:]
    share20 = (sum(1 for e in last20 if e["status"] == "captured") / len(last20)) if last20 else None
    return {
        "cadence": "daily", "as_of": through or FIRST_DAY, "session_date": through or FIRST_DAY,
        "computed_at": now.isoformat(timespec="seconds"),
        "order": "free-analyst-data order (7 October 2026), task C: captured and missing snapshot days",
        "first_day": FIRST_DAY, "decided_through": through,
        "decision_rule": "a session is decided at 09:30 ET on the next trading day (the nightly's last retry is 06:41 ET)",
        "policy": "files are immutable (sha256 recorded); a missed day is never backfilled from a later day's values",
        "counts": {"days": len(days), "captured": len(cap), "missing": len(days) - len(cap)},
        "captured_share_last_20": round(share20, 4) if share20 is not None else None,
        "latest_captured": max((e["date"] for e in cap), default=None),
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
    log(f"through {idx['decided_through']}: {idx['counts']['captured']} of {idx['counts']['days']} days captured; "
        f"latest {idx['latest_captured']}; missing: {', '.join(miss) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
