#!/usr/bin/env python3
"""R01: precommitted official Hawaii SB3001 version chronology + evidence audit.
Source-level flags are *not* legal classifications, and testimony != causal attribution.
"""
import csv, hashlib, json, re, time
from pathlib import Path
from datetime import datetime,timezone
import requests
from bs4 import BeautifulSoup

OUT=Path("research/stigler_r01/results")
OUT.mkdir(parents=True,exist_ok=True)
PREFIX="https://data.capitol.hawaii.gov/sessions/session2026/"
STAGES=["","SD1_","SD2_","HD1_","HD2_","HD3_","CD1_"]
SOURCES=[("BILL_"+(s or "INTRO"),f"{PREFIX}bills/SB3001_{s}.HTM") for s in STAGES]+[
 ("COMMITTEE_SD1",f"{PREFIX}CommReports/SB3001_SD1_SSCR2388_.HTM"),
 ("COMMITTEE_SD2",f"{PREFIX}CommReports/SB3001_SD2_SSCR3078_.HTM"),
 ("COMMITTEE_HD2",f"{PREFIX}CommReports/SB3001_HD2_HSCR1484-26_.HTM"),
 ("COMMITTEE_HD3",f"{PREFIX}CommReports/SB3001_HD3_HSCR1829-26_.HTM"),
 ("CONFERENCE_CD1",f"{PREFIX}CommReports/SB3001_CD1_CCR95-26_.HTM"),
]
s=requests.Session()
s.headers.update({"User-Agent":"RISU independent public legislative archive 2026/1.0 (academic, 1 second pauses)",
                   "Accept-Language":"en-US,en;q=0.8"})
def acquire(url):
 for tries in range(3):
  try:
   r=s.get(url,timeout=30)
   if r.status_code==200:return r
   if r.status_code not in (429,500,502,503,504):return r
  except requests.RequestException:pass
  time.sleep(2+3*tries)
 return None
def normalized(text):
 return re.sub(r"\s+"," ",text)
def context(text,pattern,before=60,after=320):
 m=re.search(pattern,text,re.I)
 return text[max(0,m.start()-before):m.end()+after] if m else None
def flag(text,pattern):
 return bool(re.search(pattern,text,re.I))
rows=[];full={}
for key,url in SOURCES:
 time.sleep(1.0)
 r=acquire(url)
 if not r:
  rows.append({"source":key,"url":url,"status":"UNAVAILABLE","fulltext_length":None});continue
 bs=BeautifulSoup(r.content,"html.parser")
 for tag in bs(["script","style","nav","footer"]):tag.decompose()
 tx=normalized(bs.get_text(" ",strip=True))
 valid=len(tx)>700
 row={"source":key,"url":url,"status":str(r.status_code) if valid else "SHORT_OR_UNPARSEABLE",
      "content_sha256":hashlib.sha256(r.content).hexdigest(),
      "fulltext_length":len(tx),"captured_utc":datetime.now(timezone.utc).isoformat()}
 if valid:
  row["operator_definition"]=context(tx,r'["“]Operator["”]\s+means',10,220)
  row["user_definition"]=context(tx,r'["“](?:Account holder["”]\s+or\s+["“]user|User)["”]\s+means',10,260)
  row["service_definition"]=context(tx,r'["“](?:Conversational artificial intelligence service|AI companion)["”]\s+(?:or\s+["“]service["”]\s+)?means',10,450)
  row["model_third_party_exemption"]=flag(tx,r'not create liability for the developer of an artificial intelligence model')
  row["embedded_software_carveout"]=flag(tx,r'is a feature within another software application')
  row["guest_explicit"]=flag(tx,r'guest or through a temporary account')
  row["three_feature_phrase"]=flag(tx,r'asking unprompted or unsolicited emotion.based questions')
  row["operator_AND"]=flag(tx,r'operator["”]\s+means a person who develops and makes available')
  row["operator_OR"]=flag(tx,r'operator["”]\s+means a person who develops or makes available')
  row["Google_support_mentioned"]=flag(tx,r'Google')
  row["constitutional_objection_mentioned"]=flag(tx,r'constitutional challenge|regulate speech')
  full[key]={"url":url,"text":tx,"sha256":row["content_sha256"]}
 rows.append(row)
 print("SOURCE",json.dumps({k:v for k,v in row.items() if k not in
   ("operator_definition","user_definition","service_definition")}),flush=True)
(OUT/"HI_stage_fulltext.json").write_text(json.dumps(full,ensure_ascii=False,indent=2))
(OUT/"HI_stage_flags.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2))
cols=["source","url","status","content_sha256","fulltext_length","operator_AND","operator_OR",
      "guest_explicit","embedded_software_carveout","three_feature_phrase","model_third_party_exemption",
      "Google_support_mentioned","constitutional_objection_mentioned"]
with (OUT/"HI_stage_flags.csv").open("w",newline="",encoding="utf8") as f:
 w=csv.DictWriter(f,cols);w.writeheader();w.writerows([{k:row.get(k) for k in cols} for row in rows])
missing=[x["source"] for x in rows if x["status"]!="200"]
audit={"status":"SOURCES_ONLY_NO_LEGAL_JUDGMENTS","retrieved":len(rows)-len(missing),
       "requested":len(rows),"unavailable":missing,"date_utc":datetime.now(timezone.utc).isoformat(),
       "limitations":"Automated phrase presence, not legal applicability, stakeholder amendment attribution or market harm. Inspect full text and context."}
(OUT/"source_audit.json").write_text(json.dumps(audit,indent=2))
print("AUDIT",json.dumps(audit),flush=True)
if missing:raise RuntimeError("Unresolved official source document(s): "+", ".join(missing))
