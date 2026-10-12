"""Current-phasor counter-test on the same previously voltage-undetected faults.
All tests operate on the public simulation records; no real protection relay claim.
"""
import csv, hashlib, io, json, re, time
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
import requests

OUT=Path('current_results'); OUT.mkdir(exist_ok=True)
DATA='https://zenodo.org/records/22904220/files/DERfaults_measurements.csv?download=1'
META='https://zenodo.org/records/22904220/files/labels_metadata_DERfaults.csv?download=1'
SHA='645fc79d6cd9f35324295317317683be5fd085524521346f84e42837a657c6bd'
prev=pd.read_csv('original_baseline/fault_output/per_fault_scores.csv')
assert len(prev)==19800 and prev.SampleID.is_unique
ident=pd.read_csv(io.BytesIO(requests.get(META,timeout=90).content))
assert len(ident)==19800 and ident.SampleID.is_unique
baseline=prev[['SampleID','score_93']].merge(ident,on='SampleID',validate='one_to_one')
suspect=baseline[(baseline.Fault_Label!=0)&baseline.Fault_Bus.str.startswith('t_bus')&(baseline.score_93<.01)]
assert len(suspect)==5833,('Frozen voltage-missed sample count changed',len(suspect))
fixed=set(suspect.SampleID)
print('FROZEN_POPULATION',json.dumps({'all':len(baseline),'faults':int((baseline.Fault_Label!=0).sum()),'voltage_missed_t_bus':len(fixed)}),flush=True)
p=Path('DERfaults_measurements.csv');h=hashlib.sha256()
with requests.get(DATA,stream=True,timeout=(40,220)) as r:
 r.raise_for_status()
 with p.open('wb') as f:
  size=0
  for j,chunk in enumerate(r.iter_content(2*1024*1024)):
   if chunk:
    f.write(chunk);h.update(chunk);size+=len(chunk)
    if j%70==0:print('SOURCE_TRANSFER_MB',round(size/1e6,1),flush=True)
assert h.hexdigest()==SHA,('Source changed',h.hexdigest())
print('SOURCE_OK',json.dumps({'bytes':size,'sha256':h.hexdigest()}),flush=True)
with p.open(encoding='utf-8-sig') as f: fields=next(csv.reader(f))
fields_set=set(fields)
quartets=[]
for item in fields:
 m=re.match(r'^(Line\..+_T[12]_Ph[123])_Imag_pre$',item)
 if not m:continue
 stem=m.group(1)
 cols=[stem+'_Imag_pre',stem+'_Iang_pre',stem+'_Imag_post',stem+'_Iang_post']
 if all(q in fields_set for q in cols):quartets.append((stem,cols))
assert len(quartets)>200
print('CURRENT_SCHEMA',json.dumps({'all_fields':len(fields),'quartets':len(quartets),'lines':len(set(x.split('_T')[0] for x,_ in quartets))}),flush=True)
needed={'SampleID'}
for _,names in quartets:needed.update(names)
res=[]
for chunk in pd.read_csv(p,usecols=lambda c:c in needed,chunksize=96):
 n=len(chunk); ids=chunk.SampleID.to_numpy(dtype=int)
 change=np.zeros(n); premax=np.zeros(n)
 peak1=np.zeros(n);peak10=np.zeros(n);t1=np.zeros(n);t2=np.zeros(n)
 winning=np.zeros(n,dtype=int);validcount=np.zeros(n,dtype=int)
 for i,(stem,names) in enumerate(quartets):
  p_mag=chunk[names[0]].to_numpy(dtype=np.float64)
  p_ang=np.deg2rad(chunk[names[1]].to_numpy(dtype=np.float64))
  q_mag=chunk[names[2]].to_numpy(dtype=np.float64)
  q_ang=np.deg2rad(chunk[names[3]].to_numpy(dtype=np.float64))
  delta=np.hypot(q_mag*np.cos(q_ang)-p_mag*np.cos(p_ang),
                 q_mag*np.sin(q_ang)-p_mag*np.sin(p_ang))
  good=np.isfinite(delta)&np.isfinite(p_mag)&np.isfinite(q_mag)&(p_mag>=0)&(q_mag>=0)
  validcount+=good
  delta=np.where(good,delta,0);p_mag=np.where(good,p_mag,0)
  winning=np.where(delta>change,i,winning)
  change=np.maximum(change,delta);premax=np.maximum(premax,p_mag)
  peak1=np.maximum(peak1,delta/np.maximum(1,p_mag))
  peak10=np.maximum(peak10,delta/np.maximum(10,p_mag))
  if '_T1_' in stem:t1=np.maximum(t1,delta)
  else:t2=np.maximum(t2,delta)
 res.append(pd.DataFrame({'SampleID':ids,'Iabsolute':change,'Ibaseline_max':premax,
     'Iglobal':change/np.maximum(1,premax),'Ich_floor1':peak1,'Ich_floor10':peak10,
     'Iterminal1':t1,'Iterminal2':t2,'top_line':[quartets[j][0] for j in winning],
     'valid_channels':validcount}))
 if (len(res)*96)%2400<96:print('PARSED_BLOCKS',len(res),flush=True)
x=pd.concat(res,ignore_index=True)
assert len(x)==19800 and x.SampleID.is_unique
d=baseline.merge(x,on='SampleID',validate='one_to_one')
d['voltage_missed']=d.SampleID.isin(fixed)
d['type']=np.where(d.Fault_Bus.str.startswith('t_bus'),'t_bus','other')
normal=d[d.Fault_Label==0];fault=d[d.Fault_Label!=0];missed=d[d.voltage_missed]
assert len(missed)==5833
d['Rbin']=pd.cut(d.Resistance,[-1,0,1,5,15,26],labels=['normal','0-1','1-5','5-15','15-25'])
report={'source_sha256':SHA,'quartets':len(quartets),'counts':{'normal':len(normal),'fault':len(fault),'missed_voltage':len(missed)},
        'thresholds':[],'condition':[],'top_channels':[],'distributions':{}}
for name,g in [('normal',normal),('all_fault',fault),('voltage_missed',missed)]:
 report['distributions'][name]={c:{str(q):float(g[c].quantile(q)) for q in [0,.01,.05,.1,.25,.5,.75,.9,.95,.99,1]}
   for c in ['Iabsolute','Ibaseline_max','Iglobal','Ich_floor1','Ich_floor10']}
print('KEY_DISTRIBUTIONS',json.dumps(report['distributions']['voltage_missed']),flush=True)
for col in ['Iglobal','Ich_floor1','Ich_floor10','Iabsolute']:
 for cutoff in ([.001,.005,.01,.02,.05,.1,.2,.5] if col!='Iabsolute' else [1,5,10,25,50,100]):
  rr={'metric':col,'threshold':cutoff,'rescued':int((missed[col]>=cutoff).sum()),
      'unresolved':int((missed[col]<cutoff).sum()),
      'normal_alarms':int((normal[col]>=cutoff).sum()),
      'all_fault_detected':int((fault[col]>=cutoff).sum())}
  report['thresholds'].append(rr)
  print('RESULT',json.dumps(rr),flush=True)
for key in ['Scenario_ID','Fault_Type','Rbin']:
 for cat,g in missed.groupby(key,observed=True):
  report['condition'].append({'axis':key,'value':str(cat),'n':len(g),'recovered_1pct':int((g.Iglobal>=.01).sum()),
   'recovered_5pct':int((g.Iglobal>=.05).sum()),'recovered_10pct':int((g.Iglobal>=.1).sum()),
   'median_current_global':float(g.Iglobal.median())})
print('CONDITION_BREAKDOWN',json.dumps(report['condition']),flush=True)
for threshold in [.01,.05,.1]:
 sel=missed[missed.Iglobal>=threshold]
 cc=Counter(sel.top_line)
 report['top_channels'].append({'threshold':threshold,'n':len(sel),'distinct_channels':len(cc),'top10':cc.most_common(10)})
print('TOP_CURRENT_CHANNELS',json.dumps(report['top_channels']),flush=True)
d[['SampleID','Fault_Label','Scenario_ID','Fault_Type','Fault_Bus','Resistance','score_93','voltage_missed','Iabsolute','Ibaseline_max','Iglobal','Ich_floor1','Ich_floor10','Iterminal1','Iterminal2','top_line']].to_csv(OUT/'joined_voltage_current_samples.csv',index=False)
(OUT/'summary.json').write_text(json.dumps(report,indent=2))
print('CURRENT_AUDIT_COMPLETE',json.dumps({'n':len(d),'previously_missed':len(missed),'current_quartets':len(quartets)}),flush=True)
