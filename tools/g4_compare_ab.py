#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def h(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()
def canon(x)->bytes: return (json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--a',required=True); ap.add_argument('--b',required=True); ap.add_argument('--b-trace',required=True); ap.add_argument('--out',required=True); args=ap.parse_args()
    pa,pb,pt=map(Path,[args.a,args.b,args.b_trace]); A=json.loads(pa.read_text()); B=json.loads(pb.read_text()); T=json.loads(pt.read_text())
    assert A.get('status')=='DERIVED_WITHOUT_MANUSCRIPT_EXPECTED_VALUES',A.get('status')
    assert A.get('claim_count')==42,A.get('claim_count')
    law=A.get('derivation_law',{}); assert law.get('claim_ledger_read') is False and law.get('manuscript_expected_values_read') is False
    assert isinstance(B,dict) and len(B)==42,len(B) if isinstance(B,dict) else type(B)
    assert T.get('expected_values_read') is False and T.get('verifier_a_output_read') is False
    assert T.get('claim_vector_sha256')==hashlib.sha256((json.dumps(B,indent=2)+'\n').encode()).hexdigest()
    aclaims=A['claims']; idsA=set(aclaims); idsB=set(B)
    mismatches=[]
    for cid in sorted(idsA|idsB):
        if cid not in aclaims: mismatches.append({'claim_id':cid,'kind':'ONLY_B'})
        elif cid not in B: mismatches.append({'claim_id':cid,'kind':'ONLY_A'})
        elif aclaims[cid]!=B[cid]: mismatches.append({'claim_id':cid,'kind':'VALUE','A':aclaims[cid],'B':B[cid]})
    agreed=not mismatches and len(idsA)==42 and len(idsB)==42
    out={
      'schema':'replaymark.artifact-v4.g4-a-b-blind-comparison.v1',
      'status':'PASS_A_EQUALS_B_EXACT_42_OF_42' if agreed else 'FAIL_A_B_PRISTINE_BASELINE_DIVERGENCE',
      'expected_values_opened':False,'manuscript_opened':False,'claim_ledger_opened':False,
      'A_claim_count':len(idsA),'B_claim_count':len(idsB),'exact_match_count':42-len(mismatches) if len(idsA)==len(idsB)==42 else None,
      'mismatches':mismatches,
      'A_artifact_sha256':h(pa),'B_artifact_sha256':h(pb),'B_trace_sha256':h(pt),
      'A_canonical_claim_vector_sha256':hashlib.sha256(canon(aclaims)).hexdigest(),
      'B_canonical_claim_vector_sha256':hashlib.sha256(canon(B)).hexdigest(),
      'new_scientific_measurement':False,'historical_experiment_rerun':False,'mutation_executed':False
    }
    Path(args.out).write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':out['status'],'mismatches':len(mismatches)},sort_keys=True))
    if not agreed: raise SystemExit(3)
if __name__=='__main__': main()
