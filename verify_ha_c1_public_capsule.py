from __future__ import annotations
import ast, base64, gzip, hashlib, json, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent
M=json.loads((ROOT/'HA_C1_PUBLIC_CAPSULE_MANIFEST.json').read_text())

def sha(p: Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()
def git(*a:str)->str: return subprocess.check_output(['git',*a],cwd=ROOT,text=True).strip()

def main()->None:
    assert M['status']=='FROZEN_BEFORE_PUBLIC_QUALIFICATION_RUN'
    base=M['pre_c1_main']
    subprocess.check_call(['git','merge-base','--is-ancestor',base,'HEAD'],cwd=ROOT)
    changed=set(filter(None,git('diff','--name-only',f'{base}..HEAD').splitlines()))
    expected=set(M['added_path_allowlist'])
    assert changed==expected, ('public changed-path mismatch',sorted(changed-expected),sorted(expected-changed))
    status=git('diff','--name-status',f'{base}..HEAD').splitlines()
    assert all(x.startswith('A\t') for x in status), status

    for group in ('source_hashes','shim_hashes'):
        for rel,want in M[group].items():
            got=sha(ROOT/rel); assert got==want,(rel,got,want)

    oracle=ast.parse((ROOT/'ha_c1_literal_oracle.py').read_text())
    for n in ast.walk(oracle):
        if isinstance(n,ast.Import): assert all(not a.name.startswith('replaymark') for a in n.names)
        elif isinstance(n,ast.ImportFrom): assert not (n.module or '').startswith('replaymark')

    for rel in M['shim_hashes']:
        text=(ROOT/rel).read_text().lower()
        for forbidden in ('homeassistant','preset_mode','climate.agentmark','comfort','set_preset_mode'):
            assert forbidden not in text,(rel,forbidden)

    package=ROOT/'fixtures/HA_C1_ARCHIVED_FIXTURES_V1.json.gz.b64'
    raw=gzip.decompress(base64.b64decode(package.read_bytes()))
    assert hashlib.sha256(raw).hexdigest()==M['decoded_fixture_sha256']
    fixture=json.loads(raw)
    assert len(fixture['observations'])==M['expected_population']['observations']
    assert len(fixture['actions'])==M['expected_population']['actions']
    (ROOT/'fixtures/HA_C1_ARCHIVED_FIXTURES_V1.json').write_bytes(raw)
    print(json.dumps({'stage':'HA-C1-PUBLIC-PREFLIGHT','status':'PASS','private_source_freeze_head':M['private_source_authority']['source_freeze_head'],'positive_records':216,'negative_cases':10},sort_keys=True,indent=2))

if __name__=='__main__': main()
