#!/usr/bin/env python3
# frozen pilot v2: four CAIDA snapshots -> RIPE RIS history -> daily historical RPKI
import csv,gzip,hashlib,io,ipaddress,json,lzma,os,re,statistics,time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,datetime,timedelta,timezone
import requests
OUT='out2';os.makedirs(OUT,exist_ok=True)
BASE='https://data.caida.org/datasets/routing/routeviews-prefix2as/2026/09/'
CHECK=['20260907','20260914','20260923','20260930'];N=60
WS=datetime(2026,9,10,tzinfo=timezone.utc);WE=datetime(2026,10,2,tzinfo=timezone.utc)
TALS=['afrinic.tal','apnic.tal','arin.tal','lacnic.tal','ripencc.tal']

def req(url,params=None,timeout=90):
    for i in range(4):
        try:
            r=requests.get(url,params=params,timeout=timeout,headers={'User-Agent':'neutral-public-routing-pilot/2.0'});r.raise_for_status();return r
        except Exception:
            if i==3:raise
            time.sleep(i+1)

def caida(day):
    h=req(BASE,timeout=30).text
    m=re.search(r'href="(routeviews-rv2-'+day+r'-\d{4}\.pfx2as\.gz)"',h)
    if not m:raise RuntimeError('missing '+day)
    u=BASE+m.group(1);txt=gzip.decompress(req(u).content).decode('utf8','replace');o={}
    for z in txt.splitlines():
        q=z.split('\t');
        if len(q)<3 or not q[2].isdigit():continue
        try:
            pl=int(q[1]);a=int(q[2]);n=ipaddress.ip_network(q[0]+'/'+q[1],strict=False)
            if n.version==4 and 8<=pl<=24 and a>0 and a!=23456:o[str(n)]=a
        except:pass
    return u,o

def dt(x):
    if x is None:return None
    if isinstance(x,(int,float)):return datetime.fromtimestamp(x,tz=timezone.utc)
    y=datetime.fromisoformat(str(x).replace('Z','+00:00'));return y if y.tzinfo else y.replace(tzinfo=timezone.utc)

def history(c):
    p,a,b=c
    j=req('https://stat.ripe.net/data/routing-history/data.json',params={'resource':p,'starttime':WS.isoformat(),'endtime':WE.isoformat(),'min_peers':10,'normalise_visibility':'true','max_rows':100},timeout=60).json()['data']
    g={a:[],b:[]}
    for bo in j.get('by_origin',[]):
        try:o=int(str(bo.get('origin')).replace('AS',''))
        except:continue
        if o not in g:continue
        for pe in bo.get('prefixes',[]):
            if pe.get('prefix')!=p:continue
            for t in pe.get('timelines',[]):
                s,e=dt(t.get('starttime')),dt(t.get('endtime'))
                if s and e:g[o].append((s,e,t.get('visibility')))
    cut=datetime(2026,9,14,tzinfo=timezone.utc)
    old=[x for x in g[a] if x[0]<=cut<=x[1]] or g[a]
    new=[x for x in g[b] if x[1]>=cut]
    oe=max((x[1] for x in old),default=None);ns=min((x[0] for x in new),default=None)
    if not oe or not ns:return None
    return {'prefix':p,'old_asn':a,'new_asn':b,'routing':{'new_start':ns.isoformat(),'old_end':oe.isoformat(),'time_granularity':j.get('time_granularity'),'old_segments':len(g[a]),'new_segments':len(g[b])}}

def sups(p):
    n=ipaddress.ip_network(p);out=[str(n)]
    while n.prefixlen>0:
        n=n.supernet();out.append(str(n))
    return out

def parse_roa(blob,wanted):
    rd=csv.DictReader(io.StringIO(lzma.decompress(blob).decode('utf8','replace')));o=defaultdict(list)
    for r in rd:
        p=r.get('IP Prefix') or r.get('prefix') or r.get('Prefix')
        if p not in wanted:continue
        try:a=int(str(r.get('ASN') or r.get('asn')).upper().replace('AS',''));m=int(r.get('Max Length') or r.get('maxLength') or r.get('max_length'))
        except:continue
        o[p].append((a,m))
    return o

def one_roa_file(args):
    d,tal,wanted=args;u=f'https://ftp.ripe.net/rpki/{tal}/{d.year:04d}/{d.month:02d}/{d.day:02d}/roas.csv.xz'
    try:return d,tal,parse_roa(req(u,timeout=90).content,wanted),None
    except Exception as e:return d,tal,None,repr(e)

def valid(p,a,roas,S):
    L=ipaddress.ip_network(p).prefixlen
    return any(x==a and L<=m for q in S[p] for x,m in roas.get(q,[]))

def daterange(a,b):
    while a<=b:yield a;a+=timedelta(days=1)

def main():
    sources=[];maps=[]
    with ThreadPoolExecutor(max_workers=4) as ex:
        fs={ex.submit(caida,d):d for d in CHECK};got={}
        for f in as_completed(fs):
            u,m=f.result();got[fs[f]]=(u,m);print('CAIDA',fs[f],len(m),flush=True)
    for d in CHECK:u,m=got[d];sources.append(u);maps.append(m)
    common=set.intersection(*[set(m) for m in maps]);cand=[]
    for p in common:
        a0,a1,b0,b1=[m[p] for m in maps]
        if a0==a1 and b0==b1 and a0!=b0:cand.append((p,a0,b0))
    cand.sort(key=lambda x:hashlib.sha256('|'.join(map(str,x)).encode()).hexdigest())
    print('persistent candidates',len(cand),flush=True)
    val=[]
    with ThreadPoolExecutor(max_workers=12) as ex:
        fs={ex.submit(history,c):c for c in cand[:180]}
        for f in as_completed(fs):
            try:r=f.result()
            except Exception as e:print('history skip',fs[f][0],repr(e),flush=True);continue
            if r:val.append(r)
    val.sort(key=lambda r:hashlib.sha256(r['prefix'].encode()).hexdigest());val=val[:N]
    print('RIS-crossvalidated',len(val),flush=True)
    if len(val)<50:raise RuntimeError('fewer than 50 transitions after RIS cross-validation')
    P=[r['prefix'] for r in val];S={p:sups(p) for p in P};wanted={q for p in P for q in S[p]};hist={p:{} for p in P}
    dates=list(daterange(date(2026,9,10),date(2026,10,2)));tasks=[(d,t,wanted) for d in dates for t in TALS];per=defaultdict(lambda:defaultdict(list));ok=defaultdict(int)
    with ThreadPoolExecutor(max_workers=10) as ex:
        fs=[ex.submit(one_roa_file,x) for x in tasks]
        for f in as_completed(fs):
            d,t,o,e=f.result()
            if o is None:print('RPKI skip',d,t,e,flush=True);continue
            ok[d]+=1
            for p,z in o.items():per[d][p].extend(z)
    for d in dates:
        if not ok[d]:continue
        roas=per[d];ds=d.isoformat()
        for r in val:
            p=r['prefix'];hist[p][ds]={'old':valid(p,r['old_asn'],roas,S),'new':valid(p,r['new_asn'],roas,S)}
        print('RPKI',d,'files',ok[d],flush=True)
    for r in val:
        p=r['prefix'];h=hist[p];D=sorted(h);ns=dt(r['routing']['new_start']);oe=dt(r['routing']['old_end'])
        newdays=[x for x in D if h[x]['new']];olddays=[x for x in D if h[x]['old']]
        fn=newdays[0] if newdays else None;lo=olddays[-1] if olddays else None
        prev=(ns.date()-timedelta(days=1)).isoformat();same=ns.date().isoformat();nxt=(oe.date()+timedelta(days=1)).isoformat()
        r['rpki']={'first_new_day':fn,'new_valid_prev_day':h.get(prev,{}).get('new'),'new_valid_same_day':h.get(same,{}).get('new'),'new_auth_minus_bgp_days':(date.fromisoformat(fn)-ns.date()).days if fn else None,'last_old_day':lo,'old_valid_next_day':h.get(nxt,{}).get('old'),'old_auth_tail_days_proxy':(date.fromisoformat(lo)-oe.date()).days if lo else None,'old_tail_right_censored':bool(lo and D and lo==D[-1])}
    C=defaultdict(int);lead=[];tail=[]
    for r in val:
        x=r['rpki']
        if x['new_valid_prev_day'] is True:C['new_preauthorized_prev_day']+=1
        elif x['new_valid_same_day'] is True:C['new_same_day_only_or_earlier']+=1
        elif x['new_valid_same_day'] is False:C['new_not_authorized_same_day']+=1
        else:C['new_timing_unresolved']+=1
        if x['old_valid_next_day'] is True:C['old_still_authorized_next_day']+=1
        if x['new_auth_minus_bgp_days'] is not None:lead.append(x['new_auth_minus_bgp_days'])
        if x['old_auth_tail_days_proxy'] is not None and x['old_auth_tail_days_proxy']>=0:tail.append(x['old_auth_tail_days_proxy'])
    summary={'raw_four_snapshot_candidates':len(cand),'validated_n':len(val),'class_counts':dict(C),'new_auth_minus_bgp_days_median':statistics.median(lead) if lead else None,'new_auth_minus_bgp_days_range':[min(lead),max(lead)] if lead else None,'old_auth_tail_days_proxy_median':statistics.median(tail) if tail else None,'old_auth_tail_nonnegative_n':len(tail),'caida_sources':sources,'population_definition':'exact IPv4 single-origin A at Sep7/Sep14 and single-origin B at Sep23/Sep30 in CAIDA rv2; both origins independently visible in RIPE RIS routing history with min_peers=10','caveats':['pilot uses RIPE routing-history time bins; final event timing must use exact BGP updates','RPKI is daily so within-day ordering remains unresolved','persistent observed origin transitions are not automatically asserted legitimate transfers','old authorization tails may be right-censored']}
    open(OUT+'/summary.json','w').write(json.dumps(summary,indent=2,sort_keys=True));open(OUT+'/records.json','w').write(json.dumps(val,indent=2,sort_keys=True));open(OUT+'/daily.json','w').write(json.dumps(hist,sort_keys=True))
    with open(OUT+'/records.csv','w',newline='') as f:
        F=['prefix','old_asn','new_asn','new_start','old_end','time_granularity','first_new_day','new_valid_prev_day','new_valid_same_day','new_auth_minus_bgp_days','last_old_day','old_valid_next_day','old_auth_tail_days_proxy','old_tail_right_censored'];w=csv.DictWriter(f,fieldnames=F);w.writeheader()
        for r in val:
            q=r['routing'];w.writerow({'prefix':r['prefix'],'old_asn':r['old_asn'],'new_asn':r['new_asn'],'new_start':q['new_start'],'old_end':q['old_end'],'time_granularity':q['time_granularity'],**r['rpki']})
    print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
