#!/usr/bin/env python3
"""backup_cron_gate.py — a GitHub cron is a backup once the external scheduler dispatches the workflow
(Execution Order: Make the Daily Options Snapshot Reliable, 5 October 2026, items 2.1 and 2.7).

A scheduled (cron) run proceeds only when no successful run of the same workflow already covers its slot:
  --within-min N      a successful run created in the last N minutes
  --since-et HH:MM    a successful run created today since HH:MM ET (e.g. the market-open snapshot)
Any other event (a dispatch from the scheduler, a manual run) always proceeds. Without the external
scheduler, nothing has run, so the backup crons behave exactly as before.

Writes run=true|false (and why=...) to $GITHUB_OUTPUT. The run history is read with `gh api`, which
authenticates itself with the job token (permissions actions: read). On any API failure the run proceeds:
a duplicate refresh is harmless, a missing one is not.

Usage:  python scripts/ops/backup_cron_gate.py --workflow intraday.yml (--within-min 25 | --since-et 09:30)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def out(run: bool, why: str) -> int:
    print(f"backup-cron gate: run={'true' if run else 'false'} ({why})")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"run={'true' if run else 'false'}\nwhy={why}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--within-min", type=float)
    g.add_argument("--since-et", default=None)
    ap.add_argument("--now", default=None, help="UTC ISO time (tests)")
    a = ap.parse_args()
    if os.environ.get("GITHUB_EVENT_NAME", "schedule") != "schedule":
        return out(True, f"{os.environ.get('GITHUB_EVENT_NAME')} event")
    now = datetime.fromisoformat(a.now).replace(tzinfo=timezone.utc) if a.now else datetime.now(timezone.utc)
    if a.within_min is not None:
        since = now - timedelta(minutes=a.within_min)
    else:
        h, m = map(int, a.since_et.split(":"))
        since = now.astimezone(ET).replace(hour=h, minute=m, second=0, microsecond=0).astimezone(timezone.utc)
    slug = os.environ.get("GITHUB_REPOSITORY", "wernerhl/portfolio-tournament")
    own = os.environ.get("GITHUB_RUN_ID")
    q = f"repos/{slug}/actions/workflows/{a.workflow}/runs?status=success&per_page=20&created=>={since:%Y-%m-%dT%H:%M:%SZ}"
    try:
        r = subprocess.run(["gh", "api", q], capture_output=True, text=True, timeout=60)
        runs = json.loads(r.stdout).get("workflow_runs", []) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        runs = None
    if runs is None:
        return out(True, "run history not readable; proceeding")
    done = [x for x in runs if str(x.get("id")) != own]
    if done:
        x = done[0]
        return out(False, f"run {x.get('run_number')} ({x.get('event')}, {x.get('created_at')}) already covers this slot")
    return out(True, f"no successful run since {since:%H:%M} UTC")


if __name__ == "__main__":
    sys.exit(main())
