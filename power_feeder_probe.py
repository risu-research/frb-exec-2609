"""Smoke test of accessible, published power-distribution feeders."""
import json,os,traceback
import powerfulcases as cases
from opendssdirect import dss
for name in ["ieee13_opendss","ieee34_opendss","ieee37_opendss","ieee123_opendss"]:
 try:
  c=cases.load(name)
  print("CASE",name,"PATH",c.dss,flush=True)
  dss.Text.Command(f'Compile "{c.dss}"')
  dss.Solution.Solve()
  print("BASE",json.dumps({"name":name,"converged":bool(dss.Solution.Converged()),
    "nodes":len(dss.Circuit.AllBusNames()),"load_count":dss.Loads.Count(),
    "loads":dss.Loads.AllNames()[:12],"lines":len(dss.Lines.AllNames()),
    "sample_buses":dss.Circuit.AllBusNames()[:18],
    "voltage_pu":[round(float(x),5) for x in dss.Circuit.AllBusMagPu()[:15]],
    "minpu":float(min((x for x in dss.Circuit.AllBusMagPu() if x>0),default=0)),
    "maxpu":float(max(dss.Circuit.AllBusMagPu() or [0]))}),flush=True)
  print("LINES",name,[(l,dss.Lines.Name(l),dss.Lines.Bus1(),dss.Lines.Bus2()) for l in dss.Lines.AllNames()[:5]],flush=True)
 except Exception as e: print("FAIL",name,type(e).__name__,str(e)[:600],traceback.format_exc()[-700:],flush=True)
