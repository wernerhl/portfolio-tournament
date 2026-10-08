#!/usr/bin/env python3
"""
audit_nightly.py -- generic assertion sweep over every served data file.

Design principles (from the ledger):
  * Discover files; never maintain a per-file list that can be forgotten.
  * Test whether values are POSSIBLE and columns are ALIVE, not whether code ran.
  * Assert outcomes, not procedures.
Findings are emitted as (severity, check, detail). Exit 1 on any CRITICAL.

Delivered with the 8-Sept reconciliation memo (corrected suite). Installed
under scripts/ per order item 6. Two additions on install, both requested:
  * HOLIDAYS extended through 2027 (order item 6).
  * v4:monthly_columns assertion (memo Section 4, decision 1).
"""
import json, csv, glob, os, sys, re, math
from datetime import date, datetime, timedelta

# ---------- trading calendar (NYSE 2026-2027; extend annually) ----------
HOLIDAYS = {date(2026,1,1),date(2026,1,19),date(2026,2,16),date(2026,4,3),date(2026,5,25),
            date(2026,6,19),date(2026,7,3),date(2026,9,7),date(2026,11,26),date(2026,12,25),
            # 2027 (order item 6: extended now so it is not forgotten in January)
            date(2027,1,1),date(2027,1,18),date(2027,2,15),date(2027,3,26),date(2027,5,31),
            date(2027,6,18),date(2027,7,5),date(2027,9,6),date(2027,11,25),date(2027,12,24)}
def is_trading_day(d): return d.weekday()<5 and d not in HOLIDAYS
def last_session(today=None):
    from datetime import timezone
    now_et = datetime.now(timezone.utc) - timedelta(hours=4)
    # The calendar is the ET calendar: on a runner (UTC) after 20:00 ET, date.today() is
    # already tomorrow, which made the sweep judge every file against a session that had
    # not happened (29-Sept run at 22:36 ET reported "last session 2026-09-30").
    d = today or now_et.date()
    if not is_trading_day(d) or (d==now_et.date() and (now_et.hour,now_et.minute)<(16,15)): d -= timedelta(days=1)
    while not is_trading_day(d): d -= timedelta(days=1)
    return d
def trading_days(a,b):
    d=a; out=[]
    while d<=b:
        if is_trading_day(d): out.append(d)
        d+=timedelta(days=1)
    return out

F=[]  # findings
def add(sev, check, detail): F.append((sev,check,detail))


# ── Order 1-Oct-2026 [R1]: regime card display checks (pure; tests/test_r_order_checks.py mutates) ──
# The unit each card's value_str must carry. Independent of scripts/regime_display.py on purpose: a
# change that drops a unit from both the formatter and the payload must still fire here.
REGIME_UNITS = {"yield_3m10y": "pp", "breakeven_5y": "%", "baa_aaa": "bp", "vix_term": "pts", "mfg_new_orders": "M",
                "loan_tightening": "%", "consumer_expect": "%", "hy_oas": "bp", "realized_vol": "%",
                "spx_ret_60d": "%", "spx_drawdown": "%", "oil_60d_vel": "%"}
REGIME_SCALE = {"hy_oas": 100.0}   # stored in percent, shown in basis points
SEVERITY_WORDS = ("crisis", "acute", "stress", "shock", "spike", "crunch", "drain", "severely", "panic")


# [R5.3] the code paths that must never read the rates-stress block: R, the label, the headline, the overlay
# scalar, every sizing path and the brief's colour rules
RATES_STRESS_CONSUMERS = ('scripts/compute_regime_v2.py', 'scripts/regime_label.py', 'scripts/compute_vol_regime.py',
                          'scripts/compute_nav.py', 'scripts/compute_twins.py', 'scripts/daily_brief.py',
                          'data/brief_rules.json', 'app.js#headlineVerdict')
_RS_TOKEN = re.compile(r'rates_stress|RATES_STRESS|\^MOVE')
_RS_MOVE_CHANNEL = re.compile(r'\(\s*["\']move["\']\s*,')     # a "move" channel in the regime's INDICATORS


def rates_stress_sources(repo_root):
    """name -> source text for every consumer (headlineVerdict's body only, for app.js)."""
    out = {}
    for name in RATES_STRESS_CONSUMERS:
        path, _, fn = name.partition('#')
        try:
            txt = open(os.path.join(repo_root, path)).read()
        except Exception:
            out[name] = None; continue
        if fn:
            m_ = re.search(r'function\s+' + fn + r'\s*\(.*?\n}\n', txt, re.S)
            txt = m_.group(0) if m_ else None
        out[name] = txt
    return out


def check_rates_stress_gate(states, sources):
    out = []
    rs = (states or {}).get('rates_stress')
    if rs is not None and str(rs.get('label', '')).upper() != 'DIAGNOSTIC':
        out.append(('CRITICAL', 'bond:rates_stress_gate', f'rates_stress label is {rs.get("label")!r}, not DIAGNOSTIC'))
    for name, txt in (sources or {}).items():
        if txt is None:
            out.append(('HIGH', 'bond:rates_stress_gate', f'{name}: source unreadable, the gate could not be verified')); continue
        if _RS_TOKEN.search(txt) or (name.endswith('compute_regime_v2.py') and _RS_MOVE_CHANNEL.search(txt)):
            out.append(('CRITICAL', 'bond:rates_stress_gate', f'{name} reads the rates-stress block or MOVE (DIAGNOSTIC: no registered test has passed)'))
    return out


def check_bond_carry(states, sleeve_metrics, fred):
    """[R3] bond:carry_basis. CRITICAL when the duration read or the menu's carry column is computed from
    distribution yields (or carries yield per unit of duration); HIGH when IEF's pickup falls outside
    [DGS5 - DGS3MO, DGS10 - DGS3MO] +- 5bp on its inputs date, or a sleeve lacks both a curve-implied
    yield and its reason."""
    out = []
    d = ((states or {}).get('allocation_questions') or {}).get('duration') or {}
    sm = {r.get('ticker'): r for r in (sleeve_metrics or {}).get('sleeves', [])}
    if d:
        bad = [k for k in ('highest_yield_per_duration', 'extension_favoured') if k in d]
        if bad or 'per unit of duration' in str(d.get('read', '')).lower() or not str(d.get('basis', '')).lower().startswith('curve-implied'):
            out.append(('CRITICAL', 'bond:carry_basis', f'the duration read is not on the curve-implied basis (fields {bad}; basis {d.get("basis")!r})'))
        for leg in ('intermediate', 'long'):
            l = d.get(leg) or {}
            tk = l.get('ticker'); cy = l.get('curve_implied_yield_pct'); dy = (sm.get(tk) or {}).get('distribution_yield_pct')
            if 'curve_implied_yield_pct' not in l:
                out.append(('CRITICAL', 'bond:carry_basis', f'duration read {leg} leg {tk} carries no curve-implied yield'))
            elif cy is not None and dy is not None and abs(float(cy) - float(dy)) < 0.005:
                out.append(('CRITICAL', 'bond:carry_basis', f'duration read {leg} leg {tk}: curve-implied {cy}% equals the distribution yield {dy}%'))
    menu = (((states or {}).get('book_integration') or {}).get('menu') or {}).get('sleeves', [])
    for r in menu:
        if 'yield_per_duration' in r:
            out.append(('CRITICAL', 'bond:carry_basis', f'menu row {r.get("ticker")} carries yield_per_duration (the deprecated carry metric)')); break
    cash = ((d.get('cash') or {}).get('yield_pct')) if d else None
    for r in menu:
        if r.get('pickup_bp') is not None and r.get('distribution_yield_pct') is not None and cash is not None \
           and abs(float(r['pickup_bp']) - (float(r['distribution_yield_pct']) - float(cash)) * 100) < 0.5 \
           and r.get('curve_implied_yield_pct') is not None and abs(float(r['curve_implied_yield_pct']) - float(r['distribution_yield_pct'])) > 0.01:
            out.append(('CRITICAL', 'bond:carry_basis', f'menu row {r.get("ticker")}: the pickup is computed from the distribution yield')); break
    for tk, r in sm.items():
        if r.get('curve_implied_yield_pct') is None and r.get('real_yield_pct') is None and not r.get('curve_implied_reason'):
            out.append(('HIGH', 'bond:carry_basis', f'{tk}: no curve-implied yield and no reason recorded'))
    ief = (d.get('intermediate') or {}) if d else {}
    if fred is not None and ief.get('pickup_bp') is not None and ief.get('inputs_date'):
        try:
            row = fred.loc[:ief['inputs_date'], ['us03m', 'us05y', 'us10y']].dropna().iloc[-1]
            lo, hi = (row['us05y'] - row['us03m']) * 100 - 5, (row['us10y'] - row['us03m']) * 100 + 5
            if not (lo <= float(ief['pickup_bp']) <= hi):
                out.append(('HIGH', 'bond:carry_basis', f'IEF pickup {ief["pickup_bp"]}bp outside [DGS5-DGS3MO, DGS10-DGS3MO] +-5bp = [{lo:.1f}, {hi:.1f}] on {ief["inputs_date"]}'))
        except Exception as e:  # noqa: BLE001
            out.append(('MEDIUM', 'bond:carry_basis', f'IEF pickup range check could not run ({type(e).__name__})'))
    return out


def check_regime_display(ri):
    out = []
    for i in (ri or {}).get('indicators', []):
        k, v, vs, nar = i.get('key'), i.get('value'), str(i.get('value_str') or ''), str(i.get('narrative') or '').lower()
        u = REGIME_UNITS.get(k)
        if u and v is not None and u not in vs:
            out.append(('HIGH', 'regime:unit', f'{k}: value_str "{vs}" lacks its unit {u}'))
        if k in REGIME_SCALE and v is not None:
            m_ = re.search(r'-?\d[\d,]*\.?\d*', vs)
            shown = float(m_.group(0).replace(',', '')) if m_ else None
            if shown is None or abs(shown - v * REGIME_SCALE[k]) > 1.0:
                out.append(('HIGH', 'regime:unit', f'{k}: value_str "{vs}" does not show value {v} x {REGIME_SCALE[k]:.0f}'))
        if v is None:
            continue
        bad = None
        if k == 'vix_term' and (('backwardation' in nar and v < 0) or ('contango' in nar and v > 0)): bad = 'term structure word vs the sign of the spread'
        if k == 'yield_3m10y' and 'inverted' in nar and v > 0: bad = '"inverted" with a positive slope'
        if k in ('spx_ret_60d', 'oil_60d_vel') and ((re.search(r'\b(negative|down|falling)\b', nar) and v > 0) or (re.search(r'\b(positive|up|rising|rallying)\b', nar) and v < 0)): bad = 'direction word vs the sign of the change'
        if k == 'loan_tightening' and (('tightening' in nar and 'net tightening' in nar and v < 0) or ('easing' in nar and v > 0)): bad = 'easing/tightening vs the sign'
        if k in ('nfci', 'anfci') and (('looser' in nar and v > 0) or ('tighter' in nar and v < 0)): bad = 'looser/tighter vs the sign'
        if k in ('kcfsi', 'stlfsi') and (('calmer' in nar and v > 0)): bad = '"calmer than average" with a positive index'
        if bad:
            out.append(('HIGH', 'regime:narrative_level', f'{k}: "{i.get("narrative")}" contradicts value {v} ({bad})'))
        sev_ = [w for w in SEVERITY_WORDS if re.search(r'\b' + w, nar)]
        risky = i.get('pctile_10y_risky')
        if sev_ and (risky is None or float(risky) < 90):
            out.append(('HIGH', 'regime:narrative_level', f'{k}: severity word(s) {sev_} with ten-year percentile in the risky direction {risky} (< 90)'))
    return out

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}')
def to_date(s):
    try: return date.fromisoformat(str(s)[:10])
    except: return None

# ---------- generic date-axis discovery ----------
def max_date_in(obj, depth=0, found=None):
    """Recursively find the max ISO date in any structure (keys named like dates or values)."""
    if found is None: found=[]
    if depth>6: return found
    if isinstance(obj, dict):
        for k,v in obj.items():
            if isinstance(k,str) and DATE_RE.match(k): found.append(to_date(k))
            if isinstance(v,str) and DATE_RE.match(v) and any(t in k.lower() for t in ('date','as_of','asof','session','d','day')):
                found.append(to_date(v))
            max_date_in(v, depth+1, found)
    elif isinstance(obj, list):
        for x in obj[:5000]: max_date_in(x, depth+1, found)
    return found

STATIC = {'backtest_equity_curves.csv','backtest_metrics.json','thesis_registry.json','visibility_registry.json',
          'v4_calibration.json','thesis_backtest.json','regime_conditional_scores.json','event_calendar.json',
          'registry_proposals.json','thesis_claims.json','tier_holdings.json',
          # analysis artifacts with no JSON cadence field to declare themselves (suite correction 2026-09-08:
          # the first after-run flagged these as CRITICAL-stale; a referee that alarms on static files trains
          # everyone to ignore it). JSON files declare `cadence` and are honored below.
          'backtest_holdings_log.csv','regime_v2_leadtimes.csv','regime_v3_daily.csv','vol_canonical_close.json',
          # C1 / B2 evaluation artifacts (backtest window ends 2026-05; OOF eval reruns monthly)
          'backtest_equity_curves_gross.csv','v4_oof_predictions.csv'}
NON_DAILY_CADENCE = {'static','on_change','weekly','monthly'}   # a served JSON's own declaration (order item 5)
DECLARED = ('session_date','as_of','asof','date','last_updated')  # authoritative freshness keys, in priority order
def declared_date(obj):
    if isinstance(obj,dict):
        for k in DECLARED:
            if k in obj and to_date(obj[k]): return to_date(obj[k])
        if 'days' in obj and isinstance(obj['days'],list) and obj['days']:
            d=obj['days'][-1]
            if isinstance(d,dict) and to_date(d.get('date','')): return to_date(d['date'])
        if 'history' in obj and isinstance(obj['history'],list) and obj['history']:
            d=obj['history'][-1]
            if isinstance(d,dict) and to_date(d.get('date','')): return to_date(d['date'])
    return None
def audit_dir(root, label, last_sess):
    files = sorted(glob.glob(os.path.join(root,'*.json'))+glob.glob(os.path.join(root,'*.csv')))
    for path in files:
        name=os.path.basename(path)
        if name in ('index.html','files.txt'): continue
        try:
            if name.endswith('.csv'):
                rows=list(csv.DictReader(open(path,encoding='utf-8')))
                datecol=next((c for c in rows[0] if 'date' in c.lower()),None) if rows else None
                dates=[to_date(r[datecol]) for r in rows] if datecol else []
                dates=[d for d in dates if d]
                obj=rows
            else:
                obj=json.load(open(path,encoding='utf-8'))
                dd=declared_date(obj)
                dates=[dd] if dd else [d for d in max_date_in(obj) if d]
                if not dd: add('MEDIUM',f'{label}:schema',f'{name}: no declared as_of/session_date; freshness inferred from max date (unreliable)')
        except Exception as e:
            add('CRITICAL',f'{label}:parse',f'{name}: unreadable ({e})'); continue
        if not dates:
            add('INFO',f'{label}:freshness',f'{name}: no date axis found (static config?)'); continue
        mx=max(dates)
        age=len(trading_days(mx,last_sess))-1 if mx<=last_sess else 0   # sessions, not calendar days
        # Honor the file's DECLARED cadence (order item 5): static / on_change / weekly / monthly
        # files are old by design, not stale. The hardcoded STATIC set covers CSVs that cannot declare.
        declared_static = isinstance(obj,dict) and str(obj.get('cadence','')).lower() in NON_DAILY_CADENCE
        if name in STATIC or declared_static:
            continue
        if mx>last_sess and not is_trading_day(mx):
            add('CRITICAL',f'{label}:calendar',f'{name}: contains non-trading date {mx} (phantom session)')
        elif age>1:
            add('CRITICAL' if age>5 else 'HIGH',f'{label}:freshness',f'{name}: max date {mx} is {age} sessions-old vs last session {last_sess}')
        # CSV-specific: gaps, phantoms, duplicates
        if name.endswith('.csv') and dates:
            ds=sorted(set(dates))
            phantoms=[d for d in ds if not is_trading_day(d)]
            if phantoms: add('CRITICAL',f'{label}:calendar',f'{name}: non-trading-day rows {phantoms[:5]}')
            if len(ds)>30:
                expected=set(trading_days(ds[-60] if len(ds)>60 else ds[0], ds[-1]))
                missing=sorted(expected-set(ds))
                # Tournament audit 30-Sept-2026 (T1): a gap is CRITICAL. Producers self-heal — the
                # published vintage records a no-publish row for a missed session, the tournament
                # history is backfilled under the as-published convention — so a CRITICAL here
                # means a producer failed to, never a legitimate hole.
                if missing: add('CRITICAL',f'{label}:gaps',f'{name}: missing trading days in recent window {missing[:6]}')
            # consecutive identical numeric rows (frozen-computation symptom)
            ISO=re.compile(r'calibrated|equal_weight|elastic',re.I)   # isotonic/step-mapped columns hold constant by design
            # Order 30-Sept C3 (tournament:dead_columns resolved): regime_v4_daily.csv's model-winner
            # columns (*_logistic_pc, *_elastic_net) are written ONLY by the monthly regime_v4_ml run and
            # are empty by design on every nightly row after it (the nightly scorer preserves, never
            # produces, them — score_regime_v4_daily.py). The generic "empty for the last 5 rows" test
            # therefore fired every day between monthly runs; the specific v4:monthly_columns check below
            # (populated through the monthly model's train_end, else HIGH) is the assertion that can
            # actually be satisfied, so those columns are exempt from the generic test here.
            MONTHLY=re.compile(r'_logistic_pc$|_elastic_net$')
            empties=[c for c in rows[0] if c!=datecol and not (name=='regime_v4_daily.csv' and MONTHLY.search(c))
                     and all(str(r.get(c,'')).strip()=='' for r in rows[-5:])
                     and sum(1 for r in rows[:-5] if str(r.get(c,'')).strip()!='')>0.5*max(1,len(rows[:-5]))]
            if empties: add('HIGH',f'{label}:dead_columns',f'{name}: columns empty for last 5+ rows but populated earlier: {empties[:6]}')
            numcols=[c for c in rows[0] if c!=datecol and not ISO.search(c) and re.match(r'^-?\d+(\.\d+)?([eE]-?\d+)?$',str(rows[-1].get(c,'')))]
            if len(numcols)>=2 and len(rows)>2:
                i=len(rows)-1
                while i>0 and all(rows[i][c]==rows[i-1][c] for c in numcols): i-=1
                run=len(rows)-i
                if run>=3: add('CRITICAL',f'{label}:frozen',f'{name}: last {run} rows identical across {len(numcols)} numeric columns (frozen inputs since {rows[i][datecol]})')
    return files

def main(troot, sroot, today=None):
    ls=last_session(today)
    print(f'last trading session: {ls}')
    # F1 (7-Oct-2026): every check runs inside its own error handler; a check that raises becomes a CRITICAL finding
    # referee:check_failed:<name> and the other checks still run. The final line REFEREE COMPLETE tells audit_status
    # the referee finished; without it (or with a traceback in the report) the run is CRITICAL referee:crashed.
    try:
        audit_dir(troot,'tournament',ls); audit_dir(sroot,'screener',ls)   # 'screener' = the screen view's tree (data/screen after the merge)
    except Exception as _e:
        add('CRITICAL','referee:check_failed:files',f'the file scan did not finish: {type(_e).__name__}: {str(_e)[:200]}')

    T=lambda n: json.load(open(os.path.join(troot,n)))
    def _lang(path,label):
        """the words edge and alpha appear nowhere; no buy/sell directive — CRITICAL (order 30-Sept §8.8)"""
        if not os.path.exists(path): return
        blob=open(path,encoding='utf-8').read().lower()
        hits=[w for w in ('edge','alpha') if re.search(r'\b'+w+r'\b',blob)]
        if hits: add('CRITICAL',f'{label}:language',f'{os.path.relpath(path,troot)} contains prohibited word(s) {hits}')
        for tok in ('"action":"buy"','"action":"sell"','"recommendation":"buy"','"recommendation":"sell"','buy now','sell now'):
            if tok in blob: add('CRITICAL',f'{label}:directive',f'{os.path.relpath(path,troot)} contains a buy/sell directive ({tok!r})')
    # ---------- tournament identities ----------
    try:
        t=T('tournament.json'); h_pub=t['history']; L_pub=h_pub[-1]
        # F2 (7-Oct-2026): the checks read the errata-corrected history (data/errata.json); the published rows are judged
        # only for values no erratum covers. An edited erratum is CRITICAL (append-only); a day-to-day change above 15%
        # in any tier value without an erratum or a recorded re-seed/flow is HIGH.
        import errata as _errata
        _eprob=_errata.verify()
        if _eprob: add('CRITICAL','errata:edited','data/errata.json is append-only: '+'; '.join(_eprob)[:300])
        h=_errata.apply_history(h_pub); L=h[-1]
        _ecov={(str(e['date'])[:10],e['tier'],(e.get('ticker') or '').upper()) for e in _errata.entries()}
        _edates=_errata.dates()
        _flows={str(ev.get('date'))[:10] for ev in ((t.get('werner_comparable') or {}).get('reseed_events') or [])}
        _jumps=[]
        for _i in range(1,len(h)):
            for _tid,_td in (h[_i].get('tiers') or {}).items():
                _p=((h[_i-1].get('tiers') or {}).get(_tid) or {}).get('nav'); _n=_td.get('nav'); _d=str(h[_i].get('date'))[:10]
                if _p and _n and abs(_n/_p-1)>0.15 and _tid not in _edates.get(_d,[]) and not (_tid=='5_werner' and _d in _flows):
                    _jumps.append(f'{_tid} {_d} {(_n/_p-1)*100:+.1f}%')
        if _jumps: add('HIGH','errata:unexplained_jump',f'day-to-day tier value change above 15% with no erratum and no recorded flow: {_jumps[:6]}')
        if _edates: add('INFO','errata:applied',f'corrected values applied for {sorted(_edates)} (data/errata.json; the published rows are unchanged)')
        # T1 (audit 30-Sept-2026): no missing session in the history — CRITICAL; backfilled rows are
        # marked and counted (INFO). T3: the label must respect the hysteresis corridor from 30 Sept.
        hd_=[to_date(r['date']) for r in h if to_date(r.get('date',''))]
        if hd_:
            miss_=[d for d in trading_days(hd_[0],hd_[-1]) if d not in set(hd_)]
            if miss_: add('CRITICAL','tournament:gaps',f'tournament.json history missing session(s) {[str(d) for d in miss_[:8]]} — backfill_sessions.py did not run')
            nb_=sum(1 for r in h if r.get('backfilled'))
            if nb_: add('INFO','tournament:backfilled',f'{nb_} history row(s) are backfilled under the as-published convention (marked backfilled: true)')
        try:
            sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__))))
            from regime_label import label_with_corridor as _lwc, LEVELS as _LV
            for i in range(1,len(h)):
                if str(h[i].get('date',''))<'2026-09-30': continue
                exp_=_lwc(float(h[i]['R_t']),h[i-1].get('regime'))
                if h[i].get('regime')!=exp_: add('CRITICAL','label:corridor',f'tournament row {h[i]["date"]}: label {h[i].get("regime")} but the corridor off {h[i-1].get("regime")} at R {h[i]["R_t"]} gives {exp_}')
        except Exception as _e:
            add('MEDIUM','label:corridor',f'corridor check could not run ({type(_e).__name__})')
        # T3: one issuer, one class per tier (data/share_classes.json); the operator tier not comparable until rebuilt from trades
        scp_=os.path.join(troot,'share_classes.json')
        if os.path.exists(scp_):
            iss_={}
            for issuer,s_ in (json.load(open(scp_)).get('issuers') or {}).items():
                for c_ in s_.get('classes',[]): iss_[str(c_).upper()]=issuer
            for k,v in L['tiers'].items():
                seen_={}
                for p_ in v.get('positions',[]):
                    if (p_.get('shares') or 0)>0 and str(p_.get('ticker','')).upper() in iss_:
                        seen_.setdefault(iss_[str(p_['ticker']).upper()],[]).append(p_['ticker'])
                for issuer,cl_ in seen_.items():
                    if len(cl_)>1: add('HIGH','tournament:issuer_dup',f'{k}: two classes of {issuer} held together {cl_} (collapsed at the next reconstitution)')
        wc_=t.get('werner_comparable')
        if not wc_: add('HIGH','tournament:werner_comparable','tournament.json carries no werner_comparable block (the operator tier must be marked not comparable until rebuilt from trades)')
        elif wc_.get('comparable') and not wc_.get('rebuilt_from_trades'): add('CRITICAL','tournament:werner_comparable','the operator tier is marked comparable without a trades-based rebuild on record')
        # 1-Oct-2026: the operator tier must equal the account (book.json) on the same session — the 30-Sept
        # row kept $89,340 of tier cash against the account's $148,317 and read the MU/ANET sales as a 29.6% loss
        try:
            bk_=json.load(open(os.path.join(troot,'book.json')))
            w5_=(L['tiers'].get('5_werner') or {})
            if w5_ and bk_.get('nav') and str(bk_.get('session_date') or bk_.get('as_of'))[:10]==str(L['date'])[:10]:
                gap_=abs(float(w5_.get('nav') or 0)/float(bk_['nav'])-1.0)
                if gap_>0.01: add('HIGH','tournament:werner_vs_book',f'operator tier NAV {float(w5_.get("nav") or 0):,.0f} vs the book {float(bk_["nav"]):,.0f} on {L["date"]} ({gap_*100:.1f}% apart; cash {float(w5_.get("cash") or 0):,.0f} vs {float(bk_.get("cash") or 0):,.0f})')
        except Exception as _e:
            add('MEDIUM','tournament:werner_vs_book',f'check could not run ({type(_e).__name__})')
        # T2 / T4 / T6 (audit order 30-Sept): the nightly audit, the twins and their logs, the mistakes ledger — under data/tournament/
        # (outside the generic sweep) and data/mistakes.jsonl
        tap_=os.path.join(troot,'tournament','audit.json')
        if os.path.exists(tap_):
            ta_=json.load(open(tap_)); tad_=to_date(ta_.get('session_date') or '')
            if not tad_ or (tad_<ls and len(trading_days(tad_,ls))-1>1): add('HIGH','audit:stale',f'tournament/audit.json session_date {tad_} vs last session {ls}')
            if ta_.get('missing_sessions_now'): add('CRITICAL','tournament:gaps',f'tournament/audit.json reports missing sessions {ta_["missing_sessions_now"][:6]}')
        else: add('HIGH','audit:missing','data/tournament/audit.json absent (tournament_audit.py did not run)')
        twp_=os.path.join(troot,'tournament','twins.json')
        if os.path.exists(twp_):
            tw_=json.load(open(twp_)); twd_=to_date(tw_.get('session_date') or '')
            if not twd_ or (twd_<ls and len(trading_days(twd_,ls))-1>1): add('HIGH','twins:stale',f'twins.json session_date {twd_} vs last session {ls}')
            rp_=os.path.join(troot,'tournament','continuous_rules.json')
            if os.path.exists(rp_):
                import hashlib as _hr
                if tw_.get('rules_sha256') and tw_['rules_sha256']!=_hr.sha256(open(rp_,'rb').read()).hexdigest():
                    add('HIGH','twins:rules_changed','twins.json was computed under a different continuous_rules.json (re-register the rules)')
            for tid_,w_ in (tw_.get('twins') or {}).items():
                hist_=w_.get('history') or w_.get('nav_history') or []
                l_=hist_[-1] if hist_ else w_
                g_=abs(float(l_.get('target_cash_pct') or 0)-float(l_.get('actual_cash_pct') or 0))
                if g_>5.0+1e-6: add('HIGH','twins:cash_gap',f'{tid_}: cash gap {g_:.1f} points after execution (the rule executes beyond 5)')
                par_=w_.get('parent_tier') or w_.get('parent')
                if par_ not in L['tiers']: add('HIGH','twins:parent',f'{tid_}: parent tier {par_} not in the tournament')
                eq_=sum(float(p_.get('value') or 0) for p_ in (w_.get('positions') or [])); cash_=float(w_.get('cash') or 0)
                if w_.get('nav') and abs(eq_+cash_-float(w_['nav']))>1: add('CRITICAL','identity:nav',f'{tid_}: equity+cash={eq_+cash_:.0f} != nav={w_["nav"]:.0f}')
                K_=w_.get('K')
                if K_ and (w_.get('n_positions') or 0)>K_: add('HIGH','twins:positions',f'{tid_}: {w_.get("n_positions")} positions > K={K_}')
            _lang(twp_,'twins')
            sp_=os.path.join(troot,'tournament','twins_state.json')
            if os.path.exists(sp_):
                st_=json.load(open(sp_))
                if str(st_.get('last_session') or st_.get('session_date') or '')[:10]!=str(tw_.get('session_date'))[:10]: add('HIGH','twins:state',f'twins_state.json session {st_.get("last_session") or st_.get("session_date")} != twins.json {tw_.get("session_date")}')
        trp_=os.path.join(troot,'tournament','trades.jsonl')
        if os.path.exists(trp_):
            ids2_=[]
            try:
                for ln_ in open(trp_,encoding='utf-8'):
                    ln_=ln_.strip()
                    if ln_: ids2_.append(json.loads(ln_).get('trade_id'))
            except Exception as e:
                add('CRITICAL','logs:parse',f'trades.jsonl unreadable ({e})')
            if len(ids2_)!=len(set(ids2_)): add('CRITICAL','logs:duplicate','trades.jsonl carries duplicate trade ids')
        for lf_ in ('tournament/trades.jsonl','tournament/spells.jsonl'):
            lp2_=os.path.join(troot,lf_)
            if os.path.exists(lp2_): _lang(lp2_,'logs') if '_lang' in dir() else None
        mp_=os.path.join(troot,'mistakes.jsonl')
        if os.path.exists(mp_):
            import hashlib as _hm
            ents_=[]
            try:
                for ln_ in open(mp_,encoding='utf-8'):
                    ln_=ln_.strip()
                    if ln_: ents_.append(json.loads(ln_))
            except Exception as e:
                add('CRITICAL','mistakes:parse',f'mistakes.jsonl unreadable ({e})')
            ids_={e.get('entry_id') for e in ents_}
            for e in ents_:
                body_={k:v for k,v in e.items() if k!='entry_sha256'}
                if _hm.sha256(json.dumps(body_,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()!=e.get('entry_sha256'):
                    add('CRITICAL','mistakes:edited',f'mistakes.jsonl entry {e.get("entry_id")} does not match its hash — the ledger is append-only')
                if e.get('refers_to') and e['refers_to'] not in ids_: add('HIGH','mistakes:reference',f'entry {e.get("entry_id")} refers to an unknown entry')
            if len(ids_)!=len(ents_): add('CRITICAL','mistakes:duplicate','mistakes.jsonl carries duplicate entry ids')
        else: add('HIGH','mistakes:missing','data/mistakes.jsonl absent')
        # 7-Oct-2026: a position published without a price (the provider's bar missing for the session) is a CRITICAL of
        # its own, and the sums below treat None as 0 so the referee reports instead of crashing (on 6 Oct it crashed
        # here and the run was recorded as 0 findings while the operator tier's NAV was published 20% low)
        nopx_=[f'{k}:{p.get("ticker")}' for k,v in L_pub['tiers'].items() for p in v.get('positions',[]) if (p.get('shares') or 0)>0 and (p.get('price') is None or p.get('value') is None)
           and (str(L_pub.get('date'))[:10],k,str(p.get('ticker')).upper()) not in _ecov]
        if nopx_: add('CRITICAL','identity:position_price',f'positions published without a price or value for {L.get("date")}: {nopx_[:8]}')
        for k,v in L['tiers'].items():
            eq=sum((p.get('value') or 0) for p in v.get('positions',[])); cash=v.get('cash') or 0
            if abs(eq+cash-(v.get('nav') or 0))>1: add('CRITICAL','identity:nav',f'{k}: equity+cash={eq+cash:.0f} != nav={v.get("nav")}')
            w=sum((p.get('weight') or 0) for p in v.get('positions',[]))
            if w>101: add('HIGH','identity:weights',f'{k}: position weights sum {w:.1f}%>100')
        inc=h[0]
        for b,vals in L['benchmarks'].items():
            p0,p1=inc['benchmarks'][b].get('price'),vals.get('price'); n0,n1=inc['benchmarks'][b].get('nav'),vals.get('nav')
            if p0 and p1 and n0 and n1 and abs(n1/n0-p1/p0)>1e-4: add('CRITICAL','identity:benchmark',f'{b}: nav ratio {n1/n0:.5f} != price ratio {p1/p0:.5f}')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:tournament',f'the tournament checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- cross-file: regime ----------
    try:
        ri=T('regime_indicators.json'); rd=list(csv.DictReader(open(os.path.join(troot,'regime_daily.csv'))))
        if abs(float(rd[-1]['R_t'])-float(ri['R_full']))>1e-3: add('HIGH','xfile:R_full',f'regime_daily {rd[-1]["R_t"]} vs indicators {ri["R_full"]} on {rd[-1]["date"]}')
        if abs(float(L['R_t'])-float(ri['R_full']))>1e-3: add('HIGH','xfile:R_full',f'tournament {L["R_t"]} vs indicators {ri["R_full"]}')
        # published vintage must be frozen: compare to earlier snapshot rows (spot check: values never change once written)
        pub=list(csv.DictReader(open(os.path.join(troot,'regime_daily_published.csv'))))
        rcol=next((c for c in pub[0] if c.startswith('R_t') or c.lower().startswith('r_')),None)
        j5=[r for r in pub if r['date']=='2026-06-05']
        if j5 and rcol and abs(float(j5[0][rcol])-0.4269)>1e-4: add('CRITICAL','vintage:rewrite',f'published 2026-06-05 {rcol}={j5[0][rcol]} != 0.4269 (as-published value was rewritten)')
        # regime label vs value with hysteresis corridor (enter>=0.32, exit<0.28)
        R=float(ri['R_full']); lab=str(ri.get('regime','')).upper()
        if R<0.28 and 'ELEV' in lab: add('HIGH','label:hysteresis',f'R_full {R} below exit threshold but label {lab}')
        if R>=0.32 and lab in ('LOW RISK','NORMAL','CALM'): add('HIGH','label:hysteresis',f'R_full {R} above entry threshold but label {lab}')
        # Order 1-Oct-2026 [R1]: the cards' units and narratives (display only)
        for f_ in check_regime_display(ri): add(*f_)
    except Exception as _e:
        add('CRITICAL','referee:check_failed:regime',f'the regime checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- vol complex single source ----------
    try:
        if os.path.exists(os.path.join(troot,'vol_close_canonical.json')):
            can=T('vol_close_canonical.json'); vr=T('vol_regime.json'); it=T('intraday.json')
            for src,val,key in (('vol_regime',vr.get('curve',{}).get('spot_vix'),'vix'),('intraday',it.get('vix_now'),'vix')):
                c=can.get(key)
                if c is not None and val is not None and abs(float(val)-float(c))>0.011: add('HIGH','xfile:vol_single_source',f'{src} vix {val} vs canonical {c}')
        else: add('HIGH','arch:canonical_close','vol_close_canonical.json absent (single-source fix not landed)')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:vol_complex',f'the vol_complex checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- canonical close / intraday bot must respect the trading calendar ----------
    try:
        cp_=os.path.join(troot,'vol_close_canonical.json')
        if os.path.exists(cp_):
            can=json.load(open(cp_)); cd=to_date(can.get('date',''))
            if cd and not is_trading_day(cd): add('CRITICAL','calendar:canonical_close',f'vol_close_canonical dated {cd} (non-trading day): phantom close written')
            dead=[k for k,v in (can.get('providers') or {}).items() if v=='unavailable']
            if dead: add('HIGH','provider:vol_complex',f'canonical providers unavailable for {dead} (Cboe path failing; intraday nulls follow from this)')
            ri_=T('regime_indicators.json')
            if can.get('skew') is None and ri_.get('skew'): add('HIGH','xfile:skew_two_sources',f'regime_indicators has skew {ri_.get("skew")} while canonical is null: second source in use')
        it_=T('intraday.json'); its=to_date(it_.get('timestamp',''));
        if it_.get('session_date') is None and its and not is_trading_day(its): add('MEDIUM','calendar:intraday_bot',f'intraday bot ran on non-trading day {its} and wrote session=None')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:calendar',f'the calendar checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- safety inputs / null guards ----------
    try:
        it=T('intraday.json')
        for k in ('skew','vix_now','vix3m','vvix'):
            if it.get(k) is None: add('HIGH','nullguard',f'intraday.{k} is null; dependent safety checks must read IMPAIRED not false')
        comp=it.get('complacency_active')
        if comp is False and (it.get('skew') is None): add('CRITICAL','nullguard:complacency','complacency_active=false with skew=null (silent-false)')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:nullguard',f'the nullguard checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- stale-badge wiring per panel (HTML) ----------
    try:
        hp=os.path.join(os.path.dirname(troot.rstrip('/')),'t','index.html') if False else os.path.join(troot,'..','index.html')
        hp=hp if os.path.exists(hp) else os.path.join(troot,'index.html')
        if os.path.exists(hp):
            html=open(hp,encoding='utf-8').read()
            panels=[p_ for p_ in ('vol_regime','thesis_daily','regime_v4_daily','regime_indicators') if p_ in html]
            calls=len(re.findall(r'isStaleAsOf\(',html))
            if calls<len(panels): add('HIGH','ui:stale_badge',f'{calls} isStaleAsOf() call sites for {len(panels)} daily panels')
            if 'lastTradingSessionISO' in html and not re.search(r'lastTradingSessionISO[^}]{0,800}(HOLIDAY|holiday)',html,re.S): add('HIGH','ui:calendar',"lastTradingSessionISO() not holiday-aware")
    except Exception as _e:
        add('CRITICAL','referee:check_failed:badges',f'the badges checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- v4 ----------
    try:
        v4=list(csv.DictReader(open(os.path.join(troot,'regime_v4_daily.csv'))))
        if not os.path.exists(os.path.join(troot,'v4_delta_attribution.json')): add('MEDIUM','v4:explainability','delta attribution file absent')
        # memo Section 4, decision 1: the monthly-model columns (logistic_pc /
        # elastic_net) must be populated through the most recent monthly run's
        # training end. Blank tails were the nightly rescore wiping them.
        spp=os.path.join(troot,'v4_scoring_params.json')
        if v4 and os.path.exists(spp):
            sp_=json.load(open(spp)); te=to_date(sp_.get('train_end') or sp_.get('fitted_at') or '')
            mcols=[c for c in v4[0] if c.endswith(('_logistic_pc','_elastic_net'))]
            for c in mcols:
                last_nn=max((to_date(r['date']) for r in v4 if str(r.get(c,'')).strip()!='' and to_date(r['date'])), default=None)
                if te and (last_nn is None or last_nn<te):
                    add('HIGH','v4:monthly_columns',f'{c} populated through {last_nn} but monthly model train_end is {te}')
        # order 9-Sept B2.3: calibration evidence must be out-of-fold with a stated fold definition
        calp=os.path.join(troot,'v4_calibration.json')
        if os.path.exists(calp):
            cj=json.load(open(calp))
            if cj.get('evaluation')!='out_of_fold' or not cj.get('fold_definition'):
                add('MEDIUM','v4:calibration_evaluation','v4_calibration.json lacks evaluation: out_of_fold with a fold definition (in-sample reliability is not calibration evidence)')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:v4',f'the v4 checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- vol_regime validation integrity ----------
    try:
        vr=T('vol_regime.json'); val=vr.get('validation',{})
        ex=val.get('today_excluded') or val.get('excluded_today')
        if vr.get('as_of')==str(ls) and not ex: add('MEDIUM','validation:lookahead','today not excluded from reversion hit-rate')
        ev=val.get('event_day_only_reversion') or (val.get('walk_forward') or {}).get('event_day_only_reversion') or (val.get('walk_forward') or {}).get('event_day_only') or {}
        if ev.get('n',0)<20 and not (ev.get('caveat') or ev.get('not_yet_evidence') or ev.get('small_n_caveat') or ev.get('small_n')): add('MEDIUM','validation:small_n','event-day n<20 without caveat flag')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:vol_regime',f'the vol_regime checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- thesis / registry governance ----------
    try:
        reg=T('thesis_registry.json')
        if not reg.get('frozen_at'): add('CRITICAL','governance:registry','thesis registry not frozen')
        if reg.get('frozen_at') and not reg.get('approved_by'): add('HIGH','governance:provenance','registry frozen without approved_by')
        td=T('thesis_daily.json'); dd=(td.get('days') or [td])[-1]
        for k,v in dd.get('tiers',{}).items():
            u=v.get('unclassified_share',0)
            if u and u>0.15: add('HIGH','governance:coverage',f'{k}: unclassified share {u:.0%} > 15%')
            ne=v.get('n_eff'); ex_=v.get('exposure_invested') or v.get('exposure')
            if ne and ex_ and isinstance(ex_,dict):
                s=sum(ex_.values()); w=[x/s for x in ex_.values() if s]
                calc=1/sum(x*x for x in w) if w else None
                if calc and abs(calc-ne)>0.15: add('HIGH','identity:n_eff',f'{k}: n_eff {ne} vs recomputed {calc:.2f}')
        at=dd.get('attribution',{})
        for k,v in at.items():
            c=v.get('cum',{})
            if not c: continue
            # Repair 2026-09-16: a null component is a broken identity (the 15-Sept run served
            # nulls and this line crashed with a TypeError, recorded as "0 findings"). Same
            # severity as a non-summing identity; the referee must never crash on served data.
            nulls=[f for f in ('active','cash_eff','alloc_eff','selection') if c.get(f) is None]
            if nulls:
                add('CRITICAL','identity:attribution',f'{k}: null component(s) {nulls} — identity cannot be verified'); continue
            if abs(c.get('active',0)-(c.get('cash_eff',0)+c.get('alloc_eff',0)+c.get('selection',0)))>1e-4:
                add('CRITICAL','identity:attribution',f'{k}: components do not sum to active')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:governance',f'the governance checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- the book (order 16-Sept 2.3) ----------
    try:
        # holdings.json is the only holdings source; the ingestion job (2.1) writes it from the brokerage
        # export and records the export's own positions and cash in holdings_export.json. Three checks:
        #   holdings older than 5 sessions             → HIGH   (order 30-Sept C3: 20 was too loose for an
        #                                                        operator who trades weekly)
        #   served ⊄ export or export ⊄ served         → CRITICAL (the served book is not the account)
        #   book.json tickers ≠ holdings.json tickers  → CRITICAL (order 30-Sept C3: the analytics must be
        #                                                        the book that is held — the 16-Sept book
        #                                                        reported MU at 60% of risk after its sale)
        #   cash off the export by more than 1 percent → HIGH
        # Until an export is on record the set and cash checks report INFO, never a finding.
        hp_=os.path.join(troot,'holdings.json')
        if os.path.exists(hp_):
            hj=json.load(open(hp_)); hd=to_date(hj.get('as_of') or '')
            if not hd: add('HIGH','book:holdings_date','holdings.json: no as_of date')
            else:
                hage=len(trading_days(hd,ls))-1 if hd<=ls else 0
                if hage>5: add('HIGH','book:holdings_age',f'holdings.json as_of {hd} is {hage} sessions old (>5): confirm or re-export the account')
            served={str(h.get('ticker','')).upper() for h in hj.get('holdings',[]) if (h.get('shares') or 0)>0}
            bp_=os.path.join(troot,'book.json')
            if os.path.exists(bp_):
                try:
                    bj=json.load(open(bp_))
                    booked={str(p.get('ticker','')).upper() for p in bj.get('positions',[]) if (p.get('shares') or 0)>0}
                    if booked!=served:
                        add('CRITICAL','book:holdings_mismatch',f'book.json tickers {sorted(booked)} != holdings.json tickers {sorted(served)} — the analytics are not the held book')
                except Exception as e:
                    add('CRITICAL','book:holdings_mismatch',f'book.json unreadable for the holdings equality check ({type(e).__name__})')
            else:
                add('HIGH','book:holdings_mismatch','book.json absent — the holdings equality check cannot run')
            ep_=os.path.join(troot,'holdings_export.json')
            if os.path.exists(ep_):
                ex=json.load(open(ep_))
                exp={str(h.get('ticker','')).upper() for h in ex.get('positions',[]) if (h.get('shares') or 0)>0}
                miss_served=sorted(exp-served); miss_export=sorted(served-exp)
                if miss_served: add('CRITICAL','book:export_mismatch',f'export holdings absent from holdings.json: {miss_served}')
                if miss_export: add('CRITICAL','book:export_mismatch',f'served holdings absent from the latest export: {miss_export}')
                ec=ex.get('cash'); sc_=hj.get('cash')
                if ec is not None and sc_ is not None and float(ec)>0 and abs(float(sc_)/float(ec)-1)>0.01:
                    add('HIGH','book:cash_mismatch',f'holdings.json cash {sc_} differs from the export cash {ec} by {abs(float(sc_)/float(ec)-1)*100:.1f}% (>1%)')
                if hj.get('input_sha256') and ex.get('input_sha256') and hj['input_sha256']!=ex['input_sha256']:
                    add('HIGH','book:export_hash',f'holdings.json input_sha256 {str(hj["input_sha256"])[:12]} != export record {str(ex["input_sha256"])[:12]}')
            else:
                add('INFO','book:export',f'no brokerage export on record (holdings_export.json absent); holdings.json source: {hj.get("source")}')
        else:
            add('CRITICAL','book:holdings_missing','data/holdings.json absent — the only holdings source')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:book',f'the book checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- the fixed-income module (order 16-Sept) ----------
    try:
        # Served under data/bonds/ (outside the generic data/*.json sweep), so the module's
        # artifacts are checked here. Governance is enforced, not assumed:
        #   rates-regime state must carry the DIAGNOSTIC label                → CRITICAL (the gate)
        #   the credit read must be computed from option-adjusted spreads     → HIGH
        #   no served bond file may contain a buy/sell directive, edge, alpha → CRITICAL
        #   sleeve metrics missing / stale / with data gaps                   → HIGH
        sm_=os.path.join(troot,'bonds','sleeve_metrics.json')
        if os.path.exists(sm_):
            sm=json.load(open(sm_)); sd=to_date(sm.get('session_date') or '')
            if sd and sd<ls and (len(trading_days(sd,ls))-1)>5:
                add('HIGH','bond:sleeve_stale',f'sleeve_metrics.json session_date {sd} is {len(trading_days(sd,ls))-1} sessions old (>5)')
            sl=sm.get('sleeves',[])
            gaps=[r['ticker'] for r in sl if r.get('correlation_to_book') is None or r.get('vol_126_ann') is None]
            if gaps: add('HIGH','bond:sleeve_coverage',f'sleeves missing volatility/correlation (no price history?): {gaps}')
            noyield=[r['ticker'] for r in sl if not r.get('yield_available')]
            if noyield: add('INFO','bond:sleeve_yield',f'sleeves with distribution yield unavailable (not substituted): {noyield}')
        else:
            add('HIGH','bond:sleeve_metrics_missing','data/bonds/sleeve_metrics.json absent — the fixed-income sleeve menu has no data')
        stp_=os.path.join(troot,'bonds','states.json')
        if os.path.exists(stp_):
            stj=json.load(open(stp_))
            rr=(stj.get('rates_regime') or {})
            if rr and str(rr.get('label','')).upper()!='DIAGNOSTIC':
                add('CRITICAL','bond:diagnostic_gate',f'rates-regime state label is {rr.get("label")!r}, not DIAGNOSTIC — the sizing gate is not held')
            cr=(stj.get('credit') or {})
            meth=str(cr.get('method','')).lower()
            if cr and ('option-adjusted' not in meth and 'oas' not in meth):
                add('HIGH','bond:credit_method','credit read method does not reference option-adjusted spreads (an ETF price ratio is prohibited)')
            # Order 1-Oct-2026 [R3]: the carry basis is the curve-implied yield
            fred_=None
            try:
                import pandas as _pd
                fred_=_pd.read_parquet(os.path.join(troot,'source','fred_indicators.parquet')); fred_.index=_pd.to_datetime(fred_.index)
            except Exception:
                fred_=None
            for f_ in check_bond_carry(stj, json.load(open(sm_)) if os.path.exists(sm_) else {}, fred_): add(*f_)
            # [R5.3] the rates-stress monitor stays DIAGNOSTIC and unread by R, the headline, the overlay, sizing, the brief's colours
            for f_ in check_rates_stress_gate(stj, rates_stress_sources(os.path.dirname(os.path.abspath(troot)))): add(*f_)
        # language: the words edge and alpha appear nowhere in the module; no buy/sell directive
        for bf in ('bonds/sleeve_metrics.json','bonds/states.json','bonds/sleeve_universe.json'):
            bp_=os.path.join(troot,bf)
            if os.path.exists(bp_):
                blob=open(bp_).read().lower()
                hits=[w for w in ('edge','alpha') if re.search(r'\b'+w+r'\b',blob)]
                if hits: add('CRITICAL','bond:language',f'{bf} contains prohibited word(s) {hits} (order §9.9)')
                for tok in ('"action":"buy"','"action":"sell"','"recommendation":"buy"','"recommendation":"sell"','buy now','sell now'):
                    if tok in blob: add('CRITICAL','bond:directive',f'{bf} contains a buy/sell directive ({tok!r})')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:bonds',f'the bonds checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- the options lens (order 26-Sept, Phase 6) ----------
    try:
        # The chain vintage of the session must exist, be pulled inside 15:30–16:00 ET on a trading
        # day (a backfill is flagged and reported, never silently accepted), be immutable once written
        # (per-file sha256 recorded at write time and re-checked here), carry live bid-ask quotes on
        # at least 70% of front-expiry strikes for each held name (else the name's options column
        # reads `impaired`), every computed ATM implied volatility must lie in [0.05, 3.0], every held
        # name must have a next-earnings date, and no served options file may carry the provider's IV
        # field, a directive, or the words edge/alpha.
        oroot=os.path.join(troot,'options'); vroot=os.path.join(oroot,'vintages')
        held_=set()
        if os.path.exists(hp_):
            held_={str(h.get('ticker','')).upper() for h in json.load(open(hp_)).get('holdings',[]) if (h.get('shares') or 0)>0}
        if os.path.isdir(vroot):
            vints=sorted(d for d in os.listdir(vroot) if len(d)==10 and os.path.isdir(os.path.join(vroot,d)) and os.path.exists(os.path.join(vroot,d,'_meta.json')))
            # Order 5-Oct-2026, section 3: (1) the trading day's vintage exists (HIGH, with the reason the index
            # records); (2) the captured share of the last 20 trading days is at least 90% (HIGH); (3) every
            # scheduled vintage was pulled inside 15:30–16:00 ET: pulled_at, completed_at and each ticker's
            # written_at (CRITICAL: an after-hours pull). A new after-hours backfill is CRITICAL as well; the
            # 25-Sept seed is the one flagged backfill. The index must agree with the folders (HIGH).
            ip_=os.path.join(vroot,'_index.json')
            idx_={e.get('date'):e for e in (json.load(open(ip_)).get('days',[]) if os.path.exists(ip_) else [])}
            if not os.path.exists(ip_):
                add('HIGH','options:index','data/options/vintages/_index.json absent (vintage_index.py runs at 16:05 ET and in the nightly)')
            if not vints or vints[-1]<ls.isoformat():
                e_=idx_.get(ls.isoformat()) or {}
                why_=f"reason {e_.get('reason')} ({e_.get('evidence','')})" if e_.get('status')=='missing' else 'not yet recorded in _index.json'
                add('HIGH','options:vintage_missing',f'no chain vintage for the last session {ls} (latest: {vints[-1] if vints else "none"}); {why_}')
            if idx_:
                last20=[e for d_,e in sorted(idx_.items()) if d_<=ls.isoformat()][-20:]
                cap_=sum(1 for e in last20 if e.get('status')=='captured')
                if last20 and cap_/len(last20)<0.90:
                    miss_=[f"{e['date']} {e.get('reason')}" for e in last20 if e.get('status')!='captured']
                    add('HIGH','options:captured_share',f'{cap_} of the last {len(last20)} trading days captured ({cap_/len(last20)*100:.0f}% < 90%); missing: {miss_[:8]}')
                for d_,e in idx_.items():
                    has_=d_ in vints
                    if e.get('status')=='captured' and not has_: add('HIGH','options:index',f'_index.json says {d_} captured but no vintage folder with _meta.json exists')
                    if e.get('status')=='missing' and has_: add('HIGH','options:index',f'_index.json says {d_} missing but its vintage exists (rerun vintage_index.py)')
            for v_ in vints:
                meta_v=json.load(open(os.path.join(vroot,v_,'_meta.json')))
                kind_v=str(meta_v.get('snapshot_kind',''))
                if kind_v=='backfill':
                    if v_!='2026-09-25': add('CRITICAL','options:backfill',f'vintage {v_} is an after-hours backfill (pulled {meta_v.get("pulled_at")}); missed days are never backfilled (order 5-Oct-2026)')
                    continue
                stamps=[('pulled_at',meta_v.get('pulled_at')),('completed_at',meta_v.get('completed_at'))]+[(f'{tk}.written_at',m.get('written_at')) for tk,m in (meta_v.get('tickers') or {}).items()]
                bad_=[]
                for nm_,ts_ in stamps:
                    if not ts_:
                        if nm_=='pulled_at': bad_.append('pulled_at missing')
                        continue
                    ts_=str(ts_); hm_=(int(ts_[11:13]),int(ts_[14:16])) if len(ts_)>=16 else None
                    if ts_[:10]!=v_ or not hm_ or not ((15,30)<=hm_<(16,0)): bad_.append(f'{nm_} {ts_[:16]}')
                if bad_ or not is_trading_day(to_date(v_)):
                    add('CRITICAL','options:snapshot_window',f'vintage {v_} has timestamps outside 15:30–16:00 ET on its trading day: {bad_[:4]} (an after-hours pull is prohibited)')
            if vints:
                vd=os.path.join(vroot,vints[-1]); mp=os.path.join(vd,'_meta.json')
                meta=json.load(open(mp)) if os.path.exists(mp) else {}
                kind=str(meta.get('snapshot_kind',''))
                if kind=='backfill':
                    add('INFO','options:snapshot_backfill',f'vintage {vints[-1]} is the flagged 25-Sept backfill (post-close quotes as retained by the provider), not a 15:45 snapshot')
                elif kind!='scheduled':
                    add('HIGH','options:snapshot_kind',f'vintage {vints[-1]} has no snapshot_kind in _meta.json')
                tk_meta=meta.get('tickers',{})
                try:
                    import hashlib
                    for tk,m in tk_meta.items():
                        fp=os.path.join(vd,f'{tk}.parquet')
                        if not os.path.exists(fp): add('HIGH','options:vintage_file',f'{vints[-1]}/{tk}.parquet recorded in _meta but absent'); continue
                        if m.get('sha256') and hashlib.sha256(open(fp,'rb').read()).hexdigest()!=m['sha256']:
                            add('CRITICAL','options:immutable',f'{vints[-1]}/{tk}.parquet differs from the sha256 recorded at write time — a vintage was rewritten')
                except Exception as e:
                    add('MEDIUM','options:immutable',f'immutability check could not run ({type(e).__name__})')
                for tk in sorted(held_):
                    m=tk_meta.get(tk)
                    if not m: add('HIGH','options:held_missing',f'held name {tk} absent from vintage {vints[-1]}'); continue
                    sh=m.get('front_live_quote_share')
                    if sh is None or sh<0.70: add('HIGH','options:live_quotes',f'{tk}: {"no" if sh is None else f"{sh*100:.0f}% of"} front-expiry strikes carry live bid-ask quotes (<70%) — the options column reads impaired')
                try:
                    import pandas as _pd
                    for tk in list(tk_meta)[:60]:
                        fp=os.path.join(vd,f'{tk}.parquet')
                        if os.path.exists(fp) and 'impliedVolatility' in _pd.read_parquet(fp,columns=None).columns:
                            add('CRITICAL','options:provider_iv',f'{vints[-1]}/{tk}.parquet carries the provider impliedVolatility field — must never be stored'); break
                except Exception as e:
                    add('INFO','options:provider_iv',f'parquet column check skipped ({type(e).__name__})')
        lp_=os.path.join(oroot,'lens.json')
        if os.path.exists(lp_):
            lj=json.load(open(lp_)); bad=[]
            for tk,n in (lj.get('names') or {}).items():
                vp_=(n.get('volatility') or {})
                for k in ('iv30','iv90'):
                    v=vp_.get(k)
                    if v is not None and not (0.05<=float(v)<=3.0): bad.append(f'{tk}:{k}={v}')
            if bad: add('CRITICAL','options:iv_range',f'ATM implied volatility outside [0.05, 3.0]: {bad[:6]}')
            if 'impliedVolatility' in open(lp_).read(): add('CRITICAL','options:provider_iv','lens.json mentions the provider impliedVolatility field')
            # Order 30-Sept C2: every held name's lens spot date must be the last session (the GEV record
            # carried "spot_source: 2026-09-25 close" on 30 September while the snapshot job was not running).
            stale=[]
            for tk in sorted(held_):
                n=(lj.get('names') or {}).get(tk) or {}
                # spot_source is either "YYYY-MM-DD close" (the fallback) or "provider 1-minute tape" (a
                # scheduled vintage: the spot is the tape at the snapshot, so its date is the vintage's pulled_at)
                src_=str(n.get('spot_source') or '')
                sd_=to_date(src_[:10])
                if sd_ is None and 'tape' in src_.lower(): sd_=to_date(str(lj.get('pulled_at') or '')[:10])
                if sd_ is None or sd_!=ls: stale.append(f'{tk}: {src_ or "no spot"}')
            if stale: add('HIGH','options:lens_spot_stale',f'held names whose lens spot is not the last session {ls}: {stale[:6]}')
            # C1: the event-implied move must be computed by the bracketing method (or its flagged fallback)
            meth=str((lj.get('definitions') or {}).get('event_move',''))
            if 'bracketing' not in meth.lower(): add('HIGH','options:event_method','lens.json event_move definition is not the bracketing method (order 30-Sept C1)')
        ep_=os.path.join(oroot,'earnings_reactions.json')
        if os.path.exists(ep_) and held_:
            ej=json.load(open(ep_)).get('names',{})
            noe=[tk for tk in sorted(held_) if not ((ej.get(tk) or {}).get('next') or {}).get('date')]
            if noe: add('HIGH','options:next_earnings',f'held names without a next-earnings date: {noe}')
        for of in ('options/lens.json','options/earnings_reactions.json','options/hedges.json'):
            op_=os.path.join(troot,of)
            if os.path.exists(op_):
                blob=open(op_).read().lower()
                hits=[w for w in ('edge','alpha') if re.search(r'\b'+w+r'\b',blob)]
                if hits: add('CRITICAL','options:language',f'{of} contains prohibited word(s) {hits} (order §9.8)')
                for tok in ('"action":"buy"','"action":"sell"','"recommendation":"buy"','"recommendation":"sell"','buy now','sell now'):
                    if tok in blob: add('CRITICAL','options:directive',f'{of} contains a buy/sell directive ({tok!r})')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:options',f'the options checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- the entry state (order 2-Oct-2026, E1/E2) ----------
    try:
        # States from the allowed set (or none, with a reason); every card name graded; the stop respects its
        # 200-day floor; a size never leaves the name at or above 40% of the book's risk; the label stays
        # DIAGNOSTIC until the registered validation reports a pass; the mean-reversion reference carries no
        # buy-zone language anywhere served; the transition log parses and holds the session's transitions.
        esp_=os.path.join(troot,'entry_state.json')
        if os.path.exists(esp_):
            ej_=json.load(open(esp_)); en_=ej_.get('names') or {}
            # rules version 3 (revised order of 6-Oct-2026): the WAIT state is removed, so a WAIT anywhere is outside the set
            allowed_={'AVOID','WATCH','READY','READY-HALF'}
            bad_=[f'{k}:{v.get("state")}' for k,v in en_.items() if v.get('state') is not None and v.get('state') not in allowed_]
            if bad_: add('HIGH','entry:states',f'entry_state.json states outside the rule set: {bad_[:6]}')
            nr_=[k for k,v in en_.items() if v.get('state') is None and not v.get('reason')]
            if nr_: add('HIGH','entry:states',f'names without a state and without a reason: {nr_[:6]}')
            cards_=ej_.get('cards') or {}
            miss_=[k for g in ('held','board','tiers') for k in (cards_.get(g) or []) if k not in en_]
            if miss_: add('HIGH','entry:cards',f'card names missing from entry_state.json: {sorted(set(miss_))[:8]}')
            nos_=[k for k in (cards_.get('held') or []) if (en_.get(k) or {}).get('state') is None]
            if nos_: add('MEDIUM','entry:held_ungraded',f'held names without an entry state: {[(k,(en_.get(k) or {}).get("reason")) for k in nos_]}')
            # rules version 2 (order 6-Oct-2026): the stop is the 40-session low less 1 ATR (no 200-day floor); READY
            # needs a size factor of at least a quarter, READY-HALF the earnings modifier; a ceiling flag caps at WATCH;
            # AVOID only below the 200-day with negative momentum
            stp_,mod_,cap_g,gate_=[],[],[],[]
            for k,v in en_.items():
                st_=v.get('state')
                if not st_: continue
                if v.get('stop') is not None and v.get('range_lo') is not None and v.get('atr') is not None and abs(v['stop']-(v['range_lo']-v['atr']))>0.011: stp_.append(k)
                if st_ in ('READY','READY-HALF') and (v.get('size_factor') is None or v['size_factor']<0.25-1e-9): mod_.append(f'{k}: {st_} at size factor {v.get("size_factor")}')
                if st_=='READY-HALF' and 'earnings' not in [m.get('name') for m in (v.get('modifiers') or [])]: mod_.append(f'{k}: READY-HALF without the earnings modifier')
                if v.get('ceiling_flag') and st_ in ('READY','READY-HALF'): cap_g.append(k)
                t_=v.get('trend') or {}
                if st_=='AVOID' and not (t_.get('below_200d') and (t_.get('mom_12_1') or 0)<0): gate_.append(k)
            if stp_: add('HIGH','entry:stop_rule',f'stops that are not the 40-session low less 1 ATR: {stp_[:6]}')
            if mod_: add('HIGH','entry:modifiers',f'states inconsistent with the size modifiers: {mod_[:6]}')
            if cap_g: add('HIGH','entry:ceiling_cap',f'READY although the ceiling flag is set (it caps at WATCH): {cap_g[:6]}')
            if gate_: add('HIGH','entry:trend_gate',f'AVOID without the gate condition (below the 200-day AND negative momentum): {gate_[:6]}')
            # version 3: heavily shorted = days-to-cover >= 7 OR short interest >= 20% of the float; the flag, its stated
            # cause and the size modifier must agree with the two measures on the card
            cfgm_={}
            try: cfgm_=(json.load(open(os.path.join(troot,'entry_state_config.json'))).get('modifiers') or {})
            except Exception: pass
            dmin_,smin_=cfgm_.get('days_to_cover_min',7.0),cfgm_.get('short_pct_float_min',0.20)
            sh_=[]
            for k,v in en_.items():
                if not v.get('state'): continue
                si_=v.get('short_interest') or {}
                want_=bool((si_.get('days_to_cover') is not None and si_['days_to_cover']>=dmin_) or (si_.get('short_pct_float') is not None and si_['short_pct_float']>=smin_))
                if bool(v.get('heavily_shorted'))!=want_: sh_.append(f'{k}: flag {v.get("heavily_shorted")} vs days-to-cover {si_.get("days_to_cover")}, short of float {si_.get("short_pct_float")}')
                if v['state'] in ('READY','READY-HALF','WATCH') and v.get('size_factor') is not None and want_!=('heavily_shorted' in [m.get('name') for m in (v.get('modifiers') or [])]):
                    sh_.append(f'{k}: heavily_shorted modifier does not match the flag')
            if sh_: add('HIGH','entry:short_flag',f'heavily-shorted flag inconsistent with days-to-cover / short interest of the float: {sh_[:6]}')
            cap_=[]
            for k,v in en_.items():
                z_=v.get('size') or {}
                if v.get('state') in ('WATCH','READY','READY-HALF') and z_.get('shares') is None and not z_.get('reason'): cap_.append(f'{k}: no size, no reason')
                if (z_.get('shares') or 0)>0 and ((z_.get('book_after') or {}).get('risk_share_name') or 0)>=0.40: cap_.append(f'{k}: risk share {(z_.get("book_after") or {}).get("risk_share_name")}')
            if cap_: add('HIGH','entry:size',f'sizes breaking the rule (40% risk-share cap or missing): {cap_[:6]}')
            vp_=os.path.join(troot,'entry_state_validation.json')
            verdict_=(json.load(open(vp_)).get('verdict') if os.path.exists(vp_) else None)
            cfgp_=os.path.join(troot,'entry_state_config.json')
            lab_=[str(ej_.get('label'))]+([str(json.load(open(cfgp_)).get('label'))] if os.path.exists(cfgp_) else [])
            if any(l!='DIAGNOSTIC' for l in lab_) and verdict_!='PASS':
                add('CRITICAL','entry:diagnostic_gate',f'entry state labelled {lab_} while the registered validation verdict is {verdict_!r} (DIAGNOSTIC until it reports a pass)')
            _lang(esp_,'entry')
            lgp_=os.path.join(troot,'entry_state_log.jsonl')
            if os.path.exists(lgp_):
                try:
                    keys_={(x['date'],x['ticker'],x['from'],x['to'],x['reason']) for x in (json.loads(l) for l in open(lgp_,encoding='utf-8') if l.strip())}
                    lost_=[t_['ticker'] for t_ in (ej_.get('transitions_today') or []) if (t_['date'],t_['ticker'],t_['from'],t_['to'],t_['reason']) not in keys_]
                    if lost_: add('MEDIUM','entry:log',f'transitions of the session not in entry_state_log.jsonl: {lost_[:6]}')
                except Exception as e:
                    add('HIGH','entry:log',f'entry_state_log.jsonl unreadable ({e})')
            elif ej_.get('transitions_today'): add('MEDIUM','entry:log','transitions reported but entry_state_log.jsonl is absent')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:entry',f'the entry checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- free-analyst-data order (7-Oct-2026), task C: the estimate snapshots ----------
    try:
        # The latest snapshot is at most one trading day old and covers at least 95% of the universe; every captured
        # file matches the sha256 the index recorded (immutable: CRITICAL); the revision variables stay DIAGNOSTIC and
        # out of every score until 12 months of snapshots exist and the registered test reports (CRITICAL).
        asn_=os.path.join(troot,'analyst','snapshots'); aix_=os.path.join(asn_,'_index.json')
        if os.path.isdir(asn_):
            from trading_calendar import last_completed_session as _lcs, prev_trading_day as _ptd
            import datetime as _dt
            snaps_=sorted(f[:10] for f in os.listdir(asn_) if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json',f))
            S_=_lcs(); P_=_ptd(_dt.date.fromisoformat(S_))
            if not snaps_:
                add('INFO','analyst:snapshot_missing','no analyst-estimate snapshot yet (the first is written by the nightly of 7 Oct 2026)')
            else:
                L_=snaps_[-1]
                if L_<P_: add('HIGH','analyst:snapshot_stale',f'latest analyst snapshot {L_} is more than one trading day old (last session {S_})')
                try:
                    lj_=json.load(open(os.path.join(asn_,L_+'.json')))
                    cov_=lj_.get('coverage'); un_=(lj_.get('universe') or {}).get('n')
                    if cov_ is None or cov_<0.95: add('HIGH','analyst:snapshot_coverage',f'snapshot {L_} covers {cov_!r} of the universe ({lj_.get("captured")} of {un_}; at least 95% required)')
                    if lj_.get('immutable') is not True: add('HIGH','analyst:snapshot_flag',f'snapshot {L_} is not flagged immutable')
                except Exception as e: add('HIGH','analyst:snapshot_unreadable',f'snapshot {L_}: {e}')
                if os.path.exists(aix_):
                    try:
                        import hashlib as _hl
                        ix_=json.load(open(aix_)); bad_=[]
                        for e_ in (ix_.get('days') or []):
                            if e_.get('status')=='captured' and e_.get('sha256'):
                                fp_=os.path.join(asn_,e_['date']+'.json')
                                if os.path.exists(fp_) and _hl.sha256(open(fp_,'rb').read()).hexdigest()!=e_['sha256']: bad_.append(e_['date'])
                        if bad_: add('CRITICAL','analyst:snapshot_immutable',f'snapshot files rewritten since the index recorded them: {bad_[:6]}')
                        missing_=[e_['date'] for e_ in (ix_.get('days') or []) if e_.get('status')=='missing']
                        if missing_: add('INFO','analyst:snapshot_index',f'{len(missing_)} missed day(s) on record: {missing_[-5:]}')
                    except Exception as e: add('HIGH','analyst:snapshot_index',f'_index.json unreadable ({e})')
                else: add('MEDIUM','analyst:snapshot_index','data/analyst/snapshots/_index.json absent')
            _lang(aix_,'analyst')
        arv_=os.path.join(troot,'analyst','revisions.json')
        if os.path.exists(arv_):
            try:
                rv_=json.load(open(arv_)); mo_=((rv_.get('snapshots') or {}).get('months') or 0)
                if rv_.get('label')!='DIAGNOSTIC' and mo_<12: add('CRITICAL','analyst:diagnostic_gate',f"revisions.json labelled {rv_.get('label')!r} with {mo_} months of snapshots (DIAGNOSTIC until 12 months and a registered test)")
                if rv_.get('in_score') is not False: add('CRITICAL','analyst:in_score','revisions.json marks the revision variables as score inputs')
            except Exception as e: add('HIGH','analyst:revisions',f'revisions.json unreadable ({e})')
            _lang(arv_,'analyst')
            # F4: a provider-reported consensus row in the registered test's inputs is CRITICAL; G1: the look-ahead filter
            for _rf in ('walkforward_test.json','candidate_list_test_result.json'):
                _rp=os.path.join(troot,'analyst',_rf)
                if not os.path.exists(_rp): continue
                try:
                    _rj=json.load(open(_rp))
                    _cr=((_rj.get('inputs') or {}).get('consensus_rows') or {})
                    if (_cr.get('provider_reported_rows_in_test') or 0)>0: add('CRITICAL','analyst:provider_rows_in_test',f"{_rf}: {_cr['provider_reported_rows_in_test']} provider-reported consensus rows entered the registered test (cards-only rows; F4)")
                    _opts=((_rj.get('table') or {}).get('options') or {}); _opts2=(_rj.get('options') or {})
                    if _opts.get('current_universe_only') or _opts2.get('current_universe_only'): add('CRITICAL','analyst:lookahead_filter',f"{_rf}: the run set current_universe_only (a filter on today's universe; look-ahead)")
                except Exception as _e: add('HIGH','analyst:test_result',f'{_rf} unreadable ({type(_e).__name__})')
            scp2_=os.path.join(troot,'screen','scores.json')
            if os.path.exists(scp2_):
                try:
                    rows2_=(json.load(open(scp2_)).get('watchlist') or [])
                    ank_=sorted({k for r in rows2_ for k in r if str(k).startswith('an_')})
                    if ank_: add('CRITICAL','analyst:in_score',f'analyst variables present in the screen scores before validation: {ank_[:6]}')
                except Exception: pass
    except Exception as _e:
        add('CRITICAL','referee:check_failed:analyst',f'the analyst checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- order 6-Oct-2026 (revised) 6b: the operator's picks against QQQ ----------
    try:
        # The number of independent decisions accompanies every figure; index funds, sector funds and gold stay out;
        # the summed difference is the sum of its positions; below about 30 decisions the panel says it cannot
        # distinguish skill from chance; the window ends on the record's last session.
        pqp_=os.path.join(troot,'picks_vs_qqq.json')
        if os.path.exists(pqp_):
            pq_=json.load(open(pqp_)); pcf_={}
            try: pcf_=json.load(open(os.path.join(troot,'picks_vs_qqq_config.json')))
            except Exception: pass
            exl_={t.upper() for k,v in (pcf_.get('exclude') or {}).items() if isinstance(v,list) for t in v}
            nod_,exin_,idn_=[],[],[]
            mind_=pq_.get('min_decisions') or 30
            for w_ in (pq_.get('windows') or []):
                if 'operator' not in w_: continue
                groups_=[('operator',w_['operator'])]+[(tid,t) for tid,t in ((w_.get('algorithmic') or {}).get('tiers') or {}).items()]
                groups_.append(('algorithmic',w_.get('algorithmic') or {}))
                for g_,x_ in groups_:
                    sm_=x_.get('summary') or {}
                    if not isinstance(sm_.get('decisions'),int): nod_.append(f"{w_['id']}:{g_}")
                    if sm_.get('closed') and not isinstance(sm_.get('closed_decisions'),int): nod_.append(f"{w_['id']}:{g_}:closed")
                    pos_=x_.get('positions')
                    if pos_ is None and g_=='algorithmic': pos_=[q for t in (x_.get('tiers') or {}).values() for q in (t.get('positions') or [])]
                    for q in (pos_ or []):
                        if str(q.get('ticker','')).upper() in exl_: exin_.append(f"{w_['id']}:{g_}:{q.get('ticker')}")
                    if pos_ is not None and sm_:
                        tot_=sum(q.get('diff_usd') or 0 for q in pos_)
                        if abs(tot_-(sm_.get('diff_usd') or 0))>0.05*max(1,len(pos_)): idn_.append(f"{w_['id']}:{g_} positions {tot_:.2f} vs summary {sm_.get('diff_usd')}")
                        if sm_.get('dollars_in') and sm_.get('diff_pct') is not None and abs(sm_['diff_usd']/sm_['dollars_in']-sm_['diff_pct'])>1e-4: idn_.append(f"{w_['id']}:{g_} percent")
            low_=min([(w_['operator']['summary'].get('decisions') or 0) for w_ in (pq_.get('windows') or []) if 'operator' in w_] or [0])
            if low_<mind_ and 'cannot distinguish skill from chance' not in str(pq_.get('skill_note','')):
                add('HIGH','picks:skill_note',f'fewer than {mind_} independent decisions but the panel does not say the comparison cannot distinguish skill from chance')
            if nod_: add('HIGH','picks:decisions',f'figures without the number of independent decisions: {nod_[:6]}')
            if exin_: add('HIGH','picks:excluded',f'index funds, sector funds or gold inside the comparison: {exin_[:6]}')
            if idn_: add('HIGH','picks:identity',f'summary figures that are not the sum of their positions: {idn_[:6]}')
            if str(pq_.get('label'))!='DESCRIPTIVE': add('HIGH','picks:label',f"picks_vs_qqq.json labelled {pq_.get('label')!r}, not DESCRIPTIVE")
            if str(pq_.get('as_of'))[:10]!=str(L.get('date'))[:10]: add('MEDIUM','picks:as_of',f"picks_vs_qqq.json as of {pq_.get('as_of')} but the tournament record ends {L.get('date')}")
            _lang(pqp_,'picks')
        elif os.path.exists(os.path.join(troot,'picks_vs_qqq_config.json')):
            add('HIGH','picks:missing','picks_vs_qqq.json absent (the 6b panel has nothing to render)')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:picks',f'the picks checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- order 6-Oct-2026: provider checks, earnings dates and timing, the long range ----------
    try:
        pfp_=os.path.join(troot,'provider_flags.json')
        if os.path.exists(pfp_):
            pf_=json.load(open(pfp_)); pn_=pf_.get('names') or {}
            badf_=[f'{k}:{f.get("field")}' for k,v in pn_.items() for f in (v.get('flags') or []) if f.get('field') not in ('forwardPE','freeCashflow','revenueGrowth') or not f.get('reason')]
            if badf_: add('HIGH','provider:flags',f'provider flags without a known field or a reason: {badf_[:6]}')
            scp_=os.path.join(troot,'screen','scores.json')
            if os.path.exists(scp_):
                rows_=(json.load(open(scp_)).get('watchlist') or [])
                built_with_=any('provider_suspect(' in str(r.get('data_flags','')) for r in rows_)
                miss_=[]
                for r in rows_:
                    fl_=[f['field'] for f in ((pn_.get(str(r.get('ticker')).upper()) or {}).get('flags') or [])]
                    for fld in fl_:
                        if f'provider_suspect({fld})' not in str(r.get('data_flags','')): miss_.append(f"{r.get('ticker')}:{fld}")
                if miss_:
                    if built_with_: add('HIGH','provider:excluded',f'flagged provider fields still in the screen scores: {miss_[:6]}')
                    else: add('INFO','provider:excluded',f'the screen has not been rebuilt with the provider checks yet ({len(miss_)} flagged fields on the board await the next nightly)')
        edp_=os.path.join(troot,'earnings_dates.json')
        if os.path.exists(edp_):
            en2_=(json.load(open(edp_)).get('names') or {})
            badc_=[k for k,v in en2_.items() if v.get('conflict') and not (v.get('conflict_text') and v.get('date'))]
            if badc_: add('HIGH','earnings:conflict',f'earnings-date conflicts without the sources shown or a decided date: {badc_[:6]}')
            if os.path.exists(esp_):
                esn_=(json.load(open(esp_)).get('names') or {})
                hid_=[k for k,v in en2_.items() if v.get('conflict') and k in esn_ and esn_[k].get('state') and not ((esn_[k].get('earnings') or {}).get('conflict'))]
                if hid_: add('HIGH','earnings:conflict',f'an earnings-date conflict not carried to the card: {hid_[:6]}')
        erp_=os.path.join(troot,'options','earnings_reactions.json'); scp2_=os.path.join(troot,'screen','scores.json')
        if os.path.exists(erp_):
            # the names the reaction history covers: the held names and the screen board (options_common.analyzed_universe)
            an_=set(held_)|({str(r.get('ticker')).upper() for r in (json.load(open(scp2_)).get('watchlist') or [])} if os.path.exists(scp2_) else set())
            rx_=(json.load(open(erp_)).get('names') or {})
            untimed_=[f'{k} {h.get("date")}' for k in sorted(an_) for h in ((rx_.get(k) or {}).get('history') or []) if h.get('time_of_day') not in ('before_open','after_close') or not h.get('timing_source')]
            if untimed_: add('HIGH','earnings:timing',f'reactions without a release timing and its source (before open: prior close to release-day close; after close: release-day close to next): {untimed_[:6]}')
        lrp_=os.path.join(troot,'long_range.json')
        if os.path.exists(lrp_) and os.path.exists(esp_):
            lrn_=(json.load(open(lrp_)).get('names') or {})
            cards2_=(json.load(open(esp_)).get('cards') or {})
            cn_=sorted({k for g in ('held','board','tiers','review') for k in (cards2_.get(g) or [])})
            nolr_=[k for k in cn_ if k not in lrn_]
            old_=[k for k in cn_ if k in lrn_ and lrn_[k].get('fetched_at') and to_date(lrn_[k]['fetched_at'][:10]) and (to_date(ls.isoformat())-to_date(lrn_[k]['fetched_at'][:10])).days>14]
            if nolr_: add('HIGH','long_range:coverage',f'card names without a long-range record (5-year and all-time highs, ceilings): {nolr_[:8]}')
            if old_: add('MEDIUM','long_range:stale',f'card names whose long-range history is more than 14 days old: {old_[:8]}')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:provider',f'the provider checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- global rates (order 6-Oct-2026, section 8) ----------
    try:
        # each series fresh within its expected lag (business days for daily series, 8 for the term premiums, 45 calendar
        # days for the OECD monthly averages; data/rates/global_rates_config.json); Panel B's identities within 2 bp; every
        # panel row carries its date; the day's rates vintage exists and matches the sha256 recorded when it was written
        gcfg_p=os.path.join(troot,'rates','global_rates_config.json'); gm_p=os.path.join(troot,'rates','series_meta.json'); gr_p=os.path.join(troot,'rates','global_rates.json')
        if os.path.exists(gcfg_p) and os.path.exists(gm_p):
            gcfg_=json.load(open(gcfg_p)); gm_=json.load(open(gm_p))
            def _bd_between(a,b):
                n=0; d=a
                while d<b:
                    d+=timedelta(days=1)
                    if d.weekday()<5: n+=1
                return n
            stale_=[]
            for k,sdef in (gcfg_.get('series') or {}).items():
                m_=gm_.get(k) or {}; d_=to_date(str(m_.get('as_of') or '')[:10])
                if d_ is None: stale_.append(f'{k}: no data'); continue
                if sdef.get('freq')=='monthly':
                    if (ls-d_).days>sdef.get('lag_days',45)+31: stale_.append(f'{k}: {d_} (monthly, lag {sdef.get("lag_days",45)} days)')
                elif _bd_between(d_,ls)>sdef.get('lag_bd',1): stale_.append(f'{k}: {d_} ({_bd_between(d_,ls)} business days behind {ls}, allowed {sdef.get("lag_bd",1)})')
            if stale_: add('HIGH','rates:stale',f'global-rates series older than their expected lag: {stale_[:8]}')
        if os.path.exists(gr_p):
            g_=json.load(open(gr_p)); idn_=(g_.get('panel_b') or {}).get('identities') or {}
            tol_=idn_.get('tolerance_pp',0.02)
            for k_,lab_ in (('b1_gap_pp','nominal = real + breakeven'),('b2_gap_pp','nominal = expected short rate + term premium')):
                if idn_.get(k_) is None or abs(idn_[k_])>tol_+1e-9: add('HIGH','rates:identity',f'Panel B identity {lab_} off by {idn_.get(k_)} pp (tolerance {tol_})')
            nod_=[r.get('code') for r in ((g_.get('panel_a') or {}).get('rows') or []) if not r.get('date')]
            nod_+=[x.get('series') for x in (g_.get('panel_d') or []) if not x.get('date')]
            nod_+=[k for k,v in ((g_.get('panel_b') or {}).get('current') or {}).items() if not v.get('date')]
            nod_+=[x.get('id') for grp in ('worsening','reversal') for x in ((g_.get('panel_e') or {}).get(grp) or []) if not x.get('as_of')]
            if nod_: add('HIGH','rates:as_of',f'global-rates values shown without their as-of date: {nod_[:8]}')
            txt_=json.dumps(g_).lower()
            for neg_ in ('no forecast and no recommendation','no recommendation','not a recommendation','no forecast','not a forecast'):
                txt_=txt_.replace(neg_,'')                   # the panels' own disclaimers
            for w_ in ('we expect','will rise','will fall','buy ','sell ','recommend'):
                if w_ in txt_: add('HIGH','rates:language',f'global_rates.json contains forecast or recommendation wording ({w_.strip()!r})')
            _lang(gr_p,'rates')
        vi_p=os.path.join(troot,'rates','vintages','_index.json')
        if os.path.exists(gcfg_p):
            vidx_=json.load(open(vi_p)).get('vintages',{}) if os.path.exists(vi_p) else {}
            import hashlib as _hl2
            for d_,rec_ in vidx_.items():
                vp_=os.path.join(troot,'rates','vintages',f'{d_}.json')
                if not os.path.exists(vp_): add('HIGH','rates:vintage',f'rates vintage {d_} recorded but absent'); continue
                if _hl2.sha256(open(vp_,'rb').read()).hexdigest()!=rec_.get('sha256'): add('CRITICAL','rates:vintage_immutable',f'rates vintage {d_} differs from the sha256 recorded when it was written: a vintage was rewritten')
            if ls.isoformat() not in vidx_ and not any(k_>=ls.isoformat() for k_ in vidx_):
                add('HIGH','rates:vintage',f'no rates vintage for the session {ls} (latest {max(vidx_) if vidx_ else "none"})')
        rroot_=os.path.abspath(os.path.join(troot,'..'))
        bz_=[]
        for fn_ in ('app.js','pages.js','screen.js','common.js','index.html','book.html','screen.html','tournament.html','guide.html','data/ticker_signals.json','data/brief_facts.json'):
            fp_=os.path.join(rroot_,fn_)
            if os.path.exists(fp_):
                low_=open(fp_,encoding='utf-8').read().lower()
                # the one sanctioned mention is the relabel itself (a .replace() of the old phrase)
                low_=low_.replace('/rulebook entry zone/g','')
                for ph_ in ('entry zone','buy zone','buy-zone','buy the dip','buying zone','at the zone','in the zone'):
                    if ph_ in low_: bz_.append(f'{fn_}: "{ph_}"')
        if bz_: add('HIGH','entry:buy_zone_language',f'buy-zone language served for the mean-reversion reference (order 2-Oct §2): {bz_[:6]}')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:rates',f'the rates checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- the daily brief, the goals, the news feed, realized gains, ownership (order 30-Sept) ----------
    try:
        # (_lang, the language/directive scan, is defined at the top of main — it is used by the tournament block too)
        # the brief: append-only log with hashes; one entry for the last session; text under the validator's rules
        lgp=os.path.join(troot,'daily_log.jsonl'); rlp=os.path.join(troot,'brief_rules.json'); bfp=os.path.join(troot,'brief_facts.json')
        if os.path.exists(lgp):
            import hashlib as _hl
            entries=[]
            try:
                for ln in open(lgp,encoding='utf-8'):
                    ln=ln.strip()
                    if ln: entries.append(json.loads(ln))
            except Exception as e:
                add('CRITICAL','brief:parse',f'daily_log.jsonl unreadable ({e})'); entries=[]
            ids={e.get('entry_id') for e in entries}
            rules=json.load(open(rlp)) if os.path.exists(rlp) else {}
            fw=[w for w in (rules.get('narrative') or {}).get('forecast_words',[])]
            rules_sha=_hl.sha256(json.dumps(rules,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest() if rules else None
            for e in entries:
                body={k:v for k,v in e.items() if k!='entry_sha256'}
                h=_hl.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
                if h!=e.get('entry_sha256'): add('CRITICAL','brief:edited',f'daily_log.jsonl entry {e.get("entry_id")} does not match its recorded hash — an entry was edited (the log is append-only)')
                if e.get('supersedes') and e['supersedes'] not in ids: add('HIGH','brief:correction_ref',f'entry {e.get("entry_id")} supersedes an unknown entry {e["supersedes"]}')
                if e.get('color') not in ('RED','YELLOW','GREEN'): add('CRITICAL','brief:color',f'entry {e.get("entry_id")} colour {e.get("color")!r}')
                t=str(e.get('text') or ''); low=' '+re.sub(r'[^a-z0-9 %+.-]',' ',t.lower())+' '
                if len(t.split())>int((rules.get('narrative') or {}).get('max_words',40)): add('CRITICAL','brief:length',f'entry {e.get("entry_id")} has {len(t.split())} words (>40)')
                bad=[w for w in fw if re.search(r'(?<![a-z])'+re.escape(w)+r'(?![a-z])',low)]
                if bad: add('CRITICAL','brief:forecast',f'entry {e.get("entry_id")} contains forecast word(s) {bad}')
                if e.get('text_source') not in ('model','template'): add('HIGH','brief:source',f'entry {e.get("entry_id")} text_source {e.get("text_source")!r}')
            if entries:
                last=entries[-1]
                if str(last.get('session'))<ls.isoformat(): add('HIGH','brief:missing',f'no brief entry for the last session {ls} (last: {last.get("session")})')
                if rules_sha and last.get('rules_sha256') and last['rules_sha256']!=rules_sha:
                    add('HIGH','brief:rules_changed','brief_rules.json differs from the rules the latest entry was evaluated under (re-register the rules; the log records the old hash)')
                if rules and not rules.get('frozen_at'): add('HIGH','brief:rules_unfrozen','brief_rules.json carries no frozen_at')
                if os.path.exists(bfp):
                    bf=json.load(open(bfp))
                    if bf.get('entry_id')!=last.get('entry_id') or bf.get('payload_sha256')!=last.get('payload_sha256'):
                        add('HIGH','brief:facts_mismatch','brief_facts.json does not carry the payload of the latest log entry')
            else:
                add('HIGH','brief:empty','daily_log.jsonl has no entries')
            _lang(lgp,'brief')
        else:
            add('HIGH','brief:missing','data/daily_log.jsonl absent — the daily brief has not run')
        # the goals: computed against the immutable claims register (pinned by its 18-Sept record)
        gp=os.path.join(troot,'goals.json'); crp=os.path.join(troot,'claims_register.json')
        if os.path.exists(crp):
            cr=json.load(open(crp)); cl=[c for c in cr.get('claims',[]) if c.get('claim_id')=='claim-2026-09-18-1']
            if not cl or abs(float(cl[0].get('start_value_usd',0))-229245.80)>1e-6 or abs(float(cl[0].get('target_annualized_return',0))-0.29)>1e-9 or int(cl[0].get('horizon_years',0))!=3 or str(cl[0].get('start_date'))!='2026-09-18':
                add('CRITICAL','claims:record_changed','claims_register.json: the 18-Sept claim (account $229,245.80; 29 percent annualized; three years; start 2026-09-18) is not intact — the record is never edited')
            cids=[c.get('claim_id') for c in cr.get('claims',[])]
            if len(cids)!=len(set(cids)): add('CRITICAL','claims:duplicate_ids','claims_register.json has duplicate claim ids')
            if os.path.exists(gp):
                import hashlib as _hl2
                gj=json.load(open(gp))
                if gj.get('register_sha256')!=_hl2.sha256(json.dumps(cr,sort_keys=True).encode()).hexdigest():
                    add('HIGH','goals:register_stale','goals.json was computed against a different claims register')
                hg=gj.get('house_goal') or {}
                if not (hg.get('fx') or {}).get('rate'): add('HIGH','goals:fx_missing','goals.json carries no USDBRL rate')
                for c in gj.get('claims',[]):
                    if c.get('annualized_caption') is None: add('HIGH','goals:caption','claims progress lacks the annualized-figures caption')
                _lang(gp,'goals')
            else:
                add('HIGH','goals:missing','data/goals.json absent (compute_goals.py did not run)')
        # the news feed: fresh, tiered, bodies never stored, clean vocabulary
        np_=os.path.join(troot,'news.json')
        if os.path.exists(np_):
            nj=json.load(open(np_)); nd=to_date(nj.get('as_of') or '')
            if not nd or (nd<ls and len(trading_days(nd,ls))-1>1): add('HIGH','news:stale',f'news.json as_of {nd} vs last session {ls}')
            items=nj.get('items') or []
            if any(k in it for it in items for k in ('body','content','article','description')): add('CRITICAL','news:body_stored','news.json stores article bodies/descriptions (never stored)')
            if any(it.get('tier') not in (1,2) or not it.get('tier_label') for it in items): add('HIGH','news:tier','news.json items without a tier / tier label')
            if any(it.get('tier')==2 and it.get('tier_label')!='secondary' for it in items): add('HIGH','news:tier','Tier-2 items must be labeled secondary')
            _lang(np_,'news')
        else:
            add('HIGH','news:missing','data/news.json absent (fetch_news.py did not run)')
        rgp=os.path.join(troot,'realized_gains.json')
        if os.path.exists(rgp): _lang(rgp,'gains')
        # ownership (E1/E2): classification stated on every purchase; as-of and disclosure dates on every 13F figure
        ip_=os.path.join(troot,'ownership','insiders.json')
        if os.path.exists(ip_):
            ij=json.load(open(ip_))
            isd=to_date(ij.get('session_date') or '')
            if not isd or (isd<ls and len(trading_days(isd,ls))-1>1): add('HIGH','insiders:stale',f'insiders.json session_date {isd} vs last session {ls}')
            if 'cohen' not in json.dumps(ij.get('method') or {}).lower(): add('HIGH','insiders:method','insiders.json does not cite the Cohen, Malloy and Pomorski rule')
            if 'enters no score' not in str((ij.get('signal_registration') or {}).get('status','')): add('CRITICAL','insiders:gate','insiders.json: the candidate signal is not marked "enters no score" (the E1 gate)')
            for tk,n in (ij.get('names') or {}).items():
                rows=(n.get('opportunistic_purchases_90d') or [])+(n.get('sales_shown') or [])
                if any(r.get('classification')!='opportunistic' or not r.get('classification_basis') for r in rows): add('CRITICAL','insiders:classification',f'{tk}: a card row without the stated opportunistic classification and its basis')
                cl=n.get('cluster') or {}
                if cl and bool(cl.get('flag'))!=(int(cl.get('n_distinct_buyers_30d') or 0)>=3): add('CRITICAL','insiders:cluster',f'{tk}: cluster flag {cl.get("flag")} inconsistent with {cl.get("n_distinct_buyers_30d")} distinct buyers')
                if (n.get('sales_shown') or []) and not (n.get('sales_cluster') or {}).get('flag'): add('CRITICAL','insiders:sales_rule',f'{tk}: sales shown without an opportunistic sales cluster')
                if (n.get('sales_shown') or []) and n.get('sales_shown_label')!='sales are mostly compensation or diversification': add('HIGH','insiders:sales_label',f'{tk}: sales shown without the required label')
            if (ij.get('history_coverage') or {}).get('complete') is False: add('HIGH','insiders:history',f'insider history incomplete: quarters missing {(ij.get("history_coverage") or {}).get("quarters_missing")}')
            _lang(ip_,'insiders')
        else:
            add('INFO','insiders:missing','data/ownership/insiders.json absent (EDGAR access needs the declared contact, SEC_USER_AGENT)')
        hp13=os.path.join(troot,'ownership','holders_13f.json')
        if os.path.exists(hp13):
            hj13=json.load(open(hp13))
            h13d=to_date(hj13.get('as_of') or '')
            if not h13d or (ls-h13d).days>10: add('HIGH','ownership:stale',f'holders_13f.json as_of {h13d} is more than 10 days old (weekly)')
            for tk,n in (hj13.get('names') or {}).items():
                rows=(n.get('top_holders') or [])+(n.get('new_positions_over_1b') or [])+(n.get('full_exits_over_1b') or [])+(n.get('prior_holders_without_current_filing') or [])
                if any(not r.get('as_of_quarter_end') or not r.get('disclosed') for r in rows): add('CRITICAL','ownership:dates',f'{tk}: a 13F figure without as-of quarter-end and disclosure date')
                cap=str(n.get('caption') or '')
                if rows and not (cap.startswith('positions as of ') and cap.endswith('; long positions only; no hedges shown.')): add('HIGH','ownership:caption',f'{tk}: 13F caption not in the required form')
            _lang(hp13,'ownership')
        else:
            add('INFO','ownership:missing','data/ownership/holders_13f.json absent (EDGAR access needs the declared contact, SEC_USER_AGENT)')
        # visibility review dates (screener)
        vp=os.path.join(sroot,'visibility_registry.json')
        if os.path.exists(vp):
            vreg=json.load(open(vp))
            if not vreg.get('frozen_at'): add('CRITICAL','governance:visibility','visibility registry not frozen')
            over=(vreg.get('overrides') or vreg.get('entries') or {})
            items=over.items() if isinstance(over,dict) else [(o.get('ticker'),o) for o in over]
            for tk,o in items:
                rb=to_date(o.get('review_by',''))
                if rb and rb<ls: add('HIGH','governance:review_overdue',f'visibility override {tk} review_by {rb} passed (decay should be active)')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:brief',f'the brief checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- event calendar ----------
    try:
        cal=T('event_calendar.json'); ev=cal if isinstance(cal,list) else cal.get('events',[])
        sept=[e for e in ev if str(e.get('date','')).startswith('2026-09')]
        types=[(e['date'],e.get('type')) for e in sept]
        if not any(t=='NFP' and d=='2026-09-04' for d,t in types): add('HIGH','calendar:anchor','Sept NFP not on 2026-09-04')
        if not any(t=='FOMC' for d,t in types): add('HIGH','calendar:anchor','no FOMC entry in September (meeting 15-16 Sep, decision 16 Sep)')
        if not any(t=='CPI' for d,t in types): add('HIGH','calendar:anchor','no CPI entry in September')
        noprov=[e for e in sept if not e.get('source_url')]
        if noprov: add('MEDIUM','calendar:provenance',f'{len(noprov)} Sept entries lack source_url')
        # Order 30-Sept A2: the agencies' anchors and the cluster detector. Anchors asserted here as
        # well as in the builder, so a regressed file (not only a failed build) is caught.
        have={(str(e.get('date')),e.get('type')) for e in ev}
        for d,t in [('2026-09-30','PCE'),('2026-10-02','NFP'),('2026-10-14','CPI'),('2026-10-15','PPI'),
                    ('2026-10-28','FOMC'),('2026-10-29','PCE'),('2026-11-03','ELECTION')]:
            if (d,t) not in have: add('HIGH','calendar:anchor',f'{t} anchor {d} missing (order 30-Sept A2)')
        noimp=[e for e in ev if str(e.get('date',''))>='2026-09-30' and e.get('impact') not in ('high','medium','low')]
        if noimp: add('HIGH','calendar:impact',f'{len(noimp)} upcoming entries lack an impact level (first: {noimp[0].get("date")} {noimp[0].get("type")})')
        if isinstance(cal,dict) and 'clusters' not in cal: add('HIGH','calendar:clusters','event_calendar.json carries no cluster detection (A2)')
        # Order 1-Oct-2026 R6: Treasury auctions against TreasuryDirect TA_WS (a failed fetch is itself a finding)
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from calendar_checks import check_treasury_source, load_announced
            _ann, _fs = load_announced(os.path.join(troot, 'event_calendar.json'))
            for _sev, _chk, _det in check_treasury_source(cal, _ann, today=str(ls), fetch_status=_fs): add(_sev, _chk, _det)
        except Exception as _e:
            add('HIGH', 'calendar:treasury_source', f'check could not run: {type(_e).__name__}: {_e}')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:events',f'the events checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- screener ----------
    try:
        sc=json.load(open(os.path.join(sroot,'scores.json'))); w=sc.get('watchlist',[])
        if w:
            pens=[r.get('corr_penalty') for r in w]
            if all((p in (0,0.0,None)) for p in pens): add('CRITICAL','screener:corr_dead','all watchlist corr_penalty zero/null')
            alive=sum(1 for r in w if r.get('max_corr') not in (None,0,0.0))
            if alive/len(w)<0.9: add('HIGH','screener:corr_coverage',f'only {alive}/{len(w)} top-40 names corr-alive')
            for r in w:
                fp=r.get('fwd_pe')
                if fp is not None and (fp<3 or fp>150): add('HIGH','screener:range',f'{r.get("ticker")} fwd_pe {fp} outside plausible support')
                fy=r.get('fcf_yield_pct')
                if fy is not None and (fy<-60 or fy>30): add('HIGH','screener:range',f'{r.get("ticker")} fcf_yield {fy} outside support')
            if 'fcf_yield_pct' not in w[0]: add('HIGH','screener:typed_fields','fcf_yield_pct field absent (typed split not landed)')
            def should_bb(r):
                b=r.get('base_level') or r.get('entry_level'); p=r.get('current_price'); rsi=r.get('rsi') or 99
                return bool(b and p and p<0.9*b and rsi<25)
            miss=[r.get('ticker') for r in w if should_bb(r) and not r.get('broken_base')]
            if miss: add('HIGH','screener:broken_base',f'names meeting BB rule but untagged: {miss[:5]}')
            funds=[r.get('fundamental') for r in w if r.get('fundamental') is not None]
            if funds and (max(funds)-min(funds))<3: add('HIGH','screener:dispersion',f'fundamental spread {max(funds)-min(funds):.1f} collapsed')
        st=os.path.join(sroot,'status.json')
        if os.path.exists(st):
            s=json.load(open(st)); sd=to_date(s.get('session_date',''))
            if sd and (ls-sd).days>1: add('HIGH','screener:stale',f'session_date {sd} vs last session {ls}')
            if s.get('failure_reason') and 'exit 1' in str(s['failure_reason']) and len(str(s['failure_reason']))<40: add('MEDIUM','status:opaque','failure_reason does not name the failing assertion')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:screener',f'the screener checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- status plumbing (tournament) ----------
    try:
        sp=os.path.join(troot,'status.json')
        if os.path.exists(sp):
            s=json.load(open(sp))
            if s.get('failure_reason') and 'exit 1' in str(s['failure_reason']): add('MEDIUM','status:opaque','tournament failure_reason does not name the failing assertion')
    except Exception as _e:
        add('CRITICAL','referee:check_failed:status',f'the status checks did not finish: {type(_e).__name__}: {str(_e)[:200]}')
    # ---------- the live site (F3, 7-Oct-2026) ----------
    # The served status.json of the live site: its session and its age in hours are reported every run; more than one
    # trading session behind the last session is HIGH (scripts/site_alerts.py opens the site-stale issue).
    try:
        import urllib.request as _ur, datetime as _dt2
        _req=_ur.Request('https://wernerhl.github.io/portfolio-tournament/data/status.json?t='+str(int(_dt2.datetime.now().timestamp())),headers={'User-Agent':'portfolio-tournament referee'})
        with _ur.urlopen(_req,timeout=20) as _r: _live=json.load(_r)
        _lsess=str(_live.get('session_date') or '')[:10]; _ok=_live.get('last_success')
        _age=round((_dt2.datetime.now(_dt2.timezone.utc)-_dt2.datetime.fromisoformat(str(_ok)).astimezone(_dt2.timezone.utc)).total_seconds()/3600,1) if _ok else None
        _allowed=prev_trading_day(ls) if callable(globals().get('prev_trading_day')) else None
        if _allowed is None:
            from trading_calendar import prev_trading_day as _ptd2; _allowed=_ptd2(ls)
        if _lsess and _lsess<str(_allowed): add('HIGH','site:stale',f'the live site serves session {_lsess} ({_age} h since its last publish); the last session is {ls} and one session behind ({_allowed}) is the most allowed')
        else: add('INFO','site:session',f'live site session {_lsess or "unknown"}, {_age} h since its last publish (last session {ls})')
    except Exception as _e:
        add('MEDIUM','site:unreachable',f'the live status.json could not be read: {type(_e).__name__}: {str(_e)[:120]}')
    # ---------- report ----------
    order={'CRITICAL':0,'HIGH':1,'MEDIUM':2,'INFO':3}
    F.sort(key=lambda x:order[x[0]])
    for sev,chk,det in F: print(f'[{sev:<8}] {chk:<28} {det}')
    crit=sum(1 for f in F if f[0]=='CRITICAL')
    print(f'\n{len(F)} findings; {crit} CRITICAL')
    print(f'REFEREE COMPLETE: {len(F)} findings; {crit} CRITICAL')
    return 1 if crit else 0

if __name__=='__main__':
    # Order 16-Sept 6.4: one repository — the screen view's tree is data/screen; discovery covers it.
    troot=sys.argv[1] if len(sys.argv)>1 else 'data'; sroot=sys.argv[2] if len(sys.argv)>2 else os.path.join(troot,'screen')
    sys.exit(main(troot,sroot))
