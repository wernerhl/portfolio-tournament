#!/usr/bin/env python3
"""
audit_alerts.py — issues for persistent referee findings, and the age of every HIGH finding.

The referee (scripts/audit_nightly.py) writes reports/audit_last.txt every night. A HIGH finding there never
blocks the publish and, until now, was surfaced only in the status strips: a dead feed (rates:stale since
2-Oct-2026) or a month-old book (book:holdings_age) could sit in the report for weeks. This script, run in the
nightly's alerts step with the job token:

  1. keeps data/audit_findings_state.json: for every HIGH or CRITICAL check in the report, the session it was
     first seen, the session last seen and the latest detail line. A check that leaves the report is dropped.
  2. opens ONE issue labelled `audit-finding` per check in WATCH while it is in the report, and closes it when
     the check is gone. An issue whose check has been in the report for CHRONIC_SESSIONS or more sessions gets
     the `audit-chronic` label (once, with a comment).

The mechanism is the signal alerts' (scripts/signal_alerts.py, class GitHub): dry-run whenever
GITHUB_ACTIONS != "true" (no gh call outside CI). Exit code 0 always.

Usage:  python scripts/audit_alerts.py sync [--report reports/audit_last.txt] [--dry-run]
        python scripts/audit_alerts.py status [--report ...]      # print the parsed findings with their ages
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

STATE = ROOT / "data" / "audit_findings_state.json"
REPORT = ROOT / "reports" / "audit_last.txt"

# checks that get an issue: each one is a feed or a record that a person has to fix; the rest stay in the strips
WATCH = {
    "rates:stale": "a global-rates series is older than its allowed lag (see data/rates/series_meta.json `error`)",
    "book:holdings_age": "data/holdings.json is older than five sessions: confirm or re-export the account",
    "universe:stale_ticker": "universe names with no price bar in five sessions (delisted, merged or renamed?)",
    "governance:review_overdue": "visibility overrides past their review_by date",
    "tournament:dead_columns": "model columns empty in the latest rows but populated earlier",
    "nullguard": "an input to a safety check is null",
}
LABEL = "audit-finding"
CHRONIC_LABEL = "audit-chronic"
CHRONIC_SESSIONS = 10

LINE_RE = re.compile(r"^\[(CRITICAL|HIGH|MEDIUM|LOW|INFO)\s*\]\s+(\S+)\s+(.*)$")
SESSION_RE = re.compile(r"^last trading session:\s*(\d{4}-\d{2}-\d{2})")


def parse(report: Path) -> tuple[str | None, dict[str, dict]]:
    """The report's session and {check: {severity, details}} for HIGH and CRITICAL lines."""
    session, out = None, {}
    for ln in report.read_text().splitlines():
        m = SESSION_RE.match(ln)
        if m:
            session = m.group(1); continue
        m = LINE_RE.match(ln)
        if not m or m.group(1) not in ("CRITICAL", "HIGH"):
            continue
        sev, check, detail = m.groups()
        rec = out.setdefault(check, {"severity": sev, "details": []})
        if sev == "CRITICAL":
            rec["severity"] = "CRITICAL"
        rec["details"].append(detail.strip())
    return session, out


def sessions_between(a: str, b: str) -> int:
    """Trading sessions from a to b (a counts as 1). Falls back to weekdays when the calendar is unavailable."""
    from datetime import date, timedelta
    try:
        from trading_calendar import is_trading_day
    except Exception:  # noqa: BLE001
        is_trading_day = lambda d: d.weekday() < 5            # noqa: E731
    d, end, n = date.fromisoformat(a), date.fromisoformat(b), 0
    while d <= end:
        if is_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n


def update_state(session: str, found: dict[str, dict], prev: dict) -> dict:
    checks = {}
    for check, rec in sorted(found.items()):
        old = (prev.get("checks") or {}).get(check) or {}
        first = old.get("first_seen") or session
        checks[check] = {
            "severity": rec["severity"],
            "first_seen": first,
            "last_seen": session,
            "age_sessions": sessions_between(first, session),
            "n_lines": len(rec["details"]),
            "detail": rec["details"][0][:300],
            **({"issue": old["issue"]} if old.get("issue") else {}),
            **({"chronic_flagged": True} if old.get("chronic_flagged") else {}),
        }
    # cadence/session_date: the referee's freshness scan reads them (as data/alert_state.json declares them)
    return {"schema": 1, "cadence": "daily", "session_date": session, "session": session,
            **({"seeded_from": prev["seeded_from"]} if prev.get("seeded_from") else {}), "checks": checks}


def issue_title(check: str) -> str:
    return f"Audit finding: {check}"


def issue_body(check: str, rec: dict, details: list[str]) -> str:
    lines = [
        f"The nightly referee has reported **{check}** ({rec['severity']}) since session **{rec['first_seen']}** "
        f"({rec['age_sessions']} session(s)).",
        "",
        f"What it means: {WATCH.get(check, '—')}.",
        "",
        "Latest report lines (`reports/audit_last.txt`):",
        "",
        *[f"- `{d[:400]}`" for d in details[:12]],
        "",
        "This issue closes itself on the first nightly whose report no longer carries the check. "
        f"It is labelled `{CHRONIC_LABEL}` after {CHRONIC_SESSIONS} sessions. Ages: `data/audit_findings_state.json`.",
    ]
    return "\n".join(lines)


def gh_issues(gh, label: str) -> list[dict]:
    if gh.dry_run:
        return []
    try:
        return json.loads(gh._run(["issue", "list", "--label", label, "--state", "open", "--limit", "50",
                                   "--json", "number,title"]) or "[]")
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: gh issue list failed: {e}")
        return []


def sync_issues(gh, state: dict, found: dict[str, dict]) -> None:
    open_ = {i["title"]: i["number"] for i in gh_issues(gh, LABEL)}
    if not gh.dry_run:
        for name, color, desc in ((LABEL, "fbca04", "a persistent nightly-referee finding (scripts/audit_alerts.py)"),
                                  (CHRONIC_LABEL, "b60205", f"a referee finding open {CHRONIC_SESSIONS}+ sessions")):
            try:
                gh._run(["label", "create", name, "--color", color, "--description", desc, "--force"])
            except Exception as e:  # noqa: BLE001
                print(f"  WARNING: could not ensure label {name}: {e}")
    for check in sorted(WATCH):
        title = issue_title(check)
        rec = state["checks"].get(check)
        num = open_.get(title)
        if rec:
            if num is None:
                print(f"  {'WOULD OPEN' if gh.dry_run else 'OPENING'}: {title} (since {rec['first_seen']})")
                if not gh.dry_run:
                    try:
                        url = gh._run(["issue", "create", "--title", title, "--label", LABEL,
                                       "--body", issue_body(check, rec, found[check]["details"])]).strip()
                        m = re.search(r"/issues/(\d+)", url)
                        num = int(m.group(1)) if m else None
                    except Exception as e:  # noqa: BLE001
                        print(f"  WARNING: gh issue create failed: {e}")
            else:
                print(f"  #{num} already open: {title} ({rec['age_sessions']} sessions)")
            if num:
                rec["issue"] = num
            if num and rec["age_sessions"] >= CHRONIC_SESSIONS and not rec.get("chronic_flagged"):
                print(f"  {'WOULD LABEL' if gh.dry_run else 'LABELLING'} #{num} {CHRONIC_LABEL}")
                if not gh.dry_run:
                    try:
                        gh._run(["issue", "edit", str(num), "--add-label", CHRONIC_LABEL])
                        gh._run(["issue", "comment", str(num), "--body",
                                 f"In the referee's report for {rec['age_sessions']} sessions (since {rec['first_seen']}): chronic."])
                        rec["chronic_flagged"] = True
                    except Exception as e:  # noqa: BLE001
                        print(f"  WARNING: could not flag #{num} chronic: {e}")
        elif num is not None:
            print(f"  {'WOULD CLOSE' if gh.dry_run else 'CLOSING'} #{num}: {title}")
            if not gh.dry_run:
                try:
                    gh._run(["issue", "close", str(num), "--comment",
                             f"The referee's report for {state['session']} no longer carries {check}; closing."])
                except Exception as e:  # noqa: BLE001
                    print(f"  WARNING: gh issue close failed: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sync", "status"])
    ap.add_argument("--report", type=Path, default=REPORT)
    ap.add_argument("--state", type=Path, default=STATE)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        session, found = parse(a.report)
        if not session:
            print("audit_alerts: the report names no session; nothing done"); return 0
        prev = json.loads(a.state.read_text()) if a.state.exists() else {}
        state = update_state(session, found, prev)
        if a.cmd == "status":
            for c, r in state["checks"].items():
                print(f"{r['severity']:8} {c:32} {r['age_sessions']:3} session(s) since {r['first_seen']}")
            return 0
        import signal_alerts as sa
        dry = a.dry_run or os.environ.get("GITHUB_ACTIONS") != "true"
        sync_issues(sa.GitHub(dry_run=dry, slug=sa.repo_slug()), state, found)
        if not a.dry_run:
            a.state.parent.mkdir(parents=True, exist_ok=True)
            a.state.write_text(json.dumps(state, indent=1) + "\n")
        print(f"audit_alerts: {len(state['checks'])} HIGH/CRITICAL check(s) tracked for {session}")
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: audit alerts failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
