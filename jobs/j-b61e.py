#!/usr/bin/env python3
import csv,gzip,hashlib,io,ipaddress,json,lzma,os,re,statistics,time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,datetime,timedelta,timezone
import requests
OUT='out3';os.makedirs(OUT,exist_ok=True)
BASE='https://data.caida.org/datasets/routing/routeviews-prefix2as/2026/09/'
CHECK=['20260907','20260914','20260923','20260930'];N=60
WS=datetime(2026,9,10,tzinfo=timezone.utc);WE=datetime(2026,10,2,tzinfo=timezone.utc)
TALS=['afrinic.tal','apnic.tal','arin.tal','lacnic.tal','ripencc.tal']

def req(u,params=None,timeout=90):
 for i in range(4):
  try:
   r=requests.get(u,params=params,timeout=timeout,headers={'User-Agent':'neutral-routing-confirm/1.0'});r.raise_for_status();return r
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

def hist(c):
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
 n=ipaddress.ip_network(p);o=[str(n)]
 while n.prefixlen:n=n.supernet();o.append(str(n))
 return o

def parse_roa(blob,want):
 rd=csv.DictReader(io.StringIO(lzma.decompress(blob).decode('utf8','replace')));o=defaultdict(list)
 for r in rd:
  p=r.get('IP Prefix') or r.get('prefix') or r.get('Prefix')
  if p not in want:continue
  try:a=int(str(r.get('ASN') or r.get('asn')).upper().replace('AS',''));m=int(r.get('Max Length') or r.get('maxLength') or r.get('max_length'))
  except:continue
  o[p].append((a,m))
 return o

def roa_file(x):
 d,t,w=x;u=f'https://ftp.ripe.net/rpki/{t}/{d.year:04d}/{d.month:02d}/{d.day:02d}/roas.csv.xz'
 try:return d,t,parse_roa(req(u).content,w),None
 except Exception as e:return d,t,None,repr(e)

def applicable(p,roas,A):
 L=ipaddress.ip_network(p).prefixlen;return [(a,m) for q in A[p] for a,m in roas.get(q,[]) if L<=m]
def status(p,a,roas,A):
 z=applicable(p,roas,A)
 if any(x==a for x,_ in z):return 'valid'
 return 'invalid' if z else 'notfound'
def days(a,b):
 while a<=b:yield a;a+=timedelta(days=1)

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
 with ThreadPoolExecutor(max_workers=12) as ex:
  fs={ex.submit(hist,c):c for c in cand[:180]}
  for f in as_completed(fs):
   try:r=f.result()
   except:continue
   if r:val.append(r)
 val.sort(key=lambda r:hashlib.sha256(r['prefix'].encode()).hexdigest());val=val[:N]
 if len(val)<50:raise RuntimeError(len(val))
 P=[r['prefix'] for r in val];A={p:ancestors(p) for p in P};want={q for p in P for q in A[p]};D=list(days(date(2026,9,10),date(2026,10,2)));per=defaultdict(lambda:defaultdict(list));ok=defaultdict(int)
 with ThreadPoolExecutor(max_workers=10) as ex:
  fs=[ex.submit(roa_file,(d,t,want)) for d in D for t in TALS]
  for f in as_completed(fs):
   d,t,o,e=f.result()
   if o is None:continue
   ok[d]+=1
   for p,z in o.items():per[d][p].extend(z)
 daily={p:{} for p in P}
 for d in D:
  if not ok[d]:continue
  roas=per[d];ds=d.isoformat()
  for r in val:
   p=r['prefix'];daily[p][ds]={'old':status(p,r['old_asn'],roas,A),'new':status(p,r['new_asn'],roas,A)}
 C=defaultdict(int);leads=[];tails=[];rc=0
 for r in val:
  p=r['prefix'];h=daily[p];keys=sorted(h);ns=todt(r['new_start']);oe=todt(r['old_end']);prev=(ns.date()-timedelta(days=1)).isoformat();same=ns.date().isoformat();nxt=(oe.date()+timedelta(days=1)).isoformat()
  old_prev=h.get(prev,{}).get('old');new_prev=h.get(prev,{}).get('new');new_same=h.get(same,{}).get('new');old_same=h.get(same,{}).get('old');old_next=h.get(nxt,{}).get('old');new_next=h.get(nxt,{}).get('new')
  new_valid_days=[x for x in keys if h[x]['new']=='valid'];old_valid_days=[x for x in keys if h[x]['old']=='valid'];fn=new_valid_days[0] if new_valid_days else None;lo=old_valid_days[-1] if old_valid_days else None;right=bool(lo and keys and lo==keys[-1])
  if new_prev=='valid':C['new_valid_prev_day']+=1
  if new_same=='valid':C['new_valid_same_day']+=1
  elif new_same=='invalid':C['new_invalid_same_day']+=1
  elif new_same=='notfound':C['new_notfound_same_day']+=1
  else:C['new_same_day_unresolved']+=1
  if old_prev=='valid' and new_same=='invalid':C['old_valid_prev_to_new_invalid']+=1
  if old_same=='valid' and new_same=='valid':C['dual_valid_on_new_start_day']+=1
  if old_next=='valid':C['old_valid_day_after_observed_end']+=1
  if old_next=='valid' and new_next=='valid':C['dual_valid_day_after_old_end']+=1
  if fn:leads.append((date.fromisoformat(fn)-ns.date()).days)
  if lo:
   t=(date.fromisoformat(lo)-oe.date()).days
   if t>=0:tails.append(t)
   if right:rc+=1
  r['rpki']={'old_prev_day':old_prev,'new_prev_day':new_prev,'old_on_new_start_day':old_same,'new_on_start_day':new_same,'old_day_after_end':old_next,'new_day_after_old_end':new_next,'first_new_valid_day':fn,'new_valid_minus_start_days':((date.fromisoformat(fn)-ns.date()).days if fn else None),'last_old_valid_day':lo,'old_retention_days_proxy':((date.fromisoformat(lo)-oe.date()).days if lo else None),'old_retention_right_censored':right}
 summary={'raw_four_snapshot_candidates':len(cand),'validated_n':len(val),'counts':dict(C),'new_valid_minus_bgp_start_days_median':statistics.median(leads) if leads else None,'new_valid_minus_bgp_start_days_range':[min(leads),max(leads)] if leads else None,'old_authorization_retention_days_nonnegative_n':len(tails),'old_authorization_retention_days_proxy_median':statistics.median(tails) if tails else None,'old_authorization_retention_right_censored_n':rc,'interpretation_guardrails':['invalid means at least one covering/maxLength-applicable VRP exists but none authorizes observed new ASN','notfound means no applicable VRP; do not count as RPKI-invalid','authorization retention is not labeled stale without evidence that old origin is no longer an intended backup','routing-history bins and daily RPKI snapshots only support day-scale pilot claims; exact event timing needs MRT/update refinement'],'population':'single-origin A on CAIDA Sep7+Sep14; single-origin B on Sep23+Sep30; A!=B; independently seen for both origins by RIPE RIS routing-history min_peers=10; deterministic hash sample n=60','caida_sources':[got[d][0] for d in CHECK]}
 open(OUT+'/summary.json','w').write(json.dumps(summary,indent=2,sort_keys=True));open(OUT+'/records.json','w').write(json.dumps(val,indent=2,sort_keys=True));open(OUT+'/daily.json','w').write(json.dumps(daily,sort_keys=True));print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
