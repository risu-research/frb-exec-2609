#!/usr/bin/env python3
"""Source-wide October 2026 CO or NY filing/transaction tranche, official publisher edition."""
from __future__ import annotations
import argparse,gzip,hashlib,json,time,urllib.parse,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
SOURCES={
 'CO':{'host':'data.colorado.gov','id':'casm-dbbj','date':'receiveddate',
       'fields':(':id','entityid','transactionid','historydes','receiveddate','effectivedate'),
       'native_id':'entityid','filing_id':'transactionid','label':'historydes','effective':'effectivedate'},
 'NY':{'host':'data.ny.gov','id':'63wc-4exh','date':'date_filed',
       'fields':(':id','corpid_num','film_num','date_filed','eff_date','documenttype','mod_certcode','entitytype','law'),
       'native_id':'corpid_num','filing_id':'film_num','label':'documenttype','effective':'eff_date'},
}
def fetch(url):
    for attempt in range(4):
        try:
            req=urllib.request.Request(url,headers={'Accept':'application/json',
                     'User-Agent':'RISUAP-official-administrative-data/0.3'})
            with urllib.request.urlopen(req,timeout=120) as response:
                return json.loads(response.read(20_000_000))
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ConnectionError) as exc:
            if attempt==3:raise
            print('Official API request retry',attempt+1,type(exc).__name__,flush=True)
            time.sleep(2**attempt)

def get_meta(s):
    data=fetch('https://'+s['host']+'/api/views/'+s['id']+'.json')
    return {'dataset_name':data.get('name'),'updated_epoch':data.get('rowsUpdatedAt'),
            'metadata_modified_epoch':data.get('viewLastModified'),
            'license':data.get('license'),'source_url':'https://'+s['host']+'/d/'+s['id']}

def query_count(s,where):
    url='https://'+s['host']+'/resource/'+s['id']+'.json?'+urllib.parse.urlencode(
        {'$select':'count(*)','$where':where})
    return int(fetch(url)[0]['count'])

def normalize(row,state,s):
    native=row.get(s['native_id'])
    if native is None or not str(native).strip():return None
    native=str(native).strip()
    rid=str(row.get(':id') or '').strip()
    if not rid:raise ValueError('Missing source system row ID')
    event_id=row.get(s['filing_id'])
    received=row.get(s['date'])
    if not isinstance(received,str) or not '2026-10-01'<=received[:10]<='2026-10-31':
        raise ValueError('Row outside October source window')
    item={'jurisdiction':'US-'+state,'entity_key':'US-'+state+':'+native,
          'registry_id':native,'source_record_id':str(event_id) if event_id is not None else None,
          'source_event_label':row.get(s['label']),
          'source_event_code':row.get('mod_certcode') if state=='NY' else None,
          'filed_or_received_at':received,'effective_at':row.get(s['effective']),
          'time_field_basis':'received_date' if state=='CO' else 'filed_date',
          'source_dataset_id':s['id'],'publisher_system_row_id':rid,
          'source_event_type':row.get('entitytype') if state=='NY' else None,
          'source_law':row.get('law') if state=='NY' else None,
          'original_document_audit':'UNVERIFIED'}
    item['event_key']=item['entity_key']+'#'+rid
    return item

def export(state,output,limit):
    s=SOURCES[state]
    where=f"{s['date']} >= '2026-10-01T00:00:00' AND {s['date']} < '2026-11-01T00:00:00'"
    before=get_meta(s);count=query_count(s,where)
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise FileExistsError('Output is not empty')
    digest=hashlib.sha256();got=0;excluded=0;pages=[];ids=set()
    with gzip.open(out/'events.jsonl.gz','wb',compresslevel=7) as f:
        for offset in range(0,count,limit):
            query={'$select':','.join(s['fields']),'$where':where,
                   '$order':':id','$limit':limit,'$offset':offset}
            url='https://'+s['host']+'/resource/'+s['id']+'.json?'+urllib.parse.urlencode(query)
            rows=fetch(url)
            if len(rows)!=min(limit,count-offset):
                raise ValueError('Unexpected API page length at '+str(offset))
            for row in rows:
                rid=row.get(':id')
                if not rid or rid in ids:raise ValueError('Duplicate or absent source row key')
                ids.add(rid)
                obj=normalize(row,state,s)
                if obj is None:excluded+=1;continue
                b=(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode('utf-8')
                f.write(b);digest.update(b);got+=1
            pages.append(len(rows))
            print('SOURCE',state,'processed',offset+len(rows),'of',count,flush=True)
    after=get_meta(s);after_count=query_count(s,where)
    if before!=after or count!=after_count:
        raise RuntimeError('Source edition changed mid-ingest. Refuse to publish staged data.')
    if got+excluded!=count or len(ids)!=count:raise RuntimeError('Source count mismatch')
    result={'schema':'risuap_socrata_oct_v03','jurisdiction':'US-'+state,
      'product_version':'v0.3-source-tranche',
      'edition_acquired_utc':datetime.now(timezone.utc).isoformat(),
      'source':before,'source_dataset_id':s['id'],'source_domain':s['host'],
      'observation_scope':{'kind':'complete_calendar_month_window_as_of_publisher_edition',
          'first_date':'2026-10-01','end_exclusive':'2026-11-01','date_field':s['date']},
      'pagination':{'order':':id','page_limit':limit,'page_lengths':pages,
          'publisher_version_unchanged_during_ingest':True},
      'counts':{'official_window_rows':count,'exported_records':got,'excluded_missing_native_ids':excluded},
      'events_uncompressed_sha256':digest.hexdigest(),
      'field_scope':'Source-native ID, filing type, event dates and source row reference only; no name/address/person/tax fields.',
      'caveat':'Complete date window for one publisher edition; not full historical source or a legally verified outcome.'}
    (out/'manifest.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--state',required=True,choices=SOURCES.keys())
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--limit',type=int,default=10000)
    a=p.parse_args()
    if not 100<=a.limit<=50000:raise ValueError('Invalid source API page limit')
    m=export(a.state,a.out,a.limit)
    print('FINAL',m['jurisdiction'],m['counts'],m['events_uncompressed_sha256'],flush=True)
