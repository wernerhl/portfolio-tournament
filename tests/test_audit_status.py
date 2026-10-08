#!/usr/bin/env python3
"""
tests/test_audit_status.py — the referee fails closed (follow-up order of 7 October 2026, F1):

  1. a report file containing only a traceback gives CRITICAL referee:crashed and exit 1
  2. a report file with findings and no final REFEREE COMPLETE line gives referee:crashed and exit 1
  3. a check that raises inside audit_nightly.py becomes CRITICAL referee:check_failed:<name>, the other checks'
     findings are still present, and the report ends with the REFEREE COMPLETE line
  4. a complete report with findings and the final line passes through unchanged (no referee:* finding)

The third test runs the referee on a scratch copy of data/ with one served file made unreadable to its check.

    .venv/bin/python tests/test_audit_status.py
"""
from __future__ import annotations
import io
import json
import shutil
import subprocess
import sys
import tempfile
import traceback
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATUS_PY = REPO / "scripts" / "audit_status.py"
RESULTS = []


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def status_run(report_text: str) -> tuple[int, dict, str]:
    """audit_status.py on a report file inside a temporary directory that is not a git repository (the restore
    step's git calls fail harmlessly there and nothing in the repository is touched)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "audit.txt"; rep.write_text(report_text)
        st = td / "status.json"; st.write_text(json.dumps({"last_success": "2026-10-05T22:00:00-04:00", "session_date": "2026-10-05"}))
        r = subprocess.run([sys.executable, str(STATUS_PY), str(rep), "--status", str(st), "--restore-dir", str(td / "served")],
                           cwd=td, capture_output=True, text=True)
        return r.returncode, json.loads(st.read_text()), r.stdout + r.stderr


def test_traceback_only_report_is_critical():
    rc, st, out = status_run("last trading session: 2026-10-06\nTraceback (most recent call last):\n  File \"x.py\", line 1, in <module>\n"
                             "TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'\n")
    assert rc == 1, (rc, out)
    assert "referee:crashed" in st["audit"]["critical"], st["audit"]
    assert st["failure_reason"].startswith("audit: referee:crashed"), st.get("failure_reason")


def test_findings_without_final_line_is_critical():
    rc, st, _ = status_run("last trading session: 2026-10-06\n[HIGH    ] options:captured_share       4 of 8 days\n[INFO    ] book:export                  none\n\n2 findings; 0 CRITICAL\n")
    assert rc == 1 and "referee:crashed" in st["audit"]["critical"], st["audit"]
    assert "options:captured_share" in st["audit"]["high"]


def test_complete_report_passes():
    rc, st, _ = status_run("last trading session: 2026-10-06\n[HIGH    ] options:captured_share       4 of 8 days\n\n1 findings; 0 CRITICAL\nREFEREE COMPLETE: 1 findings; 0 CRITICAL\n")
    assert rc == 0 and not st["audit"]["critical"], st["audit"]
    assert not any(c.startswith("referee:") for c in st["audit"]["high"] + st["audit"]["critical"])


def test_finding_quoting_traceback_passes():
    """G6: the word Traceback inside a finding's message (the options check quotes the step's annotation) is not a crash;
    only a line that begins a Python traceback outside a finding, or a missing final line, is."""
    rc, st, _ = status_run("last trading session: 2026-10-07\n[HIGH    ] options:vintage_missing      reason push_failed (run 51: 'Traceback (most recent call last):' quoted from the step)\n\n1 findings; 0 CRITICAL\nREFEREE COMPLETE: 1 findings; 0 CRITICAL\n")
    assert rc == 0 and not st["audit"]["critical"] and "options:vintage_missing" in st["audit"]["high"], st["audit"]
    rc2, st2, _ = status_run("last trading session: 2026-10-07\n[HIGH    ] x:y                          fine\nTraceback (most recent call last):\n  File \"a.py\", line 1\nValueError: boom\n\n1 findings; 0 CRITICAL\nREFEREE COMPLETE: 1 findings; 0 CRITICAL\n")
    assert rc2 == 1 and "referee:crashed" in st2["audit"]["critical"], st2["audit"]


def test_check_that_raises_is_reported_and_the_rest_still_run():
    sys.path.insert(0, str(REPO / "scripts"))
    import audit_nightly as an
    with tempfile.TemporaryDirectory() as td:
        data = Path(td) / "data"
        shutil.copytree(REPO / "data", data, ignore=shutil.ignore_patterns("*.parquet", "vintages", "v4_vintages", "source"))
        # the picks check iterates the windows list; an integer there raises inside that check only
        (data / "picks_vs_qqq.json").write_text(json.dumps({"windows": 5, "label": "DESCRIPTIVE"}))
        an.F.clear()
        buf = io.StringIO()
        with redirect_stdout(buf):
            an.main(str(data), str(data / "screen"))
        out = buf.getvalue()
    import re
    LINE = re.compile(r"^\[(CRITICAL|HIGH|MEDIUM|INFO)\s*\]\s+(\S+)")
    lines = [l for l in out.splitlines() if LINE.match(l)]
    checks = [LINE.match(l).group(2) for l in lines]
    assert any(c.startswith("referee:check_failed:picks") for c in checks), checks[:10]
    assert any(c.startswith(("entry:", "options:", "governance:", "analyst:", "tournament:", "identity:")) for c in checks), "other checks must still report"
    assert out.rstrip().splitlines()[-1].startswith("REFEREE COMPLETE:"), out.rstrip().splitlines()[-2:]
    n = int(out.rstrip().splitlines()[-1].split()[2])
    assert n == len(lines), (n, len(lines))


if __name__ == "__main__":
    for fn in [test_traceback_only_report_is_critical, test_findings_without_final_line_is_critical, test_complete_report_passes,
               test_finding_quoting_traceback_passes, test_check_that_raises_is_reported_and_the_rest_still_run]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
