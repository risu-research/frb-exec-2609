#!/usr/bin/env bash
set -euo pipefail
OUT=results/rpkispool_tar_members_20261002
mkdir -p "$OUT"
URL=https://rpkiviews.kerfuffle.net/rpkidata/rpkispools/2026/09/04/20260904-rpkispool.tar.zst
# Stream only until enough tar members have been listed; head closes the pipeline early.
set +e
timeout 180 bash -c "curl -L --fail --silent --show-error '$URL' | zstd -dc | tar -tf - | head -n 300" > "$OUT/first300.txt" 2> "$OUT/stderr.txt"
RC=$?
set -e
python3 - <<'PY'
from pathlib import Path
import re,json
p=Path('results/rpkispool_tar_members_20261002/first300.txt')
lines=[x.strip() for x in p.read_text(errors='replace').splitlines() if x.strip()]
# pull timestamp-like tokens and infer spacing if names carry times
vals=[]
for x in lines:
    m=re.search(r'(20260904[-_.T]?\d{6})',x)
    if m: vals.append(m.group(1))
Path('results/rpkispool_tar_members_20261002/summary.json').write_text(json.dumps({'n_members_seen':len(lines),'first20':lines[:20],'last20':lines[-20:],'timestamp_tokens_first20':vals[:20]},indent=2))
print(json.dumps({'n_members_seen':len(lines),'first20':lines[:20],'last20':lines[-20:],'timestamp_tokens_first20':vals[:20]},indent=2))
PY
exit 0
