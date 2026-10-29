#!/usr/bin/env python3
"""FOCI 2027 alias-sensitive historical observability audit.

Adds www variants and names directly observed in the matched 2025-05-14
49-URL OONI reports to the 13 officially documented roots.
This is a bounded address corpus, NOT an exhaustive universe of possible aliases.
"""
import argparse, json, sys, time
from collections import defaultdict
from pathlib import Path
from foci_ooni_count import (API, CCS, DOMAINS, PERIODS, request_json,
                             rows_for_result, as_number, write_csv)

ROOT_TO_ENTRY = {
    "eadaily.com":"EADaily", "fondsk.ru":"Fondsk", "lenta.ru":"Lenta",
    "news-front.info":"NewsFront", "news-front.su":"NewsFront",
    "rubaltic.ru":"RuBaltic", "southfront.press":"SouthFront",
    "strategic-culture.org":"Strategic Culture", "strategic-culture.su":"Strategic Culture",
    "tvzvezda.ru":"Krasnaya Zvezda", "redstar.ru":"Krasnaya Zvezda",
    "radiozvezda.ru":"Krasnaya Zvezda", "zvezdaweekly.ru":"Krasnaya Zvezda",
}
# Fixed from the 49-URL report pair, 2025-05-14, not heuristic discovery.
OBSERVED_EXTRA_HOSTS = [
    "de.southfront.press",
    "by.rubaltic.ru", "lt.rubaltic.ru", "lv.rubaltic.ru",
    "pl.rubaltic.ru", "www.rubaltic.ru",
    "bgr.news-front.su", "de.news-front.su",
    "en.news-front.su", "es.news-front.su", "fr.news-front.su",
    "ge.news-front.su", "hu.news-front.su", "id.news-front.su",
    "pl.news-front.su", "sk.news-front.su", "srb.news-front.su",
]
HOSTS = sorted(set(DOMAINS + ["www."+d for d in DOMAINS] + OBSERVED_EXTRA_HOSTS))
ENTRIES=sorted(set(ROOT_TO_ENTRY.values()))

def entry_for(host):
    roots=[root for root in ROOT_TO_ENTRY if host==root or host.endswith("."+root)]
    if len(roots) != 1: raise ValueError("Unmapped or ambiguous hostname "+host)
    return ROOT_TO_ENTRY[roots[0]]

def run(out, mode):
    periods=PERIODS if mode=="full" else [PERIODS[0],PERIODS[-1]]
    hostrows, entryrows, errors=[],[],[]
    for cc in CCS:
        for since,until in periods:
            params={"domain":",".join(HOSTS),"probe_cc":cc,"test_name":"web_connectivity",
                    "since":since,"until":until,"axis_x":"domain","axis_y":"probe_asn"}
            try:
                body,url=request_json(params)
                byhost=defaultdict(lambda:{"n":0,"a":set(),"an":0,"conf":0,"fail":0})
                for q in rows_for_result(body):
                    h=q.get("domain")
                    if h not in HOSTS: raise ValueError("Unexpected hostname "+str(h))
                    n=int(q.get("measurement_count",0))
                    byhost[h]["n"]+=n
                    asn=as_number(q.get("probe_asn"))
                    if asn and n: byhost[h]["a"].add(asn)
                    byhost[h]["an"]+=int(q.get("anomaly_count",0))
                    byhost[h]["conf"]+=int(q.get("confirmed_count",0))
                    byhost[h]["fail"]+=int(q.get("failure_count",0))
                byentry=defaultdict(lambda:{"n":0,"a":set(),"an":0,"conf":0,"fail":0})
                for host in HOSTS:
                    z=byhost[host];e=entry_for(host)
                    hostrows.append({"country":cc,"host":host,"legal_entry":e,
                                    "since":since,"until":until,
                                    "measurement_count":z["n"],
                                    "unique_asn_count":len(z["a"]),
                                    "asn_list":";".join(sorted(z["a"])),
                                    "anomaly_count":z["an"],"confirmed_count":z["conf"],
                                    "failure_count":z["fail"],"source_query":url})
                    dest=byentry[e]
                    for k in ("n","an","conf","fail"):dest[k]+=z[k]
                    dest["a"].update(z["a"])
                for e in ENTRIES:
                    z=byentry[e]
                    entryrows.append({"country":cc,"legal_entry":e,
                                      "since":since,"until":until,
                                      "measurement_count":z["n"],
                                      "unique_asn_count":len(z["a"]),
                                      "asn_list":";".join(sorted(z["a"])),
                                      "anomaly_count":z["an"],"confirmed_count":z["conf"],
                                      "failure_count":z["fail"],"source_query":url})
                print("ALIAS",cc,since,"total",sum(x["n"] for x in byentry.values()),
                      "legal_entries_seen",sum(x["n"]>0 for x in byentry.values()),flush=True)
            except Exception as exc:
                errors.append({"country":cc,"since":since,"until":until,"error":str(exc)})
                print("FAILED",cc,since,str(exc)[:240],file=sys.stderr,flush=True)
            time.sleep(.5)
    write_csv(out/"alias_host_country_period_counts.csv",hostrows,
              ["country","host","legal_entry","since","until","measurement_count",
               "unique_asn_count","asn_list","anomaly_count","confirmed_count",
               "failure_count","source_query"])
    write_csv(out/"legal_entry_country_period_counts.csv",entryrows,
              ["country","legal_entry","since","until","measurement_count",
               "unique_asn_count","asn_list","anomaly_count","confirmed_count",
               "failure_count","source_query"])
    summary=[]
    bykey=defaultdict(list)
    for r in entryrows: bykey[(r["country"],r["legal_entry"])].append(r)
    for cc in CCS:
        for e in ENTRIES:
            rows=bykey[(cc,e)]
            asns=set(";".join(r["asn_list"] for r in rows).split(";"))-{""}
            summary.append({"country":cc,"legal_entry":e,
                "measurement_count":sum(r["measurement_count"] for r in rows),
                "unique_asn_count":len(asns),"asn_list":";".join(sorted(asns)),
                "complete_periods":len(rows),"expected_periods":len(periods),
                "status":"complete" if len(rows)==len(periods) else "incomplete"})
    write_csv(out/"legal_entry_country_full_summary.csv",summary,
              ["country","legal_entry","measurement_count","unique_asn_count",
               "asn_list","complete_periods","expected_periods","status"])
    write_csv(out/"alias_failed_queries.csv",errors,["country","since","until","error"])
    manifest={"mode":mode,"periods":periods,"official_roots":len(DOMAINS),
              "alias_hosts_including_roots":len(HOSTS),"countries":CCS,
              "complete_queries":len(entryrows)//len(ENTRIES),"failed_queries":len(errors),
              "complete":not errors,"method":"fixed 13 official roots + 13 www variants + 17 observed report subdomains",
              "limit":"Bounded address-set sensitivity; not all possible historical or future domains."}
    (out/"alias_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("ALIAS_FINAL",json.dumps(manifest),flush=True)
    if errors:sys.exit(2)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=["quick","full"],default="full")
    p.add_argument("--output",default="alias_results")
    a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    run(out,a.mode)
