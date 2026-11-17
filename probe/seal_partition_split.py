#!/usr/bin/env python3
"""Seal deterministic Florida source partitions in independently authenticated chunks.

Reads only the official-source-derived minimal fields from an isolated public
compute runner. Outputs AES-256-GCM encrypted JSON only; no plaintext artifacts.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TABLES = ('events.jsonl.gz', 'entities.jsonl.gz', 'report_observations.jsonl.gz',
          'event_receipt.json', 'master_receipt.json')
AAD = b'risuap-bulk-v02-batch'


def seal(root, recipient, output, first, last, chunk_size):
    if not (0 <= first <= last < 256) or chunk_size < 1 or (last-first+1) % chunk_size:
        raise ValueError('Invalid range or chunk size')
    pub = serialization.load_pem_public_key(Path(recipient).read_bytes())
    root = Path(root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    full = {kind: json.loads((root / (kind + '_batch_receipt.json')).read_text())
            for kind in ('event','master')}
    for kind, report in full.items():
        if report.get('range') != [first, last]:
            raise ValueError('Unexpected source-wide batch range for ' + kind)
        if set(report['shards']) != {str(i) for i in range(first, last+1)}:
            raise ValueError('Missing source partition counts')
    results = []
    for lo in range(first, last+1, chunk_size):
        hi = lo + chunk_size - 1
        raw_stream = io.BytesIO()
        with zipfile.ZipFile(raw_stream, mode='w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for kind, report in full.items():
                scoped = dict(report)
                scoped['range'] = [lo, hi]
                scoped['shards'] = {str(i): report['shards'][str(i)] for i in range(lo, hi+1)}
                scoped['source_batch_range'] = [first, last]
                archive.writestr(kind + '_batch_receipt.json', json.dumps(scoped, sort_keys=True, indent=2) + '\n')
            for i in range(lo, hi+1):
                for table in TABLES:
                    filepath = root / ('bucket_%03d' % i) / table
                    if not filepath.is_file():
                        raise FileNotFoundError(filepath)
                    archive.write(filepath, arcname='bucket_%03d/%s' % (i,table))
        plain = raw_stream.getvalue()
        key,nonce = os.urandom(32),os.urandom(12)
        wrapped = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        encrypted = AESGCM(key).encrypt(nonce, plain, AAD)
        envelope = dict(schema='risuap-bulk-v02-batch', first=lo, last=hi,
                        source_batch_range=[first,last],
                        plain_sha256=hashlib.sha256(plain).hexdigest(),
                        wrapped_key_b64=base64.b64encode(wrapped).decode('ascii'),
                        nonce_b64=base64.b64encode(nonce).decode('ascii'),
                        ciphertext_b64=base64.b64encode(encrypted).decode('ascii'))
        target = output / ('sealed-batch-%03d-%03d.json' % (lo,hi))
        target.write_text(json.dumps(envelope, separators=(',', ':')) + '\n', encoding='utf-8')
        results.append({'range':[lo,hi],'sealed_bytes':target.stat().st_size,
                        'plain_sha256':envelope['plain_sha256'],'file':target.name})
        print('Sealed',lo,hi,'bytes',target.stat().st_size,flush=True)
    return results


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--recipient',type=Path,required=True)
    p.add_argument('--out-dir',type=Path,required=True)
    p.add_argument('--first',type=int,required=True)
    p.add_argument('--last',type=int,required=True)
    p.add_argument('--chunk-size',type=int,default=16)
    a=p.parse_args()
    print(json.dumps(seal(a.root,a.recipient,a.out_dir,a.first,a.last,a.chunk_size),indent=2))
