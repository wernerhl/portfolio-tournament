#!/usr/bin/env python3
"""
ingest_inbox.py — the operator's one-shot for inbox/ (order of 30 Sept 2026, C4): runs the three
ingestion jobs in order, each as a subprocess with the venv interpreter, then archives the
processed exports.

    1. ingest_brokerage.py --write             positions + transactions → data/holdings.json + holdings_export.json
    2. seed_actions_from_transactions.py --write  BUY/SELL transactions → data/actions.jsonl (idempotent)
    3. ingest_realized_gains.py --write        realized gain/loss export → data/realized_gains.json

Usage
    ingest_inbox.py [--inbox inbox] [--data-dir data] [--scratch scratch] [--dry-run]
                    [--no-signals] [--include-reinvest] [--actions FILE] [--vintage FILE]

  * Every CSV in inbox/ is classified by HEADER SNIFFING (never by name): realized gain/loss
    export (a closing/sale date column), positions export, transactions export, or unrecognised.
    The jobs are then called with explicit file paths — ingest_brokerage.py would otherwise read a
    realized-gains export as a second positions file and refuse the inbox as ambiguous.
  * The absence of any one file type is tolerated: the step that needs it is skipped and the
    report says why.  Two files of the same kind are ambiguous: that step is skipped, exit 1.
  * --dry-run runs every job without --write and moves nothing.  (The jobs still write their
    best guess under scratch/, which is git-ignored.)
  * After a write run the CSVs whose job exited 0 are moved to inbox/archive/<ET timestamp>/
    (git-ignore that directory: `inbox/archive/`).  A file whose job failed — exit 2, a required
    column unmapped — stays in the inbox for the operator to fix the synonym table and rerun.
  * The final checklist says which served files changed (sha256 before vs after).
  * Exit code: 0 when every step that ran exited 0 and nothing was ambiguous; otherwise the
    highest exit code of the steps that ran (2 = a column unmapped somewhere), or 1.
"""
from __future__ import annotations

import argparse
import hashlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
INBOX = REPO / "inbox"
SCRATCH = REPO / "scratch"
VENV_PY = REPO / ".venv" / "bin" / "python"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable

sys.path.insert(0, str(HERE))
import ingest_brokerage as ib  # noqa: E402
import ingest_realized_gains as rg  # noqa: E402
from trading_calendar import now_et  # noqa: E402

KINDS = ("positions", "transactions", "realized_gains")
SERVED = ("holdings.json", "holdings_export.json", "actions.jsonl", "realized_gains.json")


# ─── helpers ─────────────────────────────────────────────────────────────────────────────
def classify(path: Path) -> str:
    """realized_gains | positions | transactions | unrecognised | unreadable — by header sniffing."""
    try:
        rows = ib.read_csv_rows(path.read_bytes())
    except Exception:
        return "unreadable"
    if rg.sniff_header(rows) is not None:
        return "realized_gains"
    hit = ib.sniff_header(rows)
    return hit[1] if hit else "unrecognised"


def digest(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def line_count(p: Path) -> int | None:
    if not p.exists():
        return None
    return sum(1 for line in p.read_text().splitlines() if line.strip())


def newest_ingest_dir(scratch: Path) -> Path | None:
    dirs = [d for d in scratch.glob("ingest_*") if d.is_dir()] if scratch.exists() else []
    return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None


def run_step(argv: list[str]) -> int:
    print("   $ " + " ".join(shlex.quote(a) for a in argv))
    cp = subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO))
    for line in (cp.stdout + cp.stderr).splitlines():
        print("   " + line)
    print(f"   → exit {cp.returncode}")
    return cp.returncode


class Step:
    def __init__(self, name: str):
        self.name, self.status, self.rc, self.detail = name, "skipped", None, ""

    def skip(self, why: str) -> None:
        self.status, self.detail = "skipped", why
        print(f"   skipped — {why}")

    def ran(self, rc: int) -> None:
        self.status, self.rc = ("ran" if rc == 0 else "FAILED"), rc


# ─── main ────────────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("Usage")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inbox", default=str(INBOX), help="directory holding the exported CSVs (default: repo inbox/)")
    ap.add_argument("--data-dir", default=str(DATA), help="served data directory (default: repo data/)")
    ap.add_argument("--scratch", default=str(SCRATCH), help="scratch root for the jobs' best-guess output (default: repo scratch/)")
    ap.add_argument("--dry-run", action="store_true", help="run every job without --write; move nothing")
    ap.add_argument("--no-signals", action="store_true", help="passed to the seeding job: skip the git lookup of ticker_signals.json")
    ap.add_argument("--include-reinvest", action="store_true", help="passed to the seeding job: seed dividend reinvestments as buys")
    ap.add_argument("--actions", help="action log for the seeding job (default: <data-dir>/actions.jsonl)")
    ap.add_argument("--vintage", help="published regime vintage CSV for the seeding job (default: <data-dir>/regime_daily_published.csv)")
    args = ap.parse_args(argv)

    inbox, data_dir, scratch = Path(args.inbox), Path(args.data_dir), Path(args.scratch)
    actions = Path(args.actions) if args.actions else data_dir / "actions.jsonl"
    vintage = Path(args.vintage) if args.vintage else data_dir / "regime_daily_published.csv"
    write_flag = [] if args.dry_run else ["--write"]
    print(f"ingest_inbox: {'DRY RUN' if args.dry_run else 'WRITE'} · inbox {inbox} · data {data_dir} · scratch {scratch}")
    print(f"interpreter: {PY}")
    if not inbox.is_dir():
        print(f"error: inbox not found: {inbox}", file=sys.stderr)
        return 1

    csvs = sorted((p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() == ".csv"), key=lambda p: p.name)
    kinds = {p: classify(p) for p in csvs}
    print(f"\ninbox: {len(csvs)} CSV file(s) — classified by header sniffing, never by name")
    for p, k in kinds.items():
        print(f"  {p.name:44s} → {k}")
    if not csvs:
        print("  nothing to do: no .csv in the inbox", file=sys.stderr)
        return 1
    by_kind: dict[str, list[Path]] = {}
    for p, k in kinds.items():
        by_kind.setdefault(k, []).append(p)
    ambiguous = [k for k in KINDS if len(by_kind.get(k, [])) > 1]
    for k in ambiguous:
        print(f"  ! ambiguous: more than one {k} CSV: " + ", ".join(p.name for p in by_kind[k]))
    one = {k: (by_kind[k][0] if len(by_kind.get(k, [])) == 1 else None) for k in KINDS}
    pos, txn, gains = one["positions"], one["transactions"], one["realized_gains"]

    before = {n: digest(data_dir / n) for n in SERVED}
    before["actions.jsonl"] = digest(actions)
    actions_lines_before = line_count(actions)
    processed: list[Path] = []
    steps: list[Step] = []

    # ── 1. positions + transactions → holdings.json + holdings_export.json ──
    s1 = Step("ingest_brokerage.py")
    steps.append(s1)
    print(f"\n── step 1/3: ingest_brokerage.py {' '.join(write_flag)} (positions + transactions → holdings.json + holdings_export.json)")
    if "positions" in ambiguous or "transactions" in ambiguous:
        s1.skip("ambiguous inbox (more than one positions or transactions CSV)")
    elif pos is None:
        s1.skip("no positions CSV in the inbox" + (" (a transactions CSV is present, but ingest_brokerage.py needs the positions CSV too)" if txn else ""))
    else:
        cmd = [PY, str(HERE / "ingest_brokerage.py"), "--positions", str(pos), "--scratch", str(scratch), "--data-dir", str(data_dir)]
        if txn is not None:
            cmd += ["--transactions", str(txn)]
        s1.ran(run_step(cmd + write_flag))
        if s1.rc == 0:
            processed += [pos] + ([txn] if txn else [])

    # ── 2. BUY/SELL transactions → actions.jsonl ──
    s2 = Step("seed_actions_from_transactions.py")
    steps.append(s2)
    print(f"\n── step 2/3: seed_actions_from_transactions.py {' '.join(write_flag)} (BUY/SELL transactions → actions.jsonl)")
    if s1.status != "ran":
        s2.skip("ingest_brokerage.py did not complete (the seeding job reads its parsed transactions)")
    elif txn is None:
        s2.skip("no transactions CSV in the inbox")
    elif not vintage.exists():
        s2.skip(f"published regime vintage not found: {vintage} (pass --vintage)")
    else:
        nd = newest_ingest_dir(scratch)
        if nd is None:
            s2.skip(f"no scratch/ingest_*/ under {scratch} after step 1")
        else:
            cmd = [PY, str(HERE / "seed_actions_from_transactions.py"), "--scratch", str(nd), "--actions", str(actions),
                   "--vintage", str(vintage), "--repo", str(REPO)]
            if args.no_signals:
                cmd.append("--no-signals")
            if args.include_reinvest:
                cmd.append("--include-reinvest")
            s2.ran(run_step(cmd + write_flag))

    # ── 3. realized gain/loss export → realized_gains.json ──
    s3 = Step("ingest_realized_gains.py")
    steps.append(s3)
    print(f"\n── step 3/3: ingest_realized_gains.py {' '.join(write_flag)} (realized gain/loss export → realized_gains.json)")
    if "realized_gains" in ambiguous:
        s3.skip("ambiguous inbox (more than one realized gain/loss CSV)")
    elif gains is None:
        s3.skip("no realized gain/loss CSV in the inbox")
    else:
        cmd = [PY, str(HERE / "ingest_realized_gains.py"), "--file", str(gains), "--scratch", str(scratch), "--data-dir", str(data_dir)]
        s3.ran(run_step(cmd + write_flag))
        if s3.rc == 0:
            processed.append(gains)

    # ── archive ──
    print("\n── archive")
    if args.dry_run:
        print("   dry run: nothing moved — the files stay in the inbox")
    elif not processed:
        print("   nothing to archive (no step completed)")
    else:
        dest = inbox / "archive" / now_et().strftime("%Y%m%dT%H%M%S")
        n = 1
        while dest.exists():
            n += 1
            dest = dest.with_name(f"{dest.name.split('_')[0]}_{n}")
        dest.mkdir(parents=True)
        for p in processed:
            shutil.move(str(p), str(dest / p.name))
            print(f"   moved {p.name} → {dest}/")
    left = [p for p in csvs if p not in processed or args.dry_run]
    if left and not args.dry_run:
        print("   left in the inbox: " + ", ".join(f"{p.name} ({kinds[p]})" for p in left))

    # ── checklist ──
    print(f"\n── served files checklist ({data_dir})")
    for n in SERVED:
        p = actions if n == "actions.jsonl" else data_dir / n
        after = digest(p)
        if before[n] is None and after is None:
            status = "absent"
        elif before[n] is None:
            status = "created"
        elif before[n] == after:
            status = "unchanged"
        else:
            status = "changed"
        extra = ""
        if n == "actions.jsonl" and after is not None:
            extra = f" ({line_count(p)} lines, +{(line_count(p) or 0) - (actions_lines_before or 0)})"
        print(f"   [{status:9s}] {p}{extra}")

    ran = [s for s in steps if s.status == "ran"]
    failed = [s for s in steps if s.status == "FAILED"]
    skipped = [s for s in steps if s.status == "skipped"]
    print(f"\nsteps: ran {len(ran)}, skipped {len(skipped)}, failed {len(failed)}"
          + (" · dry run — nothing served written, nothing moved" if args.dry_run else ""))
    for s in steps:
        tail = f"exit {s.rc}" if s.rc is not None else s.detail
        print(f"  {s.name:36s} {s.status:8s} {tail}")
    if ambiguous:
        return 1
    return max([s.rc for s in steps if s.rc is not None] or [0])


if __name__ == "__main__":
    sys.exit(main())
