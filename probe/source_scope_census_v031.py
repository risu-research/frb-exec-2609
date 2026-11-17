#!/usr/bin/env python3
"""Independent exact publisher row counts for the v0.3.1 CO/NY ingestion scopes."""
import datetime,json,urllib.request,urllib.parse
SOURCES=[
('co_master','data.colorado.gov','4ykn-tg5h',None),
('co_events','data.colorado.gov','casm-dbbj','receiveddate'),
('ny_events','data.ny.gov','63wc-4exh','date_filed'),
('ny_status','data.ny.gov','3gg2-jgnp','date_filed')]
result=[]
for name,host,source,datecol in SOURCES:
 q={'$select':'count(*)'}
 if datecol:q['$where']=f"{datecol} >= '2025-01-01T00:00:00' AND {datecol} < '2026-11-01T00:00:00'"
 url=f'https://{host}/resource/{source}.json?'+urllib.parse.urlencode(q)
 req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'RISUAP-independent-denominator'})
 with urllib.request.urlopen(req,timeout=180) as response:count=int(json.load(response)[0]['count'])
 result.append({'role':name,'dataset':source,'rows':count,'source_date_window':q.get('$where'),'official_url':f'https://{host}/d/{source}'})
 print('SOURCE CENSUS',name,count,flush=True)
print(json.dumps({'catalog_version':'v0.3.1','captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'publisher_counts':result},indent=2))
