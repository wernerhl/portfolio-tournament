# Audit rerun of 7 October 2026: the harness with each universe filter alone and with the 21 and 43 variables.
import sys, warnings; warnings.filterwarnings('ignore')
sys.path.insert(0,'scripts/analyst')   # run from the repository root
import numpy as np, pandas as pd
import walkforward_test as wf, reconcile as rc
stamp=wf.latest_stamp()
base=[v+'_rk' for v in wf.BASE_VARS]
def feats(T,vs): return [v+'_rk' for v in vs if v+'_rk' in T.columns]
res=[]
def go(label,T,f,cost=0.0,rank=True,lam=100.0):
    r=rc.step(label,T,f,cost,rank,lam); res.append(r)
# workspace treatment, no universe filter
T,_=wf.build_table(stamp,hold_delisted=False,clip=3.0,ext=True)
go('a 5 vars, no filter',T,base)
go('b 21 price vars, no filter',T,feats(T,wf.EXT_PRICE_VARS))
Tf=T[T['has_fund'].fillna(False)].copy()
go('c 43 vars, names with fundamentals, no filter',Tf,feats(Tf,wf.EXT_PRICE_VARS+wf.EXT_FUND_VARS))
go('c2 5 vars, names with fundamentals, no filter',Tf,base)
# split step 4
Tl,_=wf.build_table(stamp,hold_delisted=False,clip=3.0,ext=True,liquid_only=True)
go('d 5 vars, liquidity filter only',Tl,base)
go('d2 21 vars, liquidity filter only',Tl,feats(Tl,wf.EXT_PRICE_VARS))
Ts,_=wf.build_table(stamp,hold_delisted=False,clip=3.0,ext=True,sector_known_only=True)
go('e 5 vars, sector filter only',Ts,base)
# repository treatment (delisted held, 10 bps), ranked target, 43 vars, no filter
T0,_=wf.build_table(stamp,ext=True)
go('f repo treatment, 21 vars, ranked target, 10 bps',T0,feats(T0,wf.EXT_PRICE_VARS),cost=wf.COST_BPS)
T0f=T0[T0['has_fund'].fillna(False)].copy()
go('g repo treatment, 43 vars, ranked target, 10 bps',T0f,feats(T0f,wf.EXT_PRICE_VARS+wf.EXT_FUND_VARS),cost=wf.COST_BPS)
go('h repo treatment, 43 vars, raw target lam 1, 10 bps',T0f,feats(T0f,wf.EXT_PRICE_VARS+wf.EXT_FUND_VARS),cost=wf.COST_BPS,rank=False,lam=1.0)
pd.DataFrame(res).to_csv('agent_steps.csv',index=False)   # written in the current folder
