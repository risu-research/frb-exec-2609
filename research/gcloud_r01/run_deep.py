#!/usr/bin/env python3
"""R01b full result-index overlap for 11 precommitted query pairs, using only public GET.
Adaptive follow-up to 2026-11-23 exploratory first-page pilot, NOT confirmatory validation.
"""
import csv, hashlib, json, math, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

ROOT="https://www.applytosupply.digitalmarketplace.service.gov.uk"
PATH="/g-cloud/search"
OUT=Path("research/gcloud_r01/results_full");OUT.mkdir(parents=True,exist_ok=True)
PAIRS=[
 ("01","citizen enquiry assistant","chatbot","virtual assistant"),
 ("02","speech to text","speech to text","speech transcription"),
 ("03","extract scanned text","optical character recognition","OCR"),
 ("04","document classification","document classification","document categorisation"),
 ("05","personal data redaction","personal data redaction","PII redaction"),
 ("06","invoice data capture","invoice data extraction","invoice capture"),
 ("07","meeting transcription","meeting transcription","meeting audio transcription"),
 ("08","semantic document search","semantic search","natural language search"),
 ("09","translation","machine translation","automated translation"),
 ("10","contract review","contract analysis","contract intelligence"),
 ("11","fraud detection","fraud detection","fraud analytics"),
]
S=requests.Session();S.headers.update({"User-Agent":"RISU-Institute-open-public-search-study/0.1", "Accept-Language":"en-GB"})
errors=[]
def get(params):
    for tries in range(3):
        try:
            r=S.get(ROOT+PATH,params=params,timeout=35)
            if r.status_code==200:return r
            errors.append({"reason":"http_error","status":r.status_code,"url":r.url})
            if r.status_code not in (429,500,502,503,504):break
        except Exception as e:errors.append({"reason":"request_error","error":repr(e)})
        time.sleep(2*(tries+1))
    raise RuntimeError("Public source inaccessible, fail closed: "+str(params))
def count_from(soup):
    text=soup.get_text(" ",strip=True)
    for pat in (r"([\d,]+)\s+results found in Lot 2b",r"([\d,]+)\s+results found"):
        m=re.search(pat,text,flags=re.I)
        if m:return int(m.group(1).replace(",",""))
    return None
def extract(soup):
    cards=[];seen=set()
    for a in soup.select('a[href*="/g-cloud/services/"]'):
        url=urljoin(ROOT,a.get("href",""))
        m=re.search(r"/g-cloud/services/(\d+)",urlparse(url).path)
        if not m or m.group(1) in seen:continue
        li=a.find_parent("li") or a.find_parent("article")
        if not li:continue
        name=a.get_text(" ",strip=True)
        parts=list(li.stripped_strings)
        k=next((i for i,t in enumerate(parts) if t.strip()==name.strip()),-1)
        vendor=parts[k+1] if k>=0 and k+1<len(parts) else ""
        abstract=" ".join(parts[k+2:k+5])[:400] if k>=0 else ""
        cards.append({"id":m.group(1),"service":name,"supplier":vendor,"summary":abstract,"url":url})
        seen.add(m.group(1))
    return cards
def fetch_all(term):
    allrows=[];seen=set();pages=[];expected=None
    for page in range(1,16):
        params={"lot":"saas","q":term}
        if page>1:params["page"]=page
        time.sleep(1.25)
        r=get(params);sp=BeautifulSoup(r.text,"html.parser")
        c=count_from(sp);rows=extract(sp)
        if expected is None:
            expected=c
            if expected is None:raise ValueError("missing result count for "+term)
            if expected==0:return {"term":term,"count":0,"rows":[],"pages":[]}
        if c!=expected:errors.append({"reason":"count_drift","term":term,"page":page,"c":c,"expected":expected})
        keys=set()
        for v in rows:
            keys.add(v["id"])
            if v["id"] not in seen:allrows.append(v);seen.add(v["id"])
        pages.append({"page":page,"url":r.url,"count_on_page":len(rows),
          "new_unique_ids":len(keys-seen.union(set())) if False else None,
          "first_id":rows[0]["id"] if rows else None,
          "last_id":rows[-1]["id"] if rows else None,
          "sha256":hashlib.sha256(r.content).hexdigest()})
        print("PAGE",json.dumps({"term":term,"page":page,"expected":expected,
         "extracted":len(rows),"unique_total":len(seen),"url":r.url}),flush=True)
        if not rows:break
        if len(seen)>=expected:break
        if page>=math.ceil(expected/max(len(rows),1))+2:
            errors.append({"reason":"unexpected_page_count","term":term,"page":page,"expected":expected})
            break
        if page>1 and len(seen)==sum(1 for x in allrows if x["id"] in seen) and allrows[:len(rows)]==rows:
            errors.append({"reason":"possible_pagination_loop","term":term,"page":page})
            break
    return {"term":term,"count":expected,"rows":allrows,"pages":pages,"complete":len(allrows)==expected}
records={}
for pid,requirement,a,b in PAIRS:
    x=fetch_all(a);y=fetch_all(b)
    records[pid]={"description":requirement,"A":x,"B":y}
    sx={r["id"] for r in x["rows"]};sy={r["id"] for r in y["rows"]}
    ax={r["supplier"].casefold().strip() for r in x["rows"] if r["supplier"]};
    ay={r["supplier"].casefold().strip() for r in y["rows"] if r["supplier"]}
    diff={
      "pair_id":pid,"requirement":requirement,"query_A":a,"query_B":b,
      "service_count_A":x["count"],"service_count_B":y["count"],
      "retrieved_A":len(sx),"retrieved_B":len(sy),
      "complete_A":x.get("complete",False),"complete_B":y.get("complete",False),
      "intersection_services":len(sx&sy),"union_services":len(sx|sy),
      "jaccard_services":round(len(sx&sy)/len(sx|sy),6) if sx|sy else None,
      "unique_to_A":len(sx-sy),"unique_to_B":len(sy-sx),
      "unique_suppliers_A":len(ax),"unique_suppliers_B":len(ay),
      "intersection_suppliers":len(ax&ay),"union_suppliers":len(ax|ay),
      "jaccard_suppliers":round(len(ax&ay)/len(ax|ay),6) if ax|ay else None,
      "examples_only_A":[r for r in x["rows"] if r["id"] not in sy][:5],
      "examples_only_B":[r for r in y["rows"] if r["id"] not in sx][:5],
    }
    records[pid]["summary"]=diff
    print("PAIR_FULL",json.dumps({k:v for k,v in diff.items() if k not in ("examples_only_A","examples_only_B")}),flush=True)
# Repeat a source query at the END of the run to detect instability.
a0=records["04"]["A"]
repeat=fetch_all("document classification")
repeatIDs=[r["id"] for r in repeat["rows"]]
origIDs=[r["id"] for r in a0["rows"]]
stability={"term":"document classification","same_total_count":repeat["count"]==a0["count"],
           "same_full_set":set(repeatIDs)==set(origIDs),
           "same_first_30_order":repeatIDs[:30]==origIDs[:30],
           "count_orig":a0["count"],"count_repeat":repeat["count"]}
print("STABILITY",json.dumps(stability),flush=True)
records["_meta"]={
 "retrieval_started_from":"2026-11-23 exploratory pilot",
 "execution_timestamp":datetime.now(timezone.utc).isoformat(),
 "scope":"PUBLIC G-Cloud 15 Lot 2b search, not buyer CAS",
 "pairs_adaptively_selected":"All 11 measurable pairs from R01a; excluded original pair 12 whose count is unparsed",
 "stability":stability,"errors":errors,"limit":"No independently assessed eligibility, award or price inference"}
(OUT/"full_index_records.json").write_text(json.dumps(records,indent=2,ensure_ascii=False))
rows=[records[k]["summary"] for k in records if not k.startswith("_")]
cols=[k for k in rows[0] if k not in ("examples_only_A","examples_only_B")]
with (OUT/"full_index_summary.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows([{k:v[k] for k in cols} for v in rows])
(OUT/"summary_for_review.json").write_text(json.dumps({"pairs":[
    {**{k:v for k,v in r.items() if k not in ("examples_only_A","examples_only_B")},
       "example_A":r["examples_only_A"][:3],"example_B":r["examples_only_B"][:3]}
    for r in rows],"stability":stability,"errors":errors},indent=2))
if not all(v["complete_A"] and v["complete_B"] for v in rows):
    print("FINAL_FAIL_INCOMPLETE: no complete-set claims allowed",flush=True)
    sys.exit(2)
if not stability["same_full_set"]:
    print("FINAL_FAIL_UNSTABLE: index drift or retrieval problem",flush=True)
    sys.exit(3)
print("FINAL_SUCCESS_FULL_RETRIEVAL",json.dumps({"pairs":len(rows),"all_complete":True,"stability":stability}),flush=True)
