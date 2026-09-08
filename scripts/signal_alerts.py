#!/usr/bin/env python3
"""
signal_alerts.py — order item 4.3: signal alerts as GitHub issues.

Post-publish step of the nightly (daily_update.yml, after the data/ commit).
Compares the served state with the last recorded state (data/alert_state.json)
and, on a genuine transition, opens ONE GitHub issue per event type in this
repository, labelled per event type; GitHub's notification delivers it. When
the state reverts, the open issue is closed with a comment stating the
reverting values and the session. No external service, no additional secret:
`gh` runs with the job token (GH_TOKEN = github.token, permissions.issues:
write).

Events (served inputs, read-only)
  regime       data/regime_indicators.json  `regime` label + `R_full`
  shock        data/intraday.json           `shock_active` became true
  complacency  data/intraday.json           `complacency_active` became true,
               OR the check became IMPAIRED (`complacency_active == "impaired"`
               / "complacency" in `impaired_checks`); the issue body says
               which. Fallback when intraday.json is absent or lacks the
               field: regime_indicators.json `complacency_flag` (active only).
  data/status.json supplies the pipeline session / last_success for the body.
  (data/vol_regime.json carries no impaired flag — checked, not used.)

Bands — copied from scripts/compute_regime_v2.py classify(), lines 295-297
(JULY AUDIT FIX 4b). They are function-local there, so they cannot be
imported; keep in sync by hand:
  LEVELS = LOW RISK | ELEVATED | HIGH RISK | CRISIS      EDGES = 0.30/0.50/0.70

Hysteresis rule (design item 3)
  A regime transition counts only if the served label differs from the label
  held in the alert state AND R_full has moved at least H = 0.02 beyond the
  edge it crossed, i.e. it sits >= 0.02 inside the new band: an upward move
  needs R_full >= edge + 0.02, a downward move needs R_full <= edge - 0.02,
  where `edge` is the boundary of the new band on the side it was entered
  (the last edge crossed for a multi-band jump). Otherwise the alert state
  keeps the previous label and nothing is opened or closed. The same rule
  decides a revert (label back to the band the open issue started from).
  This is deliberately independent of the +/-0.02 corridor compute_regime_v2
  applies when it writes the label: the served label is recomputed over the
  full (revised) history every night and can flip without R_full sitting
  clearly inside the new band on the latest session.

Per-session cap
  At most one issue per event type per session: the state file records the
  session each event type last opened an issue, and in live mode
  `gh issue list --label <x> --state open` is consulted before creating — an
  existing open issue is reused (commented), never duplicated. A further move
  while a regime issue is open (e.g. HIGH RISK -> CRISIS) closes it as
  superseded and opens the new transition.

State file data/alert_state.json
  cadence "daily", session_date, as_of (from the served regime file), the
  alert-level regime label + served label + R_full, shock flag, complacency
  kind (active / impaired / null), intraday stamps, the open issue per event
  type and the session each event type last opened an issue. The file is only
  rewritten when its content changes (no clock-only churn).

First run (no state file): record the state and exit 0 without opening
anything — "first run: state recorded, no alerts" (pre-answered decision).

CLI
  --data-dir DIR     served files + state file location (default: data/)
  --state-file PATH  override the state file (default: DIR/alert_state.json)
  --dry-run          print exactly what would be created/closed and make no
                     gh call at all. Default whenever the env var
                     GITHUB_ACTIONS != "true" — live mode exists only in CI.
  --write-state      write the state file. Dry-run writes it only with this
                     flag (a would-open is recorded with a null placeholder
                     issue number so scenarios can be chained); live mode
                     always writes it, because an unpersisted live action
                     would repeat the next night.
Exit code 0 always; only a crash (unhandled exception) is non-zero, and the
workflow step is additionally guarded with `|| true`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "data"
STATE_FILENAME = "alert_state.json"
SCHEMA = 1

# ── Bands: copied verbatim from scripts/compute_regime_v2.py classify(),
#    lines 295-297. Keep in sync by hand.
LEVELS = ["LOW RISK", "ELEVATED", "HIGH RISK", "CRISIS"]
EDGES = [0.30, 0.50, 0.70]
H = 0.02          # alert-level hysteresis depth (design item 3)

EVENTS = ("regime", "shock", "complacency")
LABELS = {
    "regime": ("alert:regime", "d93f0b",
               "Regime label crossed a band on R_full (hysteresis 0.02); "
               "opened by scripts/signal_alerts.py"),
    "shock": ("alert:shock", "b60205",
              "Intraday shock active (VIX spike / SPX drop / backwardation / HY credit); "
              "opened by scripts/signal_alerts.py"),
    "complacency": ("alert:complacency", "fbca04",
                    "Complacency active (SKEW>140 and VIX<17) or complacency check impaired; "
                    "opened by scripts/signal_alerts.py"),
}
FOOTER = ("_Opened automatically by `scripts/signal_alerts.py` (order item 4.3). "
          "It closes automatically, with a comment, when the state reverts._")
FALLBACK_DASHBOARD = "https://wernerhl.github.io/portfolio-tournament/"


# ─────────────────────────────────────────────────────────────────────
# small helpers
# ─────────────────────────────────────────────────────────────────────
def as_float(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None          # NaN -> None


def fmt(x, nd=4, suffix="", sign=False):
    if x is None:
        return "n/a"
    return f"{x:+.{nd}f}{suffix}" if sign else f"{x:.{nd}f}{suffix}"


def load_json(path: Path):
    """dict/list or None. A missing or unreadable served file is reported and
    treated as absent — the alert step must not crash the nightly on it."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:                # unparseable
        print(f"  WARNING: {path.name} unreadable ({e}); treated as absent")
        return None


def repo_slug() -> str | None:
    slug = os.environ.get("GITHUB_REPOSITORY")
    if slug:
        return slug
    try:
        url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"],
                                      cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    except Exception:
        pass
    return None


def dashboard_url(slug: str | None) -> str:
    if slug and "/" in slug:
        owner, repo = slug.split("/", 1)
        return f"https://{owner}.github.io/{repo}/"
    return FALLBACK_DASHBOARD


def band_note() -> str:
    return (f"bands on R_full: {LEVELS[0]} < {EDGES[0]:.2f} <= {LEVELS[1]} < {EDGES[1]:.2f} "
            f"<= {LEVELS[2]} < {EDGES[2]:.2f} <= {LEVELS[3]}; alert hysteresis {H:.2f}")


# ─────────────────────────────────────────────────────────────────────
# served state
# ─────────────────────────────────────────────────────────────────────
def snapshot(data_dir: Path) -> dict | None:
    reg = load_json(data_dir / "regime_indicators.json")
    if not isinstance(reg, dict):
        return None
    intra = load_json(data_dir / "intraday.json")
    intra = intra if isinstance(intra, dict) else {}
    status = load_json(data_dir / "status.json")
    status = status if isinstance(status, dict) else {}

    session = (reg.get("session_date") or reg.get("as_of")
               or status.get("session_date") or intra.get("session_date"))

    # complacency: intraday carries active / impaired; regime carries active only
    if "complacency_active" in intra:
        ca = intra.get("complacency_active")
        active = ca is True
        impaired = (ca == "impaired") or ("complacency" in (intra.get("impaired_checks") or []))
        compl_source = "intraday.json complacency_active"
        compl_reason = intra.get("complacency_reason")
    else:
        active = reg.get("complacency_flag") is True
        impaired = False
        compl_source = "regime_indicators.json complacency_flag (intraday.json absent)"
        compl_reason = reg.get("complacency_reason")
    kind = "impaired" if impaired else ("active" if active else None)

    return {
        "session": session,
        "as_of": reg.get("as_of") or session,
        "regime_updated": reg.get("updated"),
        "served_label": reg.get("regime"),
        "r_full": as_float(reg.get("R_full")),
        "r_lead": as_float(reg.get("R_lead")),
        "early_warning": reg.get("early_warning"),
        "regime_complacency_flag": reg.get("complacency_flag"),
        "shock_active": intra.get("shock_active") is True,
        "shock_reasons": list(intra.get("shock_reasons") or []),
        "impaired_checks": list(intra.get("impaired_checks") or []),
        "compl_kind": kind,
        "compl_reason": compl_reason,
        "compl_source": compl_source,
        "intraday": {
            "present": bool(intra),
            "session_date": intra.get("session_date"),
            "timestamp": intra.get("timestamp"),
            "spx_change_pct": intra.get("spx_change_pct"),
            "vix_now": intra.get("vix_now"),
            "vix_change_pct": intra.get("vix_change_pct"),
            "vix3m": intra.get("vix3m"),
            "backwardation": intra.get("backwardation"),
            "skew": intra.get("skew"),
            "skew_source": intra.get("skew_source"),
            "credit_change_dur_adj_pct": intra.get("credit_change_dur_adj_pct"),
        },
        "status": {
            "session_date": status.get("session_date"),
            "last_success": status.get("last_success"),
            "last_attempt": status.get("last_attempt"),
            "failure_reason": status.get("failure_reason"),
        },
    }


# ─────────────────────────────────────────────────────────────────────
# hysteresis
# ─────────────────────────────────────────────────────────────────────
def resolve_regime(prev_label, served_label, r_full):
    """Apply the alert-level hysteresis. Returns (alert_label, transition, note).
    `alert_label` is the label the alert state holds after this run."""
    if served_label not in LEVELS:
        return prev_label, False, f"served label {served_label!r} is not a band; keeping {prev_label!r}"
    if prev_label not in LEVELS:
        return served_label, False, "no previous band in alert state; adopting the served label without alert"
    if served_label == prev_label:
        return prev_label, False, None
    if r_full is None:
        return prev_label, False, f"label {prev_label} -> {served_label} but R_full missing; keeping {prev_label}"
    i, j = LEVELS.index(prev_label), LEVELS.index(served_label)
    if j > i:
        edge = EDGES[j - 1]
        depth = r_full - edge
    else:
        edge = EDGES[j]
        depth = edge - r_full
    depth = round(depth, 6)
    if depth >= H:
        return served_label, True, (f"crossed {edge:.2f}: R_full {r_full:.4f} is {depth:.4f} inside "
                                    f"{served_label} (>= {H:.2f})")
    return prev_label, False, (f"suppressed by hysteresis: served label {prev_label} -> {served_label} "
                               f"but R_full {r_full:.4f} is only {depth:.4f} beyond the {edge:.2f} edge "
                               f"(< {H:.2f}); alert state keeps {prev_label}")


# ─────────────────────────────────────────────────────────────────────
# GitHub via gh (live) / printer (dry-run)
# ─────────────────────────────────────────────────────────────────────
class GitHub:
    def __init__(self, dry_run: bool, slug: str | None):
        self.dry_run = dry_run
        self.slug = slug
        self.log: list[str] = []          # human summary of actions taken / would-be

    # -- plumbing -------------------------------------------------------
    def _run(self, args: list[str], stdin: str | None = None) -> str:
        cmd = ["gh", *args]
        if self.slug:
            cmd += ["-R", self.slug]
        p = subprocess.run(cmd, cwd=ROOT, text=True, input=stdin,
                           capture_output=True, timeout=120)
        if p.returncode != 0:
            err = (p.stderr or "").strip().splitlines()
            raise RuntimeError(f"gh {' '.join(args[:2])} failed (rc={p.returncode}): "
                               f"{err[-1] if err else 'no stderr'}")
        return p.stdout

    @staticmethod
    def _number_from_url(url: str) -> int | None:
        m = re.search(r"/issues/(\d+)\s*$", url.strip())
        return int(m.group(1)) if m else None

    # -- operations -----------------------------------------------------
    def ensure_label(self, event: str) -> bool:
        name, color, desc = LABELS[event]
        if self.dry_run:
            print(f"  WOULD ENSURE label {name} (#{color}) — {desc}")
            return True
        try:
            self._run(["label", "create", name, "--color", color, "--description", desc, "--force"])
            return True
        except Exception as e:
            print(f"  WARNING: could not ensure label {name}: {e}")
            return False

    def list_open(self, event: str) -> list[dict]:
        name = LABELS[event][0]
        if self.dry_run:
            print(f"  (dry-run: gh issue list --label {name} --state open not queried)")
            return []
        try:
            out = self._run(["issue", "list", "--label", name, "--state", "open",
                             "--limit", "20", "--json", "number,title,url"])
            return json.loads(out or "[]")
        except Exception as e:
            print(f"  WARNING: gh issue list failed for {name}: {e}")
            return []

    def issue_state(self, number: int) -> str | None:
        if self.dry_run:
            return None
        try:
            return self._run(["issue", "view", str(number), "--json", "state", "--jq", ".state"]).strip()
        except Exception as e:
            print(f"  WARNING: gh issue view #{number} failed: {e}")
            return None

    def create(self, event: str, title: str, body: str) -> dict | None:
        """Returns the issue record {number, url} or None on failure.
        Dry-run returns a placeholder record (number None)."""
        name = LABELS[event][0]
        if self.dry_run:
            print(f"  WOULD CREATE issue")
            print(f"    title : {title}")
            print(f"    labels: {name}")
            print("    body  :")
            for line in body.splitlines():
                print(f"      {line}")
            self.log.append(f"would create [{event}] {title}")
            return {"number": None, "url": None, "dry_run": True}
        labelled = self.ensure_label(event)
        args = ["issue", "create", "--title", title, "--body-file", "-"]
        try:
            out = self._run(args + (["--label", name] if labelled else []), stdin=body)
        except Exception as e:
            if labelled:
                print(f"  WARNING: labelled create failed ({e}); retrying without label")
                try:
                    out = self._run(args, stdin=body)
                except Exception as e2:
                    print(f"  ERROR: could not create issue [{event}]: {e2}")
                    return None
            else:
                print(f"  ERROR: could not create issue [{event}]: {e}")
                return None
        url = out.strip().splitlines()[-1] if out.strip() else ""
        number = self._number_from_url(url)
        print(f"  CREATED issue #{number} {url}")
        self.log.append(f"created [{event}] #{number} {title}")
        return {"number": number, "url": url or None, "dry_run": False}

    def close(self, event: str, rec: dict | None, comment: str) -> bool:
        """Close the recorded issue (or, if the record has no number, any open
        issue carrying the event label). Idempotent: an already-closed issue is
        reported and treated as done."""
        number = (rec or {}).get("number")
        if self.dry_run:
            if rec is None:
                print(f"  no issue recorded for [{event}] (flag was already set when the state was first "
                      f"recorded); live mode would close any open issue labelled {LABELS[event][0]} — "
                      f"gh not queried in dry-run")
                self.log.append(f"nothing recorded to close [{event}]")
                return True
            who = f"#{number}" if number else "(dry-run placeholder, no number)"
            print(f"  WOULD CLOSE issue {who} [{LABELS[event][0]}] with comment:")
            for line in comment.splitlines():
                print(f"      {line}")
            self.log.append(f"would close [{event}] {who}")
            return True
        targets = [number] if number else [i.get("number") for i in self.list_open(event)]
        targets = [n for n in targets if n]
        if not targets:
            print(f"  no open issue found to close for [{event}]")
            return True
        ok = True
        for n in targets:
            st = self.issue_state(n)
            if st == "CLOSED":
                print(f"  issue #{n} already closed")
                continue
            try:
                self._run(["issue", "close", str(n), "--comment", comment])
                print(f"  CLOSED issue #{n}")
                self.log.append(f"closed [{event}] #{n}")
            except Exception as e:
                print(f"  ERROR: could not close issue #{n}: {e}")
                ok = False
        return ok

    def comment(self, event: str, rec: dict | None, body: str) -> None:
        number = (rec or {}).get("number")
        if self.dry_run or not number:
            who = f"#{number}" if number else "(dry-run placeholder)"
            print(f"  WOULD COMMENT on issue {who} [{event}]:")
            for line in body.splitlines():
                print(f"      {line}")
            return
        try:
            self._run(["issue", "comment", str(number), "--body-file", "-"], stdin=body)
            print(f"  COMMENTED on issue #{number}")
            self.log.append(f"commented [{event}] #{number}")
        except Exception as e:
            print(f"  WARNING: could not comment on #{number}: {e}")


# ─────────────────────────────────────────────────────────────────────
# issue text
# ─────────────────────────────────────────────────────────────────────
def _session_lines(snap: dict) -> list[str]:
    st, it = snap["status"], snap["intraday"]
    return [
        f"**Session:** {snap['session']} (regime as_of {snap['as_of']}, computed {snap['regime_updated']})",
        f"**Pipeline status:** session {st['session_date']}, last_success {st['last_success']}, "
        f"failure_reason {st['failure_reason']}",
        f"**Intraday snapshot:** session {it['session_date']}, timestamp {it['timestamp']} UTC",
    ]


def regime_issue(snap: dict, prev: dict, note: str, dash: str) -> tuple[str, str]:
    lab, r = snap["served_label"], snap["r_full"]
    title = f"[regime] {prev['label']} → {lab} (R_full {fmt(r, 2)}) — session {snap['session']}"
    body = "\n".join([
        f"**Event:** regime label crossed a band — {prev['label']} → {lab}",
        *_session_lines(snap),
        "",
        "| | previous (alert state) | current |",
        "|---|---|---|",
        f"| regime label | {prev['label']} | {lab} |",
        f"| R_full | {fmt(prev.get('R_full'))} | {fmt(r)} |",
        f"| R_lead / early warning | — | {fmt(snap['r_lead'])} / {snap['early_warning']} |",
        f"| previous state session | {prev.get('session') or 'n/a'} | {snap['session']} |",
        "",
        f"Hysteresis check: {note}.",
        f"({band_note()})",
        "",
        f"Dashboard: {dash}",
        "",
        FOOTER,
    ])
    return title, body


def shock_issue(snap: dict, prev: dict, dash: str) -> tuple[str, str]:
    it = snap["intraday"]
    reasons = "; ".join(snap["shock_reasons"]) or "no reason recorded"
    title = f"[shock] Shock active: {reasons} — session {snap['session']}"
    body = "\n".join([
        f"**Event:** intraday shock active (shock_active false → true)",
        *_session_lines(snap),
        "",
        f"**Reasons:** {reasons}",
        "",
        "| metric | value |",
        "|---|---|",
        f"| SPX change | {fmt(as_float(it['spx_change_pct']), 2, '%', sign=True)} |",
        f"| VIX | {fmt(as_float(it['vix_now']), 2)} ({fmt(as_float(it['vix_change_pct']), 1, '%', sign=True)}) |",
        f"| VIX3M | {fmt(as_float(it['vix3m']), 2)} (backwardation: {it['backwardation']}) |",
        f"| HY credit, duration-adjusted | {fmt(as_float(it['credit_change_dur_adj_pct']), 2, '%', sign=True)} |",
        f"| impaired checks | {', '.join(snap['impaired_checks']) or 'none'} |",
        f"| regime | {snap['served_label']} (R_full {fmt(snap['r_full'])}) |",
        "",
        f"Previous state: shock inactive (session {prev.get('session') or 'n/a'}).",
        "",
        f"Dashboard: {dash}",
        "",
        FOOTER,
    ])
    return title, body


def complacency_issue(snap: dict, prev: dict, dash: str) -> tuple[str, str]:
    it = snap["intraday"]
    kind = snap["compl_kind"]
    reason = snap["compl_reason"] or "no reason recorded"
    if kind == "impaired":
        # compute_intraday phrases the reason "COMPLACENCY CHECK IMPAIRED — <why>"; keep only <why> in the title
        why = re.sub(r"(?i)^complacency check impaired\s*[—\-:]*\s*", "", reason) or reason
        head = f"Complacency check IMPAIRED: {why}"
        event = "complacency check impaired (an input feed is unavailable; the check cannot be evaluated)"
    else:
        head = f"Complacency active: {reason}"
        event = "complacency active (SKEW > 140 and VIX < 17)"
    title = f"[complacency] {head} — session {snap['session']}"
    body = "\n".join([
        f"**Event:** {event}",
        f"**Which:** {kind.upper()}",
        *_session_lines(snap),
        "",
        "| metric | value |",
        "|---|---|",
        f"| SKEW | {fmt(as_float(it['skew']), 1)} ({it['skew_source'] or 'n/a'}) |",
        f"| VIX | {fmt(as_float(it['vix_now']), 2)} |",
        f"| impaired checks | {', '.join(snap['impaired_checks']) or 'none'} |",
        f"| regime_indicators complacency_flag | {snap['regime_complacency_flag']} |",
        f"| source | {snap['compl_source']} |",
        f"| regime | {snap['served_label']} (R_full {fmt(snap['r_full'])}) |",
        "",
        f"Previous state: complacency {prev.get('kind') or 'inactive, not impaired'} "
        f"(session {prev.get('session') or 'n/a'}).",
        "",
        f"Dashboard: {dash}",
        "",
        FOOTER,
    ])
    return title, body


CLOSED_BY = "Closed automatically by scripts/signal_alerts.py."


# ─────────────────────────────────────────────────────────────────────
# state
# ─────────────────────────────────────────────────────────────────────
def fresh_state(snap: dict) -> dict:
    lab = snap["served_label"]
    return {
        "cadence": "daily",
        "session_date": snap["session"],
        "as_of": snap["as_of"],
        "updated": None,
        "schema": SCHEMA,
        "regime": {"label": lab if lab in LEVELS else None,
                   "served_label": lab, "R_full": snap["r_full"], "session": snap["session"]},
        "shock": {"active": snap["shock_active"], "reasons": snap["shock_reasons"],
                  "session": snap["session"]},
        "complacency": {"kind": snap["compl_kind"], "reason": snap["compl_reason"],
                        "session": snap["session"]},
        "intraday": {"session_date": snap["intraday"]["session_date"],
                     "timestamp": snap["intraday"]["timestamp"]},
        "issues": {e: None for e in EVENTS},
        "last_opened": {e: None for e in EVENTS},
        "last_run": {"session_date": snap["session"], "mode": None, "actions": []},
    }


def load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict) or "regime" not in st:
            raise ValueError("not an alert state")
        for key in ("issues", "last_opened"):
            st.setdefault(key, {})
            for e in EVENTS:
                st[key].setdefault(e, None)
        return st
    except Exception as e:
        print(f"  WARNING: state file {path} unreadable ({e}) — re-recording state, no alerts this run")
        return None


def write_state(path: Path, state: dict, previous: dict | None, allowed: bool) -> None:
    def strip(d):
        return {k: v for k, v in d.items() if k != "updated"}
    changed = previous is None or strip(previous) != strip(state)
    if not allowed:
        print(f"  state file: not written ({'changed' if changed else 'unchanged'}; dry-run without --write-state)")
        return
    if not changed:
        print(f"  state file: unchanged, not rewritten ({path})")
        return
    state["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    print(f"  state file: written {path}")


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="order item 4.3 — signal alerts as GitHub issues")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--state-file", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be created/closed; no gh call (default outside GitHub Actions)")
    ap.add_argument("--write-state", action="store_true",
                    help="write the state file (dry-run only writes it with this flag)")
    args = ap.parse_args(argv)

    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    dry_run = args.dry_run or not in_ci
    write_allowed = args.write_state or not dry_run
    data_dir: Path = args.data_dir
    state_path: Path = args.state_file or (data_dir / STATE_FILENAME)
    slug = repo_slug()
    dash = dashboard_url(slug)
    gh = GitHub(dry_run, slug)

    print(f"signal_alerts: mode={'DRY-RUN' if dry_run else 'LIVE'} data={data_dir} "
          f"state={state_path} repo={slug or 'unknown'}")

    snap = snapshot(data_dir)
    if snap is None:
        print("  regime_indicators.json missing — nothing to compare; exit 0")
        return 0
    if snap["served_label"] is None and snap["r_full"] is None:
        print("  regime_indicators.json carries no regime/R_full — nothing to compare; exit 0")
        return 0
    it = snap["intraday"]
    print(f"  session {snap['session']} | regime {snap['served_label']} (R_full {fmt(snap['r_full'])}) | "
          f"shock {'ACTIVE' if snap['shock_active'] else 'inactive'} | "
          f"complacency {snap['compl_kind'] or 'none'} | intraday session {it['session_date']} "
          f"{'(missing)' if not it['present'] else ''}")

    prev = load_state(state_path)
    if prev is None:
        state = fresh_state(snap)
        state["last_run"]["mode"] = "dry-run" if dry_run else "live"
        state["last_run"]["actions"] = ["first run: state recorded, no alerts"]
        if write_allowed:
            write_state(state_path, state, None, True)
            print("first run: state recorded, no alerts")
        else:
            print("first run: no previous state — would record state, no alerts (dry-run without --write-state, nothing written)")
        return 0

    state = json.loads(json.dumps(prev))          # working copy
    state["cadence"] = "daily"
    state["session_date"] = snap["session"]
    state["as_of"] = snap["as_of"]
    state["schema"] = SCHEMA
    state["intraday"] = {"session_date": it["session_date"], "timestamp": it["timestamp"]}
    actions: list[str] = []
    session = snap["session"]

    def cap_ok(event: str) -> bool:
        last = state["last_opened"].get(event)
        if last == session:
            print(f"  [{event}] suppressed: an issue was already opened for session {session} "
                  f"(at most one per event type per session)")
            actions.append(f"[{event}] suppressed by per-session cap ({session})")
            return False
        return True

    def open_issue(event: str, title: str, body: str) -> dict | None:
        """Per-session cap + reuse of an existing open issue, then create."""
        if not cap_ok(event):
            return None
        existing = gh.list_open(event)
        if existing:
            rec = {"number": existing[0].get("number"), "url": existing[0].get("url"), "dry_run": False}
            print(f"  [{event}] open issue #{rec['number']} already carries {LABELS[event][0]} — "
                  f"reused, not duplicated; commenting with the new values")
            gh.comment(event, rec, f"**{title}**\n\n{body}")
            rec["reused"] = True
            return rec
        rec = gh.create(event, title, body)
        if rec is not None:
            rec["opened_session"] = session
            state["last_opened"][event] = session
        return rec

    # ── regime ─────────────────────────────────────────────────────────
    preg = state["regime"]
    prev_label = preg.get("label")
    alert_label, transition, note = resolve_regime(prev_label, snap["served_label"], snap["r_full"])
    print(f"  [regime] alert state {prev_label} (R_full {fmt(preg.get('R_full'))}) -> served "
          f"{snap['served_label']} (R_full {fmt(snap['r_full'])})"
          + (f": {note}" if note else ": no change"))
    if note and not transition:
        actions.append(f"[regime] {note}")
    open_reg = state["issues"].get("regime")
    advance_regime = True
    if transition:
        if open_reg and open_reg.get("from") == alert_label:
            comment = (f"Reverted: regime label back to {alert_label} (R_full {fmt(snap['r_full'])}; {note}) "
                       f"— session {session}. Was {open_reg.get('to')} (R_full {fmt(open_reg.get('R_full'))}) "
                       f"when opened (session {open_reg.get('opened_session')}). {CLOSED_BY}")
            print(f"  [regime] REVERT {open_reg.get('to')} -> {alert_label}: closing open issue")
            if gh.close("regime", open_reg, comment):
                state["issues"]["regime"] = None
                actions.append(f"[regime] closed (reverted to {alert_label})")
            else:
                advance_regime = False
        else:
            if open_reg:
                comment = (f"Superseded: regime moved on to {alert_label} (R_full {fmt(snap['r_full'])}; {note}) "
                           f"— session {session}; a new issue tracks that transition. "
                           f"Was {open_reg.get('to')} (R_full {fmt(open_reg.get('R_full'))}). {CLOSED_BY}")
                print(f"  [regime] {open_reg.get('to')} -> {alert_label} while an issue is open: closing it as superseded")
                if gh.close("regime", open_reg, comment):
                    state["issues"]["regime"] = None
                    actions.append(f"[regime] closed (superseded by {alert_label})")
            print(f"  [regime] TRANSITION {prev_label} -> {alert_label}: opening issue")
            title, body = regime_issue(snap, {**preg, "label": prev_label}, note, dash)
            rec = open_issue("regime", title, body)
            if rec is not None:
                rec.update({"from": prev_label, "to": alert_label, "R_full": snap["r_full"], "session": session})
                state["issues"]["regime"] = rec
                actions.append(f"[regime] {'would open' if dry_run else 'opened'} {prev_label} -> {alert_label}")
            elif state["last_opened"].get("regime") != session:
                advance_regime = False             # create failed: retry next run
    if advance_regime:
        state["regime"] = {"label": alert_label, "served_label": snap["served_label"],
                           "R_full": snap["r_full"], "session": session}

    # ── shock ──────────────────────────────────────────────────────────
    psh = state["shock"]
    was, now = bool(psh.get("active")), snap["shock_active"]
    advance_shock = True
    open_sh = state["issues"].get("shock")
    if now and not was:
        print(f"  [shock] inactive -> ACTIVE ({'; '.join(snap['shock_reasons']) or 'no reasons'}): opening issue")
        title, body = shock_issue(snap, psh, dash)
        rec = open_issue("shock", title, body)
        if rec is not None:
            rec.update({"reasons": snap["shock_reasons"], "session": session})
            state["issues"]["shock"] = rec
            actions.append(f"[shock] {'would open' if dry_run else 'opened'}")
        elif state["last_opened"].get("shock") != session:
            advance_shock = False
    elif was and not now:
        comment = (f"Reverted: shock_active false — session {session} (intraday snapshot {it['timestamp']} UTC, "
                   f"session {it['session_date']}). VIX {fmt(as_float(it['vix_now']), 2)} "
                   f"({fmt(as_float(it['vix_change_pct']), 1, '%', sign=True)}), "
                   f"SPX {fmt(as_float(it['spx_change_pct']), 2, '%', sign=True)}, "
                   f"VIX3M {fmt(as_float(it['vix3m']), 2)}, HY credit (dur-adj) "
                   f"{fmt(as_float(it['credit_change_dur_adj_pct']), 2, '%', sign=True)}. "
                   f"Was: {'; '.join(psh.get('reasons') or []) or 'n/a'} (session {psh.get('session')}). {CLOSED_BY}")
        print("  [shock] ACTIVE -> inactive: closing open issue")
        if gh.close("shock", open_sh, comment):
            state["issues"]["shock"] = None
            actions.append("[shock] closed (reverted)")
        else:
            advance_shock = False
    else:
        print(f"  [shock] {'ACTIVE' if now else 'inactive'} (unchanged)")
    if advance_shock:
        state["shock"] = {"active": now, "reasons": snap["shock_reasons"], "session": session}

    # ── complacency ────────────────────────────────────────────────────
    pco = state["complacency"]
    pk, ck = pco.get("kind"), snap["compl_kind"]
    advance_compl = True
    open_co = state["issues"].get("complacency")
    if ck and not pk:
        print(f"  [complacency] none -> {ck.upper()}: opening issue")
        title, body = complacency_issue(snap, pco, dash)
        rec = open_issue("complacency", title, body)
        if rec is not None:
            rec.update({"kind": ck, "session": session})
            state["issues"]["complacency"] = rec
            actions.append(f"[complacency] {'would open' if dry_run else 'opened'} ({ck})")
        elif state["last_opened"].get("complacency") != session:
            advance_compl = False
    elif pk and not ck:
        comment = (f"Reverted: complacency inactive and the check is not impaired — session {session} "
                   f"(intraday snapshot {it['timestamp']} UTC). SKEW {fmt(as_float(it['skew']), 1)}, "
                   f"VIX {fmt(as_float(it['vix_now']), 2)}, impaired checks: "
                   f"{', '.join(snap['impaired_checks']) or 'none'}. Was {pk} "
                   f"({pco.get('reason') or 'n/a'}; session {pco.get('session')}). {CLOSED_BY}")
        print(f"  [complacency] {pk.upper()} -> none: closing open issue")
        if gh.close("complacency", open_co, comment):
            state["issues"]["complacency"] = None
            actions.append("[complacency] closed (reverted)")
        else:
            advance_compl = False
    elif pk and ck and pk != ck:
        print(f"  [complacency] {pk.upper()} -> {ck.upper()} while the issue stays open: commenting")
        gh.comment("complacency", open_co,
                   f"Complacency state changed {pk} → {ck} — session {session}: "
                   f"{snap['compl_reason'] or 'no reason recorded'} (SKEW {fmt(as_float(it['skew']), 1)}, "
                   f"VIX {fmt(as_float(it['vix_now']), 2)}, impaired checks: "
                   f"{', '.join(snap['impaired_checks']) or 'none'}). Issue stays open until both clear.")
        if open_co:
            open_co["kind"] = ck
        actions.append(f"[complacency] kind changed {pk} -> {ck}")
    else:
        print(f"  [complacency] {ck or 'none'} (unchanged)")
    if advance_compl:
        state["complacency"] = {"kind": ck, "reason": snap["compl_reason"], "session": session}

    # ── persist ────────────────────────────────────────────────────────
    state["last_run"] = {"session_date": session, "mode": "dry-run" if dry_run else "live",
                         "actions": actions or ["no state change"]}
    write_state(state_path, state, prev, write_allowed)
    print("summary: " + ("; ".join(gh.log) if gh.log else "no issues to create or close"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
