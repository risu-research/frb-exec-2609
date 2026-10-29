#!/usr/bin/env python3
"""FOCI 2027: fixed 8-site unlisted non-sanctioned Russian news controls.
Predeclared and checked absent in Citizen Lab global+6 EU country lists at
2025-04-07 commit and 2026-10-29 current snapshot before OONI outcomes.
Historical OONI coverage, not sanctions compliance or website availability.
"""
import csv,json,time,datetime as dt,sys
from pathlib import Path
from collections import defaultdict
from foci_ooni_count import CCS,PERIODS,request_json,rows_for_result,as_number,write_csv

CONTROLS = [
 ("Novaya Gazeta Europe","novayagazeta.eu"),
 ("The Moscow Times","themoscowtimes.com"),
 ("RBC","rbc.ru"),
 ("Mediazona","zona.media"),
 ("The Bell","thebell.io"),
 ("TV Rain","tvrain.tv"),
 ("Fontanka","fontanka.ru"),
 ("iStories","istories.media")
]
HOSTS=[x[1] for x in CONTROLS]
O=Path("foci_unlisted_controls_results")
O.mkdir(exist_ok=True)
rows=[];errors=[]
for cc in CCS:
 for since,until in PERIODS:
  days=(dt.date.fromisoformat(until)-dt.date.fromisoformat(since)).days
  params={"probe_cc":cc,"domain":",".join(HOSTS),
          "test_name":"web_connectivity","since":since,"until":until,
          "axis_x":"domain","axis_y":"probe_asn"}
  try:
   v,u=request_json(params,attempts=5)
   byhost={h:{"n":0,"asns":set(),"anomaly":0,"confirmed":0,"failure":0} for h in HOSTS}
   for result in rows_for_result(v):
    h=result.get("domain")
    if h not in byhost:raise ValueError("Unrequested host "+str(h))
    d=byhost[h]
    n=int(result.get("measurement_count",0))
    d["n"]+=n
    asn=as_number(result.get("probe_asn"))
    if asn and n:d["asns"].add(asn)
    for src,dst in [("anomaly_count","anomaly"),("confirmed_count","confirmed"),("failure_count","failure")]:
     d[dst]+=int(result.get(src,0))
   for ent,h in CONTROLS:
    d=byhost[h]
    rows.append({"country":cc,"since":since,"until_exclusive":until,"days":days,
      "entity":ent,"hostname":h,"measurement_count":d["n"],
      "unique_asn_count":len(d["asns"]),"asn_ids":";".join(sorted(d["asns"])),
      "anomaly_count":d["anomaly"],"confirmed_count":d["confirmed"],
      "failure_count":d["failure"],"source_query":u,"status":"complete"})
   print("UNLISTED",cc,since,"measurements",sum(d["n"] for d in byhost.values()),
         "sites_seen",sum(d["n"]>0 for d in byhost.values()),flush=True)
  except Exception as exc:
   errors.append({"country":cc,"since":since,"until_exclusive":until,"error":str(exc)})
   print("FAILED",cc,since,str(exc)[:200],file=sys.stderr,flush=True)
  time.sleep(.4)

fieldnames=["country","since","until_exclusive","days","entity","hostname",
            "measurement_count","unique_asn_count","asn_ids","anomaly_count",
            "confirmed_count","failure_count","source_query","status"]
write_csv(O/"unlisted_site_country_period.csv",rows,fieldnames)
write_csv(O/"failed_queries.csv",errors,["country","since","until_exclusive","error"])
summ=[]
for cc in CCS:
 for ent,host in CONTROLS:
  r=[x for x in rows if x["country"]==cc and x["hostname"]==host]
  asns=set()
  for x in r:asns.update(filter(None,x["asn_ids"].split(";")))
  summ.append({"country":cc,"entity":ent,"hostname":host,
   "measurement_count":sum(x["measurement_count"] for x in r),
   "asn_union_count":len(asns),"asn_ids":";".join(sorted(asns)),
   "positive_windows":sum(x["measurement_count"]>0 for x in r),
   "complete_windows":len(r),"expected_windows":len(PERIODS),
   "status":"complete" if len(r)==len(PERIODS) else "incomplete"})
write_csv(O/"unlisted_site_country_full_period.csv",summ,
          ["country","entity","hostname","measurement_count","asn_union_count","asn_ids",
           "positive_windows","complete_windows","expected_windows","status"])
manifest={
 "purpose":"Equal-sized unlisted non-sanctioned news cohort; descriptive coverage check",
 "date_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"countries":CCS,
 "dates":PERIODS,"controls":CONTROLS,
 "test_lists":["global","de","fr","pl","it","cz","sk"],
 "pre_activation_snapshot":"74c65f0cb00db78525404c01269cc2a65e7addcc",
 "pre_activation_and_current_testlist_matches":0,
 "site_selection":"fixed prior to outcome query from recognizable Russia-related news outlets absent in all 7 lists",
 "n_successful_queries":42-len(errors),"n_failed_queries":len(errors),
 "complete":not errors,
 "note":"Absence in these 7 test lists does not imply absence on other national lists or no custom OONI probes. All sites' legal status needs interpretation at entity level."}
(O/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
print("DONE",json.dumps(manifest),flush=True)
if errors:sys.exit(2)
