import json, time, requests, pandas as pd, numpy as np, sys
from concurrent.futures import ThreadPoolExecutor
import os
UA={'User-Agent':os.environ['SEC_USER_AGENT']}   # the declared contact the SEC requires, from the environment (redacted on delivery to the public repository)
C=pd.read_pickle('C.pkl'); tick=[c for c in C.columns if c!='SPY']
tk=json.load(open('../dl/tick.json')); cik={v['ticker'].replace('.','-'):v['cik_str'] for v in tk.values()}
have=[t for t in tick if t in cik]; print('tickers',len(tick),'with CIK',len(have),flush=True)
DUR=['Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','RevenueFromContractWithCustomerIncludingAssessedTax','SalesRevenueNet','SalesRevenueGoodsNet','NetIncomeLoss','OperatingIncomeLoss','GrossProfit','CostOfRevenue','CostOfGoodsAndServicesSold','CostOfGoodsSold','NetCashProvidedByUsedInOperatingActivities','NetCashProvidedByUsedInOperatingActivitiesContinuingOperations','PaymentsToAcquirePropertyPlantAndEquipment','PaymentsToAcquireProductiveAssets','ResearchAndDevelopmentExpense','WeightedAverageNumberOfDilutedSharesOutstanding']
INST=['Assets','StockholdersEquity','StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest','CommonStockSharesOutstanding']
def get(t):
    url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik[t]:010d}.json'
    for k in range(4):
        try:
            r=requests.get(url,headers=UA,timeout=60)
            if r.status_code==200: break
            if r.status_code==404: return t,None
            time.sleep(1+2*k)
        except Exception as e: time.sleep(1+2*k)
    else: return t,None
    f=r.json().get('facts',{}); rows=[]
    def grab(ns,c):
        u=f.get(ns,{}).get(c,{}).get('units',{})
        for unit,lst in u.items():
            if unit not in('USD','shares'): continue
            for x in lst:
                if x.get('form','') not in('10-K','10-Q','10-K/A','10-Q/A','20-F','40-F','10-KT','10-QT'): continue
                rows.append((t,c,x.get('start'),x['end'],x['val'],x['filed'],x['form']))
    for c in DUR+INST: grab('us-gaap',c)
    grab('dei','EntityCommonStockSharesOutstanding')
    time.sleep(0.25)
    return t,rows
out=[]; miss=[]
with ThreadPoolExecutor(3) as ex:
    for i,(t,rows) in enumerate(ex.map(get,have)):
        if rows is None: miss.append(t)
        else: out+=rows
        if i%100==0: print(i,len(out),flush=True)
F=pd.DataFrame(out,columns=['tic','concept','start','end','val','filed','form'])
for c in ('start','end','filed'): F[c]=pd.to_datetime(F[c],errors='coerce')
F.to_pickle('facts.pkl'); print('facts',F.shape,'companies',F.tic.nunique(),'missing',len(miss),miss[:40])
