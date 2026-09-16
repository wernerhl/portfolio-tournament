# Relocated 2026-09-16 (order 6.1) from portfolio-screener/scripts/build_json.py — paths changed (one repository: config scripts/screen/config.json, served data data/screen/), nothing else.
"""
JSON output wrapper for the scoring model.
Reads scripts/screen/config.json (settings + category tags) and this repository's
data/holdings.json (the book — order 3.1, one holdings source; local since
order 6.1), runs scoring, outputs data/screen/scores.json for the frontend.
"""
import json, sys, os
import numpy as np
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

# Patch the scoring script to use config
ROOT = Path(__file__).resolve().parent.parent.parent      # the tournament repository (order 6.1: one repo)
CONFIG = Path(__file__).resolve().parent / "config.json"  # scripts/screen/config.json
OUTPUT = ROOT / "data" / "screen" / "scores.json"

def load_config():
    with open(CONFIG) as f:
        return json.load(f)

DATA = ROOT / "data" / "screen"      # the screen view's served data directory


def _write_status(path, ok, reason, session_date, computed_at):
    """[5] data/status.json — written on BOTH success and rejection; the
    frontend staleness badge reads it. Rejection preserves last_success."""
    prev = {}
    try:
        with open(path) as f:
            prev = json.load(f)
    except Exception:
        pass
    st = {
        'last_attempt': computed_at,
        'last_success': computed_at if ok else prev.get('last_success'),
        'failure_reason': None if ok else str(reason),
        'session_date': session_date,
    }
    with open(path, 'w') as f:
        json.dump(st, f, indent=1)


def _expected_session(now_et):
    """Most recent completed NYSE session, weekday approximation (holidays
    not modeled — a holiday mismatch rejects and needs --force-publish;
    recorded as a known limitation in the report)."""
    from datetime import timedelta
    d = now_et.date()
    if now_et.weekday() < 5 and (now_et.hour, now_et.minute) >= (16, 15):
        return str(d)
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return str(d)


def main():
    # yfinance's sqlite caches (tz/cookies) are shared per-user and throw
    # 'database is locked' under concurrent access — one such lock killed
    # TSM's price top-up on 08-07 and blocked that publish. Isolate per run.
    try:
        import yfinance as _yf, tempfile
        _yf.set_tz_cache_location(tempfile.mkdtemp(prefix="yfcache_"))
    except Exception:
        pass

    # [5] Run guard: publish only after the close (>=16:15 ET) on trading
    # days, or under --force-publish REASON. Otherwise every output routes to
    # data/screen/scratch/<ts>/ — a manual midday run can no longer overwrite the
    # served board. Non-trading days pass the clock gate (no session hazard).
    import argparse
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    ap = argparse.ArgumentParser()
    ap.add_argument('--force-publish', metavar='REASON', default=None,
                    help='publish despite the session guard; reason recorded in provenance')
    args, _unknown = ap.parse_known_args()

    now_et = _dt.now(ZoneInfo("America/New_York"))
    is_weekday = now_et.weekday() < 5
    after_close = (now_et.hour, now_et.minute) >= (16, 15)
    forced = args.force_publish is not None
    publish = (not is_weekday) or after_close or forced
    computed_at = now_et.isoformat(timespec='seconds')

    scratch_dir = None
    if not publish:
        scratch_dir = DATA / "scratch" / now_et.strftime('%Y%m%d-%H%M%S')
        scratch_dir.mkdir(parents=True, exist_ok=True)
        print(f"[5] RUN GUARD: {now_et.strftime('%H:%M ET')} is pre-close on a trading day "
              f"and no --force-publish given → SCRATCH MODE ({scratch_dir.relative_to(ROOT)})")

    config = load_config()

    # Monkey-patch the portfolio and midcap list into score_universe
    import score_universe as su

    # Order 3.1 (2026-09-09): ONE holdings source. The book comes from the
    # tournament repo's data/holdings.json — this repository's since order 6.1
    # (before that read cross-repository, exactly like the canonical
    # fundamentals artifact (#92)). The screener's own
    # config["portfolio"] list and its "cash" are gone; only the per-ticker
    # category tag stays here (config["holding_categories"], default "Core").
    # No source → rejection: status.json records it ([5] semantics), the run
    # stops, the last good board stays served.
    status_path = (scratch_dir or DATA) / "status.json"
    try:
        holdings_blob, holdings_prov = su.fetch_holdings()
    except (SystemExit, Exception) as e:
        _write_status(status_path, ok=False, reason=e, session_date=None,
                      computed_at=computed_at)
        print(f"::error::{e}")
        raise
    categories = config.get("holding_categories", {})
    portfolio = {                                   # same per-ticker shape as before
        h["ticker"]: {"shares": h["shares"], "cost": h["cost_basis"],
                      "category": categories.get(h["ticker"], "Core")}
        for h in holdings_blob["holdings"] if (h.get("shares") or 0) > 0
    }
    cash = holdings_blob.get("cash", 0) or 0
    print(f"  book: {len(portfolio)} positions {sorted(portfolio)} + cash {cash:,.2f} "
          f"(holdings.json as_of {holdings_prov.get('as_of')}, {holdings_prov['mode']})")

    # Set portfolio weights (normalize)
    su.CURRENT_PORTFOLIO = su.portfolio_weights(holdings_blob["holdings"])

    # Set midcap additions
    su.MIDCAP_ADDITIONS = config.get("midcap_additions", [])

    # Broken-base cap + visibility governance knobs (plan 2.3 / 2.5)
    bb = config.get("broken_base", {})
    su.BROKEN_BASE_GAP_PCT  = float(bb.get("gap_pct",  su.BROKEN_BASE_GAP_PCT))
    su.BROKEN_BASE_RSI      = float(bb.get("rsi",      su.BROKEN_BASE_RSI))
    su.BROKEN_BASE_TECH_CAP = float(bb.get("tech_cap", su.BROKEN_BASE_TECH_CAP))
    su.VISIBILITY_FALLBACK_CAP = float(config.get("visibility_fallback_cap",
                                                  su.VISIBILITY_FALLBACK_CAP))
    
    # Order 9-Sept A2 — visibility retirement archival pass. An override that
    # has passed two consecutive earnings cycles without review is moved to
    # registry['retired'] with its full record (history preserved), removed
    # from entries, and logged in policy_events. Scoring then uses the sector
    # prior. Returning it requires a human re-registration with a fresh
    # rationale and date. Never touches an entry that has been reviewed.
    try:
        from datetime import date as _date
        vreg_p = DATA / "visibility_registry.json"
        vreg = json.load(open(vreg_p))
        vreg.setdefault("policy", {})["retirement"] = (
            "two consecutive earnings cycles without review → retire to the sector prior, "
            "archive with history; re-registration (fresh rationale + date) required to restore")
        retired_now = []
        today = _date.today().isoformat()
        for tk in list((vreg.get("entries") or {}).keys()):
            e = vreg["entries"][tk]
            ra = su.visibility_retire_at(e)
            if ra and today >= ra:
                rec = dict(e); rec.update({"ticker": tk, "retired_at": today, "retire_rule_date": ra,
                                           "reason": "two consecutive earnings cycles without review"})
                vreg.setdefault("retired", []).append(rec)
                del vreg["entries"][tk]
                retired_now.append(tk)
        if retired_now:
            vreg.setdefault("policy_events", []).append({"date": today, "event": "retired", "tickers": retired_now})
            with open(vreg_p, "w") as f:
                json.dump(vreg, f, indent=1)
            print(f"  visibility retirement: archived {retired_now}")
    except Exception as e:
        print(f"  WARNING visibility retirement pass skipped: {type(e).__name__}: {e}")

    # [5] scratch mode redirects every score_universe output too
    if scratch_dir is not None:
        su.OUTPUT_DIR = scratch_dir

    # Run the main scoring pipeline
    su.main()

    # Now convert CSV output to JSON for the frontend
    import pandas as pd
    from datetime import datetime

    csv_path = (scratch_dir or DATA) / "scored_universe.csv"
    if not csv_path.exists():
        print("ERROR: scored_universe.csv not found")
        return
    
    df = pd.read_csv(csv_path)
    
    # Build portfolio summary
    portfolio_summary = []
    for ticker, holdings in portfolio.items():
        row = df[df['ticker'] == ticker]
        if len(row) > 0:
            r = row.iloc[0]
            current_price = r.get('current_price', 0)
            cost = holdings.get('cost', 0)
            shares = holdings.get('shares', 0)
            gain_pct = ((current_price / cost) - 1) * 100 if cost > 0 else 0
            portfolio_summary.append({
                'ticker': ticker,
                'name': r.get('name', ticker),
                'shares': shares,
                'cost': cost,
                'current_price': round(current_price, 2),
                'market_value': round(current_price * shares, 2),
                'gain_pct': round(gain_pct, 1),
                'category': holdings.get('category', 'Core'),
                'composite': round(r.get('composite', 0), 1),
                'fundamental': round(r.get('fundamental', 0), 1),
                'technical': round(r.get('technical', 0), 1),
                'visibility': round(r.get('visibility', 0), 1),
            })
    
    total_equity_value = sum(p['market_value'] for p in portfolio_summary)
    # cash: from holdings.json (loaded above), not from this repo's config
    total_value = total_equity_value + cash
    
    # Build watchlist — INCLUDE held names (you can always add to a position).
    # Held names stay in the ranking, flagged `held:true` so the frontend can
    # tag them as add-to-position candidates rather than hiding them. Top 40 so
    # the held names don't crowd out fresh ideas.
    portfolio_tickers = set(portfolio.keys())
    watchlist_df = df.head(40)
    # Order 16-Sept 1.2: held names are always in the universe and always on the
    # board. A held name outside the top 40 is appended with its true rank and
    # flagged held (it is scored like any other name; the board just never
    # hides the book). The top-40 ordering above it is unchanged.
    held_extra = df[df['ticker'].isin(portfolio_tickers) & ~df['ticker'].isin(watchlist_df['ticker'])]
    if len(held_extra):
        print(f"  board: appending held names outside the top 40: {held_extra['ticker'].tolist()}")
        watchlist_df = pd.concat([watchlist_df, held_extra])

    import math

    def _num(x, nd=3):
        """Coerce to a rounded float, or None for NaN/empty/None — typed
        numeric fields are a number or null, never '' or NaN."""
        try:
            if x is None or (isinstance(x, str) and not x.strip()):
                return None
            v = float(x)
            return None if (math.isnan(v) or math.isinf(v)) else round(v, nd)
        except (TypeError, ValueError):
            return None

    watchlist = []
    for _, r in watchlist_df.iterrows():
        watchlist.append({
            'rank': int(r.get('rank', 0)) if 'rank' in r else int(_ + 1),
            'ticker': r['ticker'],
            'held': bool(r.get('in_portfolio', False)) or (r['ticker'] in portfolio_tickers),
            'on_board_as': 'top40' if (int(r.get('rank', 0)) if 'rank' in r else int(_ + 1)) <= 40 else 'held',   # 1.2
            'name': r.get('name', ''),
            'sector': r.get('sector', ''),
            'category': r.get('category', ''),
            'mcap_B': round(r.get('mcap_B', 0), 1),
            'current_price': round(r.get('current_price', 0), 2),
            'entry_level': round(r.get('entry_level', 0), 2),
            'composite': round(r.get('composite', 0), 1),
            'fundamental': round(r.get('fundamental', 0), 1),
            'technical': round(r.get('technical', 0), 1),
            'visibility': round(r.get('visibility', 0), 1),
            'broken_base': bool(r.get('broken_base', False)),
            # None = correlation unavailable (visible impairment) — never 0-filled
            'corr_penalty': _num(r.get('corr_penalty'), 1),
            'corr_status': r.get('corr_status', 'ok') if isinstance(r.get('corr_status'), str) else 'ok',
            'corr_null_reason': (r.get('corr_null_reason') if isinstance(r.get('corr_null_reason'), str) else None),
            'leverage_penalty': _num(r.get('leverage_penalty'), 1),   # #93
            'lev_status': r.get('lev_status', 'ok') if isinstance(r.get('lev_status'), str) else 'ok',
            'nd_ebitda': _num(r.get('nd_ebitda'), 2),
            'portfolio_corr': _num(r.get('portfolio_corr')),
            'max_corr': _num(r.get('max_corr')),
            'max_corr_with': (r.get('max_corr_with') if isinstance(r.get('max_corr_with'), str) and r.get('max_corr_with') else None),
            # Typed fields: fwd_pe is a P/E ratio or null; fcf_yield_pct is a
            # percent or null. Never fall back across semantic types.
            'fwd_pe': _num(r.get('fwd_pe'), 1),
            'fcf_yield_pct': _num(r.get('fcf_yield_pct'), 1),
            'data_flags': r.get('data_flags', '') if isinstance(r.get('data_flags'), str) else '',
            'rev_growth_pct': r.get('rev_growth_pct', ''),
            'gross_margin_pct': r.get('gross_margin_pct', ''),
            'rsi': r.get('rsi', ''),
        })
    
    # Full universe stats
    universe_stats = {
        'total': len(df),
        'median_score': round(df['composite'].median(), 1),
        'mean_score': round(df['composite'].mean(), 1),
        'max_score': round(df['composite'].max(), 1),
        'min_score': round(df['composite'].min(), 1),
        'sectors': df['sector'].value_counts().to_dict(),
        'categories': df['category'].value_counts().to_dict(),
    }
    
    # ── CI tripwires ─────────────────────────────────────────────────────
    # Fail the build LOUDLY rather than publish a silently impaired board.
    # July 2026 lesson: the correlation column died to all-zeros for weeks and
    # nothing noticed, because nothing asserted anything.
    def validate_outputs(df, watchlist):
        # 1) Correlation column must be ALIVE. Against a 4-megacap tech book,
        #    something in a 500+ name universe must correlate > 0.3 (market
        #    beta alone guarantees it). All null/zero → computation dead.
        # column-missing-safe: a vanished column must REJECT, not crash
        import numpy as _np
        _col = lambda c: (pd.to_numeric(df[c], errors='coerce') if c in df.columns
                          else pd.Series(_np.nan, index=df.index))
        mc, pc = _col('max_corr'), _col('portfolio_corr')
        n_alive = int(((mc.abs() > 0.3) | (pc.abs() > 0.3)).sum())
        if n_alive == 0:
            raise SystemExit(
                "CI FAIL: correlation column is dead — no name in the universe "
                "shows |corr| > 0.3 vs the portfolio. The computation is broken "
                "(this exact failure shipped silently in July 2026); refusing to publish.")

        # 1b) [3] Coverage: share of scored names with corr_status == 'ok'.
        #     <60% fails the build; <90% publishes with an amber banner
        #     (frontend reads corr_coverage_pct). Every null carries a reason.
        status = df.get('corr_status').fillna('') if 'corr_status' in df else pd.Series('', index=df.index)
        ok_mask = status == 'ok'
        coverage = 100.0 * float(ok_mask.sum()) / max(len(df), 1)
        impaired = []
        for _, r in df[~ok_mask].iterrows():
            reason = r.get('corr_null_reason')
            if not isinstance(reason, str) or not reason:
                raise SystemExit(f"CI FAIL: unexplained correlation null for {r['ticker']} "
                                 "(every null must carry corr_null_reason)")
            impaired.append({'ticker': r['ticker'], 'reason': reason})
        if coverage < 60:
            raise SystemExit(f"CI FAIL: correlation coverage {coverage:.1f}% < 60%")
        # [3] names that must be alive: current book + the named list + top-40
        # (top-40/book may alternatively appear in impaired with a reason —
        # the named seven must be strictly alive)
        must_alive = ['ANET', 'CRDO', 'MU', 'ALAB', 'QCOM', 'ARM', 'TSM']
        alive_set = set(df[ok_mask]['ticker'])
        for t in must_alive:
            if t not in alive_set:
                raise SystemExit(f"CI FAIL: {t} is not corr-alive (order item 3.3 names it explicitly)")
        reasoned = {i['ticker'] for i in impaired}
        for t in list(portfolio_tickers) + [e['ticker'] for e in watchlist]:
            if t not in alive_set and t not in reasoned:
                raise SystemExit(f"CI FAIL: {t} (book/top-40) neither corr-alive nor reasoned")

        # 2) Typed ranges (defense in depth — score_universe nulls at source)
        #    [2] fcf bounds widened to [-60, 30]: the check catches corruption,
        #    not true deep-burn readings (NBIS -15.6% is a real value signal).
        for e in watchlist:
            if e['fwd_pe'] is not None and not (3 <= e['fwd_pe'] <= 150):
                raise SystemExit(f"CI FAIL: fwd_pe out of range for {e['ticker']}: {e['fwd_pe']}")
            if e['fcf_yield_pct'] is not None and not (-60 <= e['fcf_yield_pct'] <= 30):
                raise SystemExit(f"CI FAIL: fcf_yield_pct out of range for {e['ticker']}: {e['fcf_yield_pct']}")
        # 3) Structural floors
        if len(watchlist) < 30:
            raise SystemExit(f"CI FAIL: watchlist collapsed to {len(watchlist)} rows")
        # #93 leverage module must be ALIVE (the corr-column lesson): if the
        # status column is overwhelmingly 'unavailable', the input feed died.
        lev_ok = df['lev_status'].isin(['ok', 'de_fallback', 'financial_na',
                                        'neg_ebitda_debt', 'neg_ebitda_low_debt']).sum()
        if lev_ok < 0.8 * len(df):
            raise SystemExit(f"CI FAIL: leverage module dead — only {lev_ok}/{len(df)} "
                             "names have a computable leverage status")

        # #92 sample equality assert (plan 4.1): when the canonical artifact
        # was consumed, N sampled tickers must match it exactly — catches
        # partial consumption or mutation between source and board.
        ds = getattr(su, 'DATA_SOURCE', {})
        if ds.get('mode') == 'canonical':
            import json as _json, urllib.request
            base = ds['base']
            fp = f"{base}/data/canonical/fundamentals.json"
            blob = (_json.loads(Path(fp).read_text()) if not base.startswith('http')
                    else _json.loads(urllib.request.urlopen(fp, timeout=30).read()))
            canon = blob['tickers']
            used = getattr(su, 'FUNDAMENTALS_USED', {})
            sample = [t for t in list(canon)[::max(1, len(canon)//10)][:10] if t in used]
            for t in sample:
                for f in ('marketCap', 'forwardPE'):
                    if canon[t].get(f) != used[t].get(f):
                        raise SystemExit(f"CI FAIL: canonical equality broken for {t}.{f}: "
                                         f"canonical={canon[t].get(f)} consumed={used[t].get(f)}")
            print(f"  canonical equality assert: OK on {len(sample)} sampled tickers")

        # Floor tightened 400->500 (2026-07-30): the 19:00 ET run scored 423
        # names (113 Yahoo failures) and PASSED the 400 floor — only the
        # named-seven assert saved the publish. 500/535 = 93% minimum.
        if len(df) < 500:
            raise SystemExit(f"CI FAIL: scored universe collapsed to {len(df)} rows "
                             "(535 expected — Wikipedia-fallback-style regression?)")
        print(f"  validate_outputs: OK  (corr alive {n_alive}, coverage {coverage:.1f}%, "
              f"{len(impaired)} impaired w/reasons, {len(watchlist)} watchlist, {len(df)} scored)")
        return {'coverage_pct': round(coverage, 1), 'impaired': impaired}

    # [5] session-equality check (publish mode) + status.json on both outcomes
    session_date = getattr(su, 'LAST_PRICE_DATE', None)
    try:
        # forced publishes bypass the session check too (the reason is in
        # provenance) — force overrides the guard, not just the clock
        if publish and not forced and session_date != _expected_session(now_et):
            raise SystemExit(f"CI FAIL: data session {session_date} != current session "
                             f"{_expected_session(now_et)} — refusing to publish stale/partial data")
        covmeta = validate_outputs(df, watchlist)
    except (SystemExit, Exception) as e:   # ANY validation crash = failed run:
        _write_status(status_path, ok=False, reason=e, session_date=session_date,
                      computed_at=computed_at)      # status.json still lands
        print(f"::error::{e}")
        raise
    _write_status(status_path, ok=True, reason=None, session_date=session_date,
                  computed_at=computed_at)

    # [4] Drawdown-watch shelf: broken-base names whose BUSINESS clears the
    # quality bar (fundamental >= 18/25 AND visibility >= 15/25), ranked by
    # fundamental + visibility ONLY (capped technical displayed, not ranked).
    # Max 15 rows. Names with the tag that miss the bar stay in the main list.
    ddf = df[df.get('broken_base') == True].copy() if 'broken_base' in df else df.iloc[0:0].copy()
    if len(ddf):
        ddf['_f'] = pd.to_numeric(ddf['fundamental'], errors='coerce')
        ddf['_v'] = pd.to_numeric(ddf['visibility'], errors='coerce')
        ddf = ddf[(ddf['_f'] >= 18) & (ddf['_v'] >= 15)]
        ddf = ddf.sort_values(by=['_f', '_v'], ascending=False, key=None)
        ddf['_q'] = ddf['_f'] + ddf['_v']
        ddf = ddf.sort_values('_q', ascending=False).head(15)
    drawdown_watch = []
    for _, r in ddf.iterrows():
        ep = float(r.get('entry_level') or 0)
        cp = float(r.get('current_price') or 0)
        drawdown_watch.append({
            'ticker': r['ticker'], 'name': r.get('name', ''), 'sector': r.get('sector', ''),
            'fundamental': _num(r.get('fundamental'), 1), 'visibility': _num(r.get('visibility'), 1),
            'technical_capped': _num(r.get('technical'), 1), 'composite': _num(r.get('composite'), 1),
            'quality_rank_score': _num(r.get('_q'), 1),
            'depth_below_base_pct': round((cp / ep - 1) * 100, 1) if ep and cp else None,
            'rsi': _num(r.get('rsi'), 1),
            'corr_penalty': _num(r.get('corr_penalty'), 1),
            'portfolio_corr': _num(r.get('portfolio_corr')),
            'max_corr_with': (r.get('max_corr_with') if isinstance(r.get('max_corr_with'), str) else None),
        })

    # Assemble output
    output = {
        # SEPT AUDIT [8.3]: naive-UTC 'updated' removed — session_date and
        # computed_at (ET, tz-aware) are the authoritative declared dates.
        'session_date': session_date,          # [5] the session this data represents
        'computed_at': computed_at,            # [5] when it was computed (ET)
        'provenance': {                        # [5] forced publishes carry their reason
            'mode': 'publish' if publish else 'scratch',
            'forced_publish': bool(forced),
            'force_reason': args.force_publish,
            'data_source': getattr(su, 'DATA_SOURCE', {'mode': 'direct'}),   # #92
            'holdings_source': holdings_prov,      # order 3.1: where the book came from
        },
        'corr_coverage_pct': covmeta['coverage_pct'],   # [3]
        'corr_impaired': covmeta['impaired'],           # [3] every null + reason
        'drawdown_watch': drawdown_watch,               # [4]
        'portfolio': {
            'holdings': portfolio_summary,
            'total_equity': round(total_equity_value, 2),
            'cash': cash,
            'total_value': round(total_value, 2),
            'equity_pct': round(total_equity_value / total_value * 100, 1) if total_value > 0 else 0,
            'cash_pct': round(cash / total_value * 100, 1) if total_value > 0 else 0,
        },
        'watchlist': watchlist,
        'universe': universe_stats,
    }
    
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)): return int(obj)
            if isinstance(obj, (np.floating,)): return float(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return super().default(obj)

    # Sanitize NaN/Infinity → null. Python's json.dump emits literal `NaN`
    # (valid for Python, INVALID for the browser's JSON.parse — it throws
    # "Unexpected token N" and the page renders "No data found"). This bit
    # when the universe grew to 535 + held names were included: names with
    # no correlation match carry max_corr_with = NaN. allow_nan=False makes
    # any future NaN a loud CI failure instead of a silently-broken page.
    import math
    def _clean(o):
        if isinstance(o, dict):  return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, list):  return [_clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
        if isinstance(o, (np.floating,)):
            x = float(o); return None if (math.isnan(x) or math.isinf(x)) else x
        return o

    out_path = (scratch_dir / "scores.json") if scratch_dir is not None else OUTPUT
    with open(out_path, 'w') as f:
        json.dump(_clean(output), f, indent=2, cls=NpEncoder, allow_nan=False)

    print(f"\nJSON output: {out_path}")
    print(f"Portfolio: {len(portfolio_summary)} positions, ${total_equity_value:,.0f} equity + ${cash:,.0f} cash = ${total_value:,.0f}")
    print(f"Watchlist: {len(watchlist)} candidates")

    # Daily as-published vintage (plan 2.7a): immutable copies under
    # data/screen/vintages/<date>/ — the tournament's published-vintage convention.
    # This is what makes the pre-registered forward validation (Spearman IC on
    # frozen vintages, first evaluation Feb 2027) possible at all.
    # [5] PUBLISH MODE ONLY: vintages are as-published records by definition;
    # scratch runs never mint one.
    if publish:
        import shutil
        vint = DATA / "vintages" / (session_date or datetime.now().strftime("%Y-%m-%d"))
        vint.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_path, vint / "scores.json")
        for fn in ("scored_universe.csv", "watchlist_top30.csv"):
            src = DATA / fn
            if src.exists():
                shutil.copy2(src, vint / fn)
        print(f"Vintage archived: {vint.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
