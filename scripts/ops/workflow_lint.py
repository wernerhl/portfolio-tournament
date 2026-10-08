#!/usr/bin/env python3
"""
workflow_lint.py — lint every workflow file with actionlint (github.com/rhysd/actionlint, MIT licence), pinned.

A YAML parser accepts a step that carries both `run:` and `with:`; GitHub rejects the file and every push then
produces a failed run with no jobs (the F3 break of 7 October 2026, repaired in [G9]). actionlint reports it, and
the other things GitHub rejects: an `inputs.trigger` expression in a workflow that declares no `trigger` input,
an unknown key, a bad needs reference.

The pinned release is downloaded once per machine into a cache directory outside the repository, its sha256
checked against the release's published checksums (recorded below), and run with shellcheck and pyflakes turned
off (the script bodies are checked elsewhere). Used by tests/test_workflows.py and by the referee
(scripts/audit_nightly.py, HIGH ops:workflow_lint).

Usage:  python scripts/ops/workflow_lint.py [--repo DIR]      exit 0 clean, 1 errors, 2 the linter could not run
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSION = "1.7.12"
BASE = f"https://github.com/rhysd/actionlint/releases/download/v{VERSION}/"
# sha256 of the release archives, from actionlint_1.7.12_checksums.txt published with the release
ASSETS = {
    ("Darwin", "arm64"):  ("actionlint_1.7.12_darwin_arm64.tar.gz", "aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f"),
    ("Linux", "x86_64"):  ("actionlint_1.7.12_linux_amd64.tar.gz",  "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"),
}
CACHE = Path(os.environ.get("ACTIONLINT_CACHE") or (Path.home() / ".cache" / "actionlint"))
REPO = Path(__file__).resolve().parents[2]


class LinterUnavailable(RuntimeError):
    pass


def binary() -> Path:
    key = (platform.system(), platform.machine())
    if key not in ASSETS:
        raise LinterUnavailable(f"no pinned actionlint build for {key}")
    name, sha = ASSETS[key]
    CACHE.mkdir(parents=True, exist_ok=True)
    exe = CACHE / f"actionlint-{VERSION}"
    if exe.exists():
        return exe
    archive = CACHE / name
    if not archive.exists():
        try:
            urllib.request.urlretrieve(BASE + name, archive)
        except Exception as e:  # noqa: BLE001
            raise LinterUnavailable(f"download failed: {type(e).__name__}: {e}") from e
    got = hashlib.sha256(archive.read_bytes()).hexdigest()
    if got != sha:
        archive.unlink(missing_ok=True)
        raise LinterUnavailable(f"sha256 mismatch for {name}: {got} != {sha}")
    with tarfile.open(archive) as tf:
        member = next(m for m in tf.getmembers() if m.name == "actionlint")
        member.name = exe.name
        try:
            tf.extract(member, CACHE, filter="data")
        except TypeError:                      # Python before the filter argument
            tf.extract(member, CACHE)
    exe.chmod(0o755)
    return exe


def lint(repo: Path | str = REPO) -> tuple[int, str]:
    """(error count, the linter's output) for .github/workflows/*.yml; raises LinterUnavailable."""
    repo = Path(repo)
    files = sorted((repo / ".github" / "workflows").glob("*.yml")) + sorted((repo / ".github" / "workflows").glob("*.yaml"))
    if not files:
        return 0, ""
    exe = binary()
    # paths relative to the repository: the output's file names then start with .github/workflows/
    r = subprocess.run([str(exe), "-shellcheck=", "-pyflakes=", "-no-color"] + [str(f.relative_to(repo)) for f in files], capture_output=True, text=True, cwd=str(repo))
    if r.returncode not in (0, 1):
        raise LinterUnavailable(f"actionlint exit {r.returncode}: {r.stderr[:300]}")
    out = r.stdout.strip()
    n = sum(1 for ln in out.splitlines() if ln.startswith(".github/workflows/") and ":" in ln and not ln.startswith(" "))
    return n, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args()
    try:
        n, out = lint(Path(a.repo))
    except LinterUnavailable as e:
        print(f"[workflow_lint] linter unavailable: {e}")
        return 2
    print(out if out else f"[workflow_lint] actionlint {VERSION}: no errors")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
