"""Published IEEE distribution feeder reproducibility probe."""
import json,traceback
from pathlib import Path
from opendssdirect import dss
ROOT=Path("published-models/Distrib/IEEETestCases")
CASES={"ieee13":("13Bus","IEEE13Nodeckt.dss"),
       "ieee34":("34Bus","ieee34Mod1.dss"),
       "ieee123":("123Bus","IEEE123Master.dss")}
for name,(folder,file) in CASES.items():
 try:
  path=(ROOT/folder/file).resolve()
  assert path.exists(),str(path)
  print("CASE",name,"BYTES",path.stat().st_size,flush=True)
  dss.Text.Command(f'Compile "{path}"')
  dss.Solution.Solve()
  volts=list(dss.Circuit.AllBusMagPu())
  loads=dss.Loads.AllNames()
  lines=dss.Lines.AllNames()
  print("BASE",json.dumps({"name":name,"converged":bool(dss.Solution.Converged()),
    "buses":len(dss.Circuit.AllBusNames()),"loads":len(loads),"lines":len(lines),
    "sample_loads":loads[:10],"sample_buses":dss.Circuit.AllBusNames()[:10],
    "minpu":min([v for v in volts if v>0],default=0),
    "maxpu":max(volts,default=0),
    "sumloadkw":sum([dss.Loads.kW() for l in loads if dss.Loads.Name(l)])}),flush=True)
  for l in loads[:3]:
   dss.Loads.Name(l)
   dss.Circuit.SetActiveElement("Load."+l)
   print("LOAD_SAMPLE",name,l,dss.CktElement.BusNames(),dss.Loads.kV(),dss.Loads.Phases(),dss.Loads.kW(),flush=True)
  for l in lines[:5]:
   dss.Lines.Name(l)
   print("LINE_SAMPLE",name,l,dss.Lines.Bus1(),dss.Lines.Bus2(),flush=True)
 except Exception as e: print("FAIL",name,type(e).__name__,str(e)[:600],traceback.format_exc()[-500:],flush=True)
