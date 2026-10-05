#!/usr/bin/env python3
"""snapshot_alerts.py — the missed-snapshot issue (Execution Order: Make the Daily Options Snapshot
Reliable, 5 October 2026, item 2.4).

When a trading day is decided missing (data/options/vintages/_index.json, written at 16:05 ET), open ONE
GitHub issue labelled `options-snapshot-missed` with the date and the reason. When a later day's vintage is
written, close it. The mechanism is the signal alerts' (scripts/signal_alerts.py, class GitHub): `gh` with
the job token (permissions issues: write), one issue per event, dry-run whenever GITHUB_ACTIONS != "true"
(no gh call at all outside CI).

  sync                   open issues for missing days decided from ALERTS_FROM on that have none yet (open or
                         closed); close open issues whose date precedes a captured day
  sync --close-only      only the closing half (the snapshot workflow, right after it writes a vintage)
  sync --force-miss D    acceptance test 5: also open a "[TEST]" issue for day D (reason forced_test) without
                         touching the index; the next capture after D closes it like any other

Exit code 0 always (a failed gh call is reported, never fatal to the calling workflow).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import options_common as oc          # noqa: E402
import signal_alerts as sa           # noqa: E402

EVENT = "options_snapshot_missed"
LABEL = "options-snapshot-missed"
sa.LABELS[EVENT] = (LABEL, "d29922", "no option-chain vintage was written for a trading day (5-Oct-2026 order, 2.4)")
ALERTS_FROM = "2026-10-05"           # the alert starts with the order; earlier misses are recorded in the index only
INDEX = oc.VINTAGES / "_index.json"
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def title_for(day: str, test: bool = False) -> str:
    return f"{'[TEST] ' if test else ''}Options snapshot missed: {day}"


def body_for(entry: dict, test: bool = False) -> str:
    lines = [
        f"No option-chain vintage was written for **{entry['date']}** inside the 15:30–16:00 ET window.",
        "",
        f"- reason: `{entry.get('reason')}`",
        f"- evidence: {entry.get('evidence') or '—'}",
        f"- recorded: {entry.get('recorded_at') or '—'}",
        "",
        "The day stays missing: missed days are never backfilled with after-hours data, and IV rank and percentile "
        "use captured days only (`data/options/vintages/_index.json`).",
        "",
        "Checks: the external scheduler's log (`cd scheduler/worker && wrangler tail`) and the token's expiry "
        "(docs/scheduling.md); `gh run list --workflow options_snapshot.yml --limit 10`.",
        "",
        "This issue closes itself when the next trading day's vintage is written.",
    ]
    if test:
        lines = ["**Acceptance test 5 (forced miss).** The index is not changed; this checks the alert path only.", ""] + lines
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


def sync(gh: sa.GitHub, close_only: bool, force_miss: str | None) -> None:
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {"days": []}
    captured = set(oc.captured_sessions())
    issues = all_issues(gh)
    have = {DATE_RE.search(i["title"]).group(1) + ("T" if i["title"].startswith("[TEST]") else "")
            for i in issues if DATE_RE.search(i.get("title", ""))}
    if not close_only:
        for e in idx.get("days", []):
            if e.get("status") == "missing" and e["date"] >= ALERTS_FROM and e["date"] not in have:
                print(f"missing {e['date']} ({e.get('reason')}): opening the issue")
                gh.create(EVENT, title_for(e["date"]), body_for(e))
        if force_miss and force_miss + "T" not in have:
            print(f"forced miss {force_miss}: opening the test issue")
            gh.create(EVENT, title_for(force_miss, test=True),
                      body_for({"date": force_miss, "reason": "forced_test", "evidence": "dispatched with force_miss_date"}, test=True))
    opened = [i for i in issues if i.get("state") == "OPEN"]
    for i in opened:
        m = DATE_RE.search(i.get("title", ""))
        if not m:
            continue
        later = sorted(d for d in captured if d > m.group(1))
        if later:
            meta = oc.vintage_meta(later[0])
            gh._run(["issue", "close", str(i["number"]), "--comment",
                     f"The {later[0]} vintage was written (pulled {meta.get('pulled_at', '?')}); closing. "
                     f"{m.group(1)} stays recorded as missed in data/options/vintages/_index.json."]) if not gh.dry_run else None
            print(f"{'WOULD CLOSE' if gh.dry_run else 'CLOSED'} #{i['number']} ({i['title']}): {later[0]} captured")
    if gh.dry_run and not issues:
        print(f"  (dry-run: open issues are closed when a later day is captured; latest captured {max(captured) if captured else 'none'})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sync"])
    ap.add_argument("--close-only", action="store_true")
    ap.add_argument("--force-miss", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.force_miss and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.force_miss):
        print(f"--force-miss {a.force_miss!r} is not a date; ignored"); a.force_miss = None
    dry = a.dry_run or os.environ.get("GITHUB_ACTIONS") != "true"
    gh = sa.GitHub(dry_run=dry, slug=sa.repo_slug())
    try:
        sync(gh, a.close_only, a.force_miss)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: snapshot alerts failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
