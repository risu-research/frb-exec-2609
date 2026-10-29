#!/usr/bin/env python3
"""FOCI 2027: reproducible first-parent histories of seven public test lists.

Audits BOTH citizenlab/test-lists and ooni/test-lists default branches.
Every change touching a studied URL is captured from git diffs, including merges.
A zero change count is supported by a fully cloned first-parent history, not
merely a pair of snapshots. Git timestamps are publication proxies, not probe
client refresh or dissemination timestamps.
"""
import csv, datetime as dt, io, json, os, re, subprocess, tempfile, time
from pathlib import Path

OUT=Path("foci_git_history_results")
OUT.mkdir(exist_ok=True)
LISTS=["global","de","fr","pl","it","cz","sk"]
PATHS=["lists/"+l+".csv" for l in LISTS]
COHORTS={
 "new_2025_roots":{
 "EADaily":["eadaily.com"], "Fondsk":["fondsk.ru"],"Lenta":["lenta.ru"],
 "NewsFront":["news-front.info","news-front.su"],
 "RuBaltic":["rubaltic.ru"],"SouthFront":["southfront.press"],
 "Strategic Culture":["strategic-culture.org","strategic-culture.su"],
 "Krasnaya Zvezda":["tvzvezda.ru","redstar.ru","radiozvezda.ru","zvezdaweekly.ru"]},
 "old_sanctioned":{"RT":["rt.com"],"Sputnik":["sputniknews.com","sputnikglobe.com"]},
 "prelisted_non_sanctioned":{
 "BBC":["bbc.com"],"DW":["dw.com"],"France 24":["france24.com"],
 "Al Jazeera":["aljazeera.com"],"Reuters":["reuters.com"],"The Guardian":["theguardian.com"]},
 "unlisted_non_sanctioned":{
 "Novaya Gazeta Europe":["novayagazeta.eu"],"The Moscow Times":["themoscowtimes.com"],
 "RBC":["rbc.ru"],"Mediazona":["zona.media"],"The Bell":["thebell.io"],
 "TV Rain":["tvrain.tv"],"Fontanka":["fontanka.ru"],"iStories":["istories.media"]},
 "recent_addition_controls":{"Euronews":["euronews.com"],"NPR":["npr.org"]}
}
HOSTS=sorted({root for ents in COHORTS.values() for roots in ents.values() for root in roots})
REGEX="|".join(re.escape(h).replace(r"\.","[.]") for h in HOSTS)
REPOS=["citizenlab/test-lists","ooni/test-lists"]
SNAPS={"pre_2022_sanctions":"2022-03-01T23:59:59Z",
       "pre_2025_announcement":"2025-02-23T23:59:59Z",
       "pre_2025_activation":"2025-04-08T23:59:59Z",
       "oct_29_2026":"2026-10-29T23:59:59Z"}
def git(cwd,*args,ok=True):
 p=subprocess.run(["git","-C",str(cwd),*args],capture_output=True,text=True,
                  encoding="utf-8",errors="replace",timeout=200)
 if p.returncode and ok: raise RuntimeError("git "+" ".join(args[:5])+
                                            " failed: "+p.stderr[:900])
 return p.stdout if p.returncode==0 else None
def reader(blob):
 if not blob:return []
 return list(csv.DictReader(io.StringIO(blob)))
def normalized(url):
 try:
  h=url.lower().strip().split("://",1)[1].split("/",1)[0].split(":",1)[0].split("?",1)[0]
  return h.removeprefix("www.")
 except Exception:return ""
def matches(rows,root):
 return sorted(set((x.get("url") or "",x.get("category_code") or "",
                    x.get("date_added") or "") for x in rows
           if (normalized(x.get("url",""))==root or
               normalized(x.get("url","")).endswith("."+root))))
def load(cwd,sha,path):
 x=git(cwd,"show",sha+":"+path,ok=False)
 return reader(x)
def write(path,rows,cols):
 with path.open("w",newline="",encoding="utf8") as f:
  w=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore");w.writeheader();w.writerows(rows)
events=[];snapshots=[];summary=[];metadata=[]
for repo in REPOS:
 cwd=Path(tempfile.mkdtemp(prefix="foci-testlists-"))
 clone=["git","-c","protocol.version=2","clone","--quiet","--filter=blob:none",
        "--no-checkout","--single-branch","https://github.com/"+repo+".git",str(cwd)]
 p=subprocess.run(clone,capture_output=True,text=True,timeout=180,errors="replace")
 if p.returncode:
  raise RuntimeError("clone "+repo+" failed: "+p.stderr[:900])
 head=git(cwd,"rev-parse","HEAD").strip()
 shallow=git(cwd,"rev-parse","--is-shallow-repository").strip()
 if shallow!="false":raise ValueError("Cannot assert full history: shallow clone")
 first=git(cwd,"rev-list","--max-parents=0","HEAD").strip().splitlines()
 # --first-parent makes the default branch history, not random short-lived PR branches.
 # -m makes merge commits show first-parent diff, including merged test-list edits.
 cmd=["log","--first-parent","-m","--reverse","--format=FOCI_COMMIT:%H",
      "-G",REGEX,"--",*PATHS]
 history=git(cwd,*cmd)
 ids=[]
 for line in history.splitlines():
  if line.startswith("FOCI_COMMIT:"):
   sha=line.split(":",1)[1].strip()
   if sha not in ids:ids.append(sha)
 print("CLONED",repo,"head",head,"first_root",first[:1],
       "candidate_touch_commits",len(ids),flush=True)
 for snap,stamp in SNAPS.items():
  rev=git(cwd,"rev-list","-1","--first-parent","--before="+stamp,"HEAD").strip()
  if not rev:raise ValueError("Missing snapshot "+snap+" for "+repo)
  for path in PATHS:
   rows=load(cwd,rev,path)
   for cohort,entities in COHORTS.items():
    for entity,roots in entities.items():
     matching=set()
     for root in roots:matching.update(matches(rows,root))
     snapshots.append({
      "repository":repo,"snapshot":snap,"timestamp_bound":stamp,"commit":rev,
      "list":path.replace("lists/","").replace(".csv",""),
      "cohort":cohort,"entity":entity,"domain_roots":";".join(roots),
      "matches":len(matching),"matched_urls":";".join(x[0] for x in sorted(matching))
     })
  print("SNAPSHOT",repo,snap,rev,flush=True)
 for num,sha in enumerate(ids):
  parent=git(cwd,"rev-parse",sha+"^1",ok=False)
  if parent is None:continue
  parent=parent.strip()
  changed=git(cwd,"diff","--name-only",parent,sha,"--",*PATHS).splitlines()
  stamp=git(cwd,"show","-s","--format=%cI",sha).strip()
  title=git(cwd,"show","-s","--format=%s",sha).strip()[:150]
  for path in changed:
   before=load(cwd,parent,path)
   after=load(cwd,sha,path)
   for cohort,entities in COHORTS.items():
    for entity,roots in entities.items():
     b=set();a=set()
     for root in roots:
      b.update(matches(before,root));a.update(matches(after,root))
     if b!=a:
      before_urls=set(x[0] for x in b)
      after_urls=set(x[0] for x in a)
      events.append({
       "repository":repo,"commit":sha,"commit_date":stamp,
       "list":path.replace("lists/","").replace(".csv",""),
       "cohort":cohort,"entity":entity,
       "roots":";".join(roots),
       "before_urls":len(before_urls),"after_urls":len(after_urls),
       "added_urls":";".join(sorted(after_urls-before_urls)),
       "removed_urls":";".join(sorted(before_urls-after_urls)),
       "before_details":";".join("|".join(x) for x in sorted(b)),
       "after_details":";".join("|".join(x) for x in sorted(a)),
       "type":("added" if not b else "removed" if not a else "modified"),
       "commit_title":title,
       "commit_url":"https://github.com/"+repo+"/commit/"+sha
      })
  if (num+1)%25==0:
   print("EVENT_SCAN",repo,num+1,len(ids),"events",sum(e["repository"]==repo for e in events),flush=True)
 metadata.append({"repository":repo,"head":head,"head_datetime":git(cwd,"show","-s","--format=%cI",head).strip(),
                  "shallow":shallow,"first_ancestor":first[:1],
                  "candidate_touch_commits":len(ids),
                  "observed_membership_changes":sum(e["repository"]==repo for e in events),
                  "full_first_parent_from_root":True})
 print("FINISHED_HISTORY",repo,"events",sum(e["repository"]==repo for e in events),flush=True)
write(OUT/"membership_events_full_first_parent.csv",events,
 ["repository","commit","commit_date","list","cohort","entity","roots",
  "before_urls","after_urls","added_urls","removed_urls",
  "before_details","after_details","type","commit_title","commit_url"])
write(OUT/"fixed_date_snapshots.csv",snapshots,
 ["repository","snapshot","timestamp_bound","commit","list","cohort","entity",
  "domain_roots","matches","matched_urls"])
write(OUT/"repository_audit_manifest.csv",metadata,
 ["repository","head","head_datetime","shallow","first_ancestor",
  "candidate_touch_commits","observed_membership_changes","full_first_parent_from_root"])
for repo in REPOS:
 for cohort,entities in COHORTS.items():
  for entity in entities:
   rr=[e for e in events if e["repository"]==repo and e["cohort"]==cohort and e["entity"]==entity]
   post=[e for e in rr if e["commit_date"]>="2025-04-09"]
   ss=[e for e in snapshots if e["repository"]==repo and e["cohort"]==cohort and
       e["entity"]==entity and e["snapshot"]=="oct_29_2026"]
   summary.append({
    "repository":repo,"cohort":cohort,"entity":entity,
    "total_membership_change_events":len(rr),
    "post_2025_activation_change_events":len(post),
    "first_event_date":min((e["commit_date"] for e in rr),default=""),
    "last_event_date":max((e["commit_date"] for e in rr),default=""),
    "present_in_2026_global_or_6_lists":int(any(e["matches"] for e in ss)),
    "current_matching_entries":sum(e["matches"] for e in ss),
   })
write(OUT/"entity_change_summary.csv",summary,
 ["repository","cohort","entity","total_membership_change_events",
  "post_2025_activation_change_events","first_event_date","last_event_date",
  "present_in_2026_global_or_6_lists","current_matching_entries"])
manifest={"run_at":dt.datetime.now(dt.timezone.utc).isoformat(),"repositories":metadata,
 "audited_list_paths":PATHS,"analyzed_groups":COHORTS,
 "method":"git clone full, default-branch first-parent -G domain regex, reconstruct pre/post states at each candidate change, independently scan four fixed-date snapshots",
 "scope":"Complete default-branch history of host-matching membership changes for the fixed cohorts on seven list paths; not all repositories, all URL aliases, actual client downloads or all Git branches.",
 "warning":"Comparison at Git commit time; merge dates and source publication dates do not prove when OONI probes refreshed the list. A no-change result is bounded to seven selected lists and fixed root/host matching."}
(OUT/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
print("AUDIT_COMPLETE",json.dumps({"repositories":metadata,"n_events":len(events),
 "post_2025_new":sum(s["post_2025_activation_change_events"] for s in summary if s["cohort"]=="new_2025_roots")}),flush=True)
