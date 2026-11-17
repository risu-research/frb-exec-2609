#!/usr/bin/env python3
"""Read Florida official daily master and event files into minimal source-linked tables."""
from __future__ import annotations
import argparse, collections, gzip, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
import paramiko
import bulk_partition as base
import sftp_download as official

SOURCES={
 'master':('/Public/doc/cor',re.compile(r'^([0-9]{8})c\.txt$',re.I),base.MASTER_WIDTH),
 'event':('/Public/doc/cor/Events',re.compile(r'^([0-9]{8})ce\.txt$',re.I),base.EVENT_WIDTH),
}

def get_row(kind, raw, name, ordinal, day):
    eid=base.field(raw,(1,12))
    if not base.eligible_id(eid):raise LookupError('invalid native ID')
    if kind=='master':
        f={key:base.field(raw,pos) for key,pos in base.MASTER_FIELDS.items()}
        formed=base.date8(f['formation_date']);last=base.date8(f['last_transaction_date'])
        slots=[]
        for n in (1,2,3):
            year=f['report_year_'+str(n)]
            filed=base.date8(f['report_date_'+str(n)])
            if year and not re.fullmatch(r'[0-9]{4}',year):raise ValueError('annual report year')
            if year or filed:
                slots.append({'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL',
                    'report_year_source':year or None,'report_filed_date':filed,
                    'report_slot_number':n,'source_field':'corporate_master_annual_report_slot',
                    'source_file':name,'source_file_date':day,
                    'source_row_ordinal':ordinal,'complete_annual_report_history':False})
        row={'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL','registry_id':eid,
            'entity_form_source':f['filing_type'] or None,
            'status_observation_source_value':f['status_code'] or None,
            'formation_date_observed':formed,'last_transaction_date_observed':last,
            'source_file':name,'source_file_date':day,'source_row_ordinal':ordinal,
            'source_kind':'daily_corporate_file','status_at_historical_time_known':False}
        return row,slots
    f={key:base.field(raw,pos) for key,pos in base.EVENT_FIELDS.items()}
    filed=base.date8(f['filed_date'])
    if not filed:raise ValueError('event filed date absent')
    effective=base.date8(f['effective_date'])
    row={'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL','registry_id':eid,
         'event_key':'US-FL:'+eid+'#'+name+'@'+str(ordinal),
         'source_record_id':f['event_sequence'] or None,
         'source_event_code':f['event_code'] or None,
         'source_event_label':f['event_description'] or None,
         'filed_or_received_at':filed,'effective_at':effective,
         'time_field_basis':'filed_date','source_kind':'daily_corporate_event',
         'source_file':name,'source_file_date':day,'source_row_ordinal':ordinal,
         'source_content_fingerprint':hashlib.sha256(base.encode([
             eid,f['event_sequence'],f['event_code'],filed,effective])).hexdigest()}
    return row,[]

def capture(start_day,end_day,out_dir,event_start_day='20261005'):
    if not (re.fullmatch(r'[0-9]{8}',start_day) and re.fullmatch(r'[0-9]{8}',end_day) and
            '20261008'<=start_day<=end_day<='20261116'):
        raise ValueError('v0.3 first edition is bounded by source-vintage dates')
    if not '20261005'<=event_start_day<=start_day:raise ValueError('Invalid event bridge start')
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise FileExistsError('Output directory must be empty')
    t=paramiko.Transport((official.HOST,22));t.banner_timeout=30;t.auth_timeout=30;t.set_keepalive(20)
    t.connect(username=official.PUBLIC_USER,password=official.PUBLIC_PASSWORD)
    counters=collections.Counter();receipts=[]
    tablehashes={k:hashlib.sha256() for k in ('entities','events','report_observations')}
    try:
        sftp=paramiko.SFTPClient.from_transport(t)
        try:
            with (gzip.open(out/'entities.jsonl.gz','wb',compresslevel=7) as master,
                  gzip.open(out/'events.jsonl.gz','wb',compresslevel=7) as events,
                  gzip.open(out/'report_observations.jsonl.gz','wb',compresslevel=7) as reports):
                writers={'master':master,'event':events}
                for kind in ('master','event'):
                    directory,pattern,width=SOURCES[kind]
                    files=[]
                    for a in sftp.listdir_attr(directory):
                        match=pattern.match(a.filename)
                        if match and (event_start_day if kind=='event' else start_day)<=match.group(1)<=end_day:
                            files.append((match.group(1),a.filename,a))
                    files.sort(key=lambda x:(x[0],x[1]))
                    if not files:raise RuntimeError('No official daily source files: '+kind)
                    for day,name,attr in files:
                        source=directory+'/'+name
                        sha=hashlib.sha256();bytecount=0
                        c=collections.Counter()
                        with sftp.open(source,'rb') as f:
                            f.prefetch(attr.st_size)
                            for ordinal,line in enumerate(f,1):
                                bytecount+=len(line);sha.update(line);c['physical_rows']+=1
                                raw=line.rstrip(b'\r\n')
                                if len(raw)!=width:
                                    c['bad_width']+=1;continue
                                try:row,slots=get_row(kind,raw,name,ordinal,day)
                                except LookupError:
                                    c['invalid_id']+=1;continue
                                except ValueError:
                                    c['unparseable']+=1;continue
                                payload=base.encode(row);writers[kind].write(payload)
                                tablehashes['entities' if kind=='master' else 'events'].update(payload)
                                c['exported_rows']+=1
                                for slot in slots:
                                    serialized=base.encode(slot)
                                    reports.write(serialized)
                                    tablehashes['report_observations'].update(serialized)
                                    c['report_slots']+=1
                        after=sftp.stat(source)
                        if bytecount!=attr.st_size or after.st_size!=attr.st_size or after.st_mtime!=attr.st_mtime:
                            raise RuntimeError('Official file changed during download: '+name)
                        if not c['physical_rows'] or not c['exported_rows']:
                            raise RuntimeError('Empty or unparseable official file: '+name)
                        counters.update({kind+'_'+key:value for key,value in c.items()})
                        receipts.append({'kind':kind,'file':name,'file_date':day,
                          'official_path':source,'sha256':sha.hexdigest(),'size_bytes':bytecount,
                          'remote_mtime_epoch':attr.st_mtime,'counts':dict(c)})
                        print('CAPTURED',kind,name,'source_rows',c['physical_rows'],
                              'exported',c['exported_rows'],flush=True)
        finally:sftp.close()
    finally:t.close()
    days={k:sorted({r['file_date'] for r in receipts if r['kind']==k}) for k in SOURCES}
    manifest={'schema':'risuap_fl_daily_edition_v03',
      'captured_utc':datetime.now(timezone.utc).isoformat(),
      'base_full_snapshot':'v0.2.6-internal',
      'base_quarterly_archive_sha256':{'cordata.zip':base.CORDATA_SHA,'corevent.zip':base.COREVENT_SHA},
      'coverage':{'kind':'daily_incremental_observations_not_full_snapshot',
       'first_file_date':start_day,'event_bridge_start':event_start_day,'last_file_date':end_day,'published_dates':days,
       'note':'Missing records from a daily file do not imply deletion or disappearance.'},
      'official_source_url':'https://dos.fl.gov/sunbiz/other-services/data-downloads/daily-data/',
      'counts':dict(counters),'file_receipts':receipts,
      'jsonl_uncompressed_sha256':{k:v.hexdigest() for k,v in tablehashes.items()},
      'privacy':'No names addresses officers tax identifiers or document images retained',
      'legal_status':'No filing duty compliance or payment inference',
      'dataset_license_review':'pending'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--start-day',default='20261008')
    p.add_argument('--end-day',default='20261116')
    p.add_argument('--event-start-day',default='20261005')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    m=capture(a.start_day,a.end_day,a.out,a.event_start_day)
    print('TOTALS',json.dumps(m['counts'],sort_keys=True))
