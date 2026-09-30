#!/usr/bin/env python3
"""compute_lens.py — per-stock options features, nightly → data/options/lens.json (Phase 2).

For each analyzed name in the session's chain vintage: volatility pricing (ATM implied
volatility at the nearest expiries to 30 and 90 days, realized volatility over 21 and 63
sessions, the two gaps, a state label), the term structure, the event (next earnings, the
event-implied move isolated from the term structure, the historical reaction distribution,
the event premium), the skew, positioning (descriptive only), and dealer gamma (descriptive,
assumption-flagged, collapsed by default). IV rank and percentile come from the archive and
are null until it holds enough sessions.

Everything is descriptive. No panel built from this file emits a directional recommendation.

Definitions (also written into the file):
  * sessions to expiry are the sessions strictly after the snapshot session (its own close,
    minutes away at 15:45, is not a session of variance); the same count feeds the inversion;
  * ATM at an expiry = the strike nearest spot, IV = mean of the call and put inversions;
  * FRONT = the expiry nearest 30 calendar days, BACK = nearest 90 (the order's "nearest
    expiries"); the calendar-interpolated 30/90-day values are recorded beside them;
  * state: cheap if IV30 < RV21 and IV30 < RV63; rich if above both; mixed otherwise;
  * event-implied move (order 30-Sept, C1, the bracketing method): with PRE the last expiry
    before the release and POST the first expiry after it, event variance = post total
    variance − pre total variance − base variance at the pre-expiry IV over the non-event
    sessions between them; without a pre-event expiry, the post-event expiry against a later
    expiry free of a further release (forward variance as the base), flagged as a fallback;
  * skew = IV(put, K = 0.9 spot) − IV(call, K = 1.1 spot) at the front expiry, strikes
    interpolated; the 25-delta risk reversal is recorded beside it;
  * dealer gamma under the convention dealers are long calls, short puts.
"""
from __future__ import annotations
import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import options_common as oc
from trading_calendar import last_completed_session, now_et

warnings.filterwarnings("ignore")
OUT = oc.OPT / "lens.json"
GAMMA_MAX_DAYS = 90
ARCHIVE_MIN_SESSIONS = 60        # IV rank/percentile need at least this many archived sessions


def log(m: str) -> None:
    print(f"[compute_lens] {m}", flush=True)


def r4(x, nd=4):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, nd)


# ── chain helpers ────────────────────────────────────────────────────────
def atm_iv_at(df: pd.DataFrame, expiry: str, spot: float) -> tuple[float | None, float | None]:
    """(ATM IV, ATM strike) at an expiry: strike nearest spot, mean of call and put IV."""
    e = df[(df.expiry == expiry) & df.iv.notna()]
    if e.empty:
        return None, None
    k = float(e.iloc[(e.strike - spot).abs().argsort().iloc[0]].strike)
    ivs = e[e.strike == k].iv.astype(float).tolist()
    return (float(np.mean(ivs)) if ivs else None), k


def iv_at_strike(df: pd.DataFrame, expiry: str, cp: str, K: float) -> float | None:
    """IV at strike K by linear interpolation over the expiry's valid IVs for one side."""
    e = df[(df.expiry == expiry) & (df.cp == cp) & df.iv.notna()].sort_values("strike")
    if len(e) < 2:
        return None
    ks, vs = e.strike.astype(float).values, e.iv.astype(float).values
    if K < ks[0] or K > ks[-1]:
        return None
    return float(np.interp(K, ks, vs))


def iv_at_delta(df: pd.DataFrame, expiry: str, cp: str, target: float) -> float | None:
    e = df[(df.expiry == expiry) & (df.cp == cp) & df.iv.notna() & df.delta.notna()]
    if len(e) < 2:
        return None
    e = e.assign(d=e.delta.astype(float)).sort_values("d")
    ds, vs = e.d.values, e.iv.astype(float).values
    if target < ds[0] or target > ds[-1]:
        return None
    return float(np.interp(target, ds, vs))


def max_pain(e: pd.DataFrame) -> float | None:
    """Strike minimizing the total intrinsic value of open interest at expiry."""
    if e.empty:
        return None
    ks = np.sort(e.strike.unique().astype(float))
    calls = e[e.cp == "c"]; puts = e[e.cp == "p"]
    best, best_v = None, None
    for S in ks:
        v = float((calls.open_interest * np.maximum(0.0, S - calls.strike)).sum() + (puts.open_interest * np.maximum(0.0, puts.strike - S)).sum())
        if best_v is None or v < best_v:
            best, best_v = float(S), v
    return best


def top_oi(e: pd.DataFrame, cp: str, n: int = 3) -> list[dict]:
    s = e[e.cp == cp].sort_values("open_interest", ascending=False).head(n)
    return [{"strike": float(r.strike), "open_interest": int(r.open_interest)} for r in s.itertuples()]


def dealer_gamma(df: pd.DataFrame, spot: float, r: float, q: float) -> dict:
    """Net gamma exposure per 1% move at spot (dollars) and the flip level, under the
    convention that dealers are long calls and short puts. Descriptive; not validated."""
    e = df[df.iv.notna() & (df.open_interest > 0)].copy()
    sess = pd.Timestamp(df.expiry.min()) if len(df) else None
    if e.empty:
        return {"per_1pct": None, "flip_level": None, "n_contracts": 0}
    e = e[e.sessions_to_expiry <= int(GAMMA_MAX_DAYS * 252 / 365) + 1]
    def net_at(S):
        tot = 0.0
        for row in e.itertuples():
            g = oc.bs_gamma(S, float(row.strike), float(row.T), r, q, float(row.iv))
            if g is None:
                continue
            sign = 1.0 if row.cp == "c" else -1.0
            tot += sign * g * int(row.open_interest) * 100 * S * S * 0.01
        return tot
    at_spot = net_at(spot)
    grid = np.linspace(0.85 * spot, 1.15 * spot, 31)
    vals = [net_at(S) for S in grid]
    flip = None
    for i in range(1, len(grid)):
        if (vals[i - 1] <= 0 < vals[i]) or (vals[i - 1] >= 0 > vals[i]):
            x0, x1, y0, y1 = grid[i - 1], grid[i], vals[i - 1], vals[i]
            flip = float(x0 + (0 - y0) * (x1 - x0) / (y1 - y0)) if y1 != y0 else float(x0)
            break
    return {"per_1pct": round(at_spot, 0), "flip_level": r4(flip, 2), "flip_vs_spot": r4(flip / spot - 1.0) if flip else None,
            "n_contracts": int(len(e)), "expiries_within_days": GAMMA_MAX_DAYS}


# ── per-name lens ────────────────────────────────────────────────────────
def name_lens(tk: str, df: pd.DataFrame, meta_tk: dict, session: str, closes: pd.Series | None,
              earn: dict | None, r: float, archive: dict) -> dict:
    spot = float(meta_tk["spot"]); q = float(meta_tk.get("q") or 0.0)
    sess = pd.Timestamp(session)
    expiries = sorted(df.expiry.unique().tolist())
    cal_days = {e: (pd.Timestamp(e) - sess).days for e in expiries}
    front = oc.pick_expiry(expiries, session, oc.FRONT_DAYS); back = oc.pick_expiry(expiries, session, oc.BACK_DAYS)
    atm = {e: atm_iv_at(df, e, spot) for e in expiries}
    iv_front, k_front = atm.get(front, (None, None)); iv_back, _ = atm.get(back, (None, None))
    pts = [(cal_days[e], atm[e][0]) for e in expiries if atm[e][0] is not None]
    iv30_interp, iv90_interp = oc.interp_days(pts, 30), oc.interp_days(pts, 90)
    warnings_: list[str] = []
    impaired = (meta_tk.get("front_live_quote_share") is None) or (meta_tk["front_live_quote_share"] < oc.LIVE_QUOTE_BAR)
    if impaired:
        warnings_.append(f"front-expiry live-quote share {meta_tk.get('front_live_quote_share')} below {oc.LIVE_QUOTE_BAR} — column reads impaired")

    # realized volatility
    rv21 = oc.realized_vol(closes, 21) if closes is not None else None
    rv63 = oc.realized_vol(closes, 63) if closes is not None else None
    state = None
    if iv_front is not None and rv21 is not None and rv63 is not None:
        state = "cheap" if (iv_front < rv21 and iv_front < rv63) else ("rich" if (iv_front > rv21 and iv_front > rv63) else "mixed")

    # IV rank / percentile from the archive (the system's own history)
    hist = archive.get(tk) or []
    if len(hist) >= ARCHIVE_MIN_SESSIONS and iv_front is not None:
        arr = np.array(hist, dtype=float)
        iv_rank = float((iv_front - arr.min()) / (arr.max() - arr.min())) if arr.max() > arr.min() else None
        iv_pct = float((arr < iv_front).mean())
        rank_note = f"archive of {len(hist)} sessions"
    else:
        iv_rank = iv_pct = None
        rank_note = f"null until the archive holds {ARCHIVE_MIN_SESSIONS} sessions (has {len(hist)}); a purchased history would supply it earlier (item 1.4)"

    # event
    nxt = (earn or {}).get("next") or {}
    ev_date = nxt.get("date"); tod = nxt.get("time_of_day")
    event: dict = {"next_earnings": ev_date, "time_of_day": tod, "days_to": None, "sessions_to": None,
                   "expiry_after": None, "implied_move": None, "implied_move_reason": None}
    if ev_date:
        ed = pd.Timestamp(ev_date)
        event["days_to"] = int((ed - sess).days)
        event["sessions_to"] = oc.sessions_between(sess, ed) if ed > sess else 0
        # Order 30-Sept C1 — the bracketing method. The 26-Sept specification subtracted base
        # variance at the BACK-month IV from the first post-event expiry, which collapses toward
        # zero whenever the event is weeks away or the back month carries term premium (GEV read
        # 2.9%, NVDA 2.2%). Correct method: the last expiry BEFORE the release (contains no event)
        # and the first expiry AFTER it (contains it); event variance = post total variance − pre
        # total variance − base variance at the pre-expiry IV over the non-event sessions between
        # the two expiries. An expiry on the release date expires at the close: it precedes an
        # after-close release and contains a before-open one. Without a pre-event expiry, the
        # fallback compares the post-event expiry with a later expiry that contains no further
        # release (forward variance between them = the base per session), and is flagged.
        live = [e for e in expiries if oc.sessions_to_expiry(session, e) >= 1]
        after = [e for e in live if (pd.Timestamp(e) > ed) or (tod == "before_open" and pd.Timestamp(e) >= ed)]
        before = [e for e in live if (pd.Timestamp(e) < ed) or (tod == "after_close" and pd.Timestamp(e) == ed)]
        e_post = after[0] if after else None
        e_pre = before[-1] if before else None
        event["expiry_after"] = e_post
        event["expiry_before"] = e_pre
        event["fallback"] = False
        if e_post is None:
            event["implied_move_reason"] = "no listed expiry after the release"
        else:
            iv_post, _ = atm.get(e_post, (None, None))
            n_post = oc.sessions_to_expiry(session, e_post)
            if iv_post is None or n_post < 1:
                event["implied_move_reason"] = "no ATM IV at the first expiry after the release"
            elif e_pre is not None and atm.get(e_pre, (None, None))[0] is not None:
                iv_pre, _ = atm.get(e_pre, (None, None))
                n_pre = oc.sessions_to_expiry(session, e_pre)
                non_event = max(0, n_post - n_pre - 1)
                v_post = iv_post ** 2 * n_post / 252.0
                v_pre = iv_pre ** 2 * n_pre / 252.0
                ev_var = v_post - v_pre - iv_pre ** 2 * non_event / 252.0
                event.update({"iv_post": r4(iv_post), "sessions_to_post": n_post, "iv_pre": r4(iv_pre), "sessions_to_pre": n_pre,
                              "non_event_sessions": non_event, "event_variance": r4(ev_var, 6),
                              "method": "bracketing: post total variance − pre total variance − IV_pre²·(non-event sessions)/252; "
                                        "pre = last expiry before the release, post = first expiry after it; sessions strictly after the snapshot session"})
                if ev_var > 0:
                    event["implied_move"] = float(np.sqrt(ev_var))
                else:
                    event["implied_move_reason"] = "event variance not positive under the bracketing method (the pre-expiry's variance and base exceed the post-expiry's)"
            else:
                # fallback: forward variance between the post-event expiry and a later expiry that
                # contains no further release (the next release is assumed no sooner than 80
                # calendar days after this one); prefer a reference at least five sessions later.
                cutoff = ed + pd.Timedelta(days=80)
                refs = [e for e in live if pd.Timestamp(e) > pd.Timestamp(e_post) and pd.Timestamp(e) <= cutoff and atm.get(e, (None, None))[0] is not None]
                far = [e for e in refs if oc.sessions_to_expiry(session, e) - n_post >= 5]
                e_ref = far[0] if far else (refs[-1] if refs else None)
                event["fallback"] = True
                event["fallback_reason"] = ("no listed expiry before the release" if e_pre is None else "no ATM IV at the expiry before the release")
                if e_ref is None:
                    event["implied_move_reason"] = "fallback impossible: no later expiry free of a further release with an ATM IV"
                else:
                    iv_ref, _ = atm.get(e_ref, (None, None))
                    n_ref = oc.sessions_to_expiry(session, e_ref)
                    v_post = iv_post ** 2 * n_post / 252.0
                    v_ref = iv_ref ** 2 * n_ref / 252.0
                    base = (v_ref - v_post) / max(1, n_ref - n_post)          # forward variance per session
                    ev_var = v_post - base * max(0, n_post - 1)
                    event.update({"iv_post": r4(iv_post), "sessions_to_post": n_post, "reference_expiry": e_ref, "iv_reference": r4(iv_ref),
                                  "sessions_to_reference": n_ref, "base_variance_per_session": r4(base, 6), "event_variance": r4(ev_var, 6),
                                  "method": "fallback (no pre-event expiry): base per session = forward variance between the post-event expiry and a "
                                            "later expiry free of a further release; event variance = post total variance − base·(sessions to post − 1)"})
                    if base <= 0:
                        event["implied_move_reason"] = "fallback base not positive (the reference expiry's total variance is below the post-event expiry's)"
                    elif ev_var > 0:
                        event["implied_move"] = float(np.sqrt(ev_var))
                    else:
                        event["implied_move_reason"] = "event variance not positive under the fallback"
            # the superseded 26-Sept figure, kept beside the new one for the transition
            if iv_back is not None and iv_post is not None and n_post >= 1:
                old = iv_post ** 2 * n_post / 252.0 - iv_back ** 2 * max(0, n_post - 1) / 252.0
                event["superseded_26sept_method"] = {"implied_move": r4(float(np.sqrt(old))) if old > 0 else None, "base_iv_back": r4(iv_back),
                                                     "method": "sqrt(IV_E1²·n/252 − IV_back²·(n−1)/252) — replaced 30-Sept (C1)"}
    # historical reaction distribution
    hx = (earn or {}).get("history") or []
    st = (earn or {}).get("stats") or {}
    ab = np.array([abs(h["reaction"]) for h in hx]) if hx else np.array([])
    im = event["implied_move"]
    hist_block = {"n": int(len(ab)), "mean_abs": r4(st.get("mean_abs")), "median_abs": r4(st.get("median_abs")),
                  "max_abs": r4(st.get("max_abs")), "max_date": st.get("max_date"),
                  "n_exceeding_implied": int((ab > im).sum()) if (im is not None and len(ab)) else None,
                  "share_exceeding_implied": r4(float((ab > im).mean())) if (im is not None and len(ab)) else None,
                  "last8": {"n": int(min(8, len(ab))), "median_abs": r4(st.get("median_abs_last8")), "mean_abs": r4(st.get("mean_abs_last8")),
                            "n_exceeding_implied": int((ab[-8:] > im).sum()) if (im is not None and len(ab)) else None}}
    event["history"] = hist_block
    event["event_premium"] = r4(im - float(st["median_abs"])) if (im is not None and st.get("median_abs") is not None) else None

    # term structure
    term = {"front_expiry": front, "back_expiry": back, "front_iv": r4(iv_front), "back_iv": r4(iv_back),
            "front_minus_back": r4(iv_front - iv_back) if (iv_front is not None and iv_back is not None) else None,
            "inverted": bool(iv_front > iv_back) if (iv_front is not None and iv_back is not None) else None, "reason": None}
    if term["inverted"] and ev_date and front and pd.Timestamp(ev_date) <= pd.Timestamp(front):
        term["reason"] = f"earnings {ev_date} falls inside the front tenor ({front})"

    # skew at the front expiry
    put10 = iv_at_strike(df, front, "p", 0.9 * spot) if front else None
    call10 = iv_at_strike(df, front, "c", 1.1 * spot) if front else None
    put25 = iv_at_delta(df, front, "p", -0.25) if front else None
    call25 = iv_at_delta(df, front, "c", 0.25) if front else None
    skew = {"expiry": front, "put_10pct_otm_iv": r4(put10), "call_10pct_otm_iv": r4(call10),
            "skew": r4(put10 - call10) if (put10 is not None and call10 is not None) else None,
            "rr25": r4(put25 - call25) if (put25 is not None and call25 is not None) else None,
            "put_25d_iv": r4(put25), "call_25d_iv": r4(call25),
            "change_5s": None, "change_5s_note": "null until the archive holds six sessions"}
    sk_hist = archive.get(f"{tk}:skew") or []
    if len(sk_hist) >= 6 and skew["skew"] is not None:
        skew["change_5s"] = r4(skew["skew"] - sk_hist[-6]); skew["change_5s_note"] = None

    # positioning at the front expiry
    fe = df[df.expiry == front] if front else df.iloc[0:0]
    poi, coi = int(fe[fe.cp == "p"].open_interest.sum()), int(fe[fe.cp == "c"].open_interest.sum())
    mp = max_pain(fe)
    positioning = {"expiry": front, "put_oi": poi, "call_oi": coi, "put_call_oi_ratio": r4(poi / coi, 3) if coi else None,
                   "max_pain": mp, "max_pain_vs_spot": r4(mp / spot - 1.0) if mp else None,
                   "top_oi_calls": top_oi(fe, "c"), "top_oi_puts": top_oi(fe, "p"),
                   "note": "descriptive only; never an input"}

    gamma = dealer_gamma(df, spot, r, q)
    gamma.update({"convention": "dealers long calls, short puts",
                  "caveat": ("sign depends on who holds the calls; for names with heavy speculative call buying the "
                             "convention is likely reversed; not validated"), "collapsed_by_default": True})

    # Roles follow the CURRENT holdings and board (the vintage's roles are what they were at the
    # snapshot; a name sold since must not read "held" on the event board or the hedge cards).
    cur_roles = oc.analyzed_universe()
    roles_now = cur_roles.get(tk, [])
    return {
        "roles": roles_now, "roles_at_snapshot": meta_tk.get("roles", []),
        "spot": r4(spot, 2), "spot_source": meta_tk.get("spot_source"),
        "impaired": bool(impaired), "front_live_quote_share": r4(meta_tk.get("front_live_quote_share")),
        "volatility": {"iv30": r4(iv_front), "iv30_expiry": front, "iv30_days": cal_days.get(front), "atm_strike_30": k_front,
                       "iv90": r4(iv_back), "iv90_expiry": back, "iv90_days": cal_days.get(back),
                       "iv30_interp_calendar": r4(iv30_interp), "iv90_interp_calendar": r4(iv90_interp),
                       "rv21": r4(rv21), "rv63": r4(rv63),
                       "gap_iv_rv21": r4(iv_front - rv21) if (iv_front is not None and rv21 is not None) else None,
                       "gap_iv_rv63": r4(iv_front - rv63) if (iv_front is not None and rv63 is not None) else None,
                       "state": state, "iv_rank": r4(iv_rank), "iv_percentile": r4(iv_pct), "rank_note": rank_note},
        "term_structure": term, "event": event, "skew": skew, "positioning": positioning, "dealer_gamma": gamma,
        "atm_by_expiry": [{"expiry": e, "days": cal_days[e], "sessions": int(df[df.expiry == e].sessions_to_expiry.iloc[0]), "atm_iv": r4(atm[e][0]), "atm_strike": atm[e][1]} for e in expiries],
        "warnings": warnings_,
    }


def build_archive(sessions: list[str], names: list[str]) -> dict:
    """Front-tenor ATM IV and skew per name across the archived sessions (for rank/percentile
    and the 5-session skew change). Cheap while the archive is small."""
    arch: dict = {}
    for s in sessions[-300:]:
        meta = oc.vintage_meta(s)
        for tk in names:
            p = oc.vintage_path(s, tk)
            if not p.exists() or tk not in meta.get("tickers", {}):
                continue
            df = pd.read_parquet(p, columns=["expiry", "cp", "strike", "iv", "delta"])
            spot = float(meta["tickers"][tk]["spot"]); exps = sorted(df.expiry.unique().tolist())
            front = oc.pick_expiry(exps, s, oc.FRONT_DAYS)
            iv, _ = atm_iv_at(df, front, spot) if front else (None, None)
            if iv is not None:
                arch.setdefault(tk, []).append(iv)
            p10 = iv_at_strike(df, front, "p", 0.9 * spot) if front else None
            c10 = iv_at_strike(df, front, "c", 1.1 * spot) if front else None
            if p10 is not None and c10 is not None:
                arch.setdefault(f"{tk}:skew", []).append(p10 - c10)
    return arch


def build(session: str | None = None) -> dict:
    sessions = oc.vintage_sessions()
    if not sessions:
        raise SystemExit("[compute_lens] no chain vintage on disk — run snapshot_chains.py first")
    session = session or sessions[-1]
    meta = oc.vintage_meta(session)
    vint = oc.load_vintage(session)
    names = sorted(vint)
    r = float(meta.get("risk_free") or oc.risk_free()[0])
    cl, prov = oc.closes(names, session)
    earn = json.loads((oc.OPT / "earnings_reactions.json").read_text()).get("names", {}) if (oc.OPT / "earnings_reactions.json").exists() else {}
    archive = build_archive(sessions, names)
    out_names, warns = {}, []
    for tk in names:
        try:
            out_names[tk] = name_lens(tk, vint[tk], meta["tickers"][tk], session, cl[tk] if tk in cl.columns else None, earn.get(tk), r, archive)
        except Exception as e:
            warns.append(f"{tk}: {type(e).__name__}: {str(e)[:80]}")
    return {
        "cadence": "daily", "session_date": session, "as_of": now_et().date().isoformat(),
        "computed_at": now_et().isoformat(timespec="seconds"),
        "snapshot_kind": meta.get("snapshot_kind"), "pulled_at": meta.get("pulled_at"), "risk_free": r,
        "archive_sessions": len(sessions),
        "definitions": {
            "iv": "Black-Scholes inversion (Brent on [0.01, 5.0]) from bid-ask mids (else last, flagged); the provider's IV field is never used",
            "sessions_to_expiry": "trading sessions strictly after the snapshot session (the pull day's close, minutes away at 15:45, is not a session of variance); T = sessions/252, identical for the inversion and the event subtraction",
            "atm": "strike nearest spot; IV = mean of the call and put inversions",
            "tenors": "FRONT = expiry nearest 30 calendar days, BACK = nearest 90 (the order's 'nearest expiries'); calendar-interpolated values recorded beside them",
            "realized_vol": "std (ddof=1) of daily log returns × √252 over 21 and 63 sessions",
            "state": "cheap if IV30 < RV21 and RV63; rich if above both; mixed otherwise",
            "event_move": ("bracketing (order 30-Sept, C1): with PRE the last expiry before the release and POST the first after it, "
                           "event variance = IV_post²·n_post/252 − IV_pre²·n_pre/252 − IV_pre²·(n_post − n_pre − 1)/252, the move its square root; "
                           "an expiry on the release date precedes an after-close release and contains a before-open one; without a pre-event expiry the "
                           "fallback takes the base per session from the forward variance between POST and a later expiry free of a further release, flagged"),
            "skew": "IV(put, 0.9·spot) − IV(call, 1.1·spot) at the front expiry, interpolated in strike; 25-delta risk reversal beside it",
            "dealer_gamma": "Σ sign·Γ·OI·100·S²·1% over expiries within 90 days, dealers long calls / short puts — descriptive, not validated",
        },
        "closes_provenance": prov, "names": out_names, "warnings": warns,
        "note": "descriptive: what the options market prices about each name; no directional recommendation; options-derived return signals are registered candidates on the union universe only",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args()
    payload = build(args.session)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    log(f"wrote {OUT.relative_to(oc.REPO)}: {len(payload['names'])} names, session {payload['session_date']} ({payload['snapshot_kind']}); warnings {len(payload['warnings'])}")
    for w in payload["warnings"]:
        log(f"  WARN {w}")
    if args.do_print:
        for tk, n in payload["names"].items():
            v, e, t, p = n["volatility"], n["event"], n["term_structure"], n["positioning"]
            im = e.get("implied_move"); h = e.get("history", {})
            log(f"  {tk:5} spot {n['spot']:8} IV30 {v['iv30']} RV21 {v['rv21']} RV63 {v['rv63']} → {v['state']:5} | term {t['front_minus_back']} inv={t['inverted']} "
                f"| earn {e['next_earnings']} E1 {e['expiry_after']} move {None if im is None else round(im*100,2)}% hist med {None if h.get('median_abs') is None else round(h['median_abs']*100,2)}% exceed {h.get('n_exceeding_implied')}/{h.get('n')} "
                f"| skew {n['skew']['skew']} | P/C {p['put_call_oi_ratio']} maxpain {p['max_pain']}{' | IMPAIRED' if n['impaired'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
