#!/usr/bin/env python3
"""
entry_state_v1.py — the entry-state rules of 2 October 2026 (version 1), FROZEN.

Kept verbatim so the registered 2-Oct validation (reports/entry_state_validation_registration*_2026-10-02.md,
scripts/entry_state_validation.py) stays reproducible after the 6-Oct revision replaced these rules in
scripts/entry_state.py. Reads data/entry_state_config_2026-10-02.json (sha256 0f438215…, as registered).
Never edited; the nightly does not run it.

Original docstring follows.

The screen answers what is worth owning; this answers whether the tape confirms an entry now, and gives
every name a defined stop and a risk-budget size. Per name, nightly, parameters in
data/entry_state_config.json:

  trend gate   12-month return excluding the last month > 0 and close > 200-day average; else AVOID
  setup        close < MA20 - 1 ATR(14), or RSI(14) <= 40, or close in the lowest quarter of the 40-session
               range; absent: WAIT ("extended; buying strength")
  trigger      while the setup holds: close > prior session's high, or the first close back above the prior
               40-session low after a close below it (failed breakdown); setup without trigger: WATCH
  event gate   earnings within 20 sessions: READY-HALF (half size); else READY
  invalidation stop = max(40-session low - 1 ATR, 200-day average); a READY arms its stop; a later close below
               the armed stop is logged as a stop breach and the name re-evaluates to AVOID or WATCH
  size         shares = 0.5% x account / (entry - stop), halved at READY-HALF, capped so the name's post-entry
               share of book risk stays below 40%; the post-entry volatility, beta and largest risk share shown

DIAGNOSTIC until the registered validation (reports/entry_state_validation_registration_2026-10-02.md) reports.
Descriptive rule output: it states what the rule reads, not an instruction to trade.

Outputs: data/entry_state.json (every name in the union universe, the held names and the tier holdings; the
card names carry size and book effect), data/entry_state_log.jsonl (append-only transitions of the card names),
data/source/ohlc_daily.parquet (split-adjusted daily OHLC plus the adjusted close, about two years).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = HERE.parent
DATA = REPO / "data"
SOURCE = DATA / "source"
CONFIG = DATA / "entry_state_config_2026-10-02.json"   # version 1, frozen
OHLC = SOURCE / "ohlc_daily.parquet"
OUT = DATA / "entry_state.json"
LOG = DATA / "entry_state_log.jsonl"
STATES = ("AVOID", "WAIT", "WATCH", "READY", "READY-HALF")
KEEP_SESSIONS = 520


def log(m: str) -> None:
    print(f"[entry_state] {m}", flush=True)


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text())


# ── indicators (one ticker) ──────────────────────────────────────────────────────────────────
def indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """df: columns open, high, low, close (split-adjusted), index sessions ascending."""
    c, h, l = df["close"].astype(float), df["high"].astype(float), df["low"].astype(float)
    t, s, st, tg = cfg["trend"], cfg["setup"], cfg["stop"], cfg["trigger"]
    out = pd.DataFrame(index=df.index)
    out["close"], out["high"], out["low"] = c, h, l
    out["ma_short"] = c.rolling(s["ma_short"]).mean()
    out["ma50"] = c.rolling(50).mean()
    out["ma_long"] = c.rolling(t["ma_long"]).mean()
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    out["atr"] = tr.rolling(s["atr_sessions"]).mean()                          # simple mean of the true range
    d = c.diff()
    up, dn = d.clip(lower=0).rolling(s["rsi_sessions"]).mean(), (-d.clip(upper=0)).rolling(s["rsi_sessions"]).mean()
    out["rsi"] = np.where(dn == 0, 100.0, 100.0 - 100.0 / (1.0 + up / dn.replace(0, np.nan)))   # simple-average RSI
    out.loc[up.isna() | dn.isna(), "rsi"] = np.nan
    out["mom_12_1"] = c.shift(t["momentum_skip_sessions"]) / c.shift(t["momentum_lookback_sessions"]) - 1.0
    n = s["range_sessions"]
    out["range_hi"] = h.rolling(n).max()
    out["range_lo"] = l.rolling(n).min()
    out["prior_lo"] = l.shift(1).rolling(st["range_sessions"]).min()               # the 40-session low before today
    out["trend"] = (out["mom_12_1"] > 0) & (c > out["ma_long"])
    out["setup_atr"] = c < out["ma_short"] - s["atr_mult"] * out["atr"]
    out["setup_rsi"] = out["rsi"] <= s["rsi_max"]
    out["setup_range"] = c <= out["range_lo"] + s["range_quantile"] * (out["range_hi"] - out["range_lo"])
    out["setup"] = out["setup_atr"] | out["setup_rsi"] | out["setup_range"]
    out["trig_high"] = c > h.shift(1)
    out["stop"] = np.maximum(l.rolling(st["range_sessions"]).min() - st["atr_mult"] * out["atr"], out["ma_long"])
    # failed breakdown: a close below the prior 40-session low, then the first close back above that low
    lvl = np.full(len(c), np.nan); fb = np.zeros(len(c), dtype=bool)
    active, age = None, 0
    cv, plv = c.to_numpy(), out["prior_lo"].to_numpy()
    for i in range(len(cv)):
        if active is not None:
            age += 1
            if cv[i] > active:
                fb[i], lvl[i], active = True, active, None
                continue
            if age > tg["failed_breakdown_window_sessions"]:
                active = None
        if active is None and not math.isnan(plv[i]) and cv[i] < plv[i]:
            active, age = plv[i], 0
        lvl[i] = active if active is not None else np.nan
    out["trig_failed_breakdown"] = fb
    out["breakdown_level"] = lvl                       # the low a close must recover (while a breakdown is active)
    ready = ["close", "ma_long", "atr", "rsi", "mom_12_1", "range_lo", "stop"]
    out["complete"] = out[ready].notna().all(axis=1)
    return out


def sessions_until(d0: date, d1: date) -> int:
    """Trading sessions after d0 up to and including d1."""
    from trading_calendar import is_trading_day
    n, cur = 0, d0
    while cur < d1:
        cur = date.fromordinal(cur.toordinal() + 1)
        if is_trading_day(cur):
            n += 1
    return n


def evaluate(ind: pd.DataFrame, cfg: dict, earnings: list[date] | None = None, armed: dict | None = None,
             earnings_known: bool = True) -> pd.DataFrame:
    """Sequential state machine. `armed` = {"stop": x, "date": iso} carried from the previous run.
    The state is read from each session's conditions (the order's section 1); READY marks the trigger
    session. A trigger arms that session's stop; the armed stop is carried until a close falls below it (a
    stop breach: logged, the stop disarmed, the name re-evaluated to WATCH or AVOID), until the trend gate
    fails, or until a new trigger replaces it. (A persisting READY was tried and rejected: the order's
    reference reads Corpay WATCH on 1 Oct although it triggered six sessions earlier without a breach.)
    Returns one row per session: state, trigger kind, armed stop, breach."""
    ev = cfg["event"]
    rows, armed = [], dict(armed or {})
    earn = sorted(earnings or [])

    def gate(d0):
        nxt = next((e for e in earn if e > d0), None)
        sess = sessions_until(d0, nxt) if nxt else None
        return sess, (sess is not None and sess <= ev["earnings_sessions"])

    for ts, r in ind.iterrows():
        d0 = ts.date()
        rec = {"date": str(d0), "state": None, "trigger": None, "breach": False, "breach_stop": None,
               "armed_stop": armed.get("stop"), "armed_since": armed.get("date"), "earnings_in_sessions": None}
        if not r["complete"]:
            rec["state"] = None; rows.append(rec); continue
        if armed.get("stop") is not None and r["close"] < armed["stop"]:
            rec.update(breach=True, breach_stop=armed["stop"]); armed = {}
        if not r["trend"]:
            st, armed = "AVOID", {}
        elif not r["setup"]:
            st = "WAIT"
        elif r["trig_high"] or r["trig_failed_breakdown"]:
            kind = "close above the prior session's high" if r["trig_high"] else "failed breakdown recovered"
            sess, half = gate(d0)
            st = "READY-HALF" if half else "READY"
            rec.update(trigger=kind, earnings_in_sessions=sess)
            armed = {"stop": float(r["stop"]), "date": str(d0)}
        else:
            st = "WATCH"
        rec["state"] = st
        rec["armed_stop"], rec["armed_since"] = armed.get("stop"), armed.get("date")
        rows.append(rec)
    return pd.DataFrame(rows).set_index("date")


def transitions_of(ev: pd.DataFrame, prev: str | None = None) -> list[dict]:
    """Every state change in an evaluated series, and every stop breach, with its reason. `prev` is the
    state the series starts from (the previous run's), so a change on the first session is caught."""
    out = []
    for d, r in ev.iterrows():
        st = r["state"]
        if not isinstance(st, str):          # incomplete history: no state (None becomes NaN in the frame)
            continue
        if r["breach"]:
            out.append({"date": d, "from": prev, "to": st, "reason": f"stop breach (close below the armed stop {round(float(r['breach_stop']), 2)})"})
        elif prev is not None and st != prev:
            reason = (r["trigger"] if st.startswith("READY") else "trend gate failed" if st == "AVOID"
                      else "setup absent (extended)" if st == "WAIT" else "setup without trigger")
            out.append({"date": d, "from": prev, "to": st, "reason": reason})
        prev = st
    return out


# ── the OHLC store ───────────────────────────────────────────────────────────────────────────
def _yf_ohlc(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i + 50]
        try:
            d = yf.download(batch, start=start, progress=False, auto_adjust=False, group_by="ticker", threads=True)
        except Exception as e:  # noqa: BLE001
            log(f"batch {i}: {type(e).__name__}: {e}")
            continue
        for tk in batch:
            try:
                x = d[tk] if isinstance(d.columns, pd.MultiIndex) else d
                x = x.rename(columns=str.lower).rename(columns={"adj close": "adj_close"})
                x = x[["open", "high", "low", "close", "adj_close"]].dropna(subset=["close"])
                if len(x):
                    x.index = pd.to_datetime(x.index).tz_localize(None)
                    out[tk] = x
            except Exception:  # noqa: BLE001
                continue
    return out


def update_store(tickers: list[str], full_start: str = "2024-06-01") -> pd.DataFrame:
    """Long-format store (date, ticker, open, high, low, close, adj_close). New tickers get the full window;
    the rest the last 30 calendar days, overlaid. Non-session and partial-today rows are dropped."""
    from trading_calendar import is_trading_day, last_completed_session
    store = pd.read_parquet(OHLC) if OHLC.exists() else pd.DataFrame(columns=["ticker", "open", "high", "low", "close", "adj_close"])
    if len(store):
        store.index = pd.to_datetime(store.index)
    have = set(store["ticker"].unique()) if len(store) else set()
    new = [t for t in tickers if t not in have]
    old = [t for t in tickers if t in have]
    recent_start = (pd.Timestamp(last_completed_session()) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    got = {}
    if new:
        log(f"full history for {len(new)} new tickers from {full_start}")
        got.update(_yf_ohlc(new, full_start))
    if old:
        got.update(_yf_ohlc(old, recent_start))
        # a split (or a provider restatement) inside the stored window shows as stored closes that disagree
        # with the refreshed ones on common dates: refetch that ticker's full window rather than splice
        redo = []
        for tk in old:
            x = got.get(tk)
            if x is None or not len(x):
                continue
            st = store.loc[store["ticker"] == tk, "close"]
            common = st.index.intersection(x.index)
            if len(common) and float((st.loc[common] / x.loc[common, "close"] - 1).abs().max()) > 0.02:
                redo.append(tk)
        if redo:
            log(f"stored closes disagree with the provider (split or restatement): full refetch for {redo}")
            got.update(_yf_ohlc(redo, full_start))
            store = store[~store["ticker"].isin(redo)]
    last = pd.Timestamp(last_completed_session())
    frames = []
    for tk, x in got.items():
        x = x.loc[[d for d in x.index if is_trading_day(d.date()) and d <= last]]
        x = x.copy(); x["ticker"] = tk
        frames.append(x)
    if frames:
        inc = pd.concat(frames)
        if len(store):
            key_inc = set(zip(inc.index, inc["ticker"]))
            keep = [k not in key_inc for k in zip(store.index, store["ticker"])]
            store = pd.concat([store[keep], inc])
        else:
            store = inc
    store = store.sort_index()
    # keep about two years per ticker
    cutoff = store.index.unique().sort_values()[-KEEP_SESSIONS] if store.index.nunique() > KEEP_SESSIONS else store.index.min()
    store = store.loc[store.index >= cutoff]
    store.index.name = "date"
    OHLC.parent.mkdir(parents=True, exist_ok=True)
    store.to_parquet(OHLC)
    log(f"store: {store['ticker'].nunique()} tickers, {store.index.nunique()} sessions, through {store.index.max().date()} "
        f"({len(got)} fetched this run)")
    return store


def frame_for(store: pd.DataFrame, tk: str) -> pd.DataFrame:
    x = store[store["ticker"] == tk].drop(columns=["ticker"]).sort_index()
    return x[~x.index.duplicated(keep="last")]


# ── names, earnings, sizing ──────────────────────────────────────────────────────────────────
def universe_and_cards() -> tuple[list[str], dict[str, list[str]]]:
    uni = [t.strip().upper() for t in (DATA / "universe.txt").read_text().split() if t.strip()] if (DATA / "universe.txt").exists() else []
    held = [str(h["ticker"]).upper() for h in json.loads((DATA / "holdings.json").read_text()).get("holdings", []) if (h.get("shares") or 0) > 0]
    board = []
    try:
        board = [str(r["ticker"]).upper() for r in json.loads((DATA / "screen" / "scores.json").read_text()).get("watchlist", [])]
    except Exception:  # noqa: BLE001
        pass
    tiers = []
    try:
        last = json.loads((DATA / "tournament.json").read_text())["history"][-1]["tiers"]
        for tid, t in last.items():
            tiers += [str(p["ticker"]).upper() for p in t.get("positions", []) if (p.get("shares") or 0) > 0]
    except Exception:  # noqa: BLE001
        pass
    cards = {"held": sorted(set(held)), "board": board, "tiers": sorted(set(tiers))}
    allt = sorted(set(uni) | set(held) | set(board) | set(tiers))
    return allt, cards


def earnings_dates() -> dict[str, list[date]]:
    out: dict[str, set] = {}
    try:
        for e in json.loads((DATA / "event_calendar.json").read_text()).get("events", []):
            if e.get("type") == "EARNINGS" and e.get("ticker"):
                out.setdefault(str(e["ticker"]).upper(), set()).add(date.fromisoformat(e["date"][:10]))
    except Exception:  # noqa: BLE001
        pass
    try:
        er = json.loads((DATA / "options" / "earnings_reactions.json").read_text()).get("names", {})
        for tk, v in er.items():
            nd = ((v or {}).get("next") or {}).get("date")
            if nd:
                out.setdefault(tk.upper(), set()).add(date.fromisoformat(nd[:10]))
    except Exception:  # noqa: BLE001
        pass
    return {k: sorted(v) for k, v in out.items()}


class Book:
    """The current book (holdings.json at the last close) and the 126-session return window, for sizing."""
    def __init__(self, cfg: dict):
        import book_analytics as ba
        self.ba = ba
        h = ba.load_holdings(); px = ba.load_prices(); last = px.ffill().iloc[-1]
        self.vals = {}
        for p in h.get("holdings", []):
            tk = str(p.get("ticker", "")).upper(); sh = float(p.get("shares") or 0)
            if sh > 0 and tk in px.columns and pd.notna(last.get(tk)):
                self.vals[tk] = sh * float(last[tk])
        self.cash = float(h.get("cash") or 0.0)
        self.nav = sum(self.vals.values()) + self.cash
        self.rets = ba.daily_returns(px)
        etf = ba.load_etfs()
        self.spy = ba.daily_returns(etf)["SPY"] if "SPY" in etf.columns else pd.Series(dtype=float)
        self.window = cfg["size"]["risk_window_sessions"]
        self.as_of = h.get("as_of")

    def effect(self, tk: str, value: float, extra_rets: pd.Series | None = None) -> dict:
        ba = self.ba
        vals = dict(self.vals); vals[tk] = vals.get(tk, 0.0) + value
        w = {k: v / self.nav for k, v in vals.items()}
        rets = self.rets
        if tk not in rets.columns and extra_rets is not None:
            rets = rets.join(extra_rets.rename(tk), how="left")
        r_win = ba.window_returns(rets, list(w), window=self.window)
        rc = ba.risk_contributions(r_win, w)
        shares = {k: v for k, v in (rc.get("shares") or {}).items() if v is not None}
        top = max(shares.items(), key=lambda kv: kv[1]) if shares else (None, None)
        series = (r_win[[c for c in w if c in r_win.columns]].fillna(0.0) * pd.Series(w)).sum(axis=1)
        beta = ba.ols_beta(series, self.spy.reindex(series.index)).get("beta") if len(self.spy) else None
        return {"vol_nav_ann": rc.get("vol_nav_ann"), "beta_spy": beta, "risk_share_name": shares.get(tk),
                "largest_risk_share": top[1], "largest_risk_name": top[0], "invested_share": sum(vals.values()) / self.nav}


def size_for(book: Book, tk: str, entry: float, stop: float, half: bool, cfg: dict, extra_rets=None) -> dict:
    sz = cfg["size"]
    if not (entry and stop and entry > stop):
        return {"shares": None, "reason": "no entry above the stop"}
    risk_dollars = sz["risk_budget"] * book.nav * (cfg["event"]["size_factor"] if half else 1.0)
    shares = int(math.floor(risk_dollars / (entry - stop)))
    cash_cap = int(math.floor(book.cash / entry)) if entry > 0 else 0
    capped_by = None
    if shares > cash_cap:
        shares, capped_by = cash_cap, "cash"
    eff = book.effect(tk, shares * entry, extra_rets) if shares > 0 else book.effect(tk, 0.0, extra_rets)
    lim = sz["max_post_entry_risk_share"]
    # compared at the published precision (4 decimals), so a share that rounds to the cap counts as at it
    under = lambda e_: round(e_.get("risk_share_name") or 0, 4) < lim
    if shares > 0 and not under(eff):
        lo, hi = 0, shares
        while hi - lo > 1:
            mid = (lo + hi) // 2
            e = book.effect(tk, mid * entry, extra_rets)
            if under(e): lo = mid
            else: hi = mid
        shares, capped_by = lo, "risk share"
        eff = book.effect(tk, shares * entry, extra_rets)
    before = book.effect(tk, 0.0, extra_rets)
    return {"shares": shares, "entry": round(entry, 2), "stop": round(stop, 2), "risk_per_share": round(entry - stop, 2),
            "risk_dollars": round(shares * (entry - stop), 2), "value": round(shares * entry, 2),
            "risk_budget": sz["risk_budget"] * (cfg["event"]["size_factor"] if half else 1.0), "account_value": round(book.nav, 2),
            "capped_by": capped_by,
            "book_before": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in before.items()},
            "book_after": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in eff.items()}}


def r2(x, nd=2):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), nd)


def txt(x):
    """A string field of the evaluation frame (None/NaN when empty) as str or None."""
    return x if isinstance(x, str) else None


def card_record(tk: str, ind: pd.DataFrame, ev: pd.DataFrame, earn: list[date], cfg: dict) -> dict:
    r = ind.iloc[-1]; e = ev.iloc[-1]; d0 = ind.index[-1].date()
    nxt = next((x for x in earn if x > d0), None)
    st = e["state"]
    trig_level = r2(r["high"])                                  # the close the next session must exceed
    rec = {
        "state": st, "date": str(d0), "close": r2(r["close"]),
        "trend": {"pass": bool(r["trend"]), "mom_12_1": r2(r["mom_12_1"], 4), "ma200": r2(r["ma_long"])},
        "setup": {"present": bool(r["setup"]), "below_ma20_minus_atr": bool(r["setup_atr"]), "rsi_le_40": bool(r["setup_rsi"]),
                  "lowest_quarter_of_range": bool(r["setup_range"])},
        "trigger": txt(e["trigger"]), "trigger_level": trig_level,
        "breakdown_level": r2(r["breakdown_level"]) if not pd.isna(r["breakdown_level"]) else None,
        "stop": r2(r["stop"]), "armed_stop": r2(e["armed_stop"]), "armed_since": txt(e["armed_since"]),
        "breach": bool(e["breach"]), "breach_stop": r2(e["breach_stop"]),
        "ma20": r2(r["ma_short"]), "ma50": r2(r["ma50"]), "atr": r2(r["atr"]), "rsi": r2(r["rsi"], 1),
        "range_lo": r2(r["range_lo"]), "range_hi": r2(r["range_hi"]),
        "next_earnings": str(nxt) if nxt else None,
        "sessions_to_earnings": sessions_until(d0, nxt) if nxt else None,
        "earnings_known": bool(earn),
    }
    return rec


def main() -> int:
    from trading_calendar import last_completed_session
    cfg = load_config()
    allt, cards = universe_and_cards()
    store = update_store(allt)
    earn = earnings_dates()
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    prev_names = prev.get("names", {})
    book = Book(cfg)
    card_set = set(cards["held"]) | set(cards["board"]) | set(cards["tiers"])
    groups = {tk: g.drop(columns=["ticker"]).sort_index() for tk, g in store.groupby("ticker")}
    names, transitions = {}, []
    # the session graded is the store's latest bar (a late provider bar leaves the payload dated the prior
    # session, which the freshness rule then reads as pending/stale, rather than grading on a partial day)
    session = str(store.index.max().date())
    if session < str(pd.Timestamp(last_completed_session()).date()):
        log(f"store ends {session}, before the last completed session {last_completed_session()}: graded as of {session}")
    for tk in allt:
        f = groups.get(tk, pd.DataFrame(columns=["open", "high", "low", "close", "adj_close"]))
        f = f[~f.index.duplicated(keep="last")]
        if not len(f) or str(f.index[-1].date()) < session:
            # no bar for the session (delisted, halted or a provider gap): no state on old prices
            lastb = str(f.index[-1].date()) if len(f) else None
            names[tk] = {"state": None, "date": lastb,
                         "reason": f"no bar for {session} from the provider (last bar {lastb or 'none'}); no state on stale prices"}
            continue
        if len(f) < 260:
            names[tk] = {"state": None, "reason": f"insufficient history ({len(f)} sessions; the trend gate needs 253)"}
            continue
        ind = indicators(f, cfg)
        # what this session is graded from: the previous run's state, armed stop and date. A rerun of the
        # same session (the nightly's retry slots) reuses the inputs it was first graded from, so it
        # reproduces the same record and transitions instead of re-grading on its own output.
        p = prev_names.get(tk) or {}
        if p.get("date") == session and p.get("graded_from"):
            g = p["graded_from"]
        else:
            g = {"after": p.get("date") if p.get("state") else None, "state": p.get("state"),
                 "armed": ({"stop": p["armed_stop"], "date": p.get("armed_since")} if p.get("armed_stop") is not None else None)}
        sub = ind.loc[ind.index > pd.Timestamp(g["after"])] if g["after"] else ind.iloc[-60:]
        if not len(sub):
            sub = ind.iloc[-1:]
        ev = evaluate(sub, cfg, earn.get(tk), g["armed"])
        rec = card_record(tk, ind.loc[:sub.index[-1]], ev, earn.get(tk, []), cfg)
        rec["graded_from"] = g
        st = rec["state"]
        if st in ("READY", "READY-HALF", "WATCH"):            # sized wherever a card can open (any graded name)
            entry = rec["close"] if st.startswith("READY") else rec["trigger_level"]
            stop = rec["armed_stop"] if st.startswith("READY") and rec["armed_stop"] else rec["stop"]
            extra = f["adj_close"].pct_change() if tk not in book.rets.columns else None
            half = st == "READY-HALF" or (st == "WATCH" and rec["sessions_to_earnings"] is not None
                                          and rec["sessions_to_earnings"] <= cfg["event"]["earnings_sessions"])
            rec["size"] = size_for(book, tk, entry, stop, half, cfg, extra)
            rec["size"]["basis"] = ("the close at READY" if st.startswith("READY") else
                                    "the trigger level (today's high), as if the next session triggers") + \
                                   (" · half size: earnings within 20 sessions" if half else "")
        else:
            rec["size"] = {"shares": None, "reason": "no entry defined at " + str(st)}
        if tk in card_set:
            # transitions since the previous run (a first run reports only the session's own)
            grp = [k for k in ("held", "board", "tiers") if tk in cards[k]]
            for t in transitions_of(ev, g["state"]):
                if g["after"] or t["date"] == session:
                    transitions.append({"date": t["date"], "ticker": tk, "from": t["from"], "to": t["to"],
                                        "reason": t["reason"], "groups": grp})
        names[tk] = rec
    counts = {s: sum(1 for v in names.values() if v.get("state") == s) for s in STATES}
    validation = {"verdict": "NOT RUN", "summary": "the registered validation has not reported"}
    vp = DATA / "entry_state_validation.json"
    if vp.exists():
        vj = json.loads(vp.read_text()); r_ = vj.get("result") or {}
        dm, ds = r_.get("dMAE") or {}, r_.get("dSTOP20") or {}
        pt = lambda x: f"{x * 100:+.2f}" if isinstance(x, (int, float)) else "?"
        why = " (the registered test lacked power)" if vj.get("verdict") == "NO VERDICT" else ""
        validation = {"verdict": vj.get("verdict"), "as_of": vj.get("as_of"), "report": "reports/entry_state_validation_2026-10-02.md",
                      "summary": (f"registered test, 2010 to {vj.get('entries_through')}: {vj.get('verdict')}{why}. READY entries' median loss "
                                  f"before 20 sessions {pt(dm.get('point'))} pt against month-start entries (90% interval {pt((dm.get('ci90') or [None])[0])} to "
                                  f"{pt((dm.get('ci90') or [None, None])[1])}); stopped out within 20 sessions "
                                  f"{(ds.get('mean_contestant') or 0) * 100:.0f}% against {(ds.get('mean_baseline') or 0) * 100:.0f}%")}
    payload = {
        "cadence": "daily", "session_date": session, "as_of": session,
        "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": cfg["label"], "label_reason": cfg["label_reason"], "config_frozen_at": cfg["frozen_at"], "validation": validation,
        "account_value": round(book.nav, 2), "holdings_as_of": book.as_of,
        "cards": cards, "counts": counts, "transitions_today": transitions,
        "definitions": {k: cfg[k]["rule"] for k in ("trend", "setup", "trigger", "event", "stop", "size")},
        "note": "a rule output for reading, not an instruction to trade; DIAGNOSTIC until the registered validation reports",
        "names": names,
    }
    OUT.write_text(json.dumps(payload, indent=1, allow_nan=False))
    if transitions:
        seen = set()
        if LOG.exists():
            for line in LOG.read_text().splitlines():
                try:
                    x = json.loads(line); seen.add((x["date"], x["ticker"], x["from"], x["to"], x["reason"]))
                except (ValueError, KeyError):
                    continue
        with LOG.open("a") as fh:
            for t in transitions:
                if (t["date"], t["ticker"], t["from"], t["to"], t["reason"]) in seen:
                    continue                      # already logged by an earlier run of this session
                fh.write(json.dumps({**t, "logged_at": payload["computed_at"]}) + "\n")
    log(f"{session}: {len(names)} names; " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f"; {len(transitions)} card transitions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
