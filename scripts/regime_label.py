#!/usr/bin/env python3
"""regime_label.py — the ONE regime-label function, with the hysteresis corridor.

Bands keep their centres (0.30 / 0.50 / 0.70) and transitions need a ±0.02 corridor: a higher
band is entered at edge + 0.02 and left at edge − 0.02. compute_regime_v2 has shaped its own
label column this way since the June audit; compute_nav re-derived the tournament rows' label
from R with plain edges, so the served label entered ELEVATED at 0.3173, 0.3198 and 0.3022 and
changed 17 times in four months (tournament audit of 30 September 2026, finding 2.3). Every
consumer now calls this module: the tournament rows, the daily brief, the action ledger, the
signal alerts' resolution, the seeding of operator trades. The R values and the published
vintage are untouched — this shapes only the label.

    label_with_corridor(R, prev_label)   the label for R given the previous session's label
    corridor_series(values)              labels for a whole series, sequentially
    plain_band(R)                        the band by plain edges (first observation only)
"""
from __future__ import annotations

LEVELS = ["LOW RISK", "ELEVATED", "HIGH RISK", "CRISIS"]
EDGES = [0.30, 0.50, 0.70]
H = 0.02
ENTRY_EDGES = [e + H for e in EDGES]     # 0.32 / 0.52 / 0.72
EXIT_EDGES = [e - H for e in EDGES]      # 0.28 / 0.48 / 0.68


def plain_band(R: float) -> str:
    return LEVELS[sum(1 for e in EDGES if float(R) >= e)]


def label_with_corridor(R, prev_label: str | None = None) -> str:
    """The corridor label for R. Without a previous band (first observation) the plain band."""
    if R is None:
        return "UNKNOWN"
    R = float(R)
    if prev_label not in LEVELS:
        return plain_band(R)
    level = LEVELS.index(prev_label)
    while level < 3 and R >= EDGES[level] + H:
        level += 1
    while level > 0 and R < EDGES[level - 1] - H:
        level -= 1
    return LEVELS[level]


def corridor_series(values, first_label: str | None = None) -> list[str]:
    out, prev = [], first_label
    for v in values:
        lab = label_with_corridor(v, prev)
        out.append(lab)
        if lab in LEVELS:
            prev = lab
    return out


if __name__ == "__main__":
    import sys
    vals = [float(x) for x in sys.argv[1:]]
    print(corridor_series(vals))
