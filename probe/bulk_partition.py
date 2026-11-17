#!/usr/bin/env python3
"""Source-wide Florida quarterly binary-to-minimal-record partition, streaming.

Selection is deterministic by SHA-256(entity key) on all valid official rows.
No names, address, officer data, FEI, PDFs or status inference are exported.
No researcher-chosen entity lists are used.
"""
import argparse
import collections
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from contextlib import contextmanager

COREVENT_SHA='395c5240b2eddabf5300b09c658c93320a1e9a311a4897983526d8dc1152280d'
CORDATA_SHA='f85264b1443a7f60c8a95ec69bebc9407cc87367fe5acef59a17b58068d5bee9'
EVENT_FIELDS={'entity_id':(1,12),'event_sequence':(13,5),'event_code':(18,20),'event_description':(38,40),'effective_date':(78,8),'filed_date':(86,8)}
MASTER_FIELDS={'entity_id':(1,12),'status_code':(205,1),'filing_type':(206,15),'formation_date':(473,8),'last_transaction_date':(496,8),'report_year_1':(506,4),'report_date_1':(511,8),'report_year_2':(519,4),'report_date_2':(524,8),'report_year_3':(532,4),'report_date_3':(537,8)}
EVENT_WIDTH=662
MASTER_WIDTH=1440
SFTP_OFFICIAL='https://dos.fl.gov/sunbiz/other-services/data-downloads/quarterly-data/'


def field(b,spec):
    start,n=spec
    return b[start-1:start-1+n].decode('latin-1').strip()


def date8(s):
    s=s.strip()
    if not s: return None
    if not re.fullmatch(r'[0-9]{8}',s): raise ValueError('invalid source date')
    matches=[]
    for y,m,d in ((int(s[4:]),int(s[0:2]),int(s[2:4])),(int(s[:4]),int(s[4:6]),int(s[6:8]))):
        try:
            q=date(y,m,d).isoformat()
            if q not in matches:matches.append(q)
        except ValueError:pass
    if len(matches)!=1:raise ValueError('invalid or ambiguous source date')
    return matches[0]


def eligible_id(x):
    return bool(re.fullmatch(r'[A-Z0-9]{6,12}',x))


def bucket(entity,modulus):
    return int.from_bytes(hashlib.sha256(('US-FL:'+entity).encode('ascii')).digest()[:8],'big')%modulus


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for part in iter(lambda:f.read(4*1024*1024),b''):h.update(part)
    return h.hexdigest()


@contextmanager
def stream_member(archive_path, z, member):
    if member.compress_type in (0,8,12,14):
        with z.open(member) as f:yield f
        return
    exe=shutil.which('7z') or shutil.which('7zz') or shutil.which('7za')
    if not exe:raise RuntimeError('7z binary required for ZIP compression method '+str(member.compress_type))
    with tempfile.TemporaryFile() as stderr:
        p=subprocess.Popen([exe,'x','-so','-y','-bd','-bsp0',str(archive_path),member.filename],stdout=subprocess.PIPE,stderr=stderr)
        try:
            yield p.stdout
            p.stdout.close()
            code=p.wait()
            if code!=0:
                stderr.seek(0)
                raise RuntimeError('7zip stream failed: '+stderr.read(700).decode('utf-8','replace'))
        finally:
            if p.poll() is None:p.kill()
            p.wait()
            if p.stdout is not None and not p.stdout.closed:p.stdout.close()


def iter_source(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        members=sorted((x for x in z.infolist() if not x.is_dir() and x.filename.lower().endswith(('.dat','.txt'))),key=lambda m:m.filename)
        if not members:raise ValueError('No fixed-width members')
        for member in members:
            with stream_member(zip_path,z,member) as f:
                for i,line in enumerate(f,1):
                    yield member.filename,i,line.rstrip(b'\r\n')


def encode(row):return (json.dumps(row,separators=(',',':'),sort_keys=True,ensure_ascii=False)+'\n').encode('utf-8')


def extract(source,kind,out,modulus,selected_bucket,expected_sha):
    if sha256(source)!=expected_sha:raise ValueError(kind+' official archive SHA256 changed')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    size=EVENT_WIDTH if kind=='event' else MASTER_WIDTH
    fname='events.jsonl.gz' if kind=='event' else 'entities.jsonl.gz'
    counts=collections.Counter()
    status=collections.Counter()
    types=collections.Counter()
    years=collections.Counter()
    sample=[]
    # gzip mtime defaults to present time. Immutable content hashed over decompressed JSONL
    core_hash=hashlib.sha256()
    report_hash=hashlib.sha256()
    seen_master=set() if kind=='master' else None
    # Compact rollup is no substitute for exporting records.
    with gzip.open(out/fname,'wb',compresslevel=7) as dest:
        report_file=gzip.open(out/'report_observations.jsonl.gz','wb',compresslevel=7) if kind=='master' else None
        try:
            for member,ordinal,raw in iter_source(source):
                counts['source_physical_rows']+=1
                if len(raw)!=size:
                    counts['source_bad_width']+=1
                    continue
                eid=field(raw,(1,12))
                if not eligible_id(eid):
                    counts['source_invalid_ids']+=1
                    continue
                counts['source_valid_width_and_id']+=1
                if bucket(eid,modulus)!=selected_bucket:continue
                counts['partition_id_matches']+=1
                try:
                    if kind=='event':
                        f={k:field(raw,v) for k,v in EVENT_FIELDS.items()}
                        filed=date8(f['filed_date'])
                        if not filed:raise ValueError('event date absent')
                        effective=date8(f['effective_date'])
                        # Source row location disambiguates repeated event sequence IDs.
                        row={'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL','registry_id':eid,
                            'event_key':f'US-FL:{eid}#'+member+'@'+str(ordinal),
                            'source_member':member,'source_row_ordinal':ordinal,
                            'source_record_id':f['event_sequence'] or None,
                            'source_event_code':f['event_code'] or None,
                            'source_event_label':f['event_description'] or None,
                            'filed_or_received_at':filed,'effective_at':effective,
                            'time_field_basis':'filed_date','source_archive':'corevent.zip',
                            'source_content_fingerprint':hashlib.sha256(encode([eid,f['event_sequence'],f['event_code'],filed,effective])).hexdigest()}
                        years[filed[:4]]+=1
                        types[f['event_code'] or '<blank>']+=1
                    else:
                        f={k:field(raw,v) for k,v in MASTER_FIELDS.items()}
                        if eid in seen_master:
                            counts['duplicate_entity_rows']+=1
                            continue
                        formdate=date8(f['formation_date'])
                        lastdate=date8(f['last_transaction_date'])
                        slots=[]
                        for n in (1,2,3):
                            yr=f['report_year_'+str(n)]
                            filed=date8(f['report_date_'+str(n)])
                            if yr and not re.fullmatch(r'\d{4}',yr):raise ValueError('invalid report year')
                            if yr or filed:slots.append((str(yr) if yr else None,filed,n))
                        seen_master.add(eid)
                        row={'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL','registry_id':eid,
                             'entity_form_source':f['filing_type'] or None,
                             'status_observation_source_value':f['status_code'] or None,
                             'formation_date_observed':formdate,'last_transaction_date_observed':lastdate,
                             'source_archive':'cordata.zip','source_member':member,
                             'source_row_ordinal':ordinal,'status_at_historical_time_known':False}
                        status[f['status_code'] or '<blank>']+=1
                        types[f['filing_type'] or '<blank>']+=1
                    payload=encode(row)
                except ValueError:
                    counts['partition_unparseable']+=1
                    continue
                dest.write(payload)
                core_hash.update(payload)
                counts['exported_rows']+=1
                if len(sample)<5:sample.append(eid)
                if kind=='master':
                    for yr,filed,n in slots:
                        r={'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL',
                           'report_year_source':yr,'report_filed_date':filed,
                           'report_slot_number':n,'source_field':'corporate_master_annual_report_slot',
                           'source_archive':'cordata.zip','complete_annual_report_history':False}
                        pay=encode(r)
                        report_file.write(pay)
                        report_hash.update(pay)
                        counts['exported_report_slots']+=1
                if counts['source_physical_rows']%2_000_000==0:
                    print('Read',kind,counts['source_physical_rows'],'exported',counts['exported_rows'],flush=True)
        finally:
            if report_file:report_file.close()
    receipt={'schema_version':'fl_source_partition_v0.2','kind':kind,'archive':source.name,
        'official_source_url':SFTP_OFFICIAL,'source_archive_sha256':expected_sha,
        'selection':'sha256(UTF8("US-FL:"+entity_id)) first 8 bytes unsigned big endian modulo modulus',
        'modulus':modulus,'bucket':selected_bucket,'counts':dict(counts),
        'event_year_counts':dict(sorted(years.items())),
        'source_types':dict(sorted(types.items())),
        'status_codes':dict(sorted(status.items())),
        'jsonl_uncompressed_sha256':core_hash.hexdigest(),
        'reports_uncompressed_sha256':report_hash.hexdigest() if kind=='master' else None,
        'limits':['Source-wide scan, one deterministic hash shard; not statewide complete',
           'No names, addresses, tax IDs, officers, or original document content',
           'Unparseable selected records are counted rather than silently treated as absent',
           'Current master snapshot is not a historical status record',
           'Three report slots are not full annual-report history',
           'No inference of legal compliance']}
    (out/(kind+'_receipt.json')).write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'kind':kind,'counts':dict(counts),'status':dict(status),'years':dict(years),'modulus':modulus,'bucket':selected_bucket},sort_keys=True),flush=True)
    return receipt


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--kind',choices=['event','master'],required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--modulus',type=int,default=256)
    p.add_argument('--bucket',type=int,default=0)
    a=p.parse_args()
    if a.modulus != 256 or not 0<=a.bucket<a.modulus:
        raise SystemExit('v0.2 uses 256 fixed shards; bucket must be in [0,255]')
    extract(a.source,a.kind,a.out,a.modulus,a.bucket,COREVENT_SHA if a.kind=='event' else CORDATA_SHA)

if __name__=='__main__':main()