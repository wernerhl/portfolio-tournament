#!/usr/bin/env python3
"""
tests/test_errata.py — the errata file is append-only against its previous commit (second follow-up of 7 October
2026, G6): on a scratch git repository, an entry edited together with its hash and a deleted entry are findings; an
appended entry is not; the per-entry hash check still catches an edit without its hash.

    .venv/bin/python tests/test_errata.py
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import errata   # noqa: E402

RESULTS = []


def run(fn):
    try:
        fn(); RESULTS.append((fn.__name__, True)); print(f"PASS {fn.__name__}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False)); print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); traceback.print_exc()


def scratch_repo() -> tuple[Path, list[dict]]:
    td = Path(tempfile.mkdtemp())
    (td / "data").mkdir()
    e1 = errata.make("data/tournament.json", "5_werner", "2026-10-06", "nav", 191067.57, 239269.16, "r", None, "2026-10-07", seq=1, existing=[])
    e2 = errata.make("data/tournament.json", "5_werner", "2026-10-06", "equity", 42750.6, 90952.19, "r", None, "2026-10-07", seq=2, existing=[e1])
    (td / "data" / "errata.json").write_text(json.dumps({"entries": [e1, e2]}, indent=1))
    for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"]):
        subprocess.run(cmd, cwd=td, check=True, capture_output=True)
    return td, [e1, e2]


def write(td: Path, entries: list[dict]):
    (td / "data" / "errata.json").write_text(json.dumps({"entries": entries}, indent=1))


def test_unchanged_and_appended_pass():
    td, es = scratch_repo()
    assert errata.compare_with_previous(td) == []
    e3 = errata.make("data/tournament.json", "5_werner", "2026-10-06", "cash", 1.0, 2.0, "r", None, "2026-10-08", seq=3, existing=es)
    write(td, es + [e3])
    assert errata.compare_with_previous(td) == []


def test_edited_with_its_hash_is_a_finding():
    td, es = scratch_repo()
    e1 = dict(es[0]); e1["corrected"] = 999.0; e1["sha256"] = errata._sha(e1)      # the hash check alone would pass
    write(td, [e1, es[1]])
    p = errata.compare_with_previous(td)
    assert len(p) == 1 and "edited" in p[0] and e1["id"] in p[0], p


def test_deleted_entry_is_a_finding():
    td, es = scratch_repo()
    write(td, [es[1]])
    p = errata.compare_with_previous(td)
    assert len(p) == 1 and "deleted" in p[0] and es[0]["id"] in p[0], p


def test_hash_check_catches_an_edit_without_its_hash():
    td, es = scratch_repo()
    e1 = dict(es[0]); e1["corrected"] = 999.0
    write(td, [e1, es[1]])
    import importlib
    saved = errata.ERRATA; errata.ERRATA = td / "data" / "errata.json"
    try:
        p = errata.verify()
    finally:
        errata.ERRATA = saved
    assert len(p) == 1 and "does not match its sha256" in p[0], p


if __name__ == "__main__":
    for fn in [test_unchanged_and_appended_pass, test_edited_with_its_hash_is_a_finding, test_deleted_entry_is_a_finding, test_hash_check_catches_an_edit_without_its_hash]:
        run(fn)
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)
