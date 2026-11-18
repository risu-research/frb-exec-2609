#!/usr/bin/env python3
"""Official NY DOS name-history source-count census. No entity names/IDs exported."""
import datetime as dt,json,time,random,urllib.request,urllib.parse,sys
BASE='https://data.ny.gov'
ID='ekwr-p59j'
def request(path,params=None):
 url=BASE+path+('?' + urllib.parse.urlencode(params) if params else '')
 for n in range(5):
  try:
   req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'RISUAP-v038-census'})
   with urllib.request.urlopen(req,timeout=90) as r:return json.load(r)
  except Exception:
   if n==4:raise
   time.sleep(min(20,2**n+random.random()))
def meta():
 m=request('/api/views/'+ID+'.json')
 return {'dataset':ID,'rows_epoch':m.get('rowsUpdatedAt'),'metadata_epoch':m.get('viewLastModified'),
  'license':m.get('license'),'column_contract':sorted(c.get('fieldName') for c in m['columns'] if c.get('fieldName') in
  ('corpid_num','film_num','date_filed','name_type','name_status','corp_name'))}
def count(where=None):
 q={'$select':'count(*)'}
 if where:q['$where']=where
 return int(request('/resource/'+ID+'.json',q)[0]['count'])
def main():
 expected=['corpid_num','corp_name','date_filed','film_num','name_status','name_type']
 before=meta()
 if before['column_contract']!=sorted(expected):raise RuntimeError('Source schema changed')
 bounds=['1800-01-01','1900-01-01','1950-01-01','1970-01-01','1980-01-01','1990-01-01','2000-01-01','2005-01-01','2010-01-01','2015-01-01','2018-01-01']+[f'{y}-01-01' for y in range(2019,2028)]
 windows=[('pre1800',None,bounds[0])]+[(f'{a[:4]}_{b[:4]}',a,b) for a,b in zip(bounds,bounds[1:])]
 full=count()
 observed=[]
 for label,start,end in windows:
  clauses=[]
  if start:clauses.append("date_filed >= '"+start+"T00:00:00'")
  if end:clauses.append("date_filed < '"+end+"T00:00:00'")
  n=count(' AND '.join(clauses))
  observed.append({'label':label,'start_inclusive':start,'end_exclusive':end,'publisher_rows':n})
  print('OFFICIAL_COUNT',label,n,flush=True,file=sys.stderr)
 null=count('date_filed IS NULL')
 after=meta()
 if before!=after:raise RuntimeError('Official publisher edition changed during census')
 if sum(x['publisher_rows'] for x in observed)+null!=full:raise RuntimeError('Year range count mismatch')
 print(json.dumps({'schema':'risuap-v038-official-name-source-census-v1','publisher':after,
  'captured_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'full_rows':full,
  'rows_without_filed_date':null,'windows':observed,
  'status':'official_count_census_only_not_ingested'},sort_keys=True,indent=2))
if __name__=='__main__':main()
