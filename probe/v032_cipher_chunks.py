#!/usr/bin/env python3
"""Split an already sealed ciphertext into transport-sized, SHA-256-pinned chunks.

Output manifest contains no plaintext, identities or keys. Restore with ordered
literal-byte concatenation and independently check complete ciphertext SHA.
"""
import argparse,hashlib,json,pathlib,datetime
def sha(p):
 h=hashlib.sha256()
 with open(p,"rb") as f:
  for part in iter(lambda:f.read(4*1024*1024),b""):h.update(part)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--sealed",required=True)
 ap.add_argument("--label",required=True)
 ap.add_argument("--out",required=True)
 ap.add_argument("--part-bytes",type=int,default=40*1024*1024)
 a=ap.parse_args()
 if not(1*1024*1024 <= a.part_bytes <= 60*1024*1024):raise ValueError("Unsafe chunk size")
 f=pathlib.Path(a.sealed); out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
 parts=[]
 with f.open("rb") as src:
  for idx in range(16):
   buf=src.read(a.part_bytes)
   if not buf:break
   name=f"sealed.part{idx:02d}"
   p=out/name
   p.write_bytes(buf)
   parts.append({"file":name,"bytes":len(buf),"sha256":sha(p)})
  if src.read(1):raise ValueError("Ciphertext requires >16 chunks")
 if not parts:raise ValueError("No source ciphertext")
 m={"schema":"risuap-v032-cipher-chunk-receipt","label":a.label,
    "created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "content_type":"encrypted_json_sealed_v031","ciphertext_file_sha256":sha(f),
    "ciphertext_file_bytes":f.stat().st_size,"parts":parts}
 (out/"transport-receipt.json").write_text(json.dumps(m,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print("TRANSPORT",a.label,m["ciphertext_file_bytes"],len(parts),m["ciphertext_file_sha256"],flush=True)
 for i,x in enumerate(parts):print("CHUNK",a.label,i,x["bytes"],x["sha256"],flush=True)
if __name__=="__main__":main()
