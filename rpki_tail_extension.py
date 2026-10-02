#!/usr/bin/env python3
import csv, hashlib, json, re, urllib.request
from collections import defaultdict
from pathlib import Path
import rpki_fast_pilot as b

DATES=['20260901','20260908','20260915','20260922','20260929']
OUT=Path(__file__).resolve().parent/'results'/'rpki_retirement_tail_20261002'
OUT.mkdir(parents=True,exist_ok=True)

def discover(date):
    ym=f'{date[:4]}/{date[4:6]}/'
    url='https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/'+ym
    html=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'risu-rpki-tail/1.0'}),timeout=60).read().decode('utf-8','replace')
    names=sorted(set(re.findall(r'routeviews-rv2-'+date+r'-\d{4}\.pfx2as\.gz',html)))
    if not names: raise RuntimeError('No CAIDA pfx2as file for '+date)
    names.sort(key=lambda n:abs(int(re.search(r'-(\d{4})\.pfx2as',n).group(1))-1200))
    return ym+names[0]

def main():
    for d in DATES:
        if d not in b.FILES: b.FILES[d]=discover(d)
    maps={d:b.load_pfx2as(d) for d in DATES}
    d0,d1=DATES[:2]
    changed=[p for p,A in maps[d0].items() if p in maps[d1] and maps[d1][p]!=A]
    persistent=[p for p in changed if all(maps[d].get(p)==maps[d1][p] for d in DATES[2:])]
    cohorts=defaultdict(list)
    for p in persistent: cohorts[(maps[d0][p],maps[d1][p])].append(p)
    reps=[]
    for (A,B),ps in cohorts.items():
        p=min(ps,key=lambda x:hashlib.sha256(x.encode()).hexdigest())
        reps.append((A,B,p,len(ps)))
    reps=sorted(reps,key=lambda z:hashlib.sha256((z[0]+'>'+z[1]).encode()).hexdigest())[:100]
    if len(reps)<50: raise RuntimeError(f'Only {len(reps)} distinct persistent pairs')
    pfx=[z[2] for z in reps]; als=b.anchors(); cov={}; used={}
    for d in DATES: cov[d],used[d]=b.load_cover(d,pfx,als)
    rows=[]
    for A,B,p,npfx in reps:
        r={'prefix':p,'A':A,'B':B,'pair_prefix_count':npfx}
        for d in DATES:
            r['A_'+d]=b.status(p,A,cov[d]); r['B_'+d]=b.status(p,B,cov[d])
        rows.append(r)
    with open(OUT/'events.csv','w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    n=len(rows); count=lambda fn:sum(bool(fn(r)) for r in rows)
    counts={
      'B_preauthorized_d0':count(lambda r:r['B_'+DATES[0]]=='valid'),
      'B_invalid_at_takeover':count(lambda r:r['B_'+DATES[1]]=='invalid'),
      'B_notfound_at_takeover':count(lambda r:r['B_'+DATES[1]]=='notfound'),
      'A_valid_at_takeover':count(lambda r:r['A_'+DATES[1]]=='valid'),
      'A_valid_plus1w':count(lambda r:r['A_'+DATES[2]]=='valid'),
      'A_valid_plus2w':count(lambda r:r['A_'+DATES[3]]=='valid'),
      'A_valid_plus3w':count(lambda r:r['A_'+DATES[4]]=='valid'),
      'dual_valid_at_takeover':count(lambda r:r['A_'+DATES[1]]=='valid' and r['B_'+DATES[1]]=='valid')}
    covered=count(lambda r:r['B_'+DATES[1]] in ('valid','invalid'))
    summary={'design':{'dates':DATES,'caida_files':{d:b.FILES[d] for d in DATES},'raw_changed_prefixes':len(changed),'persistent_prefixes_through_plus3w':len(persistent),'distinct_origin_pairs':len(cohorts),'sample_n':n,'sampling':'one deterministic representative per A->B pair; sha256 pair sample','guardrail':'Persistent routing replacement plus lingering old-origin validity does not prove that authorization is unnecessary or erroneous; intent/failover/organization classification remains required.'},'rpki_anchors_used':used,'counts':counts,'rates':{k:v/n for k,v in counts.items()},'conditional':{'rpki_covered_at_takeover_n':covered,'B_invalid_given_covered':counts['B_invalid_at_takeover']/covered if covered else None}}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (OUT/'README.md').write_text('# Extended RPKI authorization-retirement pilot\n\n'+'\n'.join(f'- {k}: {v}/{n} ({v/n:.1%})' for k,v in counts.items())+'\n\nGuardrail: lingering validity is not automatically stale or misconfigured.\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
