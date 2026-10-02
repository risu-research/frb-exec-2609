#!/usr/bin/env python3
import csv,gzip,hashlib,io,ipaddress,json,lzma,os,re,statistics,time
from collections import defaultdict,Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,datetime,timedelta,timezone
import requests
OUT='out4';os.makedirs(OUT,exist_ok=True)
BASE='https://data.caida.org/datasets/routing/routeviews-prefix2as/2026/09/'
CHECK=['20260907','20260914','20260923','20260930'];N=100
WS=datetime(2026,9,10,tzinfo=timezone.utc);WE=datetime(2026,10,2,tzinfo=timezone.utc)
TALS=['afrinic.tal','apnic.tal','arin.tal','lacnic.tal','ripencc.tal']

def req(u,params=None,timeout=90):
 for i in range(4):
  try:
   r=requests.get(u,params=params,timeout=timeout,headers={'User-Agent':'neutral-routing-pilot/3.0'});r.raise_for_status();return r
  except Exception:
   if i==3:raise
   time.sleep(i+1)

def caida(day):
 h=req(BASE,timeout=30).text;m=re.search(r'href="(routeviews-rv2-'+day+r'-\d{4}\.pfx2as\.gz)"',h)
 if not m:raise RuntimeError(day)
 u=BASE+m.group(1);o={}
 for z in gzip.decompress(req(u).content).decode('utf8','replace').splitlines():
  q=z.split('\t')
  if len(q)<3 or not q[2].isdigit():continue
  try:n=ipaddress.ip_network(q[0]+'/'+q[1],strict=False);a=int(q[2])
  except:continue
  if n.version==4 and 8<=n.prefixlen<=24 and a>0 and a!=23456:o[str(n)]=a
 return u,o

def todt(x):
 d=datetime.fromisoformat(str(x).replace('Z','+00:00'));return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def rh(c):
 p,a,b=c;j=req('https://stat.ripe.net/data/routing-history/data.json',params={'resource':p,'starttime':WS.isoformat(),'endtime':WE.isoformat(),'min_peers':10,'normalise_visibility':'true','max_rows':100},timeout=60).json()['data'];g={a:[],b:[]}
 for bo in j.get('by_origin',[]):
  try:o=int(str(bo.get('origin')).replace('AS',''))
  except:continue
  if o not in g:continue
  for pe in bo.get('prefixes',[]):
   if pe.get('prefix')!=p:continue
   for t in pe.get('timelines',[]):
    try:s,e=todt(t['starttime']),todt(t['endtime'])
    except:continue
    g[o].append((s,e))
 cut=datetime(2026,9,14,tzinfo=timezone.utc);old=[x for x in g[a] if x[0]<=cut<=x[1]] or g[a];new=[x for x in g[b] if x[1]>=cut]
 oe=max((x[1] for x in old),default=None);ns=min((x[0] for x in new),default=None)
 return None if not oe or not ns else {'prefix':p,'old_asn':a,'new_asn':b,'new_start':ns.isoformat(),'old_end':oe.isoformat(),'time_granularity':j.get('time_granularity')}

def ancestors(p):
 n=ipaddress.ip_network(p);z=[str(n)]
 while n.prefixlen:n=n.supernet();z.append(str(n))
 return z

def parse_roa(blob,want):
 rd=csv.DictReader(io.StringIO(lzma.decompress(blob).decode('utf8','replace')));o=defaultdict(list)
 for r in rd:
  p=r.get('IP Prefix') or r.get('prefix') or r.get('Prefix')
  if p not in want:continue
  try:a=int(str(r.get('ASN') or r.get('asn')).upper().replace('AS',''));m=int(r.get('Max Length') or r.get('maxLength') or r.get('max_length'))
  except:continue
  o[p].append((a,m))
 return o

def rf(x):
 d,t,w=x;u=f'https://ftp.ripe.net/rpki/{t}/{d.year:04d}/{d.month:02d}/{d.day:02d}/roas.csv.xz'
 try:return d,t,parse_roa(req(u).content,w),None
 except Exception as e:return d,t,None,repr(e)

def status(p,a,roas,A):
 L=ipaddress.ip_network(p).prefixlen;z=[(x,m) for q in A[p] for x,m in roas.get(q,[]) if L<=m]
 if any(x==a for x,_ in z):return 'valid'
 return 'invalid' if z else 'notfound'
def dr(a,b):
 while a<=b:yield a;a+=timedelta(days=1)
def ekey(r):return f"{r['old_asn']}->{r['new_asn']}@{r['new_start']}|{r['old_end']}"

def main():
 got={}
 with ThreadPoolExecutor(max_workers=4) as ex:
  fs={ex.submit(caida,d):d for d in CHECK}
  for f in as_completed(fs):got[fs[f]]=f.result()
 maps=[got[d][1] for d in CHECK];common=set.intersection(*map(set,maps));cand=[]
 for p in common:
  x=[m[p] for m in maps]
  if x[0]==x[1] and x[2]==x[3] and x[0]!=x[2]:cand.append((p,x[0],x[2]))
 cand.sort(key=lambda x:hashlib.sha256('|'.join(map(str,x)).encode()).hexdigest());val=[]
 with ThreadPoolExecutor(max_workers=16) as ex:
  fs={ex.submit(rh,c):c for c in cand[:360]}
  for f in as_completed(fs):
   try:r=f.result()
   except:continue
   if r:val.append(r)
 val.sort(key=lambda r:hashlib.sha256(r['prefix'].encode()).hexdigest());val=val[:N]
 if len(val)<N:raise RuntimeError(f'only {len(val)}')
 P=[r['prefix'] for r in val];A={p:ancestors(p) for p in P};want={q for p in P for q in A[p]};D=list(dr(date(2026,9,10),date(2026,10,2)));per=defaultdict(lambda:defaultdict(list));ok=defaultdict(int)
 with ThreadPoolExecutor(max_workers=10) as ex:
  fs=[ex.submit(rf,(d,t,want)) for d in D for t in TALS]
  for f in as_completed(fs):
   d,t,o,e=f.result()
   if o is None:continue
   ok[d]+=1
   for p,z in o.items():per[d][p].extend(z)
 daily={p:{} for p in P}
 for d in D:
  if not ok[d]:continue
  ds=d.isoformat();roas=per[d]
  for r in val:
   p=r['prefix'];daily[p][ds]={'old':status(p,r['old_asn'],roas,A),'new':status(p,r['new_asn'],roas,A)}
 for r in val:
  p=r['prefix'];h=daily[p];keys=sorted(h);ns=todt(r['new_start']);oe=todt(r['old_end']);d0=ns.date();de=oe.date();prev=(d0-timedelta(days=1)).isoformat();same=d0.isoformat();nexts=(d0+timedelta(days=1)).isoformat();oldnext=(de+timedelta(days=1)).isoformat()
  future=[d for d in keys if date.fromisoformat(d)>=d0 and h[d]['new']=='valid'];fv=future[0] if future else None;oldvalid=[d for d in keys if h[d]['old']=='valid'];lo=oldvalid[-1] if oldvalid else None
  r['event_key']=ekey(r);r['rpki']={'new_prev_day':h.get(prev,{}).get('new'),'new_transition_day_snapshot':h.get(same,{}).get('new'),'new_next_day':h.get(nexts,{}).get('new'),'old_day_after_observed_end':h.get(oldnext,{}).get('old'),'new_day_after_old_end':h.get(oldnext,{}).get('new'),'first_new_valid_on_or_after_start':fv,'future_valid_lag_days':((date.fromisoformat(fv)-d0).days if fv else None),'last_old_valid_day':lo,'old_retention_days_proxy':((date.fromisoformat(lo)-de).days if lo else None),'old_retention_right_censored':bool(lo and keys and lo==keys[-1])}
 def summarize(items):
  C=Counter();lags=[];tails=[];rc=0
  for r in items:
   x=r['rpki'];s=x['new_transition_day_snapshot'];n=x['new_next_day'];p=x['new_prev_day'];on=x['old_day_after_observed_end'];nn=x['new_day_after_old_end']
   C['new_prev_valid']+=p=='valid';C['transition_snapshot_valid']+=s=='valid';C['transition_snapshot_invalid']+=s=='invalid';C['transition_snapshot_notfound']+=s=='notfound';C['new_invalid_next_day']+=n=='invalid';C['new_notfound_next_day']+=n=='notfound';C['new_valid_next_day']+=n=='valid';C['old_valid_day_after_end']+=on=='valid';C['dual_valid_day_after_old_end']+=(on=='valid' and nn=='valid');C['old_prev_valid_and_new_invalid_next_day']+=(p=='valid' and n=='invalid')
   if x['future_valid_lag_days'] is not None:lags.append(x['future_valid_lag_days'])
   if x['old_retention_days_proxy'] is not None and x['old_retention_days_proxy']>=0:tails.append(x['old_retention_days_proxy'])
   rc+=x['old_retention_right_censored']
  return {'n':len(items),'counts':dict(C),'future_new_valid_lag_days_median':statistics.median(lags) if lags else None,'future_new_valid_lag_days_range':[min(lags),max(lags)] if lags else None,'old_retention_nonnegative_n':len(tails),'old_retention_days_proxy_median':statistics.median(tails) if tails else None,'old_retention_right_censored_n':rc}
 # event representatives: deterministic smallest prefix per identical AS-pair/timing event
 groups=defaultdict(list)
 for r in val:groups[r['event_key']].append(r)
 reps=[sorted(z,key=lambda r:ipaddress.ip_network(r['prefix']).network_address)[0] for z in groups.values()]
 summary={'raw_four_snapshot_candidates':len(cand),'prefix_sample':summarize(val),'distinct_event_sample':summarize(reps),'distinct_event_count':len(reps),'largest_prefix_cluster':max(map(len,groups.values())),'cluster_size_histogram':dict(sorted(Counter(map(len,groups.values())).items())),'population':'exact IPv4 prefix is single-origin A in CAIDA Sep7+Sep14 and single-origin B in Sep23+Sep30; independently both origins appear in RIPE RIS routing-history min_peers=10; deterministic hash sample of 100 cross-validated prefixes; identical (old ASN,new ASN,new_start,old_end) grouped as one operational event','conservative_signal':'new_invalid_next_day is the day-scale mismatch signal; transition-day snapshot alone is not used to infer within-day ordering','guardrails':['notfound is not RPKI-invalid','authorization retention is not called stale without evidence old origin is no longer an intended backup','daily RPKI and 8-hour routing-history bins motivate exact-update/finer-RPKI follow-up for sub-day claims','observed origin change is not automatically a legitimate transfer'],'caida_sources':[got[d][0] for d in CHECK]}
 open(OUT+'/summary.json','w').write(json.dumps(summary,indent=2,sort_keys=True));open(OUT+'/records.json','w').write(json.dumps(val,indent=2,sort_keys=True));open(OUT+'/events.json','w').write(json.dumps(reps,indent=2,sort_keys=True));open(OUT+'/daily.json','w').write(json.dumps(daily,sort_keys=True));print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
