import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, bisect
F=pd.read_pickle('facts.pkl'); F=F.dropna(subset=['end','filed','val'])
F=F.sort_values('filed').drop_duplicates(['tic','concept','start','end'],keep='first')
F['dur']=(F.end-F.start).dt.days
S=pd.read_pickle('S.pkl'); U=pd.read_pickle('U.pkl')
D1=pd.Timedelta(days=1)
def near(sorted_ends, target, tol=10):
    i=bisect.bisect_left(sorted_ends,target); best=None
    for j in (i-1,i):
        if 0<=j<len(sorted_ends) and abs((sorted_ends[j]-target).days)<=tol:
            if best is None or abs((sorted_ends[j]-target).days)<abs((best-target).days): best=sorted_ends[j]
    return best
def ttm_series(df):
    """df: duration facts of one concept for one company -> {end:(ttm,avail)}"""
    ann=df[(df.dur>=350)&(df.dur<=380)]; A={r.end:(r.val,r.filed) for r in ann.itertuples()}; aend=sorted(A)
    oth=df[(df.dur>=80)&(df.dur<=290)]; res=dict(A)
    byend={}
    for r in oth.itertuples(): byend.setdefault(r.end,[]).append(r)
    oend=sorted(byend)
    for E in oend:
        if E in res: continue
        y=max(byend[E],key=lambda r:r.dur)
        fy=near(aend,y.start-D1)
        if fy is None: continue
        pe=near(oend,E-pd.Timedelta(days=365))
        if pe is None: continue
        cand=[r for r in byend[pe] if abs(r.dur-y.dur)<=12]
        if not cand: continue
        res[E]=(A[fy][0]+y.val-cand[0].val, y.filed)
    return res
def with_lags(res):
    ends=sorted(res); out={}
    for E in ends:
        l1=near(ends,E-pd.Timedelta(days=91)); l4=near(ends,E-pd.Timedelta(days=365)); l5=near(ends,E-pd.Timedelta(days=456))
        out[E]=dict(v=res[E][0],avail=res[E][1],l1=res[l1][0] if l1 else np.nan,l4=res[l4][0] if l4 else np.nan,l5=res[l5][0] if l5 else np.nan)
    return out
def first(*ds):
    """combine dicts by priority per end"""
    out={}
    for d in ds:
        for E,v in d.items():
            if E not in out: out[E]=v
    return out
REV=['Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','RevenueFromContractWithCustomerIncludingAssessedTax','SalesRevenueNet','SalesRevenueGoodsNet']
recs=[]
for tic,g in F.groupby('tic'):
    c={k:v for k,v in g.groupby('concept')}
    def T(name): return with_lags(ttm_series(c[name])) if name in c else {}
    rev=first(*[T(n) for n in REV]); ni=T('NetIncomeLoss'); oi=T('OperatingIncomeLoss'); gp=T('GrossProfit')
    cost=first(T('CostOfRevenue'),T('CostOfGoodsAndServicesSold'),T('CostOfGoodsSold'))
    cfo=first(T('NetCashProvidedByUsedInOperatingActivities'),T('NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'))
    cap=first(T('PaymentsToAcquirePropertyPlantAndEquipment'),T('PaymentsToAcquireProductiveAssets')); rd=T('ResearchAndDevelopmentExpense')
    def inst(name):
        if name not in c: return {}
        d=c[name]; return {r.end:(r.val,r.filed) for r in d.itertuples()}
    assets=inst('Assets'); eq=first(inst('StockholdersEquity'),inst('StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'))
    aend=sorted(assets)
    sh={}
    if 'WeightedAverageNumberOfDilutedSharesOutstanding' in c:
        for r in c['WeightedAverageNumberOfDilutedSharesOutstanding'].sort_values('dur').itertuples():
            if r.dur>=80 and r.end not in sh: sh[r.end]=(r.val,r.filed)
    dei=c.get('EntityCommonStockSharesOutstanding'); deif={}
    if dei is not None:
        for r in dei.itertuples(): deif[r.filed]=r.val
    ends=sorted(set(rev)|set(ni))
    # SUE: quarterly change in TTM net income (= yoy change of the quarter), scaled by its std over the previous 8 quarters
    niE=sorted(ni); dni={E:ni[E]['v']-ni[E]['l1'] for E in niE}
    for E in ends:
        r=rev.get(E,{}); n=ni.get(E,{}); av=[x.get('avail') for x in (r,n) if x.get('avail') is not None]
        if not av: continue
        avail=max(av)
        a=assets.get(E,(np.nan,None))[0]; al=near(aend,E-pd.Timedelta(days=365)); a4=assets[al][0] if al else np.nan
        e=eq.get(E,(np.nan,None))[0]
        s=sh.get(E,(np.nan,None))[0]
        if not np.isfinite(s) or s<=0: s=deif.get(avail,np.nan)
        sue=np.nan
        if E in dni and np.isfinite(dni[E]):
            i=niE.index(E); h=[dni[x] for x in niE[max(0,i-8):i] if np.isfinite(dni[x])]
            if len(h)>=6 and np.std(h)>0: sue=dni[E]/np.std(h)
        g_=gp.get(E,{}).get('v',np.nan)
        if not np.isfinite(g_) and E in cost and E in rev: g_=rev[E]['v']-cost[E]['v']
        recs.append(dict(tic=tic,end=E,avail=avail,rev=r.get('v',np.nan),rev_l1=r.get('l1',np.nan),rev_l4=r.get('l4',np.nan),rev_l5=r.get('l5',np.nan),
            ni=n.get('v',np.nan),ni_l4=n.get('l4',np.nan),oi=oi.get(E,{}).get('v',np.nan),oi_l4=oi.get(E,{}).get('l4',np.nan),gp=g_,
            cfo=cfo.get(E,{}).get('v',np.nan),capex=cap.get(E,{}).get('v',np.nan),capex_l4=cap.get(E,{}).get('l4',np.nan),rd=rd.get(E,{}).get('v',np.nan),
            assets=a,assets_l4=a4,equity=e,shares=s,sue=sue))
R=pd.DataFrame(recs); R=R[R.avail.notna()]
# split factor after the filing date (shares in a filing are on the share basis of the filing date)
fac=[]
for r in R.itertuples():
    if r.tic in S.columns:
        s=S[r.tic]; s=s[(s.index>r.avail)&(s>0)]; fac.append(float(np.prod(s.values)) if len(s) else 1.0)
    else: fac.append(np.nan)
R['shares_adj']=R.shares*np.array(fac)
R=R.sort_values(['tic','end'])
# share growth: shares_adj vs one year earlier
R['sh_l4']=np.nan
for tic,g in R.groupby('tic'):
    ends=list(g.end); m=dict(zip(g.end,g.shares_adj))
    R.loc[g.index,'sh_l4']=[m.get(near(ends,E-pd.Timedelta(days=365)),np.nan) if near(ends,E-pd.Timedelta(days=365)) is not None else np.nan for E in ends]
R.to_pickle('fund_records.pkl')
print('records',R.shape,'companies',R.tic.nunique(), 'avail range',R.avail.min().date(),R.avail.max().date())
print(R.notna().mean().round(2).to_string())
for t in ('AAPL','NVDA','JPM','XOM','MU'):
    x=R[R.tic==t].tail(1).iloc[0]; px=U[t].dropna().iloc[-1]
    print(t,'end',x.end.date(),'filed',x.avail.date(),f"rev_ttm {x.rev/1e9:.1f}B ni_ttm {x.ni/1e9:.1f}B assets {x.assets/1e9:.0f}B shares_adj {x.shares_adj/1e9:.2f}B mcap {px*x.shares_adj/1e12:.2f}T rev_g {x.rev/x.rev_l4-1:+.0%}")
x=R[(R.tic=='NVDA')&(R.avail<'2021-01-01')].tail(1).iloc[0]; print('NVDA end',x.end.date(),'shares raw',x.shares/1e9,'adj',x.shares_adj/1e9)
