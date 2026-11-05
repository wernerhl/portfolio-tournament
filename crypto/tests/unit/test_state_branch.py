"""scripts/state.sh (MarketMonitoring, 2026-11-05): crypto's generated files round-trip through the
orphan `crypto-state` branch as ONE parentless commit per save, a lease stops a stale writer, the
write set is enforced, and collector raw files are merged without overwriting. Local bare origin."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("git")), reason="needs bash, git")
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "STATE_PY": "python3",
}


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, env=ENV, check=True, capture_output=True, text=True).stdout


def _clone(tmp: Path, origin: Path, name: str) -> Path:
    repo = tmp / name
    _git(tmp, "clone", "-q", str(origin), str(repo))
    return repo


def _setup(tmp: Path) -> tuple[Path, Path]:
    origin = tmp / "origin.git"
    _git(tmp, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp / "seed"
    _git(tmp, "clone", "-q", str(origin), str(repo))
    (repo / "crypto" / "scripts").mkdir(parents=True)
    (repo / "crypto" / "config").mkdir()
    shutil.copy(ROOT / "scripts" / "state.sh", repo / "crypto" / "scripts" / "state.sh")
    shutil.copy(ROOT / "scripts" / "check_write_set.py", repo / "crypto" / "scripts" / "check_write_set.py")
    shutil.copy(ROOT / "config" / "job_writes.yaml", repo / "crypto" / "config" / "job_writes.yaml")
    shutil.copy(ROOT / ".gitignore", repo / "crypto" / ".gitignore")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "code")
    _git(repo, "push", "-q", "origin", "HEAD:main")
    return origin, repo


def _state(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "crypto/scripts/state.sh", *args], cwd=repo, env=ENV, capture_output=True, text=True
    )


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / "crypto" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_round_trip_one_parentless_commit_and_main_untouched(tmp_path):
    origin, a = _setup(tmp_path)
    assert _state(a, "restore").returncode == 0  # no branch yet: starts empty
    _write(a, "data/processed/prices_daily.parquet", "v1")
    _write(a, "site/data/daily.json", "{}")
    r = _state(a, "save", "daily")
    assert r.returncode == 0, r.stderr + r.stdout
    head = _git(origin, "rev-parse", "crypto-state").strip()
    assert _git(origin, "log", "--format=%P", "-1", head).strip() == ""  # parentless
    assert _git(a, "status", "--porcelain").strip() == ""  # generated files never staged on main
    # a second clone restores the same files
    b = _clone(tmp_path, origin, "b")
    assert _state(b, "restore").returncode == 0
    assert (b / "crypto/data/processed/prices_daily.parquet").read_text() == "v1"
    # and its save replaces the branch with one new parentless commit
    _write(b, "data/processed/prices_daily.parquet", "v2")
    assert _state(b, "save", "daily").returncode == 0
    new = _git(origin, "rev-parse", "crypto-state").strip()
    assert new != head and _git(origin, "rev-list", "--count", "crypto-state").strip() == "1"


def test_a_stale_writer_is_refused_by_the_lease(tmp_path):
    origin, a = _setup(tmp_path)
    _state(a, "restore")
    _write(a, "data/processed/prices_daily.parquet", "v1")
    assert _state(a, "save", "daily").returncode == 0
    b = _clone(tmp_path, origin, "b")
    c = _clone(tmp_path, origin, "c")
    _state(b, "restore")
    _state(c, "restore")
    _write(b, "data/processed/prices_daily.parquet", "from b")
    assert _state(b, "save", "daily").returncode == 0
    _write(c, "data/processed/prices_daily.parquet", "from c")
    r = _state(c, "save", "daily")
    assert r.returncode != 0  # c restored the snapshot b replaced: refused, b's write survives
    d = _clone(tmp_path, origin, "d")
    _state(d, "restore")
    assert (d / "crypto/data/processed/prices_daily.parquet").read_text() == "from b"


def test_the_write_set_is_enforced(tmp_path):
    _, a = _setup(tmp_path)
    _state(a, "restore")
    _write(a, "data/processed/prices_daily.parquet", "daily-owned")  # not an hourly table
    r = _state(a, "save", "hourly")
    assert r.returncode != 0 and "outside its write set" in r.stderr


def test_unchanged_snapshot_is_not_pushed(tmp_path):
    origin, a = _setup(tmp_path)
    _state(a, "restore")
    _write(a, "data/processed/prices_daily.parquet", "v1")
    _state(a, "save", "daily")
    before = _git(origin, "rev-parse", "crypto-state").strip()
    r = _state(a, "save", "daily")
    assert r.returncode == 0 and "no changes" in r.stdout
    assert _git(origin, "rev-parse", "crypto-state").strip() == before


def test_collector_raw_is_merged_without_overwriting(tmp_path):
    origin, a = _setup(tmp_path)
    _state(a, "restore")
    _write(a, "data/raw/2026/11/05/bybit_ws_0100.json.gz", "state copy")
    assert _state(a, "save", "hourly").returncode == 0
    col = _clone(tmp_path, origin, "collector")
    _git(col, "checkout", "-q", "--orphan", "crypto-collector")
    _git(col, "rm", "-rqf", "--cached", ".")
    for rel, text in (("2026/11/05/bybit_ws_0100.json.gz", "collector copy"), ("2026/11/05/binance_ws_0200.json.gz", "new")):
        p = col / "crypto/data/raw" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    _git(col, "add", "-f", "crypto/data/raw")
    _git(col, "commit", "-qm", "collector raw")
    _git(col, "push", "-q", "origin", "crypto-collector")
    b = _clone(tmp_path, origin, "b")
    r = _state(b, "restore")
    assert r.returncode == 0 and "collector raw merged (1 new files)" in r.stdout, r.stdout
    raw = b / "crypto/data/raw/2026/11/05"
    assert (raw / "bybit_ws_0100.json.gz").read_text() == "state copy"
    assert (raw / "binance_ws_0200.json.gz").read_text() == "new"
