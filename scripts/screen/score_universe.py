# Relocated 2026-09-16 (order 6.1) from portfolio-screener/scripts/score_universe.py — paths changed (one repository: served data data/screen/, canonical artifact + holdings + universe local), nothing else.
"""
Portfolio Scoring Model — Universe Screener
============================================
Screens S&P 500 + 50 AI/infrastructure mid-caps.
Computes 4-factor score: Fundamental Quality, Technical Positioning,
Visibility/Backlog, and Correlation Penalty.
Outputs ranked watchlist with entry levels.

Usage:
    python score_universe.py

Output:
    data/screen/scored_universe.csv   — full scored universe
    data/screen/watchlist_top30.csv   — top 30 candidates with entry levels
    data/screen/portfolio_report.txt  — summary report
"""

import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')

try:
    import yfinance as yf
except ImportError:
    os.system(f"{sys.executable} -m pip install yfinance --break-system-packages -q")
    import yfinance as yf

# ── Configuration ──────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent.parent   # the tournament repository (order 6.1: one repo)
OUTPUT_DIR = ROOT / "data" / "screen"                    # the screen view's served data directory
OUTPUT_DIR.mkdir(exist_ok=True)
LAST_PRICE_DATE = None   # [5] set by main() after the price fetch

# Current portfolio weights (fraction of equity, for the correlation penalty).
# Order 3.1 (2026-09-09): ONE holdings source — the tournament repo's
# data/holdings.json, read cross-repository by fetch_holdings() below. No
# hardcoded book lives here any more: build_json.py fills this before main(),
# and a standalone run fills it from the same file inside main().
CURRENT_PORTFOLIO = {}

# The 50 mid-cap AI/infrastructure additions beyond S&P 500
MIDCAP_ADDITIONS = [
    # AI Infrastructure — Connectivity & Networking
    "CRDO",   # Credo Technology — AEC cables
    "ALAB",   # Astera Labs — PCIe retimers
    "COHR",   # Coherent — photonics
    "LITE",   # Lumentum — optical components
    "CIEN",   # Ciena — networking
    "CALX",   # Calix — cloud networking
    "FN",     # Fabrinet — optical manufacturing

    # AI Infrastructure — Semicap & Test
    "ONTO",   # Onto Innovation — process control
    "ACMR",   # ACM Research — wet processing
    "AEHR",   # Aehr Test — burn-in testing
    "PLAB",   # Photronics — photomasks
    "COHU",   # Cohu — test equipment
    "UCTT",   # Ultra Clean — parts & gas delivery
    "KLIC",   # Kulicke & Soffa — bonding equipment

    # AI Power & Grid
    "TLN",    # Talen Energy — nuclear
    "NRG",    # NRG Energy — power generation
    "OKLO",   # Oklo — SMR nuclear
    "BWXT",   # BWX Technologies — nuclear
    "POWL",   # Powell Industries — electrical equipment

    # AI Cloud / HPC
    "CRWV",   # CoreWeave — AI cloud (if public)
    "NBIS",   # Nebius — AI cloud
    "DLR",    # Digital Realty — data center REIT
    "EQIX",   # Equinix — data center REIT
    "QTS",    # QTS Realty (if still public)

    # AI Software / Applications
    "PLTR",   # Palantir
    "AI",     # C3.ai
    "SOUN",   # SoundHound
    "BBAI",   # BigBear.ai
    "PATH",   # UiPath
    "ESTC",   # Elastic
    "MDB",    # MongoDB
    "CFLT",   # Confluent
    "DDOG",   # Datadog

    # Quantum
    "IONQ",   # IonQ
    "RGTI",   # Rigetti
    "QBTS",   # D-Wave

    # Other thematic
    "MRVL",   # Marvell — custom silicon #2
    "ARM",    # ARM Holdings — royalty model
    "SMCI",   # Super Micro — AI servers
    "DELL",   # Dell — servers
    "PSTG",   # Pure Storage
    "WDC",    # Western Digital
    "WOLF",   # Wolfspeed — SiC
    "GEV",    # GE Vernova
    "VST",    # Vistra — power
    "IREN",   # IREN — HPC hosting
    "WULF",   # TeraWulf — HPC hosting
    "APLD",   # Applied Digital — HPC hosting
    "CIFR",   # Cipher Mining
]


# ── S&P 500 Tickers ───────────────────────────────────────────────────

# ── Broken-base cap (plan 2.3 — Werner approved 2026-07-29) ───────────
# A name trading >GAP% below its base with RSI<RSI_MAX is a falling knife,
# not an entry: cap the technical score so the board stops ranking the
# most-drawn-down names on top. They stay listed, tagged 'broken_base'.
# Overridden from config.json "broken_base" via build_json.
BROKEN_BASE_GAP_PCT  = 10.0
BROKEN_BASE_RSI      = 25.0
BROKEN_BASE_TECH_CAP = 12.0

# ── Visibility governance (plan 2.5) ──────────────────────────────────
# Sector priors shared by the legacy path and the registry fallback.
SECTOR_VIS_PRIORS = {
    'Utilities': 18,
    'Consumer Defensive': 16,
    'Healthcare': 15,
    'Financial Services': 14,
    'Industrials': 14,
    'Technology': 13,
    'Communication Services': 13,
    'Basic Materials': 11,
    'Consumer Cyclical': 11,
    'Energy': 12,
    'Real Estate': 15,
}
# In registry mode, a name with NO researched override earns at most this
# much of the 25-pt factor from sector priors alone — an un-researched
# "visibility" score is unearned judgment (the old fallback gave a bitcoin
# miner 16/25). Config-tunable: "visibility_fallback_cap".
VISIBILITY_FALLBACK_CAP = 10.0
VIS_REGISTRY = None   # set in main() from data/visibility_registry.json


def load_visibility_registry():
    """Governed replacement for the hardcoded VISIBILITY_OVERRIDES (per-entry
    rationale, review dates, decay — the thesis-registry pattern). ACTIVE ONLY
    ONCE FROZEN (Werner-approved); until then the legacy dict stays
    authoritative and we say so loudly. Never auto-merged."""
    import json as _json
    reg_path = ROOT / "data" / "screen" / "visibility_registry.json"
    if not reg_path.exists():
        return None
    try:
        reg = _json.loads(reg_path.read_text())
    except Exception as e:
        print(f"  WARNING: visibility_registry.json unreadable ({e}) — legacy overrides in effect")
        return None
    if not reg.get("frozen_at"):
        print(f"  visibility registry v{reg.get('version')} PENDING APPROVAL — legacy overrides in effect")
        return None
    print(f"  visibility registry v{reg.get('version')} ACTIVE (frozen {reg.get('frozen_at')}, "
          f"{len(reg.get('entries', {}))} entries)")
    return reg


def visibility_retire_at(entry: dict) -> str | None:
    """Order 9-Sept A2: the date an unreviewed override retires to the sector
    prior — two consecutive earnings cycles without review. Earnings-anchored
    entries: the second earnings after the last review (next_earnings + ~91d)
    plus the 14-day grace; 180-day-cadence entries: as_of + 182d + 14d.
    A review (new as_of / next_earnings) resets the clock."""
    from datetime import date as _date, timedelta as _td
    try:
        as_of = _date.fromisoformat(str(entry.get('as_of') or '')[:10])
    except ValueError:
        return None
    cadence = str(entry.get('cadence') or '')
    try:
        if cadence.startswith('earnings') and entry.get('next_earnings'):
            anchor = _date.fromisoformat(str(entry['next_earnings'])[:10])
            return (anchor + _td(days=91 + 14)).isoformat()
    except ValueError:
        pass
    return (as_of + _td(days=182 + 14)).isoformat()


def visibility_from_registry(fund_data, ticker):
    """Registry-mode visibility: frozen entry value with review-decay, or the
    capped sector fallback. Decay (Werner's cadence spec, 2026-07-29): past
    review_by the override decays LINEARLY to the sector prior over 90 days.
    Hard triggers (guidance cut, backlog decline, cancelled PPA) override the
    calendar — those arrive as registry edits, not computed here."""
    from datetime import date
    sector = (fund_data or {}).get('sector', '')
    prior = min(SECTOR_VIS_PRIORS.get(sector, 12.5), VISIBILITY_FALLBACK_CAP)

    entry = VIS_REGISTRY.get('entries', {}).get(ticker)
    if entry:
        val = float(entry['value'])
        details = {'override': entry.get('rationale', ''), 'registry': True}
        # Order 9-Sept A2 — retirement: an override that passes TWO consecutive
        # earnings cycles without review retires to the sector prior (the
        # nightly archival pass in build_json moves it to registry['retired']
        # with its history; returning requires re-registration with a fresh
        # rationale and date). The system no longer depends on the operator's
        # promptness; decay covers the first missed cycle, retirement the second.
        retire_at = visibility_retire_at(entry)
        details['retire_at'] = retire_at
        if retire_at and date.today().isoformat() >= retire_at:
            return round(prior, 1), {'override': entry.get('rationale', ''), 'registry': True,
                                     'retired': True, 'retired_at': retire_at,
                                     'vis_status': 'retired — two earnings cycles without review; '
                                                   'sector prior applies; re-register to restore'}
        rb = entry.get('review_by')
        if rb:
            try:
                days_late = (date.today() - date.fromisoformat(rb)).days
            except ValueError:
                days_late = 0
            if days_late > 0:
                w = max(0.0, 1.0 - days_late / 90.0)
                val = prior + (val - prior) * w
                details['review_due'] = f"{rb} ({days_late}d overdue — decaying to sector prior)"
        return round(val, 1), details

    if not fund_data:
        return min(12.5, VISIBILITY_FALLBACK_CAP), {}
    base = SECTOR_VIS_PRIORS.get(sector, 12.5)
    gross = fund_data.get('grossMargins')
    if gross and gross > 0.60:
        base += 2
    elif gross and gross > 0.40:
        base += 1
    # `or ''`: a key present with value None defeats .get's default (#92
    # canonical data carries explicit nulls where the old fetcher wrote '')
    industry = fund_data.get('industry') or ''
    if any(kw in industry.lower() for kw in ['software', 'saas', 'subscription', 'service']):
        base += 2
    capped = min(base, VISIBILITY_FALLBACK_CAP)
    return round(min(25, capped), 1), {'sector_base': sector,
                                       'fallback_capped': bool(capped < base)}


def get_sp500_tickers():
    """Fetch current S&P 500 constituents."""
    try:
        table = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')
        tickers = table[0]['Symbol'].tolist()
        # Fix tickers with dots (BRK.B -> BRK-B for Yahoo)
        tickers = [t.replace('.', '-') for t in tickers]
        return tickers
    except Exception as e:
        print(f"  Failed to fetch S&P 500 list: {e}")
        print("  Using cached list...")
        # Fallback: top 100 by market cap
        return [
            "AAPL","MSFT","NVDA","AMZN","GOOG","META","BRK-B","AVGO","LLY","JPM",
            "TSLA","V","UNH","XOM","MA","COST","PG","JNJ","HD","ABBV",
            "WMT","NFLX","BAC","CRM","ORCL","CVX","MRK","KO","AMD","PEP",
            "TMO","ADBE","ACN","LIN","MCD","CSCO","PM","ABT","GE","ISRG",
            "TXN","DHR","INTU","NOW","QCOM","CAT","VZ","AMGN","IBM","GS",
            "AXP","BKNG","MS","SPGI","BLK","PFE","T","NEE","LOW","UNP",
            "RTX","HON","ELV","SYK","AMAT","DE","LRCX","SCHW","PLD","TJX",
            "KLAC","ADP","VRTX","MMC","REGN","C","ADI","BSX","PANW","CB",
            "FI","BMY","MDLZ","SBUX","SO","MO","CL","ICE","CME","WM",
            "GD","MCK","APD","FCX","USB","TT","ORLY","AZO","HCA","ANET",
            "TSM","MU","CEG","ETN","VRT","GEV",
        ]


# ── Data Fetching ─────────────────────────────────────────────────────

FETCH_FAILED = set()   # [3] tickers with no usable prices after batch + individual retry

# #92 canonical artifact (plan 4.1): the tournament repo performs the ONE
# fundamentals fetch nightly and publishes data/canonical/fundamentals.json +
# data/source/prices_daily.parquet (public repo). This screener consumes those
# instead of running its own 535-name fetch — the double-fetch is what caused
# the 2026-07-29 rejection night (113/535 names lost to Yahoo rate limits on
# our runner). Direct fetch remains as a LOUD fallback, never a silent one.
CANONICAL_BASES = [
    str(ROOT),                                                          # this repository (order 6.1): local artifact first
    "https://raw.githubusercontent.com/wernerhl/portfolio-tournament/main",   # recorded fallback only
]
DATA_SOURCE = {"mode": "direct"}      # overwritten when canonical is consumed
FUNDAMENTALS_USED = {}                # for build_json's sample equality assert

# Order 3.1 (2026-09-09): ONE holdings source. Werner's book (tier 5) lives in
# the tournament repo's data/holdings.json. Order 6.1 (2026-09-16): that is
# now THIS repository, so the local file is read first; the raw GitHub URL is
# a recorded fallback only (or an explicit override via HOLDINGS_LOCAL_PATH,
# e.g. to test an edited file). The screener's own config["portfolio"] list
# is gone.
HOLDINGS_LOCAL   = str(ROOT / "data" / "holdings.json")   # same repository — read first
HOLDINGS_URL     = "https://raw.githubusercontent.com/wernerhl/portfolio-tournament/main/data/holdings.json"   # recorded fallback only
HOLDINGS_SOURCE  = {"mode": "none"}   # provenance of the book actually used


def fetch_canonical(universe, universe_with_bench):
    """Try each canonical base; return (prices_df, fundamentals, provenance)
    or (None, None, reason) so main() can fall back to direct fetch."""
    import json as _json, urllib.request, tempfile, os
    from datetime import date

    for base in CANONICAL_BASES:
        try:
            local = not base.startswith("http")
            fpath = f"{base}/data/canonical/fundamentals.json"
            if local:
                if not Path(fpath).exists():
                    continue
                blob = _json.loads(Path(fpath).read_text())
            else:
                with urllib.request.urlopen(fpath, timeout=30) as r:
                    blob = _json.loads(r.read())
            prov = blob["provenance"]

            # Cheap staleness sanity (the [5] session guard in build_json does
            # the strict data-session == current-session assert downstream).
            sd = date.fromisoformat(prov["session_date"])
            if (date.today() - sd).days > 5:
                print(f"  canonical at {base}: stale (session {sd}) — skipping")
                continue

            ppath = f"{base}/{prov['prices_ref']}"
            if local:
                prices = pd.read_parquet(ppath)
            else:
                tmp = os.path.join(tempfile.gettempdir(), "canon_prices.parquet")
                urllib.request.urlretrieve(ppath, tmp)
                prices = pd.read_parquet(tmp)
            prices.index = pd.to_datetime(prices.index)
            prices = prices.tail(260)                    # ~1y window
            if "SPY_volume" in prices.columns:
                prices = prices.drop(columns=["SPY_volume"])

            fund = dict(blob["tickers"])
            miss_f = sorted(set(universe) - set(fund))
            miss_p = sorted(set(universe) - set(prices.columns))
            if len(miss_f) > 0.05 * len(universe) or len(miss_p) > 0.05 * len(universe):
                print(f"  canonical at {base}: coverage short (fund -{len(miss_f)}, "
                      f"prices -{len(miss_p)}) — falling back entirely")
                continue

            # Top-ups: benchmark + the few names canonical lacks
            topup = sorted(set(miss_p) | {"^GSPC"})
            px2 = fetch_price_data(topup, period="1y")
            prices = prices.join(px2, how="outer") if len(px2.columns) else prices
            if miss_f:
                fund.update(fetch_fundamentals(miss_f))

            prov_out = {
                "mode": "canonical", "base": base,
                "canonical_session": prov["session_date"],
                "canonical_built_at": prov["built_at"],
                "canonical_coverage_pct": prov["coverage_pct"],
                "fund_topups": miss_f, "price_topups": miss_p,
            }
            print(f"  canonical consumed from {base} "
                  f"(session {prov['session_date']}, {len(fund)} names, "
                  f"topups fund={len(miss_f)} prices={len(miss_p)})")
            return prices, fund, prov_out
        except Exception as e:
            print(f"  canonical at {base}: {type(e).__name__}: {e} — trying next")
    return None, None, {"mode": "direct", "reason": "no usable canonical base"}


def _validate_holdings(blob, where):
    """Shape of data/holdings.json: {cash, holdings: [{ticker, shares, cost_basis, ...}]}."""
    if not isinstance(blob, dict) or not isinstance(blob.get("holdings"), list):
        raise ValueError(f"{where}: no 'holdings' list")
    for h in blob["holdings"]:
        for k in ("ticker", "shares", "cost_basis"):
            if k not in h:
                raise ValueError(f"{where}: holding {h} lacks '{k}'")
    if "cash" not in blob:
        raise ValueError(f"{where}: no 'cash'")
    return blob


def fetch_holdings():
    """Return (blob, provenance) for the tournament's data/holdings.json.
    Sources in order: HOLDINGS_LOCAL_PATH (explicit override) → this
    repository's data/holdings.json → the GET (two attempts, 30 s timeout,
    like fetch_canonical) as a recorded fallback. No usable source → SystemExit: a board scored against an empty or
    invented book must never publish silently (the July-2026 lesson)."""
    import json as _json, urllib.request, os, time
    global HOLDINGS_SOURCE

    candidates = []
    override = os.environ.get("HOLDINGS_LOCAL_PATH")
    if override:
        candidates.append(("local_override", override))
    if Path(HOLDINGS_LOCAL).exists():
        candidates.append(("local", HOLDINGS_LOCAL))
    candidates.append(("url_fallback", HOLDINGS_URL))

    errors = []
    for mode, where in candidates:
        attempts = 2 if where.startswith("http") else 1
        for attempt in range(1, attempts + 1):
            try:
                if where.startswith("http"):
                    with urllib.request.urlopen(where, timeout=30) as r:
                        blob = _json.loads(r.read())
                else:
                    blob = _json.loads(Path(where).read_text())
                _validate_holdings(blob, where)
                HOLDINGS_SOURCE = {
                    "mode": mode, "path": where,
                    "as_of": blob.get("as_of"), "cadence": blob.get("cadence"),
                    "n_holdings": len(blob["holdings"]), "cash": blob.get("cash"),
                }
                print(f"  holdings consumed from {where} [{mode}] "
                      f"(as_of {blob.get('as_of')}, {len(blob['holdings'])} positions, "
                      f"cash {blob.get('cash')})")
                return blob, dict(HOLDINGS_SOURCE)
            except Exception as e:
                errors.append(f"{where} (attempt {attempt}): {type(e).__name__}: {e}")
                more = "retrying" if attempt < attempts else "trying next"
                print(f"  holdings at {where}: {type(e).__name__}: {e} — {more}")
                if attempt < attempts:
                    time.sleep(2)
    raise SystemExit("holdings source unavailable — " + "; ".join(errors) +
                     " (order 3.1: the tournament repo's data/holdings.json is the only holdings source)")


def portfolio_weights(holdings):
    """{ticker: cost-basis weight (fraction of equity)} from a holdings.json
    list — the CURRENT_PORTFOLIO shape the correlation penalty expects."""
    total = sum((h.get("shares") or 0) * (h.get("cost_basis") or 0) for h in holdings)
    if total <= 0:
        return {}
    return {h["ticker"]: (h["shares"] * h["cost_basis"]) / total
            for h in holdings if (h.get("shares") or 0) > 0}

def fetch_price_data(tickers, period="1y"):
    """Batch download price history. [3]: batch failures retry individually
    once; still-failing names land in FETCH_FAILED so every downstream null
    carries a reason instead of vanishing silently."""
    global FETCH_FAILED
    print(f"  Downloading price data for {len(tickers)} tickers...")
    # Split into chunks to avoid timeout
    chunk_size = 100
    all_data = {}
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i+chunk_size]
        try:
            data = yf.download(chunk, period=period, progress=False, auto_adjust=True, threads=True)
            if data is not None and 'Close' in data.columns:
                closes = data['Close']
                if isinstance(closes, pd.Series):
                    all_data[chunk[0]] = closes
                else:
                    for t in closes.columns:
                        if not closes[t].isna().all():
                            all_data[t] = closes[t]
            time.sleep(1)
        except Exception as e:
            print(f"    Chunk {i//chunk_size + 1} error: {e}")

    # [3] individual retry for anything the batch missed — twice, because
    # yfinance's shared sqlite caches throw transient 'database is locked'
    # errors under concurrency (a lock killed TSM's top-up on 08-07 and
    # blocked that night's publish). Lock errors get a 5s settle first.
    missing = [t for t in tickers if t not in all_data]
    for t in missing:
        for attempt in (1, 2):
            try:
                s = yf.download(t, period=period, progress=False, auto_adjust=True, threads=False)
                if s is not None and 'Close' in s.columns and not s['Close'].isna().all():
                    c = s['Close']
                    all_data[t] = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
                break
            except Exception as e:
                if attempt == 1 and 'locked' in str(e).lower():
                    time.sleep(5)
                    continue
                break
    FETCH_FAILED = {t for t in tickers if t not in all_data}
    if FETCH_FAILED:
        print(f"  FETCH FAILED after retry ({len(FETCH_FAILED)}): {sorted(FETCH_FAILED)[:10]}...")
    print(f"  Got price data for {len(all_data)} tickers")
    return pd.DataFrame(all_data)


def fetch_fundamentals(tickers, _retry_pass=False):
    """Fetch fundamental data for each ticker.

    2026-07-30 hardening: the 19:00 ET nightly lost 113/535 names to Yahoo
    rate-limiting (a board scored on 423 names was correctly REJECTED by the
    named-seven tripwire). Failed names now get one full retry pass with a
    long backoff — same policy item [3] mandated for the price fetch."""
    if not _retry_pass:
        print(f"  Fetching fundamentals for {len(tickers)} tickers...")
    results = {}
    errors = 0
    failed = []

    for i, ticker in enumerate(tickers):
        if i % 50 == 0 and i > 0:
            if not _retry_pass:
                print(f"    ... {i}/{len(tickers)} done ({errors} errors)")
            time.sleep(2 if not _retry_pass else 4)  # heavier backoff on retry

        try:
            t = yf.Ticker(ticker)
            try:
                info = t.info or {}
            except Exception:
                info = {}
            # 2026-08-06 quoteSummary outage ladder: .info is broken server-
            # side for a growing symbol shard (73 names incl. MU/AMD/JPM by
            # 08-05); fast_info is a different endpoint and stayed healthy.
            # A name with fast_info-only data stays SCORED (missing fields
            # hit the same neutral defaults as any absent metric) instead of
            # vanishing and tripping the named-seven publish block.
            if not info.get('marketCap'):
                try:
                    fi = t.fast_info
                    mcap = (fi.get('marketCap') if hasattr(fi, 'get') else None) or \
                           (fi.get('market_cap') if hasattr(fi, 'get') else None) or \
                           getattr(fi, 'market_cap', None)
                    px = (fi.get('lastPrice') if hasattr(fi, 'get') else None) or \
                         (fi.get('last_price') if hasattr(fi, 'get') else None)
                    if mcap:
                        info['marketCap'] = float(mcap)
                        if not info.get('currentPrice') and px:
                            info['currentPrice'] = float(px)
                except Exception:
                    pass
            if not info.get('marketCap'):
                errors += 1
                failed.append(ticker)
                continue

            results[ticker] = {
                'marketCap': info.get('marketCap', 0),
                'forwardPE': info.get('forwardPE'),
                'trailingPE': info.get('trailingPE'),
                'priceToBook': info.get('priceToBook'),
                'revenueGrowth': info.get('revenueGrowth'),
                'grossMargins': info.get('grossMargins'),
                'operatingMargins': info.get('operatingMargins'),
                'profitMargins': info.get('profitMargins'),
                'returnOnEquity': info.get('returnOnEquity'),
                'returnOnAssets': info.get('returnOnAssets'),
                'debtToEquity': info.get('debtToEquity'),
                'freeCashflow': info.get('freeCashflow'),
                'totalRevenue': info.get('totalRevenue'),
                'earningsGrowth': info.get('earningsGrowth'),
                'currentPrice': info.get('currentPrice') or info.get('regularMarketPrice'),
                'fiftyDayAverage': info.get('fiftyDayAverage'),
                'twoHundredDayAverage': info.get('twoHundredDayAverage'),
                'fiftyTwoWeekHigh': info.get('fiftyTwoWeekHigh'),
                'fiftyTwoWeekLow': info.get('fiftyTwoWeekLow'),
                'sector': info.get('sector', ''),
                'industry': info.get('industry', ''),
                'shortName': info.get('shortName', ticker),
                'beta': info.get('beta'),
                'dividendYield': info.get('dividendYield'),
            }
        except Exception:
            errors += 1
            failed.append(ticker)

    if failed and not _retry_pass:
        print(f"  Retry pass for {len(failed)} failed fundamentals (30s backoff)...")
        time.sleep(30)
        recovered = fetch_fundamentals(failed, _retry_pass=True)
        results.update(recovered)
        still = sorted(set(failed) - set(recovered))
        print(f"  Retry recovered {len(recovered)}; still failed ({len(still)}): {still[:12]}")

    if not _retry_pass:
        print(f"  Got fundamentals for {len(results)} tickers ({len(tickers)-len(results)} unrecovered)")
    return results


# ── Factor Computations ───────────────────────────────────────────────

def compute_technical_score(prices_df, ticker):
    """
    Technical Positioning Score (0-25)
    - Distance from 200-DMA
    - RSI (14-day)
    - Relative strength vs SPX (6-month)
    - Distance from 52-week support
    """
    if ticker not in prices_df.columns:
        return None, {}
    
    px = prices_df[ticker].dropna()
    if len(px) < 60:
        return None, {}
    
    current = px.iloc[-1]
    
    # 200-day MA distance (score higher when near or below — buy at support)
    ma200 = px.rolling(200).mean().iloc[-1] if len(px) >= 200 else px.rolling(len(px)).mean().iloc[-1]
    ma200_dist = (current - ma200) / ma200  # negative = below MA
    # Score: best at -5% to +5% of MA (buying near support), worst at +30%+ (extended)
    if ma200_dist < -0.15:
        ma_score = 3.0  # deeply oversold — might be broken, not just cheap
    elif ma200_dist < -0.05:
        ma_score = 6.0  # oversold, near support
    elif ma200_dist < 0.05:
        ma_score = 5.5  # near MA, healthy
    elif ma200_dist < 0.15:
        ma_score = 4.0  # slightly extended
    elif ma200_dist < 0.30:
        ma_score = 2.5  # extended
    else:
        ma_score = 1.0  # very extended
    
    # RSI (14-day)
    delta = px.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_val = rsi.iloc[-1] if not np.isnan(rsi.iloc[-1]) else 50
    # Score: best at 30-45 (oversold), worst at 75+ (overbought)
    if rsi_val < 30:
        rsi_score = 5.5  # deeply oversold
    elif rsi_val < 45:
        rsi_score = 6.0  # oversold, ideal entry
    elif rsi_val < 55:
        rsi_score = 5.0  # neutral
    elif rsi_val < 70:
        rsi_score = 3.5  # overbought
    else:
        rsi_score = 1.5  # very overbought
    
    # Relative strength vs SPX (6-month)
    if '^GSPC' in prices_df.columns or 'SPY' in prices_df.columns:
        spx_col = '^GSPC' if '^GSPC' in prices_df.columns else 'SPY'
        spx = prices_df[spx_col].dropna()
        min_len = min(len(px), len(spx), 126)
        if min_len > 20:
            stock_ret = (px.iloc[-1] / px.iloc[-min_len] - 1)
            spx_ret = (spx.iloc[-1] / spx.iloc[-min_len] - 1)
            rel_strength = stock_ret - spx_ret
            # Score: outperforming = higher score
            rs_score = min(6.5, max(1.0, 3.5 + rel_strength * 15))
        else:
            rs_score = 3.5
            rel_strength = 0
    else:
        rs_score = 3.5
        rel_strength = 0
    
    # Distance from 52-week support
    low_52w = px.tail(252).min() if len(px) >= 252 else px.min()
    high_52w = px.tail(252).max() if len(px) >= 252 else px.max()
    range_52w = high_52w - low_52w
    if range_52w > 0:
        pct_from_low = (current - low_52w) / range_52w
        # Score: best near the low (buying support), worst near high
        support_score = max(1.0, min(6.5, 6.5 - pct_from_low * 5))
    else:
        support_score = 3.5
    
    total = ma_score + rsi_score + rs_score + support_score
    total = min(25.0, max(0.0, total))
    
    details = {
        'ma200_dist': round(ma200_dist * 100, 1),
        'rsi': round(rsi_val, 1),
        'rel_strength_6m': round(rel_strength * 100, 1),
        'pct_52w_range': round(pct_from_low * 100 if range_52w > 0 else 50, 1),
    }
    
    return round(total, 1), details


def compute_fundamental_score(fund_data):
    """
    Fundamental Quality Score (0-25)
    - FCF Yield (or inverse forward P/E as proxy)
    - Revenue growth
    - Margin quality (gross + operating)
    - ROIC proxy (ROE adjusted for leverage)
    """
    if not fund_data:
        return None, {}
    
    scores = []
    details = {}
    
    # FCF Yield / Valuation (0-7)
    # Score priority unchanged: FCF yield first, forward P/E fallback. But BOTH
    # metrics are recorded in details regardless of which branch scored — the
    # display layer previously fell back fwd_pe→fcf_yield across semantic
    # types, publishing FCF yields labeled as P/Es (GOOG "0.6", NVDA "1.0").
    fwd_pe = fund_data.get('forwardPE')
    mcap = fund_data.get('marketCap', 0)
    fcf = fund_data.get('freeCashflow', 0)

    if fwd_pe and fwd_pe > 0:
        details['forward_pe'] = round(fwd_pe, 1)
    if fcf and mcap and mcap > 0:
        fcf_yield = fcf / mcap * 100          # raw, so thresholds are unchanged
        details['fcf_yield'] = round(fcf_yield, 1)

    if 'fcf_yield' in details:
        # [2] Tail extension (written instruction 2026-07-29): the old ladder
        # collapsed everything <=0 to 1.0 and the old [-5,25] range check
        # nulled true deep-burn readings (NBIS -15.6% became a neutral null).
        # Steps above 2% unchanged; (0,2] drops 3.0->2.0; tails score.
        if fcf_yield > 6: val_score = 7.0
        elif fcf_yield > 4: val_score = 6.0
        elif fcf_yield > 2: val_score = 4.5
        elif fcf_yield > 0: val_score = 2.0
        elif fcf_yield > -5: val_score = 1.0
        else: val_score = 0.5
    elif 'forward_pe' in details:
        if fwd_pe < 12: val_score = 6.5
        elif fwd_pe < 20: val_score = 5.5
        elif fwd_pe < 30: val_score = 4.0
        elif fwd_pe < 50: val_score = 2.5
        else: val_score = 1.0
    else:
        val_score = 3.0
    scores.append(val_score)
    
    # Revenue Growth (0-6)
    rev_growth = fund_data.get('revenueGrowth')
    if rev_growth is not None:
        details['rev_growth'] = round(rev_growth * 100, 1)
        if rev_growth > 0.40: growth_score = 6.0
        elif rev_growth > 0.20: growth_score = 5.0
        elif rev_growth > 0.10: growth_score = 4.0
        elif rev_growth > 0.0: growth_score = 3.0
        elif rev_growth > -0.10: growth_score = 2.0
        else: growth_score = 1.0
    else:
        growth_score = 3.0
    scores.append(growth_score)
    
    # Margin Quality (0-6)
    gross = fund_data.get('grossMargins')
    operating = fund_data.get('operatingMargins')
    if gross is not None and operating is not None:
        details['gross_margin'] = round(gross * 100, 1)
        details['op_margin'] = round(operating * 100, 1)
        # Combined margin score
        margin_avg = (gross + max(0, operating)) / 2
        if margin_avg > 0.40: margin_score = 6.0
        elif margin_avg > 0.25: margin_score = 5.0
        elif margin_avg > 0.15: margin_score = 3.5
        elif margin_avg > 0.05: margin_score = 2.0
        else: margin_score = 1.0
    else:
        margin_score = 3.0
    scores.append(margin_score)
    
    # Return on Equity / Capital Efficiency (0-6)
    # The old buried D/E haircut (-1.5/-0.5) moved to compute_leverage_penalty
    # (#93) so leverage is scored ONCE, visibly, not twice invisibly.
    roe = fund_data.get('returnOnEquity')
    if roe is not None:
        details['roe'] = round(roe * 100, 1)
        if roe > 0.30: roe_score = 6.0
        elif roe > 0.20: roe_score = 5.0
        elif roe > 0.10: roe_score = 3.5
        elif roe > 0: roe_score = 2.0
        else: roe_score = 1.0
    else:
        roe_score = 3.0
    scores.append(roe_score)
    
    total = sum(scores)
    total = min(25.0, max(0.0, total))
    
    return round(total, 1), details


def compute_visibility_score(fund_data, ticker, force_legacy=False):
    """
    Visibility / Backlog Score (0-25)
    
    This is the hardest factor to automate. Backlog data isn't in standard feeds.
    We use proxies:
    - Revenue predictability (low quarterly variance)
    - Recurring revenue indicators (SaaS, subscriptions, service contracts)
    - Sector-based visibility premium (utilities, defense, infrastructure > cyclicals)
    
    Manual overrides for known backlog data should be added to VISIBILITY_OVERRIDES.
    """
    VISIBILITY_OVERRIDES = {
        # Ticker: (score, reason)
        "GEV":  (23, "$163B backlog, 25yr service contracts"),
        "AVGO": (22, "$73B contracted backlog through 2028"),
        "ANET": (20, "Multi-year AI networking pipeline"),
        "VRT":  (20, "$15B backlog, 109% YoY growth"),
        "CEG":  (21, "Multi-decade nuclear PPAs"),
        "LMT":  (22, "$166B defense backlog"),
        "RTX":  (21, "$196B defense/aero backlog"),
        "GD":   (21, "$91B defense backlog"),
        "NOC":  (21, "$85B defense backlog"),
        "ORCL": (19, "RPO $130B+"),
        "GOOG": (20, "$460B cloud backlog"),
        "MSFT": (18, "$627B commercial RPO"),
        "AMZN": (17, "AWS backlog growing"),
        "NVDA": (20, "$1T order book through 2027"),
        "TSM":  (21, "Multi-year contracted wafer starts"),
        "ETN":  (19, "Record electrical backlog"),
        "POWL": (18, "Backlog at record levels"),
        "TLN":  (19, "AWS nuclear PPA"),
    }
    
    # Registry mode (plan 2.5): once the governed registry is frozen it is the
    # single authority — the hardcoded dict above becomes migration history.
    # force_legacy exists ONLY for the [6] board-delta ablation (computes the
    # pre-registry visibility alongside), never for scoring.
    if VIS_REGISTRY is not None and not force_legacy:
        return visibility_from_registry(fund_data, ticker)

    if ticker in VISIBILITY_OVERRIDES:
        score, reason = VISIBILITY_OVERRIDES[ticker]
        return score, {'override': reason}

    if not fund_data:
        return 12.5, {}

    # Sector-based visibility premium
    sector = fund_data.get('sector', '')
    industry = fund_data.get('industry') or ''   # None-safe (#92 canonical nulls)

    base = SECTOR_VIS_PRIORS.get(sector, 12.5)
    
    # Adjust for margin stability (high margins = more pricing power = more visibility)
    gross = fund_data.get('grossMargins')
    if gross and gross > 0.60:
        base += 2
    elif gross and gross > 0.40:
        base += 1
    
    # Adjust for recurring revenue indicators
    if any(kw in industry.lower() for kw in ['software', 'saas', 'subscription', 'service']):
        base += 2
    
    return min(25, round(base, 1)), {'sector_base': sector}


def compute_leverage_penalty(fund_data):
    """#93 Leverage penalty (0 to -5) — absolute ramps, both-systems module.

    Primary: net-debt / EBITDA. Fallback: debt-to-equity. Negative-EBITDA
    names with meaningful debt (>10% of market cap) are levered cash burners
    and take a fixed -4. Financials are exempt (banks/insurers carry balance-
    sheet leverage by construction — D/E and ND/EBITDA are not comparable).
    Interest coverage is unavailable in the data source (no interestExpense
    field) — documented, not silently approximated.

    Returns (penalty, details) with penalty=None + lev_status='unavailable'
    when no metric can be computed — the corr-penalty precedent: a dead
    input is visibly dead, never a silent 0. This module replaces the old
    buried -1.5 ROE haircut (removed) so leverage is scored once, visibly.
    """
    if not fund_data:
        return None, {'lev_status': 'unavailable'}
    if (fund_data.get('sector') or '') == 'Financial Services':
        return 0.0, {'lev_status': 'financial_na'}
    td, tc = fund_data.get('totalDebt'), fund_data.get('totalCash')
    eb, de = fund_data.get('ebitda'), fund_data.get('debtToEquity')
    mcap = fund_data.get('marketCap') or 0

    if td is not None and eb is not None:
        if eb > 0:
            nde = (td - (tc or 0)) / eb
            if   nde <= 1: p = 0.0
            elif nde <= 2: p = -0.5
            elif nde <= 3: p = -1.5
            elif nde <= 4: p = -2.5
            elif nde <= 6: p = -3.5
            else:          p = -5.0
            return p, {'lev_status': 'ok', 'nd_ebitda': round(nde, 2)}
        if mcap and td > 0.10 * mcap:
            return -4.0, {'lev_status': 'neg_ebitda_debt', 'nd_ebitda': None}
        return 0.0, {'lev_status': 'neg_ebitda_low_debt', 'nd_ebitda': None}

    if de is not None:
        if   de < 50:  p = 0.0
        elif de < 100: p = -0.5
        elif de < 200: p = -1.5
        elif de < 400: p = -3.0
        else:          p = -5.0
        return p, {'lev_status': 'de_fallback', 'dte_pct': round(de, 1)}

    return None, {'lev_status': 'unavailable'}


def compute_correlation_penalty(prices_df, ticker, portfolio_weights):
    """
    Correlation Penalty (0 to -10) — book-aware, null on failure.

    Primary measure: correlation of the candidate's daily returns against the
    position-weighted PORTFOLIO return series over the last ~126 trading days.
    This is weight-aware by construction — duplicating a 30% position moves
    the book series far more than duplicating a 2% one. The max pairwise
    correlation vs any single holding is retained for the "duplicates NVDA"
    message. Bucket thresholds unchanged from the original design.

    Held names exclude THEMSELVES from the book series (self-correlation is
    1.0 by definition); an add-to candidate is judged on what it duplicates
    in the rest of the book.

    July 2026 rewrite — why: the original ran `prices_df.pct_change().dropna()`
    on the full 536-column frame. dropna(how='any') deletes every row where ANY
    ticker is NaN, so once the universe grew to 535 (new listings, chunk-fetch
    misses) essentially no rows survived, every pair fell below the obs floor,
    and the function returned 0.0/None for ALL names — silently. Correlations
    are now computed per-pair / per-book on aligned series only.

    Returns (penalty, details). On failure returns (None, corr_status=
    'unavailable') — NEVER a silent zero-fill. A zero must mean "measured,
    uncorrelated", not "computation died" (that ambiguity hid the bug).
    """
    WINDOW  = 126   # ~6 trading months of daily returns
    MIN_OBS = 60    # [3] floor for pairwise AND book overlap (60 trading days)

    def _fail(reason):
        return None, {'corr_status': 'unavailable', 'corr_null_reason': reason,
                      'max_corr': None, 'max_corr_with': None,
                      'portfolio_corr': None, 'n_obs': 0}

    if not portfolio_weights:
        return _fail('no_book_overlap')
    if ticker in FETCH_FAILED:
        return _fail('fetch_failed')
    if ticker not in prices_df.columns:
        return _fail('fetch_failed')

    tail = prices_df.tail(WINDOW + 1)
    cand = tail[ticker].pct_change()
    if cand.dropna().shape[0] < MIN_OBS:
        return _fail('insufficient_history')

    # Holdings' return series (self excluded for held candidates).
    # [3] Per-member overlap floor: a book position with <60 overlapping
    # days vs THIS candidate (e.g. a short-history BMNR) is excluded from
    # this candidate's pair set and the book weights renormalize over the
    # remaining members — the candidate is NOT nulled for a member's gap.
    held = {}
    for pticker, w in portfolio_weights.items():
        col = pticker.replace('.', '-')
        if col == ticker:
            continue
        if col in tail.columns:
            pair_n = pd.concat([cand, tail[col].pct_change()], axis=1).dropna().shape[0]
            if pair_n >= MIN_OBS:
                held[pticker] = (tail[col].pct_change(), w)
    if not held:
        return _fail('no_book_overlap')

    # Pairwise max — for the user-facing "highest overlap: NVDA" message
    max_corr, max_corr_ticker = 0.0, None
    for pticker, (ret, _w) in held.items():
        pair = pd.concat([cand, ret], axis=1).dropna()
        c = pair.corr().iloc[0, 1]
        if not np.isnan(c) and abs(c) > max_corr:
            max_corr, max_corr_ticker = abs(c), pticker

    # Book-level correlation: candidate vs position-weighted portfolio returns
    book = pd.concat({p: r for p, (r, _w) in held.items()}, axis=1)
    aligned = pd.concat([cand.rename('_cand'), book], axis=1).dropna()
    if len(aligned) < MIN_OBS:
        return _fail('insufficient_history')
    weights = pd.Series({p: w for p, (_r, w) in held.items()})
    weights = weights / weights.sum()
    book_ret = (aligned[list(weights.index)] * weights).sum(axis=1)
    portfolio_corr = aligned['_cand'].corr(book_ret)
    if np.isnan(portfolio_corr):
        return _fail('insufficient_history')

    apc = abs(portfolio_corr)
    if apc > 0.85:
        penalty = -10.0
    elif apc > 0.75:
        penalty = -7.0
    elif apc > 0.65:
        penalty = -4.0
    elif apc > 0.50:
        penalty = -2.0
    else:
        penalty = 0.0

    details = {
        'corr_status': 'ok',
        'corr_null_reason': None,
        'max_corr': round(float(max_corr), 3),
        'max_corr_with': max_corr_ticker,
        'portfolio_corr': round(float(portfolio_corr), 3),
        'n_obs': int(len(aligned)),
    }
    return round(penalty, 1), details


# ── Main Pipeline ─────────────────────────────────────────────────────

def main():
    global VIS_REGISTRY, CURRENT_PORTFOLIO
    print("=" * 60)
    print(f"PORTFOLIO SCORING MODEL — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    VIS_REGISTRY = load_visibility_registry()

    # Order 3.1: the book comes from the tournament's holdings.json (one
    # source). build_json.py sets CURRENT_PORTFOLIO before calling main(); a
    # standalone run reads the same file here.
    if not CURRENT_PORTFOLIO:
        _blob, _ = fetch_holdings()
        CURRENT_PORTFOLIO = portfolio_weights(_blob["holdings"])

    # 1. Build universe
    # Load the ONE universe (order 6.2, 2026-09-16): data/universe.txt — the
    # union of the two views' universes plus every held name, built nightly by
    # scripts/build_universe.py — from a committed file: deterministic, and it
    # replaces the flaky Wikipedia S&P-500 scrape that was silently falling
    # back to a hardcoded ~100 names (the screen had been running on ~149, not 500).
    print("\n[1/5] Building universe...")
    uni_file = ROOT / "data" / "universe.txt"
    if uni_file.exists():
        base = [t.strip() for t in uni_file.read_text().split() if t.strip()]
        src = f"union {len(base)} (data/universe.txt)"
    else:
        base = get_sp500_tickers()
        src = f"S&P 500 scrape fallback ({len(base)})"
    # Always fold in current portfolio holdings + curated mid-caps so the
    # screen can rank names you own and your growth watchlist (both are already
    # in the union universe — kept as a no-op safeguard).
    universe = sorted(set(base) | set(MIDCAP_ADDITIONS) | set(CURRENT_PORTFOLIO.keys()))
    # Add SPX for relative strength calculation
    universe_with_bench = list(set(universe + ['^GSPC']))
    print(f"  Universe: {len(universe)} tickers  [{src} + {len(MIDCAP_ADDITIONS)} mid-caps + portfolio]")
    
    # 2+3. Canonical-first (#92): one fetch feeds both repos. Direct fetch is
    # the fallback and says so in provenance — never a silent substitution.
    global LAST_PRICE_DATE, DATA_SOURCE, FUNDAMENTALS_USED
    print("\n[2+3/5] Consuming canonical artifact...")
    prices, fundamentals, DATA_SOURCE = fetch_canonical(universe, universe_with_bench)
    if prices is None:
        print("  CANONICAL UNAVAILABLE — direct-fetch fallback (recorded in provenance)")
        print("\n[2/5] Fetching price data (direct)...")
        prices = fetch_price_data(universe_with_bench, period="1y")
        print("\n[3/5] Fetching fundamentals (direct)...")
        fundamentals = fetch_fundamentals(universe)
    FUNDAMENTALS_USED = fundamentals
    # [5] session stamp consumed by build_json's guard
    LAST_PRICE_DATE = str(prices.index.max().date()) if len(prices) else None
    
    # 4. Score everything
    print("\n[4/5] Scoring universe...")
    rows = []
    scored = 0
    
    for ticker in universe:
        fund = fundamentals.get(ticker, {})
        if not fund:
            continue
        
        # Technical score
        tech_score, tech_details = compute_technical_score(prices, ticker)
        if tech_score is None:
            continue
        
        # Fundamental score
        fund_score, fund_details = compute_fundamental_score(fund)
        if fund_score is None:
            continue
        
        # Visibility score
        vis_score, vis_details = compute_visibility_score(fund, ticker)
        
        # Correlation penalty (None = computation failed → visible impairment,
        # contributes 0 to the composite but is NEVER displayed as a measured 0)
        corr_penalty, corr_details = compute_correlation_penalty(
            prices, ticker, CURRENT_PORTFOLIO
        )
        penalty_applied = corr_penalty if corr_penalty is not None else 0.0

        # #93 leverage penalty (same visible-impairment semantics as corr)
        lev_penalty, lev_details = compute_leverage_penalty(fund)
        lev_applied = lev_penalty if lev_penalty is not None else 0.0

        # Entry level — computed BEFORE the composite so the broken-base cap
        # can reference it (20-DMA or recent support)
        px_series = prices[ticker].dropna() if ticker in prices.columns else pd.Series()
        if len(px_series) > 20:
            ma20 = px_series.rolling(20).mean().iloc[-1]
            ma50 = px_series.rolling(50).mean().iloc[-1] if len(px_series) > 50 else ma20
            current_px = px_series.iloc[-1]
            # Suggest entry at the higher of: 5% below current, or 50-DMA
            entry_level = max(ma50, current_px * 0.95)
            entry_level = round(entry_level, 2)
        else:
            current_px = fund.get('currentPrice', 0)
            entry_level = round(current_px * 0.95, 2) if current_px else 0

        # Broken-base cap (plan 2.3 — Werner approved "Cap it" 2026-07-29):
        # >GAP% below base with RSI<RSI_MAX = falling knife, not an entry.
        # Cap the technical score and tag the row — stated design and actual
        # behavior now agree (the old text claimed a penalty that never fired).
        rsi_val = tech_details.get('rsi')
        broken_base = bool(
            entry_level and current_px and rsi_val is not None
            and current_px < entry_level * (1 - BROKEN_BASE_GAP_PCT / 100.0)
            and rsi_val < BROKEN_BASE_RSI
        )
        tech_precap = tech_score          # [6] ablation input for board-delta
        if broken_base:
            tech_score = min(tech_score, BROKEN_BASE_TECH_CAP)

        # [6] ablation input: what the legacy (pre-registry) visibility path
        # would have scored — consumed only by scripts/oneoff/board_delta.py.
        vis_legacy, _ = compute_visibility_score(fund, ticker, force_legacy=True)

        # Composite score
        composite = tech_score + fund_score + vis_score + penalty_applied + lev_applied
        composite = max(0, min(75, composite))  # 0-75 (25+25+25, corr -10, lev -5)
        
        # Category classification
        sector = fund.get('sector', '')
        rev_growth = fund.get('revenueGrowth')
        mcap = fund.get('marketCap', 0)
        
        if rev_growth and rev_growth > 0.30:
            category = "Growth"
        elif vis_score >= 20:
            category = "Compounder"
        elif sector in ['Energy', 'Basic Materials']:
            category = "Cyclical"
        elif mcap and mcap < 10e9:
            category = "Speculative"
        else:
            category = "Core"
        
        # Already in portfolio?
        in_portfolio = ticker in CURRENT_PORTFOLIO or ticker.replace('-', '.') in CURRENT_PORTFOLIO

        # Typed display fields + ingest-time range checks (never fall back
        # across semantic types; out-of-range → null + flag, never a
        # substituted value). Scoring above reads raw values and is unchanged.
        data_flags = []
        fwd_pe_val = fund_details.get('forward_pe')
        if fwd_pe_val is not None and not (3.0 <= fwd_pe_val <= 150.0):
            data_flags.append(f"fwd_pe_out_of_range({fwd_pe_val})")
            fwd_pe_val = None
        # [2] bounds widened to [-60, 30]: the check catches corruption, not
        # true readings. A missing forward P/E from negative earnings is a
        # legitimate null, not a flag (only present-but-absurd values flag).
        fcf_yield_val = fund_details.get('fcf_yield')
        if fcf_yield_val is not None and not (-60.0 <= fcf_yield_val <= 30.0):
            data_flags.append(f"fcf_yield_out_of_range({fcf_yield_val})")
            fcf_yield_val = None

        rows.append({
            'ticker': ticker,
            'name': (fund.get('shortName') or ticker)[:30],
            'sector': sector,
            'industry': (fund.get('industry') or '')[:30],
            'category': category,
            'mcap_B': round(mcap / 1e9, 1) if mcap else 0,
            'current_price': round(current_px, 2) if isinstance(current_px, (int, float)) else 0,
            'entry_level': entry_level,
            # Scores
            'fundamental': fund_score,
            'technical': tech_score,
            'visibility': vis_score,
            'corr_penalty': corr_penalty,          # None = unavailable, NOT 0
            'corr_status': corr_details.get('corr_status', 'ok'),
            'leverage_penalty': lev_penalty,       # #93 None = unavailable, NOT 0
            'lev_status': lev_details.get('lev_status', 'ok'),
            'nd_ebitda': lev_details.get('nd_ebitda'),
            'dte_pct': lev_details.get('dte_pct'),
            'broken_base': broken_base,
            'composite': round(composite, 1),
            # Key metrics — typed: fwd_pe is a P/E ratio or empty, never an
            # FCF yield (the old column fell back across semantic types)
            'fwd_pe': fwd_pe_val if fwd_pe_val is not None else '',
            'fcf_yield_pct': fcf_yield_val if fcf_yield_val is not None else '',
            'rev_growth_pct': fund_details.get('rev_growth', ''),
            'gross_margin_pct': fund_details.get('gross_margin', ''),
            'roe_pct': fund_details.get('roe', ''),
            'rsi': tech_details.get('rsi', ''),
            'ma200_dist_pct': tech_details.get('ma200_dist', ''),
            'rel_str_6m_pct': tech_details.get('rel_strength_6m', ''),
            'portfolio_corr': corr_details.get('portfolio_corr'),
            'max_corr': corr_details.get('max_corr'),
            'max_corr_with': corr_details.get('max_corr_with'),
            'corr_null_reason': corr_details.get('corr_null_reason'),
            'n_corr_obs': corr_details.get('n_obs', 0),
            'technical_precap': tech_precap,       # [6] ablation columns
            'visibility_legacy': vis_legacy,
            'data_flags': ';'.join(data_flags),
            'in_portfolio': in_portfolio,
        })
        scored += 1
    
    print(f"  Scored: {scored} tickers")
    
    # 5. Build output
    print("\n[5/5] Building output...")
    df = pd.DataFrame(rows)
    df = df.sort_values('composite', ascending=False).reset_index(drop=True)
    df.index = df.index + 1  # 1-indexed rank
    df.index.name = 'rank'
    
    # Save full universe
    df.to_csv(OUTPUT_DIR / "scored_universe.csv")
    print(f"  Full universe: {OUTPUT_DIR / 'scored_universe.csv'}")
    
    # Top 40 watchlist — INCLUDE held names (you can always add to a position).
    # Held names stay in the ranking, tagged 'in_portfolio', so an add-to-position
    # candidate that scores well isn't hidden. Bumped 30→40 so held names don't
    # crowd out fresh ideas.
    watchlist = df.head(40)
    watchlist.to_csv(OUTPUT_DIR / "watchlist_top30.csv")
    print(f"  Top 40 watchlist (incl. held): {OUTPUT_DIR / 'watchlist_top30.csv'}")
    
    # Summary report
    report_lines = []
    report_lines.append("=" * 70)
    report_lines.append(f"PORTFOLIO SCORING MODEL — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append("=" * 70)
    report_lines.append(f"\nUniverse: {len(df)} scored tickers")
    report_lines.append(f"Score range: {df['composite'].min():.1f} — {df['composite'].max():.1f}")
    report_lines.append(f"Median: {df['composite'].median():.1f}")
    
    report_lines.append("\n" + "─" * 70)
    report_lines.append("TOP 40 CANDIDATES (all names · ★ = already held, add-to candidate)")
    report_lines.append("─" * 70)
    report_lines.append(f"{'Rank':<5} {'Ticker':<7} {'Name':<25} {'Score':>6} {'Fund':>5} {'Tech':>5} {'Vis':>5} {'Corr':>5} {'Entry':>9} {'Cat':<12}")
    report_lines.append("─" * 70)

    for idx, row in watchlist.iterrows():
        held_mark = "★" if row.get('in_portfolio') else " "
        cp = row['corr_penalty']
        corr_str = f"{cp:>5.1f}" if pd.notna(cp) else "  n/a"   # unavailable ≠ 0
        report_lines.append(
            f"{idx:<5}{held_mark}{row['ticker']:<6} {row['name']:<25} {row['composite']:>6.1f} "
            f"{row['fundamental']:>5.1f} {row['technical']:>5.1f} {row['visibility']:>5.1f} "
            f"{corr_str} {row['entry_level']:>9.2f} {row['category']:<12}"
        )
    
    report_lines.append("\n" + "─" * 70)
    report_lines.append("CURRENT PORTFOLIO SCORES")
    report_lines.append("─" * 70)
    portfolio_df = df[df['in_portfolio']]
    for idx, row in portfolio_df.iterrows():
        report_lines.append(
            f"  {row['ticker']:<7} {row['name']:<25} Score: {row['composite']:>5.1f}  "
            f"(F:{row['fundamental']:.0f} T:{row['technical']:.0f} V:{row['visibility']:.0f})"
        )
    
    report_lines.append("\n" + "─" * 70)
    report_lines.append("SECTOR DISTRIBUTION — TOP 30")
    report_lines.append("─" * 70)
    sector_counts = watchlist['sector'].value_counts()
    for sector, count in sector_counts.items():
        report_lines.append(f"  {sector:<30} {count}")
    
    report_lines.append("\n" + "─" * 70)
    report_lines.append("CATEGORY DISTRIBUTION — TOP 30")
    report_lines.append("─" * 70)
    cat_counts = watchlist['category'].value_counts()
    for cat, count in cat_counts.items():
        report_lines.append(f"  {cat:<20} {count}")
    
    report_text = "\n".join(report_lines)
    with open(OUTPUT_DIR / "portfolio_report.txt", "w") as f:
        f.write(report_text)
    
    print(f"  Report: {OUTPUT_DIR / 'portfolio_report.txt'}")
    
    # Print summary to console
    print("\n" + report_text)
    
    print("\n" + "=" * 70)
    print("DONE. Next steps:")
    print("  1. Review top 30 — apply discretionary judgment layer")
    print("  2. Write entry tickets for selected names")
    print("  3. Set limit orders at entry levels")
    print("  4. Re-run monthly to update scores")
    print("=" * 70)


if __name__ == "__main__":
    main()
