#!/usr/bin/env python3
"""R02 official-document availability and exact-phrase mapping (not adoption causality)."""
import csv, hashlib, json, re, time
from pathlib import Path
from datetime import datetime,timezone
from io import BytesIO
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
OUT=Path("research/stigler_r02/results")
OUT.mkdir(parents=True,exist_ok=True)
SOURCES=[["CO","HB26-1263","Introduced","https://www.leg.colorado.gov/bill_files/112332/download","law"],["CO","HB26-1263","Reengrossed","https://www.leg.colorado.gov/bill_files/115038/download","law"],["CO","HB26-1263","Rerevised","https://www.leg.colorado.gov/bill_files/116315/download","law"],["CO","HB26-1263","Final Act","https://www.leg.colorado.gov/bill_files/116772/download","law"],["CO","HB26-1263","L.019 committee amendment","https://leg.colorado.gov/summary_attachments/46907/download","amendment"],["CO","HB26-1263","L.020 committee amendment","https://leg.colorado.gov/summary_attachments/46908/download","amendment"],["CO","HB26-1263","House committee hearing","https://www.leg.colorado.gov/committee_meeting_hearing_summary/30036","process"],["CO","HB26-1263","Senate committee hearing","https://leg.colorado.gov/committee_meeting_hearing_summary/30774","process"],["AZ","HB2311","House bill text","https://www.azleg.gov/legtext/57leg/2r/bills/hb2311h.htm","law"],["AZ","HB2311","Senate bill text","https://www.azleg.gov/legtext/57leg/2r/bills/hb2311s.htm","law"],["AZ","HB2311","Feb 12 committee amendment summary","https://www.azleg.gov/legtext/57leg/2R/summary/H.HB2311_021226_CAUCUS%20AND%20COW.DOCX.htm","process"],["AZ","HB2311","Mar 2 House engrossed summary","https://www.azleg.gov/legtext/57leg/2R/summary/H.HB2311_030226_HOUSE%20ENGROSSED.DOCX.htm","process"],["AZ","HB2311","Governor June 19 veto letter","https://www.azleg.gov/govlettr/57leg/2r/hb2311.pdf","executive"],["OR","SB1546","-1 proposed amendment","https://olis.oregonlegislature.gov/liz/2026R1/Downloads/ProposedAmendment/30390","amendment"],["OR","SB1546","-2 adopted amendment","https://olis.oregonlegislature.gov/liz/2026R1/Downloads/ProposedAmendment/30469","amendment"],["OR","SB1546","-A3 proposed amendment","https://olis.oregonlegislature.gov/liz/2026R1/Downloads/ProposedAmendment/30712","amendment"],["OR","SB1546","Public testimony index","https://apps.oregonlegislature.gov/liz/2026R1/Measures/Testimony/SB1546","process"],["OR","SB1546","Enrolled text","https://olis.oregonlegislature.gov/liz/2026R1/Downloads/MeasureDocument/SB1546/Enrolled","law"],["GA","SB540","Signed law","https://gov.georgia.gov/document/2026-signed-legislation/sb-540/download","law"],["GA","SB540","Official legislation detail","https://www.legis.ga.gov/legislation/73452","process"],["IA","SF2417","Lobbyist declarations","https://www.legis.iowa.gov/lobbyist/reports/declarations?ba=SF2417","lobby"],["IA","SF2417","Official bill history","https://www.legis.iowa.gov/legislation/billTracking/billHistory?billName=SF2417&ga=91","process"],["IA","SF2417","Signed enrolled text","https://www.legis.iowa.gov/docs/publications/LGE/91/attachments/SF2417.html","law"],["NE","LB525","Official history","https://nebraskalegislature.gov/bills/view_bill.php?DocumentID=59601&docnum=LB525&leg=109","process"],["NE","LB525","Final engrossed text","https://nebraskalegislature.gov/FloorDocs/109/PDF/Engrossed/LB525.pdf","law"],["WA","HB2225","Official bill history","https://app.leg.wa.gov/billsummary?BillNumber=2225&Year=2026","process"]]
PATTERNS={
 "third_party_developer_shield":r"(?:does not create liability for the developer|shall not create liability for the developer|does not create liability for.*developer)",
 "developer_operator":r"(?:operator.{0,120}develops and makes|operator.{0,120}develops or makes|operator.{0,120}makes available)",
 "embedded_software_exclusion":r"(?:is a feature within another software application|within another software application)",
 "three_feature_companion":r"(?:asking unprompted or unsolicited|retaining information from prior interactions)",
 "no_private_action":r"(?:does not create a private right of action|no private right of action)",
 "governor_veto":r"(?:i vetoed|vetoed hb.?2311|i will not protect)",
 "google_identified":r"google(?: llc)?",
 "openai_identified":r"openai",
 "age_method":r"(?:age verification|age assurance|age estimation)",
}
sess=requests.Session()
sess.headers.update({"User-Agent":"RISU Institute public-source independent legal history study; finite academic check (GitHub: risu-research)","Accept-Language":"en-US,en;q=0.8"})
def fetch(url):
 for i in range(3):
  try:
   x=sess.get(url,timeout=30)
   if x.status_code==200: return x
   if x.status_code not in (429,500,502,503,504):return x
  except Exception: pass
  time.sleep(1.8+i*2)
 return None
def extract(r):
 ispdf=r.content.startswith(b'%PDF') or 'pdf' in r.headers.get('content-type','').lower()
 if ispdf:
  pdf=PdfReader(BytesIO(r.content))
  return 'PDF',' '.join((p.extract_text() or '') for p in pdf.pages)
 soup=BeautifulSoup(r.content,'html.parser')
 for elt in soup(['script','style','nav','footer']):elt.decompose()
 return 'HTML',soup.get_text(' ',strip=True)
def snap(text,pat):
 m=re.search(pat,text,re.I|re.S)
 return re.sub(r'\s+',' ',text[max(0,m.start()-80):m.end()+140])[:300] if m else ''
results=[]
for n,(state,bill,name,url,kind) in enumerate(SOURCES):
 time.sleep(1.05)
 r=fetch(url)
 row={'state':state,'bill':bill,'stage':name,'class':kind,'url':url,
      'timestamp_utc':datetime.now(timezone.utc).isoformat()}
 if r is None:
  row['status']='REQUEST_FAILED'; results.append(row)
  print('FETCH',state,name,'REQUEST_FAILED',flush=True);continue
 row['http_status']=r.status_code
 row['actual_url']=r.url
 row['sha256']=hashlib.sha256(r.content).hexdigest()
 row['size_bytes']=len(r.content)
 if r.status_code!=200:
  row['status']='HTTP_'+str(r.status_code);results.append(row)
  print('FETCH',state,name,row['status'],flush=True);continue
 try:
  fmt,txt=extract(r)
  txt=re.sub(r'\s+',' ',txt)
 except Exception as exc:
  fmt,txt='ERROR',''
  row['extract_error']=str(exc)
 row['format']=fmt
 row['text_chars']=len(txt)
 row['status']='SOURCE_TEXT' if len(txt)>=500 else 'IMAGE_ONLY_OR_UNREADABLE'
 if row['status']=='SOURCE_TEXT':
  for key,pattern in PATTERNS.items():
   row[key]=bool(re.search(pattern,txt,re.I|re.S))
   row[key+'_context']=snap(txt,pattern)
 else:
  for key in PATTERNS:row[key]=None
 results.append(row)
 print('FETCH',json.dumps({'state':state,'stage':name,'status':row['status'],
   'bytes':len(r.content),'chars':len(txt),'format':fmt,
   'flags':{k:row[k] for k in PATTERNS}}),flush=True)
(OUT/'source_manifest.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
fieldnames=['state','bill','stage','class','url','actual_url','http_status','status','format','size_bytes','text_chars','sha256']+list(PATTERNS)
with (OUT/'source_manifest.csv').open('w',encoding='utf8',newline='') as f:
 w=csv.DictWriter(f,fieldnames=fieldnames);w.writeheader();w.writerows(
  {k:record.get(k) for k in fieldnames} for record in results)
summary={'total':len(results),'with_readable_text':sum(x.get('status')=='SOURCE_TEXT' for x in results),
 'image_only':[(x['state'],x['stage']) for x in results if x.get('status')=='IMAGE_ONLY_OR_UNREADABLE'],
 'failed':[(x['state'],x['stage'],x.get('status')) for x in results if x.get('status') not in ('SOURCE_TEXT','IMAGE_ONLY_OR_UNREADABLE')],
 'by_state':{s:{'total':sum(r['state']==s for r in results),
  'readable':sum(r['state']==s and r.get('status')=='SOURCE_TEXT' for r in results)}
  for s in sorted(set(r['state'] for r in results))},
 'scope':'source availability and literal phrase presence only; no lobbyist-authorship or causal adoption finding',
 'note':'This is not an exhaustive enumeration of each legislature. No original private communications or testimony are represented by a committee amendment document.'}
(OUT/'source_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
print('SUMMARY',json.dumps(summary),flush=True)
