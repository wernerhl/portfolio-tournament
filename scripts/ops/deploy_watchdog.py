#!/usr/bin/env python3
"""
deploy_watchdog.py — cancel deploy jobs stuck in the queue (follow-up order of 7 October 2026, F3).

On 6 October a Pages deploy job sat in the "waiting" state for 14 hours, holding the shared pages-deploy
concurrency group: three later deploys were cancelled by the group and the nightly's own deploy stayed pending, so
the site served the 5-October session until the run was cancelled by hand. This script lists the runs whose
`deploy` job has been waiting, queued or in progress for more than --max-age-min minutes and cancels them. It runs
as the first step of the nightly and intraday workflows and every 30 minutes from watchdog.yml, with the
workflow's own GITHUB_TOKEN (permissions actions: write); it never handles a credential of its own and skips the
run it is part of.

Usage:  python scripts/ops/deploy_watchdog.py [--max-age-min 30] [--job deploy] [--dry-run]
Exit code 0 always (a failed API call is reported, never fatal to the calling workflow).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

SLUG = os.environ.get("GITHUB_REPOSITORY", "wernerhl/portfolio-tournament")
STUCK = ("waiting", "queued", "in_progress", "pending", "requested")


def log(m: str) -> None:
    print(f"[deploy_watchdog] {m}", flush=True)


def gh_api(path: str, method: str = "GET"):
    cmd = ["gh", "api", path] + (["-X", method] if method != "GET" else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"gh api {path}: {type(e).__name__}"); return None
    if r.returncode:
        log(f"gh api {path}: rc {r.returncode} {r.stderr.strip()[:160]}"); return None
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        return None


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def stuck_runs(job_name: str, max_age_min: int, now: datetime) -> list[dict]:
    """Runs whose `job_name` job has been in a non-completed state for more than max_age_min minutes."""
    me = os.environ.get("GITHUB_RUN_ID")
    out = []
    seen = set()
    for st in ("waiting", "queued", "in_progress", "pending", "requested"):
        j = gh_api(f"repos/{SLUG}/actions/runs?status={st}&per_page=100")
        for run in ((j or {}).get("workflow_runs") or []):
            if str(run["id"]) == str(me) or run["id"] in seen:
                continue
            seen.add(run["id"])
            jobs = (gh_api(f"repos/{SLUG}/actions/runs/{run['id']}/jobs?per_page=50") or {}).get("jobs") or []
            for job in jobs:
                if job.get("name") != job_name or job.get("status") not in STUCK:
                    continue
                since = _ts(job.get("started_at")) or _ts(job.get("created_at")) or _ts(run.get("run_started_at")) or _ts(run.get("created_at"))
                age_min = (now - since).total_seconds() / 60.0 if since else None
                if age_min is not None and age_min > max_age_min:
                    out.append({"run_id": run["id"], "run_number": run.get("run_number"), "workflow": run.get("name"),
                                "job_status": job.get("status"), "since": since.isoformat(), "age_min": round(age_min, 1)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-min", type=int, default=30)
    ap.add_argument("--job", default="deploy")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    try:
        stuck = stuck_runs(a.job, a.max_age_min, now)
    except Exception as e:  # noqa: BLE001
        log(f"could not list runs: {type(e).__name__}: {e}"); return 0
    if not stuck:
        log(f"no {a.job} job older than {a.max_age_min} min in the waiting/queued/in-progress states"); return 0
    for s in stuck:
        if a.dry_run:
            log(f"WOULD CANCEL run {s['run_number']} ({s['workflow']}, id {s['run_id']}): {a.job} job {s['job_status']} since {s['since']} ({s['age_min']} min)")
            continue
        r = gh_api(f"repos/{SLUG}/actions/runs/{s['run_id']}/cancel", method="POST")
        log(f"{'CANCELLED' if r is not None else 'cancel FAILED for'} run {s['run_number']} ({s['workflow']}, id {s['run_id']}): "
            f"{a.job} job {s['job_status']} since {s['since']} ({s['age_min']} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
