#!/usr/bin/env python3
"""Non-personal Socrata date-window counters and stable paging feature probe."""
import json,urllib.parse,urllib.request,datetime
from concurrent.futures import ThreadPoolExecutor

SOURCES=(('US-CO','data.colorado.gov','casm-dbbj','receiveddate'),
         ('US-NY','data.ny.gov','63wc-4exh','date_filed'))
def load(url):
    req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'RISUAP-processed-official-source/0.3'})
    with urllib.request.urlopen(req,timeout=90) as response:
        return json.loads(response.read(500000))
def probe(item):
    state,host,dataset,datecol=item
    base=f'https://{host}/resource/{dataset}.json'
    result={'jurisdiction':state,'dataset':dataset,'date_column':datecol}
    for prefix,where in (
        ('2026_ytd',f"{datecol} >= '2026-01-01T00:00:00' AND {datecol} < '2026-11-01T00:00:00'"),
        ('october_2026',f"{datecol} >= '2026-10-01T00:00:00' AND {datecol} < '2026-11-01T00:00:00'")):
        try:
            u=base+'?'+urllib.parse.urlencode({'$select':'count(*)','$where':where})
            result[prefix+'_rows']=int(load(u)[0]['count'])
        except Exception as exc:
            result[prefix+'_error']=str(exc)[:200]
    try:
        q={'$select':(':id,'+('entityid,transactionid,receiveddate' if state=='US-CO' else 'corpid_num,film_num,date_filed')),
           '$order':':id','$limit':1,'$where':where}
        row=load(base+'?'+urllib.parse.urlencode(q))
        result['system_id_order_supported']=True
        result['returned_fields']=sorted(row[0].keys()) if row else []
    except Exception as exc:
        result['system_id_order_supported']=False
        result['ordering_error']=str(exc)[:150]
    return result
with ThreadPoolExecutor(max_workers=2) as pool:items=list(pool.map(probe,SOURCES))
print(json.dumps({'schema':'risuap_co_ny_ingest_feasibility_v03','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
'results':items},indent=2))
