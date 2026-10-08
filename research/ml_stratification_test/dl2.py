import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, yfinance as yf, logging
from concurrent.futures import ThreadPoolExecutor
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
C=pd.read_pickle('C.pkl'); syms=[c for c in C.columns if c!='SPY']
U=[];S=[]
for i in range(0,len(syms),120):
    ch=syms[i:i+120]; d=yf.download(ch,start='2003-06-01',end='2026-10-07',auto_adjust=False,actions=True,progress=False,threads=True)
    U.append(d['Close']); S.append(d['Stock Splits']); print(i,flush=True)
U=pd.concat(U,axis=1).reindex(C.index); S=pd.concat(S,axis=1).reindex(C.index).fillna(0)
U.to_pickle('U.pkl'); S.to_pickle('S.pkl')
def info(t):
    try:
        x=yf.Ticker(t).info; return t,x.get('sector'),x.get('industry'),x.get('longName')
    except Exception: return t,None,None,None
with ThreadPoolExecutor(4) as ex: R=list(ex.map(info,syms))
I=pd.DataFrame(R,columns=['tic','sector','industry','name']).set_index('tic'); I.to_csv('info.csv')
print('sector known',I.sector.notna().sum(),'of',len(I)); print(I.sector.value_counts().to_string())
