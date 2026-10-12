"""Two-year, fixed-budget prospective decision comparison on public aggregate data."""
import json, math
from pathlib import Path
import numpy as np
import pandas as pd

OUT=Path("audit_output")
A={y:pd.read_csv(OUT/f"annual_rank_audit_{y}.csv",dtype={'cnpj':str,'area':str}) for y in (2024,2025)}
T={y:pd.read_csv(OUT/f"retained_{y}.csv",dtype={'cnpj':str,'area':str}) for y in (2024,2025)}
for y in (2024,2025):
    assert not A[y].duplicated(['cnpj','area']).any()
    assert not T[y].duplicated(['cnpj','area']).any()
    A[y]=A[y].merge(T[y],on=['cnpj','area'],validate='one_to_one')
    A[y]['old_rate24']=A[y]['annual_24_ch']/A[y]['median_customers']
    A[y]['old_rate_all']=A[y]['annual_all_ch']/A[y]['median_customers']
    A[y]['old_rate_notexcluded']=A[y]['annual_nonexcluded_ch']/A[y]['median_customers']
    A[y]['old_rate_no3']=A[y]['no3_ch']/A[y]['median_customers']
    A[y]['old_rate_no36']=A[y]['no36_ch']/A[y]['median_customers']
    print("YEAR_PANEL",y,len(A[y]),A[y].cnpj.nunique(),flush=True)
D=A[2024].merge(A[2025],on=['cnpj','area'],suffixes=('_24','_25'),validate='one_to_one')
sizes=D.groupby('cnpj').size()
D=D[D.cnpj.isin(sizes[sizes>=8].index)].copy()
D['future_rate24']=D['annual_24_ch_25']/D['median_customers_25']
D['future_rate24_no3']=D['no3_24h_ch_25']/D['median_customers_25']
D['future_rate24_no36']=D['no36_24h_ch_25']/D['median_customers_25']
print('PAIRED_PANEL',len(D),D.cnpj.nunique(), 'min_utility_n',D.groupby('cnpj').size().min(),flush=True)
PREDICTORS={
 'official_dec':'official_dec_24',
 'official_fec':'official_fec_24',
 'total_rate':'old_rate_all_24',
 'long24_rate':'old_rate24_24',
 'long24_total':'annual_24_ch_24',
 'total_absolute':'annual_all_ch_24',
 'nonexcluded_rate':'old_rate_notexcluded_24',
 'population':'median_customers_24',
}
targets={
 'tail24_total':'annual_24_ch_25',
 'tail24_no3':'no3_24h_ch_25',
 'tail24_no36':'no36_24h_ch_25',
 'tail24_rate':'future_rate24',
}
# No trained model or weights: fixed ordinal rank and top-k decisions only.
BUDGETS=(.05,.10,.20)
rows=[]
for name,g0 in D.groupby('cnpj'):
 g=g0.sort_values('area',kind='stable')
 n=len(g)
 for budget in BUDGETS:
  k=max(1,math.ceil(budget*n))
  for target,targetcol in targets.items():
   outcome=g[targetcol].fillna(0).clip(lower=0).to_numpy(dtype=float)
   total=float(outcome.sum())
   if total<=0:continue
   score_oracle=np.sort(outcome)[-k:].sum()/total
   expected_random=k/n
   choices={}
   for algorithm,predcol in PREDICTORS.items():
    score=g[predcol].to_numpy(dtype=float)
    score=np.nan_to_num(score,nan=-1e300,neginf=-1e300,posinf=1e300)
    # stable sort on deterministic area-ID order, descending score.
    idx=np.argsort(-score,kind='stable')[:k]
    capture=float(outcome[idx].sum()/total)
    choices[algorithm]=capture
    rows.append({'utility':name,'n':n,'budget':budget,'k':k,'target':target,
                 'strategy':algorithm,'capture':capture,'oracle':score_oracle,
                 'random_expected':expected_random,'target_total':total})
   rows.append({'utility':name,'n':n,'budget':budget,'k':k,'target':target,
                'strategy':'random_expected','capture':expected_random,
                'oracle':score_oracle,'random_expected':expected_random,'target_total':total})
   rows.append({'utility':name,'n':n,'budget':budget,'k':k,'target':target,
                'strategy':'oracle_2025','capture':score_oracle,
                'oracle':score_oracle,'random_expected':expected_random,'target_total':total})
R=pd.DataFrame(rows)
assert len(R)>0
print('DECISION_GROUPS',R[['utility','budget','target']].drop_duplicates().groupby(['target','budget']).size().to_json(),flush=True)
rng=np.random.default_rng(20261012)
summ=[]
for (target,budget,strategy),s in R.groupby(['target','budget','strategy']):
 out={'target':target,'budget':budget,'strategy':strategy,'utilities':len(s),
      'mean_capture':float(s.capture.mean()),'median_capture':float(s.capture.median()),
      'pooled_capture':float(np.sum(s.capture*s.target_total)/np.sum(s.target_total)),
      'mean_oracle':float(s.oracle.mean()),'mean_random':float(s.random_expected.mean())}
 summ.append(out)
for target in targets:
 for budget in BUDGETS:
  w=R[(R.target==target)&(R.budget==budget)].pivot(index='utility',columns='strategy',values='capture')
  if len(w)<3:continue
  ref=w['official_dec'].to_numpy()
  U=len(w)
  res={}
  for strategy in ['total_rate','long24_rate','long24_total','total_absolute','official_fec','nonexcluded_rate','population']:
   diff=w[strategy].to_numpy()-ref
   sims=rng.choice(np.arange(U),(6000,U),replace=True)
   boots=np.mean(diff[sims],axis=1)
   lo,hi=np.quantile(boots,[.025,.975])
   z=(int((diff>1e-12).sum()),int((diff<-1e-12).sum()),int((np.abs(diff)<=1e-12).sum()))
   res[strategy]={'mean_gain_pctpoints':round(100*float(diff.mean()),3),
                  'bootstrap95_pctpoints':[round(100*float(lo),3),round(100*float(hi),3)],
                  'wins_losses_ties':z,
                  'median_gain_pctpoints':round(100*float(np.median(diff)),3)}
  print('PAIRWISE',target,budget,len(w),json.dumps(res),flush=True)
  if target=='tail24_total' and budget==.10:
   (OUT/'fixed_budget_pairwise.json').write_text(json.dumps(res,indent=2))
S=pd.DataFrame(summ).sort_values(['target','budget','mean_capture'],ascending=[True,True,False])
print('DECISION_SUMMARY',S.round(5).to_json(orient='records'),flush=True)
# baseline external diagnostic: no claims about physically prevented outages.
for budget in BUDGETS:
 x=S[(S.budget==budget)&(S.target=='tail24_total')]
 print('PRIMARY_BOARD',budget,json.dumps(x[['strategy','utilities','mean_capture','pooled_capture','mean_oracle','mean_random']].round(4).to_dict(orient='records')),flush=True)
(OUT/'prospective_summary.json').write_text(json.dumps({'n_areas':len(D),'n_utilities':int(D.cnpj.nunique()),
    'frozen_year':2024,'heldout_year':2025,'metrics':summ,
    'definition':'Within-company top ceil(budget*N), evaluated against next-year true tail customer-hours; selection precedes held-out year.'},indent=2))
D[['cnpj','area','official_dec_24','old_rate_all_24','old_rate24_24','annual_24_ch_25','no3_24h_ch_25','no36_24h_ch_25','future_rate24']].to_csv(OUT/'paired_2024_features_2025_outcomes.csv',index=False)
print('PROSPECTIVE_EVALUATION_COMPLETE',flush=True)
