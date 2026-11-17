#!/usr/bin/env python3
"""Encrypt a reviewed, source-locked minimal RISUAP dataset before public runner upload."""
import argparse,base64,hashlib,io,json,os,pathlib,zipfile
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
AAD=b"risuap-socrata-v031"
def main():
 p=argparse.ArgumentParser();p.add_argument("--source",required=True);p.add_argument("--recipient",required=True);p.add_argument("--out",required=True)
 a=p.parse_args();root=pathlib.Path(a.source)
 files=sorted(x for x in root.iterdir() if x.is_file())
 if len(files)!=2 or not any(x.name=="manifest.json" for x in files) or not any(x.suffix==".gz" for x in files):raise ValueError("Incomplete dataset")
 mem=io.BytesIO()
 with zipfile.ZipFile(mem,"w",compression=zipfile.ZIP_STORED) as z:
  for f in files:z.write(f,arcname=f.name)
 raw=mem.getvalue();pub=serialization.load_pem_public_key(pathlib.Path(a.recipient).read_bytes());key=os.urandom(32);nonce=os.urandom(12)
 wrapped=pub.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
 cipher=AESGCM(key).encrypt(nonce,raw,AAD)
 obj={"schema":"risuap-socrata-v031","plain_sha256":hashlib.sha256(raw).hexdigest(),"wrapped_key_b64":base64.b64encode(wrapped).decode(),"nonce_b64":base64.b64encode(nonce).decode(),"ciphertext_b64":base64.b64encode(cipher).decode()}
 pathlib.Path(a.out).write_text(json.dumps(obj,separators=(",",":"))+"\n")
 print("SEALED",len(raw),len(cipher),flush=True)
if __name__=="__main__":main()
