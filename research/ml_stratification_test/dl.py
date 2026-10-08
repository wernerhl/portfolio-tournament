import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, yfinance as yf, logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
m=pd.read_csv('../dl/sp500/S&P 500 Historical Components & Changes (Updated).csv',parse_dates=['date'])
m=m[m.date>='2004-06-01']
ever=sorted({t.strip() for s in m.tickers for t in s.split(',')})
print('ever members since mid-2004:',len(ever))
ymap={t:t.replace('.','-') for t in ever}
syms=sorted(set(ymap.values()))+['SPY']
C=[];V=[]
for i in range(0,len(syms),120):
    ch=syms[i:i+120]
    d=yf.download(ch,start='2003-06-01',end='2026-10-07',auto_adjust=True,progress=False,threads=True)
    C.append(d['Close']); V.append(d['Volume']); print(i, d['Close'].dropna(axis=1,how='all').shape[1],'/',len(ch),flush=True)
C=pd.concat(C,axis=1); V=pd.concat(V,axis=1)
C=C.dropna(axis=1,how='all'); V=V[C.columns]
C.to_pickle('C.pkl'); V.to_pickle('V.pkl'); m.to_pickle('mem.pkl')
print('have prices for',C.shape[1]-1,'of',len(syms)-1, 'rows',C.shape[0], C.index[-1].date())
