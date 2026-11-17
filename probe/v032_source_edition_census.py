#!/usr/bin/env python3
"""Count-only official source-edition census for RISUAP v0.3.2. No entity records are exported."""
import datetime as dt, json, random, time, urllib.error, urllib.parse, urllib.request

SRC={
"co_master":("data.colorado.gov","4ykn-tg5h",None),
"co_events":("data.colorado.gov","casm-dbbj","receiveddate"),
"ny_events":("data.ny.gov","63wc-4exh","date_filed"),
"ny_status":("data.ny.gov","3gg2-jgnp","date_filed")
}
def get(url):
 for n in range(6):
  try:
   req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"RISUAP-source-census-v032"})
   with urllib.request.urlopen(req,timeout=100) as r: return json.load(r)
  except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ConnectionError):
   if n==5:raise
   time.sleep(min(30,2**n+random.random()))
def meta(h,s):
 x=get(f"https://{h}/api/views/{s}.json")
 return {"rows_updated_epoch":x.get("rowsUpdatedAt"),"metadata_updated_epoch":x.get("viewLastModified"),
         "license":x.get("license"),"title":x.get("name")}
def count(h,s,f,start=None,end=None):
 q={"$select":"count(*)"}
 if f and start and end:q["$where"]=f"{f} >= '{start}T00:00:00' AND {f} < '{end}T00:00:00'"
 u=f"https://{h}/resource/{s}.json?"+urllib.parse.urlencode(q)
 return int(get(u)[0]["count"])
def main():
 out={"schema":"risuap-source-edition-census-v032","captured_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
      "sources":{},"status":"metadata_and_counts_only"}
 for kind,(host,src,f) in SRC.items():
  before=meta(host,src)
  windows=([("entire_source",None,None)] if not f else
           [(str(y),f"{y}-01-01",f"{y+1}-01-01") for y in range(2018,2025)]+
           [("existing_2025_2026","2025-01-01","2026-11-01"),
            ("october_2026","2026-10-01","2026-11-01"),
            ("nov_to_nov17_2026","2026-11-01","2026-11-18")])
  obs=[{"name":name,"start":start,"end_exclusive":end,"count":count(host,src,f,start,end)} for name,start,end in windows]
  after=meta(host,src)
  if before!=after:raise RuntimeError("Publisher edition changed mid-census: "+kind)
  out["sources"][kind]={"publisher_dataset":src,"domain":host,"date_field":f,"publisher":before,
    "publisher_edition_stable":True,"windows":obs}
 print(json.dumps(out,sort_keys=True,indent=2))
if __name__=="__main__":main()
