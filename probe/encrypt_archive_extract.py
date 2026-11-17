"""Encrypt selected public-source extracts for private review, never publish raw IDs."""
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

ROOT = Path("output_public_archives")
FILES = ["fl_stage10_selection.lock.json", "fl_stage10_events.json", "fl_stage10_minimal.json"]
out = io.BytesIO()
with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as z:
    for name in FILES:
        p = ROOT / name
        if not p.is_file():
            raise RuntimeError("Missing required source extract " + name)
        z.write(p, arcname=name)
raw = out.getvalue()
pub = serialization.load_pem_public_key(Path("probe/archive-recipient.pem").read_bytes())
key, nonce = os.urandom(32), os.urandom(12)
aad = b"public-archive-extract-v1"
wrapped = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                       algorithm=hashes.SHA256(), label=None))
sealed = AESGCM(key).encrypt(nonce, raw, aad)
payload = {"schema": "public-archive-extract-v1",
           "sha256_plain_archive": hashlib.sha256(raw).hexdigest(),
           "rsa_oaep_key_b64": base64.b64encode(wrapped).decode("ascii"),
           "aes_gcm_nonce_b64": base64.b64encode(nonce).decode("ascii"),
           "ciphertext_b64": base64.b64encode(sealed).decode("ascii")}
Path("encrypted-extract.json").write_text(json.dumps(payload, sort_keys=True) + "\n")
print("Sealed deterministic source extracts; plaintext was not uploaded.")
