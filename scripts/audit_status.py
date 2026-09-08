#!/usr/bin/env python3
"""audit_status.py — post-publish audit plumbing (order item 6).

Parses audit_nightly.py output and records the result in status.json:
  * CRITICAL → served files under --restore-dir are restored to the last good
    commit (a rejected publish writes nothing), status.json names the failing
    checks in failure_reason, exit 1 (the workflow step fails; the deploy then
    publishes the last good board + the new status.json so the dashboard
    shows the rejection — the [8.2] semantics).
  * HIGH → logged in status.json.audit.high; surfaced in the dashboard status
    strip; never blocks.

usage: audit_status.py <audit_report.txt> --status <status.json> --restore-dir <dir>
"""
import json, re, subprocess, sys
from datetime import datetime
from pathlib import Path

LINE = re.compile(r"^\[(CRITICAL|HIGH|MEDIUM|INFO)\s*\]\s+(\S+)\s+(.*)$")


def main() -> int:
    args = sys.argv[1:]
    report = Path(args[0])
    status = Path(args[args.index("--status") + 1]) if "--status" in args else Path("data/status.json")
    restore = Path(args[args.index("--restore-dir") + 1]) if "--restore-dir" in args else Path("data")
    repo = status.resolve().parent.parent if status.resolve().parent.name == "data" else Path.cwd()

    # Order 9-Sept, B3: each repository's deploy is blocked only by CRITICAL
    # findings whose label belongs to that repository. Cross-file findings
    # (xfile:*) are reported in both status strips and block neither.
    scope = args[args.index("--scope") + 1] if "--scope" in args else "tournament"

    def scope_of(check: str) -> str:
        if check.startswith("xfile:"):
            return "xfile"
        if check.startswith("screener:") or check in ("governance:visibility", "governance:review_overdue"):
            return "screener"
        return "tournament"

    findings = []
    for ln in report.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(ln.strip())
        if m:
            findings.append((m.group(1), m.group(2), m.group(3)))
    crit_all = sorted({c for s, c, _ in findings if s == "CRITICAL"})
    crit = sorted({c for c in crit_all if scope_of(c) == scope})            # blocking here
    crit_other = sorted({c for c in crit_all if scope_of(c) not in (scope, "xfile")})
    high = sorted({c for s, c, _ in findings if s == "HIGH"})
    xfile = sorted({f"{s}:{c}" for s, c, _ in findings if scope_of(c) == "xfile" and s in ("CRITICAL", "HIGH")})
    block = {
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": scope,
        "n_findings": len(findings),
        "critical": crit,                 # blocking for THIS repository
        "critical_other_repo": crit_other, # reported, does not block here
        "xfile": xfile,                   # reported in both strips, blocks neither
        "high": high,
        "report": str(report),
    }

    if crit:
        # Served files back to the last good commit; ONLY status.json changes.
        subprocess.run(["git", "checkout", "--", str(restore)], cwd=repo, check=False)
        subprocess.run(["git", "clean", "-fdq", str(restore)], cwd=repo, check=False)

    prev = {}
    try:
        prev = json.loads(status.read_text())
    except Exception:
        pass
    now = block["ran_at"]
    out = dict(prev)
    out["audit"] = block
    if crit:
        out["last_attempt"] = now
        out["failure_reason"] = "audit: " + ", ".join(crit)
        # last_success preserved from the restored (last good) status
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(json.dumps(out, indent=1))
    print(f"audit [{scope}]: {len(findings)} findings — blocking CRITICAL {crit or 'none'} · "
          f"other-repo CRITICAL {crit_other or 'none'} · xfile {xfile or 'none'} · HIGH {high or 'none'}")
    if crit:
        print("::error::audit CRITICAL — served files restored to last good; status.json names the checks")
    return 1 if crit else 0


if __name__ == "__main__":
    sys.exit(main())
