#!/usr/bin/env python3
"""Encrypt a multi-shard public-source extract before leaving the compute runner."""
import argparse,base64,hashlib,io,json,os,zipfile
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

p=argparse.ArgumentParser()
p.add_argument('--root',type=Path,required=True)
p.add_argument('--recipient',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--first',type=int,default=0)
p.add_argument('--last',type=int,default=7)
a=p.parse_args()
assert 0<=a.first<=a.last<256
files=[a.root/(k+'_batch_receipt.json') for k in ('event','master')]
for b in range(a.first,a.last+1):
    d=a.root/('bucket_%03d'%b)
    files += [d/f for f in ('events.jsonl.gz','entities.jsonl.gz','report_observations.jsonl.gz','event_receipt.json','master_receipt.json')]
if not all(f.is_file() for f in files):raise ValueError('Incomplete source batch')
stream=io.BytesIO()
with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
    for f in files:z.write(f,arcname=f.relative_to(a.root).as_posix())
raw=stream.getvalue()
pub=serialization.load_pem_public_key(a.recipient.read_bytes())
key,nonce=os.urandom(32),os.urandom(12)
wrapped=pub.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
enc=AESGCM(key).encrypt(nonce,raw,b'risuap-bulk-v02-batch')
payload={'schema':'risuap-bulk-v02-batch','first':a.first,'last':a.last,
    'plain_sha256':hashlib.sha256(raw).hexdigest(),
    'wrapped_key_b64':base64.b64encode(wrapped).decode(),
    'nonce_b64':base64.b64encode(nonce).decode(),
    'ciphertext_b64':base64.b64encode(enc).decode()}
a.out.write_text(json.dumps(payload,separators=(',',':'))+'\n',encoding='utf-8')
print('Sealed source batch only. Encrypted bytes:',a.out.stat().st_size)
