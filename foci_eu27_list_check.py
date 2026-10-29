#!/usr/bin/env python3
"""FOCI 2027: EU27 official-source URL observability input audit.

Independently tests all 27 EU member-specific Citizen Lab and OONI fork
test-list snapshots plus global. Read-only; no claims about OONI client fetch.
"""
import csv,io,json,time,urllib.request,urllib.error,datetime as dt
from pathlib import Path

CODES=["at","be","bg","hr","cy","cz","dk","ee","fi","fr","de","gr",
       "hu","ie","it","lv","lt","lu","mt","nl","pl","pt","ro","sk",
       "si","es","se"]
ROOTS={
 "EADaily":["eadaily.com"],"Fondsk":["fondsk.ru"],"Lenta":["lenta.ru"],
 "NewsFront":["news-front.info","news-front.su"],"RuBaltic":["rubaltic.ru"],
 "SouthFront":["southfront.press"],
 "Strategic Culture":["strategic-culture.org","strategic-culture.su"],
 "Krasnaya Zvezda":["tvzvezda.ru","redstar.ru","radiozvezda.ru","zvezdaweekly.ru"]
}
SHAS={"pre_2025_04_09":"74c65f0cb00db78525404c01269cc2a65e7addcc",
      "current_2026_10_29":"master"}
REPOS=["citizenlab/test-lists","ooni/test-lists"]
OUT=Path("foci_eu27_lists");OUT.mkdir(exist_ok=True)
def request(url):
 req=urllib.request.Request(url,headers={"User-Agent":"RISU-FOCI-2027-EU27/1.0"})
 last=None
 for i in range(4):
  try:
   with urllib.request.urlopen(req,timeout=45) as s:return s.read().decode("utf-8-sig")
  except urllib.error.HTTPError as ex:
   if ex.code==404:return None
   last=ex
  except Exception as ex:last=ex
  time.sleep(min(8,2**i))
 raise RuntimeError(str(last))
def host(url):
 try:
  return url.lower().strip().split("://",1)[1].split("/",1)[0].split(":",1)[0].removeprefix("www.")
 except: return ""
rows=[];errors=[]
for repo in REPOS:
 for snapshot,ref in SHAS.items():
  for cc in ["global"]+CODES:
   uri=f"https://raw.githubusercontent.com/{repo}/{ref}/lists/{cc}.csv"
   try:
    data=request(uri)
    parsed=list(csv.DictReader(io.StringIO(data))) if data is not None else []
    for ent,roots in ROOTS.items():
     matches=[]
     for v in parsed:
      h=host(v.get("url",""))
      if any(h==root or h.endswith("."+root) for root in roots):
       matches.append(v["url"])
     rows.append({"repository":repo,"snapshot":snapshot,"list":cc,
                 "country_specific_list_exists":int(data is not None),
                 "legal_entry":ent,"match_count":len(matches),
                 "matched_urls":";".join(sorted(set(matches))),
                 "source_uri":uri})
    if cc in ("global","de","pl"):print("SAMPLE",repo,snapshot,cc,
      "matches",sum(x["match_count"] for x in rows if
       x["repository"]==repo and x["snapshot"]==snapshot and x["list"]==cc),flush=True)
   except Exception as ex:
    errors.append({"repository":repo,"snapshot":snapshot,"list":cc,"error":str(ex)})
    print("FAILED",repo,snapshot,cc,str(ex)[:250],flush=True)
   time.sleep(.10)

with (OUT/"eu27_membership.csv").open("w",newline="",encoding="utf8") as f:
 fields=list(rows[0]);w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
with (OUT/"failed.csv").open("w",newline="",encoding="utf8") as f:
 w=csv.DictWriter(f,fieldnames=["repository","snapshot","list","error"])
 w.writeheader();w.writerows(errors)
summary=[]
for repo in REPOS:
 for snapshot in SHAS:
  for entity in ROOTS:
   m=[r for r in rows if r["repository"]==repo and r["snapshot"]==snapshot and r["legal_entry"]==entity]
   country_matches=sorted(r["list"] for r in m if r["match_count"]>0 and r["list"]!="global")
   global_match=int(any(r["match_count"]>0 for r in m if r["list"]=="global"))
   summary.append({"repository":repo,"snapshot":snapshot,"entity":entity,
                   "global_registered":global_match,"member_state_lists":len(country_matches),
                   "country_codes":";".join(country_matches),
                   "total_matched_urls":sum(r["match_count"] for r in m),
                   "missing_country_lists":";".join(sorted(r["list"] for r in m if not r["country_specific_list_exists"] and r["list"]!="global"))})
with (OUT/"eu27_entity_summary.csv").open("w",newline="",encoding="utf8") as f:
 fields=list(summary[0]);w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(summary)
manifest={"european_union_member_states":CODES,"original_roots":ROOTS,
 "repositories":REPOS,"snapshot_refs":SHAS,
 "analysis_date_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
 "successful_list_fetches":len(set((r["repository"],r["snapshot"],r["list"]) for r in rows)),
 "failed_list_fetches":len(errors),
 "note":"An absent country-specific list is not a measurement zero. Global applies across countries. Snapshots are not the full event history or client refresh timeline."}
(OUT/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
print("EU27_COMPLETE",json.dumps({"errors":len(errors),"summary":summary}),flush=True)
if errors:raise SystemExit(2)
