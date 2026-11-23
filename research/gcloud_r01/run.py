#!/usr/bin/env python3
"""Stigler/G-Cloud R01: non-invasive public search audit. Pre-registered pairs below.
No actual buyer shortlist, eligibility, award, price effect or causality is inferred.
"""
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

HOST = "https://www.applytosupply.digitalmarketplace.service.gov.uk"
PATH = "/g-cloud/search"
OUT = Path("research/gcloud_r01/results")
OUT.mkdir(parents=True, exist_ok=True)
PAIRS = [
 ("01","citizen enquiry assistant","chatbot","virtual assistant"),
 ("02","convert speech to text","speech to text","speech transcription"),
 ("03","read text from scans","optical character recognition","OCR"),
 ("04","categorise government documents","document classification","document categorisation"),
 ("05","redact personal identifiers","personal data redaction","PII redaction"),
 ("06","extract invoice fields","invoice data extraction","invoice capture"),
 ("07","transcribe meetings","meeting transcription","meeting audio transcription"),
 ("08","search knowledge semantically","semantic search","natural language search"),
 ("09","translate text automatically","machine translation","automated translation"),
 ("10","analyse contract clauses","contract analysis","contract intelligence"),
 ("11","detect potentially fraudulent activity","fraud detection","fraud analytics"),
 ("12","analyse public feedback tone","sentiment analysis","opinion mining")
]
UA = "RISU-Institute-independent-research/0.1 (public catalogue snapshot; modest rate)"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language":"en-GB,en;q=0.9"})
LOG=[]
def fetch(params, tries=3):
    for i in range(tries):
        try:
            r=S.get(urljoin(HOST, PATH),params=params,timeout=35)
            if r.status_code == 200:
                return r
            LOG.append({"event":"http_error","status":r.status_code,"url":r.url})
            if r.status_code not in (429,500,502,503,504): return r
        except Exception as e:
            LOG.append({"event":"request_exception","error":str(e)})
        time.sleep(2+i*3)
    raise RuntimeError("request failed after retries")
def search_count(soup):
    s=soup.get_text(" ",strip=True)
    tests=[r"([\d,]+)\s+results found in Lot 2b",r"([\d,]+)\s+results found",r"([\d,]+)\s+services found"]
    for pattern in tests:
        match=re.search(pattern,s,flags=re.I)
        if match:return int(match.group(1).replace(",",""))
    return None
def cards(soup):
    rows=[];seen=set()
    for a in soup.select('a[href*="/g-cloud/services/"]'):
        href=urljoin(HOST,a.get("href","")); path=urlparse(href).path
        m=re.search(r"/g-cloud/services/(\d+)",path)
        if not m:continue
        sid=m.group(1)
        if sid in seen:continue
        li=a.find_parent("li")
        if li is None:li=a.find_parent("article")
        if li is None:li=a.find_parent("div")
        if li is None:continue
        title=a.get_text(" ",strip=True)
        pieces=list(li.stripped_strings)
        # Usually the title is the first entry in each listing and supplier the next entry.
        pindex=next((i for i,v in enumerate(pieces) if v.strip()==title.strip()),-1)
        supplier=pieces[pindex+1] if pindex>=0 and pindex+1<len(pieces) else ""
        summary=" ".join(pieces[pindex+2:pindex+5])[:600] if pindex>=0 else ""
        # Discard any generic heading/pagination link, service IDs are our primary keys.
        rows.append({"id":sid,"name":title,"supplier":supplier,"summary":summary,"url":href})
        seen.add(sid)
    return rows
base=fetch({"lot":"saas"})
soup0=BeautifulSoup(base.text,"html.parser")
base_count=search_count(soup0); baseline_cards=cards(soup0)
print("BASELINE",json.dumps({"status":base.status_code,"url":base.url,
 "count":base_count,"service_cards":len(baseline_cards),"html_bytes":len(base.content)}),flush=True)
if base_count is None or base_count < 1000 or len(baseline_cards)<5:
    raise RuntimeError("BASELINE_INVALID: cannot parse official marketplace")
form_info=[]
for form in soup0.find_all("form"):
    names=[{"name":x.get("name"),"type":x.get("type"),"id":x.get("id")} for x in form.find_all("input")]
    form_info.append({"method":form.get("method"),"action":form.get("action"),"fields":names[:80]})
(OUT/"form_inspection.json").write_text(json.dumps(form_info,indent=2))
# Do not silently accept an inert/incorrect URL parameter. Find a keyword form parameter.
named = [x.get("name") for f in soup0.find_all("form") for x in f.find_all("input")
         if (x.get("type") or "text") in ("text","search") and x.get("name")]
tried=[]; query_field=None
for name in list(dict.fromkeys(named + ["q","keywords","search"])):
    t=fetch({"lot":"saas",name:"optical character recognition"})
    bs=BeautifulSoup(t.text,"html.parser")
    c=search_count(bs); listed=cards(bs)
    tried.append({"parameter":name,"count":c,"cards":len(listed),"url":t.url,"code":t.status_code})
    if c is not None and c != base_count and len(listed)>=1:
        query_field=name;break
    time.sleep(.6)
(OUT/"field_detection.json").write_text(json.dumps(tried,indent=2))
print("FIELD_DETECTION",json.dumps(tried),flush=True)
if query_field is None:
    raise RuntimeError("SEARCH_FIELD_UNRESOLVED: stopping rather than inventing observations")
responses=[]; started=datetime.now(timezone.utc).isoformat()
for pid,purpose,a,b in PAIRS:
    for variant,term in (("A",a),("B",b)):
        time.sleep(1.4)
        r=fetch({"lot":"saas",query_field:term})
        bs=BeautifulSoup(r.text,"html.parser")
        count=search_count(bs); listing=cards(bs)
        rec={
          "pair_id":pid,"purpose":purpose,"variant":variant,"term":term,
          "url":r.url,"status":r.status_code,"count":count,
          "html_sha256":hashlib.sha256(r.content).hexdigest(),
          "cards":listing[:30], "displayed_count":len(listing),
          "observed_at":datetime.now(timezone.utc).isoformat()
        }
        responses.append(rec)
        print("QUERY",json.dumps({"pair":pid,"variant":variant,"term":term,
            "count":count,"cards":len(listing),"code":r.status_code,"url":r.url}),flush=True)
        if count is None or (count>0 and not listing):
            LOG.append({"event":"invalid_observation","pair":pid,"variant":variant,"count":count,"cards":len(listing)})
(OUT/"raw_observations.json").write_text(json.dumps({
 "started":started,"finished":datetime.now(timezone.utc).isoformat(),"baseline_count":base_count,
 "baseline_url":base.url,"query_field":query_field,"pair_design":PAIRS,
 "observations":responses,"errors":LOG},indent=2,ensure_ascii=False))
byid={}
for row in responses:byid.setdefault(row["pair_id"],{})[row["variant"]]=row
summaries=[]
for pid,purpose,a,b in PAIRS:
    x,y=byid[pid]["A"],byid[pid]["B"]
    sx={c["id"] for c in x["cards"]};sy={c["id"] for c in y["cards"]}
    vx={c["supplier"].casefold() for c in x["cards"] if c["supplier"]}
    vy={c["supplier"].casefold() for c in y["cards"] if c["supplier"]}
    summaries.append({
     "pair_id":pid,"requirement":purpose,"term_A":a,"term_B":b,
     "all_indexed_count_A":x["count"],"all_indexed_count_B":y["count"],
     "first_page_services_A":len(sx),"first_page_services_B":len(sy),
     "service_overlap_first_page":len(sx&sy),"service_union_first_page":len(sx|sy),
     "service_jaccard_first_page":round(len(sx&sy)/len(sx|sy),6) if sx|sy else None,
     "supplier_overlap_first_page":len(vx&vy),
     "supplier_jaccard_first_page":round(len(vx&vy)/len(vx|vy),6) if vx|vy else None,
     "a_only_examples":[c for c in x["cards"] if c["id"] not in sy][:3],
     "b_only_examples":[c for c in y["cards"] if c["id"] not in sx][:3],
     "full_result_set_captured":False, "eligibility_verified":False,
     "causal_impact_estimated":False})
with (OUT/"pair_summary.csv").open("w",newline="",encoding="utf-8") as f:
    cols=[k for k in summaries[0] if k not in ("a_only_examples","b_only_examples")]
    w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
    for row in summaries:w.writerow({k:row[k] for k in cols})
(OUT/"pair_summary.json").write_text(json.dumps(summaries,indent=2,ensure_ascii=False))
for s in summaries:
    print("PAIR_RESULT",json.dumps({k:v for k,v in s.items() if k not in ("a_only_examples","b_only_examples")}),flush=True)
nvalid=sum(all(byid[p][v]["count"] is not None and
 (byid[p][v]["count"]==0 or len(byid[p][v]["cards"])>0) for v in ("A","B"))
 for p,_,_,_ in PAIRS)
print("FINAL",json.dumps({"valid_pairs":nvalid,"total_pairs":len(PAIRS),
 "query_field":query_field,"warning":"FIRST-PAGE SEARCH EXPOSURE ONLY; NOT ELIGIBILITY OR MARKET HARM"}),flush=True)
if nvalid<len(PAIRS):sys.exit(2)
