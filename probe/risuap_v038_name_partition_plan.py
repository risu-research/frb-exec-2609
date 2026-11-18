#!/usr/bin/env python3
"""Freeze a nonoverlapping official NY Name Status History date partition plan.

Only counts, date windows, source edition metadata. No person/entity rows.
Never blend source vintages: compare before and after the entire partition census.
"""
import argparse, datetime as dt, hashlib, json, pathlib, random, sys, time
import urllib.error, urllib.parse, urllib.request

DATASET='ekwr-p59j'
BASE='https://data.ny.gov'


def get(path, params=None):
    url=BASE+path+('?' + urllib.parse.urlencode(params) if params else '')
    for i in range(6):
        try:
            req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'RISUAP-v038-bounded-census/1'})
            with urllib.request.urlopen(req, timeout=110) as response:
                return json.load(response)
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ConnectionError):
            if i == 5: raise
            time.sleep(min(35,2**i+random.random()))


def official_meta():
    j=get(f'/api/views/{DATASET}.json')
    fields=sorted(c['fieldName'] for c in j['columns'] if c.get('fieldName') in ('corpid_num','film_num','date_filed','name_type','name_status','corp_name'))
    if fields != sorted(['corpid_num','film_num','date_filed','name_type','name_status','corp_name']):
        raise ValueError('Publisher source-column schema changed: '+repr(fields))
    return {'dataset':DATASET,'rows_epoch':j.get('rowsUpdatedAt'),'metadata_epoch':j.get('viewLastModified'),'license':j.get('license'),'fields':fields}


def count(start,end):
    parts=[]
    if start is not None:parts.append(f"date_filed >= '{start}T00:00:00'")
    if end is not None:parts.append(f"date_filed < '{end}T00:00:00'")
    params={'$select':'count(*)'}
    if parts:params['$where']=' AND '.join(parts)
    return int(get(f'/resource/{DATASET}.json',params)[0]['count'])


def midpoint(start,end):
    if start is None:raise ValueError('Historical unbounded interval cannot bisect automatically')
    a,b=dt.date.fromisoformat(start),dt.date.fromisoformat(end)
    d=a+dt.timedelta(days=(b-a).days//2)
    if d<=a or d>=b:raise ValueError('One-day window too large for one bounded transport')
    return d.isoformat()


def plan_one(start,end,n,cap,query,level=0):
    if n<=cap:
        return [{'start_inclusive':start,'end_exclusive':end,'official_rows':n,'depth':level}]
    middle=midpoint(start,end)
    left=query(start,middle);right=query(middle,end)
    if left+right!=n:raise RuntimeError(f'Official source window split does not reconcile: {start}, {middle}, {end}: {n} vs {left}+{right}')
    return plan_one(start,middle,left,cap,query,level+1)+plan_one(middle,end,right,cap,query,level+1)


def build(census,cap,query,edition_check):
    roots=census['windows'];prior=edition_check()
    expected={'rows_epoch':census['publisher']['rows_epoch'],'metadata_epoch':census['publisher']['metadata_epoch'],'license':census['publisher']['license']}
    if any(prior.get(k)!=v for k,v in expected.items()):raise RuntimeError('Publisher edition differs from frozen census; begin a new edition census instead of mixing')
    buckets=[]
    for root in roots:
        a,b,n=root['start_inclusive'],root['end_exclusive'],root['publisher_rows']
        # Re-query every root even when already known, to ensure root counts remain stable.
        current=query(a,b)
        if current!=n:raise RuntimeError(f'Official root source count changed for {a} .. {b}: {current} vs {n}')
        additions=plan_one(a,b,n,cap,query)
        for x in additions:
            x['root_label']=root['label']
            x['partition_id']=f"name_{(x['start_inclusive'] or 'BEGIN').replace('-','')}_{x['end_exclusive'].replace('-','')}"
            buckets.append(x)
        print('PLAN_ROOT',root['label'],n,'partitions',len(additions),file=sys.stderr,flush=True)
    current_total=query(None,None)
    if current_total!=census['full_rows'] or sum(x['official_rows'] for x in buckets)!=current_total or census['rows_without_filed_date']!=0:
        raise RuntimeError('Full source census or date coverage does not reconcile')
    if buckets[0]['start_inclusive'] is not None or buckets[-1]['end_exclusive']!='2027-01-01':raise RuntimeError('Unbounded source-date coverage missing')
    for l,r in zip(buckets,buckets[1:]):
        if l['end_exclusive']!=r['start_inclusive']:raise RuntimeError('Source date ranges have gaps or overlaps')
    if len({x['partition_id'] for x in buckets})!=len(buckets):raise RuntimeError('Duplicate partition ID')
    after=edition_check()
    if after!=prior:raise RuntimeError('Publisher edition changed during partition plan; discard plan')
    census_hash=hashlib.sha256(json.dumps(census,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'schema':'risuap-v038-name-source-complete-partition-plan-v1','status':'official_count_only_not_acquired',
        'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'source_census_sha256':census_hash,
        'publisher_edition_before':prior,'publisher_edition_after':after,
        'source_dataset':DATASET,'complete_population_rows':current_total,
        'exclusion_null_filing_date':0,'max_rows_per_partition':cap,
        'partitions':buckets,'partition_count':len(buckets)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--census',type=pathlib.Path,required=True)
    p.add_argument('--out',type=pathlib.Path,required=True);p.add_argument('--cap',type=int,default=100000)
    a=p.parse_args();
    if not 10000<=a.cap<=110000:raise ValueError('Unsafe partition cap')
    census=json.loads(a.census.read_text())
    if census['schema']!='risuap-v038-official-name-source-census-v1':raise ValueError('Unsupported input census schema')
    res=build(census,a.cap,count,official_meta)
    a.out.write_text(json.dumps(res,indent=2,sort_keys=True)+'\n')
    print('VALID_PARTITION_PLAN',res['partition_count'],res['complete_population_rows'],file=sys.stderr)

if __name__=='__main__':main()
