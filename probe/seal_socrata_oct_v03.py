#!/usr/bin/env python3
"""Seal verified source-edition October CO/NY tables into private authenticated archive."""
import argparse,base64,hashlib,io,json,os,zipfile
from pathlib import Path
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
AAD=b'risuap-socrata-oct-v03'
def seal(source,recipient,out):
    root=Path(source)
    files=[root/'manifest.json',root/'events.jsonl.gz']
    if not all(x.is_file() for x in files):raise FileNotFoundError('Incomplete official source edition')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_STORED) as z:
        for file in files:z.write(file,arcname=file.name)
    clear=buffer.getvalue()
    key,nonce=os.urandom(32),os.urandom(12)
    public=serialization.load_pem_public_key(Path(recipient).read_bytes())
    wrapped=public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    encrypted=AESGCM(key).encrypt(nonce,clear,AAD)
    payload={'schema':'risuap-socrata-oct-v03','plain_sha256':hashlib.sha256(clear).hexdigest(),
             'wrapped_key_b64':base64.b64encode(wrapped).decode('ascii'),
             'nonce_b64':base64.b64encode(nonce).decode('ascii'),
             'ciphertext_b64':base64.b64encode(encrypted).decode('ascii')}
    Path(out).write_text(json.dumps(payload,separators=(',',':'))+'\n',encoding='utf-8')
    print('Official source edition authenticated and encrypted:',Path(out).stat().st_size)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--recipient',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();seal(a.source,a.recipient,a.out)
