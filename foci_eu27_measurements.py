#!/usr/bin/env python3
"""FOCI 2027 EU27 observed measurement coverage, 42-host fixed bounded corpus.

The same 2025-04-09 to 2026-10-30 exclusive windows as the earlier six-
country audit, extended to all 27 EU member states. Uses read-only official
OONI aggregates grouped by hostname and ASN. Zero recorded only on successful
queries; incomplete queries flagged, never imputed. No active probes.
"""
import csv,json,sys,time,datetime as dt
from collections import defaultdict
from pathlib import Path
from foci_ooni_count import PERIODS,request_json,rows_for_result,as_number,write_csv
from foci_ooni_aliases import HOSTS,ROOT_TO_ENTRY,ENTRIES,entry_for
EU27=["AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR",
      "HU","IE","IT","LV","LT","LU","MT","NL","PL","PT","RO","SK",
      "SI","ES","SE"]
OUT=Path("foci_eu27_measurements");OUT.mkdir(exist_ok=True)
failures=[];hosts=[];entries=[];blocks=[]
for cc in EU27:
 for since,until in PERIODS:
  days=(dt.date.fromisoformat(until)-dt.date.fromisoformat(since)).days
  params={"domain":",".join(HOSTS),"probe_cc":cc,
          "test_name":"web_connectivity","since":since,"until":until,
          "axis_x":"domain","axis_y":"probe_asn"}
  try:
   response,url=request_json(params,attempts=5)
   byhost={h:{"n":0,"asns":set(),"a":0,"c":0,"f":0} for h in HOSTS}
   for row in rows_for_result(response):
    h=row.get("domain")
    if h not in byhost:raise ValueError("Returned unrequested host "+str(h))
    rec=byhost[h];n=int(row.get("measurement_count",0))
    if n<0:raise ValueError("Negative record count")
    rec["n"]+=n;asn=as_number(row.get("probe_asn"))
    if asn and n:rec["asns"].add(asn)
    rec["a"]+=int(row.get("anomaly_count",0))
    rec["c"]+=int(row.get("confirmed_count",0))
    rec["f"]+=int(row.get("failure_count",0))
   byentry=defaultdict(lambda:{"n":0,"asns":set(),"a":0,"c":0,"f":0})
   overall={"n":0,"asns":set(),"a":0,"c":0,"f":0}
   for h,d in byhost.items():
    e=entry_for(h)
    hosts.append({"country":cc,"since":since,"until_exclusive":until,
                  "hostname":h,"legal_entry":e,
                  "measurement_count":d["n"],"asn_list":";".join(sorted(d["asns"])),
                  "unique_asn_count":len(d["asns"])})
    for dest in (byentry[e],overall):
     for k in ("n","a","c","f"):dest[k]+=d[k]
     dest["asns"].update(d["asns"])
   for e in ENTRIES:
    d=byentry[e]
    entries.append({"country":cc,"since":since,"until_exclusive":until,
                  "days":days,"legal_entry":e,"measurement_count":d["n"],
                  "unique_asn_count":len(d["asns"]),
                  "asn_list":";".join(sorted(d["asns"])),
                  "anomaly_count":d["a"],"confirmed_count":d["c"],
                  "failure_count":d["f"],
                  "rate_per_day":round(d["n"]/days,6),
                  "source_query":url})
   blocks.append({"country":cc,"since":since,"until_exclusive":until,
                  "days":days,"measurement_count":overall["n"],
                  "unique_asn_count":len(overall["asns"]),
                  "asn_list":";".join(sorted(overall["asns"])),
                  "observed_entries":sum(byentry[e]["n"]>0 for e in ENTRIES),
                  "observed_hosts":sum(d["n"]>0 for d in byhost.values()),
                  "rate_per_day":round(overall["n"]/days,6),
                  "source_query":url})
   print("EU27_PERIOD",cc,since,"records",overall["n"],
         "ASNs",len(overall["asns"]),"entries",sum(byentry[e]["n"]>0 for e in ENTRIES),flush=True)
  except Exception as e:
   failures.append({"country":cc,"since":since,"until_exclusive":until,"error":str(e)})
   print("EU27_FAILED",cc,since,str(e)[:350],file=sys.stderr,flush=True)
  time.sleep(.4)
write_csv(OUT/"eu27_host_period.csv",hosts,
 ["country","since","until_exclusive","hostname","legal_entry",
  "measurement_count","asn_list","unique_asn_count"])
write_csv(OUT/"eu27_entity_period.csv",entries,
 ["country","since","until_exclusive","days","legal_entry","measurement_count",
  "unique_asn_count","asn_list","anomaly_count","confirmed_count",
  "failure_count","rate_per_day","source_query"])
write_csv(OUT/"eu27_country_period.csv",blocks,
 ["country","since","until_exclusive","days","measurement_count",
  "unique_asn_count","asn_list","observed_entries","observed_hosts",
  "rate_per_day","source_query"])
write_csv(OUT/"failed_queries.csv",failures,
 ["country","since","until_exclusive","error"])
totals=[]
for cc in EU27:
 rows=[r for r in blocks if r["country"]==cc]
 asns=set()
 for row in rows:asns.update(filter(None,row["asn_list"].split(";")))
 ent=set(r["legal_entry"] for r in entries if
       r["country"]==cc and r["measurement_count"]>0)
 totals.append({"country":cc,
  "measurement_count":sum(x["measurement_count"] for x in rows),
  "distinct_asns":len(asns),
  "asn_list":";".join(sorted(asns)),
  "observed_legal_entries":len(ent),
  "legal_entries":";".join(sorted(ent)),
  "positive_windows":sum(r["measurement_count"]>0 for r in rows),
  "complete_windows":len(rows),"expected_windows":len(PERIODS),
  "status":"complete" if len(rows)==len(PERIODS) else "incomplete"})
write_csv(OUT/"eu27_country_total.csv",totals,
 ["country","measurement_count","distinct_asns","asn_list",
  "observed_legal_entries","legal_entries","positive_windows",
  "complete_windows","expected_windows","status"])
manifest={"eu27":EU27,"fixed_hostname_count":len(HOSTS),
 "source":"OONI /api/v1/aggregation; web_connectivity; axis_x=domain; axis_y=probe_asn",
 "measurement_bounds":[PERIODS[0][0],PERIODS[-1][-1]],
 "as_of_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
 "successful_queries":len(blocks),"expected_queries":len(EU27)*len(PERIODS),
 "failed_queries":len(failures),"complete":not failures,
 "total_measured_records":sum(x["measurement_count"] for x in blocks),
 "interpretation":"Observations only, nonrandom OONI participants, no sanction compliance inferences; 42 fixed hosts not all conceivable aliases."}
(OUT/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
print("EU27_MEASUREMENT_COMPLETE",json.dumps({"manifest":manifest,"country_totals":totals}),flush=True)
if failures:sys.exit(2)
