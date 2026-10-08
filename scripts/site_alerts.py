#!/usr/bin/env python3
"""
site_alerts.py — the site-stale issue (follow-up order of 7 October 2026, F3).

The referee's check site:stale fetches the served data/status.json from the live site and raises HIGH when its
session is more than one trading session behind the last session. This script, run in the nightly's alerts step
with the job token, opens ONE issue labelled `site-stale` while that holds and closes it when the site has caught
up. The mechanism is the signal alerts' (scripts/signal_alerts.py, class GitHub): dry-run whenever
GITHUB_ACTIONS != "true". Exit code 0 always.

Usage:  python scripts/site_alerts.py sync [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import signal_alerts as sa                                      # noqa: E402
from trading_calendar import last_completed_session, now_et, prev_trading_day   # noqa: E402

EVENT = "site_stale"
LABEL = "site-stale"
sa.LABELS[EVENT] = (LABEL, "d29922", "the live site serves a session more than one trading session behind (7-Oct-2026 order, F3)")
LIVE = "https://wernerhl.github.io/portfolio-tournament/data/status.json"
TITLE = "Live site stale"


def live_status() -> dict | None:
    try:
        req = urllib.request.Request(LIVE + f"?t={int(datetime.now().timestamp())}", headers={"User-Agent": "portfolio-tournament site check"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        print(f"live status.json not readable: {type(e).__name__}: {e}")
        return None


def staleness() -> dict:
    """The live session against the last completed session: stale when more than one trading session behind."""
    st = live_status() or {}
    live = str(st.get("session_date") or "")[:10]
    last = last_completed_session()
    allowed = prev_trading_day(date.fromisoformat(last))
    age_h = None
    if st.get("last_success"):
        try:
            age_h = round((datetime.now(timezone.utc) - datetime.fromisoformat(str(st["last_success"])).astimezone(timezone.utc)).total_seconds() / 3600, 1)
        except ValueError:
            pass
    return {"live_session": live or None, "last_session": last, "allowed_session": allowed, "age_hours": age_h,
            "stale": bool(live) and live < allowed, "unreachable": not st}


def sync(gh: sa.GitHub) -> None:
    s = staleness()
    print(f"live site: session {s['live_session']} (last success {s['age_hours']} h ago); last session {s['last_session']}; "
          f"{'STALE' if s['stale'] else 'unreachable' if s['unreachable'] else 'current or one session behind'}")
    issues = []
    if not gh.dry_run:
        try:
            issues = json.loads(gh._run(["issue", "list", "--label", LABEL, "--state", "open", "--limit", "20", "--json", "number,title"]) or "[]")
        except Exception as e:  # noqa: BLE001
            print(f"  WARNING: gh issue list failed: {e}")
    if s["stale"]:
        if issues:
            print(f"  issue #{issues[0]['number']} already open")
        else:
            body = (f"The live site serves **{s['live_session']}** while the last completed session is **{s['last_session']}** "
                    f"(more than one trading session behind; last successful publish {s['age_hours']} hours ago).\n\n"
                    "Checks: `gh run list --limit 10` for cancelled or waiting deploy jobs (the watchdog cancels a deploy job stuck "
                    "for more than 30 minutes: `.github/workflows/watchdog.yml`), `data/status.json` on main for a rejected publish "
                    "(failure_reason), and the Pages deployment history.\n\nThis issue closes itself when the site catches up.")
            print(f"  {'WOULD OPEN' if gh.dry_run else 'OPENING'} the site-stale issue")
            gh.create(EVENT, f"{TITLE}: serving {s['live_session']} on {now_et():%Y-%m-%d}", body)
    else:
        for i in issues:
            if not gh.dry_run:
                gh._run(["issue", "close", str(i["number"]), "--comment", f"The live site serves {s['live_session']} (last session {s['last_session']}); closing."])
            print(f"  {'WOULD CLOSE' if gh.dry_run else 'CLOSED'} #{i['number']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sync", "status"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "status":
        print(json.dumps(staleness(), indent=1)); return 0
    dry = a.dry_run or os.environ.get("GITHUB_ACTIONS") != "true"
    gh = sa.GitHub(dry_run=dry, slug=sa.repo_slug())
    try:
        sync(gh)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: site alerts failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
