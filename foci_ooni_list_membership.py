#!/usr/bin/env python3
"""Pinned Citizen Lab seven-list membership comparison, 2025 vs 2026.
Includes pre-specified controls and independent unlisted negative controls.
"""
import csv,io,json,time,urllib.request,datetime as dt
from pathlib import Path
from foci_ooni_controls import PRIMARY,ANCILLARY

UNLISTED=[
 ("Novaya Gazeta Europe","novayagazeta.eu"),("The Moscow Times","themoscowtimes.com"),
 ("RBC","rbc.ru"),("Mediazona","zona.media"),("The Bell","thebell.io"),
 ("TV Rain","tvrain.tv"),("Fontanka","fontanka.ru"),("iStories","istories.media")]
COHORTS={**PRIMARY,**ANCILLARY,"unlisted_non_sanctioned_news":UNLISTED}
SNAPS={
 "before_2025_application":"74c65f0cb00db78525404c01269cc2a65e7addcc",
 "current_2026_10_29":"05977348d780f193c5ed35618aba8c7061daa61f"
}
LISTS=["global","de","fr","pl","it","cz","sk"]
OUT=Path("foci_testlist_results");OUT.mkdir(exist_ok=True)
def query(url):
 req=urllib.request.Request(url,headers={"User-Agent":"RISU-FOCI-2027-archival-research/1.0"})
 for k in range(4):
  try:
   with urllib.request.urlopen(req,timeout=45) as resp:
    return resp.read().decode("utf-8-sig")
  except Exception as err:
   if k==3:raise
   time.sleep(2*(k+1))
def hostname(url):
 u=url.strip().lower()
 if "://" not in u:return ""
 return u.split("://",1)[1].split("/",1)[0].split(":",1)[0]
all_rows=[]
for snap,sha in SNAPS.items():
 for listname in LISTS:
  url="https://raw.githubusercontent.com/citizenlab/test-lists/"+sha+"/lists/"+listname+".csv"
  raw=query(url)
  reader=list(csv.DictReader(io.StringIO(raw)))
  for g,items in COHORTS.items():
   for name,host in items:
    h=host.removeprefix("www.")
    found=[]
    for row in reader:
     urlhost=hostname(row["url"]);normal=urlhost.removeprefix("www.")
     if normal==h or normal.endswith("."+h):
      found.append(row)
    all_rows.append({
      "snapshot":snap,"sha":sha,"list":listname,"cohort":g,
      "entity":name,"query_host":host,"matching_urls_count":len(found),
      "matching_urls":";".join(x["url"] for x in found),
      "date_added":";".join(x.get("date_added","") for x in found),
      "category_codes":";".join(x.get("category_code","") for x in found),
      "source":url})
  print("TESTLIST",snap,listname,"entries",len(reader),flush=True)
with (OUT/"testlist_membership_7x2_snapshots.csv").open("w",newline="",encoding="utf-8") as f:
 w=csv.DictWriter(f,fieldnames=list(all_rows[0]));w.writeheader();w.writerows(all_rows)
checks={}
for snap in SNAPS:
 checks[snap]={}
 for g,items in COHORTS.items():
  have=sorted(set(r["query_host"] for r in all_rows if r["snapshot"]==snap and r["cohort"]==g and r["matching_urls_count"]>0))
  checks[snap][g]={"matched_sites":len(have),"total_sites":len(items),"sites":have}
(O/"testlist_summary.json").write_text(json.dumps({
 "source_shas":SNAPS,"compared_lists":LISTS,"classification":checks,
 "as_of_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
 "note":"Only global plus six chosen country lists; no assertion about all countries, private probes, or all aliases."},indent=2)+"\n")
print("LIST_SNAPSHOT_CHECK",json.dumps(checks),flush=True)
