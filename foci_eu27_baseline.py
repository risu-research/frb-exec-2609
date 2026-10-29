#!/usr/bin/env python3
"""FOCI 2027 EU27 baseline: were established global-news targets measured?

Seven grouped official OONI aggregations; no active probing, no credentials.
Controls pre-specified in earlier matched cohorts.
Count any news measurement in each EU country/window, compare to bounded
2025 legal-target observability, but DO NOT infer absence of blocking.
"""
import json, csv, sys, time, datetime as dt
from collections import defaultdict
from pathlib import Path
from foci_ooni_count import request_json, rows_for_result, PERIODS
CC=["AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR",
    "HU","IE","IT","LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"]
CTRL=["www.bbc.com","www.dw.com","www.france24.com","www.aljazeera.com",
      "www.reuters.com","www.theguardian.com"]
OUT=Path("foci_eu27_baseline_results");OUT.mkdir(exist_ok=True)
rows=[];problems=[]
for since,until in PERIODS:
 params={"probe_cc":",".join(CC),"domain":",".join(CTRL),
         "test_name":"web_connectivity","since":since,"until":until,
         "axis_x":"probe_cc","axis_y":"domain"}
 try:
  response,uri=request_json(params,attempts=5)
  by={(cc,h):0 for cc in CC for h in CTRL}
  for r in rows_for_result(response):
   cc=r.get("probe_cc");h=r.get("domain")
   if (cc,h) not in by:raise ValueError("Unexpected country or host "+str((cc,h)))
   by[(cc,h)]+=int(r.get("measurement_count",0))
  for cc in CC:
   counts=[by[(cc,h)] for h in CTRL]
   rows.append({"country":cc,"since":since,"until_exclusive":until,
                "six_control_measurements":sum(counts),
                "number_of_control_sites_observed":sum(n>0 for n in counts),
                "all_six_control_sites_observed":int(all(n>0 for n in counts)),
                "at_least_one_control_observed":int(any(n>0 for n in counts)),
                "source_query":uri})
  print("BASELINE_PERIOD",since,"countries_observing_controls",
        sum(sum(by[(cc,h)] for h in CTRL)>0 for cc in CC),
        "total_measurements",sum(by.values()),flush=True)
 except Exception as exc:
  problems.append({"since":since,"until":until,"error":str(exc)})
  print("BASELINE_FAILED",since,str(exc),file=sys.stderr,flush=True)
 time.sleep(.6)
with (OUT/"eu27_baseline_country_period.csv").open("w",newline="",encoding="utf-8") as f:
 fields=["country","since","until_exclusive","six_control_measurements",
         "number_of_control_sites_observed","all_six_control_sites_observed",
         "at_least_one_control_observed","source_query"]
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
summ=[]
for cc in CC:
 d=[r for r in rows if r["country"]==cc]
 summ.append({"country":cc,"six_news_measurements":sum(x["six_control_measurements"] for x in d),
              "positive_periods":sum(x["at_least_one_control_observed"] for x in d),
              "all_six_positive_periods":sum(x["all_six_control_sites_observed"] for x in d),
              "complete_periods":len(d),"status":"complete" if len(d)==len(PERIODS) else "incomplete"})
with (OUT/"eu27_baseline_country_summary.csv").open("w",newline="",encoding="utf-8") as f:
 fields=list(summ[0]);w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(summ)
(OUT/"manifest.json").write_text(json.dumps({"countries":CC,"controls":CTRL,
 "periods":PERIODS,"completed_requests":len(PERIODS)-len(problems),
 "failed_requests":problems,"as_of_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
 "caveat":"News-site measurements are a reference for OONI activity; not matched on clients, consent, time-of-day, or all site features."},indent=2)+"\n")
print("BASELINE_FINAL",json.dumps({"n_failures":len(problems),"summaries":summ}),flush=True)
if problems:sys.exit(2)
