#!/usr/bin/env python3
import csv, gzip, hashlib, ipaddress, json, lzma, re, shutil, time, urllib.request
from collections import defaultdict
from pathlib import Path

BASE=Path(__file__).resolve().parent
DATA=BASE/'_rpki_fast_data'
OUT=BASE/'results'/'rpki_handoff_fast_20261002'
DATA.mkdir(exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
DATES=['20260901','20260908','20260915']
FILES={
 '20260901':'2026/09/routeviews-rv2-20260901-1200.pfx2as.gz',
 '20260908':'2026/09/routeviews-rv2-20260908-1000.pfx2as.gz',
 '20260915':'2026/09/routeviews-rv2-20260915-1200.pfx2as.gz',
}
TARGET_N=100
UA='risu-research-rpki-fast-pilot/1.1'

def fetch(url,dest,retries=4):
    dest=Path(dest)
    if dest.exists() and dest.stat().st_size: return dest
    tmp=dest.with_suffix(dest.suffix+'.part')
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA})
            with urllib.request.urlopen(req,timeout=120) as r, open(tmp,'wb') as f:
                shutil.copyfileobj(r,f,1024*1024)
            tmp.replace(dest); print('downloaded',url,dest.stat().st_size,flush=True); return dest
        except Exception as e:
            print('retry',i+1,url,e,flush=True)
            try: tmp.unlink()
            except FileNotFoundError: pass
            time.sleep(2**i)
    raise RuntimeError(url)

def load_pfx2as(date):
    rel=FILES[date]
    url='https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/'+rel
    f=fetch(url,DATA/Path(rel).name)
    out={}
    with gzip.open(f,'rt',encoding='utf-8',errors='replace') as g:
        for line in g:
            if not line or line.startswith('#'): continue
            p=line.rstrip('\n').split('\t')
            if len(p)<3: continue
            addr,plen_s,asn=p[0],p[1],p[2].strip()
            if ':' in addr or not asn.isdigit(): continue
            try:
                plen=int(plen_s); net=ipaddress.ip_network(f'{addr}/{plen}',strict=False)
            except Exception: continue
            if net.version==4: out[str(net)]=asn
    print(date,'single-origin IPv4 prefixes',len(out),flush=True)
    return out

def anchors():
    req=urllib.request.Request('https://ftp.ripe.net/rpki/',headers={'User-Agent':UA})
    html=urllib.request.urlopen(req,timeout=60).read().decode('utf-8','replace')
    hs=re.findall(r'href=["\']([^"\']+/)["\']',html,re.I)
    a=sorted({h.strip('/') for h in hs if h not in ('../','./') and '://' not in h and re.fullmatch(r'[A-Za-z0-9_.-]+/',h)})
    print('anchors',a,flush=True); return a

def findcol(names,cands):
    n={re.sub(r'[^a-z0-9]','',x.lower()):x for x in names if x}
    for c in cands:
        k=re.sub(r'[^a-z0-9]','',c.lower())
        if k in n:return n[k]

def load_cover(date,prefixes,als):
    nets={p:ipaddress.ip_network(p) for p in prefixes}
    byo=defaultdict(list)
    for p,n in nets.items(): byo[int(str(n.network_address).split('.')[0])].append(p)
    out=defaultdict(list); used=[]
    y,m,d=date[:4],date[4:6],date[6:8]
    for a in als:
        url=f'https://ftp.ripe.net/rpki/{a}/{y}/{m}/{d}/roas.csv.xz'
        fn=DATA/f'roas.{a}.{date}.csv.xz'
        try: fetch(url,fn,retries=2)
        except Exception: continue
        used.append(a)
        with lzma.open(fn,'rt',encoding='utf-8',errors='replace',newline='') as fh:
            rd=csv.DictReader(fh)
            if not rd.fieldnames: continue
            pc=findcol(rd.fieldnames,['IP Prefix','prefix']); ac=findcol(rd.fieldnames,['ASN','asn']); mc=findcol(rd.fieldnames,['Max Length','maxLength','max_length'])
            if not pc or not ac: raise RuntimeError('bad ROA header '+repr(rd.fieldnames))
            for r in rd:
                raw=(r.get(pc) or '').strip(); aa=(r.get(ac) or '').strip().upper().removeprefix('AS')
                if not raw or ':' in raw or not aa.isdigit():continue
                try:v=ipaddress.ip_network(raw,strict=False)
                except:continue
                if v.version!=4:continue
                rm=(r.get(mc) or '').strip() if mc else ''
                try: mx=int(rm) if rm else v.prefixlen
                except: mx=v.prefixlen
                plist=byo.get(int(str(v.network_address).split('.')[0]),[]) if v.prefixlen>=8 else prefixes
                vs,ve=int(v.network_address),int(v.broadcast_address)
                for p in plist:
                    c=nets[p]
                    if vs<=int(c.network_address) and int(c.broadcast_address)<=ve:
                        out[p].append((aa,v.prefixlen,mx,raw,a))
    print(date,'RPKI anchors used',used,flush=True); return out,used

def status(p,asn,cov):
    plen=ipaddress.ip_network(p).prefixlen
    rs=cov.get(p,[])
    if not rs:return 'notfound'
    return 'valid' if any(a==asn and plen<=mx for a,_pl,mx,_raw,_ta in rs) else 'invalid'

def main():
    d0,d1,d2=DATES
    x0,x1,x2=[load_pfx2as(d) for d in DATES]
    changes=[p for p,a in x0.items() if p in x1 and x1[p]!=a]
    persistent=[p for p in changes if p in x2 and x2[p]==x1[p]]

    # Avoid counting a bulk migration of many prefixes between the same origins as
    # dozens of independent handoffs. One deterministic representative per A->B pair.
    cohorts=defaultdict(list)
    for p in persistent:
        cohorts[(x0[p],x1[p])].append(p)
    reps=[]
    for (A,B), ps in cohorts.items():
        p=min(ps,key=lambda x:hashlib.sha256(x.encode()).hexdigest())
        reps.append((A,B,p,len(ps)))
    sample=sorted(reps,key=lambda z:hashlib.sha256((z[0]+'>'+z[1]).encode()).hexdigest())[:TARGET_N]
    prefixes=[z[2] for z in sample]
    print('changes',len(changes),'persistent_prefixes',len(persistent),'distinct_origin_pairs',len(cohorts),'sample_pairs',len(sample),flush=True)
    if len(sample)<50: raise RuntimeError('fewer than 50 distinct persistent origin-pair transitions')

    als=anchors(); cov={}; meta={}
    for d in DATES: cov[d],meta[d]=load_cover(d,prefixes,als)
    rows=[]
    for A,B,p,cohort_n in sample:
        r={'prefix':p,'old_origin_A':A,'new_origin_B':B,'pair_prefix_count':cohort_n,
           'A_d0':status(p,A,cov[d0]),'B_d0':status(p,B,cov[d0]),
           'A_d1':status(p,A,cov[d1]),'B_d1':status(p,B,cov[d1]),
           'A_d2':status(p,A,cov[d2]),'B_d2':status(p,B,cov[d2])}
        r['B_preauthorized_d0']=r['B_d0']=='valid'
        r['B_invalid_d1']=r['B_d1']=='invalid'
        r['B_notfound_d1']=r['B_d1']=='notfound'
        r['B_valid_d1']=r['B_d1']=='valid'
        r['A_lingering_valid_d1']=r['A_d1']=='valid'
        r['A_lingering_valid_d2']=r['A_d2']=='valid'
        r['dual_valid_d1']=r['A_d1']=='valid' and r['B_d1']=='valid'
        rows.append(r)
    with open(OUT/'events.csv','w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    keys=['B_preauthorized_d0','B_invalid_d1','B_notfound_d1','B_valid_d1','A_lingering_valid_d1','A_lingering_valid_d2','dual_valid_d1']
    counts={k:sum(bool(r[k]) for r in rows) for k in keys}; n=len(rows)
    covered_d1=counts['B_valid_d1']+counts['B_invalid_d1']
    summary={'design':{'source':'CAIDA RouteViews pfx2as daily snapshots','dates':DATES,'files':FILES,'filter':'exact prefix, single-origin; A at d0, B at d1 and d2; collapse persistent prefixes by A->B origin pair; one deterministic representative per pair; deterministic sha256 pair sample','sample_n':n,'raw_changes':len(changes),'persistent_prefixes':len(persistent),'distinct_origin_pairs':len(cohorts),'guardrail':'Daily-snapshot feasibility pilot. A_lingering_valid means authorization persisted after observed routing replacement; it does not establish that authorization is unnecessary, stale, malicious, or misconfigured.'},'rpki_anchors_used':meta,'counts':counts,'rates':{k:v/n for k,v in counts.items()},'conditional':{'rpki_covered_at_d1_n':covered_d1,'new_origin_invalid_among_rpki_covered_d1':(counts['B_invalid_d1']/covered_d1 if covered_d1 else None)}}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    md=['# RPKI handoff kill/keep pilot — origin-pair deduplicated','',f'- Raw single-origin changed prefixes: {len(changes)}',f'- Persistent changed prefixes: {len(persistent)}',f'- Distinct persistent A→B origin pairs: {len(cohorts)}',f'- Deterministic distinct-pair sample: {n}','','## Coarse results','']
    md += [f'- {k}: **{counts[k]}/{n} ({counts[k]/n:.1%})**' for k in keys]
    if covered_d1:
        md += [f'- new-origin Invalid conditional on RPKI coverage at d1: **{counts["B_invalid_d1"]}/{covered_d1} ({counts["B_invalid_d1"]/covered_d1:.1%})**']
    md += ['','## Guardrail','','This is a daily-snapshot feasibility pilot, not an exact timing or intent study. `A_lingering_valid` is not automatically stale authorization: failover, same-organization migration, or intentional multi-origin policy can justify retaining A. A full study must add multi-collector persistence, organization/transfer/failover stratification, and update-level timing.']
    (OUT/'README.md').write_text('\n'.join(md),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
