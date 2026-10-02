#!/usr/bin/env python3
# frozen pilot v1
import csv, gzip, hashlib, io, ipaddress, json, lzma, os, re, statistics, time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import requests

S = requests.Session()
S.headers.update({'User-Agent':'neutral-public-routing-pilot/1.0'})
OUT='out2'; os.makedirs(OUT, exist_ok=True)
BASE='https://data.caida.org/datasets/routing/routeviews-prefix2as/2026/09/'
CHECK_DATES=['20260907','20260914','20260923','20260930']
WINDOW_START=datetime(2026,9,10,tzinfo=timezone.utc)
WINDOW_END=datetime(2026,10,2,tzinfo=timezone.utc)
TALS=['afrinic.tal','apnic.tal','arin.tal','lacnic.tal','ripencc.tal']
N_TARGET=80


def get(url, **kw):
    for i in range(4):
        try:
            timeout=kw.pop('timeout',90)
            r=S.get(url, timeout=timeout, **kw)
            r.raise_for_status(); return r
        except Exception:
            if i==3: raise
            time.sleep(1.0*(i+1))


def caida_url(day):
    html=get(BASE, timeout=30).text
    m=re.search(r'href="(routeviews-rv2-'+day+r'-\d{4}\.pfx2as\.gz)"', html)
    if not m: raise RuntimeError('no CAIDA file for '+day)
    return BASE+m.group(1)


def load_pfx2as(day):
    url=caida_url(day)
    raw=gzip.decompress(get(url, timeout=90).content).decode('utf-8','replace')
    out={}
    for line in raw.splitlines():
        parts=line.split('\t')
        if len(parts)<3: continue
        ip, plen, origin=parts[:3]
        if not origin.isdigit(): continue
        try:
            plen_i=int(plen); asn=int(origin)
            if asn<=0 or asn==23456 or not (8<=plen_i<=24): continue
            net=ipaddress.ip_network(f'{ip}/{plen_i}', strict=False)
            if net.version!=4: continue
        except Exception: continue
        out[str(net)]=asn
    return url,out


def parse_dt(x):
    if x is None: return None
    if isinstance(x,(int,float)): return datetime.fromtimestamp(x,tz=timezone.utc)
    s=str(x).replace('Z','+00:00')
    d=datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def route_history(prefix,a,b):
    url='https://stat.ripe.net/data/routing-history/data.json'
    params={
      'resource':prefix,'starttime':WINDOW_START.isoformat(),'endtime':WINDOW_END.isoformat(),
      'min_peers':10,'normalise_visibility':'true','include_first_hop':'false','max_rows':100
    }
    j=get(url,params=params,timeout=60).json()['data']
    got={a:[],b:[]}
    for bo in j.get('by_origin',[]):
        try:o=int(str(bo.get('origin')).replace('AS',''))
        except:continue
        if o not in got: continue
        for pe in bo.get('prefixes',[]):
            if pe.get('prefix')!=prefix: continue
            for t in pe.get('timelines',[]):
                st=parse_dt(t.get('starttime')); en=parse_dt(t.get('endtime'))
                if st and en:
                    got[o].append({'start':st,'end':en,'peers':t.get('full_peers_seeing'),'visibility':t.get('visibility')})
    cutoff=datetime(2026,9,14,tzinfo=timezone.utc)
    old_cross=[x for x in got[a] if x['start']<=cutoff<=x['end']]
    old_end=max((x['end'] for x in (old_cross or got[a])), default=None)
    new_after=[x for x in got[b] if x['end']>=cutoff]
    new_start=min((x['start'] for x in new_after), default=None)
    return {
      'time_granularity':j.get('time_granularity'),
      'old_end':old_end.isoformat() if old_end else None,
      'new_start':new_start.isoformat() if new_start else None,
      'old_segments':len(got[a]),'new_segments':len(got[b]),
      'latest_max_ff_peers':j.get('latest_max_ff_peers')
    }


def bgp_state_check(prefix,when,asn):
    url='https://stat.ripe.net/data/bgp-state/data.json'
    j=get(url,params={'resource':prefix,'timestamp':when.isoformat()},timeout=60).json()['data']
    origins=[]
    for r in j.get('bgp_state',[]):
        if r.get('target_prefix')!=prefix: continue
        path=r.get('path') or []
        if path:
            try: origins.append(int(path[-1]))
            except: pass
    if not origins:return {'n':0,'fraction':None}
    return {'n':len(origins),'fraction':sum(x==asn for x in origins)/len(origins)}


def supernets(prefix):
    n=ipaddress.ip_network(prefix)
    return [str(n)]+[str(x) for x in n.supernets()]


def parse_roas(content,wanted):
    text=lzma.decompress(content).decode('utf-8','replace')
    rd=csv.DictReader(io.StringIO(text)); out=defaultdict(list)
    for row in rd:
        p=row.get('IP Prefix') or row.get('prefix') or row.get('Prefix')
        if p not in wanted: continue
        a=row.get('ASN') or row.get('asn'); ml=row.get('Max Length') or row.get('maxLength') or row.get('max_length')
        try: asn=int(str(a).upper().replace('AS','')); ml=int(ml)
        except: continue
        out[p].append((asn,ml))
    return out


def valid(prefix,asn,roas,sups):
    plen=ipaddress.ip_network(prefix).prefixlen
    return any(ra==asn and plen<=ml for sp in sups[prefix] for ra,ml in roas.get(sp,[]))


def days(a,b):
    while a<=b:
        yield a; a+=timedelta(days=1)


def main():
    maps=[]; sources=[]
    for d in CHECK_DATES:
        u,m=load_pfx2as(d); sources.append(u); maps.append(m); print('CAIDA',d,len(m),flush=True)
    common=set(maps[0])
    for m in maps[1:]: common &= set(m)
    candidates=[]
    for p in common:
        a0,a1,b0,b1=(m[p] for m in maps)
        if a0==a1 and b0==b1 and a0!=b0:
            candidates.append((p,a0,b0))
    candidates.sort(key=lambda x:hashlib.sha256(('|'.join(map(str,x))).encode()).hexdigest())
    print('four-snapshot persistent candidates',len(candidates),flush=True)

    validated=[]
    for i,(p,a,b) in enumerate(candidates[:240],1):
        try:
            h=route_history(p,a,b)
            s0=bgp_state_check(p,datetime(2026,9,14,12,tzinfo=timezone.utc),a)
            s1=bgp_state_check(p,datetime(2026,9,30,12,tzinfo=timezone.utc),b)
        except Exception as e:
            print('skip API',p,repr(e),flush=True); continue
        if not h['old_end'] or not h['new_start']: continue
        if (s0['fraction'] or 0)<0.5 or (s1['fraction'] or 0)<0.5: continue
        validated.append({'prefix':p,'old_asn':a,'new_asn':b,'routing':h,'state_old':s0,'state_new':s1})
        print('validated',len(validated),p,a,b,h['new_start'],h['old_end'],flush=True)
        if len(validated)>=N_TARGET: break
        time.sleep(.04)
    if len(validated)<50:
        raise RuntimeError(f'only {len(validated)} cross-source persistent transitions')

    prefs=[r['prefix'] for r in validated]
    sups={p:supernets(p) for p in prefs}
    wanted={sp for p in prefs for sp in sups[p]}
    hist={p:{} for p in prefs}
    start=date(2026,9,10); end=date(2026,10,2)
    for d in days(start,end):
        roas=defaultdict(list); files=0
        for tal in TALS:
            u=f'https://ftp.ripe.net/rpki/{tal}/{d.year:04d}/{d.month:02d}/{d.day:02d}/roas.csv.xz'
            try:
                rr=get(u,timeout=90)
                part=parse_roas(rr.content,wanted)
                for k,v in part.items(): roas[k].extend(v)
                files+=1
            except Exception as e:
                print('RPKI skip',d,tal,repr(e),flush=True)
        if not files: continue
        ds=d.isoformat()
        for r in validated:
            p=r['prefix']; hist[p][ds]={'old':valid(p,r['old_asn'],roas,sups),'new':valid(p,r['new_asn'],roas,sups)}
        print('RPKI',d,'files',files,flush=True)

    for r in validated:
        p=r['prefix']; st=hist[p]; ds=sorted(st)
        ns=parse_dt(r['routing']['new_start']); oe=parse_dt(r['routing']['old_end'])
        first_new=next((x for x in ds if st[x]['new']),None)
        old_days=[x for x in ds if st[x]['old']]; last_old=old_days[-1] if old_days else None
        prev=(ns.date()-timedelta(days=1)).isoformat() if ns else None
        same=ns.date().isoformat() if ns else None
        nxt=(oe.date()+timedelta(days=1)).isoformat() if oe else None
        r['rpki']={
          'first_new_day':first_new,'new_valid_prev_day':st.get(prev,{}).get('new'),
          'new_valid_same_day':st.get(same,{}).get('new'),'last_old_day':last_old,
          'old_valid_next_day':st.get(nxt,{}).get('old'),
          'new_auth_minus_bgp_days':((date.fromisoformat(first_new)-ns.date()).days if first_new and ns else None),
          'old_auth_tail_days_proxy':((date.fromisoformat(last_old)-oe.date()).days if last_old and oe else None),
          'old_tail_right_censored':bool(last_old and ds and last_old==ds[-1])
        }

    counts=defaultdict(int); leads=[]; tails=[]
    for r in validated:
        x=r['rpki']
        if x['new_valid_prev_day'] is True: counts['new_preauthorized_prev_day']+=1
        elif x['new_valid_same_day'] is True: counts['new_same_day_only_or_earlier']+=1
        elif x['new_valid_same_day'] is False: counts['new_not_authorized_same_day']+=1
        else: counts['new_timing_unresolved']+=1
        if x['old_valid_next_day'] is True: counts['old_still_authorized_next_day']+=1
        if x['old_auth_tail_days_proxy'] is not None and x['old_auth_tail_days_proxy']>=0: tails.append(x['old_auth_tail_days_proxy'])
        if x['new_auth_minus_bgp_days'] is not None: leads.append(x['new_auth_minus_bgp_days'])
    summary={
      'population_definition':'exact IPv4 prefixes single-origin and unchanged at 2026-09-07/14, changed to another single origin and unchanged at 2026-09-23/30 in CAIDA rv2; cross-validated by RIPE RIS routing history and endpoint BGP state >=50% origin share',
      'caida_sources':sources,'raw_four_snapshot_candidates':len(candidates),'validated_n':len(validated),
      'class_counts':dict(counts),'new_auth_minus_bgp_days_median':statistics.median(leads) if leads else None,
      'new_auth_minus_bgp_days_range':[min(leads),max(leads)] if leads else None,
      'old_auth_tail_days_proxy_median':statistics.median(tails) if tails else None,
      'old_auth_tail_nonnegative_n':len(tails),
      'caveats':['RIPE routing-history may aggregate time; use exact BGP updates for final timing.','RPKI archive is daily, so within-day ROA/BGP ordering is unresolved.','Persistent observed origin transition is not asserted to be a legitimate transfer without external ground truth.','Right-censored old authorizations are retained and flagged.']
    }
    with open(f'{OUT}/summary.json','w') as f: json.dump(summary,f,indent=2,sort_keys=True)
    with open(f'{OUT}/records.json','w') as f: json.dump(validated,f,indent=2,sort_keys=True)
    with open(f'{OUT}/daily.json','w') as f: json.dump(hist,f,sort_keys=True)
    fields=['prefix','old_asn','new_asn','new_start','old_end','time_granularity','old_state_fraction','new_state_fraction','first_new_day','new_valid_prev_day','new_valid_same_day','new_auth_minus_bgp_days','last_old_day','old_valid_next_day','old_auth_tail_days_proxy','old_tail_right_censored']
    with open(f'{OUT}/records.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in validated:
            x=r['rpki']; q=r['routing']
            w.writerow({'prefix':r['prefix'],'old_asn':r['old_asn'],'new_asn':r['new_asn'],'new_start':q['new_start'],'old_end':q['old_end'],'time_granularity':q['time_granularity'],'old_state_fraction':r['state_old']['fraction'],'new_state_fraction':r['state_new']['fraction'],**x})
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__': main()
