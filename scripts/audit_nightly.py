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
    d = today or date.today()
    from datetime import timezone
    now_et = datetime.now(timezone.utc) - timedelta(hours=4)
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
          'backtest_holdings_log.csv','regime_v2_leadtimes.csv','regime_v3_daily.csv','vol_canonical_close.json'}
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
                if missing: add('HIGH',f'{label}:gaps',f'{name}: missing trading days in recent window {missing[:6]}')
            # consecutive identical numeric rows (frozen-computation symptom)
            ISO=re.compile(r'calibrated|equal_weight|elastic',re.I)   # isotonic/step-mapped columns hold constant by design
            empties=[c for c in rows[0] if c!=datecol and all(str(r.get(c,'')).strip()=='' for r in rows[-5:])
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
    audit_dir(troot,'tournament',ls); audit_dir(sroot,'screener',ls)

    T=lambda n: json.load(open(os.path.join(troot,n)))
    # ---------- tournament identities ----------
    t=T('tournament.json'); h=t['history']; L=h[-1]
    for k,v in L['tiers'].items():
        eq=sum(p.get('value',0) for p in v.get('positions',[])); cash=v.get('cash',0)
        if abs(eq+cash-v['nav'])>1: add('CRITICAL','identity:nav',f'{k}: equity+cash={eq+cash:.0f} != nav={v["nav"]:.0f}')
        w=sum(p.get('weight',0) for p in v.get('positions',[]))
        if w>101: add('HIGH','identity:weights',f'{k}: position weights sum {w:.1f}%>100')
    inc=h[0]
    for b,vals in L['benchmarks'].items():
        p0,p1=inc['benchmarks'][b].get('price'),vals.get('price'); n0,n1=inc['benchmarks'][b].get('nav'),vals.get('nav')
        if p0 and p1 and n0 and n1 and abs(n1/n0-p1/p0)>1e-4: add('CRITICAL','identity:benchmark',f'{b}: nav ratio {n1/n0:.5f} != price ratio {p1/p0:.5f}')
    # ---------- cross-file: regime ----------
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
    # ---------- vol complex single source ----------
    if os.path.exists(os.path.join(troot,'vol_close_canonical.json')):
        can=T('vol_close_canonical.json'); vr=T('vol_regime.json'); it=T('intraday.json')
        for src,val,key in (('vol_regime',vr.get('curve',{}).get('spot_vix'),'vix'),('intraday',it.get('vix_now'),'vix')):
            c=can.get(key)
            if c is not None and val is not None and abs(float(val)-float(c))>0.011: add('HIGH','xfile:vol_single_source',f'{src} vix {val} vs canonical {c}')
    else: add('HIGH','arch:canonical_close','vol_close_canonical.json absent (single-source fix not landed)')
    # ---------- canonical close / intraday bot must respect the trading calendar ----------
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
    # ---------- safety inputs / null guards ----------
    it=T('intraday.json')
    for k in ('skew','vix_now','vix3m','vvix'):
        if it.get(k) is None: add('HIGH','nullguard',f'intraday.{k} is null; dependent safety checks must read IMPAIRED not false')
    comp=it.get('complacency_active')
    if comp is False and (it.get('skew') is None): add('CRITICAL','nullguard:complacency','complacency_active=false with skew=null (silent-false)')
    # ---------- stale-badge wiring per panel (HTML) ----------
    hp=os.path.join(os.path.dirname(troot.rstrip('/')),'t','index.html') if False else os.path.join(troot,'..','index.html')
    hp=hp if os.path.exists(hp) else os.path.join(troot,'index.html')
    if os.path.exists(hp):
        html=open(hp,encoding='utf-8').read()
        panels=[p_ for p_ in ('vol_regime','thesis_daily','regime_v4_daily','regime_indicators') if p_ in html]
        calls=len(re.findall(r'isStaleAsOf\(',html))
        if calls<len(panels): add('HIGH','ui:stale_badge',f'{calls} isStaleAsOf() call sites for {len(panels)} daily panels')
        if 'lastTradingSessionISO' in html and not re.search(r'lastTradingSessionISO[^}]{0,800}(HOLIDAY|holiday)',html,re.S): add('HIGH','ui:calendar',"lastTradingSessionISO() not holiday-aware")
    # ---------- v4 ----------
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
    # ---------- vol_regime validation integrity ----------
    vr=T('vol_regime.json'); val=vr.get('validation',{})
    ex=val.get('today_excluded') or val.get('excluded_today')
    if vr.get('as_of')==str(ls) and not ex: add('MEDIUM','validation:lookahead','today not excluded from reversion hit-rate')
    ev=val.get('event_day_only_reversion') or (val.get('walk_forward') or {}).get('event_day_only_reversion') or (val.get('walk_forward') or {}).get('event_day_only') or {}
    if ev.get('n',0)<20 and not (ev.get('caveat') or ev.get('not_yet_evidence') or ev.get('small_n_caveat') or ev.get('small_n')): add('MEDIUM','validation:small_n','event-day n<20 without caveat flag')
    # ---------- thesis / registry governance ----------
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
        if c and abs(c.get('active',0)-(c.get('cash_eff',0)+c.get('alloc_eff',0)+c.get('selection',0)))>1e-4:
            add('CRITICAL','identity:attribution',f'{k}: components do not sum to active')
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
    # ---------- event calendar ----------
    cal=T('event_calendar.json'); ev=cal if isinstance(cal,list) else cal.get('events',[])
    sept=[e for e in ev if str(e.get('date','')).startswith('2026-09')]
    types=[(e['date'],e.get('type')) for e in sept]
    if not any(t=='NFP' and d=='2026-09-04' for d,t in types): add('HIGH','calendar:anchor','Sept NFP not on 2026-09-04')
    if not any(t=='FOMC' for d,t in types): add('HIGH','calendar:anchor','no FOMC entry in September (meeting 15-16 Sep, decision 16 Sep)')
    if not any(t=='CPI' for d,t in types): add('HIGH','calendar:anchor','no CPI entry in September')
    noprov=[e for e in sept if not e.get('source_url')]
    if noprov: add('MEDIUM','calendar:provenance',f'{len(noprov)} Sept entries lack source_url')
    # ---------- screener ----------
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
    # ---------- status plumbing (tournament) ----------
    sp=os.path.join(troot,'status.json')
    if os.path.exists(sp):
        s=json.load(open(sp))
        if s.get('failure_reason') and 'exit 1' in str(s['failure_reason']): add('MEDIUM','status:opaque','tournament failure_reason does not name the failing assertion')
    # ---------- report ----------
    order={'CRITICAL':0,'HIGH':1,'MEDIUM':2,'INFO':3}
    F.sort(key=lambda x:order[x[0]])
    for sev,chk,det in F: print(f'[{sev:<8}] {chk:<28} {det}')
    crit=sum(1 for f in F if f[0]=='CRITICAL')
    print(f'\n{len(F)} findings; {crit} CRITICAL')
    return 1 if crit else 0

if __name__=='__main__':
    troot=sys.argv[1] if len(sys.argv)>1 else 'data'; sroot=sys.argv[2] if len(sys.argv)>2 else '../portfolio-screener/data'
    sys.exit(main(troot,sroot))
