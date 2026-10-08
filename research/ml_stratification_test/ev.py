import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, yfinance as yf
EV=[('MP','2025-07-10','Pentagon preferred + price floor'),('INTC','2025-08-22','Commerce 9.9%'),('LAC','2025-09-24','Energy 5% warrants'),('TMQ','2025-10-07','10% stake'),
    ('CCJ','2025-10-28','Westinghouse partnership'),('AREC','2025-11-03','ReElement warrants'),('010130.KS','2025-12-15','Korea Zinc JV'),('LHX','2026-01-13','$1B convertible in missile unit'),
    ('USAR','2026-01-26','Commerce shares + warrant'),('GFS','2026-05-21','CHIPS equity'),('IBM','2026-05-21','Anderon stake'),('QBTS','2026-05-21','quantum $100M'),('RGTI','2026-05-21','quantum $100M'),
    ('INFQ','2026-05-21','quantum $100M'),('ALMU','2026-07-29','CHIPS R&D equity'),('AA','2026-08-31','gallium project equity'),('ELMT','2026-09-14','Pentagon 19.9%')]
T=sorted({e[0] for e in EV})+['SPY','QQQ']
d=yf.download(T,start='2025-01-01',end='2026-10-08',auto_adjust=True,progress=False)['Close']
spy=d['SPY'].dropna(); idx=spy.index
rows=[]
for t,dt,what in EV:
    p=d[t].reindex(idx).ffill()
    i=idx.searchsorted(pd.Timestamp(dt))
    if i>=len(idx) or pd.isna(p.iloc[max(i-1,0)]): rows.append(dict(t=t,date=dt,what=what)); continue
    def r(a,b,s=p): 
        return s.iloc[b]/s.iloc[a]-1 if 0<=a<len(idx) and 0<=b<len(idx) and pd.notna(s.iloc[a]) else np.nan
    row=dict(t=t,date=dt,what=what,pre20=r(i-21,i-1)-r(i-21,i-1,spy),jump=r(i-1,min(i+1,len(idx)-1))-r(i-1,min(i+1,len(idx)-1),spy))
    for n in (20,60,120):
        row[f'post{n}']=(r(i+1,i+1+n)-r(i+1,i+1+n,spy)) if i+1+n<len(idx) else np.nan
    row['to_now']=r(i+1,len(idx)-1)-r(i+1,len(idx)-1,spy); row['days']=len(idx)-1-(i+1)
    rows.append(row)
E=pd.DataFrame(rows).set_index('t'); pd.set_option('display.width',220)
pc=['pre20','jump','post20','post60','post120','to_now']; S=E.copy(); S[pc]=(S[pc]*100).round(0); print(S.to_string())
print('\nmean / median / share positive / n')
for c in pc:
    x=E[c].dropna(); print(c, f"{x.mean():+.1%} {x.median():+.1%} {np.mean(x>0):.0%} n={len(x)}")
# split: deals with side terms (price floor, offtake, contracts) vs cash-only
side=['MP','INTC','LAC','TMQ','CCJ','USAR','010130.KS','LHX','AA','ELMT','AREC']; cash=['GFS','IBM','QBTS','RGTI','INFQ','ALMU']
for lab,g in (('minerals/defense/Intel',side),('CHIPS R&D cash 2026',cash)):
    x=E.loc[[t for t in g if t in E.index]]; print(lab, {c:(round(x[c].mean()*100,1), round(x[c].median()*100,1), int(x[c].notna().sum())) for c in ['jump','post20','post60','to_now']})
E.to_csv('events.csv')
# --- hyperscaler capex -> supplier basket
R=pd.read_pickle('fund_records.pkl'); H=R[R.tic.isin(['MSFT','GOOGL','AMZN','META'])].dropna(subset=['capex','capex_l4'])
H['q']=H.end.dt.to_period('Q'); cnt=H.groupby('q').tic.nunique(); full=cnt[cnt==4].index
A=H[H.q.isin(full)].groupby('q').agg(capex=('capex','sum'),lag=('capex_l4','sum'),avail=('avail','max'))
A['g']=A.capex/A.lag-1; A['acc']=A.g.diff(); print('\nhyperscaler capex TTM growth by quarter (last 10):'); print((A.tail(10)[['capex','g','acc']].assign(capex=lambda x:(x.capex/1e9).round(0),g=lambda x:(x.g*100).round(0),acc=lambda x:(x.acc*100).round(0))).to_string())
sup=['NVDA','AVGO','MU','AMD','ANET','AMAT','LRCX','KLAC','MRVL','TSM','VRT','ETN','DELL','SMCI','CEG','VST','EQIX','DLR','PWR','GEV']
px=yf.download(sup+['QQQ','SPY','SMH'],start='2012-01-01',end='2026-10-08',auto_adjust=True,progress=False)['Close']
out=[]
for q,r in A.dropna(subset=['acc']).iterrows():
    i=px.index.searchsorted(r.avail)+1
    if i+63>=len(px.index): 
        j=len(px.index)-1
        if j-i<20: continue
    else: j=i+63
    s=(px[sup].iloc[j]/px[sup].iloc[i]-1).dropna()
    out.append(dict(q=str(q),avail=r.avail.date(),g=r.g,acc=r.acc,n=len(s),basket=s.mean(),qqq=px.QQQ.iloc[j]/px.QQQ.iloc[i]-1,smh=px.SMH.iloc[j]/px.SMH.iloc[i]-1))
O=pd.DataFrame(out); O['ex']=O.basket-O.qqq; O['smh_ex']=O.smh-O.qqq
print('\nquarters',len(O), 'from',O.q.iloc[0],'to',O.q.iloc[-1])
for sig in ('g','acc'):
    c=np.corrcoef(O[sig],O.ex)[0,1]; n=len(O); t=c*np.sqrt((n-2)/(1-c*c)); hi=O[O[sig]>O[sig].median()]; lo=O[O[sig]<=O[sig].median()]
    print(f"signal {sig}: corr with next-63d supplier excess over QQQ {c:+.2f} (t {t:+.1f}); above-median quarters {hi.ex.mean():+.1%} (n={len(hi)}, {np.mean(hi.ex>0):.0%} positive), below-median {lo.ex.mean():+.1%} (n={len(lo)}, {np.mean(lo.ex>0):.0%} positive)")
    c2=np.corrcoef(O[sig],O.smh_ex)[0,1]; print(f"   same with SMH minus QQQ: corr {c2:+.2f}; above {hi.smh_ex.mean():+.1%}, below {lo.smh_ex.mean():+.1%}")
pos=O[O.acc>0]; neg=O[O.acc<=0]; print(f"acceleration>0: {pos.ex.mean():+.1%} n={len(pos)} ; <=0: {neg.ex.mean():+.1%} n={len(neg)}; diff t={ (pos.ex.mean()-neg.ex.mean())/np.sqrt(pos.ex.var()/len(pos)+neg.ex.var()/len(neg)):.1f}")
O.to_csv('capex_signal.csv',index=False)
print(O.tail(8).round(3).to_string())
