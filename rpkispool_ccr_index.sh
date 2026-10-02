#!/usr/bin/env bash
set -euo pipefail
OUT=results/rpkispool_ccr_index_20261002
mkdir -p "$OUT"
URL=https://rpkiviews.kerfuffle.net/rpkidata/rpkispools/2026/09/04/20260904-rpkispool.tar.zst
# Full sequential scan of the compressed daily archive, outputting only CCR member paths.
curl -L --fail --silent --show-error "$URL" | zstd -dc --long=27 | tar -tf - | grep -E '\.ccr$' > "$OUT/ccr_members.txt"
python3 - <<'PY'
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict
import re,json,statistics
lines=[x.strip() for x in Path('results/rpkispool_ccr_index_20261002/ccr_members.txt').read_text().splitlines() if x.strip()]
pat=re.compile(r'/(\d{8}T\d{6}Z)-([^.\/]+)\.ccr$')
by=defaultdict(list)
for x in lines:
 m=pat.search(x)
 if not m: continue
 t=datetime.strptime(m.group(1),'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp();by[m.group(2)].append((t,x))
targets={'45.176.188.0/24':'2026-09-04T14:31:52Z','96.62.12.0/22':'2026-09-04T16:35:33Z'}
def ts(s): return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
near={}
for p,s in targets.items():
 t=ts(s); near[p]={}
 for node,v in sorted(by.items()):
  v=sorted(v); bef=[x for x in v if x[0]<=t]; aft=[x for x in v if x[0]>=t]
  near[p][node]={'before':bef[-1][1] if bef else None,'before_delta_s':t-bef[-1][0] if bef else None,'after':aft[0][1] if aft else None,'after_delta_s':aft[0][0]-t if aft else None}
summary={'ccr_n':len(lines),'nodes':{},'targets':near}
for node,v in sorted(by.items()):
 vv=sorted(x[0] for x in v); gaps=[vv[i]-vv[i-1] for i in range(1,len(vv))]
 summary['nodes'][node]={'n':len(vv),'first':datetime.fromtimestamp(vv[0],timezone.utc).isoformat(),'last':datetime.fromtimestamp(vv[-1],timezone.utc).isoformat(),'median_gap_s':statistics.median(gaps) if gaps else None,'min_gap_s':min(gaps) if gaps else None,'max_gap_s':max(gaps) if gaps else None}
Path('results/rpkispool_ccr_index_20261002/summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
PY
