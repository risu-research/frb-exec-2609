#!/usr/bin/env python3
"""Full official Colorado entityid/name capture; encrypt before artifact upload.

Public GitHub-hosted execution: no secret or rows are printed/uploaded unencrypted.
Source snapshot is rejected if its metadata or official row census changes.
"""
from __future__ import annotations
import base64, hashlib, json, lzma, os, pathlib, re, sqlite3, sys, time, unicodedata, urllib.parse, urllib.request
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE='https://data.colorado.gov'; DATASET='4ykn-tg5h'
META=f'{BASE}/api/views/{DATASET}.json'; API=f'{BASE}/resource/{DATASET}.json'
ID=re.compile(r'[1-9][0-9]*\Z')

def get_json(url):
    if not(url == META or url.startswith(API+'?')):raise ValueError('Non-official request prohibited')
    last=None
    for attempt in range(7):
        try:
            rq=urllib.request.Request(url,headers={'User-Agent':'RISUAP-name-source-census/0.3.8', 'Accept':'application/json'})
            with urllib.request.urlopen(rq,timeout=90) as response:
                if response.status!=200:raise IOError('Official API HTTP '+str(response.status))
                return json.load(response)
        except (OSError,ValueError) as exc:
            last=exc
            if attempt<6:time.sleep(min(60,3*2**attempt))
    raise RuntimeError('Official API unavailable after bounded retries') from last

def soql(params):return API+'?'+urllib.parse.urlencode(params)

def edition():
    data=get_json(META)
    if data.get('id')!=DATASET:raise RuntimeError('Unexpected publisher dataset')
    cols={x.get('fieldName'):x.get('dataTypeName') for x in data.get('columns',[])}
    if cols.get('entityid')!='number' or cols.get('entityname')!='text':
        raise RuntimeError('Publisher source column definitions changed')
    if not isinstance(data.get('rowsUpdatedAt'),int) or not isinstance(data.get('viewLastModified'),int):
        raise RuntimeError('Missing publisher edition')
    return {'dataset':DATASET,'rows_updated_epoch':data['rowsUpdatedAt'],
            'metadata_updated_epoch':data['viewLastModified'],'license_id':data.get('licenseId')}

def count():
    rows=get_json(soql({'$select':'count(*) AS n'}))
    if not isinstance(rows,list) or len(rows)!=1 or 'n' not in rows[0]:raise RuntimeError('Malformed official census')
    result=int(rows[0]['n'])
    if result<3000000:raise RuntimeError('Unexpectedly small official source census')
    return result

def hash_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()

def build(db_path: pathlib.Path):
    first=edition();expected=count(); rows=0; missing=0; last_id=0; digest=hashlib.sha256()
    con=sqlite3.connect(db_path)
    try:
        con.execute('PRAGMA journal_mode=DELETE')
        con.execute('PRAGMA synchronous=FULL')
        con.execute('CREATE TABLE co_names(entity_key TEXT PRIMARY KEY,name_source TEXT,name_key TEXT)')
        con.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        while rows<expected:
            p={'$select':'entityid,entityname','$order':'entityid ASC','$limit':'10000',
               '$where':f'entityid > {last_id}'}
            batch=get_json(soql(p))
            if not isinstance(batch,list) or not batch or len(batch)>10000:raise RuntimeError('Truncated official page')
            records=[]
            for item in batch:
                if not isinstance(item,dict):raise RuntimeError('Malformed publisher row')
                ident=item.get('entityid'); original=item.get('entityname')
                if not isinstance(ident,str) or not ID.fullmatch(ident):raise RuntimeError('Bad official numeric entity identifier')
                numeric=int(ident)
                if numeric<=last_id:raise RuntimeError('Nonmonotonic publisher numeric ID or duplicate')
                if original is not None and not isinstance(original,str):raise RuntimeError('Nonnative name type')
                key=unicodedata.normalize('NFKC',original).casefold().strip() if original and original.strip() else None
                if key is None:missing+=1
                records.append(('US-CO:'+ident,original,key))
                digest.update(json.dumps([ident,original],ensure_ascii=False,separators=(',',':')).encode()+b'\n')
                last_id=numeric;rows+=1
                if rows>expected:raise RuntimeError('Publisher count increased within pinned edition')
            con.executemany('INSERT INTO co_names VALUES(?,?,?)',records)
            con.commit()
            if rows%100000==0:print('COMPLETED_ROWS',rows,flush=True)
        last=edition();final_count=count()
        if first!=last or expected!=final_count or rows!=expected:
            raise RuntimeError('Source edition / official census changed; reject acquisition')
        con.execute('CREATE INDEX co_name_key_entity_idx ON co_names(name_key,entity_key)')
        metadata={**first,'verified_complete':'1','indexed_rows':str(rows),
             'missing_name_rows':str(missing),'canonical_name_pairs_sha256':digest.hexdigest(),
             'source_role':'later-observed-master-name-snapshot'}
        con.executemany('INSERT INTO meta VALUES(?,?)',[(k,str(v)) for k,v in metadata.items()])
        con.commit()
        integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok':raise RuntimeError('Complete SQLite integrity_check failed')
        return {'schema':'risuap-v038-co-name-2026-official-full-source-v2',
                'status':'VERIFIED_COMPLETE','source_dataset':DATASET,
                'source_url':f'{BASE}/Business/Business-Entities-in-Colorado/{DATASET}',
                'edition':first,'official_count_first':expected,'official_count_last':final_count,
                'rows':rows,'missing_name_rows':missing,'name_pair_digest':digest.hexdigest(),
                'sqlite_integrity_check':integrity}
    finally:con.close()

def compress_encrypt(db: pathlib.Path, report:dict, pubkey_path: pathlib.Path, artifact: pathlib.Path):
    raw_sha=hash_file(db); raw_bytes=db.stat().st_size
    compress=artifact/'co_names.sqlite3.xz'; cipherpath=artifact/'co_names.sqlite3.xz.aesgcm'
    with open(db,'rb') as src,lzma.open(compress,'wb',preset=5) as dst:
        for block in iter(lambda:src.read(1<<20),b''):dst.write(block)
    zip_sha=hash_file(compress)
    pub=serialization.load_pem_public_key(pubkey_path.read_bytes())
    key=os.urandom(32);nonce=os.urandom(12)
    enc=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
    with open(compress,'rb') as src,open(cipherpath,'wb') as dst:
        for block in iter(lambda:src.read(1<<20),b''):dst.write(enc.update(block))
        dst.write(enc.finalize())
    wrapped=pub.encrypt(key,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    report.update({'sqlite_sha256':raw_sha,'sqlite_bytes':raw_bytes,
         'xz_sha256':zip_sha,'xz_bytes':compress.stat().st_size,
         'encrypted_filename':cipherpath.name,'encrypted_sha256':hash_file(cipherpath),
         'encrypted_bytes':cipherpath.stat().st_size,'encryption':'AES-256-GCM + RSA-OAEP-SHA256',
         'nonce_b64':base64.b64encode(nonce).decode(), 'tag_b64':base64.b64encode(enc.tag).decode(),
         'wrapped_key_b64':base64.b64encode(wrapped).decode(),
         'public_key_sha256':hash_file(pubkey_path),
         'plaintext_source_rows_in_public_git':False})
    (artifact/'PUBLIC_RECEIPT.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    os.remove(compress)
    os.remove(db)
    del key
    print('SUCCESS_FULL_SOURCE_ENCRYPTED',report['rows'],'AESGCM',report['encrypted_bytes'],flush=True)

def main():
    out=pathlib.Path(sys.argv[1]);public=pathlib.Path(sys.argv[2]);work=pathlib.Path(sys.argv[3])
    out.mkdir(parents=True,exist_ok=False);work.mkdir(parents=True,exist_ok=False)
    db=work/'co_names.sqlite3'
    result=build(db)
    compress_encrypt(db,result,public,out)

if __name__=='__main__':main()