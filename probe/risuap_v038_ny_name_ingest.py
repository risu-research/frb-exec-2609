#!/usr/bin/env python3
"""Retrieve a *complete official month* of NY name history, sealing it before artifact upload.

Public GitHub execution artifact only contains ciphertext; plaintext lives only in
an ephemeral source directory subsequently removed. The owner private RSA key is not
available to this runner. No substantive current-name conclusions are inferred.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,gzip,hashlib,json,os,pathlib,random,time,urllib.error,urllib.parse,urllib.request
DS='ekwr-p59j';BASE='https://data.ny.gov';FIELDS=['corpid_num','film_num','date_filed','name_type','name_status','corp_name']

def get(path,params=None):
 url=BASE+path+(('?'+urllib.parse.urlencode(params)) if params else '')
 for retry in range(6):
  try:
   req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'RISUAP/0.3.8 official narrow source capture'})
   with urllib.request.urlopen(req,timeout=110) as f:return json.load(f)
  except (urllib.error.URLError,TimeoutError,ConnectionError) as e:
   if retry==5:raise
   time.sleep(min(32,2**retry+random.random()))

def metadata():
 m=get(f'/api/views/{DS}.json');columns={c['fieldName']:c['dataTypeName'] for c in m['columns'] if c.get('fieldName') in FIELDS}
 if set(columns)!=set(FIELDS):raise RuntimeError('Official source column contract changed '+str(columns))
 return {'dataset':DS,'title':m['name'],'rows_updated_epoch':m.get('rowsUpdatedAt'),
    'metadata_updated_epoch':m.get('viewLastModified'),'license':m.get('license'), 'columns':columns}

def main():
 p=argparse.ArgumentParser();p.add_argument('--start',required=True);p.add_argument('--end',required=True)
 p.add_argument('--out',type=pathlib.Path,required=True);p.add_argument('--limit',type=int,default=10000)
 p.add_argument('--max-rows',type=int,default=150000);a=p.parse_args()
 start,end=dt.date.fromisoformat(a.start),dt.date.fromisoformat(a.end)
 if end<=start or (end-start).days>40:raise ValueError('Pilot must be complete calendar month, not large unrestricted dataset')
 if start.day!=1 or (start+dt.timedelta(days=40)).replace(day=1)!=end:raise ValueError('Nonmonth date scope')
 if not(1<=a.limit<=20000):raise ValueError('Page too large')
 if not(1<=a.max_rows<=250000):raise ValueError('Guard maximum source rows')
 where=f"date_filed >= '{start}T00:00:00' AND date_filed < '{end}T00:00:00'"
 before=metadata();count=int(get(f'/resource/{DS}.json',{'$select':'count(*)','$where':where})[0]['count'])
 if count>a.max_rows:raise RuntimeError(f'{count} source rows exceed bounded pilot ceiling')
 a.out.mkdir(parents=True,exist_ok=False)
 target=a.out/'name_history.jsonl.gz';sha=hashlib.sha256();ids=set();tot=0;excl=0;types=collections.Counter();statuses=collections.Counter();missing_name=0
 with target.open('wb') as f,gzip.GzipFile(fileobj=f,mode='wb',mtime=0,filename='') as gz:
  for offset in range(0,count,a.limit):
   rows=get(f'/resource/{DS}.json',{'$select':':id,'+','.join(FIELDS),'$where':where,'$order':':id ASC','$limit':a.limit,'$offset':offset})
   if not rows:raise ValueError('Unexpected missing source page')
   for row in rows:
    rid=row.get(':id')
    if not rid or rid in ids:raise RuntimeError('Missing/duplicate publisher ID')
    ids.add(rid);tot+=1
    when=row.get('date_filed','')[:10]
    if not str(start)<=when<str(end):raise ValueError('Outside month')
    ident=(row.get('corpid_num') or '').strip()
    entity_key=('US-NY:'+str(int(ident))) if ident.isdigit() else None
    if not entity_key:excl+=1
    name=row.get('corp_name')
    if not name:missing_name+=1
    name_type=row.get('name_type');name_status=row.get('name_status')
    types[str(name_type)]+=1;statuses[str(name_status)]+=1
    out={'publisher_dataset':DS,'jurisdiction':'US-NY','entity_key':entity_key,
       'source_registry_id':ident or None,'publisher_row_id':rid,
       'filing_id_source':row.get('film_num'),'filed_at':row.get('date_filed'),
       'name_type_source':name_type,'name_status_source':name_status,'name_source':name}
    line=json.dumps(out,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()+b'\n';sha.update(line);gz.write(line)
   print('CAPTURED',str(start),min(offset+a.limit,count),count,flush=True)
 after=metadata()
 if before!=after:raise RuntimeError('Publisher edition changed during capture, discard product')
 if tot!=count:raise RuntimeError('Official source row count differs from fetched count')
 receipt={'schema':'risuap-v038-ny-name-month-source-v1','dataset':DS,'file':target.name,
 'start_inclusive':str(start),'end_exclusive':str(end),'scope':{'start_inclusive':str(start),'end_exclusive':str(end)},
 'publisher_before':before,'publisher_after':after,'acquired_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
 'counts':{'publisher_scope_rows':count,'exported':tot,'excluded_no_entity_key':excl,'missing_name':missing_name},
 'type_counts':dict(types),'status_counts':dict(statuses),'jsonl_sha256':sha.hexdigest(),
 'interpretation':'Name status is publisher source value at an observed edition, not historical time-travel proof.'}
 (a.out/'manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
 print('VERIFIED_OFFICIAL_MONTH',str(start),tot,'excluded_key',excl,'missing_name',missing_name,sha.hexdigest(),flush=True)
if __name__=='__main__':main()
