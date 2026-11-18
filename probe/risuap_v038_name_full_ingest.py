#!/usr/bin/env python3
"""Capture one complete frozen bounded NY DOS name-history date window.

No private data appears in stdout or a public artifact. The caller must seal and
remove the source folder before uploading to public GitHub Actions artifacts.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,gzip,hashlib,json,pathlib,random,re,sys,time
import urllib.error,urllib.parse,urllib.request

DS='ekwr-p59j';BASE='https://data.ny.gov';FIELDS=['corpid_num','film_num','date_filed','name_type','name_status','corp_name']

def get(path,params=None):
    url=BASE+path+(('?'+urllib.parse.urlencode(params)) if params else '')
    for retry in range(6):
        try:
            req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'RISUAP/0.3.8 complete bounded name-source capture'})
            with urllib.request.urlopen(req,timeout=110) as response:return json.load(response)
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ConnectionError):
            if retry==5:raise
            time.sleep(min(35,2**retry+random.random()))

def metadata():
    m=get(f'/api/views/{DS}.json')
    fields={c['fieldName']:c['dataTypeName'] for c in m['columns'] if c.get('fieldName') in FIELDS}
    if set(fields)!=set(FIELDS):raise RuntimeError('Source column contract changed')
    return {'dataset':DS,'title':m['name'],'rows_updated_epoch':m.get('rowsUpdatedAt'),
       'metadata_updated_epoch':m.get('viewLastModified'),'license':m.get('license'),'columns':fields}

def window(start,end):
    if end is None:raise ValueError('End bound required')
    dt.date.fromisoformat(end)
    if start is not None:
        dt.date.fromisoformat(start)
        if start>=end:raise ValueError('Invalid window')
    parts=[]
    if start is not None:parts.append("date_filed >= '"+start+"T00:00:00'")
    parts.append("date_filed < '"+end+"T00:00:00'")
    return ' AND '.join(parts)

def capture(start,end,out,label,limit,maxrows,expected,rows_epoch,metadata_epoch):
    where=window(start,end)
    if not re.fullmatch(r'[A-Za-z0-9_-]+',label):raise ValueError('Invalid label')
    if not 1<=limit<=20000 or not 1<=maxrows<=110000:raise ValueError('Unsafe page size or max rows')
    before=metadata()
    if before['rows_updated_epoch']!=rows_epoch or before['metadata_updated_epoch']!=metadata_epoch:
        raise RuntimeError('Official source edition changed from frozen partition plan')
    n=int(get(f'/resource/{DS}.json',{'$select':'count(*)','$where':where})[0]['count'])
    if n!=expected or n>maxrows:raise RuntimeError('Official scope count changed or exceeds bounded partition')
    out.mkdir(parents=True,exist_ok=False)
    target=out/'name_history.jsonl.gz';digest=hashlib.sha256();seen=set();total=0;missingid=0;missingname=0;types=collections.Counter();statuses=collections.Counter()
    with target.open('wb') as f,gzip.GzipFile(fileobj=f,mode='wb',mtime=0,filename='') as gz:
        for offset in range(0,n,limit):
            rs=get(f'/resource/{DS}.json',{'$select':':id,'+','.join(FIELDS),'$where':where,'$order':':id ASC','$limit':limit,'$offset':offset})
            if len(rs)!=min(limit,n-offset):raise RuntimeError('Incomplete page')
            for row in rs:
                rid=row.get(':id')
                if not rid or rid in seen:raise RuntimeError('Missing or duplicate official source UUID')
                seen.add(rid);total+=1
                day=(row.get('date_filed') or '')[:10]
                if not day or (start is not None and day<start) or day>=end:raise RuntimeError('Out-of-range filed date')
                rawid=(row.get('corpid_num') or '').strip();entity_key=('US-NY:'+str(int(rawid))) if re.fullmatch(r'[0-9]+',rawid) else None
                name=row.get('corp_name')
                if entity_key is None:missingid+=1
                if not name:missingname+=1
                types[str(row.get('name_type'))]+=1;statuses[str(row.get('name_status'))]+=1
                record={'publisher_dataset':DS,'jurisdiction':'US-NY','entity_key':entity_key,
                  'source_registry_id':rawid or None,'publisher_row_id':rid,'filing_id_source':row.get('film_num'),
                  'filed_at':row.get('date_filed'),'name_type_source':row.get('name_type'),
                  'name_status_source':row.get('name_status'),'name_source':name}
                line=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')+b'\n'
                gz.write(line);digest.update(line)
            print('COUNT_PROGRESS',label,total,'/',n,flush=True,file=sys.stderr)
    after=metadata()
    if before!=after:raise RuntimeError('Official publisher edition changed while collecting; discard all source data')
    if total!=n or len(seen)!=n:raise RuntimeError('Source count/UUID mismatch')
    manifest={'schema':'risuap-v038-ny-name-bounded-source-v2','dataset':DS,'file':target.name,
       'partition_id':label,'start_inclusive':start,'end_exclusive':end,
       'scope':{'start_inclusive':start,'end_exclusive':end},'publisher_before':before,'publisher_after':after,
       'acquired_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
       'counts':{'publisher_scope_rows':n,'exported':total,'excluded_no_entity_key':missingid,'missing_name':missingname},
       'type_counts':dict(types),'status_counts':dict(statuses),'jsonl_sha256':digest.hexdigest(),
       'interpretation':'Name status reflects observed publisher edition, not historical legal status.'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print('VERIFIED_OFFICIAL_SOURCE_WINDOW',label,total,'missing_DOS_ID',missingid,'missing_name',missingname,flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--start',required=True,help='ISO date or BEGIN for unbounded historical start')
    p.add_argument('--end',required=True);p.add_argument('--label',required=True)
    p.add_argument('--out',type=pathlib.Path,required=True);p.add_argument('--limit',type=int,default=10000)
    p.add_argument('--max-rows',type=int,default=100000);p.add_argument('--expected',type=int,required=True)
    p.add_argument('--rows-epoch',type=int,required=True);p.add_argument('--metadata-epoch',type=int,required=True)
    a=p.parse_args();capture(None if a.start=='BEGIN' else a.start,a.end,a.out,a.label,a.limit,a.max_rows,a.expected,a.rows_epoch,a.metadata_epoch)
if __name__=='__main__':main()
