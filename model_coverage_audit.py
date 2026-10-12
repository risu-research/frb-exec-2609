"""Electrical-simulation benchmark for customer-preserving model repair."""
import os,json,math,hashlib,subprocess
from pathlib import Path
import numpy as np
import pandas as pd
from opendssdirect import dss

HOME=Path.cwd()
BASE=(HOME/"published-models/Distrib/IEEETestCases").resolve()
CASES={"ieee34":("34Bus","ieee34Mod1.dss"),"ieee123":("123Bus","IEEE123Master.dss")}
OUT=HOME/"simulation_results";OUT.mkdir(exist_ok=True)
levels=[0,10,25,50,75,100,150,200,300,400,600,800]
results=[];screen=[];manifest={}
def normalize_case(folder):
 for needed in ("IEEELineCodes.dss","IEEELinecodes.DSS"):
  p=folder/needed
  if p.exists():continue
  match=next((x for x in folder.iterdir() if x.name.lower()==needed.lower()),None)
  if match:p.symlink_to(match.name)
def load_case(case):
 folder,file=CASES[case]
 path=BASE/folder/file
 normalize_case(path.parent)
 os.chdir(path.parent)
 dss.Text.Command(f'Compile "{path}"')
 dss.Solution.Solve()
 return path
def loads():
 catalog=[]
 for name in dss.Loads.AllNames():
  dss.Loads.Name(name)
  rating=dss.Loads.kW();kv=dss.Loads.kV();phase=dss.Loads.Phases()
  dss.Circuit.SetActiveElement("Load."+name)
  bus=dss.CktElement.BusNames()[0]
  catalog.append({"load":name,"bus":bus,"kw":float(rating),"kv":float(kv),"phase":int(phase)})
 return catalog
def measure(catalog):
 solved=bool(dss.Solution.Converged())
 observed=[]
 valid_volts=[float(v) for v in dss.Circuit.AllBusMagPu() if np.isfinite(v) and v>0.30]
 served=[];missed=[]
 for l in catalog:
  dss.Circuit.SetActiveElement("Load."+l["load"])
  power=dss.CktElement.Powers()
  p=sum(max(float(power[i].real),0) for i in range(min(len(power),l["phase"])))
  if l["kw"]>0 and p>.45*l["kw"]:served.append(l)
  elif l["kw"]>0:missed.append(l)
 r={"converged":solved,"min_v":round(min(valid_volts),6) if valid_volts else None,
    "max_v":round(max(valid_volts),6) if valid_volts else None,
    "energized_nodes":len(valid_volts),"total_loads":len(catalog),
    "served_loads":len(served),"missed_loads":len(missed),
    "served_kw":round(sum(l["kw"] for l in served),5),
    "lost_kw":round(sum(l["kw"] for l in missed),5),
    "lost_loads":",".join(l["load"] for l in missed[:15])}
 r["voltage_ok"]=solved and r["min_v"] is not None and r["min_v"]>=0.9499 and r["max_v"]<=1.0501
 r["service_ok"]=len(missed)==0
 r["eligible"]=bool(r["voltage_ok"] and r["service_ok"])
 return r
def execute(case,catalog,disabled=None,pv=None,kw=0):
 load_case(case)
 if disabled:dss.Text.Command(f"Disable Line.{disabled}")
 if pv is not None and kw>0:
  # Generator is a unity-power-factor PV output proxy under a fixed daytime snapshot.
  command=f"New Generator.PVTEST phases={pv['phase']} bus1={pv['bus']} kV={pv['kv']} kW={kw} pf=1 model=1"
  dss.Text.Command(command)
 dss.Solution.Solve()
 return measure(catalog)
def hc(case,catalog,disabled,pv):
 records=[]
 for power in levels:
  r=execute(case,catalog,disabled=disabled,pv=pv,kw=power)
  records.append({"power_kw":power,**r})
 # A conservative voltage-only HC bound (not a full solar hosting capacity).
 feasible=0
 for r in records:
  if r["voltage_ok"]:feasible=r["power_kw"]
  else:break
 return feasible,records

for case in CASES:
 filepath=load_case(case)
 catalog=loads()
 assert len(catalog)>20
 elements=list(dss.Lines.AllNames())
 base=measure(catalog)
 assert base["converged"]
 print("BASELINE",case,json.dumps({k:v for k,v in base.items() if k!="lost_loads"}),flush=True)
 manifest[case]={"path":str(filepath.relative_to(HOME)),"sha256":hashlib.sha256(filepath.read_bytes()).hexdigest(),
                 "n_loads":len(catalog),"n_lines":len(elements),"nominal_kw":sum(l["kw"] for l in catalog)}
 # Every switchable line is screened, without picking only positive examples.
 for i,line in enumerate(elements):
  try:
   r=execute(case,catalog,disabled=line)
   lost_frac=r["lost_kw"]/max(1e-12,sum(l["kw"] for l in catalog))
   vchange=(r["min_v"]-base["min_v"]) if r["min_v"] is not None else None
   rr={"case":case,"line":line,"lost_frac":round(lost_frac,6),
       "minvoltage_improvement":round(vchange,6) if vchange is not None else None,
       "loss_kw":r["lost_kw"],"lost_loads":r["missed_loads"],"eligible_voltage":r["voltage_ok"],
       "baseline_min":base["min_v"],"post_min":r["min_v"],
       "converged":r["converged"]}
   screen.append(rr)
  except Exception as e:screen.append({"case":case,"line":line,"error":str(e)[:200]})
 passed=[x for x in screen if x.get("case")==case and x.get("converged")]
 burdens=[x for x in passed if x.get("lost_frac",0)>0.005 and x.get("lost_frac",0)<0.45]
 fixed=[x for x in burdens if x.get("eligible_voltage")]
 print("PRUNE_SCREEN",case,json.dumps({
   "tested":len(elements),"cause_any_customer_loss":len([x for x in passed if x.get("lost_frac",0)>0]),
   "burden_candidate":len(burdens),"voltage_pass_after_customer_loss":len(fixed),
   "highest_min_voltage_gain":sorted(burdens,key=lambda x:x.get("minvoltage_improvement",-1),reverse=True)[:8]
 }),flush=True)
 # Pre-registered, deterministic selection: best voltage gain (if any) and bounded-load losses.
 chosen=[]
 for x in sorted(burdens,key=lambda x:(x.get("minvoltage_improvement",-1),-x["lost_frac"]),reverse=True):
  if x["line"] not in chosen:chosen.append(x["line"])
  if len(chosen)>=3:break
 # select 3 high-rated loads in distinct buses, excluding removed customers.
 eligible_loads=sorted([l for l in catalog if l["phase"]==3 and l["kv"]>1 and l["kw"]>=10],
                      key=lambda x:(-x["kw"],x["bus"]))
 if len(eligible_loads)<3:
  eligible_loads=sorted([l for l in catalog if l["kw"]>=10],key=lambda x:(-x["kw"],x["bus"]))
 seen=set();spots=[]
 for x in eligible_loads:
  bus=x["bus"].split(".")[0]
  if bus not in seen:spots.append(x);seen.add(bus)
  if len(spots)>=3:break
 print("TARGETS",case,json.dumps({"lines":chosen,"pv_spots":spots}),flush=True)
 for pv in spots:
  base_hc,baseline_records=hc(case,catalog,None,pv)
  assert baseline_records[0]["lost_kw"]<0.0001
  print("PV_BASE",case,pv["bus"],base_hc,json.dumps([{"kw":r["power_kw"],"low":r["min_v"],"high":r["max_v"],"ok":r["voltage_ok"]} for r in baseline_records]),flush=True)
  for cut in [None]+chosen:
   if cut is None: cap,records=base_hc,baseline_records
   else:cap,records=hc(case,catalog,cut,pv)
   # Always rescore claimed capacity on original, unmodified feeder.
   original_at_claim=next((r for r in baseline_records if r["power_kw"]==cap),None)
   if original_at_claim is None:original_at_claim=execute(case,catalog,None,pv,kw=cap)
   model_at_claim=next((r for r in records if r["power_kw"]==cap),records[0])
   pvlost=model_at_claim["lost_kw"]
   # service preserving and original violation are independent conditions.
   row={"case":case,"pv_load":pv["load"],"pv_bus":pv["bus"],"removed_line":cut or "none",
    "baseline_min_pu":base["min_v"],"hc_voltage_only_kw":cap,
    "original_hc_voltage_only_kw":base_hc,
    "claimed_gain_kw":cap-base_hc,
    "removed_load_kw_at_claim":pvlost,
    "removed_load_share":pvlost/max(1,sum(x["kw"] for x in catalog)),
    "original_voltage_ok_at_claim":original_at_claim["voltage_ok"],
    "original_min_at_claim":original_at_claim["min_v"],
    "original_max_at_claim":original_at_claim["max_v"],
    "customer_service_preserved":model_at_claim["service_ok"],
    "claim_satisfies_original_and_preserves_load":bool(original_at_claim["voltage_ok"] and model_at_claim["service_ok"]),
    "status_curve":[{"kw":r["power_kw"],"voltage_ok":r["voltage_ok"],"service_ok":r["service_ok"],
                     "min":r["min_v"],"max":r["max_v"]} for r in records]}
   results.append(row)
   print("HC_RESULT",json.dumps({k:v for k,v in row.items() if k!="status_curve"}),flush=True)
pd.DataFrame(screen).to_csv(OUT/"all_line_pruning_diagnostics.csv",index=False)
pd.DataFrame([{k:v for k,v in row.items() if k!="status_curve"} for row in results]).to_csv(OUT/"solar_siting_decisions.csv",index=False)
summary={"case_manifest":manifest,"limits":{"voltage_pu":[0.9499,1.0501],
         "scan_kw":levels,"service_threshold":"supplied load >45% rated demand",
         "claim":"Voltage-only exploratory snapshot, not full HC certification"},
         "baseline":{case:[s for s in results if s["case"]==case and s["removed_line"]=="none"] for case in CASES},
         "screen":screen,"results":results}
(OUT/"simulation.json").write_text(json.dumps(summary,indent=2))
print("SIMULATION_COMPLETE",json.dumps({"n_lines_tested":len(screen),"n_curves":len(results),"models":list(CASES)}),flush=True)
