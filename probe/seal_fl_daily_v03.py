#!/usr/bin/env python3
"""Encrypt a privacy-minimized Florida daily source edition before artifact upload."""
import argparse,base64,hashlib,io,json,os,zipfile
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SOURCES=('manifest.json','entities.jsonl.gz','events.jsonl.gz','report_observations.jsonl.gz')
AAD=b'risuap-fl-daily-v03'
def seal(source,recipient,out):
    root=Path(source)
    files=[root/name for name in SOURCES]
    if not all(f.is_file() for f in files):raise FileNotFoundError('Incomplete daily edition')
    target=io.BytesIO()
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_STORED) as z:
        for f in files:z.write(f,arcname=f.name)
    plaintext=target.getvalue()
    public=serialization.load_pem_public_key(Path(recipient).read_bytes())
    key,nonce=os.urandom(32),os.urandom(12)
    wrapped=public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    cipher=AESGCM(key).encrypt(nonce,plaintext,AAD)
    payload={'schema':'risuap-fl-daily-v03',
        'sha256_plain_archive':hashlib.sha256(plaintext).hexdigest(),
        'rsa_oaep_key_b64':base64.b64encode(wrapped).decode('ascii'),
        'aes_gcm_nonce_b64':base64.b64encode(nonce).decode('ascii'),
        'ciphertext_b64':base64.b64encode(cipher).decode('ascii')}
    Path(out).write_text(json.dumps(payload,separators=(',',':'))+'\n',encoding='utf-8')
    print('Sealed privacy-minimized official-source edition, bytes:',Path(out).stat().st_size)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--recipient',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();seal(a.source,a.recipient,a.out)
