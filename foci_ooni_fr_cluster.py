#!/usr/bin/env python3
"""Independent OONI metadata inspection of the 2026 FR 9 x 10 observation cluster."""
import csv, json, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

TARGETS = ["eadaily.com","fondsk.ru","lenta.ru","news-front.su",
           "rubaltic.ru","southfront.press","strategic-culture.su",
           "tvzvezda.ru","redstar.ru"]
OUT=Path("foci_fr_cluster_results");OUT.mkdir(exist_ok=True)
records=[]
for domain in TARGETS:
    q=urllib.parse.urlencode({"domain":domain,"probe_cc":"FR",
                               "test_name":"web_connectivity",
                               "since":"2026-07-09","until":"2026-09-30",
                               "limit":100})
    u="https://api.ooni.io/api/v1/measurements?"+q
    req=urllib.request.Request(u,headers={"User-Agent":"RISU-FOCI-2027-readonly/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=75) as r: j=json.load(r)
    if not isinstance(j.get("results"),list): raise ValueError("bad results")
    if j["metadata"].get("next_url"):raise ValueError("pagination required "+domain)
    if len(j["results"])!=10:raise ValueError(f"aggregate mismatch {domain}: {len(j['results'])}")
    for m in j["results"]:
        records.append({"query_domain":domain,"input":m.get("input"),"report_id":m.get("report_id"),
                        "measurement_uid":m.get("measurement_uid"),"probe_asn":m.get("probe_asn"),
                        "measurement_start_time":m.get("measurement_start_time"),
                        "anomaly":int(bool(m.get("anomaly"))),"confirmed":int(bool(m.get("confirmed")))})
    print("DOMAIN",domain,"count",len(j["results"]),flush=True)
    time.sleep(.5)
with (OUT/"fr_2026Q3_90_measurements.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
report_map=defaultdict(set)
asn_map=defaultdict(set)
for x in records:
    report_map[x["report_id"]].add(x["query_domain"])
    asn_map[x["probe_asn"]].add(x["query_domain"])
summary={"rows":len(records),"unique_uids":len(set(x["measurement_uid"] for x in records)),
         "unique_reports":len(report_map),
         "unique_asns":len(asn_map),
         "report_id_distribution":{k:{"count":sum(x["report_id"]==k for x in records),"n_domains":len(v)}
                                    for k,v in report_map.items()},
         "asn_distribution":{k:{"count":sum(x["probe_asn"]==k for x in records),"n_domains":len(v)}
                             for k,v in asn_map.items()},
         "date_min":min(x["measurement_start_time"] for x in records),
         "date_max":max(x["measurement_start_time"] for x in records)}
(OUT/"fr_cluster_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
print("FR_CLUSTER_SUMMARY",json.dumps(summary),flush=True)
