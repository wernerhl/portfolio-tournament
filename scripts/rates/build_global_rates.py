#!/usr/bin/env python3
"""
build_global_rates.py — the global-rates panels for the bonds page, the home strip and the daily log's facts
(Execution Order: Global Rates Panels on the Bonds Page, 6 October 2026, sections 2-7).

Reads data/source/rates_daily.parquet, data/rates/series_meta.json, data/rates/auctions.json and the event calendar
(the quarterly refunding); writes data/rates/global_rates.json:

  panel_a   G7 10-year yields: level and date, change over a week, a month and twelve months, the level's
            percentile in the country's last 20 years of monthly data; a chart since January 2021 and one of the
            change since 1 January 2026; the co-movement (average pairwise correlation of monthly changes over
            36 months, each country against the United States)
  panel_b   the U.S. 10-year split: nominal = real + breakeven; nominal = expected average short rate + term
            premium (Kim-Wright; ACM beside it); current values with one- and twelve-month changes; the term
            premium's place in its history; the identities checked on the latest common date
  panel_c   the last 12 note and bond auctions against the prior six of each maturity, "weak" by the configured
            thresholds; the announced auctions and the next quarterly refunding
  panel_d   drivers: Brent (EIA spot via FRED and the provider's front-month, the same-day value), yen per
            dollar, Japan 10-year, UK 30-year, U.S. 2-year, effective fed funds
  panel_e   signals of worsening and of reversal, each with its measured value and threshold
  home      the strip under the regime gauge: each value with its one-day change and date
  facts     the daily log's additions

Descriptive throughout: no forecast, no recommendation.  Usage:  python scripts/rates/build_global_rates.py
"""
from __future__ import annotations

import itertools
import json
import operator
import re
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
from trading_calendar import now_et   # noqa: E402  (the ET date: a runner's clock is UTC)
DATA = REPO / "data"
RATES = DATA / "rates"
CONFIG = RATES / "global_rates_config.json"
STORE = DATA / "source" / "rates_daily.parquet"
META = RATES / "series_meta.json"
AUCTIONS = RATES / "auctions.json"
OUT = RATES / "global_rates.json"
OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le}


def log(m: str) -> None:
    print(f"[global_rates] {m}", flush=True)


def r4(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 4)


class Store:
    def __init__(self):
        df = pd.read_parquet(STORE)
        df["date"] = pd.to_datetime(df["date"])
        self.s = {k: g.set_index("date")["value"].sort_index().dropna() for k, g in df.groupby("series")}
        self.meta = json.loads(META.read_text()) if META.exists() else {}

    def get(self, k) -> pd.Series:
        return self.s.get(k, pd.Series(dtype=float))

    def at(self, k, when) -> tuple[pd.Timestamp | None, float | None]:
        x = self.get(k); x = x[x.index <= pd.Timestamp(when)]
        return (x.index[-1], float(x.iloc[-1])) if len(x) else (None, None)

    def latest(self, k):
        x = self.get(k)
        return (x.index[-1], float(x.iloc[-1])) if len(x) else (None, None)

    def change(self, k, offset, pct=False):
        """latest minus the last value on or before (latest date - offset); percent change when pct."""
        d, v = self.latest(k)
        if d is None:
            return None
        d0, v0 = self.at(k, d - offset)
        if v0 is None:
            return None
        return (v / v0 - 1) * 100 if pct else v - v0

    def prev_change(self, k):
        x = self.get(k)
        return (float(x.iloc[-1] - x.iloc[-2]), str(x.index[-2].date())) if len(x) >= 2 else (None, None)

    def source(self, k) -> dict:
        m = self.meta.get(k, {})
        return {"source": m.get("source"), "id": m.get("id"), "label": m.get("label"), "retrieved_at": m.get("retrieved_at"),
                "as_of": m.get("as_of"), "error": m.get("error")}


def weekly(x: pd.Series, start: str) -> list[list]:
    x = x[x.index >= start]
    if not len(x):
        return []
    w = x.resample("W-FRI").last().dropna()
    return [[str(d.date()), r4(v)] for d, v in w.items()]


def panel_a(st: Store, cfg: dict) -> dict:
    pa = cfg["panel_a"]
    rows, chart, change = [], {}, {}
    for c in cfg["countries"]:
        mk = c["monthly"]; dk = c["daily"]
        dly = st.get(dk) if dk else pd.Series(dtype=float)
        fresh = dk and len(dly) and (pd.Timestamp(now_et().date()) - dly.index[-1]).days <= 10
        key, kind = (dk, "daily") if fresh else (mk, "monthly average")
        d, v = st.latest(key)
        m = st.get(mk); m20 = m[m.index > (m.index.max() - pd.DateOffset(years=pa["percentile_years"]))] if len(m) else m
        pct = float((m20 <= v).mean() * 100) if (v is not None and len(m20)) else None
        rows.append({"code": c["code"], "name": c["name"], "series": key, "kind": kind, "level": r4(v), "date": str(d.date()) if d is not None else None,
                     "chg_1w": r4(st.change(key, pd.Timedelta(days=7))) if kind == "daily" else None,
                     "chg_1m": r4(st.change(key, pd.DateOffset(months=1))), "chg_12m": r4(st.change(key, pd.DateOffset(years=1))),
                     "pctile_20y": r4(pct), "pctile_basis": f"monthly averages {str(m20.index.min().date())[:7]} to {str(m20.index.max().date())[:7]}" if len(m20) else None,
                     **{"src_" + k: v_ for k, v_ in st.source(key).items() if k in ("source", "label", "retrieved_at", "as_of")}})
        ser = st.get(key)
        chart[c["code"]] = weekly(ser, pa["chart_from"]) if kind == "daily" else [[str(x.date()), r4(y)] for x, y in ser[ser.index >= pa["chart_from"]].items()]
        b_d, b_v = st.at(key, pd.Timestamp(pa["change_from"]) - pd.Timedelta(days=1))
        if b_v is not None:
            sub = ser[ser.index >= pa["change_from"]]
            pts = weekly(sub, pa["change_from"]) if kind == "daily" else [[str(x.date()), r4(y)] for x, y in sub.items()]
            change[c["code"]] = {"base_date": str(b_d.date()), "base": r4(b_v), "points": [[p[0], r4((p[1] - b_v) * 100)] for p in pts]}
    # co-movement: monthly changes of the OECD series over the last 36 months
    mon = pd.concat({c["code"]: st.get(c["monthly"]) for c in cfg["countries"]}, axis=1).dropna()
    dm = mon.diff().dropna().tail(pa["corr_months"])
    corr = dm.corr()
    codes = [c["code"] for c in cfg["countries"]]
    pairs = [corr.loc[a, b] for a, b in itertools.combinations(codes, 2)]
    return {"rows": rows, "chart": chart, "change_since": change,
            "comovement": {"months": int(len(dm)), "through": str(dm.index.max().date())[:7], "from": str(dm.index.min().date())[:7],
                           "avg_pairwise": r4(float(np.mean(pairs))), "vs_us": {k: r4(corr.loc[k, "US"]) for k in codes if k != "US"},
                           "basis": "correlation of monthly changes in the OECD monthly-average 10-year yields (FRED IRLTLT01..M156N)"}}


def panel_b(st: Store, cfg: dict) -> dict:
    pb = cfg["panel_b"]
    def cur(k):
        d, v = st.latest(k)
        return {"value": r4(v), "date": str(d.date()) if d is not None else None,
                "chg_1m": r4(st.change(k, pd.DateOffset(months=1))), "chg_12m": r4(st.change(k, pd.DateOffset(years=1))), **st.source(k)}
    nom, real, be, kw, acm = (st.get(k) for k in ("us10", "us_real10", "us_be10", "us_tp_kw", "us_tp_acm"))
    start = pb["chart_from"]
    b1 = pd.concat({"nominal": nom, "real": real, "breakeven": be}, axis=1)
    b1 = b1[b1.index >= start].dropna()
    esr = (nom - kw).dropna()
    b2 = pd.concat({"nominal": nom, "term_premium_kw": kw, "expected_short_rate": esr, "term_premium_acm": acm}, axis=1, sort=True)
    b2 = b2[b2.index >= start].dropna(subset=["nominal"])
    # identities on the latest common date
    last_b1 = b1.index.max() if len(b1) else None
    gap_b1 = float(b1.loc[last_b1, "nominal"] - b1.loc[last_b1, "real"] - b1.loc[last_b1, "breakeven"]) if last_b1 is not None else None
    common = esr.index.intersection(kw.index)
    last_b2 = common.max() if len(common) else None
    gap_b2 = float(nom.loc[last_b2] - esr.loc[last_b2] - kw.loc[last_b2]) if last_b2 is not None else None
    # the term premium's place in its history
    tpd, tpv = st.latest("us_tp_kw")
    hist = kw[(kw.index < pd.Timestamp(f"{tpd.year}-01-01")) & (kw >= tpv - 1e-9)] if tpd is not None else kw.iloc[:0]
    esr_d = esr.index.max() if len(esr) else None
    return {
        "current": {"nominal": cur("us10"), "real": cur("us_real10"), "breakeven": cur("us_be10"), "term_premium_kw": cur("us_tp_kw"),
                    "term_premium_acm": cur("us_tp_acm"),
                    "expected_short_rate": {"value": r4(esr.iloc[-1]) if len(esr) else None, "date": str(esr_d.date()) if esr_d is not None else None,
                                            "chg_1m": r4(esr.iloc[-1] - esr[esr.index <= esr_d - pd.DateOffset(months=1)].iloc[-1]) if len(esr) > 30 else None,
                                            "chg_12m": r4(esr.iloc[-1] - esr[esr.index <= esr_d - pd.DateOffset(years=1)].iloc[-1]) if len(esr) > 260 else None,
                                            "basis": "the 10-year yield minus the Kim-Wright term premium on the same date"}},
        "b1": {"dates": [str(d.date()) for d in b1.index], "real": [r4(x) for x in b1["real"]], "breakeven": [r4(x) for x in b1["breakeven"]],
               "nominal": [r4(x) for x in b1["nominal"]]},
        "b2": {"dates": [str(d.date()) for d in b2.index], "nominal": [r4(x) for x in b2["nominal"]],
               "expected_short_rate": [r4(x) for x in b2["expected_short_rate"]], "term_premium_kw": [r4(x) for x in b2["term_premium_kw"]],
               "term_premium_acm": [r4(x) for x in b2["term_premium_acm"]]},
        "identities": {"b1_date": str(last_b1.date()) if last_b1 is not None else None, "b1_gap_pp": r4(gap_b1),
                       "b2_date": str(last_b2.date()) if last_b2 is not None else None, "b2_gap_pp": r4(gap_b2),
                       "tolerance_pp": pb["identity_tolerance_pp"]},
        "term_premium_history": {"current": r4(tpv), "date": str(tpd.date()) if tpd is not None else None,
                                 "last_earlier_date_at_or_above": str(hist.index[-1].date()) if len(hist) else None,
                                 "text": (f"the Kim-Wright term premium, {tpv:.2f}% on {tpd.date()}, was last at or above this level before {tpd.year} on "
                                          f"{hist.index[-1].date()}" if len(hist) else f"the Kim-Wright term premium, {tpv:.2f}% on {tpd.date()}, is above every value before {tpd.year} on record")
                                         if tpd is not None else None},
        "caption": ("both term-premium series are model estimates (Kim-Wright: Federal Reserve Board, via FRED; ACM: New York Fed) and can "
                    f"differ; the latest Kim-Wright value is dated {tpd.date() if tpd is not None else '—'}. The expected average short rate is the "
                    "10-year yield minus the Kim-Wright term premium on the same date"),
    }


def _maturity(term: str) -> int | None:
    m = re.match(r"^\s*(\d+)-Year(?:\s+(\d+)-Month)?", str(term or ""))
    if not m:
        return None
    yrs = int(m.group(1)) + (int(m.group(2) or 0) / 12)
    best = min((2, 3, 5, 7, 10, 20, 30), key=lambda t: abs(t - yrs))
    return best if abs(best - yrs) <= 0.5 else None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def panel_c(cfg: dict) -> dict:
    ac = cfg["auctions"]
    j = json.loads(AUCTIONS.read_text()) if AUCTIONS.exists() else {"rows": []}
    rows = []
    for r in j.get("rows", []):
        if str(r.get("inflation_index_security")) == "Yes" or str(r.get("floating_rate")) == "Yes":
            continue
        mat = _maturity(r.get("security_term"))
        if mat not in ac["maturities"]:
            continue
        comp = _f(r.get("comp_accepted")); ind = _f(r.get("indirect_bidder_accepted"))
        rows.append({"date": r.get("auction_date"), "maturity": mat, "security": f"{r.get('security_term')} {r.get('security_type')}",
                     "cusip": r.get("cusip"), "reopening": r.get("reopening"),
                     "size": _f(r.get("offering_amt")), "high_yield": _f(r.get("high_yield")), "bid_to_cover": _f(r.get("bid_to_cover_ratio")),
                     "indirect_share": (ind / comp * 100) if (ind is not None and comp) else None})
    rows.sort(key=lambda x: x["date"])
    today = now_et().date().isoformat()
    done = [r for r in rows if r["high_yield"] is not None and r["bid_to_cover"] is not None]
    upcoming = [r for r in rows if r["date"] >= today and r["high_yield"] is None]
    for i, r in enumerate(done):
        prior = [x for x in done[:i] if x["maturity"] == r["maturity"]][-ac["prior_n"]:]
        if len(prior) < ac["prior_n"]:
            r["comparison"] = None; r["weak"] = None; continue
        ab = float(np.mean([x["bid_to_cover"] for x in prior])); ai = float(np.mean([x["indirect_share"] for x in prior if x["indirect_share"] is not None]))
        db = r["bid_to_cover"] - ab; di = (r["indirect_share"] - ai) if r["indirect_share"] is not None else None
        why = []
        if db < -ac["weak_btc_below_pp"]:
            why.append(f"bid-to-cover {db:+.2f} against the prior six")
        if di is not None and di < -ac["weak_indirect_below_pp"]:
            why.append(f"indirect share {di:+.1f} pp against the prior six")
        r["comparison"] = {"prior_avg_btc": r4(ab), "prior_avg_indirect": r4(ai), "btc_diff": r4(db), "indirect_diff_pp": r4(di),
                           "prior_dates": [x["date"] for x in prior]}
        r["weak"] = bool(why); r["weak_why"] = "; ".join(why) or None
    last = done[-ac["last_n"]:][::-1]
    for r in rows:
        for k in ("size", "high_yield", "bid_to_cover", "indirect_share"):
            r[k] = r4(r[k])
    refund = None
    try:
        ev = json.loads((DATA / "event_calendar.json").read_text()).get("events", [])
        nxt = sorted(e for e in ev if e.get("type") == "REFUNDING" and e.get("date", "") >= today)
        refund = nxt[0] if nxt else None
    except Exception:  # noqa: BLE001
        pass
    return {"source": j.get("source"), "retrieved_at": j.get("retrieved_at"), "last": last,
            "weak_in_last_5": sum(1 for r in done[-5:] if r.get("weak")), "last_5_dates": [r["date"] for r in done[-5:]],
            "upcoming": upcoming[:10],
            "next_refunding": {"date": refund.get("date"), "name": refund.get("name"), "source": refund.get("source") or "event calendar (Treasury quarterly refunding schedule)"} if refund else None,
            "rule": (f"weak: bid-to-cover more than {ac['weak_btc_below_pp']} below the average of the previous {ac['prior_n']} auctions of the same "
                     f"maturity, or the indirect bidders' share of the competitive accepted amount more than {ac['weak_indirect_below_pp']:.0f} "
                     "percentage points below it; descriptive, no claim about the cause")}


def panel_d(st: Store) -> list[dict]:
    out = []
    for k, unit in (("brent", "usd"), ("brent_front", "usd"), ("usdjpy", "fx"), ("jp10", "pct"), ("uk30", "pct"), ("us2", "pct"), ("effr", "pct")):
        d, v = st.latest(k)
        chg = st.change(k, pd.DateOffset(months=1), pct=unit in ("usd", "fx"))
        out.append({"series": k, "unit": unit, "value": r4(v), "date": str(d.date()) if d is not None else None,
                    "chg_1m": r4(chg), "chg_1m_unit": "%" if unit in ("usd", "fx") else "pp", **st.source(k)})
    return out


def panel_e(st: Store, cfg: dict, pc: dict) -> dict:
    out = {}
    for group in ("worsening", "reversal"):
        lst = []
        for s in cfg["signals"][group]:
            if s["kind"] == "weak_in_last_5":
                val, asof = pc["weak_in_last_5"], (pc["last_5_dates"][-1] if pc["last_5_dates"] else None)
            elif s["kind"] == "level_pct":
                d, val = st.latest(s["series"]); asof = str(d.date()) if d is not None else None
            else:
                ch = st.change(s["series"], pd.DateOffset(months=1), pct=s["kind"] == "change_1m_pct")
                val = None if ch is None else (ch * 100 if s["kind"] == "change_1m_bp" else ch)
                d, _ = st.latest(s["series"]); asof = str(d.date()) if d is not None else None
            present = None if val is None else bool(OPS[s["op"]](val, s["threshold"]))
            unit = {"change_1m_bp": "bp", "change_1m_pct": "%", "level_pct": "%", "weak_in_last_5": "auctions"}[s["kind"]]
            rec = {"id": s["id"], "text": s["text"], "series": s["series"], "measured": r4(val), "unit": unit, "op": s["op"],
                   "threshold": s["threshold"], "present": present, "as_of": asof}
            if s.get("also"):                       # shown beside it: the same quantity on the same-day series
                ch2 = st.change(s["also"], pd.DateOffset(months=1), pct=s["kind"] == "change_1m_pct")
                d2, _ = st.latest(s["also"])
                rec["also"] = {"series": s["also"], "measured": r4(ch2), "as_of": str(d2.date()) if d2 is not None else None,
                               "present_on_it": None if ch2 is None else bool(OPS[s["op"]](ch2, s["threshold"]))}
            lst.append(rec)
        out[group] = lst
    out["heading"] = "conditions described by fixed rules: amber when the condition is present, green when absent; a description, not a forecast"
    out["brent_note"] = cfg["signals"].get("brent_note")
    return out


def home(st: Store, cfg: dict) -> list[dict]:
    out = []
    for k in cfg["home_strip"]:
        d, v = st.latest(k)
        ch, prev = st.prev_change(k)
        out.append({"series": k, "label": cfg["series"][k]["label"], "value": r4(v), "date": str(d.date()) if d is not None else None,
                    "chg_1d": r4(ch), "chg_1d_from": prev, "unit": "usd" if k.startswith("brent") else "pct"})
    return out


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    st = Store()
    pa, pb, pc = panel_a(st, cfg), panel_b(st, cfg), panel_c(cfg)
    pd_, pe = panel_d(st), panel_e(st, cfg, pc)
    hs = home(st, cfg)
    d10, v10 = st.latest("us10"); ch10, _ = st.prev_change("us10")
    today = now_et().date().isoformat()
    facts = {"us10": {"value": r4(v10), "date": str(d10.date()) if d10 is not None else None, "chg_1d_pp": r4(ch10)},
             "us_real10": {k: v for k, v in pb["current"]["real"].items() if k in ("value", "date")},
             "us_be10": {k: v for k, v in pb["current"]["breakeven"].items() if k in ("value", "date")},
             "us_tp_kw": {k: v for k, v in pb["current"]["term_premium_kw"].items() if k in ("value", "date")},
             "jp10": {"value": r4(st.latest("jp10")[1]), "date": str(st.latest("jp10")[0].date())},
             "brent_front": {"value": r4(st.latest("brent_front")[1]), "date": str(st.latest("brent_front")[0].date()), "label": "front-month future (price provider), same-day value"},
             "weak_auctions_today": [r for r in pc["last"] if r.get("weak") and r["date"] == today]}
    as_of = max((v.get("as_of") or "") for v in st.meta.values()) or today
    payload = {"cadence": "daily", "as_of": as_of, "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "order": "Execution Order: Global Rates Panels on the Bonds Page (6 October 2026)",
               "note": "descriptive: levels, changes and fixed-rule conditions; no forecast and no recommendation",
               "series_meta": {k: st.source(k) for k in cfg["series"]},
               "panel_a": pa, "panel_b": pb, "panel_c": pc, "panel_d": pd_, "panel_e": pe, "home": hs, "facts": facts,
               "footnotes": {"uk": "United Kingdom yields are the Bank of England's nominal zero-coupon curve; they differ by a few basis points from the benchmark gilt yields quoted in the press",
                             "monthly": "France and Italy have no free daily official series here: their rows are OECD monthly averages (FRED), about a month behind",
                             "brent": "Brent spot (EIA, via FRED) is published several days late; the price provider's front-month future gives the same-day value and is labelled as such"}}
    # the August-2026-style monthly averages beside the latest daily levels (Panel A shows both)
    for r in pa["rows"]:
        mk = next(c["monthly"] for c in cfg["countries"] if c["code"] == r["code"])
        md, mv = st.latest(mk)
        r["monthly_level"], r["monthly_date"] = r4(mv), (str(md.date())[:7] if md is not None else None)
    OUT.write_text(json.dumps(payload, indent=1, default=str, allow_nan=False))
    # the home page loads only the strip and the facts (a few hundred bytes, not the panels)
    (RATES / "global_rates_home.json").write_text(json.dumps({"cadence": "daily", "as_of": as_of, "computed_at": payload["computed_at"],
                                                              "home": hs, "facts": facts, "note": payload["note"]}, indent=1, default=str))
    pres = [s["id"] for g in ("worsening", "reversal") for s in pe[g] if s["present"]]
    log(f"panels written: A {len(pa['rows'])} countries (co-movement {pa['comovement']['avg_pairwise']} through {pa['comovement']['through']}), "
        f"B identities {pb['identities']['b1_gap_pp']}/{pb['identities']['b2_gap_pp']} pp, C {len(pc['last'])} auctions ({pc['weak_in_last_5']} weak in the last 5), "
        f"E present: {pres or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
