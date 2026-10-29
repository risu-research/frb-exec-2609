#!/usr/bin/env python3
"""Read-only OONI metadata census for FOCI 2027's fixed 42-host EU27 cohort.
Queries only host-country-period cells with positive official aggregation counts.
No client probing and no published-paper modifications.
"""
import csv, datetime as dt, json, os, sys, time, random, urllib.parse, urllib.request, urllib.error, collections, pathlib

ROOT=pathlib.Path("reconstruct_out"); ROOT.mkdir(exist_ok=True)
SRC=pathlib.Path("prior/eu27_host_period.csv")
if not SRC.exists():
    raise FileNotFoundError("Missing prior positive-cell aggregate: "+str(SRC))
orig=list(csv.DictReader(SRC.open(encoding="utf8",newline="")))
tasks=[r for r in orig if int(r["measurement_count"])>0]
assert len(orig)==27*7*42,(len(orig),27*7*42)
assert sum(int(r["measurement_count"]) for r in tasks)==3319
HOSTS={r["hostname"] for r in orig}
mapping={r["hostname"]:r["legal_entry"] for r in orig}
user_agent="Academic OONI censored-media metadata audit/1.0 (research only)"
source_host="https://api.ooni.io"
BASE=source_host+"/api/v1/measurements"
rows=[]; progress=[]; failures=[]
global_seen=set()
def query(u,cell):
  errors=[]
  for attempt in range(7):
    try:
      req=urllib.request.Request(u,headers={"User-Agent":user_agent,"Accept":"application/json"})
      with urllib.request.urlopen(req,timeout=75) as rsp:
        data=json.load(rsp)
      if not isinstance(data,dict) or not isinstance(data.get("results"),list):
        raise ValueError("Unexpected API response")
      return data
    except Exception as exc:
      errors.append(str(exc)[:160])
      delay=min(45,2.5*(attempt+1)**1.5)+random.uniform(0,.9)
      print("RETRY",cell,attempt+1,str(exc)[:160],flush=True)
      time.sleep(delay)
  raise RuntimeError("Failed 7 tries: "+repr(errors))
for i,t in enumerate(tasks):
  cc=t["country"]; host=t["hostname"]; lo=t["since"]; hi=t["until_exclusive"]
  expect=int(t["measurement_count"])
  params={"domain":host,"probe_cc":cc,"test_name":"web_connectivity","since":lo,"until":hi,
          "limit":"100","order_by":"measurement_start_time","order":"asc"}
  offset=0; got=[];seen_urls=set()
  taskkey=f"{cc}:{host}:{lo}"
  try:
    while True:
      u=BASE+"?"+urllib.parse.urlencode({**params,"offset":str(offset)})
      if u in seen_urls:raise ValueError("Pagination loop")
      seen_urls.add(u)
      data=query(u,taskkey)
      found=data["results"]
      got.extend(found)
      if len(got)>expect+110:
        raise ValueError(f"Too many records {len(got)} vs expected {expect}")
      nxt=data.get("metadata",{}).get("next_url")
      if not nxt or len(found)<100:break
      offset+=len(found)
      if offset>=expect and len(got)>=expect:break
      time.sleep(.35)
    if len(got)!=expect:raise ValueError(f"Aggregation reconciliation failed got={len(got)} expected={expect}")
    for m in got:
      uid=m.get("measurement_uid")
      stamp=m.get("measurement_start_time")
      rawasn=str(m.get("probe_asn") or "")
      asn=rawasn if rawasn.startswith("AS") else ("AS"+rawasn if rawasn else "")
      if not uid or not stamp or not asn:raise ValueError("Missing uid/time/asn")
      actual=str(m.get("input") or "")
      actual_host=urllib.parse.urlsplit(actual).hostname
      if actual_host and actual_host.lower()!=host.lower():
        raise ValueError(f"Hostname mismatch selected={host} reported={actual_host}")
      dtv=dt.datetime.fromisoformat(stamp.replace("Z","+00:00"))
      if not (dt.date.fromisoformat(lo)<=dtv.date()<dt.date.fromisoformat(hi)):
        raise ValueError(f"Timestamp outside assigned reporting window: {stamp}")
      if uid in global_seen:raise ValueError("Duplicate measurement_uid across corpus "+str(uid))
      global_seen.add(uid)
      rows.append({"country":cc,"hostname":host,"legal_entry":mapping[host],"measurement_uid":uid,
        "report_id":m.get("report_id") or "","measurement_start_time":stamp,"probe_asn":asn,
        "input":actual,"anomaly":int(bool(m.get("anomaly"))),"confirmed":int(bool(m.get("confirmed"))),
        "failure":int(bool(m.get("failure"))),"period_since":lo,"period_until":hi})
    progress.append({"country":cc,"hostname":host,"period_since":lo,"period_until":hi,
       "expected":expect,"fetched":len(got),"status":"matched"})
    print("CELL",i+1,len(tasks),taskkey,"OK",len(got),"total",len(rows),flush=True)
  except Exception as exc:
    failures.append({"country":cc,"hostname":host,"period_since":lo,"expected":expect,
                      "found":len(got),"error":str(exc)})
    print("CELL_FAILED",taskkey,str(exc),flush=True)
  time.sleep(.6)
fields=["country","hostname","legal_entry","measurement_uid","report_id",
        "measurement_start_time","probe_asn","input","anomaly","confirmed","failure",
        "period_since","period_until"]
with (ROOT/"full_measurement_metadata.csv").open("w",encoding="utf8",newline="") as out:
  w=csv.DictWriter(out,fieldnames=fields);w.writeheader();w.writerows(rows)
for name,items in [("completed_cells.csv",progress),("failed_cells.csv",failures)]:
 with (ROOT/name).open("w",encoding="utf8",newline="") as out:
  keys=list(items[0]) if items else (["country","hostname","period_since","expected","found","error"] if "failed" in name else ["country","hostname","period_since","period_until","expected","fetched","status"])
  w=csv.DictWriter(out,fieldnames=keys);w.writeheader();w.writerows(items)
manifest={"source":"OONI /api/v1/measurements, time-specific metadata","requested_positive_host_country_period_cells":len(tasks),
 "matched_positive_cells":len(progress),"unmatched_cells":len(failures),
 "expected_measurements":3319,"downloaded_measurements":len(rows),
 "distinct_measurement_uid":len(global_seen),"complete":not failures and len(rows)==3319,
 "as_of_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
 "caution":"Report IDs, ASN and temporal proximity never uniquely establish devices, users or independent runs. No active probes performed."}
(ROOT/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf8")
print("FINAL",json.dumps(manifest),flush=True)
if not manifest["complete"]:sys.exit(2)
