"""Verify every simulated secondary-side fault location against independent public network model."""
import csv,io,re,zipfile,json,requests,collections
root='https://wzy.ece.iastate.edu/publication/OpenDSS%20Model.zip'
meta='https://zenodo.org/records/22904220/files/labels_metadata_DERfaults.csv?download=1'
z=zipfile.ZipFile(io.BytesIO(requests.get(root,timeout=60).content))
loc=[x['Fault_Bus'].lower() for x in csv.DictReader(io.StringIO(requests.get(meta,timeout=70).text)) if x['Fault_Label']!='0']
targets=collections.Counter(x for x in loc if x.startswith('t_bus'))
trans=next(z.read(n).decode('utf-8-sig') for n in z.namelist() if n.endswith('DistriTransformer.dss'))
load=next(z.read(n).decode('utf-8-sig') for n in z.namelist() if n.endswith('Load.dss'))
kv={};amount={}
for line in trans.splitlines():
 m=re.search(r'\bbus=(t_bus\d+_l)\.[\d.]+\s+conn=\w+\s+kv=([0-9.]+)',line,re.I)
 if m:kv[m.group(1).lower()]=float(m.group(2))
for line in load.splitlines():
 m=re.search(r'\bbus1=(t_bus\d+_l)\.[\d.]+\s+kV=[\d.]+\s+kW=([\d.]+)',line,re.I)
 if m:amount[m.group(1).lower()]=float(m.group(2))
missed=sorted(set(targets)-set(kv))
print('TOPOLOGY_POPULATION',json.dumps({'secondary_fault_sites':len(targets),
  'total_secondary_cases':sum(targets.values()),'matched_transformers':len(set(targets)&set(kv)),
  'missing_transformers':missed,'load_record_sites':len(set(targets)&set(amount)),'rated_low_side_kv':dict(collections.Counter(kv[k] for k in targets if k in kv)),
  'site_sample':[{ 'bus':k,'n':v,'kv':kv.get(k),'load_kw':amount.get(k)} for k,v in list(targets.items())[:10]]}),flush=True)
assert len(missed)==0,'Secondary fault location without matching model'
print('TOPOLOGY_ALL_SITES_CONFIRMED',flush=True)
