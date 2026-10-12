"""Public-data, year-held-out evaluation of transmission constraint indicators."""
import hashlib, io, json, math, re, time
from pathlib import Path
import numpy as np
import pandas as pd
import requests

OUT=Path("results");OUT.mkdir(exist_ok=True)
base="https://api.neso.energy/dataset/"
sources={
 "flows":"cf3cbc92-2d5d-4c2b-bd29-e11a21070b26/resource/38a18ec1-9e40-465d-93fb-301e80fd1352/download/day-ahead-constraints-limits-and-flow-output-v1.5.csv",
 "cost_23_24":"f0055054-c55c-4068-a01c-61da4334e58f/resource/75c9c564-af38-4421-a461-a612a6921212/download/outturn-system-costs-2023-2024.csv",
 "cost_24_25":"f0055054-c55c-4068-a01c-61da4334e58f/resource/27df75fd-6233-466c-beed-3e6e2261e6b1/download/outturn-system-costs-2024-2025.csv",
 "cost_25_26":"f0055054-c55c-4068-a01c-61da4334e58f/resource/407f3e9d-5c38-4a64-98f5-923dc4d64fb2/download/outturn-system-costs-2025-2026.csv",
}
s=requests.Session();s.headers["User-Agent"]="PublicEnergyDataAudit/1.0"
provenance={}
for name,endpoint in sources.items():
 url=base+endpoint
 for attempt in range(3):
  try:
   with s.get(url,stream=True,timeout=(40,200)) as r:
    r.raise_for_status();dig=hashlib.sha256();n=0
    with open(name+".csv","wb") as dest:
     for part in r.iter_content(2**20):
      if part:dest.write(part);dig.update(part);n+=len(part)
   break
  except Exception as exc:
   print("FETCH_RETRY",name,attempt,type(exc).__name__,str(exc)[:250],flush=True)
   if attempt==2:raise
   time.sleep(3*(attempt+1))
 provenance[name]={"url":url,"size_bytes":n,"sha256":dig.hexdigest()}
 print("SOURCE",name,provenance[name]["size_bytes"],provenance[name]["sha256"],flush=True)

def readcsv(name):
 p=name+".csv"
 try:df=pd.read_csv(p,low_memory=False,on_bad_lines="error")
 except UnicodeDecodeError:df=pd.read_csv(p,low_memory=False,encoding="cp1252",on_bad_lines="error")
 print("RAW",name,len(df),list(df.columns),json.dumps(df.head(2).astype(str).to_dict("records"),ensure_ascii=False)[:900],flush=True)
 return df
def canonical(c):return re.sub(r"[^a-z0-9]","",str(c).lower())
def col(df,*want):
 have={canonical(x):x for x in df.columns}
 for w in want:
  if canonical(w) in have:return have[canonical(w)]
 for w in want:
  hits=[x for x in df.columns if canonical(w) in canonical(x)]
  if len(hits)==1:return hits[0]
 raise ValueError("Unrecognized fields "+str(want)+" actual "+str(list(df.columns)))
def groups(v):
 return v.astype(str).str.strip().str.upper().str.replace("-","_",regex=False).str.replace(" ","",regex=False)
f=readcsv("flows")
gf=col(f,"Constraint Group")
tf=col(f,"Date_ Time GMT_BST","Date, Time (GMT/BST)","Date Time GMT BST")
lf=col(f,"Limit_MW","Limit (MW)")
vf=col(f,"Flow_MW","Flow (MW)")
f["group"]=groups(f[gf]);f["timestamp"]=pd.to_datetime(f[tf],errors="coerce",dayfirst=False,format="mixed")
f["date"]=f["timestamp"].dt.normalize()
f["limit"]=pd.to_numeric(f[lf],errors="coerce")
f["flow"]=pd.to_numeric(f[vf],errors="coerce")
valid=(f["limit"]>0)&f["flow"].notna()&f["date"].notna()
print("FLOW_QUALITY",json.dumps({"raw":len(f),"valid":int(valid.sum()),"groups":sorted(f.group.unique().tolist()),"duplicate_group_timestamp":int(f.duplicated(["group","timestamp"]).sum()),"min_date":str(f.date.min()),"max_date":str(f.date.max())}),flush=True)
f=f.loc[valid].copy()
f["utilization"]=f["flow"]/f["limit"]
f["headroom"]=f["limit"]-f["flow"]
f["overload_mw"]=(f["flow"]-f["limit"]).clip(lower=0)
f["at90"]=f.utilization>=0.90
f["at100"]=f.utilization>=1.0
gd=f.groupby(["group","date"],as_index=False).agg(n_halfhours=("flow","size"),
  max_util=("utilization","max"),mean_util=("utilization","mean"),
  frac_near90=("at90","mean"),frac_over100=("at100","mean"),
  peak_overload_mw=("overload_mw","max"),
  mean_headroom=("headroom","mean"),max_flow=("flow","max"))
costs=[]
for name in ["cost_23_24","cost_24_25","cost_25_26"]:
 c=readcsv(name)
 gc=col(c,"Constraint Group")
 dc=col(c,"Settlement Date")
 cc=col(c,"Daily Cost (GBP)")
 c["group"]=groups(c[gc]);c["date"]=pd.to_datetime(c[dc],errors="coerce",format="mixed").dt.normalize()
 c["cost_gbp"]=pd.to_numeric(c[cc].astype(str).str.replace(",","",regex=False).str.replace("£","",regex=False),errors="coerce")
 print("COST_SUMMARY",name,json.dumps({"rows":len(c),"parsed":int(c.cost_gbp.notna().sum()),"groups":sorted(c.group.unique().tolist()),"min_date":str(c.date.min()),"max_date":str(c.date.max()),"negative":int((c.cost_gbp<0).sum()),"nonzero":int((c.cost_gbp!=0).sum()),"total_gbp":float(c.cost_gbp.sum())}),flush=True)
 costs.append(c[["group","date","cost_gbp"]])
cost=pd.concat(costs,ignore_index=True)
dupes=cost.duplicated(["group","date"]).sum()
if dupes:raise ValueError(f"Cost group-date duplicated {dupes}")
cost=cost.dropna(subset=["date","cost_gbp"]).copy()
joint=cost.merge(gd,on=["group","date"],how="left",indicator=True,validate="one_to_one")
joint["regime"]=np.where(joint.date<pd.Timestamp("2024-04-22"),"pre_change","post_change")
match_summary=joint.groupby(["group","regime"],dropna=False).agg(n_cost_days=("date","size"),
  flow_matched=("_merge",lambda v:int((v=="both").sum())),
  cost_total=("cost_gbp","sum"),
  matched_cost=("cost_gbp",lambda x:float(x.loc[joint.loc[x.index,"_merge"]=="both"].sum()))).reset_index()
print("MATCH_COUNTS",match_summary.to_json(orient="records"),flush=True)
print("MATCH_GLOBAL",json.dumps({"cost_days":len(cost),"matched":int((joint._merge=="both").sum()),"groups_in_both":sorted(set(cost.group)&set(gd.group)),"cost_groups_only":sorted(set(cost.group)-set(gd.group))}),flush=True)
match_summary.to_csv(OUT/"group_overlap.csv",index=False)

# Restrict main comparison to published definition regime and exact same assessed group-days.
j=joint[(joint._merge=="both")&(joint.date>=pd.Timestamp("2024-04-22"))&(joint.date<=pd.Timestamp("2026-03-31"))].copy()
j=j[j.n_halfhours>=35].copy()
j["cost_pos"]=j.cost_gbp.clip(lower=0)
j["fiscal_year"]=np.where(j.date<pd.Timestamp("2025-04-01"),"dev_24_25","heldout_25_26")
# Prior cost baseline has at least 7 days' assumed reporting latency.
history=cost.sort_values(["group","date"],kind="stable").copy()
history["cost_pos"]=history.cost_gbp.clip(lower=0)
history["past28_at_lag7"]=history.groupby("group").cost_pos.transform(lambda x:x.shift(7).rolling(28,min_periods=10).mean())
history["past7_at_lag7"]=history.groupby("group").cost_pos.transform(lambda x:x.shift(7).rolling(7,min_periods=5).mean())
j=j.merge(history[["group","date","past28_at_lag7","past7_at_lag7"]],on=["group","date"],validate="one_to_one")
training=j[j.fiscal_year=="dev_24_25"]
test=j[j.fiscal_year=="heldout_25_26"].copy()
trainmeans=training.groupby("group").cost_pos.mean()
j["group_train_mean"]=j.group.map(trainmeans)
test["group_train_mean"]=test.group.map(trainmeans)
# Only exact group-days where all strategies have valid, actually published day-ahead signals.
test=test.dropna(subset=["max_util","past28_at_lag7","group_train_mean"])
training=training.dropna(subset=["max_util","past28_at_lag7"])
print("EVALUATION_WINDOW",json.dumps({"training_n":len(training),"training_dates":int(training.date.nunique()),"test_n":len(test),"test_dates":int(test.date.nunique()),"test_groups":sorted(test.group.unique().tolist()),"test_total_gbp":float(test.cost_pos.sum()),"median_rows_per_day":float(test.groupby("date").size().median()),"zero_cost_fraction":float((test.cost_pos==0).mean()),"test_cost_positive":int((test.cost_pos>0).sum())}),flush=True)
# Retrospective fixed-budget evaluation: for each day, choose best one or two
# published constraint groups by as-of scores. Avoid using 2025 realized cost as a feature.
scores={
 "flow_peak_utilization":"max_util",
 "flow_overload_mw":"peak_overload_mw",
 "flow_hours_near90":"frac_near90",
 "flow_mean_utilization":"mean_util",
 "lagged_cost_28d":"past28_at_lag7",
 "lagged_cost_7d":"past7_at_lag7",
 "historical_group_mean":"group_train_mean",
}
# Unambiguous timestamp and deterministic tie-break by group code.
test=test.sort_values(["date","group"],kind="stable")
training.to_csv(OUT/"joined_training_days.csv",index=False)
test.to_csv(OUT/"joined_heldout_days.csv",index=False)
selection=[]
for k in [1,2]:
 for strategy,column in scores.items():
  selected=test.assign(_score=test[column].fillna(-1e20)).sort_values(
   ["date","_score","group"],ascending=[True,False,True],kind="stable").groupby("date",sort=False).head(k)
  daily=selected.groupby("date").cost_pos.sum()
  tot=test.groupby("date").cost_pos.sum()
  common=daily.index.intersection(tot.index)
  for day in common:
   selection.append({"date":day,"k":k,"strategy":strategy,
     "captured":float(daily.loc[day]),"available":float(tot.loc[day]),
     "candidate_groups":int((test.date==day).sum())})
daily=pd.DataFrame(selection)
daily.to_csv(OUT/"daily_decisions.csv",index=False)
summary=[]
for (k,strategy),z in daily.groupby(["k","strategy"]):
 # no action on dates without valid total costs; zero denominators remain in totals.
 summary.append({"k":int(k),"strategy":strategy,"days":len(z),
     "capture_fraction":float(z.captured.sum()/z.available.sum()) if z.available.sum()>0 else np.nan,
     "cost_captured_gbp":float(z.captured.sum()),
     "cost_total_gbp":float(z.available.sum()),
     "mean_daily_frac":float((z.captured/z.available.replace(0,np.nan)).mean()),
     "weekly_blocks":int(z.date.dt.to_period("W").nunique())})
S=pd.DataFrame(summary).sort_values(["k","capture_fraction"],ascending=[True,False])
print("DECISION_RESULTS",S.round(5).to_json(orient="records"),flush=True)
# paired weekly-block bootstrap across same days preserving temporal dependence.
rng=np.random.default_rng(20261012)
pairwise=[]
for k in [1,2]:
 c=daily[daily.k==k].pivot(index="date",columns="strategy",values="captured")
 z=daily[daily.k==k].groupby("date").available.first()
 assert not c.isna().any().any()
 blocks=c.index.to_period("W")
 uniq=blocks.unique()
 cvals=c.to_numpy(dtype=float); yvals=z.to_numpy(dtype=float)
 block_indices=[np.where(blocks==u)[0] for u in uniq]
 for v in ["lagged_cost_28d","lagged_cost_7d","historical_group_mean"]:
  method="flow_peak_utilization"
  a=c[method].to_numpy();b=c[v].to_numpy()
  observed=(a.sum()-b.sum())/z.sum()
  rep=[]
  for _ in range(3000):
   sampled=rng.integers(0,len(block_indices),len(block_indices))
   ix=np.concatenate([block_indices[u] for u in sampled])
   den=yvals[ix].sum()
   if den>0:rep.append((a[ix].sum()-b[ix].sum())/den)
  bounds=np.quantile(rep,[.025,.975])
  pairwise.append({"k":k,"method":method,"reference":v,"diff_pctpoints":float(100*observed),
    "bootstrap95_pctpoints":[float(100*bounds[0]),float(100*bounds[1])],
    "weeks":len(uniq)})
print("PAIRWISE_VS_BASELINES",json.dumps(pairwise),flush=True)
# Diagnose cost state: compare predictor distributions when costs high, zero, and nonzero.
valid=test.copy()
valid["cost_gt0"]=valid.cost_pos>0
valid["cost_top10"]=valid.cost_pos>=valid.cost_pos.quantile(.9)
diag=valid.groupby("group").agg(n=("date","size"),n_cost=("cost_gt0","sum"),
 total_cost=("cost_pos","sum"),median_max_util=("max_util","median"),
 frac_peak_above1=("max_util",lambda x:float((x>=1).mean())),
 within_group_corr=("max_util",lambda x:float(x.corr(valid.loc[x.index,"cost_pos"])))).reset_index()
print("GROUP_DIAGNOSTICS",diag.round(6).to_json(orient="records"),flush=True)
diag.to_csv(OUT/"group_diagnostics.csv",index=False)
obj={"provenance":provenance,"overlap":match_summary.to_dict("records"),
 "train_rows":len(training),"test_rows":len(test),"test_dates":int(test.date.nunique()),
 "test_groups":sorted(test.group.unique().tolist()),
 "results":summary,"paired":pairwise,
 "notes":["Thermal outturn costs are observed expenditure, not physical transmission failures",
 "Retrospective cross-day capture is evaluated as day-by-day top-K triage",
 "Past-cost features shift by 7 days to reflect weekly publication cadence",
 "No cross-regime pooling before 2024-04-22",
 "Forecast archive not independently verified for vintage revisions"]}
(OUT/"report.json").write_text(json.dumps(obj,indent=2,default=str))
print("PILOT_COMPLETE",flush=True)
