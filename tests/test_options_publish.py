#!/usr/bin/env python3
"""
test_options_publish.py — the options vintage reaches origin when the first push is rejected and git has no
identity (fourth follow-up of 8 October 2026, J3).

The 6-, 7- and 8-October chains were pulled inside the window and lost at the push: another bot had committed in
the meantime, the push was rejected, and the rebase that replays the vintage commit failed for want of a committer
identity (the commit carried one through -c; the rebase did not). This test builds that situation locally:

  * a bare repository is `origin`; the publishing clone is `work`; a second clone pushes a commit to `origin` so
    that `work`'s first push is rejected;
  * HOME and GIT_CONFIG_GLOBAL point at an empty temporary folder, GIT_AUTHOR_*/GIT_COMMITTER_*/EMAIL are unset,
    and user.useConfigOnly is set so that git cannot invent an identity from the machine's user name (a GitHub
    runner cannot either; a developer's Mac can, which would hide the defect);
  * scripts/options/snapshot_chains.publish() runs against `work`.

The test passes when the vintage's _meta.json is on origin's main after publish() returns "written". On the code
before 172aa60 it fails ("Committer identity unknown"); on the current code it passes. Run it before every commit
that touches scripts/options/.

    python tests/test_options_publish.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts" / "options"))
sys.path.insert(0, str(REPO / "scripts"))


def run(args, cwd, env=None, check=True):
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, env=env)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()[:300]}")
    return r


def test_vintage_reaches_origin_without_a_git_identity():
    import snapshot_chains as sc
    oc = sc.oc
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ident = ["-c", "user.name=seed", "-c", "user.email=seed@test"]
        origin = td / "origin.git"; run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], td)
        work = td / "work"; run(["git", "clone", "-q", str(origin), str(work)], td)
        (work / "README").write_text("base\n"); run(["git", "add", "README"], work)
        run(["git", *ident, "commit", "-q", "-m", "base"], work); run(["git", "push", "-q", "origin", "HEAD:main"], work)
        # another bot moves origin/main after our clone: the first push will be rejected
        other = td / "other"; run(["git", "clone", "-q", str(origin), str(other)], td)
        (other / "bot.txt").write_text("another bot\n"); run(["git", "add", "bot.txt"], other)
        run(["git", *ident, "commit", "-q", "-m", "another bot"], other); run(["git", "push", "-q", "origin", "HEAD:main"], other)
        # the vintage, moved into place as snapshot_chains does before publish()
        session = "2026-10-08"
        vint = work / "data" / "options" / "vintages" / session; vint.mkdir(parents=True)
        (vint / "_meta.json").write_text('{"session": "2026-10-08", "test": true}\n'); (vint / "SPY.parquet").write_bytes(b"\x00test")
        # no identity anywhere: empty HOME and global config, no env identity, no invention from the OS user
        home = td / "home"; home.mkdir()
        saved = {k: os.environ.get(k) for k in ("HOME", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0")}
        try:
            os.environ["HOME"] = str(home); os.environ["GIT_CONFIG_GLOBAL"] = str(home / "gitconfig"); os.environ["GIT_CONFIG_SYSTEM"] = os.devnull
            for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
                os.environ.pop(k, None)
            os.environ["GIT_CONFIG_COUNT"] = "1"; os.environ["GIT_CONFIG_KEY_0"] = "user.useConfigOnly"; os.environ["GIT_CONFIG_VALUE_0"] = "true"
            saved_repo = oc.REPO; oc.REPO = work
            try:
                outcome = sc.publish(session, "15:50")
            finally:
                oc.REPO = saved_repo
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        on_origin = run(["git", "cat-file", "-e", f"main:data/options/vintages/{session}/_meta.json"], origin, check=False).returncode == 0
        log = run(["git", "log", "--oneline", "main"], origin).stdout
        why = ""
        if outcome != "written":
            # what git says about the rebase in this environment (the code before 172aa60 logged an empty status instead)
            env = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL=str(home / "gitconfig"), GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="user.useConfigOnly", GIT_CONFIG_VALUE_0="true")
            for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
                env.pop(k, None)
            run(["git", "rebase", "--abort"], work, env=env, check=False)
            r = run(["git", "rebase", "origin/main"], work, env=env, check=False)
            lines = [ln.strip() for ln in (r.stderr + "\n" + r.stdout).splitlines() if ln.strip() and not ln.startswith("Rebasing")]
            why = " | ".join(lines)[:300] if lines else "(no message)"
            run(["git", "rebase", "--abort"], work, env=env, check=False)
        assert outcome == "written" and on_origin, f"publish() returned {outcome!r}; vintage on origin: {on_origin}; the rebase in this environment says: {why}; origin log:\n{log}"
        assert "another bot" in log and "options vintage" in log, log


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except Exception:
                print(f"FAIL {name}\n{traceback.format_exc()}"); fails += 1
    n = sum(1 for k, v in globals().items() if k.startswith("test_") and callable(v))
    print(f"\n{n - fails} passed, {fails} failed")
    sys.exit(1 if fails else 0)
