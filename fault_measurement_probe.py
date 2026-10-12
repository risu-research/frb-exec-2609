"""Open fault-data metadata and transport preflight."""
import requests,csv,io,hashlib,json
from collections import Counter
ROOT='https://zenodo.org/records/22904220/files/'
sess=requests.Session()
P={}
for fn in ['labels_metadata_DERfaults.csv','pmu_placement_configurations.csv','README.md']:
 u=ROOT+fn+'?download=1'
 r=sess.get(u,timeout=(20,80));r.raise_for_status()
 b=r.content
 open(fn,'wb').write(b)
 P[fn]={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'url':r.url}
 print('FETCH',fn,len(b),r.url,flush=True)
ls=list(csv.DictReader(io.StringIO(open('labels_metadata_DERfaults.csv').read())))
print('METADATA',json.dumps({'rows':len(ls),'scenario':dict(Counter(x['Scenario_ID'] for x in ls)),'class':dict(Counter(x['Fault_Label'] for x in ls)),'years':dict(Counter(x['Timestamp'][:4] for x in ls)),'resistance_positive':sum(float(x['Resistance'])>0 for x in ls),'fields':list(ls[0])}),flush=True)
p=list(csv.DictReader(io.StringIO(open('pmu_placement_configurations.csv').read())))
print('PMU',json.dumps({'rows':len(p),'columns':list(p[0]),'head':p[:9]}),flush=True)
u=ROOT+'DERfaults_measurements.csv?download=1'
with sess.get(u,stream=True,timeout=(25,100)) as r:
 r.raise_for_status()
 it=r.iter_lines()
 head=next(it).decode('utf-8-sig')
 print('MEASUREMENT_HEADER',json.dumps({'content_length':r.headers.get('content-length'),'num_columns':len(next(csv.reader([head]))),'first_cols':next(csv.reader([head]))[:9],'last_cols':next(csv.reader([head]))[-7:]}),flush=True)
 row=next(it).decode('utf-8')
 print('MEASUREMENT_FIRST_ROW',json.dumps({'len':len(row),'sample':row[:90]}),flush=True)
print('PREFLIGHT_COMPLETE',flush=True)
