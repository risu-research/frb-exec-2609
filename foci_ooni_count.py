#!/usr/bin/env python3
"""FOCI 2027: OONI sanctioned-media measurement counts and unique probe ASNs.

Read-only, no credentials. Official OONI /api/v1/aggregation API.
A successful empty result = zero; a failed call = missing, never zero.
This is historical OONI coverage, not the prevalence of network blocking.
"""
import argparse
import csv
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

API = "https://api.ooni.io/api/v1/aggregation"
CCS = ["DE", "FR", "PL", "IT", "CZ", "SK"]
DOMAINS = ["eadaily.com","fondsk.ru","lenta.ru","news-front.info","news-front.su",
           "rubaltic.ru","southfront.press","strategic-culture.org",
           "strategic-culture.su","tvzvezda.ru","redstar.ru","radiozvezda.ru",
           "zvezdaweekly.ru"]
EXACT_EIGHT = {
    "EADaily": "https://eadaily.com/",
    "Fondsk": "https://fondsk.ru/",
    "Lenta": "https://lenta.ru/",
    "NewsFront": "https://news-front.su/",
    "RuBaltic": "https://www.rubaltic.ru/",
    "SouthFront": "https://southfront.press/",
    "Strategic Culture": "https://strategic-culture.su/",
    "Krasnaya Zvezda": "https://tvzvezda.ru/",
}
PERIODS = [
    ("2025-04-09", "2025-07-09"),
    ("2025-07-09", "2025-10-09"),
    ("2025-10-09", "2026-01-09"),
    ("2026-01-09", "2026-04-09"),
    ("2026-04-09", "2026-07-09"),
    ("2026-07-09", "2026-09-30"),
    ("2026-09-30", "2026-10-30"),
]

def request_json(params, attempts=4):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "RISU-FOCI-2027-public-data-research/1.0 (moderate-rate)",
        "Accept": "application/json"
    })
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=65) as f:
                result = json.load(f)
            if not isinstance(result, dict) or not isinstance(result.get("result"), (list, dict)):
                raise ValueError("Unexpected API response: " + str(result)[:260])
            return result, url
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last = str(exc)
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 401, 403, 404):
                break
            time.sleep(min(25, 2 ** attempt * 2))
    raise RuntimeError("Aggregation query failed: " + url + " ; " + str(last))

def as_number(s):
    s = str(s).strip().upper()
    if s.startswith("AS"):
        s = s[2:]
    return "AS" + s if s.isdigit() and int(s) > 0 else None

def rows_for_result(body):
    data = body["result"]
    if isinstance(data, dict):
        return [data]
    return data

def write_csv(path, rows, names):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=names, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def run(out, mode):
    periods = PERIODS if mode == "full" else [PERIODS[0], PERIODS[-1]]
    all_aggregates, exact_aggregates, problems = [], [], []
    # Only one request at a time. 6 countries x 7 windows = 42 grouped queries.
    for cc in CCS:
        for since, until in periods:
            params = {"probe_cc": cc, "domain": ",".join(DOMAINS),
                      "test_name": "web_connectivity", "since": since,
                      "until": until, "axis_x": "domain", "axis_y": "probe_asn"}
            try:
                body, url = request_json(params)
                rows = rows_for_result(body)
                seen = defaultdict(lambda: {"count": 0, "asns": set(), "anomalies": 0,
                                            "confirmed": 0, "failures": 0})
                for item in rows:
                    domain = item.get("domain")
                    if domain not in DOMAINS:
                        raise ValueError("Unexpected domain " + repr(domain))
                    n = int(item.get("measurement_count", 0))
                    if n < 0:
                        raise ValueError("Negative count")
                    seen[domain]["count"] += n
                    asn = as_number(item.get("probe_asn"))
                    if asn and n:
                        seen[domain]["asns"].add(asn)
                    seen[domain]["anomalies"] += int(item.get("anomaly_count", 0))
                    seen[domain]["confirmed"] += int(item.get("confirmed_count", 0))
                    seen[domain]["failures"] += int(item.get("failure_count", 0))
                for domain in DOMAINS:
                    a = seen[domain]
                    all_aggregates.append({
                        "country": cc, "domain": domain, "since": since, "until": until,
                        "measurement_count": a["count"], "unique_asn_count": len(a["asns"]),
                        "asn_list": ";".join(sorted(a["asns"])),
                        "anomaly_count": a["anomalies"], "confirmed_count": a["confirmed"],
                        "failure_count": a["failures"], "status": "complete",
                        "source_query": url
                    })
                print("DOMAIN",cc,since,"measures",sum(x["count"] for x in seen.values()),
                      "nonempty_domains",sum(bool(x["count"]) for x in seen.values()),flush=True)
            except Exception as e:
                problems.append({"stage":"domain_group","country":cc,"since":since,
                                 "until":until,"domain_or_url":"ALL_13","error":str(e)})
                print("FAILED DOMAIN",cc,since,str(e)[:180],file=sys.stderr,flush=True)
            time.sleep(0.55)

    # Independent exact-URL query: protects against domain-vs-www/subdomain ambiguity.
    # In Germany this checks the identical 8 targets of the paired 2025-05-14 sessions.
    for name, urlval in EXACT_EIGHT.items():
        for since, until in periods:
            params = {"probe_cc": "DE", "input": urlval,
                      "test_name": "web_connectivity", "since": since,
                      "until": until, "axis_x": "probe_asn"}
            try:
                body, url = request_json(params)
                rows = rows_for_result(body)
                n = 0; asns = set(); anomalies = 0; confirmed = 0; failures = 0
                for item in rows:
                    k = int(item.get("measurement_count", 0))
                    n += k
                    asn = as_number(item.get("probe_asn"))
                    if asn and k: asns.add(asn)
                    anomalies += int(item.get("anomaly_count", 0))
                    confirmed += int(item.get("confirmed_count", 0))
                    failures += int(item.get("failure_count", 0))
                exact_aggregates.append({
                    "legal_entry":name,"country":"DE","input":urlval,"since":since,"until":until,
                    "measurement_count":n,"unique_asn_count":len(asns),
                    "asn_list":";".join(sorted(asns)),
                    "anomaly_count":anomalies,"confirmed_count":confirmed,
                    "failure_count":failures,"status":"complete","source_query":url
                })
                print("EXACT",name,since,"count",n,"ASN",len(asns),flush=True)
            except Exception as e:
                problems.append({"stage":"exact_input","country":"DE","since":since,
                                 "until":until,"domain_or_url":urlval,"error":str(e)})
                print("FAILED INPUT",name,since,str(e)[:180],file=sys.stderr,flush=True)
            time.sleep(0.55)

    cols = ["country","domain","since","until","measurement_count","unique_asn_count",
            "asn_list","anomaly_count","confirmed_count","failure_count","status","source_query"]
    write_csv(out/"domain_country_period_counts.csv",all_aggregates,cols)
    write_csv(out/"exact_eight_de_period_counts.csv",exact_aggregates,
              ["legal_entry","country","input","since","until","measurement_count",
               "unique_asn_count","asn_list","anomaly_count","confirmed_count",
               "failure_count","status","source_query"])
    write_csv(out/"failed_queries.csv",problems,["stage","country","since","until","domain_or_url","error"])
    by_group = defaultdict(lambda:{"count":0,"asns":set(),"anomalies":0,"confirmed":0,"failures":0,"periods":0})
    for r in all_aggregates:
        k=(r["country"],r["domain"])
        d=by_group[k]
        d["count"]+=r["measurement_count"]
        d["asns"].update(filter(None,r["asn_list"].split(";")))
        d["anomalies"]+=r["anomaly_count"]
        d["confirmed"]+=r["confirmed_count"]
        d["failures"]+=r["failure_count"]
        d["periods"]+=1
    summaries=[]
    for cc in CCS:
        for domain in DOMAINS:
            d=by_group[(cc,domain)]
            summaries.append({"country":cc,"domain":domain,"measurement_count":d["count"],
                              "unique_asn_count":len(d["asns"]), "asn_list":";".join(sorted(d["asns"])),
                              "anomaly_count":d["anomalies"],"confirmed_count":d["confirmed"],
                              "failure_count":d["failures"],"complete_periods":d["periods"],
                              "expected_periods":len(periods),
                              "status":"complete" if d["periods"]==len(periods) else "incomplete"})
    write_csv(out/"domain_country_full_period_summary.csv",summaries,
              ["country","domain","measurement_count","unique_asn_count","asn_list",
               "anomaly_count","confirmed_count","failure_count","complete_periods","expected_periods","status"])
    manifest={"as_of_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"mode":mode,
              "periods":periods,"n_completed_domain_queries":len(all_aggregates)//len(DOMAINS),
              "n_completed_exact_queries":len(exact_aggregates),
              "n_failures":len(problems),
              "complete":len(problems)==0,
              "warning":"OONI measurements are convenience samples; anomalies are not confirmed blocking. Domains are exact OONI indexed domains; exact URL series is separate. Partial totals are not final zeros."}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print("FINAL_MANIFEST",json.dumps(manifest),flush=True)
    if problems:
        sys.exit(2)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=["quick","full"],default="quick")
    p.add_argument("--output",default="out")
    a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    run(out,a.mode)
