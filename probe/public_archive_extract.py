"""Official bulk archive audit on read-only public quarterly ZIPs.

Research acquisition, not a legal-compliance classifier. Frozen original Stage06
cohort is reproduced BEFORE new IDs are selected. Selection is written to an
immutable local manifest before opening corporate-master report records.

No names, addresses, FEI, or officer fields are stored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

COREVENT_SHA256 = '395c5240b2eddabf5300b09c658c93320a1e9a311a4897983526d8dc1152280d'
CORDATA_SHA256 = 'f85264b1443a7f60c8a95ec69bebc9407cc87367fe5acef59a17b58068d5bee9'
FROZEN_ID_SHA256 = 'f00657c3c2ede682b3e79c1193e54fc9fdb4977c73bed3f56fe280acdc34f320'
YEARS = (2023, 2024, 2025)
EVENT_WIDTH = 662
CORPORATE_WIDTH = 1440
# Original Stage06 uses the earliest 30 candidate IDs per year before exclusion.
# Up to 30 original + 20 earlier new holdout IDs can be excluded, so 80
# earliest candidates per year are sufficient for 10 new IDs under this rule.
TOP_K = 80
EVENT_FIELDS = {'entity_id': (1, 12), 'event_sequence': (13, 5),
                'event_code': (18, 20), 'event_description': (38, 40),
                'effective_date': (78, 8), 'filed_date': (86, 8)}
CORP_FIELDS = {'entity_id': (1, 12), 'status_code': (205, 1),
               'filing_type': (206, 15), 'formation_date': (473, 8),
               'last_transaction_date': (496, 8),
               'report_year_1': (506, 4), 'report_date_1': (511, 8),
               'report_year_2': (519, 4), 'report_date_2': (524, 8),
               'report_year_3': (532, 4), 'report_date_3': (537, 8)}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def date8(s):
    x = s.strip()
    if not x:
        return None
    if len(x) != 8 or not x.isdigit():
        raise ValueError('invalid date')
    candidates = []
    for y, m, d in ((int(x[4:8]), int(x[:2]), int(x[2:4])),
                    (int(x[:4]), int(x[4:6]), int(x[6:8]))):
        try:
            v = date(y, m, d).isoformat()
            if v not in candidates:
                candidates.append(v)
        except ValueError:
            pass
    if len(candidates) != 1:
        raise ValueError('ambiguous or invalid date')
    return candidates[0]


def read_field(raw, pos_and_width):
    start, length = pos_and_width
    return raw[start-1:start-1+length].decode('latin-1').strip()


def parse_event(raw):
    if len(raw) != EVENT_WIDTH:
        raise ValueError('event width')
    fields = {k: read_field(raw, v) for k, v in EVENT_FIELDS.items()}
    if not re.fullmatch(r'[A-Z0-9]{6,12}', fields['entity_id']):
        raise ValueError('event entity ID')
    fields['filed_date'] = date8(fields['filed_date'])
    fields['effective_date'] = date8(fields['effective_date'])
    if not fields['filed_date']:
        raise ValueError('event filed date absent')
    return fields


def parse_corporate(raw):
    if len(raw) != CORPORATE_WIDTH:
        raise ValueError('corporate width')
    f = {k: read_field(raw, v) for k, v in CORP_FIELDS.items()}
    if not re.fullmatch(r'[A-Z0-9]{6,12}', f['entity_id']):
        raise ValueError('corporate entity ID')
    reports = []
    for i in (1, 2, 3):
        year = f['report_year_'+str(i)] or None
        filed = date8(f['report_date_'+str(i)])
        if year and not re.fullmatch(r'\d{4}', year):
            raise ValueError('annual-report year')
        if year or filed:
            reports.append({'report_year': year, 'filed_at': filed})
    return {'entity_id': f['entity_id'], 'status_code': f['status_code'] or None,
            'filing_type': f['filing_type'] or None,
            'formation_date': date8(f['formation_date']),
            'last_transaction_date': date8(f['last_transaction_date']),
            'up_to_three_annual_report_slots': reports}


def locate_7zip(explicit=None):
    if explicit:
        exe = shutil.which(explicit)
        if exe:
            return exe
        if Path(explicit).is_file():
            return explicit
        raise RuntimeError('Cannot find 7-Zip: '+explicit)
    for exe in ('7z', '7zz', '7za', '7z.exe', '7zz.exe'):
        found = shutil.which(exe)
        if found:
            return found
    if sys.platform == 'win32':
        for directory in (Path('C:/Program Files/7-Zip'), Path('C:/Program Files (x86)/7-Zip')):
            for filename in ('7z.exe', '7zz.exe'):
                if (directory / filename).is_file():
                    return str(directory / filename)
    return None


@contextmanager
def member_stream(path, archive, member, seven_zip=None):
    if member.compress_type in (0, 8, 12, 14):
        with archive.open(member) as stream:
            yield stream
        return
    exe = locate_7zip(seven_zip)
    if not exe:
        raise RuntimeError('Unsupported ZIP method '+str(member.compress_type)+
                           '. Install 7-Zip or use --seven-zip PATH_TO_7z.exe')
    print('7-Zip stream: '+member.filename, file=sys.stderr, flush=True)
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen([exe, 'x', '-so', '-y', '-bd', '-bsp0', str(path), member.filename],
                                   stdout=subprocess.PIPE, stderr=stderr)
        try:
            yield process.stdout
            process.stdout.close()
            code = process.wait()
            if code != 0:
                stderr.seek(0)
                raise RuntimeError('7-Zip failed: '+stderr.read(1000).decode('utf-8', 'replace'))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout and not process.stdout.closed:
                process.stdout.close()


def iter_raw_rows(zip_path, seven_zip=None):
    with zipfile.ZipFile(zip_path) as archive:
        files = sorted((m for m in archive.infolist() if not m.is_dir() and
                        m.filename.lower().endswith(('.txt', '.dat'))),
                       key=lambda x: x.filename)
        if not files:
            raise RuntimeError('No data members in ZIP: '+str(zip_path))
        for member in files:
            with member_stream(zip_path, archive, member, seven_zip) as stream:
                for row in stream:
                    yield member.filename, row.rstrip(b'\r\n')


def sortkey(x):
    return (x['filed_date'], x['entity_id'], x['event_sequence'])


def selected_id_hash(ids):
    return hashlib.sha256(('\n'.join(sorted(ids))+'\n').encode()).hexdigest()


def select_candidate_events(zip_path, seven_zip=None):
    top = {year: {} for year in YEARS}
    stats = {'scanned_rows': 0, 'wrong_length': 0,
             'malformed_candidate': 0, 'eligible_reinstatement_rows': 0}
    for _, raw in iter_raw_rows(zip_path, seven_zip):
        stats['scanned_rows'] += 1
        if stats['scanned_rows'] % 2_000_000 == 0:
            print('Corporate events scanned: {:,}'.format(stats['scanned_rows']), file=sys.stderr, flush=True)
        if len(raw) != EVENT_WIDTH:
            stats['wrong_length'] += 1
            continue
        marker = (read_field(raw, EVENT_FIELDS['event_code'])+' '+
                  read_field(raw, EVENT_FIELDS['event_description'])).upper()
        if 'REINSTAT' not in marker:
            continue
        try:
            item = parse_event(raw)
        except ValueError:
            stats['malformed_candidate'] += 1
            continue
        year = int(item['filed_date'][:4])
        if year not in top:
            continue
        stats['eligible_reinstatement_rows'] += 1
        group = top[year]
        ident = item['entity_id']
        if ident in group:
            if sortkey(item) < sortkey(group[ident]):
                group[ident] = item
        elif len(group) < TOP_K:
            group[ident] = item
        else:
            worst = max(group, key=lambda key: sortkey(group[key]))
            if sortkey(item) < sortkey(group[worst]):
                del group[worst]
                group[ident] = item

    old = []
    previous = set()
    for year in YEARS:
        choices = sorted(top[year].values(), key=sortkey)
        selected = []
        for row in choices:
            if row['entity_id'] in previous:
                continue
            selected.append(row)
            previous.add(row['entity_id'])
            if len(selected) == 10:
                break
        old.extend(dict(row, cohort_year=year) for row in selected)
    if len(old) != 30:
        raise ValueError('Failed to reconstruct all 30 original IDs')
    # Check the complete original anchor sequence without publishing its entity IDs.
    # Hash covers selected ID, year, filed date, event sequence, and event code.
    reference_tuple_rows = [[a['entity_id'], a['cohort_year'], a['filed_date'],
                             a['event_sequence'], a['event_code']] for a in old]
    reference_sha = hashlib.sha256(json.dumps(
        reference_tuple_rows, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    if reference_sha != 'b71dd25d5ebc02aaa3845f913e42f5cdf7ba09756fc8b04b51bec770e446bca9' or \
       selected_id_hash([x['entity_id'] for x in old]) != FROZEN_ID_SHA256:
        raise ValueError('Original frozen anchor ordering or identities changed')

    original_ids = {r['entity_id'] for r in old}
    excluded_new = set(original_ids)
    new = []
    shortages = {}
    for year in YEARS:
        picks = []
        for row in sorted(top[year].values(), key=sortkey):
            if row['entity_id'] in excluded_new:
                continue
            picks.append(dict(row, cohort_year=year))
            excluded_new.add(row['entity_id'])
            if len(picks) == 10:
                break
        new.extend(picks)
        shortages[str(year)] = 10 - len(picks)
    stats['holdout_shortages_per_year'] = shortages
    if len(set(r['entity_id'] for r in new)) != len(new):
        raise AssertionError('Duplicate holdout entity')
    assert not original_ids.intersection(r['entity_id'] for r in new)
    return new, stats


def collect_selected_events(zip_path, selected, seven_zip=None):
    ids = {r['entity_id'] for r in selected}
    events = []
    rows_read = 0
    for member, raw in iter_raw_rows(zip_path, seven_zip):
        rows_read += 1
        if len(raw) != EVENT_WIDTH:
            continue
        ident = read_field(raw, EVENT_FIELDS['entity_id'])
        if ident not in ids:
            continue
        event = parse_event(raw)  # Fail, rather than silently omit, malformed selected records.
        events.append({k: event[k] for k in ('entity_id', 'filed_date', 'effective_date', 'event_sequence', 'event_code', 'event_description')})
        events[-1]['source_member'] = member
    events.sort(key=lambda x:(x['entity_id'], x['filed_date'], x['event_sequence']))
    for row in selected:
        if not any(e['entity_id']==row['entity_id'] and e['filed_date']==row['filed_date'] and
                   e['event_sequence']==row['event_sequence'] and e['event_code']==row['event_code']
                   for e in events):
            raise RuntimeError('Missing chosen reinstatement anchor in extracted events')
    return events, rows_read


def render(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False)+'\n'


def write_locked(path, obj):
    content = render(obj)
    if path.exists():
        if path.read_text(encoding='utf-8') != content:
            raise RuntimeError('Immutable result already exists with different contents: '+str(path))
        print('Existing output identical: '+str(path), file=sys.stderr)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        f.write(content)


def select(corevent, out_dir, seven_zip=None):
    actual = sha256(corevent)
    if actual != COREVENT_SHA256:
        raise ValueError('corevent.zip SHA-256 does not match the original source')
    new, stats = select_candidate_events(corevent, seven_zip)
    events, second_pass_rows = collect_selected_events(corevent, new, seven_zip)
    event_obj = {
        'stage': '10', 'new_selected_ids_sha256': selected_id_hash([r['entity_id'] for r in new]),
        'corevent_sha256': actual, 'events': events}
    event_sha256 = hashlib.sha256(render(event_obj).encode('utf-8')).hexdigest()
    lock = {
        'stage': '10', 'cohort_role': 'entity-disjoint follow-up selected before cordata inspection',
        'protocol': 'research/STAGE09_FL_HOLDOUT_PROTOCOL.md',
        'corevent_sha256_verified_locally': actual,
        'expected_cordata_sha256': CORDATA_SHA256,
        'prior_30_sha256': FROZEN_ID_SHA256,
        'new_selected_ids_sha256': selected_id_hash([r['entity_id'] for r in new]),
        'source_event_extract_sha256': event_sha256,
        'original_stage06_reconstructed': True,
        'anchors': new,
        'selection_scan': stats,
        'second_event_pass_rows': second_pass_rows,
        'note': 'Selection locked before reading cordata; nonrepresentative January-biased cohort.'
    }
    lock_path = out_dir / 'fl_stage10_selection.lock.json'
    write_locked(lock_path, lock)
    # All observed events from the same corevent source; no names/addresses/officers.
    write_locked(out_dir / 'fl_stage10_events.json', event_obj)
    return lock


def enrich(cordata, out_dir, seven_zip=None):
    lock_path = out_dir / 'fl_stage10_selection.lock.json'
    event_path = out_dir / 'fl_stage10_events.json'
    if not lock_path.is_file() or not event_path.is_file():
        raise ValueError('Freeze the Stage10 selection with --phase select first')
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    event_obj = json.loads(event_path.read_text(encoding='utf-8'))
    ids = {r['entity_id'] for r in lock['anchors']}
    if hashlib.sha256(event_path.read_bytes()).hexdigest() != lock['source_event_extract_sha256']:
        raise ValueError('Source event extract does not match frozen selection')
    if len(ids) != len(lock['anchors']) or len(ids) > 30 or lock['corevent_sha256_verified_locally'] != COREVENT_SHA256 or \
       lock['new_selected_ids_sha256'] != selected_id_hash(ids) or \
       event_obj['new_selected_ids_sha256'] != lock['new_selected_ids_sha256']:
        raise ValueError('Stage10 selection/event source lock mismatch')
    if sha256(cordata) != CORDATA_SHA256:
        raise ValueError('cordata.zip SHA-256 not equal to user-attested hash')
    counts = {'scanned_rows': 0, 'wrong_length': 0, 'selected_duplicates': 0, 'selected_rows': 0}
    found = {}
    for member, raw in iter_raw_rows(cordata, seven_zip):
        counts['scanned_rows'] += 1
        if counts['scanned_rows'] % 2_000_000 == 0:
            print('Corporate master scanned: {:,}; found {}/30'.format(counts['scanned_rows'],len(found)), file=sys.stderr, flush=True)
        if len(raw) != CORPORATE_WIDTH:
            counts['wrong_length'] += 1
            continue
        ident = read_field(raw, CORP_FIELDS['entity_id'])
        if ident not in ids:
            continue
        parsed = parse_corporate(raw)
        parsed['source_member'] = member
        counts['selected_rows'] += 1
        if ident in found:
            counts['selected_duplicates'] += 1
            # First row remains visible, never silently certify duplicate-free data.
        else:
            found[ident] = parsed
    data = {
        'stage': '10', 'source': 'Florida Department of State quarterly COR master and events',
        'corevent_sha256': COREVENT_SHA256, 'cordata_sha256_verified_locally': CORDATA_SHA256,
        'new_selected_ids_sha256': lock['new_selected_ids_sha256'],
        'counts': counts,
        'holdout_shortages_per_year': lock['selection_scan']['holdout_shortages_per_year'],
        'selected_entities': len(ids), 'located_entities': len(found),
        'missing_entity_ids': sorted(ids - set(found)),
        'entity_records': [found[x] for x in sorted(found)],
        'source_events': event_obj['events'],
        'anchor_records': lock['anchors'],
        'limits': ['No original filing PDF inspected', 'Corporate master provides up to three annual-report slots',
                   'Snapshot date and historical legal status not certified', 'No reporting compliance inferred']
    }
    write_locked(out_dir / 'fl_stage10_minimal.json', data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('select','enrich','all'))
    parser.add_argument('--corevent', type=Path)
    parser.add_argument('--cordata', type=Path)
    parser.add_argument('--out-dir', type=Path, default=Path.cwd() / 'stage10_results')
    parser.add_argument('--seven-zip', type=str)
    args = parser.parse_args()
    if args.phase in ('select', 'all'):
        if not args.corevent or not args.corevent.is_file():
            parser.error('--corevent must refer to your local corevent.zip')
        locked = select(args.corevent, args.out_dir, args.seven_zip)
        print('Stage10 frozen entity selection: {} distinct IDs'.format(len(locked['anchors'])))
    if args.phase in ('enrich', 'all'):
        if not args.cordata or not args.cordata.is_file():
            parser.error('--cordata must refer to your local cordata.zip')
        enriched = enrich(args.cordata, args.out_dir, args.seven_zip)
        print('Stage10 corporate-master subset: {} / {} entities found'.format(
            enriched['located_entities'],enriched['selected_entities']))
    print('Outputs: '+str(args.out_dir.resolve()))


if __name__ == '__main__':
    main()
