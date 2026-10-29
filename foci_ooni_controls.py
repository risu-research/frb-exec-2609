#!/usr/bin/env python3
"""FOCI 2027 fixed-cohort test: 2025 sanctions vs RT/Sputnik vs prelisted news.

Uses official OONI /api/v1/aggregation. No ML, keys, scraping, or active probing.
Important: counts are OONI records from a nonrepresentative, voluntary network.
Zero is written only when an entire grouped query succeeds and validates.
"""
import csv
import datetime as dt
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from foci_ooni_count import API, CCS, PERIODS, request_json, rows_for_result, as_number, write_csv

PRIMARY={
 "new_2025": [
 ("EADaily","eadaily.com"),("Fondsk","fondsk.ru"),("Lenta","lenta.ru"),
 ("NewsFront","news-front.su"),("RuBaltic","www.rubaltic.ru"),
 ("SouthFront","southfront.press"),("Strategic Culture","strategic-culture.su"),
 ("Krasnaya Zvezda","tvzvezda.ru")],
 "old_2022": [
 ("RT","www.rt.com"),("Sputnik","sputniknews.com")],
 "non_sanctioned_news": [
 ("BBC","www.bbc.com"),("DW","www.dw.com"),("France 24","www.france24.com"),
 ("Al Jazeera","www.aljazeera.com"),("Reuters","www.reuters.com"),
 ("The Guardian","www.theguardian.com")],
}
# Prespecified ancillary controls, excluded from the three primary cohort metrics.
ANCILLARY={
 "old_alias_sensitivity":[("RT root","rt.com"),("Sputnik Globe","sputnikglobe.com")],
 "news_recent_list_additions":[("Euronews","www.euronews.com"),
                                ("NPR","www.npr.org")],
}
GROUPS={**PRIMARY,**ANCILLARY}
SITES=[(group,entity,host) for group,items in GROUPS.items() for entity,host in items]
HOSTS=[host for group,entity,host in SITES]
if len(HOSTS)!=len(set(HOSTS)):raise ValueError("Duplicate host")
HOST_INFO={host:(group,entity) for group,entity,host in SITES}

def metric():
 return {"measurements":0,"asns":set(),"anomaly":0,"confirmed":0,"failure":0}

def query_one(cc,lo,hi):
 params={"probe_cc":cc,"domain":",".join(HOSTS),
         "test_name":"web_connectivity","since":lo,"until":hi,
         "axis_x":"domain","axis_y":"probe_asn"}
 response,url=request_json(params,attempts=5)
 agg={host:metric() for host in HOSTS}
 for row in rows_for_result(response):
    host=row.get("domain")
    if host not in agg:
       raise ValueError("Unexpected domain: "+repr(host))
    n=int(row.get("measurement_count",0))
    if n<0:raise ValueError("Negative count")
    d=agg[host]
    d["measurements"]+=n
    asn=as_number(row.get("probe_asn"))
    if n and asn:d["asns"].add(asn)
    for src,dst in [("anomaly_count","anomaly"),("confirmed_count","confirmed"),("failure_count","failure")]:
       value=int(row.get(src,0))
       if value<0:raise ValueError("Negative "+src)
       d[dst]+=value
 return agg,url

def main():
 out=Path("foci_controls_results");out.mkdir(exist_ok=True)
 site_rows=[]
 group_rows=[]
 errors=[]
 for cc in CCS:
  for lo,hi in PERIODS:
   days=(dt.date.fromisoformat(hi)-dt.date.fromisoformat(lo)).days
   try:
    result,url=query_one(cc,lo,hi)
    for group,entity,host in SITES:
     r=result[host]
     site_rows.append({
       "country":cc,"since":lo,"until_exclusive":hi,"days":days,
       "cohort":group,"entity":entity,"hostname":host,
       "measurement_count":r["measurements"],
       "unique_asn_count":len(r["asns"]),
       "asn_ids":";".join(sorted(r["asns"])),
       "anomaly_count":r["anomaly"],
       "confirmed_count":r["confirmed"],"failure_count":r["failure"],
       "per_day":round(r["measurements"]/days,6),
       "source_query":url,"status":"complete"
     })
    for group,items in GROUPS.items():
     n=sum(result[h]["measurements"] for _,h in items)
     asns=set()
     for _,h in items:asns.update(result[h]["asns"])
     group_rows.append({
       "country":cc,"since":lo,"until_exclusive":hi,"days":days,
       "cohort":group,"entities":len(items),
       "entities_observed":sum(result[h]["measurements"]>0 for _,h in items),
       "measurement_count":n,"unique_asn_count":len(asns),
       "asn_ids":";".join(sorted(asns)),
       "mean_measurements_per_entity_day":round(n/(len(items)*days),7),
       "status":"complete"
     })
    print("COHORTS",cc,lo," ".join(
       g+":"+str(sum(result[h]["measurements"] for _,h in items))
       for g,items in GROUPS.items()),flush=True)
   except Exception as exc:
    errors.append({"country":cc,"since":lo,"until_exclusive":hi,"error":str(exc)})
    print("ERROR",cc,lo,str(exc)[:250],file=sys.stderr,flush=True)
   time.sleep(.45)
 site_cols=["country","since","until_exclusive","days","cohort","entity","hostname",
            "measurement_count","unique_asn_count","asn_ids","anomaly_count",
            "confirmed_count","failure_count","per_day","source_query","status"]
 group_cols=["country","since","until_exclusive","days","cohort","entities",
            "entities_observed","measurement_count","unique_asn_count","asn_ids",
            "mean_measurements_per_entity_day","status"]
 write_csv(out/"site_country_period.csv",site_rows,site_cols)
 write_csv(out/"cohort_country_period.csv",group_rows,group_cols)
 write_csv(out/"failed_queries.csv",errors,["country","since","until_exclusive","error"])

 # Full period unique ASN set is union, never sum the window ASN counts.
 entity_summary=[]
 for cc in CCS:
  for group,entities in GROUPS.items():
   for entity,host in entities:
    rr=[x for x in site_rows if (x["country"],x["cohort"],x["entity"])==(cc,group,entity)]
    asns=set()
    for x in rr:asns.update(filter(None,x["asn_ids"].split(";")))
    entity_summary.append({
      "country":cc,"cohort":group,"entity":entity,"hostname":host,
      "measurement_count":sum(x["measurement_count"] for x in rr),
      "unique_asn_count":len(asns),"asn_ids":";".join(sorted(asns)),
      "positive_windows":sum(x["measurement_count"]>0 for x in rr),
      "complete_windows":len(rr),"expected_windows":len(PERIODS),
      "total_days":sum(x["days"] for x in rr),
      "status":"complete" if len(rr)==len(PERIODS) else "incomplete"
    })
 write_csv(out/"site_country_full_period.csv",entity_summary,
 ["country","cohort","entity","hostname","measurement_count","unique_asn_count",
  "asn_ids","positive_windows","complete_windows","expected_windows","total_days","status"])

 country_group=[]
 for cc in CCS:
  for group,entities in GROUPS.items():
    subset=[x for x in entity_summary if x["country"]==cc and x["cohort"]==group]
    n=sum(x["measurement_count"] for x in subset)
    asns=set()
    for x in subset:asns.update(filter(None,x["asn_ids"].split(";")))
    complete=all(x["status"]=="complete" for x in subset)
    days=sum(x["total_days"] for x in subset)//len(subset) if complete else None
    country_group.append({
     "country":cc,"cohort":group,"entities":len(entities),
     "measured_entities":sum(x["measurement_count"]>0 for x in subset),
     "measured_entity_windows":sum(x["positive_windows"] for x in subset),
     "possible_entity_windows":len(entities)*len(PERIODS),
     "measurement_count":n,"unique_asn_count":len(asns),
     "asn_ids":";".join(sorted(asns)),
     "per_entity_day":round(n/(len(entities)*days),6) if complete else "",
     "status":"complete" if complete else "incomplete"})
 write_csv(out/"cohort_country_full_period.csv",country_group,
  ["country","cohort","entities","measured_entities","measured_entity_windows",
   "possible_entity_windows","measurement_count","unique_asn_count",
   "asn_ids","per_entity_day","status"])

 # Country-time matched exposure: compare each site against a control median in
 # the same country/window, including control-site zeros. Descriptive only.
 matched=[]
 by=(lambda group,cc,lo:[x for x in site_rows if x["cohort"]==group and
                            x["country"]==cc and x["since"]==lo])
 for cc in CCS:
  for lo,hi in PERIODS:
   controls=by("non_sanctioned_news",cc,lo)
   if len(controls)!=len(PRIMARY["non_sanctioned_news"]):continue
   median=statistics.median(x["measurement_count"] for x in controls)
   for group in ("new_2025","old_2022"):
    for x in by(group,cc,lo):
     matched.append({
       "country":cc,"since":lo,"until_exclusive":hi,"cohort":group,
       "entity":x["entity"],"measurement_count":x["measurement_count"],
       "control_median_measurements":median,
       "site_to_control_median_ratio":round(x["measurement_count"]/median,6)
           if median>0 else "",
       "ratio_defined":int(median>0),
       "note":"Descriptive non-equivalent sites: no sanction-causality claim"})
 write_csv(out/"matched_site_control_medians.csv",matched,
  ["country","since","until_exclusive","cohort","entity","measurement_count",
   "control_median_measurements","site_to_control_median_ratio","ratio_defined","note"])

 manifest={"analysis":"FOCI 2027 locked comparison",
   "date_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"countries":CCS,
   "periods":PERIODS,"cohorts":{g:sites for g,sites in GROUPS.items()},
   "original_cohort_source":"FOCI 2027 OONI count verified 2026-10-29, 2025-05-14 report",
   "control_selection":"Non-sanctioned outlets in the global Citizen Lab NEWS list as of 2025-04-07; first six fixed before outcome retrieval.",
   "pre_2025_global_snapshot":"74c65f0cb00db78525404c01269cc2a65e7addcc",
   "measurement_type":"web_connectivity",
   "query_status":"complete" if not errors else "incomplete",
   "successful_queries":42-len(errors),"failed_queries":len(errors),
   "guardrails":["Each hostname query returns its own exact OONI indexed domain",
                 "No zero imputation when a query fails",
                 "OONI records are nonrandom, sample-dependent",
                 "Selected controls are not matched on all non-policy characteristics",
                 "ASN counts use unions across hosts and periods",
                 "Anomaly is not confirmed censorship",
                 "Mixed date window lengths; per-day and per-entity-day also provided",
                 "Cohort coverage depends on fixed alias scope; inspect sensitivity"] }
 (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
 print("FINAL",json.dumps({"successful_queries":42-len(errors),"errors":errors,
          "totals":country_group}),flush=True)
 if errors:sys.exit(2)

if __name__=="__main__":main()
