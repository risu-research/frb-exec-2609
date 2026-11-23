#!/usr/bin/env python3
"""Stigler 2027 R00 two competing feasibility hypotheses.
Only official public source capture + deterministic text presence checks;
NO legal applicability inference or research allocation outcome.
"""
from pathlib import Path
import requests, hashlib, json, re, csv, time
from collections import Counter
from datetime import datetime,timezone
from io import BytesIO
from bs4 import BeautifulSoup
from pypdf import PdfReader

out=Path("research/stigler_r00/results");out.mkdir(parents=True,exist_ok=True)
law_urls={
 "HI_2026_SB3001_INTRO":"https://data.capitol.hawaii.gov/sessions/session2026/bills/SB3001_.HTM",
 "HI_2026_SB3001_FINAL":"https://data.capitol.hawaii.gov/sessions/session2026/bills/SB3001_CD1_.HTM",
 "CO_2026_HB1263_INTRO":"https://www.leg.colorado.gov/bill_files/112332/download",
 "CO_2026_HB1263_SIGNED":"https://www.leg.colorado.gov/bill_files/116851/download",
 "IA_2026_SF2417_ENROLLED":"https://www.legis.iowa.gov/docs/publications/LGE/91/attachments/SF2417.html",
 "GA_2026_SB540_SIGNED":"https://gov.georgia.gov/document/2026-signed-legislation/sb-540/download",
 "OR_2026_SB1546_ENACTED":"https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2026orLaw0085.pdf",
}
checks={
 "embedded_feature_exemption":r"(?:feature within another software application|feature of.*software application|software.*feature within another)",
 "general_conversation_trigger":r"(?:primarily simulates human conversation|primary purpose of simulating human conversation)",
 "relationship_companion_trigger":r"(?:sustained human or human.like relationship|sustained, human.like .*relationship|sustained human.like)",
 "requires_unprompted_questions":r"(?:asking unprompted|asking unsolicited|unprompted or unsolicited)",
 "requires_memory":r"(?:retaining information (?:on|from) prior interactions|retaining (?:information from|information on) prior)",
 "guest_explicitly_included":r"(?:as a guest or through a temporary account|uses .* as a guest)",
 "account_user_definition":r"(?:(?:account holder|user) means (?:a person|an individual)|account holder.*means an individual)",
 "third_party_model_developer_clause":r"(?:not create liability for the developer|nothing in this section creates liability for a person that develops|not be construed to make a developer)",
 "private_right_bar":r"(?:not.*create a private right of action|no private right of action)",
}
s=requests.Session();s.headers.update({"User-Agent":"RISU Institute Stigler R00 academic public-law audit / contact via public GitHub risu-research","Accept-Language":"en"})
def get(url):
  for j in range(3):
    try:
      r=s.get(url,timeout=35);r.raise_for_status();return r
    except Exception as ex:
      if j==2:raise
      time.sleep(2*(j+1))
def parse(r):
  ctype=r.headers.get("content-type","").lower()
  if r.content[:4]==b"%PDF" or "pdf" in ctype or r.url.lower().split("?")[0].endswith(".pdf"):
    p=PdfReader(BytesIO(r.content))
    return "\n".join(x.extract_text(extraction_mode="plain") or "" for x in p.pages), "PDF"
  bs=BeautifulSoup(r.content,"html.parser")
  for node in bs(["script","style","nav","footer"]):node.decompose()
  return bs.get_text("\n",strip=True),"HTML"
raw={}; matrix=[]; began=datetime.now(timezone.utc).isoformat()
for name,url in law_urls.items():
  time.sleep(1.0)
  resp=get(url)
  txt,kind=parse(resp)
  sha=hashlib.sha256(resp.content).hexdigest()
  if len(txt)<1400:raise ValueError("Document too short: "+name+" "+str(len(txt)))
  raw[name]={"url":url,"final_url":resp.url,"http_status":resp.status_code,"source_format":kind,
    "source_sha256":sha,"text":txt,"text_characters":len(txt)}
  row={"document":name,"format":kind,"text_chars":len(txt),"url":url,"sha256":sha}
  for key,pat in checks.items():
    match=re.search(pat,txt,re.I|re.S)
    row[key+"_present"]=bool(match)
    row[key+"_context"]=txt[max(0,match.start()-120):match.end()+180].replace("\n"," ") if match else ""
  matrix.append(row)
  print("LAW",json.dumps({"document":name,"format":kind,"length":len(txt),
    "signals":{k:row[k+"_present"] for k in checks}}),flush=True)
(out/"law_sources_fulltext.json").write_text(json.dumps(raw,ensure_ascii=False,indent=2))
(out/"law_clause_signals.json").write_text(json.dumps(matrix,ensure_ascii=False,indent=2))
with (out/"law_clause_signals.csv").open("w",newline="",encoding="utf-8") as f:
  columns=["document","format","text_chars","url","sha256"]+[k+"_present" for k in checks]
  w=csv.DictWriter(f,columns);w.writeheader();w.writerows({c:r.get(c) for c in columns} for r in matrix)
# NAIRR provider/resource snapshot, no eligibility or independence judgment.
api="https://submit-nairr.xras.org/resources.json"
resp=get(api);data=resp.json()
if not isinstance(data,list) or len(data)<20:raise ValueError("Unexpected official NAIRR feed")
nairr=[]
for r in data:
  cats={}
  for cat in r.get("featureCategories",[]):
    key=cat.get("categoryName","")
    cats[key]=[x.get("name","") for x in cat.get("features",[])]
  plain=BeautifulSoup(r.get("resourceDescription") or "", "html.parser").get_text(" ",strip=True)
  nairr.append({
    "id":r.get("resourceId"),"name":r.get("resourceName"),
    "organization":r.get("organization"),"type":r.get("resourceType"),"units":r.get("units"),
    "status_labels":cats.get("Resource Status",[]),"category_labels":cats.get("Resource Category",[]),
    "ai_capabilities":cats.get("AI Capabilities",[]),
    "unable_to_accept_phrase":bool(re.search(r"unable to accept additional NAIRR Pilot awards",plain,re.I)),
    "description_excerpt":plain[:1100], "source_url":api
  })
(out/"nairr_resource_list.json").write_text(json.dumps(nairr,indent=2,ensure_ascii=False))
with (out/"nairr_resource_list.csv").open("w",newline="",encoding="utf-8") as f:
  columns=["id","name","organization","type","units","status_labels","category_labels","unable_to_accept_phrase","source_url"]
  w=csv.DictWriter(f,columns);w.writeheader()
  for r in nairr:w.writerow({k:(json.dumps(r[k]) if isinstance(r.get(k),list) else r.get(k)) for k in columns})
stat={
  "timestamp_utc":datetime.now(timezone.utc).isoformat(),"source_hash_sha256":hashlib.sha256(resp.content).hexdigest(),
  "source_url":api,"total_resources":len(data),"by_type":dict(Counter(x["type"] for x in nairr)),
  "by_status_label":dict(Counter(t for x in nairr for t in x["status_labels"])),
  "by_category_label":dict(Counter(t for x in nairr for t in x["category_labels"])),
  "by_organization":dict(Counter(x["organization"] for x in nairr)),
  "explicit_unable_to_accept_phrase":sum(x["unable_to_accept_phrase"] for x in nairr),
  "limitations":"Catalog presence != allocation availability. University or public-center resources are NOT automatically equivalent to the program's 'government agency resources' for private-review opt-out. Cannot infer any applicant's available options without authoritative classifications and allocation rules."
}
(out/"nairr_snapshot_summary.json").write_text(json.dumps(stat,indent=2))
print("NAIRR",json.dumps(stat),flush=True)
print("AUDIT_COMPLETE",json.dumps({"law_document_count":len(matrix),"NAIRR_records":len(data),"timestamp":began}),flush=True)
