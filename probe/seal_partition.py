#!/usr/bin/env python3
"""Send privacy-minimized public-source partitions only as encrypted runner artifacts."""
import argparse, base64, hashlib, io, json, os, zipfile
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def seal(root,key_file,out):
    needed=('events.jsonl.gz','entities.jsonl.gz','report_observations.jsonl.gz','event_receipt.json','master_receipt.json')
    files=[root/name for name in needed]
    if any(not f.is_file() for f in files):raise ValueError('All source-derived files are required')
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as z:
        for f in files:z.write(f,arcname=f.name)
    plaintext=stream.getvalue()
    pub=serialization.load_pem_public_key(key_file.read_bytes())
    sym,nonce=os.urandom(32),os.urandom(12)
    aad=b'risuap-bulk-v02-partition'
    wrapped=pub.encrypt(sym,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    ciphertext=AESGCM(sym).encrypt(nonce,plaintext,aad)
    payload={'schema':'risuap-bulk-v02-partition','sha256_plain_bundle':hashlib.sha256(plaintext).hexdigest(),
        'wrapped_aes_key_b64':base64.b64encode(wrapped).decode(),
        'nonce_b64':base64.b64encode(nonce).decode(),
        'ciphertext_b64':base64.b64encode(ciphertext).decode()}
    out.write_text(json.dumps(payload,separators=(',',':'))+'\n',encoding='utf-8')
    print('Partition encrypted, only ciphertext ready for upload. Bytes:',out.stat().st_size)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--recipient',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();seal(a.root,a.recipient,a.out)
