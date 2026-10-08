#!/usr/bin/env python3
"""
test_workflows.py — every workflow file passes actionlint (third follow-up of 7 October 2026, H2).

Run before every commit that touches .github/workflows/. The F3 break (a step with both `run:` and `with:`) is
accepted by a YAML parser and rejected by GitHub; actionlint reports it. The linter is the pinned release that
scripts/ops/workflow_lint.py downloads once and checks by sha256; shellcheck and pyflakes are off.

    python tests/test_workflows.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts" / "ops"))
import workflow_lint as wl   # noqa: E402


def test_every_workflow_passes_actionlint():
    n, out = wl.lint(REPO)
    assert n == 0, f"{n} actionlint error(s):\n{out}"


def test_the_f3_break_is_reported(tmp=None):
    """A step with both run and with, as intraday.yml stood at 0fc578f, is an error."""
    import tempfile
    d = Path(tempfile.mkdtemp()); (d / ".github" / "workflows").mkdir(parents=True)
    (d / ".github" / "workflows" / "broken.yml").write_text(
        "name: broken\non: {workflow_dispatch: {}}\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n"
        "      - uses: actions/checkout@v7\n      - name: x\n        run: echo hi\n        with:\n          sparse-checkout: scripts\n")
    n, out = wl.lint(d)
    assert n >= 1 and "with" in out, out


def test_an_undeclared_input_in_run_name_is_reported():
    """`inputs.trigger` in run-name without a declared input, as nightly.yml stood at bdc9266."""
    import tempfile
    d = Path(tempfile.mkdtemp()); (d / ".github" / "workflows").mkdir(parents=True)
    (d / ".github" / "workflows" / "w.yml").write_text(
        "name: w\nrun-name: \"w · ${{ inputs.trigger || github.event_name }}\"\non:\n  workflow_dispatch:\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo hi\n")
    n, out = wl.lint(d)
    assert n >= 1 and "trigger" in out, out


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except wl.LinterUnavailable as e:
                print(f"FAIL {name}: the linter could not run ({e})"); fails += 1
            except Exception:
                print(f"FAIL {name}\n{traceback.format_exc()}"); fails += 1
    n = sum(1 for k, v in globals().items() if k.startswith("test_") and callable(v))
    print(f"\n{n - fails} passed, {fails} failed")
    sys.exit(1 if fails else 0)
