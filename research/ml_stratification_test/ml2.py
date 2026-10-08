import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, lightgbm as lgb, sys
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor
PA=pd.read_pickle('panel2.pkl'); fspy=pd.read_pickle('fspy.pkl')
ALL=[c for c in PA.columns if not c.startswith('fwd') and c!='has_fund']
PRICE=[c for c in ALL if not c.startswith('f_')]; FUND=[c for c in ALL if c.startswith('f_')]
SETS={'price':PRICE,'fund':FUND,'all':ALL}
Y0=2014
def nw_t(x,lag):
    x=np.asarray(x,float); x=x[~np.isnan(x)]; n=len(x); mu=x.mean(); e=x-mu; s=(e@e)/n
    for l in range(1,lag+1): s+=2*(1-l/(lag+1))*(e[l:]@e[:-l])/n
    return mu/np.sqrt(s/n)
def fit_predict(P,feats,h,model,seeds=(1,2)):
    dates=P.index.get_level_values(0).unique().sort_values()
    tgt=f'fwd{h}'; D=P.dropna(subset=[tgt]).copy()
    D['y']=D.groupby(level=0)[tgt].rank(pct=True)-0.5
    D['q']=(D.groupby(level=0)[tgt].rank(pct=True)*5).clip(upper=4.999).astype(int)
    out=[]; imp=[]
    for Y in range(Y0,2027):
        cut=dates[dates<pd.Timestamp(f'{Y}-01-01')]; last_train=cut[-1-h]
        tr=D[D.index.get_level_values(0)<=last_train]; te=P[P.index.get_level_values(0).year==Y]
        if len(te)==0: continue
        Xtr=tr[feats]; Xte=te[feats]
        if model=='ridge': m=Ridge(alpha=100).fit(Xtr.fillna(0),tr.y); s=m.predict(Xte.fillna(0)); imp.append(pd.Series(m.coef_,feats))
        elif model=='tree': m=DecisionTreeRegressor(max_depth=3,min_samples_leaf=max(500,len(tr)//40),random_state=0).fit(Xtr.fillna(0),tr.y); s=m.predict(Xte.fillna(0))
        else:
            s=np.zeros(len(te)); kw=dict(n_estimators=300,learning_rate=0.03,num_leaves=15,min_child_samples=200,subsample=0.7,subsample_freq=1,colsample_bytree=0.7,reg_lambda=10,verbose=-1,n_jobs=2)
            for sd in seeds:
                if model=='gbm': m=lgb.LGBMRegressor(random_state=sd,**kw).fit(Xtr,tr.y)
                else: m=lgb.LGBMRanker(random_state=sd,objective='lambdarank',label_gain=[0,1,3,7,15],lambdarank_truncation_level=100,**kw).fit(Xtr,tr.q,group=tr.groupby(level=0).size().values)
                s+=pd.Series(m.predict(Xte)).rank(pct=True).values/len(seeds)
                g=m.booster_.feature_importance('gain'); imp.append(pd.Series(g/g.sum(),feats))
        out.append(pd.Series(s,index=te.index))
    return pd.concat(out),(pd.concat(imp,axis=1).mean(axis=1) if imp else None)
def evaluate(P,score,h,label,fs):
    tgt=f'fwd{h}'; D=P[[tgt]].join(score.rename('s'),how='inner').dropna()
    rows=[]; prev=None; to=[]
    for d,g in D.groupby(level=0):
        if len(g)<100: continue
        r=g[tgt].clip(upper=3); rk=g.s.rank(method='first',pct=True)
        qs=[r[(rk>i/5)&(rk<=(i+1)/5)].mean() for i in range(5)]
        top20=r[g.s.rank(method='first',ascending=False)<=20].mean(); dec=r[rk>0.9].mean()
        names=set(g.index.get_level_values(1)[rk>0.8])
        if prev is not None: to.append(1-len(names&prev)/len(names))
        prev=names
        rows.append(dict(date=d,q1=qs[0],q2=qs[1],q3=qs[2],q4=qs[3],q5=qs[4],dec=dec,top20=top20,univ=r.mean(),ic=g.s.corr(g[tgt],method='spearman'),hit=(r[rk>0.8]>r.median()).mean(),spy=fspy.loc[d,h]))
    R=pd.DataFrame(rows).set_index('date'); ann=12/h; lag=h-1
    def line(sub,name):
        ex5=sub.q5-sub.univ; exd=sub.dec-sub.univ; ex20=sub.top20-sub.univ; ex1=sub.q1-sub.univ
        return dict(set=fs,model=label,h=h,period=name,n=len(sub),q1=sub.q1.mean()*ann,q2=sub.q2.mean()*ann,q3=sub.q3.mean()*ann,q4=sub.q4.mean()*ann,q5=sub.q5.mean()*ann,univ=sub.univ.mean()*ann,spy=sub.spy.mean()*ann,
            top5th_ex=ex5.mean()*ann,t5=nw_t(ex5,lag),top10th_ex=exd.mean()*ann,t10=nw_t(exd,lag),top20_ex=ex20.mean()*ann,t20=nw_t(ex20,lag),bot5th_ex=ex1.mean()*ann,tb=nw_t(ex1,lag),
            ic=sub.ic.mean(),t_ic=nw_t(sub.ic,lag),months_beat=(ex5>0).mean(),name_hit=sub.hit.mean(),turnover=np.mean(to))
    return R,[line(R,f'{Y0}-26'),line(R.loc[:'2019-12-31'],f'{Y0}-19'),line(R.loc['2020-01-01':],'2020-26')]
if __name__=='__main__':
    which=sys.argv[1].split(','); allres=[]; series={}; imps={}
    for fs in which:
        feats=SETS[fs]; P=PA if fs=='price' else PA[PA.has_fund & (PA.index.get_level_values(0)>='2010-06-01')]
        for h in (1,12):
            sc={}
            if fs=='price': sc['mom']=P['mom_12_1'].dropna()[lambda s:s.index.get_level_values(0)>=f'{Y0}-01-01']
            for mdl in ('ridge','tree','gbm','rank'):
                s,imp=fit_predict(P,feats,h,mdl); sc[mdl]=s; imps[(fs,mdl,h)]=imp; print('fit',fs,mdl,h,flush=True)
            sc['ens']=pd.concat([sc[k].groupby(level=0).rank(pct=True) for k in ('gbm','rank')],axis=1).mean(axis=1)
            for k,s in sc.items():
                R,res=evaluate(P,s,h,k,fs); allres+=res; series[(fs,k,h)]=R; s.to_pickle(f'sc_{fs}_{k}_{h}.pkl')
    T=pd.DataFrame(allres); T.to_csv(f'res_{"_".join(which)}.csv',index=False); pd.to_pickle(series,f'ser_{"_".join(which)}.pkl'); pd.to_pickle(imps,f'imp_{"_".join(which)}.pkl')
    pd.set_option('display.width',280); pd.set_option('display.max_columns',40)
    pc=['q1','q2','q3','q4','q5','univ','spy','top5th_ex','top10th_ex','top20_ex','bot5th_ex','months_beat','name_hit','turnover']
    S=T.copy(); S[pc]=(S[pc]*100).round(1); S[['t5','t10','t20','tb','t_ic']]=S[['t5','t10','t20','tb','t_ic']].round(1); S['ic']=S.ic.round(3)
    print(S.to_string(index=False))
