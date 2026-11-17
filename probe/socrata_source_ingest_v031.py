#!/usr/bin/env python3
"""Official CO/NY entity, filing and status source-scale ingest.
Public compute emits only ciphertext; raw source values are never artifacts.
"""
import argparse,gzip,hashlib,json,pathlib,random,time,urllib.parse,urllib.request,urllib.error
from datetime import datetime,timezone
SOURCE={
"co_master":("CO","data.colorado.gov","4ykn-tg5h","entities",None,("entityid","entitystatus","entitytype","entityformdate","jurisdictonofformation"),"entityid"),
"co_events":("CO","data.colorado.gov","casm-dbbj","events","receiveddate",("entityid","transactionid","historydes","receiveddate","effectivedate"),"entityid"),
"ny_events":("NY","data.ny.gov","63wc-4exh","events","date_filed",("corpid_num","film_num","date_filed","eff_date","documenttype","mod_certcode","entitytype","law"),"corpid_num"),
"ny_status":("NY","data.ny.gov","3gg2-jgnp","status_observations","date_filed",("corpid_num","film_num","date_filed","mod_cert_code","status"),"corpid_num")
}
def fetch(url):
 for i in range(7):
  try:
   q=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"RISUAP-v0.3-official-source"})
   with urllib.request.urlopen(q,timeout=180) as response:return json.loads(response.read(60_000_000))
  except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ConnectionError) as e:
   if i==6:raise
   delay=min(45,2**i+random.random())
   print("RETRY",type(e).__name__,round(delay,1),flush=True);time.sleep(delay)
def api(host,id,query):
 return fetch("https://"+host+"/resource/"+id+".json?"+urllib.parse.urlencode(query))
def metadata(host,id):
 j=fetch("https://"+host+"/api/views/"+id+".json")
 return {"id":id,"domain":host,"title":j.get("name"),"rows_updated_epoch":j.get("rowsUpdatedAt"),"metadata_updated_epoch":j.get("viewLastModified"),"license":j.get("license")}
def normalize(row,config):
 state,host,source,role,datefield,fields,key=config
 raw=row.get(key);uuid=row.get(":id")
 if raw is None or not str(raw).strip():return None
 if uuid is None or not str(uuid).strip():raise ValueError("Missing publisher row ID")
 native=str(raw).strip();entity="US-"+state+":"+native
 x={"jurisdiction":"US-"+state,"registry_id":native,"entity_key":entity,"publisher_dataset":source,"publisher_row_id":str(uuid)}
 if role=="entities":
  x.update({"status_observation_source_value":row.get("entitystatus"),"entity_type_source":row.get("entitytype"),"formation_date_observed":row.get("entityformdate"),"jurisdiction_of_formation_source":row.get("jurisdictonofformation"),"historical_status_certain":False})
 elif role=="status_observations":
  x.update({"status_event_key":entity+"#"+str(uuid),"filed_at":row.get("date_filed"),"filing_id_source":row.get("film_num"),"status_after_filing_source":row.get("status"),"source_modification_code":row.get("mod_cert_code")})
 else:
  x.update({"event_key":entity+"#"+str(uuid),"source_record_id":row.get("transactionid") if state=="CO" else row.get("film_num"),"source_event_label":row.get("historydes") if state=="CO" else row.get("documenttype"),"source_event_code":row.get("mod_certcode"),"filed_or_received_at":row.get(datefield),"effective_at":row.get("effectivedate") if state=="CO" else row.get("eff_date"),"time_field_basis":"received_date" if state=="CO" else "filed_date","source_event_type":row.get("entitytype") if state=="NY" else None,"source_law":row.get("law") if state=="NY" else None})
 return x
def export(kind,first,end,dest,limit):
 cfg=SOURCE[kind];state,host,id,role,datefield,fields,key=cfg
 if datefield:
  if not(first and end and first<end):raise ValueError("Date window required")
  where=f"{datefield} >= '{first}T00:00:00' AND {datefield} < '{end}T00:00:00'"
 else:
  if first or end:raise ValueError("Full master must not be date-filtered")
  where=None
 dest=pathlib.Path(dest);dest.mkdir(parents=True,exist_ok=False)
 before=metadata(host,id)
 count_query={"$select":"count(*)"}
 if where:count_query["$where"]=where
 n=int(api(host,id,count_query)[0]["count"])
 processed=excluded=0;seen=set();digest=hashlib.sha256();page_sizes=[]
 with gzip.open(dest/(role+".jsonl.gz"),"wb",compresslevel=6) as file:
  for offset in range(0,n,limit):
   q={"$select":":id,"+",".join(fields),"$order":":id","$limit":limit,"$offset":offset}
   if where:q["$where"]=where
   page=api(host,id,q);expected=min(limit,n-offset)
   if len(page)!=expected:raise ValueError("API page mismatch")
   page_sizes.append(len(page))
   for row in page:
    rid=row.get(":id")
    if not rid or rid in seen:raise ValueError("Missing or duplicate source row id")
    seen.add(rid);r=normalize(row,cfg)
    if r is None:excluded+=1;continue
    if datefield:
     dt=(r.get("filed_at") or r.get("filed_or_received_at") or "")[:10]
     if not(first<=dt<end):raise ValueError("Invalid date-window record")
    b=(json.dumps(r,sort_keys=True,ensure_ascii=False,separators=(",",":"))+"\n").encode()
    file.write(b);digest.update(b);processed+=1
   print("PAGE",kind,offset+len(page),n,flush=True)
 after=metadata(host,id)
 after_n=int(api(host,id,count_query)[0]["count"])
 if before!=after or n!=after_n:raise ValueError("Publisher updated source during retrieval")
 if processed+excluded!=n or len(seen)!=n:raise ValueError("Incomplete retrieval")
 report={"schema":"RISUAP-official-source-v031","dataset":id,"jurisdiction":"US-"+state,"role":role,"publisher_before":before,"publisher_after":after,"acquired_utc":datetime.now(timezone.utc).isoformat(),"scope":{"kind":"all_records" if where is None else "complete_date_window","start_inclusive":first,"end_exclusive":end,"date_field":datefield},"counts":{"publisher_scope_rows":n,"exported":processed,"excluded_no_entity_id":excluded},"jsonl_sha256":digest.hexdigest(),"file":role+".jsonl.gz","order":":id","page_limit":limit,"pages":len(page_sizes),"publisher_edition_stable":True,"field_policy":"No names or person/location fields; source status, IDs, codes, dates only"}
 (dest/"manifest.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
 print("COMPLETE",kind,processed,excluded,n,digest.hexdigest(),flush=True)
if __name__=="__main__":
 p=argparse.ArgumentParser()
 p.add_argument("--kind",choices=SOURCE,required=True);p.add_argument("--out",required=True)
 p.add_argument("--start");p.add_argument("--end");p.add_argument("--limit",type=int,default=20000)
 a=p.parse_args()
 if not 100<=a.limit<=50000:raise ValueError("Bad page limit")
 export(a.kind,a.start,a.end,a.out,a.limit)
