#!/usr/bin/env python3
"""
snapshot_alerts.py — the missed analyst-snapshot issue (free-analyst-data order, 7 October 2026, task C), the
mechanism of the options snapshot's (scripts/options/snapshot_alerts.py): when a trading day is decided missing in
data/analyst/snapshots/_index.json, open ONE GitHub issue labelled `analyst-snapshot-missed` with the date and the
reason; close it when a later day's snapshot is written. `gh` with the job token (permissions issues: write);
dry-run whenever GITHUB_ACTIONS != "true".

  sync                   open issues for missing days that have none yet; close open issues once a later day is captured
  sync --force-miss D    a "[TEST]" issue for day D (reason forced_test) without touching the index

Exit code 0 always.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import signal_alerts as sa           # noqa: E402

EVENT = "analyst_snapshot_missed"
LABEL = "analyst-snapshot-missed"
sa.LABELS[EVENT] = (LABEL, "d29922", "no analyst-estimate snapshot was written for a trading day (7-Oct-2026 order, task C)")
ALERTS_FROM = "2026-10-07"
INDEX = HERE.parent.parent / "data" / "analyst" / "snapshots" / "_index.json"
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def title_for(day: str, test: bool = False) -> str:
    return f"{'[TEST] ' if test else ''}Analyst snapshot missed: {day}"


def body_for(entry: dict, test: bool = False) -> str:
    lines = [
        f"No analyst-estimate snapshot (data/analyst/snapshots/{entry['date']}.json) was written for the session **{entry['date']}** "
        "by the nightly or its retries (the day is decided at 09:30 ET on the next trading day).",
        "",
        f"- reason: `{entry.get('reason')}`",
        f"- evidence: {entry.get('evidence') or '—'}",
        f"- recorded: {entry.get('recorded_at') or '—'}",
        "",
        "The day stays missing: a snapshot is a dated observation of the consensus, and a later day's values are never "
        "backfilled into it (`data/analyst/snapshots/_index.json`). Consensus history has no free source, so every missed "
        "day is a day of history lost.",
        "",
        "Checks: `gh run list --workflow nightly.yml --limit 10`; the pipeline log's `[snapshot_estimates]` lines.",
        "",
        "This issue closes itself when a later session's snapshot is written.",
    ]
    if test:
        lines = ["**Forced miss (test).** The index is not changed; this checks the alert path only.", ""] + lines
    return "\n".join(lines)


def all_issues(gh: sa.GitHub) -> list[dict]:
    if gh.dry_run:
        print(f"  (dry-run: gh issue list --label {LABEL} --state all not queried)")
        return []
    try:
        return json.loads(gh._run(["issue", "list", "--label", LABEL, "--state", "all", "--limit", "100",
                                   "--json", "number,title,state"]) or "[]")
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: gh issue list failed: {e}")
        return []


def sync(gh: sa.GitHub, force_miss: str | None) -> None:
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {"days": []}
    captured = {e["date"]: e for e in idx.get("days", []) if e.get("status") == "captured"}
    issues = all_issues(gh)
    have = {DATE_RE.search(i["title"]).group(1) + ("T" if i["title"].startswith("[TEST]") else "")
            for i in issues if DATE_RE.search(i.get("title", ""))}
    for e in idx.get("days", []):
        if e.get("status") == "missing" and e["date"] >= ALERTS_FROM and e["date"] not in have:
            print(f"missing {e['date']} ({e.get('reason')}): opening the issue")
            gh.create(EVENT, title_for(e["date"]), body_for(e))
    if force_miss and force_miss + "T" not in have:
        print(f"forced miss {force_miss}: opening the test issue")
        gh.create(EVENT, title_for(force_miss, test=True),
                  body_for({"date": force_miss, "reason": "forced_test", "evidence": "dispatched with --force-miss"}, test=True))
    for i in [i for i in issues if i.get("state") == "OPEN"]:
        m = DATE_RE.search(i.get("title", ""))
        if not m:
            continue
        later = sorted(d for d in captured if d > m.group(1))
        if later:
            e = captured[later[0]]
            if not gh.dry_run:
                gh._run(["issue", "close", str(i["number"]), "--comment",
                         f"The {later[0]} snapshot was written (captured {e.get('captured_at', '?')}, {e.get('tickers')} names); closing. "
                         f"{m.group(1)} stays recorded as missed in data/analyst/snapshots/_index.json."])
            print(f"{'WOULD CLOSE' if gh.dry_run else 'CLOSED'} #{i['number']} ({i['title']}): {later[0]} captured")
    if gh.dry_run and not issues:
        print(f"  (dry-run: open issues close when a later day is captured; latest captured {max(captured) if captured else 'none'})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sync"])
    ap.add_argument("--force-miss", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.force_miss and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.force_miss):
        print(f"--force-miss {a.force_miss!r} is not a date; ignored"); a.force_miss = None
    dry = a.dry_run or os.environ.get("GITHUB_ACTIONS") != "true"
    gh = sa.GitHub(dry_run=dry, slug=sa.repo_slug())
    try:
        sync(gh, a.force_miss)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: analyst snapshot alerts failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
