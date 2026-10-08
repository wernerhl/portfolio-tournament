"""
build_universe.py — ONE universe for both scoring views (order 6.2, 2026-09-16).

    "One universe: the union of the two universes plus every held name, built
     once nightly and consumed by both scoring views."

Inputs (all local, nothing is fetched):
    data/canonical/universe.txt          the tournament's canonical universe
    data/screen/universe_535.txt         the screen view's historical universe
                                         (copied from portfolio-screener, order 6.1)
    scripts/screen/config.json           "midcap_additions" — the screen view's supplement
    data/holdings.json                   the book — every held name is always a member

Outputs:
    data/universe.txt        sorted, one ticker per line (consumed by both views)
    data/universe_meta.json  cadence "on_change", as_of, sizes of each input, the
                             union size, and the one-sided names:
                               only_tournament         in the canonical universe only
                               only_screener_or_midcap in the screen universe ∪ midcaps only
                               held_added              held names in neither universe

Idempotent: the outputs are a pure function of the inputs; an unchanged union
leaves both files untouched (on_change semantics — as_of moves only when the
membership moves). Tickers are normalised the way the price columns are keyed
(upper-case, '.' → '-', e.g. BRK.B → BRK-B).

Usage:  python scripts/build_universe.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TOURNAMENT_UNIVERSE = DATA / "canonical" / "universe.txt"
SCREENER_UNIVERSE = DATA / "screen" / "universe_535.txt"
SCREEN_CONFIG = ROOT / "scripts" / "screen" / "config.json"
HOLDINGS = DATA / "holdings.json"

OUT_UNIVERSE = DATA / "universe.txt"
OUT_META = DATA / "universe_meta.json"


def norm(t: str) -> str:
    return str(t).strip().upper().replace(".", "-")


TICKER_CHANGES = DATA / "analyst" / "ticker_changes.csv"


def ticker_map() -> dict[str, str]:
    """G3 (second follow-up, 7-Oct-2026): old symbol -> current symbol (data/analyst/ticker_changes.csv, confirmed by SEC
    CIK). Applied to every input list; the old symbol is kept in universe_meta.json's former_tickers."""
    if not TICKER_CHANGES.exists():
        return {}
    import csv
    # H1 (third follow-up, 7-Oct-2026): a change whose old symbol is listed today under another company (Q: Qnity after
    # Quintiles) or that the membership build marked as not applying (a second share class) is not a rename of a
    # current name; the membership file's latest month-end says which symbols are listed today
    listed_today = set()
    mp = DATA / "analyst" / "sp500_membership_history.parquet"
    if mp.exists():
        try:
            import pandas as pd
            m = pd.read_parquet(mp, columns=["month_end", "ticker"])
            listed_today = set(m.loc[m["month_end"] == m["month_end"].max(), "ticker"].astype(str))
        except Exception:
            listed_today = set()
    out = {}
    with TICKER_CHANGES.open(newline="") as fh:
        for r in csv.DictReader(fh):
            o, n = norm(r.get("old") or ""), norm(r.get("new") or "")
            if not o or not n or str(r.get("applies", "True")).strip().lower() == "false" or o in listed_today:
                continue
            out[o] = n
    # chains (A -> B -> C) resolve to the last symbol
    for k in list(out):
        seen = {k}
        while out[k] in out and out[k] not in seen:
            seen.add(out[k]); out[k] = out[out[k]]
    return out


FORMER: dict[str, list[str]] = {}


def former_tickers(names) -> dict[str, list[str]]:
    """{current symbol: [former symbols]} for the universe's names, from the change table (chains included) and from
    any old symbol read from the inputs."""
    tmap = ticker_map()
    out: dict[str, list[str]] = {k: list(v) for k, v in FORMER.items()}
    present = set(names)
    for old, cur in tmap.items():
        if cur in present and old not in out.setdefault(cur, []):
            out[cur].append(old)
    return {k: sorted(v) for k, v in sorted(out.items()) if v}


def read_list(path: Path) -> list[str]:
    if not path.exists():
        sys.exit(f"build_universe: required input missing: {path.relative_to(ROOT)}")
    seen, out = set(), []
    tmap = ticker_map()
    for tok in path.read_text().split():
        tk = norm(tok)
        if tk in tmap:                                   # G3: a symbol that changed is read as its current symbol
            FORMER.setdefault(tmap[tk], [])
            if tk not in FORMER[tmap[tk]]:
                FORMER[tmap[tk]].append(tk)
            tk = tmap[tk]
        if tk and not tk.startswith("#") and tk not in seen:
            seen.add(tk)
            out.append(tk)
    return out


def main() -> None:
    tourn = read_list(TOURNAMENT_UNIVERSE)
    screen = read_list(SCREENER_UNIVERSE)
    cfg = json.loads(SCREEN_CONFIG.read_text())
    midcap = []
    for tk in cfg.get("midcap_additions", []):
        tk = norm(tk)
        if tk and tk not in midcap:
            midcap.append(tk)
    hb = json.loads(HOLDINGS.read_text())
    held = []
    for h in hb.get("holdings", []):
        if (h.get("shares") or 0) > 0:
            tk = norm(h["ticker"])
            if tk not in held:
                held.append(tk)

    set_t = set(tourn)
    set_s = set(screen) | set(midcap)          # the screen view's universe = file ∪ midcap supplement
    union = sorted(set_t | set_s | set(held))
    # Tournament audit 30-Sept-2026 (2.4 / T3): one issuer, one class. data/share_classes.json
    # lists the dual-class issuers and the class kept (the more liquid one, measured once and
    # recorded there); the other classes leave the union — unless the operator holds them,
    # since every held name is always a member.
    collapse = {"dropped": [], "kept": [], "source": "data/share_classes.json"}
    scp = DATA / "share_classes.json"
    if scp.exists():
        sc = json.loads(scp.read_text())
        for issuer, spec in (sc.get("issuers") or {}).items():
            keep = norm(spec.get("keep", ""))
            classes = [norm(c) for c in spec.get("classes", [])]
            present = [c for c in classes if c in union]
            if len(present) > 1:
                # a class the operator holds is the one kept (every held name is a member), else the
                # more liquid class recorded in share_classes.json
                held_cls = [c for c in present if c in held]
                keep = held_cls[0] if held_cls else keep
                basis = "held by the operator" if held_cls else "the more liquid class"
                for c in present:
                    if c != keep:
                        union.remove(c); collapse["dropped"].append({"issuer": issuer, "class": c, "kept": keep, "basis": basis})
                collapse["kept"].append({"issuer": issuer, "class": keep, "basis": basis})
    union = sorted(union)

    only_tournament = sorted(set_t - set_s)
    only_screener_or_midcap = sorted(set_s - set_t)
    held_added = sorted(set(held) - set_t - set_s)

    text = "\n".join(union) + "\n"
    sha = hashlib.sha256(text.encode()).hexdigest()

    # on_change: keep the existing as_of when the membership is unchanged.
    prev_meta = {}
    if OUT_META.exists():
        try:
            prev_meta = json.loads(OUT_META.read_text())
        except Exception:
            prev_meta = {}
    unchanged = (OUT_UNIVERSE.exists() and OUT_UNIVERSE.read_text() == text
                 and prev_meta.get("sha256") == sha)
    as_of = prev_meta.get("as_of") if unchanged and prev_meta.get("as_of") else date.today().isoformat()

    meta = {
        "cadence": "on_change",
        "as_of": as_of,
        "built_by": "scripts/build_universe.py (order 6.2, 2026-09-16)",
        "rule": "union of the tournament's canonical universe, the screen view's universe "
                "(historical file + config midcap_additions) and every held name in data/holdings.json; "
                "sorted, one ticker per line; consumed by both scoring views",
        "inputs": {
            "tournament_canonical": {"path": "data/canonical/universe.txt", "n": len(tourn)},
            "screener_historical": {"path": "data/screen/universe_535.txt", "n": len(screen)},
            "midcap_additions": {"path": "scripts/screen/config.json#midcap_additions", "n": len(midcap)},
            "holdings": {"path": "data/holdings.json", "n": len(held),
                         "as_of": hb.get("as_of"), "tickers": held},
        },
        "screen_universe_size": len(set_s),
        "union_size": len(union),
        "only_tournament": only_tournament,
        "only_screener_or_midcap": only_screener_or_midcap,
        "held_added": held_added,
        "share_class_collapse": collapse,
        "former_tickers": former_tickers(union),                       # G3 (second follow-up, 7-Oct-2026): current symbol -> its former symbols (the change table)
        "ticker_changes": "data/analyst/ticker_changes.csv",
        "sha256": sha,
        "output": "data/universe.txt",
    }

    if unchanged and prev_meta == meta:
        print(f"universe unchanged ({len(union)} names, sha256 {sha[:12]}…) — nothing written")
    else:
        OUT_UNIVERSE.write_text(text)
        OUT_META.write_text(json.dumps(meta, indent=1) + "\n")
        print(f"wrote data/universe.txt ({len(union)} names) and data/universe_meta.json (as_of {as_of})")

    print(f"  tournament canonical {len(tourn)} | screener file {len(screen)} + midcap {len(midcap)} "
          f"= screen universe {len(set_s)} | held {len(held)} | union {len(union)}")
    print(f"  only_tournament ({len(only_tournament)}): {only_tournament or '—'}")
    print(f"  only_screener_or_midcap ({len(only_screener_or_midcap)}): {only_screener_or_midcap or '—'}")
    print(f"  held_added ({len(held_added)}): {held_added or '—'}")


if __name__ == "__main__":
    main()
