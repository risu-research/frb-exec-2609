"""Frozen-tap and automatic-tap controls for voltage screening under PV injections."""
import os,json,hashlib
from pathlib import Path
import pandas as pd,numpy as np
from opendssdirect import dss
ROOT=(Path.cwd()/"published-models/Distrib/IEEETestCases").resolve()
CASES={"ieee34":("34Bus","ieee34Mod1.dss","890",4.16),
       "ieee123":("123Bus","IEEE123Master.dss","48",4.16)}
levels=[0,10,25,50,75,100,150,200,300,400,600,800]
results=[]
def setup(case):
 folder,file,bus,kv=CASES[case]
 p=ROOT/folder/file
 for needed in ("IEEELineCodes.dss","IEEELinecodes.DSS"):
  if not (p.parent/needed).exists():
   src=next((x for x in p.parent.iterdir() if x.name.lower()==needed.lower()),None)
   if src:(p.parent/needed).symlink_to(src.name)
 os.chdir(p.parent)
 dss.Text.Command(f'Compile "{p}"')
 dss.Solution.Solve()
 return bus,kv
def taps():
 r={}
 for n in dss.RegControls.AllNames():
  dss.RegControls.Name(n)
  r[n]=int(dss.RegControls.TapNumber())
 return r
def volts(case,kw,mode):
 bus,kv=setup(case)
 pre=taps()
 if mode=="fixed":dss.Text.Command("Set ControlMode=Off")
 if kw:
  dss.Text.Command(f'New Generator.PVTEST phases=3 bus1={bus} kv={kv} kW={kw} pf=1 model=1')
  dss.Solution.Solve()
 after=taps()
 v=[float(x) for x in dss.Circuit.AllBusMagPu() if np.isfinite(x) and x>.30]
 mn,mx=min(v),max(v)
 return {"case":case,"pv_bus":bus,"kw":kw,"control":mode,
         "converged":bool(dss.Solution.Converged()),
         "minpu":round(mn,7),"maxpu":round(mx,7),
         "strict_ansi_95_105":bool(dss.Solution.Converged() and mn>=.95 and mx<=1.05),
         "taps":after,"tap_changes":{k:after[k]-pre.get(k,0) for k in after}}
for case in CASES:
 for mode in ["auto","fixed"]:
  for kw in levels:
   try:
    r=volts(case,kw,mode)
    results.append(r)
    print("EVALUATION",json.dumps(r),flush=True)
   except Exception as e:
    print("EVALUATION_FAILURE",case,mode,kw,type(e).__name__,str(e),flush=True)
pd.DataFrame([{k:v for k,v in row.items() if k not in ("taps","tap_changes")} for row in results]).to_csv("tap_intervention.csv",index=False)
Path("tap_intervention.json").write_text(json.dumps(results,indent=2))
for case in CASES:
 for mode in ["auto","fixed"]:
  rows=[x for x in results if x["case"]==case and x["control"]==mode]
  status=[x["strict_ansi_95_105"] for x in rows]
  transitions=[(rows[i-1]["kw"],rows[i]["kw"],status[i-1],status[i])
               for i in range(1,len(rows)) if status[i-1]!=status[i]]
  print("NONMONOTONICITY",json.dumps({"case":case,"mode":mode,"transitions":transitions,
       "feasible_kw":[x["kw"] for x in rows if x["strict_ansi_95_105"]]}),flush=True)
print("CONTROL_AUDIT_COMPLETE",len(results),flush=True)
