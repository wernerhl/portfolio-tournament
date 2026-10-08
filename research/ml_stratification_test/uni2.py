import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np
from ml2 import PA, ALL, nw_t
P=PA[(PA.index.get_level_values(0)>='2014-01-01')]
rows=[]
for f in ALL:
    d=dict(var=f)
    for h in (1,12):
        D=P[[f,f'fwd{h}']].dropna(); g=D.groupby(level=0); ann=12/h
        ic=g.apply(lambda x: x[f].corr(x[f'fwd{h}'],method='spearman'))
        sp=g.apply(lambda x:(x[f'fwd{h}'].clip(upper=3)[x[f]>0.3].mean()-x[f'fwd{h}'].clip(upper=3).mean(), x[f'fwd{h}'].clip(upper=3)[x[f]<-0.3].mean()-x[f'fwd{h}'].clip(upper=3).mean()))
        hi=sp.str[0]; lo=sp.str[1]
        d.update({f'ic{h}':ic.mean(),f't{h}':nw_t(ic,h-1),f'ic{h}_1419':ic.loc[:'2019-12-31'].mean(),f'ic{h}_2026':ic.loc['2020-01-01':].mean(),f'hi{h}':hi.mean()*ann*100,f'thi{h}':nw_t(hi,h-1),f'lo{h}':lo.mean()*ann*100,f'tlo{h}':nw_t(lo,h-1),f'hi{h}_1419':hi.loc[:'2019-12-31'].mean()*ann*100,f'hi{h}_2026':hi.loc['2020-01-01':].mean()*ann*100})
    rows.append(d)
U=pd.DataFrame(rows).set_index('var'); U.to_csv('uni2.csv'); pd.set_option('display.width',280)
print(U.round(2).sort_values('ic12').to_string())
