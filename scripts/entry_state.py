#!/usr/bin/env python3
"""
entry_state.py — the entry-state indicator, version 3 (Execution Order: Revision of the Entry-State Indicator
and Related Fixes, 6 October 2026, as revised the same day; revises the 2-Oct rules, which stay frozen in
scripts/entry_state_v1.py. Version 2, the morning's text, differed only in the WAIT state and the
days-to-cover-only shorting flag; its configuration is kept in data/entry_state_config_2026-10-06_v2.json).

The screen answers what is worth owning; this reads the tape for an entry and gives every name a stop and a
risk-budget size. Per name, nightly, parameters in data/entry_state_config.json (version 3):

  trend gate   AVOID only when the close is below the 200-day average AND the 12-month return excluding the
               last month is negative. Below the 200-day with positive momentum passes, flag below_200d
  entry        a passing gate = READY, extended or pulling back (no WAIT state). The setup measures (distance
               from MA20 in ATR units, RSI(14), position in the 40-session range) and the confirmation (close
               above the prior session's high, or a failed breakdown recovered, with its volume against 1.5 x
               the 50-day average) are information only
  modifiers    in order: below_200d x0.5; earnings within 20 sessions x0.5 (READY-HALF); days-to-cover >= 7
               or short interest >= 20% of the float x0.5 (heavily shorted). Never below a quarter of the base
               size: deeper than that is WATCH
  ceiling      a multi-year ceiling (data/long_range.json, scripts/long_range.py) within 15% above the close
               caps the state at WATCH until a close above it
  stop         the 40-session low minus 1 ATR(14) (no 200-day floor)
  size         0.5% of the account at risk / (entry - stop) x the modifiers, capped below 40% of book risk

DIAGNOSTIC until the registered validation (reports/entry_state_validation_registration_v4_2026-10-06.md) reports.
Descriptive rule output: it states what the rule reads, not an instruction to trade.

Outputs: data/entry_state.json, data/entry_state_log.jsonl (append-only state changes of the card names),
data/source/ohlc_daily.parquet (split-adjusted daily OHLC, the adjusted close and volume, about two years).
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
CONFIG = DATA / "entry_state_config.json"
OHLC = SOURCE / "ohlc_daily.parquet"
OUT = DATA / "entry_state.json"
LOG = DATA / "entry_state_log.jsonl"
STATES = ("AVOID", "WATCH", "READY", "READY-HALF")      # version 3: no WAIT state
KEEP_SESSIONS = 520
COLS = ["open", "high", "low", "close", "adj_close", "volume"]


def log(m: str) -> None:
    print(f"[entry_state] {m}", flush=True)


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text())


# ── indicators (one ticker) ──────────────────────────────────────────────────────────────────
def indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """df: columns open, high, low, close (split-adjusted) and, when present, volume; index sessions ascending."""
    c, h, l = df["close"].astype(float), df["high"].astype(float), df["low"].astype(float)
    t, s, st, en = cfg["trend"], cfg["setup"], cfg["stop"], cfg["entry"]
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
    out["below_200d"] = c < out["ma_long"]
    out["trend"] = ~(out["below_200d"] & (out["mom_12_1"] < 0))                  # fails only below the 200-day AND negative momentum
    # the setup measures (version 3: information only, no state depends on them)
    out["dist_ma20_atr"] = (c - out["ma_short"]) / out["atr"]
    rng = out["range_hi"] - out["range_lo"]
    out["range_pos"] = ((c - out["range_lo"]) / rng).where(rng > 0)
    out["prior_high"] = h.shift(1)
    out["trig_high"] = c > out["prior_high"]
    out["stop"] = l.rolling(st["range_sessions"]).min() - st["atr_mult"] * out["atr"]   # no 200-day floor (version 2)
    if "volume" in df.columns:
        v = pd.to_numeric(df["volume"], errors="coerce").astype(float)
        out["volume"] = v
        out["volume_avg"] = v.rolling(en["volume_avg_sessions"]).mean()
        out["volume_ratio"] = v / out["volume_avg"]
    else:
        out["volume"] = out["volume_avg"] = out["volume_ratio"] = np.nan
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
            if age > en["failed_breakdown_window_sessions"]:
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


def ceiling_capped(close: float, levels, cfg: dict) -> float | None:
    """The ceiling the close sits within flag_within_pct below (the nearest such), or None. A close above a
    ceiling lifts its cap. `levels` is one level or a list (data/long_range.json, every qualifying ceiling)."""
    if levels is None or close is None or not np.isfinite(close):
        return None
    lv = [levels] if isinstance(levels, (int, float)) else list(levels)
    hit = [x for x in lv if x and x * (1 - cfg["ceiling"]["flag_within_pct"]) <= close < x]
    return min(hit) if hit else None


def active_ceilings(lr: dict | None, closes: pd.Series | None = None) -> list[dict]:
    """The ceilings still standing: none broken by a close above it since it formed, in the long-range history
    (refreshed weekly) or in the recent closes (`closes`, the daily store)."""
    out = []
    for c in ((lr or {}).get("ceilings") or []):
        if not c.get("level") or c.get("broken"):
            continue
        if closes is not None and c.get("formed"):
            rec = closes[closes.index > pd.Timestamp(c["formed"])]
            if len(rec) and float(rec.max()) > c["level"]:
                continue
        out.append(c)
    return out


def nearest_ceiling(close: float, lr: dict | None, closes: pd.Series | None = None) -> dict | None:
    """The lowest standing ceiling above the close (the one the price meets first)."""
    above = [c for c in active_ceilings(lr, closes) if c["level"] > close]
    return min(above, key=lambda c: c["level"]) if above else None


def heavily_shorted(days_to_cover: float | None, short_pct_float: float | None, cfg: dict) -> bool:
    """Days-to-cover of 7 or more, or short interest of 20% or more of the float (version 3: either measure)."""
    m = cfg["modifiers"]
    return bool((days_to_cover is not None and days_to_cover >= m["days_to_cover_min"]) or
                (short_pct_float is not None and short_pct_float >= m.get("short_pct_float_min", float("inf"))))


def evaluate(ind: pd.DataFrame, cfg: dict, earnings: list[date] | None = None, days_to_cover: float | None = None,
             ceilings=None, short_pct_float: float | None = None) -> pd.DataFrame:
    """The state per session, a pure function of the session's data and the name's inputs (the next earnings
    date, the current days-to-cover and short interest as a share of the float, the ceiling level). Returns
    state, the modifiers and their product, the ceiling cap, the reason for a WATCH, and the earnings distance."""
    m = cfg["modifiers"]
    shorted = heavily_shorted(days_to_cover, short_pct_float, cfg)
    earn = sorted(earnings or [])
    rows = []
    for ts, r in ind.iterrows():
        d0 = ts.date()
        rec = {"date": str(d0), "state": None, "modifiers": [], "size_factor": None, "ceiling_capped": False,
               "watch_reason": None, "earnings_in_sessions": None}
        if not r["complete"]:
            rows.append(rec); continue
        nxt = next((e for e in earn if e > d0), None)
        sess = sessions_until(d0, nxt) if nxt else None
        rec["earnings_in_sessions"] = sess
        cap_at = ceiling_capped(float(r["close"]), ceilings, cfg)
        capped = cap_at is not None
        rec["ceiling_capped"] = capped
        if not r["trend"]:
            st = "AVOID"
        else:                                    # version 3: a passing gate is an entry, extended or not
            mods, f = [], 1.0
            if r["below_200d"]:
                mods.append("below_200d"); f *= m["factor"]
            if sess is not None and sess <= m["earnings_sessions"]:
                mods.append("earnings"); f *= m["factor"]
            if shorted:
                mods.append("heavily_shorted"); f *= m["factor"]
            rec["modifiers"], rec["size_factor"] = mods, f
            if f < m["min_size_factor"] - 1e-9:
                st, rec["watch_reason"] = "WATCH", f"the size modifiers ({', '.join(mods)}) would take the size below a quarter of the base"
            elif capped:
                st, rec["watch_reason"] = "WATCH", f"capped by the long-term ceiling at {cap_at:.2f} until a close above it"
            else:
                st = "READY-HALF" if "earnings" in mods else "READY"
        rec["state"] = st
        rows.append(rec)
    return pd.DataFrame(rows).set_index("date")


def transitions_of(ev: pd.DataFrame, prev: str | None = None) -> list[dict]:
    """Every state change in an evaluated series with its reason. `prev` is the state the series starts from."""
    out = []
    for d, r in ev.iterrows():
        st = r["state"]
        if not isinstance(st, str):          # incomplete history: no state (None becomes NaN in the frame)
            continue
        if prev is not None and st != prev:
            reason = ("trend gate failed: below the 200-day average with negative 12-month momentum" if st == "AVOID"
                      else (r["watch_reason"] or "watch") if st == "WATCH"
                      else "a passing trend gate" + (" (earnings within 20 sessions: half size)" if st == "READY-HALF" else ""))
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
                x = x[COLS].dropna(subset=["close"])
                if len(x):
                    x.index = pd.to_datetime(x.index).tz_localize(None)
                    out[tk] = x
            except Exception:  # noqa: BLE001
                continue
    return out


def update_store(tickers: list[str], full_start: str = "2024-06-01") -> pd.DataFrame:
    """Long-format store (date, ticker, open, high, low, close, adj_close, volume). New tickers get the full
    window; the rest the last 30 calendar days, overlaid. Non-session and partial-today rows are dropped. A
    store written before volume was kept (6-Oct-2026) is refetched in full once."""
    from trading_calendar import is_trading_day, last_completed_session
    store = pd.read_parquet(OHLC) if OHLC.exists() else pd.DataFrame(columns=["ticker", *COLS])
    if len(store):
        store.index = pd.to_datetime(store.index)
    if len(store) and "volume" not in store.columns:
        log("the store has no volume column: full refetch of every ticker (once)")
        store = pd.DataFrame(columns=["ticker", *COLS])
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


# ── names and the per-name inputs ────────────────────────────────────────────────────────────
def universe_and_cards() -> tuple[list[str], dict[str, list[str]]]:
    uni = [t.strip().upper() for t in (DATA / "universe.txt").read_text().split() if t.strip()] if (DATA / "universe.txt").exists() else []
    held = [str(h["ticker"]).upper() for h in json.loads((DATA / "holdings.json").read_text()).get("holdings", []) if (h.get("shares") or 0) > 0]
    board = []
    try:
        board = [str(r["ticker"]).upper() for r in json.loads((DATA / "screen" / "scores.json").read_text()).get("watchlist", [])]
    except Exception:  # noqa: BLE001
        pass
    tiers = []
    card_tiers = ("1_cap_pres", "2_balanced", "3_aggressive", "4_tactical", "5_werner")   # J6: the paper tier 6_strat gets no cards
    try:
        last = json.loads((DATA / "tournament.json").read_text())["history"][-1]["tiers"]
        for tid, t in last.items():
            if tid not in card_tiers:
                continue
            tiers += [str(p["ticker"]).upper() for p in t.get("positions", []) if (p.get("shares") or 0) > 0]
    except Exception:  # noqa: BLE001
        pass
    review = []
    try:      # names the operator's orders discuss (data/review_names.json): a full card on the book page
        review = [str(r["ticker"]).upper() for r in json.loads((DATA / "review_names.json").read_text()).get("names", [])]
    except Exception:  # noqa: BLE001
        pass
    cards = {"held": sorted(set(held)), "board": board, "tiers": sorted(set(tiers)), "review": review}
    allt = sorted(set(uni) | set(held) | set(board) | set(tiers) | set(review))
    return allt, cards


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        return {}


def earnings_inputs() -> tuple[dict[str, list[date]], dict[str, dict]]:
    """The next-earnings date per name and its record. data/earnings_dates.json (the resolved date across
    sources, with any conflict; scripts/earnings_dates.py) is preferred; otherwise every date on record."""
    out: dict[str, set] = {}
    recs: dict[str, dict] = {}
    resolved = _json(DATA / "earnings_dates.json").get("names") or {}
    for tk, v in resolved.items():
        if v.get("date"):
            out.setdefault(tk.upper(), set()).add(date.fromisoformat(v["date"][:10])); recs[tk.upper()] = v
    for e in _json(DATA / "event_calendar.json").get("events", []):
        tk = str(e.get("ticker") or "").upper()
        if e.get("type") == "EARNINGS" and tk and tk not in recs:
            out.setdefault(tk, set()).add(date.fromisoformat(e["date"][:10]))
    for tk, v in (_json(DATA / "options" / "earnings_reactions.json").get("names") or {}).items():
        nd = ((v or {}).get("next") or {}).get("date")
        if nd and tk.upper() not in recs:
            out.setdefault(tk.upper(), set()).add(date.fromisoformat(nd[:10]))
    return {k: sorted(v) for k, v in out.items()}, recs


def short_interest() -> dict[str, dict]:
    """Days-to-cover, short interest as a share of the float and the month-on-month change in short interest
    per name, from the canonical fundamentals fetch (the provider's shortRatio, shortPercentOfFloat,
    floatShares, sharesShort, sharesShortPriorMonth)."""
    out = {}
    for tk, f in (_json(DATA / "canonical" / "fundamentals.json").get("tickers") or {}).items():
        f = f or {}
        dtc, spf = f.get("shortRatio"), f.get("shortPercentOfFloat")
        if dtc is None and spf is None:
            continue
        cur, prv = f.get("sharesShort"), f.get("sharesShortPriorMonth")
        stamp = f.get("dateShortInterest")
        out[tk.upper()] = {"days_to_cover": round(float(dtc), 2) if dtc is not None else None,
                           "short_pct_float": round(float(spf), 4) if spf is not None else None,
                           "float_shares": f.get("floatShares"), "shares_short": cur, "shares_short_prior_month": prv,
                           "change_vs_prior_month": round(cur / prv - 1, 4) if cur and prv else None,
                           "as_of": datetime.fromtimestamp(stamp).date().isoformat() if isinstance(stamp, (int, float)) else None}
    return out


def long_range() -> dict[str, dict]:
    return _json(DATA / "long_range.json").get("names") or {}


def provider_flags() -> dict[str, list[dict]]:
    return {k.upper(): v.get("flags", []) for k, v in (_json(DATA / "provider_flags.json").get("names") or {}).items() if v.get("flags")}


# ── sizing ────────────────────────────────────────────────────────────────────────────────────
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


def size_for(book: Book, tk: str, entry: float, stop: float, factor: float, cfg: dict, extra_rets=None) -> dict:
    sz = cfg["size"]
    if not (entry and stop and entry > stop):
        return {"shares": None, "reason": "no entry above the stop"}
    base_risk = sz["risk_budget"] * book.nav
    risk_dollars = base_risk * factor
    base_shares = int(math.floor(base_risk / (entry - stop)))
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
    return {"shares": shares, "base_shares": base_shares, "size_factor": factor, "entry": round(entry, 2), "stop": round(stop, 2),
            "risk_per_share": round(entry - stop, 2), "risk_dollars": round(shares * (entry - stop), 2), "value": round(shares * entry, 2),
            "risk_budget": sz["risk_budget"] * factor, "account_value": round(book.nav, 2), "capped_by": capped_by,
            "book_before": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in before.items()},
            "book_after": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in eff.items()}}


def r2(x, nd=2):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), nd)


MOD_TEXT = {"below_200d": "below the 200-day average (momentum positive)", "earnings": "earnings within 20 sessions",
            "heavily_shorted": "heavily shorted (days-to-cover 7 or more, or short interest 20% or more of the float)"}


def card_record(tk: str, ind: pd.DataFrame, ev: pd.DataFrame, earn: list[date], erec: dict | None, si: dict | None,
                lr: dict | None, pflags: list[dict], cfg: dict) -> dict:
    r = ind.iloc[-1]; e = ev.iloc[-1]; d0 = ind.index[-1].date()
    nxt = next((x for x in earn if x > d0), None)
    close = float(r["close"])
    vr = r.get("volume_ratio")
    ceil = nearest_ceiling(close, lr, ind["close"])
    ceil_level = ceil.get("level") if ceil else None
    rec = {
        "state": e["state"], "date": str(d0), "close": r2(close),
        "trend": {"pass": bool(r["trend"]), "below_200d": bool(r["below_200d"]), "mom_12_1": r2(r["mom_12_1"], 4), "ma200": r2(r["ma_long"])},
        "setup": {"dist_ma20_atr": r2(r["dist_ma20_atr"]), "rsi": r2(r["rsi"], 1), "range_pos": r2(r["range_pos"], 2),
                  "note": "information only: no state depends on it (version 3)"},
        "confirmation": {"close_above_prior_high": bool(r["trig_high"]), "prior_high": r2(r["prior_high"]),
                         "failed_breakdown_recovered": bool(r["trig_failed_breakdown"]),
                         "breakdown_level": r2(r["breakdown_level"]) if not pd.isna(r["breakdown_level"]) else None,
                         "volume_ratio": r2(vr, 2) if vr is not None and not pd.isna(vr) else None,
                         "volume_confirms": bool(vr is not None and not pd.isna(vr) and vr > cfg["entry"]["volume_mult"]),
                         "note": "information only: no longer required for READY"},
        "modifiers": [{"name": m, "factor": cfg["modifiers"]["factor"], "text": MOD_TEXT[m]} for m in (e["modifiers"] or [])],
        "size_factor": r2(e["size_factor"], 4) if e["size_factor"] is not None and not pd.isna(e["size_factor"]) else None,
        "watch_reason": e["watch_reason"] if isinstance(e["watch_reason"], str) else None,
        "stop": r2(r["stop"]), "ma20": r2(r["ma_short"]), "ma50": r2(r["ma50"]), "atr": r2(r["atr"]), "rsi": r2(r["rsi"], 1),
        "range_lo": r2(r["range_lo"]), "range_hi": r2(r["range_hi"]),
        "next_earnings": str(nxt) if nxt else None,
        "sessions_to_earnings": sessions_until(d0, nxt) if nxt else None,
        "earnings_known": bool(earn),
        "earnings": erec or None,
        "short_interest": si or None,
        "heavily_shorted": heavily_shorted((si or {}).get("days_to_cover"), (si or {}).get("short_pct_float"), cfg),
        "heavily_shorted_by": [k for k, ok in (("days-to-cover", (si or {}).get("days_to_cover") is not None and si["days_to_cover"] >= cfg["modifiers"]["days_to_cover_min"]),
                                                ("short interest of the float", (si or {}).get("short_pct_float") is not None and si["short_pct_float"] >= cfg["modifiers"]["short_pct_float_min"])) if ok],
        "long_range": None, "ceiling_flag": False,
        "provider_flags": pflags or [],
    }
    if lr:
        h5, ath = dict(lr.get("high_5y") or {}), dict(lr.get("ath") or {})
        for rec_hi in (h5, ath):                       # a close above the record's high (refreshed weekly) is the new high
            if rec_hi.get("close") and close > rec_hi["close"]:
                rec_hi.update(close=round(close, 2), date=str(d0))
        rec["long_range"] = {
            "high_5y": h5.get("close"), "high_5y_date": h5.get("date"), "dist_5y": r2(close / h5["close"] - 1, 4) if h5.get("close") else None,
            "ath": ath.get("close"), "ath_date": ath.get("date"), "dist_ath": r2(close / ath["close"] - 1, 4) if ath.get("close") else None,
            "ceiling": ceil, "dist_ceiling": r2(close / ceil_level - 1, 4) if ceil_level else None,
            "ceilings": [c["level"] for c in active_ceilings(lr, ind["close"])], "as_of": lr.get("as_of")}
        rec["ceiling_flag"] = ceiling_capped(close, [c["level"] for c in active_ceilings(lr, ind["close"])], cfg) is not None
    return rec


def main() -> int:
    from trading_calendar import last_completed_session
    cfg = load_config()
    allt, cards = universe_and_cards()
    store = update_store(allt)
    earn, erecs = earnings_inputs()
    si_all, lr_all, pf_all = short_interest(), long_range(), provider_flags()
    prev = _json(OUT)
    # the changes reported are those after the previous run's session; a rerun of the same session keeps
    # the baseline its first run used, so it reports the same changes
    prev_session = prev.get("transitions_after") if prev.get("session_date") == str(store.index.max().date()) else prev.get("session_date")
    book = Book(cfg)
    card_set = set(cards["held"]) | set(cards["board"]) | set(cards["tiers"]) | set(cards["review"])
    groups = {tk: g.drop(columns=["ticker"]).sort_index() for tk, g in store.groupby("ticker")}
    names, transitions = {}, []
    # the session graded is the store's latest bar (a late provider bar leaves the payload dated the prior
    # session, which the freshness rule then reads as pending/stale, rather than grading on a partial day)
    session = str(store.index.max().date())
    if session < str(pd.Timestamp(last_completed_session()).date()):
        log(f"store ends {session}, before the last completed session {last_completed_session()}: graded as of {session}")
    for tk in allt:
        f = groups.get(tk, pd.DataFrame(columns=COLS))
        f = f[~f.index.duplicated(keep="last")]
        if not len(f) or str(f.index[-1].date()) < session:
            lastb = str(f.index[-1].date()) if len(f) else None
            names[tk] = {"state": None, "date": lastb,
                         "reason": f"no bar for {session} from the provider (last bar {lastb or 'none'}); no state on stale prices"}
            continue
        if len(f) < 260:
            names[tk] = {"state": None, "reason": f"insufficient history ({len(f)} sessions; the trend gate needs 253)"}
            continue
        ind = indicators(f, cfg)
        si = si_all.get(tk); lr = lr_all.get(tk)
        ceil_levels = [c["level"] for c in active_ceilings(lr, ind["close"])]
        # the state is a pure function of the data and the name's inputs, so a rerun of the session reproduces
        # it; the last 60 sessions are evaluated and the changes after the previous run's session are reported
        sub = ind.iloc[-60:]
        ev = evaluate(sub, cfg, earn.get(tk), (si or {}).get("days_to_cover"), ceil_levels, (si or {}).get("short_pct_float"))
        rec = card_record(tk, ind, ev, earn.get(tk, []), erecs.get(tk), si, lr, pf_all.get(tk, []), cfg)
        st = rec["state"]
        if st in ("READY", "READY-HALF"):
            extra = f["adj_close"].pct_change() if tk not in book.rets.columns else None
            rec["size"] = size_for(book, tk, rec["close"], rec["stop"], rec["size_factor"] or 1.0, cfg, extra)
            rec["size"]["basis"] = "the close; " + ("modifiers: " + ", ".join(m["name"] for m in rec["modifiers"]) if rec["modifiers"] else "no modifier")
        else:
            rec["size"] = {"shares": None, "reason": (rec["watch_reason"] or f"no entry at {st}")}
        if tk in card_set:
            grp = [k for k in ("held", "board", "tiers", "review") if tk in cards[k]]
            for t in transitions_of(ev):
                if (prev_session and t["date"] > prev_session) or (not prev_session and t["date"] == session):
                    transitions.append({"date": t["date"], "ticker": tk, "from": t["from"], "to": t["to"],
                                        "reason": t["reason"], "groups": grp})
        names[tk] = rec
    counts = {s: sum(1 for v in names.values() if v.get("state") == s) for s in STATES}
    validation = {"verdict": "NOT RUN",
                  "summary": ("version 3 of the rules (6 Oct 2026, revised order): the registered validation on survivorship-free S&P 500 constituents "
                              "(reports/entry_state_validation_registration_v4_2026-10-06.md) has not run; it waits for the purchased data. "
                              "The 2-Oct rules' test returned no verdict (reports/entry_state_validation_2026-10-02.md)")}
    payload = {
        "cadence": "daily", "session_date": session, "as_of": session,
        "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rules_version": cfg.get("version", 1), "label": cfg["label"], "label_reason": cfg["label_reason"],
        "config_frozen_at": cfg["frozen_at"], "validation": validation,
        "account_value": round(book.nav, 2), "holdings_as_of": book.as_of,
        "cards": cards, "counts": counts, "transitions_today": transitions, "transitions_after": prev_session,
        "definitions": {k: cfg[k]["rule"] for k in ("trend", "setup", "entry", "modifiers", "ceiling", "stop", "size")},
        "note": "a rule output for reading, not an instruction to trade; DIAGNOSTIC until the registered validation reports",
        "names": names,
    }
    OUT.write_text(json.dumps(payload, indent=1, allow_nan=False, default=str))
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
                fh.write(json.dumps({**t, "rules_version": payload["rules_version"], "logged_at": payload["computed_at"]}) + "\n")
    log(f"{session}: {len(names)} names; " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f"; {len(transitions)} card transitions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
