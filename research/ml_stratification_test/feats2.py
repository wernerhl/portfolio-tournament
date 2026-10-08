import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np
C=pd.read_pickle('C.pkl'); V=pd.read_pickle('V.pkl'); mem=pd.read_pickle('mem.pkl')
C=C[~C.index.duplicated()].sort_index(); V=V.reindex(C.index)
C=C.loc[:, ~C.columns.duplicated()]; V=V.loc[:, ~V.columns.duplicated()]
spy=C['SPY']; C=C.drop(columns='SPY'); V=V.drop(columns='SPY')
r=C.pct_change(); r=r.where(r.abs()<1.5)       # drop obvious data errors
m=spy.pct_change()
logp=np.log(C)
F={}
F['mom_12_1']=C.shift(21)/C.shift(252)-1
F['mom_6_1']=C.shift(21)/C.shift(126)-1
F['mom_12_7']=C.shift(126)/C.shift(252)-1
F['rev_1m']=C/C.shift(21)-1
F['mom_36_13']=C.shift(252)/C.shift(756)-1
F['vol_63']=r.rolling(63,min_periods=40).std()
cov=r.rolling(252,min_periods=150).cov(m); var=m.rolling(252,min_periods=150).var()
beta=cov.div(var,axis=0); F['beta_252']=beta
res=r-beta.shift(1).mul(m,axis=0)
F['ivol_126']=res.rolling(126,min_periods=80).std()
rs=res.rolling(231,min_periods=150).sum().shift(21); rsd=res.rolling(231,min_periods=150).std().shift(21)
F['resmom_12_1']=rs/(rsd*np.sqrt(231))
F['hi52']=C/C.rolling(252,min_periods=150).max()
F['dd_3y']=C/C.rolling(756,min_periods=250).max()
F['d200']=C/C.rolling(200,min_periods=150).mean()-1
F['skew_126']=r.rolling(126,min_periods=80).skew()
F['pctpos_252']=(r>0).where(r.notna()).rolling(252,min_periods=150).mean()
U=pd.read_pickle('U.pkl').reindex(C.index)[C.columns]; dv=(U*V); F['dvol']=np.log(dv.rolling(63,min_periods=40).mean().replace(0,np.nan))
F['volchg']=V.rolling(21,min_periods=15).mean()/V.rolling(252,min_periods=150).mean()
me=C.groupby([C.index.year,C.index.month]).tail(1).index            # month-end trading days
me=me[me<=pd.Timestamp('2026-09-30')]
# max5 and ejump computed at month ends only
ra=r.values; va=V.values; idx={d:i for i,d in enumerate(C.index)}
max5=pd.DataFrame(index=me,columns=C.columns,dtype=float); ej=max5.copy()
vrel=(V/V.rolling(63,min_periods=40).mean().shift(1)).values
for d in me:
    i=idx[d]
    if i<70: continue
    w=ra[i-20:i+1]; s=np.sort(np.nan_to_num(w,nan=-9),axis=0)[-5:]; s[s==-9]=np.nan; max5.loc[d]=np.nanmean(s,axis=0)
    vw=vrel[i-62:i]; rw=ra[i-62:i+1]                      # volume-spike day in last quarter, its return plus next day
    ok=~np.all(np.isnan(vw),axis=0); j=np.zeros(vw.shape[1],dtype=int); j[ok]=np.nanargmax(vw[:,ok],axis=0)
    cols=np.arange(vw.shape[1]); jr=np.nan_to_num(rw[j,cols])+np.nan_to_num(rw[j+1,cols]); jr[~ok]=np.nan; ej.loc[d]=jr
Fm={k:v.loc[me] for k,v in F.items()}; Fm['max5']=max5; Fm['ejump']=ej
Fm['mom_accel']=Fm['mom_6_1']-Fm['mom_12_7']
Pm=C.loc[me]; rm=Pm.pct_change()
Fm['season']=sum(rm.shift(12*k-1) for k in range(1,6))/5
# membership matrix
memb=pd.DataFrame(False,index=me,columns=C.columns)
md=mem.date.values
for d in me:
    row=mem.iloc[np.searchsorted(md,np.datetime64(d),side='right')-1]
    tk=[t.strip().replace('.','-') for t in row.tickers.split(',')]
    memb.loc[d,[t for t in tk if t in memb.columns]]=True
memb=memb & Pm.notna() & (Fm['dvol']>=np.log(3e6)) & (np.array(me>=pd.Timestamp('2005-01-01'))[:,None])
# sector momentum (current GICS sector where known)
info=pd.read_csv('info.csv',index_col=0); secs=info.sector.reindex(C.columns)
unk=list(secs.index[secs.isna()]); print('no sector:',unk)
memb=memb & np.array(secs.notna())[None,:]
m6=Fm['mom_6_1'].where(memb); secmom=pd.DataFrame(index=me,columns=C.columns,dtype=float)
for s in secs.dropna().unique():
    cs=secs.index[secs==s]; secmom[cs]=np.repeat(m6[cs].mean(axis=1).values[:,None],len(cs),axis=1)
Fm['sec_mom']=secmom
R=pd.read_pickle('fund_records.pkl').sort_values(['avail','end'])
Um=pd.read_pickle('U.pkl').reindex(C.index)[C.columns].loc[me]
grid=memb.stack(); grid=grid[grid].index.to_frame(index=False); grid.columns=['date','tic']; grid=grid.sort_values('date')
grid['date']=grid.date.astype('datetime64[ns]'); R['avail']=R.avail.astype('datetime64[ns]')
M=pd.merge_asof(grid,R,left_on='date',right_on='avail',by='tic',direction='backward',tolerance=pd.Timedelta(days=200))
M['px']=[Um.at[d,t] for d,t in zip(M.date,M.tic)]
M['mcap']=M.px*M.shares_adj
pos=lambda x: x.where(x>0)
M['f_ey']=M.ni/pos(M.mcap); M['f_fcfy']=(M.cfo-M.capex.fillna(0))/pos(M.mcap); M['f_sy']=M.rev/pos(M.mcap); M['f_bm']=M.equity/pos(M.mcap)
M['f_gpa']=M.gp/pos(M.assets); M['f_roe']=M.ni/pos(M.equity); M['f_opm']=M.oi/pos(M.rev); M['f_cfoa']=M.cfo/pos(M.assets)
M['f_rev_g']=M.rev/pos(M.rev_l4)-1; M['f_rev_gq']=(M.rev-M.rev_l1)/(pos(M.rev_l4)/4); M['f_rev_acc']=M.f_rev_g-(M.rev_l1/pos(M.rev_l5)-1)
M['f_oi_g']=(M.oi-M.oi_l4)/pos(M.assets); M['f_ni_g']=(M.ni-M.ni_l4)/pos(M.assets); M['f_sue']=M.sue
M['f_ag']=M.assets/pos(M.assets_l4)-1; M['f_capex_a']=M.capex/pos(M.assets); M['f_capex_g']=M.capex/pos(M.capex_l4)-1
M['f_acc']=(M.ni-M.cfo)/pos(M.assets); M['f_sh_g']=M.shares_adj/pos(M.sh_l4)-1; M['f_rd_s']=M.rd/pos(M.rev); M['f_lev']=1-M.equity/pos(M.assets); M['f_size']=np.log(pos(M.mcap))
M['f_age']=(M.date-M.avail).dt.days
fcols=[c for c in M.columns if c.startswith('f_') and c!='f_age']
M=M.set_index(['date','tic']); M['has_fund']=M.avail.notna()&M.mcap.notna()&M.assets.notna()
print('fundamental coverage of members by year:'); print(M.has_fund.groupby(M.index.get_level_values(0).year).mean().round(2).to_dict())
for c in fcols: Fm[c]=M[c].unstack().reindex(index=me,columns=C.columns)
hasf=M.has_fund.unstack().reindex(index=me,columns=C.columns).fillna(False)
fwd={h:Pm.shift(-h)/Pm-1 for h in (1,3,12)}
spym=spy.loc[me]; fspy={h:spym.shift(-h)/spym-1 for h in (1,3,12)}
rows=[]
for k,v in Fm.items(): rows.append(v.where(memb).stack().rename(k))
P=pd.concat(rows,axis=1)
for h in (1,3,12): P[f'fwd{h}']=fwd[h].stack()
P['has_fund']=hasf.stack()
P['member']=memb.stack(); P=P[P.member].drop(columns='member'); P.index.names=['date','tic']
feats=list(Fm.keys())
# cross-sectional rank transform to [-0.5,0.5]
X=P.groupby(level=0)[feats].rank(pct=True)-0.5
X.columns=feats
out=pd.concat([X,P[[f'fwd{h}' for h in (1,3,12)]+['has_fund']]],axis=1)
out.to_pickle('panel2.pkl'); pd.DataFrame(fspy).to_pickle('fspy.pkl'); P[feats].to_pickle('raw2.pkl')
print('panel',out.shape,'months',out.index.get_level_values(0).nunique(), 'features',len(feats))
print(out.groupby(level=0).size().iloc[[0,24,60,120,180,240,-1]])
print('fwd1 extremes',P.fwd1.min(),P.fwd1.max(), (P.fwd1>1).sum())
print(P[P.fwd1>1][['fwd1']].head(10))
