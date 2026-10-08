# Audit rerun of 7 October 2026: the workspace's test with 5, 21 and 43 variables and two training starts.
import os, sys, warnings; warnings.filterwarnings('ignore')
sys.path.insert(0,'.')   # run inside the workspace folder that holds ml2.py and panel2.pkl (not delivered)
import pandas as pd, numpy as np
import ml2
from ml2 import PA, PRICE, FUND, ALL, fit_predict, evaluate
five=['mom_12_1','rev_1m','vol_63','hi52','dvol']
def run(P,feats,label,mdl='ridge'):
    s,_=fit_predict(P,feats,12,mdl); R,res=evaluate(P,s,12,mdl,label); r=res[0]
    print(f"{label:58s} n={r['n']:3d} top10 {r['top10th_ex']*100:+.2f} t {r['t10']:.2f} | top5th {r['top5th_ex']*100:+.2f} t {r['t5']:.2f} | members/mo {P.groupby(level=0).size().loc['2014':].mean():.0f}",flush=True)
    return R
d=PA.index.get_level_values(0)
Pall=PA[PA.has_fund & (d>='2010-06-01')]
out={}
out['price21_2005']=run(PA,PRICE,'A  21 price vars, training from 2005 (as reported)')
out['five_2005']=run(PA,five,'B  5 price vars, training from 2005')
out['price21_2012']=run(PA[d>='2012-01-01'],PRICE,'C  21 price vars, training from 2012')
out['five_2012']=run(PA[d>='2012-01-01'],five,'D  5 price vars, training from 2012')
out['all43_2010']=run(Pall,ALL,'E  43 vars, training from mid-2010 (as reported)')
dd=Pall.index.get_level_values(0)
out['all43_2012']=run(Pall[dd>='2012-01-01'],ALL,'F  43 vars, training from 2012')
out['fund22_2010']=run(Pall,FUND,'G  22 fundamentals, training from mid-2010')
pd.to_pickle(out,'mine_series.pkl')
