#!/usr/bin/env python3
import csv,hashlib,io,json,urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
OUT=Path('results/rpkispool_boundary_v1_20261002');OUT.mkdir(parents=True,exist_ok=True)
URL='https://raw.githubusercontent.com/risu-research/formal-exec-2609/rpki-pilot-20261002/results/rpki_lifecycle_refine_v2_20261002/exact_lifecycle_v2.csv'
try:
    txt=urllib.request.urlopen(URL,timeout=60).read().decode('utf8')
except Exception as e:
    print('refined lifecycle unavailable; clean no-op',repr(e));raise SystemExit(0)
rows=list(csv.DictReader(io.StringIO(txt)));cand=[]
for r in rows:
    ed=r.get('exact_event_date','')
    if not ed or ed<'2026-01-01':continue
    delayed=(str(r.get('B_auth_at_exact_event_date','')).lower()!='true' and bool(r.get('B_next_auth_start_exact_aligned')))
    same=(str(r.get('B_lead_calendar_days_exact_aligned',''))=='0')
    if not (delayed or same):continue
    r['_priority']=0 if delayed else 1
    cand.append(r)
by=defaultdict(list)
for r in cand:by[r['exact_event_date']].append(r)
# At most two archive-days, prioritizing days containing delayed cases, then candidate density.
dates=sorted(by,key=lambda d:(min(int(x['_priority']) for x in by[d]),-len(by[d]),d))[:2]
out=[]
for d in dates:
    xs=sorted(by[d],key=lambda r:(int(r['_priority']),hashlib.sha256((r['representative_prefix']+r['B_route_median']).encode()).hexdigest()))[:2]
    for r in xs:
        out.append({'prefix':r['representative_prefix'],'A':int(r['A']),'B':int(r['B']),'bgp_time':r['B_route_median'],
                    'date':d,'date_level_class':'B_after_event_date' if int(r['_priority'])==0 else 'same_day_unordered'})
summary={'candidate_n':len(cand),'selected_dates':dates,'selected_n':len(out),'targets':out,
         'guardrail':'Selective high-resolution confirmation only; not a prevalence sample. Priority is delayed/date-zero activation boundaries from exact multi-RRC lifecycle panel.'}
(OUT/'targets.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
