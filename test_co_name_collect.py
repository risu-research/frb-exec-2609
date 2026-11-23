"""Synthetic tests, safe to run publicly. No real entity names or IDs."""
from __future__ import annotations
import base64,importlib.util,json, tempfile,pathlib,sqlite3,hashlib,lzma
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

spec=importlib.util.spec_from_file_location('co_names',str(pathlib.Path(__file__).parent/'co_name_collect.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def synthetic_test():
    with tempfile.TemporaryDirectory() as temp:
        t=pathlib.Path(temp); names=[(10,'B & C'),(11,'Oregon LLC'),(99,'B & C'),(1000,''),(1100,'Ｈｉｇｈ')]
        original={'id':m.DATASET,'rowsUpdatedAt':1,'viewLastModified':2,'licenseId':'PUBLIC_DOMAIN',
                  'columns':[{'fieldName':'entityid','dataTypeName':'number'}, {'fieldName':'entityname','dataTypeName':'text'}]}
        source=lambda:original.copy()
        def fetch(url):
            if url==m.META:return source()
            from urllib.parse import parse_qs,urlsplit
            p=parse_qs(urlsplit(url).query)
            if 'count(' in p.get('$select',[''])[0]:return [{'n':str(len(names))}]
            where=p['$where'][0];last=int(where.split('>')[1]);return [{'entityid':str(i),'entityname':v} for i,v in names if i>last][:2]
        m.get_json=fetch;m.count=lambda:len(names)
        db=t/'real.sqlite3';rec=m.build(db)
        assert rec['rows']==5,rec
        with sqlite3.connect(db) as c:
            assert c.execute('select count(*) from co_names').fetchone()[0]==5
            assert c.execute("select name_key from co_names where entity_key='US-CO:1100'").fetchone()[0]=='high'
            assert c.execute("select count(*) from co_names where name_key='b & c'").fetchone()[0]==2
        priv=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pub=t/'p.pem';pub.write_bytes(priv.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
        artifact=t/'encrypted';artifact.mkdir()
        m.compress_encrypt(db,rec,pub,artifact)
        assert not db.exists()
        receipt=json.loads((artifact/'PUBLIC_RECEIPT.json').read_text())
        aeskey=priv.decrypt(base64.b64decode(receipt['wrapped_key_b64']),padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        dec=Cipher(algorithms.AES(aeskey),modes.GCM(base64.b64decode(receipt['nonce_b64']),base64.b64decode(receipt['tag_b64']))).decryptor()
        cipher=(artifact/receipt['encrypted_filename']).read_bytes();plain=dec.update(cipher)+dec.finalize()
        assert hashlib.sha256(plain).hexdigest()==receipt['xz_sha256']
        assert hashlib.sha256(lzma.decompress(plain)).hexdigest()==receipt['sqlite_sha256']
        print('SYNTHETIC_CAPTURE_ENCRYPT_DECRYPT_PASS')

if __name__=='__main__':synthetic_test()