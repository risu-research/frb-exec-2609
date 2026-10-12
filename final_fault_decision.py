"""Single pre-registered go/no-go test of secondary faults on feasible PMU channels.

No model fitting on fault labels. Calibration only on no-fault simulation
perturbations in DER scenarios S1-S3. Holdout uses S4-S6. The synthetic
measurement error and load drift are sensitivity assumptions, NOT measured
field accuracy, relay certification or a claim that the 1% IEEE TVE bound is
a probability model.
"""
from __future__ import annotations
import csv, io, json, re, zipfile, hashlib, collections, time, os, sys
from pathlib import Path
import numpy as np
import pandas as pd
import requests

OUT=Path("decision_result");OUT.mkdir(exist_ok=True)
ROOT="https://zenodo.org/records/22904220/files/"
RAW=Path("DERfaults_measurements.csv")
SHA="645fc79d6cd9f35324295317317683be5fd085524521346f84e42837a657c6bd"
seed=20261012
rng=np.random.default_rng(seed)
def fetch(url,timeout=100):r=requests.get(url,timeout=timeout);r.raise_for_status();return r.content
meta=pd.read_csv(io.BytesIO(fetch(ROOT+"labels_metadata_DERfaults.csv?download=1")))
placement=pd.read_csv(io.BytesIO(fetch(ROOT+"pmu_placement_configurations.csv?download=1")))
pmu=set(placement.PMU_93.dropna().astype(str).str.lower())
assert len(pmu)==93 and len(meta)==19800
old=pd.read_csv("original_baseline/fault_output/per_fault_scores.csv")
assert old.SampleID.is_unique and len(old)==19800
frozen=old[["SampleID","score_93"]].merge(meta,on="SampleID",validate="one_to_one")
frozen["low_side"]=frozen.Fault_Bus.fillna("").str.lower().str.startswith("t_bus")
frozen["missed_voltage"]=frozen.low_side & (frozen.Fault_Label!=0) & (frozen.score_93<.01)
assert frozen.missed_voltage.sum()==5833 and frozen.low_side.sum()==5849
assert frozen.SampleID.is_unique
print("FROZEN_DEFINITIONS",json.dumps({"samples":len(frozen),"faults":int((frozen.Fault_Label!=0).sum()),"low_side_faults":int(((frozen.Fault_Label!=0)&frozen.low_side).sum()),"frozen_missed":int(frozen.missed_voltage.sum())}),flush=True)
model=zipfile.ZipFile(io.BytesIO(fetch("https://wzy.ece.iastate.edu/publication/OpenDSS%20Model.zip")))
linename=next(n for n in model.namelist() if n.endswith("/Line.dss"))
raw_lines=model.read(linename).decode("utf-8-sig",errors="replace")
topology={}
for l in raw_lines.splitlines():
 m=re.search(r"^\s*new\s+Line\.([^\s]+)",l,re.I)
 if not m:continue
 b1=re.search(r"\bbus1\s*=\s*([A-Za-z0-9_.]+)",l,re.I)
 b2=re.search(r"\bbus2\s*=\s*([A-Za-z0-9_.]+)",l,re.I)
 if b1 and b2:topology[m.group(1).lower()]=(b1.group(1).split(".")[0].lower(),b2.group(1).split(".")[0].lower())
print("TOPOLOGY_LINES",len(topology),"PMU_BUSES",len(pmu),flush=True)
if os.getenv("SOURCE_PREFLIGHT")=="1":
 assert len(topology)>=150,"Unable to match enough physical line terminals"
 print("SOURCE_PREFLIGHT_OK",flush=True)
 sys.exit(0)
if not RAW.exists():
 size=0;digest=hashlib.sha256()
 with requests.get(ROOT+"DERfaults_measurements.csv?download=1",stream=True,timeout=(35,240)) as r:
  r.raise_for_status()
  with RAW.open("wb") as w:
   for ix,part in enumerate(r.iter_content(4*1024*1024)):
    if part:
     w.write(part);digest.update(part);size+=len(part)
     if ix%55==0:print("DOWNLOAD_MB",round(size/1e6,1),flush=True)
 assert digest.hexdigest()==SHA
 print("DOWNLOAD_OK",size,digest.hexdigest(),flush=True)
else:
 digest=hashlib.sha256()
 with RAW.open("rb") as h:
  for part in iter(lambda:h.read(8*1024*1024),b""):digest.update(part)
 assert digest.hexdigest()==SHA
 print("CACHED_SOURCE_OK",RAW.stat().st_size,flush=True)
with RAW.open("r",encoding="utf-8-sig") as f:fields=next(csv.reader(f))
field_set=set(fields)
vcols=[];icols=[];all_lines=set();bad_lines=set()
for field in fields:
 m=re.match(r"^(bus[^.]+)\.([123])_Vmag_pre$",field,re.I)
 if m:
  stem=field[:-len("_Vmag_pre")]
  names=[stem+"_Vmag_pre",stem+"_Vang_pre",stem+"_Vmag_post",stem+"_Vang_post"]
  if all(n in field_set for n in names):vcols.append((stem,names))
 m=re.match(r"^Line\.(.+)_T([12])_Ph([123])_Imag_pre$",field,re.I)
 if m:
  line=m.group(1).lower();end=int(m.group(2))
  all_lines.add(line)
  names=[field,field.replace("_Imag_pre","_Iang_pre"),field.replace("_Imag_pre","_Imag_post"),field.replace("_Imag_pre","_Iang_post")]
  if line not in topology:bad_lines.add(line);continue
  terminal_bus=topology[line][end-1]
  if terminal_bus in pmu and all(n in field_set for n in names):
   icols.append((line,end,terminal_bus,names))
coverage={"voltage_channels":len(vcols),"all_current_lines":len(all_lines),
 "model_line_map_n":len(topology),"missing_line_ids":sorted(bad_lines)[:40],
 "pmu_current_channels":len(icols),"measured_current_lines":len(set(x[0] for x in icols)),
 "pmu_current_sites":len(set(x[2] for x in icols)),
 "pmu_sites_total":len(pmu)}
print("PHYSICAL_CHANNEL_COVERAGE",json.dumps(coverage),flush=True)
# This is a strict source-accessibility gate; missing mapping must not silently
# fall back to an unrealistic 'all line currents available' assumption.
assert len(icols)>=50 and len(set(x[2] for x in icols))>=15, "PMU-valid current observation unavailable"
assert len(bad_lines)<10, "Original circuit lacks physical mapping for many line-current channels"
needed={"SampleID"}
for _,cols in vcols:needed.update(cols)
for _,_,_,cols in icols:needed.update(cols)
def matrices(chunk,columns):
 pre_m=np.column_stack([pd.to_numeric(chunk[cols[0]],errors="coerce").to_numpy(dtype=np.float32) for *_,cols in columns])
 pre_a=np.column_stack([pd.to_numeric(chunk[cols[1]],errors="coerce").to_numpy(dtype=np.float32) for *_,cols in columns])
 post_m=np.column_stack([pd.to_numeric(chunk[cols[2]],errors="coerce").to_numpy(dtype=np.float32) for *_,cols in columns])
 post_a=np.column_stack([pd.to_numeric(chunk[cols[3]],errors="coerce").to_numpy(dtype=np.float32) for *_,cols in columns])
 pre=pre_m*np.exp(1j*np.deg2rad(pre_a))
 post=post_m*np.exp(1j*np.deg2rad(post_a))
 return pre.astype(np.complex64),post.astype(np.complex64)

# RMS complex phasor perturbation and independent small source/load drift.
# Three independently specified stress settings, NOT tuned against fault labels.
REGIMES=[
 {"name":"low","tve_rms":.002,"current_drift_rms":.005,"voltage_drift_rms":.001},
 {"name":"nominal","tve_rms":.005,"current_drift_rms":.010,"voltage_drift_rms":.002},
 {"name":"stress","tve_rms":.010,"current_drift_rms":.020,"voltage_drift_rms":.004},
]
REPLICATES=2
parts=[]
def perturb(pre,post,kind,reg):
 n,k=pre.shape
 # Random perturbations are independent across pre/post observations and sensors;
 # do not interpret as actual PMU measurement noise distributions.
 s=reg["tve_rms"]
 b=np.abs(pre)
 e1=(rng.standard_normal((n,k))+1j*rng.standard_normal((n,k)))*s/np.sqrt(2)
 e2=(rng.standard_normal((n,k))+1j*rng.standard_normal((n,k)))*s/np.sqrt(2)
 drift=reg["current_drift_rms"] if kind=="i" else reg["voltage_drift_rms"]
 common=rng.normal(0,drift,(n,1))
 a=pre+b*e1
 c=post*(1+common)+b*e2
 if kind=="v":
  with np.errstate(divide="ignore",invalid="ignore"):
   q=np.abs(c-a)/np.maximum(np.abs(pre),1.0)
 else:
  with np.errstate(divide="ignore",invalid="ignore"):
   q=np.abs(c-a)/np.maximum(np.max(np.abs(pre),axis=1,keepdims=True),1.0)
 q=np.where(np.isfinite(q),q,-1.0)
 return np.maximum(0,np.max(q,axis=1))
rows=0
for chunk in pd.read_csv(RAW,usecols=lambda n:n in needed,chunksize=64):
 vp,vq=matrices(chunk,vcols)
 ip,iq=matrices(chunk,icols)
 for reg in REGIMES:
  for rep in range(REPLICATES):
   parts.append(pd.DataFrame({"SampleID":chunk.SampleID.to_numpy(dtype=np.int32),
     "regime":reg["name"],"rep":rep,
     "vscore":perturb(vp,vq,"v",reg),
     "iscore":perturb(ip,iq,"i",reg)}))
 rows+=len(chunk)
 if rows%2560<64:print("EVALUATED_ROWS",rows,flush=True)
assert rows==19800
scores=pd.concat(parts,ignore_index=True)
df=scores.merge(frozen[["SampleID","Scenario_ID","Fault_Label","Fault_Type","Fault_Bus","Resistance","low_side","missed_voltage"]],on="SampleID",validate="many_to_one")
df["normal"]=df.Fault_Label==0
df["test"]=df.Scenario_ID.isin(["S4","S5","S6"])
df["train"]=df.Scenario_ID.isin(["S1","S2","S3"])
assert df.train.sum()==9900*REPLICATES and df.test.sum()==9900*REPLICATES
summary={"fixed_assumptions":{"rng_seed":seed,"replicates":REPLICATES,"training_scenarios":"S1,S2,S3 - normal only",
  "testing_scenarios":"S4,S5,S6","FPR_budget":.01,"predeclared_nominal_GO_low_side_detection":.70,
  "predeclared_nominal_GO_fusion_over_best_modal_pp":10.0,
  "predeclared_stress_GO_low_side_detection":.50,"predeclared_upstream_detection":.95,
  "predeclared_max_test_fpr":.02,"note":"These are simulated nuisance models, not empirical PMU field validation"},
 "physical":coverage,"rows":rows,"regimes":[],"result":"PENDING"}
for reg in REGIMES:
 g=df[df.regime==reg["name"]].copy()
 train=g[g.train & g.normal]
 test=g[g.test].copy()
 assert len(train)==900*REPLICATES and len(test)==9900*REPLICATES
 qv=float(np.quantile(train.vscore,.99,method="higher"))
 qi=float(np.quantile(train.iscore,.99,method="higher"))
 vscale=max(float(np.quantile(train.vscore,.95)),1e-8)
 iscale=max(float(np.quantile(train.iscore,.95)),1e-8)
 trainfusion=np.maximum(train.vscore/vscale,train.iscore/iscale)
 fusedcal=float(np.quantile(trainfusion,.99,method="higher"))
 test["vdet"]=test.vscore>qv
 test["idet"]=test.iscore>qi
 test["fusion"]=np.maximum(test.vscore/vscale,test.iscore/iscale)>fusedcal
 def estimate(sub):
  return {k:float(sub[k].mean()) if len(sub) else None for k in ["vdet","idet","fusion"]}
 normal=estimate(test[test.normal])
 low=estimate(test[(~test.normal)&test.low_side])
 upstream=estimate(test[(~test.normal)&(~test.low_side)])
 previous=estimate(test[test.missed_voltage])
 byscenario={s:{"low_side":estimate(sgroup[(~sgroup.normal)&sgroup.low_side]),
     "normal":estimate(sgroup[sgroup.normal])}
   for s,sgroup in test.groupby("Scenario_ID")}
 bytype={str(k):estimate(sgroup[sgroup.low_side]) for k,sgroup in test[~test.normal].groupby("Fault_Type")}
 low_sites=test[(~test.normal)&test.low_side].groupby("Fault_Bus").fusion.mean()
 rec={"noise":reg,"calibration":{"v":qv,"i":qi,"fusion_norm":fusedcal},
   "n_test_normal":int(test.normal.sum()),"n_test_faults":int((~test.normal).sum()),
   "n_test_secondary":int(((~test.normal)&test.low_side).sum()),
   "n_test_previous_voltage_missed":int(test.missed_voltage.sum()),
   "false_alarm":normal,"secondary_detect":low,"other_fault_detect":upstream,"previously_missed_detect":previous,
   "secondary_fusion_minus_best_signal_pp":100*(low["fusion"]-max(low["vdet"],low["idet"])),
   "secondary_site_detection":{"n_sites":len(low_sites),"median":float(low_sites.median()),
     "p10":float(low_sites.quantile(.1)),"sites_below50pct":int((low_sites<.5).sum())},
   "per_scenario":byscenario,"per_fault_type":bytype}
 summary["regimes"].append(rec)
 print("HOLDOUT_RESULT",json.dumps(rec),flush=True)
# Fail closed on unresolved physical access, unrealistic test FPR, lack of strong new
# advantage beyond current-only, or collapse in higher-noise setting.
idx={x["noise"]["name"]:x for x in summary["regimes"]}
nom=idx["nominal"];stress=idx["stress"]
gates={
 "physical_line_to_pmu_mapping":len(icols)>=50 and len(bad_lines)<10,
 "heldout_false_alarm_at_most_2pct_all":all(max(x["false_alarm"].values())<=.02 for x in summary["regimes"]),
 "nominal_secondary_fusion_detect_at_least_70pct":nom["secondary_detect"]["fusion"]>=.70,
 "nominal_fusion_added_value_over_best_at_least_10pp":nom["secondary_fusion_minus_best_signal_pp"]>=10,
 "nominal_detect_other_faults_at_least_95pct":nom["other_fault_detect"]["fusion"]>=.95,
 "stress_secondary_fusion_detect_at_least_50pct":stress["secondary_detect"]["fusion"]>=.50,
 "nominal_scenarios_each_at_least_65pct_secondary":all(v["low_side"]["fusion"]>=.65 for v in nom["per_scenario"].values()),
}
summary["gates"]=gates
summary["result"]="GO" if all(gates.values()) else "NO_GO"
Path("decision_result/conclusion.json").write_text(json.dumps(summary,indent=2))
testout=df[(df.Scenario_ID.isin(["S4","S5","S6"]))&(df.regime=="nominal")]
testout[["SampleID","Scenario_ID","Fault_Label","Fault_Type","Fault_Bus","Resistance","low_side","missed_voltage","vscore","iscore"]].to_csv(OUT/"holdout_scores_nominal.csv",index=False)
print("PRE_REGISTERED_FINAL_DECISION",json.dumps({"result":summary["result"],"gates":gates,
  "nominal_secondary":nom["secondary_detect"],"stress_secondary":stress["secondary_detect"],
  "nominal_false_alarm":nom["false_alarm"],"accessible_current":len(icols)}),flush=True)
