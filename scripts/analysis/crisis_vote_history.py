#!/usr/bin/env python3
"""crisis_vote_history.py — read-only analysis for Decision Memo [R2] of 1 October 2026.

Question: the dashboard headline (app.js headlineVerdict()) takes the worst of the v2 regime label,
the early-warning label and a crisis-channel vote (n_crisis >= 1 -> DEFENSIVE, n_crisis >= 4 ->
CRISIS). How often has that vote, alone, raised the headline, which channels did it, and what would
the headline history have been under three options (A keep the vote; B count a channel only if its
ten-year percentile in the risky direction is >= 90; C show the count, no vote)?

What it reads
  * data/source/*.parquet through the v2 model's own functions (load_sources, load_series_dict,
    build_daily_panel, compute_zscores_and_risk, compute_composites, classify, status_from_phi).
    compute_regime_v2.main() is NEVER called: main() writes served files.
  * the git history of data/regime_indicators.json and blob ids (git log / show / rev-parse /
    hash-object only; nothing that changes git state).
  * data/regime_v2_daily.csv (the CI-written full history), for a sensitivity check only.

What it writes (nothing else)
  * reports/crisis_vote_history_2026-10-01.csv   one row per session
  * stdout                                        the memo's tables, in Markdown

Run from the repository root:
    .venv/bin/python scripts/analysis/crisis_vote_history.py
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import compute_regime_v2 as v2          # noqa: E402  (functions only; main() is never called)
import regime_label                     # noqa: E402

OUT_CSV = REPO / "reports" / "crisis_vote_history_2026-10-01.csv"
SERVED_PATH = "data/regime_indicators.json"
Z_LONG = 756                 # long-window z for part 1
Z_LONG_MIN_PERIODS = v2.MIN_PERIODS   # 60, the model's own min_periods (stated in the memo)
PCT_YEARS = 10
PCT_MIN_OBS = 250
B_THRESHOLD = 90.0
# served history read through this commit time: the 2026-10-01 nightly (2082b01, 04:22:14 UTC) and
# the [R1] display commit (2ef8d0d, 06:44:40 UTC, a non-nightly rewrite of the same as_of). Set to
# None to read the whole history.
CUTOFF_CT = int(pd.Timestamp("2026-10-01 12:00:00", tz="UTC").timestamp())

RANK = {"DEPLOY": 0, "LOW RISK": 0, "CLEAR": 0,
        "CAUTIOUS": 1, "ELEVATED": 1, "WATCH": 1,
        "DEFENSIVE": 2, "HIGH RISK": 2, "WARNING": 2,
        "CRISIS": 3, "DANGER": 3}
HEADLINE = ["DEPLOY", "CAUTIOUS", "DEFENSIVE", "CRISIS"]
DIRECTION = {k: d for k, _t, d, *_ in v2.INDICATORS}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True)


# ── 0. the model code used is the committed code ────────────────────────────────────────────────
def check_model_code() -> list[str]:
    """Every function used must be byte-identical to HEAD's compute_regime_v2.py."""
    head_src = git("show", "HEAD:scripts/compute_regime_v2.py")
    used = [v2.load_sources, v2.derive_series, v2.load_series_dict, v2.build_daily_panel,
            v2.compute_zscores_and_risk, v2.compute_composites, v2.classify, v2.status_from_phi]
    notes = []
    for fn in used:
        ok = inspect.getsource(fn) in head_src
        notes.append(f"{fn.__name__}: {'identical to HEAD' if ok else 'DIFFERS FROM HEAD'}")
        if not ok:
            raise SystemExit(f"model function {fn.__name__} differs from HEAD; refusing to run")
    for line in ("LOOKBACK    = 252", "MIN_PERIODS = 60", "MIN_LEAD    = 8", "MIN_FULL    = 12"):
        if line not in head_src:
            raise SystemExit(f"constant line changed in HEAD: {line!r}")
    notes.append("HEAD " + git("rev-parse", "--short", "HEAD").strip()
                 + ", compute_regime_v2.py blob " + git("rev-parse", "--short", "HEAD:scripts/compute_regime_v2.py").strip())
    # the inputs: source parquets read by load_sources(), with their git blob ids
    for stem in ["fred_indicators", "fred_derived", "vol_indicators", "vol_derived", "sector_etfs"]:
        p = f"data/source/{stem}.parquet"
        wt = git("hash-object", p).strip()[:7]
        try:
            hd = git("rev-parse", f"HEAD:{p}").strip()[:7]
        except subprocess.CalledProcessError:
            hd = "untracked"
        notes.append(f"{p}: working tree {wt}, HEAD {hd}{'' if wt == hd else ' (DIFFERS)'}; "
                     f"last commit {git('log', '-1', '--format=%h %cI', '--', p).strip()}")
    return notes


# ── 1. the revised model, recomputed with the unchanged v2 code ─────────────────────────────────
def revised_model():
    sources = v2.load_sources()
    series = v2.load_series_dict(sources)
    panel = v2.build_daily_panel(series)
    z, phi = v2.compute_zscores_and_risk(panel)
    r_lead, r_full, div, n_lead, n_full = v2.compute_composites(phi)
    regime, ew, _div = v2.classify(r_full, r_lead, div)
    status = phi.apply(lambda col: col.map(lambda p: v2.status_from_phi(p) if pd.notna(p) else None))
    return series, panel, z, phi, r_lead, r_full, regime, ew, status


def long_z(panel: pd.DataFrame, window: int = Z_LONG, min_periods: int = Z_LONG_MIN_PERIODS) -> pd.DataFrame:
    """Same method as compute_zscores_and_risk, window 756: rolling mean/std on the panel series,
    sign flipped for 'lower' channels."""
    out = pd.DataFrame(index=panel.index)
    for col in panel.columns:
        s = panel[col]
        m = s.rolling(window, min_periods=min_periods).mean()
        sd = s.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
        zz = (s - m) / sd
        out[col] = -zz if DIRECTION.get(col) == "lower" else zz
    return out


class Pctile:
    """scripts/bonds/compute_bonds.py::pctile on the v2 daily panel: share of the trailing ten
    calendar years of the series, through the session, strictly below the value, x100, rounded to
    0.1; None with fewer than 250 observations."""

    def __init__(self, panel: pd.DataFrame):
        self.s = {c: panel[c].dropna() for c in panel.columns}
        self.idx = {c: s.index.values for c, s in self.s.items()}
        self.val = {c: s.values for c, s in self.s.items()}

    def raw(self, col: str, value, through: pd.Timestamp):
        if col not in self.s or value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        through = pd.Timestamp(through)
        lo = np.searchsorted(self.idx[col], (through - pd.DateOffset(years=PCT_YEARS)).to_datetime64(), "left")
        hi = np.searchsorted(self.idx[col], through.to_datetime64(), "right")
        w = self.val[col][lo:hi]
        if len(w) < PCT_MIN_OBS:
            return None
        return round(float((w < value).mean()) * 100.0, 1)

    def risky(self, col: str, value, through, direction: str | None = None):
        p = self.raw(col, value, through)
        if p is None:
            return None
        d = direction or DIRECTION.get(col)
        return round(100.0 - p, 1) if d == "lower" else p

    def window_info(self, col: str, through):
        through = pd.Timestamp(through)
        s = self.s[col].loc[through - pd.DateOffset(years=PCT_YEARS):through]
        return len(s), s.index.min().date().isoformat()


# ── 2. served snapshots from git history ───────────────────────────────────────────────────────
NIGHTLY_MARK = "\U0001F4CA"      # the nightly job's commit subject starts with this mark ("📊 YYYY-MM-DD")


def served_snapshots(cutoff_ct: int | None = None):
    """One version per as_of: the LAST NIGHTLY commit carrying that as_of (by commit time). Manual
    commits that rewrote the file (model changes, display-only regenerations such as [R1]) are used
    only for an as_of no nightly commit carries. cutoff_ct pins the history to commits at or before
    that unix time so a rerun after later commits reproduces the memo."""
    log = git("log", "--format=%H %ct %s", "--", SERVED_PATH).strip().splitlines()
    by_asof: dict[str, list] = defaultdict(list)
    n_read = 0
    for line in log:
        sha, ct, subj = line.split(" ", 2)
        if cutoff_ct is not None and int(ct) > cutoff_ct:
            continue
        try:
            d = json.loads(git("show", f"{sha}:{SERVED_PATH}"))
        except Exception as e:  # noqa: BLE001
            print(f"  warn: {sha[:7]} unreadable: {e}", file=sys.stderr)
            continue
        n_read += 1
        a = d.get("as_of")
        if not a:
            continue
        by_asof[a].append((int(ct), sha, d, subj.startswith(NIGHTLY_MARK)))
    snaps, multi, fallback, any_vs_nightly = {}, [], [], []
    for a, vers in by_asof.items():
        vers.sort(key=lambda t: t[0])
        nightly = [v for v in vers if v[3]]
        ct, sha, d, _n = (nightly or vers)[-1]
        if not nightly:
            fallback.append(a)
        snaps[a] = {"sha": sha, "ct": ct, "d": d, "n_versions": len(vers)}
        last_any = vers[-1][2]
        k = lambda x: (x.get("regime"), x.get("early_warning"), x.get("n_crisis"))  # noqa: E731
        if k(last_any) != k(d):
            any_vs_nightly.append((a, k(d), k(last_any), vers[-1][1][:7]))
        if len(vers) > 1:
            keys = {k(v[2]) for v in vers}
            multi.append((a, len(vers), len(keys)))
    return snaps, n_read, sorted(multi), sorted(fallback), sorted(any_vs_nightly)


# ── 3. headline rules ──────────────────────────────────────────────────────────────────────────
def base_rank(regime, ew) -> int:
    rs = [RANK[x] for x in (regime, ew) if x in RANK]
    return max(rs) if rs else 0


def vote_rank(n: int) -> int:
    return 3 if n >= 4 else (2 if n >= 1 else 0)


def complacent_truthy(flag) -> bool:
    """app.js: !!(reg.complacency_flag || ...) — True and the string 'impaired' are both truthy."""
    return bool(flag)


def main():
    notes = check_model_code()
    series, panel, z, phi, r_lead, r_full, regime, ew, status = revised_model()
    zl = long_z(panel)
    P = Pctile(panel)
    snaps, n_versions_total, multi, fallback, any_vs_nightly = served_snapshots(CUTOFF_CT)

    # corridor check: classify()'s label equals regime_label.corridor_series on the same R_full
    rf = r_full.dropna()
    corridor = regime_label.corridor_series(rf.values)
    corr_mismatch = int((pd.Series(corridor, index=rf.index) != regime.loc[rf.index]).sum())
    plain = rf.map(regime_label.plain_band)
    plain_vs_corr = int((plain != regime.loc[rf.index]).sum())

    sessions = list(rf.index)
    served_not_in_panel = sorted(a for a in snaps if pd.Timestamp(a) not in set(sessions))
    rows = []
    for t in sessions:
        key = t.strftime("%Y-%m-%d")
        rev_crisis = [c for c in status.columns if status.at[t, c] == "crisis"]
        sk, vx = panel.at[t, "skew"] if "skew" in panel else np.nan, panel.at[t, "vix"] if "vix" in panel else np.nan
        rev_compl = "impaired" if (pd.isna(sk) or pd.isna(vx)) else bool(sk > 140 and vx < 17)
        rev = {"regime": regime.at[t], "ew": ew.at[t], "n_crisis": len(rev_crisis),
               "crisis": [(c, float(panel.at[t, c]), DIRECTION[c]) for c in rev_crisis],
               "complacency": rev_compl, "R_full": float(r_full.at[t]),
               "R_lead": float(r_lead.at[t]) if pd.notna(r_lead.at[t]) else None}
        if key in snaps:
            d = snaps[key]["d"]
            inds = d.get("indicators", [])
            cr = [(i["key"], i.get("value"), i.get("direction") or DIRECTION.get(i["key"]))
                  for i in inds if i.get("status") == "crisis"]
            use = {"regime": d.get("regime"), "ew": d.get("early_warning"),
                   "n_crisis": int(d.get("n_crisis") or 0), "crisis": cr,
                   "complacency": d.get("complacency_flag"), "R_full": d.get("R_full"), "R_lead": d.get("R_lead")}
            src, sha = "served", snaps[key]["sha"][:7]
            if len(cr) != use["n_crisis"]:
                print(f"  warn: {key} served n_crisis {use['n_crisis']} != crisis statuses {len(cr)}", file=sys.stderr)
        else:
            use, src, sha = rev, "revised", ""
        # ten-year percentile in the risky direction of each crisis channel on this session
        pct = []
        for c, val, dirn in use["crisis"]:
            v = val if val is not None else (float(panel.at[t, c]) if c in panel else None)
            pct.append((c, P.risky(c, v, t, dirn)))
        nB = sum(1 for _c, p in pct if p is not None and p >= B_THRESHOLD)
        b = base_rank(use["regime"], use["ew"])
        hA, hB, hC = max(b, vote_rank(use["n_crisis"])), max(b, vote_rank(nB)), b
        comp = complacent_truthy(use["complacency"])
        # what the revised recompute says on a served session (revision check)
        rev_hA = max(base_rank(rev["regime"], rev["ew"]), vote_rank(rev["n_crisis"]))
        rows.append({
            "date": key, "source": src, "commit": sha,
            "R_full": use["R_full"], "R_lead": use["R_lead"],
            "regime": use["regime"], "early_warning": use["ew"], "base_rank": b,
            "n_crisis": use["n_crisis"], "n_crisis_B": nB,
            "crisis_channels": ";".join(c for c, _ in pct),
            "crisis_pctile10y_risky": ";".join(f"{c}={'' if p is None else p}" for c, p in pct),
            "headline_A": HEADLINE[hA], "headline_B": HEADLINE[hB], "headline_C": HEADLINE[hC],
            "complacency": use["complacency"],
            "headline_A_cpl": "COMPLACENT" if (comp and hA == 0) else HEADLINE[hA],
            "headline_B_cpl": "COMPLACENT" if (comp and hB == 0) else HEADLINE[hB],
            "headline_C_cpl": "COMPLACENT" if (comp and hC == 0) else HEADLINE[hC],
            "revised_headline_A": HEADLINE[rev_hA],
            "_pct": pct,
        })
    df = pd.DataFrame(rows)
    df.drop(columns=["_pct"]).to_csv(OUT_CSV, index=False)

    # ── output ──────────────────────────────────────────────────────────────────────────────
    pr = print
    pr("# crisis_vote_history.py — output\n")
    pr("## Model code check")
    for n in notes:
        pr(f"- {n}")
    pr(f"- classify() regime label vs regime_label.corridor_series on the same R_full: {corr_mismatch} mismatches "
       f"of {len(rf)}; vs plain bands: {plain_vs_corr} sessions differ")
    pr(f"- served versions in git (commit time <= cutoff {CUTOFF_CT}): {n_versions_total}; distinct as_of: {len(snaps)}; "
       f"as_of with >1 version: {len(multi)} (of which label/n_crisis differed across versions: "
       f"{sum(1 for _a, _n, k in multi if k > 1)}: {[a for a, _n, k in multi if k > 1]})")
    pr(f"- as_of carried by no nightly commit (last manual version used): {fallback}")
    pr(f"- as_of where the last nightly version and the last version of any kind differ in "
       f"(regime, early_warning, n_crisis): {any_vs_nightly}")
    pr(f"- served as_of not a panel session: {served_not_in_panel}")
    pr(f"- sessions with R_full: {len(df)} ({df.date.iloc[0]} .. {df.date.iloc[-1]}); "
       f"served {int((df.source == 'served').sum())}, revised {int((df.source == 'revised').sum())}")

    # Part 1: today's state
    pr("\n## Part 1 — crisis channels on the last two served sessions")
    pr("| as_of | channel | dir | served value | served z252 | recomputed value | recomputed z252 | z756 | 10y pctile (raw) | 10y pctile risky | obs in 10y window | window starts |")
    pr("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for a in sorted(snaps)[-2:]:
        d = snaps[a]["d"]; t = pd.Timestamp(a)
        for i in d["indicators"]:
            if i.get("status") != "crisis":
                continue
            c = i["key"]
            nobs, wstart = P.window_info(c, t)
            pr(f"| {a} | {c} | {i.get('direction')} | {i.get('value'):.4g} | {i.get('z'):+.3f} | "
               f"{panel.at[t, c]:.4g} | {z.at[t, c]:+.3f} | {zl.at[t, c]:+.3f} | {P.raw(c, i.get('value'), t)} | "
               f"{P.risky(c, i.get('value'), t, i.get('direction'))} | {nobs} | {wstart} |")
        pr(f"\n{a}: served regime {d.get('regime')} (R_full {d.get('R_full')}), early warning {d.get('early_warning')} "
           f"(R_lead {d.get('R_lead')}), n_crisis {d.get('n_crisis')}, complacency_flag {d.get('complacency_flag')}; "
           + ", ".join(f"{o} {df.loc[df.date == a, 'headline_' + o].iloc[0]} (with complacency {df.loc[df.date == a, 'headline_' + o + '_cpl'].iloc[0]})" for o in "ABC") + "\n")
    hy0 = series["hy_oas"].index.min().date() if "hy_oas" in series else None
    pr(f"hy_oas stored history starts {hy0}; its 'ten-year' window is that history.")

    # Part 2: raised sessions
    pr("\n## Part 2 — sessions raised by the vote alone (option A headline above the regime/EW reading)")
    base = df.base_rank
    rankA = df.headline_A.map(HEADLINE.index)
    raised = df[rankA > base].copy()
    last252 = df.iloc[-252:]
    subsets = {"all": df, "served": df[df.source == "served"], "revised": df[df.source == "revised"], "last 252": last252}
    pr("| subset | sessions | raised to DEFENSIVE (n>=1) | raised to CRISIS (n>=4) | raised total | share |")
    pr("|---|---|---|---|---|---|")
    for name, s in subsets.items():
        rA = s.headline_A.map(HEADLINE.index); rb = s.base_rank
        up = rA > rb
        to_def = int((up & (rA == 2)).sum()); to_cri = int((up & (rA == 3)).sum())
        pr(f"| {name} | {len(s)} | {to_def} | {to_cri} | {to_def + to_cri} | {100 * (to_def + to_cri) / max(len(s), 1):.1f}% |")

    def channel_table(sub: pd.DataFrame, title: str):
        pr(f"\n### Per-channel summary on raised sessions — {title} ({len(sub)} raised sessions)")
        stats = defaultdict(lambda: {"n": 0, "n_served": 0, "sole": 0, "p": [], "none": 0})
        for _, r in sub.iterrows():
            pct = r["_pct"]
            for c, p in pct:
                s = stats[c]; s["n"] += 1; s["n_served"] += int(r.source == "served")
                s["sole"] += int(len(pct) == 1)
                if p is None:
                    s["none"] += 1
                else:
                    s["p"].append(p)
        pr("| channel | dir | raised sessions where crisis | of which served | sole crisis channel | median 10y pctile risky | min | max | sessions >= 90 | pctile unavailable |")
        pr("|---|---|---|---|---|---|---|---|---|---|")
        for c, s in sorted(stats.items(), key=lambda kv: -kv[1]["n"]):
            p = np.array(s["p"]) if s["p"] else np.array([np.nan])
            pr(f"| {c} | {DIRECTION.get(c)} | {s['n']} | {s['n_served']} | {s['sole']} | {np.nanmedian(p):.1f} | "
               f"{np.nanmin(p):.1f} | {np.nanmax(p):.1f} | {int((p >= B_THRESHOLD).sum())} | {s['none']} |")

    channel_table(raised, "all sessions")
    channel_table(raised[raised.source == "served"], "served sessions")
    channel_table(raised[raised.index >= df.index[-252]], "last 252 sessions")

    pr("\n### Most recent 30 raised sessions")
    pr("| date | source | regime | early warning | n_crisis | headline A | crisis channels (10y pctile, risky direction) | headline B |")
    pr("|---|---|---|---|---|---|---|---|")
    for _, r in raised.tail(30).iterrows():
        ch = ", ".join(f"{c} {'n/a' if p is None else f'{p:.1f}'}" for c, p in r["_pct"])
        pr(f"| {r.date} | {r.source} | {r.regime} | {r.early_warning} | {r.n_crisis} | {r.headline_A} | {ch} | {r.headline_B} |")

    # Part 3: options
    def changes(s: pd.Series, restrict: pd.Series | None = None) -> int:
        ch = (s != s.shift(1)) & s.shift(1).notna()
        if restrict is not None:
            ch = ch & restrict
        return int(ch.sum())

    pr("\n## Part 3 — options (headline without complacency/shock)")
    for name, s in subsets.items():
        pr(f"\n### {name} ({len(s)} sessions, {s.date.iloc[0]} .. {s.date.iloc[-1]})")
        pr("| option | DEPLOY | CAUTIOUS | DEFENSIVE | CRISIS | changes | sessions differing from A |")
        pr("|---|---|---|---|---|---|---|")
        for o in "ABC":
            col = "headline_" + o
            cnt = Counter(s[col])
            if name == "last 252":
                nch = changes(s[col])                      # transitions inside the window (251 pairs)
            else:
                nch = changes(df[col], df.index.isin(s.index))   # transitions INTO sessions of the subset
            diff = int((s[col] != s.headline_A).sum())
            pr(f"| {o} | {cnt.get('DEPLOY', 0)} | {cnt.get('CAUTIOUS', 0)} | {cnt.get('DEFENSIVE', 0)} | {cnt.get('CRISIS', 0)} | {nch} | {diff} |")

    pr("\n## Part 3b — same, with the complacency rule applied (DEPLOY -> COMPLACENT when the flag is truthy)")
    for name, s in subsets.items():
        pr(f"\n### {name}")
        pr("| option | DEPLOY | COMPLACENT | CAUTIOUS | DEFENSIVE | CRISIS | changes | differing from A |")
        pr("|---|---|---|---|---|---|---|---|")
        for o in "ABC":
            col = f"headline_{o}_cpl"
            cnt = Counter(s[col])
            nch = changes(s[col]) if name == "last 252" else changes(df[col], df.index.isin(s.index))
            diff = int((s[col] != s.headline_A_cpl).sum())
            pr(f"| {o} | {cnt.get('DEPLOY', 0)} | {cnt.get('COMPLACENT', 0)} | {cnt.get('CAUTIOUS', 0)} | {cnt.get('DEFENSIVE', 0)} | {cnt.get('CRISIS', 0)} | {nch} | {diff} |")

    # Part 3c: the counterfactual histories in compact form
    def lvl(s: pd.Series) -> str:
        c = Counter(s)
        return "/".join(str(c.get(h, 0)) for h in HEADLINE)
    pr("\n## Part 3c — headline history by month, last 252 sessions (DEPLOY/CAUTIOUS/DEFENSIVE/CRISIS, no complacency)")
    pr("| month | sessions | A | B | C |")
    pr("|---|---|---|---|---|")
    l2 = last252.assign(m=last252.date.str[:7])
    for m, g in l2.groupby("m"):
        pr(f"| {m} | {len(g)} | {lvl(g.headline_A)} | {lvl(g.headline_B)} | {lvl(g.headline_C)} |")
    pr("\n## Part 3d — by year, all sessions: share of sessions at DEFENSIVE or CRISIS; changes")
    pr("| year | sessions | n_crisis>=1 | A def+ | B def+ | C def+ | A changes | B changes | C changes |")
    pr("|---|---|---|---|---|---|---|---|---|")
    y = df.date.str[:4]
    chg = {o: (df["headline_" + o] != df["headline_" + o].shift(1)) & df["headline_" + o].shift(1).notna() for o in "ABC"}
    for yr in sorted(y.unique()):
        g = df[y == yr]
        dp = {o: 100 * (g["headline_" + o].map(HEADLINE.index) >= 2).mean() for o in "ABC"}
        pr(f"| {yr} | {len(g)} | {100 * (g.n_crisis >= 1).mean():.0f}% | {dp['A']:.0f}% | {dp['B']:.0f}% | {dp['C']:.0f}% | "
           f"{int(chg['A'][y == yr].sum())} | {int(chg['B'][y == yr].sum())} | {int(chg['C'][y == yr].sum())} |")
    pr(f"\nn_crisis over all sessions: >=1 on {100 * (df.n_crisis >= 1).mean():.1f}%, >=4 on {100 * (df.n_crisis >= 4).mean():.1f}%, "
       f"median {df.n_crisis.median():.0f}; n_crisis_B >=1 on {100 * (df.n_crisis_B >= 1).mean():.1f}%, >=4 on {100 * (df.n_crisis_B >= 4).mean():.1f}%")
    for name, s in (("last 252", last252), ("all", df)):
        bc = s.headline_B.map(HEADLINE.index) > s.headline_C.map(HEADLINE.index)
        cnt = Counter(c for pct in s.loc[bc, "_pct"] for c, p in pct if p is not None and p >= B_THRESHOLD)
        pr(f"B above C, {name}: {int(bc.sum())} sessions; qualifying channels (sessions): {cnt.most_common(8)}")

    # Sensitivity: the revised labels here against the served full-history file written by the CI
    # nightly (data/regime_v2_daily.csv, read only). They should be identical; where they are not, the
    # difference is numerical (same code, same parquets, different machine).
    srv = pd.read_csv(REPO / "data" / "regime_v2_daily.csv", dtype={"date": str})
    srv["date"] = srv["date"].str[:10]
    mm = df.merge(srv[["date", "R_full", "regime", "early_warning"]], on="date", how="left", suffixes=("", "_ci"))
    rv = mm.source == "revised"
    dR = (mm.loc[rv, "R_full"] - mm.loc[rv, "R_full_ci"]).abs()
    lab_diff = rv & ((mm.regime != mm.regime_ci) | (mm.early_warning != mm.early_warning_ci))
    pr("\n## Sensitivity — revised labels vs the CI-written data/regime_v2_daily.csv")
    pr(f"- revised sessions with |R_full - CI R_full| > 1e-4: {int((dR > 1e-4).sum())} "
       f"({mm.loc[rv & ((mm.R_full - mm.R_full_ci).abs() > 1e-4), 'date'].min()} .. "
       f"{mm.loc[rv & ((mm.R_full - mm.R_full_ci).abs() > 1e-4), 'date'].max()}); max {dR.max():.4f}")
    pr(f"- revised sessions whose regime or early-warning label differs: {int(lab_diff.sum())}")
    for o in "ABC":
        alt = []
        for _, r in mm.iterrows():
            if r.source != "revised":
                alt.append(r["headline_" + o]); continue
            b = base_rank(r.regime_ci, r.early_warning_ci)
            n = r.n_crisis if o == "A" else (r.n_crisis_B if o == "B" else 0)
            alt.append(HEADLINE[max(b, vote_rank(int(n)))])
        alt = pd.Series(alt, index=mm.index)
        pr(f"- option {o} with CI labels on revised sessions: headline differs on {int((alt != mm['headline_' + o]).sum())} sessions; "
           f"levels {dict(Counter(alt))}; changes {changes(alt)} (vs {changes(mm['headline_' + o])})")

    # Served-subsequence view and revision check
    sv = df[df.source == "served"]
    pr("\n## Served sessions read in sequence (transitions between consecutive served snapshots only)")
    for o in "ABC":
        pr(f"- {o}: {changes(sv['headline_' + o].reset_index(drop=True))} changes over {len(sv)} served sessions")
    agree = int((sv.headline_A == sv.revised_headline_A).sum())
    pr(f"- revision check: on served sessions the revised recompute gives the same option-A headline on {agree} of {len(sv)}")

    # crisis channel-sessions overall
    allp = [p for pct in df["_pct"] for _c, p in pct]
    pr(f"\n## All crisis channel-sessions: {len(allp)}; with 10y risky pctile >= 90: "
       f"{sum(1 for p in allp if p is not None and p >= B_THRESHOLD)}; unavailable: {sum(1 for p in allp if p is None)}")
    pr(f"\nCSV: {OUT_CSV.relative_to(REPO)}")


if __name__ == "__main__":
    main()
