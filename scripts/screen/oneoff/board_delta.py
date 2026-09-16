# Relocated 2026-09-16 (order 6.1) from portfolio-screener/scripts/oneoff/board_delta.py — paths changed (one repository: served data data/screen/), nothing else.
"""[6] One-off board delta attribution — correction batch, 2026-07-29.

Attributes tomorrow-morning's board movement to its four simultaneous causes
via SEQUENTIAL counterfactuals (order fixed by the written instruction):

    stage 0  pre-state board  = scored_universe.csv at PRE_COMMIT
             (last commit before the 2026-07-29 batch; vintage #1 is
             post-change and cannot serve)
    stage 1  data refresh only        = fund + technical_precap
                                        + visibility_legacy + no corr penalty
    stage 2  + correlation penalties  = stage 1 + corr_penalty
    stage 3  + broken-base caps       = fund + technical(capped)
                                        + visibility_legacy + corr_penalty
    stage 4  + visibility compression = fund + technical + visibility(registry)
                                        + corr_penalty  == published composite

Per-name effects are successive rank differences over the union of the old
and new top-40. NOTE (path-dependence, per the order): sequential attribution
depends on this stage order; a different order would split joint effects
differently. Stage 1 also carries the [2] value-ladder corrections (the fcf
tail scores), which are inseparable from "refresh" without a fifth stage the
order declined. Runs one-off against the PUBLISHED post-state; not part of
the scheduled pipeline.

Usage:  python scripts/screen/oneoff/board_delta.py
Output: data/screen/reports/board_delta_2026-07-29.md
"""
import subprocess
import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent   # the tournament repository (order 6.1: one repo)
PRE_COMMIT = "b6e383e"          # last commit before the 2026-07-29 batch
# NOTE (order 6.1): PRE_COMMIT is a commit of the absorbed portfolio-screener
# repository (path data/scored_universe.csv in THAT history); the tournament
# repository does not carry it, so load_pre() needs a clone of that history.
OUT = ROOT / "data" / "screen" / "reports" / "board_delta_2026-07-29.md"


def load_pre() -> pd.DataFrame:
    raw = subprocess.check_output(
        ["git", "show", f"{PRE_COMMIT}:data/scored_universe.csv"], cwd=ROOT, text=True)
    df = pd.read_csv(StringIO(raw))
    df = df.sort_values("composite", ascending=False).reset_index(drop=True)
    df["rank0"] = df.index + 1
    return df.set_index("ticker")


def main() -> None:
    post = pd.read_csv(ROOT / "data" / "screen" / "scored_universe.csv")
    for col in ("technical_precap", "visibility_legacy"):
        if col not in post.columns:
            sys.exit(f"post-state CSV lacks {col} — run after tonight's publish")
    pre = load_pre()

    num = lambda s: pd.to_numeric(post[s], errors="coerce").fillna(0)
    pen = pd.to_numeric(post["corr_penalty"], errors="coerce").fillna(0)
    f, t_cap, t_pre = num("fundamental"), num("technical"), num("technical_precap")
    v_reg, v_leg = num("visibility"), num("visibility_legacy")

    stages = {
        1: (f + t_pre + v_leg).clip(0, 75),                    # refresh (+[2] ladder)
        2: (f + t_pre + v_leg + pen).clip(0, 75),              # + correlation
        3: (f + t_cap + v_leg + pen).clip(0, 75),              # + broken-base cap
        4: (f + t_cap + v_reg + pen).clip(0, 75),              # + visibility compression
    }
    # stage 4 must reproduce the published composite
    resid = (stages[4] - pd.to_numeric(post["composite"], errors="coerce")).abs().max()
    assert resid < 0.15, f"stage-4 does not reproduce published composite (max dev {resid})"

    ranks = {k: s.rank(ascending=False, method="min").astype(int) for k, s in stages.items()}
    post = post.assign(**{f"rank{k}": v for k, v in ranks.items()}).set_index("ticker")

    top_old = set(pre[pre["rank0"] <= 40].index)
    top_new = set(post[post["rank4"] <= 40].index)
    rows = []
    for tk in sorted(top_old | top_new):
        in_post = tk in post.index
        r0 = int(pre.loc[tk, "rank0"]) if tk in pre.index else None
        if not in_post:
            rows.append((tk, r0, None, None, None, None, None, "left universe"))
            continue
        r = [int(post.loc[tk, f"rank{k}"]) for k in (1, 2, 3, 4)]
        if r0 is None:
            rows.append((tk, None, r[3], None, r[1]-r[0], r[2]-r[1], r[3]-r[2], "new to universe"))
            continue
        eff = (r[0]-r0, r[1]-r[0], r[2]-r[1], r[3]-r[2])
        assert sum(eff) == r[3] - r0            # telescoping sum — exact
        rows.append((tk, r0, r[3], *eff, ""))

    lines = [
        "# Board delta — 2026-07-29 correction batch",
        "",
        f"Pre-state: `{PRE_COMMIT}:data/scored_universe.csv` (last commit before the batch). "
        "Post-state: tonight's published board.",
        "",
        "Effects are successive rank differences (positive = fell, negative = rose). "
        "Sequential attribution is path-dependent on the fixed stage order; stage 1 "
        "also carries the [2] fcf value-ladder corrections.",
        "",
        "| name | old rank | new rank | refresh | corr | bb-cap | vis-compress | note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    fmt = lambda x: "—" if x is None else f"{x:+d}"
    for tk, r0, r4, e1, e2, e3, e4, note in rows:
        lines.append(f"| {tk} | {r0 or '—'} | {r4 or '—'} | {fmt(e1)} | {fmt(e2)} | {fmt(e3)} | {fmt(e4)} | {note} |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(rows)} names, union of old/new top-40)")


if __name__ == "__main__":
    main()
