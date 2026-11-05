"""scripts/rotate_raw.sh (MarketMonitoring, 2026-11-05): old raw files go to size-capped tar parts
uploaded as release assets; nothing is rewritten; a failed upload leaves every raw file in place.
A fake `gh` on PATH records the calls and stores the assets in a temp directory."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "rotate_raw.sh"
pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("tar")), reason="needs bash, tar")

FAKE_GH = """#!/usr/bin/env bash
# fake gh: release view/create/upload against $FAKE_GH_DIR/<tag>/
set -e
store="$FAKE_GH_DIR"; echo "$*" >> "$store/calls.log"
[ "${FAKE_GH_FAIL:-}" = "$2" ] && { echo "HTTP 502" >&2; exit 1; }
case "$1 $2" in
  "release view") [ -d "$store/$3" ] ;;
  "release create") mkdir -p "$store/$3" ;;
  "release upload") [ -d "$store/$3" ] || exit 1; cp "$4" "$store/$3/" ;;
  *) exit 1 ;;
esac
"""


def _env(tmp: Path, **extra: str) -> dict:
    bin_ = tmp / "bin"
    bin_.mkdir(exist_ok=True)
    gh = bin_ / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    store = tmp / "releases"
    store.mkdir(exist_ok=True)
    return {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_GH_DIR": str(store), **extra}


def _raw(work: Path, day: datetime, name: str, size: int) -> Path:
    """An hourly raw file unless the name ends in _0000 (the daily file, kept 90 days)."""
    p = work / "data" / "raw" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(os.urandom(size))  # incompressible, like the gzip payloads
    return p


def _run(work: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], cwd=work, env=env, capture_output=True, text=True)


def test_parts_are_capped_uploaded_and_hold_every_file(tmp_path):
    work = tmp_path / "crypto"
    old = datetime.now(UTC) - timedelta(days=40)  # hourly files older than 10 days rotate
    files = [_raw(work, old + timedelta(days=i % 3), f"src_x_{i + 1:04d}.json.gz", 300_000) for i in range(12)]
    keep = _raw(work, datetime.now(UTC) - timedelta(days=1), "src_x_0101.json.gz", 1000)  # too recent
    daily = _raw(work, old, "src_x_0000.json.gz", 1000)  # a daily file inside its 90-day window
    env = _env(tmp_path, MAX_PART_MB="1")
    r = _run(work, env)
    assert r.returncode == 0, r.stderr + r.stdout
    assert all(not f.exists() for f in files) and keep.exists() and daily.exists()
    rel = tmp_path / "releases" / f"crypto-raw-{old:%Y-%m}"
    tars = sorted(rel.glob("rot-*.tar"))
    assert len(tars) >= 4, tars  # 12 x 0.3 MB under a 1 MB cap: several parts
    assert all(t.stat().st_size <= 1024 * 1024 for t in tars)
    names = []
    for t in tars:
        with tarfile.open(t) as tf:
            names += [Path(m.name).name for m in tf.getmembers() if m.isfile()]
    assert sorted(names) == sorted(f.name for f in files)


def test_an_existing_release_is_reused_not_recreated(tmp_path):
    work = tmp_path / "crypto"
    old = datetime.now(UTC) - timedelta(days=40)
    env = _env(tmp_path)
    (tmp_path / "releases" / f"crypto-raw-{old:%Y-%m}").mkdir(parents=True)
    _raw(work, old, "a_x_0001.json.gz", 10_000)
    assert _run(work, env).returncode == 0
    calls = (tmp_path / "releases" / "calls.log").read_text()
    assert "release create" not in calls and "release upload" in calls


def test_a_failed_upload_restores_every_raw_file(tmp_path):
    work = tmp_path / "crypto"
    old = datetime.now(UTC) - timedelta(days=40)
    files = [_raw(work, old, f"b_x_{i + 1:04d}.json.gz", 5_000) for i in range(5)]
    r = _run(work, _env(tmp_path, FAKE_GH_FAIL="upload"))
    assert r.returncode != 0
    assert all(f.exists() for f in files), "moved files must be put back when the upload fails"
    assert "restored" in r.stderr


def test_dry_run_builds_parts_without_uploading(tmp_path):
    work = tmp_path / "crypto"
    old = datetime.now(UTC) - timedelta(days=40)
    _raw(work, old, "c_x_0001.json.gz", 10_000)
    outdir = tmp_path / "out"
    r = _run(work, _env(tmp_path, ROTATE_UPLOAD="0", ROTATE_OUT=str(outdir)))
    assert r.returncode == 0, r.stderr
    assert list(outdir.glob("*/rot-*.tar"))
    assert not (tmp_path / "releases" / "calls.log").exists()
