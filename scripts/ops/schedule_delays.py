#!/usr/bin/env python3
"""schedule_delays.py — how late GitHub delivers each scheduled workflow, and how many crons never run
(Execution Order: Make the Daily Options Snapshot Reliable, 5 October 2026, item 2.7).

For every workflow with a `schedule`, over a window of trading days: expand the crons into scheduled
instants (UTC), list the workflow's schedule-event runs (gh api, which authenticates itself), and match runs
to instants. Reported per workflow: crons in the window, runs, the share of crons that never produced a run,
and the delay (run created − cron time): median, 90th percentile, maximum, the share delivered within 15
minutes, and the share more than an hour late.

GitHub's run metadata does not record which cron fired a run. Three sources, best first:
  1. the run's title: from 5 Oct every scheduled workflow sets run-name to its cron (exact);
  2. the run's log: the nightly prints GITHUB_SCHEDULE in its decide step (exact; --logs reads it);
  3. otherwise an order-preserving match (runs never precede their cron, GitHub fires in order):
     the earliest feasible cron gives an UPPER bound on each delay, the latest a LOWER bound. Both are
     reported; the never-produced share is the same under both (the same number of runs is matched).
A run more than --max-delay-h hours after every unmatched cron is left unmatched.

Usage:  python scripts/ops/schedule_delays.py --start 2026-09-22 --end 2026-10-05T18:00 [--logs nightly] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SLUG = "wernerhl/portfolio-tournament"
WF_DIR = REPO / ".github" / "workflows"


# ── cron expansion (5 fields, UTC; *, a-b, lists, steps; GitHub semantics: dom OR dow when both restricted) ──
def _field(spec: str, lo: int, hi: int) -> set[int]:
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/"); step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = map(int, part.split("-"))
        else:
            a = b = int(part)
            if step > 1:
                b = hi
        out.update(range(a, b + 1, step))
    return out


def cron_instants(expr: str, start: datetime, end: datetime) -> list[datetime]:
    mi, ho, dom, mo, dow = expr.split()
    M, H, D, MO = _field(mi, 0, 59), _field(ho, 0, 23), _field(dom, 1, 31), _field(mo, 1, 12)
    W = {d % 7 for d in _field(dow, 0, 7)}                        # 0 and 7 are Sunday
    dom_r, dow_r = dom != "*", dow != "*"
    out, day = [], start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        wd = (day.weekday() + 1) % 7                               # Monday=1 … Sunday=0
        d_ok = (day.day in D or wd in W) if (dom_r and dow_r) else (day.day in D and wd in W)
        if day.month in MO and d_ok:
            for h in sorted(H):
                for m in sorted(M):
                    t = day.replace(hour=h, minute=m)
                    if start <= t < end:
                        out.append(t)
        day += timedelta(days=1)
    return out


def _crons_of(text: str) -> tuple[str | None, list[str]]:
    y = yaml.safe_load(text) or {}
    on = y.get("on", y.get(True)) or {}
    return y.get("name"), ([c["cron"] for c in (on.get("schedule") or [])] if isinstance(on, dict) else [])


def crons_in_effect(path: str, at: datetime, cache: dict) -> list[str]:
    """The workflow's crons as committed on main at `at` (the schedules changed during the window)."""
    sha = subprocess.run(["git", "rev-list", "-1", f"--before={at:%Y-%m-%dT%H:%M:%SZ}", "HEAD", "--", path],
                         cwd=REPO, capture_output=True, text=True).stdout.strip()
    if not sha:
        return []
    if sha not in cache:
        txt = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=REPO, capture_output=True, text=True).stdout
        cache[sha] = _crons_of(txt)[1] if txt else []
    return cache[sha]


def workflows() -> dict[str, dict]:
    out = {}
    for p in sorted(WF_DIR.glob("*.yml")):
        name, crons = _crons_of(p.read_text())
        out[p.name] = {"name": name or p.stem, "crons_now": crons, "path": str(p.relative_to(REPO))}
    return out


def instants_for(meta: dict, start: datetime, end: datetime) -> tuple[list[tuple[datetime, str]], list[str]]:
    cache, inst, seen = {}, [], []
    day = start
    while day < end:
        for c in crons_in_effect(meta["path"], min(day + timedelta(days=1), end), cache):
            if c not in seen:
                seen.append(c)
            inst += [(t, c) for t in cron_instants(c, day, min(day + timedelta(days=1), end))]
        day += timedelta(days=1)
    return sorted(inst), seen


def gh_runs(wf: str, start: datetime, until: datetime) -> list[dict]:
    q = (f"repos/{SLUG}/actions/workflows/{wf}/runs?event=schedule&per_page=100"
         f"&created={start:%Y-%m-%d}..{until:%Y-%m-%d}")
    r = subprocess.run(["gh", "api", "--paginate", q, "--jq", ".workflow_runs[] | {id, created_at, display_title, conclusion}"],
                       capture_output=True, text=True)
    runs = [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()]
    for x in runs:
        x["t"] = datetime.fromisoformat(x["created_at"].replace("Z", "+00:00"))
    return sorted(runs, key=lambda x: x["t"])


def cron_from_log(run_id: int) -> str | None:
    r = subprocess.run(["gh", "run", "view", str(run_id), "-R", SLUG, "--log"], capture_output=True, text=True)
    m = re.search(r"GITHUB_SCHEDULE: (\S+ \S+ \S+ \S+ \S+)", r.stdout)
    return m.group(1) if m else None


def match(instants: list[tuple[datetime, str]], runs: list[dict], max_delay: timedelta, latest: bool) -> list[tuple[datetime, dict]]:
    """Order-preserving assignment of runs to cron instants (each run to one instant at or before it)."""
    C = sorted(instants); pairs = []
    if not latest:
        i = 0
        for r in runs:
            while i < len(C) and C[i][0] <= r["t"] and r["t"] - C[i][0] > max_delay:
                i += 1                                              # a cron this old never produced this run
            if i < len(C) and C[i][0] <= r["t"]:
                pairs.append((C[i][0], r)); i += 1
    else:
        i = len(C) - 1
        for r in reversed(runs):
            while i >= 0 and C[i][0] > r["t"]:
                i -= 1
            if i >= 0 and r["t"] - C[i][0] <= max_delay:
                pairs.append((C[i][0], r)); i -= 1
        pairs.reverse()
    return pairs


def stats(delays_min: list[float], n_crons: int) -> dict:
    if not delays_min:
        return {"matched": 0, "never_produced_share": 1.0 if n_crons else None}
    s = sorted(delays_min)
    p90 = s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]
    return {"matched": len(s), "never_produced_share": round(1 - len(s) / n_crons, 3) if n_crons else None,
            "median_min": round(statistics.median(s), 1), "p90_min": round(p90, 1), "max_min": round(s[-1], 1),
            "within_15min_share": round(sum(1 for d in s if d <= 15) / n_crons, 3),
            "over_60min_share": round(sum(1 for d in s if d > 60) / n_crons, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-22")
    ap.add_argument("--end", default=None, help="UTC; crons scheduled before this count (default: now - 8 h)")
    ap.add_argument("--max-delay-h", type=float, default=10.0)
    ap.add_argument("--logs", default="nightly", help="comma list of workflow stems whose logs carry GITHUB_SCHEDULE")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    end = (datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end
           else datetime.now(timezone.utc) - timedelta(hours=8))
    until = end + timedelta(hours=a.max_delay_h)
    maxd = timedelta(hours=a.max_delay_h)
    log_wfs = {s.strip() + ".yml" for s in a.logs.split(",") if s.strip()}
    out = {"window_utc": [start.isoformat(), end.isoformat()], "max_delay_h": a.max_delay_h, "workflows": {}}
    for wf, meta in workflows().items():
        inst, crons = instants_for(meta, start, end)
        if not inst:
            continue
        runs = [r for r in gh_runs(wf, start, until) if r["t"] >= start]
        for r in runs:
            r["cron"] = next((c for c in crons if c in (r.get("display_title") or "")), None) or \
                        (cron_from_log(r["id"]) if wf in log_wfs else None)
        known = [r for r in runs if r.get("cron")]
        rec = {"name": meta["name"], "crons": crons, "n_crons": len(inst), "n_runs": len(runs),
               "runs_with_known_cron": len(known)}
        if known:
            exact = []
            for c in crons:
                rs = [r for r in known if r["cron"] == c]
                exact += match([(t, cc) for t, cc in inst if cc == c], rs, maxd, latest=False)
            rec["exact_known_runs"] = stats([(r["t"] - t).total_seconds() / 60 for t, r in exact], len(inst))
            rec["exact_known_runs"]["note"] = (f"{len(known)} of {len(runs)} runs carry their cron; delays exact for those, "
                                               "never-produced share a lower bound when some runs are unknown")
        lo = match(inst, runs, maxd, latest=True); hi = match(inst, runs, maxd, latest=False)
        rec["lower_bound"] = stats([(r["t"] - t).total_seconds() / 60 for t, r in lo], len(inst))
        rec["upper_bound"] = stats([(r["t"] - t).total_seconds() / 60 for t, r in hi], len(inst))
        out["workflows"][wf] = rec
        ex = rec.get("exact_known_runs") or {}
        print(f"{wf:26s} crons {len(inst):4d} runs {len(runs):3d} (cron known {len(known):3d}) never {rec['lower_bound'].get('never_produced_share')} "
              f"median {rec['lower_bound'].get('median_min')}–{rec['upper_bound'].get('median_min')} "
              f"p90 {rec['lower_bound'].get('p90_min')}–{rec['upper_bound'].get('p90_min')} "
              f"{'| exact: median ' + str(ex.get('median_min')) + ' p90 ' + str(ex.get('p90_min')) + ' never ' + str(ex.get('never_produced_share')) if ex else ''}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
