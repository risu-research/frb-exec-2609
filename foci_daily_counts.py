#!/usr/bin/env python3
"""Independent daily aggregation of the existing 42-host EU27 OONI cohort.
One country-wide grouped public-data query per observed country, fallback to
seven shorter time windows. Daily-level only, not session proof.
"""
import csv,datetime as dt,json,sys,random,time,urllib.parse,urllib.request,pathlib
SRC=pathlib.Path("prior/eu27_host_period.csv")
D=pathlib.Path("daily_output");D.mkdir(exist_ok=True)
base=list(csv.DictReader(SRC.open()))
countries=sorted(set(r['country'] for r in base if int(r['measurement_count'])>0))
hosts=sorted(set(r['hostname'] for r in base))
expected={cc:sum(int(r['measurement_count']) for r in base if r['country']==cc) for cc in countries}
assert sum(expected.values())==3319 and len(hosts)==42 and len(countries)==16
periods=sorted(set((r['since'],r['until_exclusive']) for r in base))
def call(cc,lo,hi):
 p={'domain':','.join(hosts),'probe_cc':cc,'test_name':'web_connectivity','since':lo,'until':hi,
    'axis_x':'measurement_start_day','axis_y':'domain','time_grain':'day'}
 url='https://api.ooni.io/api/v1/aggregation?'+urllib.parse.urlencode(p)
 errors=[]
 for a in range(4):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'Academic day-level OONI audit/1.0','Accept':'application/json'})
   with urllib.request.urlopen(req,timeout=65) as f: data=json.load(f)
   body=data.get('result')
   if isinstance(body,dict):body=[body]
   if not isinstance(body,list):raise ValueError('Unexpected aggregate result shape')
   out=[]
   for row in body:
    n=int(row['measurement_count'])
    if n<=0: continue
    h=row.get('domain');day=str(row.get('measurement_start_day') or '')[:10]
    if h not in hosts or len(day)!=10:raise ValueError('Unexpected hostname/day: '+str(row)[:240])
    out.append({'country':cc,'hostname':h,'day':day,'measurement_count':n})
   return out
  except Exception as e:
   errors.append(str(e)[:180]);print('RETRY',cc,lo,a,str(e)[:160],flush=True)
   time.sleep(3+a*4+random.random())
 raise RuntimeError(str(errors))
out=[];result=[];failures=[]
for cc in countries:
 try:
  try:
   a=call(cc,'2025-04-09','2026-10-30');method='full-period'
  except Exception as e:
   print('FALLBACK',cc,'to seven bounded windows',str(e)[:110],flush=True)
   a=[]
   for lo,hi in periods:
    a+=call(cc,lo,hi)
    time.sleep(.4)
   method='seven-period-fallback'
  found=sum(r['measurement_count'] for r in a)
  result.append({'country':cc,'expected':expected[cc],'downloaded':found,'method':method,'matched':found==expected[cc]})
  out+=a
  if found!=expected[cc]:failures.append({'country':cc,'error':f'count mismatch {found} vs {expected[cc]}'})
  print('DAILY',cc,'expected',expected[cc],'downloaded',found,'daycells',len(a),'method',method,flush=True)
 except Exception as e:
  failures.append({'country':cc,'error':str(e)})
  print('DAILY_FAILED',cc,str(e)[:190],flush=True)
 time.sleep(.8)
for name,rows,fields in [
 ('daily_host_counts.csv',out,['country','hostname','day','measurement_count']),
 ('country_reconciliation.csv',result,['country','expected','downloaded','method','matched']),
 ('failures.csv',failures,['country','error'])]:
 with (D/name).open('w',newline='',encoding='utf8') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
manifest={'completed':not failures and sum(r['measurement_count'] for r in out)==3319,
 'countries':len(countries),'country_completed':len(result),'failures':len(failures),
 'recovered_total':sum(r['measurement_count'] for r in out),'original_total':3319,
 'rows':len(out),'timestamp_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
(D/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('DAILY_FINAL',json.dumps(manifest),flush=True)
if not manifest['completed']:sys.exit(2)
