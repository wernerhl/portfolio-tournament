#!/usr/bin/env python3
"""
tests/test_snapshot_guard.py — order 5-Oct-2026, item 2.2: one writer per day, without a concurrency queue.

Throwaway git repositories (a bare "origin" and clones carrying a copy of scripts/), the provider pull faked,
the clock set inside the window (NOW_ET_OVERRIDE). Scenarios:
  A  a second run after the first pushed: exits "already_written" before pulling, writes nothing;
  B  a race (acceptance 2): both pull; the loser's push is rejected, it finds the vintage on origin,
     discards its own and exits "push_conflict" without retrying — one vintage, one push;
  C  a push rejected by an unrelated commit (another bot): rebased and pushed, "written";
  D  outside the window: "outside_window", nothing written.

    .venv/bin/python tests/test_snapshot_guard.py
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
RESULTS = []

HARNESS = textwrap.dedent('''
    import sys, os, json, subprocess
    root = sys.argv[1]
    sys.path.insert(0, os.path.join(root, "scripts", "options")); sys.path.insert(0, os.path.join(root, "scripts"))
    import pandas as pd
    import snapshot_chains as sc
    oc = sc.oc
    oc.closes = lambda tks, s: (pd.DataFrame(), {"store": "fake"})
    oc.risk_free = lambda: (0.04, "2026-10-01")
    oc.analyzed_universe = lambda: {"AAA": ["held"], "BBB": ["board"]}
    oc.dividend_yield = lambda tk: (0.0, "fake")
    sc.live_spot = lambda tk: (100.0, "fake tape")
    hook = os.environ.pop("DURING_PULL", None)    # a command run while this run is pulling (the race); not inherited
    def fake_pull(tk, session, spot, r, q, max_days):
        global hook
        if hook:
            subprocess.run(hook, shell=True, check=True); hook = None
        df = pd.DataFrame({"ticker": [tk] * 2, "expiry": ["2026-11-20"] * 2, "cp": ["c", "p"], "strike": [100.0, 100.0],
                           "quote": ["mid", "mid"], "iv": [0.3, 0.3]})
        return df, {"n_expiries": 1, "n_expiry_failures": 0}
    sc.pull_chain = fake_pull
    sys.argv = ["snapshot_chains.py", "--publish"]
    rc = sc.main()
    print("RC", rc)
''')


def sh(cmd, cwd=None, env=None):
    r = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{cmd}: {r.stderr[-400:]}")
    return r.stdout


def setup(tmp: Path) -> tuple[Path, Path, Path]:
    origin = tmp / "origin.git"
    sh(f"git init -q --bare -b main {origin}")
    seed = tmp / "seed"
    sh(f"git clone -q {origin} {seed}")
    shutil.copytree(REPO / "scripts", seed / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (seed / "data" / "options" / "vintages").mkdir(parents=True)
    (seed / "data" / "options" / "vintages" / ".keep").write_text("")
    sh("git add -A && git -c user.name=t -c user.email=t@t commit -q -m seed && git push -q origin HEAD:main", cwd=seed)
    a, b = tmp / "a", tmp / "b"
    sh(f"git clone -q {origin} {a}"); sh(f"git clone -q {origin} {b}")
    (tmp / "harness.py").write_text(HARNESS)
    return origin, a, b


def run_clone(clone: Path, tmp: Path, when: str, during: str | None = None) -> tuple[str, str]:
    env = {**os.environ, "NOW_ET_OVERRIDE": when, "SNAPSHOT_TRIGGER": f"test {clone.name}"}
    env.pop("GITHUB_OUTPUT", None)
    if during:
        env["DURING_PULL"] = during
    r = subprocess.run([PY, str(tmp / "harness.py"), str(clone)], cwd=clone, env=env, capture_output=True, text=True)
    out = r.stdout + r.stderr
    outcome = next((ln.split("options snapshot: ")[1].split(" —")[0] for ln in out.splitlines() if "options snapshot: " in ln), "?")
    return outcome, out


def origin_log(origin: Path) -> list[str]:
    return sh(f"git --git-dir={origin} log --format=%s main").splitlines()


def check(name, fn):
    try:
        fn(); RESULTS.append((name, True)); print(f"PASS {name}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False)); print(f"FAIL {name}: {e}")


WHEN = "2026-10-06T15:41"
SESSION = "2026-10-06"


def scenario_a():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t); origin, a, b = setup(tmp)
        o1, out1 = run_clone(a, tmp, WHEN)
        assert o1 == "written", out1
        o2, out2 = run_clone(b, tmp, WHEN)
        assert o2 == "already_written", out2
        assert not (b / "data/options/vintages" / SESSION).exists(), "B pulled anyway"
        pushes = [m for m in origin_log(origin) if m.startswith("🧾 options vintage")]
        assert len(pushes) == 1, pushes


def scenario_b():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t); origin, a, b = setup(tmp)
        # B starts first and is mid-pull when A runs to completion and pushes: B's push is rejected
        during = f"NOW_ET_OVERRIDE={WHEN} SNAPSHOT_TRIGGER='test a' {PY} {tmp / 'harness.py'} {a} > {tmp / 'a.log'} 2>&1"
        o_b, out_b = run_clone(b, tmp, WHEN, during=during)
        a_log = (tmp / "a.log").read_text()
        assert "options snapshot: written" in a_log, a_log
        assert o_b == "push_conflict", out_b
        assert "already written" in out_b, out_b
        pushes = [m for m in origin_log(origin) if m.startswith("🧾 options vintage")]
        assert len(pushes) == 1, pushes
        assert "test a" in pushes[0], pushes
        # B's working tree now equals origin (its own pull discarded), and it did not retry
        assert sh("git status --porcelain", cwd=b).strip() == "", sh("git status --porcelain", cwd=b)
        assert sh("git rev-parse HEAD", cwd=b) == sh(f"git --git-dir={origin} rev-parse main")


def scenario_c():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t); origin, a, b = setup(tmp)
        bot = tmp / "bot"; sh(f"git clone -q {origin} {bot}")
        during = (f"cd {bot} && echo x > data/other.json && git add -A && "
                  f"git -c user.name=bot -c user.email=b@b commit -q -m 'unrelated bot commit' && git push -q origin HEAD:main")
        o, out = run_clone(a, tmp, WHEN, during=during)
        assert o == "written", out
        log = origin_log(origin)
        assert log[0].startswith("🧾 options vintage") and "unrelated bot commit" in log[1], log


def scenario_d():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t); origin, a, b = setup(tmp)
        o, out = run_clone(a, tmp, "2026-10-06T17:01")
        assert o == "outside_window", out
        assert not (a / "data/options/vintages" / SESSION).exists()
        assert not [m for m in origin_log(origin) if m.startswith("🧾")]


if __name__ == "__main__":
    for n, f in (("A second run after a push exits already_written, pulls nothing", scenario_a),
                 ("B race: one vintage, one push, the loser discards and does not retry", scenario_b),
                 ("C an unrelated bot commit is rebased past, the vintage is pushed", scenario_c),
                 ("D outside the window nothing is written", scenario_d)):
        check(n, f)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
