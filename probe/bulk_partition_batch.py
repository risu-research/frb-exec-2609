#!/usr/bin/env python3
"""Stream each official archive once into multiple fixed, deterministic shards."""
import argparse, collections, contextlib, gzip, hashlib, json
from pathlib import Path
import bulk_partition as base

def produce(kind, source, root, first, last):
    expected=base.COREVENT_SHA if kind=='event' else base.CORDATA_SHA
    if base.sha256(source)!=expected:raise ValueError('Official archive digest changed')
    width=base.EVENT_WIDTH if kind=='event' else base.MASTER_WIDTH
    buckets=range(first,last+1)
    counters={b:collections.Counter() for b in buckets}
    types={b:collections.Counter() for b in buckets}
    statuses={b:collections.Counter() for b in buckets}
    years={b:collections.Counter() for b in buckets}
    row_hashes={b:hashlib.sha256() for b in buckets}
    report_hashes={b:hashlib.sha256() for b in buckets}
    seen={b:set() for b in buckets} if kind=='master' else {}
    totals=collections.Counter()
    with contextlib.ExitStack() as stack:
        outputs,report_outputs={},{}
        for b in buckets:
            folder=root/('bucket_%03d'%b)
            folder.mkdir(parents=True,exist_ok=True)
            outputs[b]=stack.enter_context(gzip.open(folder/('events.jsonl.gz' if kind=='event' else 'entities.jsonl.gz'),'wb',compresslevel=7))
            if kind=='master':
                report_outputs[b]=stack.enter_context(gzip.open(folder/'report_observations.jsonl.gz','wb',compresslevel=7))
        for member,ordinal,raw in base.iter_source(source):
            totals['physical_rows']+=1
            if len(raw)!=width:
                totals['bad_width']+=1
                continue
            eid=base.field(raw,(1,12))
            if not base.eligible_id(eid):
                totals['invalid_id']+=1
                continue
            totals['valid_width_and_id']+=1
            b=base.bucket(eid,256)
            if b<first or b>last:continue
            c=counters[b]
            c['partition_id_matches']+=1
            try:
                if kind=='event':
                    f={k:base.field(raw,v) for k,v in base.EVENT_FIELDS.items()}
                    filed=base.date8(f['filed_date'])
                    if not filed:raise ValueError('missing event date')
                    effective=base.date8(f['effective_date'])
                    row={'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL','registry_id':eid,
                         'event_key':'US-FL:'+eid+'#'+member+'@'+str(ordinal),
                         'source_member':member,'source_row_ordinal':ordinal,
                         'source_record_id':f['event_sequence'] or None,
                         'source_event_code':f['event_code'] or None,
                         'source_event_label':f['event_description'] or None,
                         'filed_or_received_at':filed,'effective_at':effective,
                         'time_field_basis':'filed_date','source_archive':'corevent.zip',
                         'source_content_fingerprint':hashlib.sha256(base.encode([eid,f['event_sequence'],f['event_code'],filed,effective])).hexdigest()}
                    years[b][filed[:4]]+=1
                    types[b][f['event_code'] or '<blank>']+=1
                else:
                    if eid in seen[b]:
                        c['duplicate_entity_rows']+=1
                        continue
                    f={k:base.field(raw,v) for k,v in base.MASTER_FIELDS.items()}
                    formation=base.date8(f['formation_date'])
                    last_date=base.date8(f['last_transaction_date'])
                    slots=[]
                    for n in (1,2,3):
                        yr=f['report_year_'+str(n)]
                        filed=base.date8(f['report_date_'+str(n)])
                        if yr and (len(yr)!=4 or not yr.isdigit()):
                            raise ValueError('bad report year')
                        if yr or filed:slots.append((yr or None,filed,n))
                    seen[b].add(eid)
                    row={'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL','registry_id':eid,
                         'entity_form_source':f['filing_type'] or None,
                         'status_observation_source_value':f['status_code'] or None,
                         'formation_date_observed':formation,
                         'last_transaction_date_observed':last_date,
                         'source_archive':'cordata.zip','source_member':member,
                         'source_row_ordinal':ordinal,'status_at_historical_time_known':False}
                    statuses[b][f['status_code'] or '<blank>']+=1
                    types[b][f['filing_type'] or '<blank>']+=1
                payload=base.encode(row)
            except ValueError:
                c['partition_unparseable']+=1
                continue
            outputs[b].write(payload)
            row_hashes[b].update(payload)
            c['exported_rows']+=1
            if kind=='master':
                for year,dt,n in slots:
                    obs={'entity_key':'US-FL:'+eid,'jurisdiction':'US-FL',
                         'report_year_source':year,'report_filed_date':dt,
                         'report_slot_number':n,'source_field':'corporate_master_annual_report_slot',
                         'source_archive':'cordata.zip','complete_annual_report_history':False}
                    p=base.encode(obs)
                    report_outputs[b].write(p)
                    report_hashes[b].update(p)
                    c['exported_report_slots']+=1
            if totals['physical_rows']%2000000==0:
                print('scanned',kind,totals['physical_rows'],flush=True)
    for b in buckets:
        c=counters[b]
        c['source_physical_rows']=totals['physical_rows']
        c['source_bad_width']=totals['bad_width']
        c['source_invalid_ids']=totals['invalid_id']
        c['source_valid_width_and_id']=totals['valid_width_and_id']
        receipt={'schema_version':'fl_source_partition_v0.2','kind':kind,
                 'archive':source.name,'official_source_url':base.SFTP_OFFICIAL,
                 'source_archive_sha256':expected,
                 'selection':'sha256(UTF8("US-FL:"+entity_id)) first 8 bytes unsigned big endian modulo modulus',
                 'modulus':256,'bucket':b,'counts':dict(c),
                 'event_year_counts':dict(sorted(years[b].items())),
                 'source_types':dict(sorted(types[b].items())),
                 'status_codes':dict(sorted(statuses[b].items())),
                 'jsonl_uncompressed_sha256':row_hashes[b].hexdigest(),
                 'reports_uncompressed_sha256':report_hashes[b].hexdigest() if kind=='master' else None,
                 'limits':['Source-wide scan, one deterministic hash shard; not statewide complete',
                           'No names, addresses, tax IDs, officers, or original document content',
                           'Unparseable selected records are counted rather than silently treated as absent',
                           'Current master snapshot is not a historical status record',
                           'Three report slots are not full annual-report history',
                           'No inference of legal compliance']}
        (root/('bucket_%03d'%b)/(kind+'_receipt.json')).write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    rollup={'kind':kind,'source_sha256':expected,'shared_source_counts':dict(totals),
            'range':[first,last],'shards':{str(b):dict(counters[b]) for b in buckets}}
    (root/(kind+'_batch_receipt.json')).write_text(json.dumps(rollup,sort_keys=True,indent=2)+'\n')
    print('completed',kind,json.dumps({'range':[first,last],'source':dict(totals),'shards':{str(b):counters[b]['exported_rows'] for b in buckets}}),flush=True)
    return rollup

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--kind',choices=('event','master'),required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--first',type=int,default=0)
    p.add_argument('--last',type=int,default=7)
    a=p.parse_args()
    if not 0<=a.first<=a.last<256:raise ValueError('Invalid shard range')
    produce(a.kind,a.source,a.out,a.first,a.last)
