#!/usr/bin/env python3
"""R02: independent source-document capture for relevance assessment.
No LLM labeling. No buyer account, no ordering, no bidder contact.
R01 labels and retrieval strata remain withheld from the adjudication sheet.
"""
import json, hashlib, random, re, time, csv
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests
HOST="https://www.applytosupply.digitalmarketplace.service.gov.uk"
BASE=HOST+"/g-cloud/search"
DEST=Path("research/gcloud_r01/r02_results");DEST.mkdir(parents=True,exist_ok=True)
S=requests.Session();S.headers.update({"User-Agent":"RISU-Institute-GCloud-R02-observation/0.1 (academic official public records only)","Accept-Language":"en-GB"})
# Frozen pre-label R01 sample. Intentionally preserve query provenance separately.
RAW={
"01":{
"A_only":"925144075459230 325853096208335 897145497731078 116908586787806 227121403248453 561472837989283",
"B_only":"268035979182204 471099203679965 711527547898118 616171059510169 332195817134810 237714021823870",
"both":"566349357228700 434040044284311 234957404453745"},
"03":{
"A_only":"794078969014840 156644839926043 192002148762670 344073819696783 762907603906734 628667583872991",
"B_only":"862622265868244 937336633946153 470660712061562 198361650113074 544055122863836 572770274117026",
"both":"654361794555895 923877056518744 329877351417130"},
"04":{
"A_only":"979101167705072 608574864950678 792029717718655 364858794913122 248881635686902 452141387386998",
"B_only":"923877056518744 121123623948905 158065586483608 465565112127094 466089237399851 804048513097544",
"both":"422714495788868 526259670685811 683134573883471"}
}
# Frozen definitions are independent of service results; these aren't procurement eligibility criteria.
RUBRIC={
"01":{"task":"standalone, deployable SaaS conversational virtual agent able to answer or triage citizen questions",
      "positive":"explicit chatbot, virtual agent, or conversational interaction capability that can process public enquiries",
      "negative":"consultancy services alone, general app development without an existing SaaS agent, contact center without bot capability, generic ML platform"},
"03":{"task":"SaaS OCR converting images or scans of documents into machine-readable text",
      "positive":"explicit OCR, scanned-image text recognition or equivalent unstructured document image transcription",
      "negative":"data extraction from pre-digitized records without image recognition, only storage/review of documents, DLP"},
"04":{"task":"SaaS automatically categorises/classifies documents into semantic document types or predefined classes",
      "positive":"explicit automatic document category/class inference or rule-based class assignment to documents",
      "negative":"manual tagging only, classification of patients or hazards instead of documents, case management without automatic document classification"}
}
def get(url, params=None):
    for j in range(3):
        try:
            r=S.get(url,params=params,timeout=30)
            if r.status_code==200:return r
            if r.status_code not in (429,500,502,503,504):return r
        except requests.RequestException:
            pass
        time.sleep(3*(j+1))
    raise RuntimeError("Fetch failed: "+str(url))
def parse_result(soup):
    ids=[]
    for a in soup.select('a[href*="/g-cloud/services/"]'):
        href=a.get('href','')
        m=re.search(r'/g-cloud/services/(\d+)',href)
        if m and m.group(1) not in ids:ids.append(m.group(1))
    return ids
# Untested query terms are additional retrieval channels, intentionally not randomized from treatments.
EXTERNAL_QUERIES=["document processing","document tagging","intelligent document","records automation"]
rng=random.Random(20261123)
manifest=[];origin={}
for pid,strata in RAW.items():
    for s,sl in strata.items():
        for sid in sl.split():
            origin.setdefault((pid,sid),[]).append("R01_"+s)
            manifest.append({"pair":pid,"id":sid,"origin":"R01_"+s})
for term in EXTERNAL_QUERIES:
    time.sleep(1.3)
    res=get(BASE,{"lot":"saas","q":term})
    soup=BeautifulSoup(res.text,"html.parser")
    ids=parse_result(soup)
    if len(ids)<7: raise RuntimeError("Alternative retrieval failed: "+term)
    sampled=rng.sample(ids,min(6,len(ids)))
    for sid in sampled: manifest.append({"pair":"04","id":sid,"origin":"alternative_keyword_"+term})
# Unconditioned baseline: randomly indexed lot 2b pages, regardless of feature similarity.
# This is an unselected reference sample and will mostly be irrelevant.
pages=rng.sample(range(3,300),12)
for p in pages:
    time.sleep(1.3)
    r=get(BASE,{"lot":"saas","page":p})
    ids=parse_result(BeautifulSoup(r.text,"html.parser"))
    if len(ids)<10: raise RuntimeError("Unconditioned catalogue page failed: "+str(p))
    for sid in rng.sample(ids,2):manifest.append({"pair":"04","id":sid,"origin":"unconditioned_page_"+str(p)})
# Add two known diagnostic examples with explicit competing listing/description.
for sid in ["130264369520376","189280877079521"]:
    manifest.append({"pair":"04","id":sid,"origin":"diagnostic_not_random"})
# Fetch each distinct page once. Same page can appear in several rubric tasks.
unique=list(dict.fromkeys(x["id"] for x in manifest))
detail={}
for k,sid in enumerate(unique):
    time.sleep(1.1)
    r=get(HOST+"/g-cloud/services/"+sid)
    text=BeautifulSoup(r.text,"html.parser").get_text("\n",strip=True)
    soup=BeautifulSoup(r.text,"html.parser")
    main=soup.select_one("main") or soup
    full=main.get_text("\n",strip=True)
    title=(soup.title.get_text(" ",strip=True) if soup.title else "")
    # Text snippets are kept without model-generated reduction, for audit.
    detail[sid]={
      "id":sid,"url":r.url,"http_status":r.status_code,
      "content_sha256":hashlib.sha256(r.content).hexdigest(),
      "html_bytes":len(r.content),"title":title,
      "extracted_text":full[:60000],
      "text_characters":len(full),
      "captured_at_utc":datetime.now(timezone.utc).isoformat(),
      "page_headings":[h.get_text(" ",strip=True) for h in main.find_all(["h1","h2","h3"])][:60],
      "pdf_links":[{"text":a.get_text(" ",strip=True),"url":a.get("href")}
                   for a in main.find_all("a",href=True) if ".pdf" in a.get("href","")][:15]
    }
    print("DETAIL",json.dumps({"i":k+1,"total":len(unique),"sid":sid,"status":r.status_code,
        "length":len(full),"title":title[:80]}),flush=True)
    if r.status_code!=200 or len(full)<400:raise RuntimeError("Cannot interpret "+sid)
# Provide blinded task-specific rows; provenance in separate sealed file.
judge=[]
for item in manifest:
    page=detail[item["id"]]
    judge.append({
      "pair":item["pair"],"service_id":item["id"],"task":RUBRIC[item["pair"]]["task"],
      "url":page["url"],"service_title":page["title"],
      "decision":None, "confidence":None,"source_quote":None,
      "source_section":None,"explicit_exclusion_reason":None,
      "notes":None
    })
rng.shuffle(judge)
(DEST/"source_documents.json").write_text(json.dumps(detail,ensure_ascii=False,indent=2))
(DEST/"blinded_adjudication.json").write_text(json.dumps({"rubric":RUBRIC,"items":judge},ensure_ascii=False,indent=2))
(DEST/"provenance_separate.json").write_text(json.dumps({
 "seed":20261123,"manifest":manifest,
 "external_terms":EXTERNAL_QUERIES,
 "unconditioned_pages":pages,
 "note":"EXTERNAL_QUERIES are independent of treated query *strings* but not of keyword search mechanism."},indent=2))
with (DEST/"adjudication_blank.csv").open("w",newline="",encoding="utf8") as f:
    w=csv.DictWriter(f,fieldnames=list(judge[0]))
    w.writeheader();w.writerows(judge)
print("RESULT",json.dumps({"source_pages":len(detail),"task_row_count":len(judge),
 "r01_manifest_rows":45,"keyword_alternative_rows":24,"independent_catalogue_rows":24,
 "diagnostic_rows":2,"status":"SOURCE_CAPTURED_ONLY_NO_JUDGMENTS"}),flush=True)
