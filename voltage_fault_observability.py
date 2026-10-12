"""Streaming audit: observed PMU location coverage and voltage-change fault screening."""
import csv,hashlib,json,os,re,requests,time
from pathlib import Path
import numpy as np,pandas as pd
ROOT="https://zenodo.org/records/22904220/files/"
O=Path("fault_output");O.mkdir(exist_ok=True)
for name in ["labels_metadata_DERfaults.csv","pmu_placement_configurations.csv"]:
 r=requests.get(ROOT+name+"?download=1",timeout=(20,90));r.raise_for_status();(O/name).write_bytes(r.content)
meta=pd.read_csv(O/"labels_metadata_DERfaults.csv")
config=pd.read_csv(O/"pmu_placement_configurations.csv")
sets={k:set(config[k].dropna().astype(str).str.strip()) for k in config.columns}
assert len(meta)==19800 and len(sets["PMU_93"])==93
pmu_real=sorted(sets["PMU_93"])
print("PMU_OVERLAP",json.dumps({k:{"n":len(v),"observable_n":len(v&sets["PMU_93"]),"not_observable":len(v-sets["PMU_93"])} for k,v in sets.items()}),flush=True)
p=O/"DERfaults_measurements.csv"
if not p.exists():
 s=requests.Session()
 start=time.time();dig=hashlib.sha256()
 with s.get(ROOT+"DERfaults_measurements.csv?download=1",stream=True,timeout=(35,200)) as r:
  r.raise_for_status()
  print("DOWNLOAD_STARTED",r.status_code,r.headers.get("Content-Length"),flush=True)
  with p.open("wb") as f:
   size=0
   for ix,part in enumerate(r.iter_content(4*1024*1024)):
    if part:
     f.write(part);dig.update(part);size+=len(part)
     if ix%45==0:print("TRANSFER_MB",round(size/1e6,1),flush=True)
 print("DOWNLOAD_COMPLETED",p.stat().st_size,dig.hexdigest(),round(time.time()-start,2),flush=True)
with p.open("r",encoding="utf-8-sig") as f:fields=next(csv.reader(f))
# all available pre/post voltage phasor quartet components per measured bus phase.
pat=re.compile(r"^(bus[^.]+)\.([123])_Vmag_pre$")
quartets=[]
for n in fields:
 m=pat.match(n)
 if m:
  stem=n.rsplit("_Vmag_pre",1)[0];keys=[stem+"_Vmag_pre",stem+"_Vang_pre",stem+"_Vmag_post",stem+"_Vang_post"]
  if all(x in fields for x in keys):quartets.append((m.group(1),keys))
buses=sorted(set(b for b,_ in quartets))
missing_from_93=sorted(set(pmu_real)-set(buses))
print("MEASUREMENT_VOLTAGE_SCHEMA",json.dumps({"columns":len(fields),"quartets":len(quartets),"pmu_93":len(pmu_real),"measured_buses":len(buses),"missing_from93":missing_from_93[:30]}),flush=True)
use={"SampleID"}
for b,keys in quartets:use.update(keys)
num_b=len(buses);bus_index={b:i for i,b in enumerate(buses)}
rng=np.random.default_rng(20261012)
subsets={93:[np.arange(num_b,dtype=int)]}
for n in [56,36,20]:
 subsets[n]=[np.sort(rng.choice(num_b,size=n,replace=False)) for _ in range(25)]
# All sensor sets are subsamples of actually measured 93 PMUs; not official nonnested configurations.
record=[]
rows_seen=0
for chunk in pd.read_csv(p,usecols=lambda c:c in use,chunksize=96,low_memory=False,dtype=np.float32 if False else None):
 chunk["SampleID"]=chunk["SampleID"].astype(int)
 arr=np.full((len(chunk),num_b),np.nan,dtype=np.float32)
 cnt=np.zeros((len(chunk),num_b),dtype=np.int16)
 for b,(a1,a2,a3,a4) in quartets:
  pre=chunk[a1].to_numpy(dtype=np.float32)
  anpre=chunk[a2].to_numpy(dtype=np.float32)
  post=chunk[a3].to_numpy(dtype=np.float32)
  anpost=chunk[a4].to_numpy(dtype=np.float32)
  delta=np.deg2rad(anpost-anpre)
  # Compute phasor distance without unstable complex constructs.
  with np.errstate(divide="ignore",invalid="ignore"):
   diff=np.sqrt((post-pre)**2+2*post*pre*(1-np.cos(delta)))/np.abs(pre)
  diff=np.where((np.abs(pre)>1e-6)&np.isfinite(diff),diff,np.nan)
  col=bus_index[b]
  x=arr[:,col]
  arr[:,col]=np.fmax(x,diff)
  cnt[:,col]+=np.isfinite(diff)
 score=np.nanmax(arr,axis=1)
 tmp=pd.DataFrame({"SampleID":chunk.SampleID.values,"score_93":score})
 for n in [56,36,20]:
  samples=np.stack([np.nanmax(arr[:,idx],axis=1) for idx in subsets[n]],axis=1)
  tmp[f"avg_coverage_{n}"]=np.mean(samples,axis=1)
  # Preserve sensitivity distribution across repeated sensor selections.
  for t in [.01,.02,.05,.10,.20]:
   tmp[f"sensitivity_{n}_{str(t).replace('.','_')}"]=(samples>=t).mean(axis=1)
 record.append(tmp)
 rows_seen+=len(tmp)
 if rows_seen%2400<96:print("PARSED_RECORDS",rows_seen,flush=True)
Q=pd.concat(record,ignore_index=True)
assert rows_seen==19800 and Q.SampleID.is_unique,{"read":rows_seen,"unique":Q.SampleID.nunique()}
D=meta.merge(Q,on="SampleID",validate="one_to_one")
D["fault"]=D.Fault_Label!=0
D["Rbin"]=pd.cut(D.Resistance,[-1,0,1,5,15,25.1],labels=["normal","0-1","1-5","5-15","15-25"])
data=[]
for (scenario,rbin),g in D.groupby(["Scenario_ID","Rbin"],observed=True):
 d={"scenario":scenario,"rbin":str(rbin),"n":len(g),"fault":bool(g.fault.iloc[0]),
    "median_max_phasor_shift":float(g.score_93.median()),
    "p10_max_phasor_shift":float(g.score_93.quantile(.1))}
 for t in [.01,.02,.05,.10,.20]:
  key=str(t).replace(".","_")
  d[f"detect93_{key}"]=float((g.score_93>=t).mean())
  for n in [56,36,20]:
   d[f"detect{n}_{key}"]=float(g[f"sensitivity_{n}_{key}"].mean())
 data.append(d)
summ=pd.DataFrame(data)
summ.to_csv(O/"scenario_resistance_sensitivity.csv",index=False)
diag={
"observability":{k:{"n":len(v),"match93":len(v&sets["PMU_93"])} for k,v in sets.items()},
"measured_buses":len(buses),"quartets":len(quartets),
"normal_disturbance":{"max":float(D.loc[~D.fault,"score_93"].max()),"mean":float(D.loc[~D.fault,"score_93"].mean())},
"fault_disturbance":{"min":float(D.loc[D.fault,"score_93"].min()),"p1":float(D.loc[D.fault,"score_93"].quantile(.01)),
                     "p50":float(D.loc[D.fault,"score_93"].median())}
}
print("DATA_QUALITY",json.dumps(diag),flush=True)
for r in data:
 if r["rbin"] in ["normal","15-25"]:print("SCENARIO_RESULT",json.dumps(r),flush=True)
D[["SampleID","Scenario_ID","Fault_Type","Fault_Label","Resistance","Fault_Bus","score_93","avg_coverage_20","avg_coverage_36","avg_coverage_56"]].to_csv(O/"per_fault_scores.csv",index=False)
(O/"report.json").write_text(json.dumps({"method":"pre/post relative complex voltage-phasor shift; 25 random subsets of observed PMUs per sensor budget; zero noise assumptions; thresholds [1,2,5,10,20]%", "seed":20261012,**diag,"results":data},indent=2))
print("BENCHMARK_AUDIT_COMPLETE",len(D),flush=True)
