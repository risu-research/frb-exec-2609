#!/usr/bin/env python3
import argparse, hashlib, json, os, zipfile
from pathlib import Path

EXPECTED = {
    "artifact_id": 10284868064,
    "artifact_name": "replaymark-artifact-v4-g5-postmiss-pass-candidate",
    "zip_sha256": "cbff30ebe4e5004ac37baad7b39e5febb3d58a229dfaa8e3d30b78e4a5522573",
    "run_id": 34654381011,
    "execution_head": "055c6d13822907fa8692fc83cab303534185dd2b",
    "public_freeze_blob": "14bfc2bf40e3cf1b94dafc38d916ebc4ade03841",
    "independent_audit_blob": "ab83e8d9503692524c4e6a308f694d3770d506d9",
    "consequential": 49,
    "metamorphic": 8,
    "obligations": 60,
}

def sha256_file(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def git_blob_sha_bytes(b):
    return hashlib.sha1(f"blob {len(b)}\0".encode()+b).hexdigest()

def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def dump(obj,p):
    Path(p).write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n",encoding="utf-8")

def die(msg):
    raise SystemExit("G6_CLOSURE_FAIL: "+msg)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--zip",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--repo-root",default=".")
    args=ap.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    root=Path(args.repo_root)

    freeze_path=root/"artifact/v4-g5/ARTIFACT_V4_G5_PUBLIC_PASS_FREEZE_V1.json"
    audit_path=root/"artifact/v4-g5/ARTIFACT_V4_G5_INDEPENDENT_REDOWNLOAD_AUDIT_V1.json"
    for p in (freeze_path,audit_path):
        if not p.is_file(): die(f"missing frozen input {p}")
    freeze_bytes=freeze_path.read_bytes(); audit_bytes=audit_path.read_bytes()
    if git_blob_sha_bytes(freeze_bytes)!=EXPECTED["public_freeze_blob"]: die("public G5 freeze Git blob mismatch")
    if git_blob_sha_bytes(audit_bytes)!=EXPECTED["independent_audit_blob"]: die("independent audit Git blob mismatch")
    freeze=json.loads(freeze_bytes); audit=json.loads(audit_bytes)
    if freeze.get("status")!="FROZEN_ARTIFACT_V4_G5_POSTMISS_PASS": die("unexpected G5 freeze status")
    if audit.get("status")!="PASS_INDEPENDENT_REDOWNLOAD_AND_RECOMPUTATION": die("unexpected independent audit status")

    zpath=Path(args.zip)
    if not zpath.is_file(): die("artifact zip absent")
    outer_sha=sha256_file(zpath)
    if outer_sha!=EXPECTED["zip_sha256"]: die("artifact ZIP sha256 mismatch")
    if freeze["evidence_capsule"]["independent_redownload_sha256"]!=outer_sha: die("freeze-to-artifact ZIP binding mismatch")
    if audit["artifact"]["independently_recomputed_zip_sha256"]!=outer_sha: die("audit-to-artifact ZIP binding mismatch")

    extract=out/"g5_extract"; extract.mkdir(exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        base=str(extract.resolve())+os.sep
        for info in z.infolist():
            target=str((extract/info.filename).resolve())
            if not target.startswith(base): die("zip path traversal")
        z.extractall(extract)
    sums=extract/"SHA256SUMS.txt"
    if not sums.is_file(): die("SHA256SUMS absent")
    checked=0
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: expected,rel=line.split(None,1)
        except ValueError: die("malformed SHA256SUMS line")
        p=extract/rel.strip()
        if not p.is_file(): die(f"missing indexed file {rel.strip()}")
        if sha256_file(p)!=expected: die(f"recursive checksum mismatch {rel.strip()}")
        checked+=1
    if checked<100: die("implausibly small recursive checksum index")

    cases=load_json(extract/"G5_POSTMISS_CASE_RESULTS.json")
    receipt=load_json(extract/"G5_POSTMISS_CAMPAIGN_RECEIPT.json")
    evid=load_json(extract/"G5_POSTMISS_EVIDENCE_INDEX.json")
    preflight=load_json(extract/"G5_POSTMISS_OUTER_PREFLIGHT_RECEIPT.json")
    pristine=load_json(extract/"PRISTINE_B_VECTOR.json")
    consequential=cases.get("consequential",[]); metamorphic=cases.get("metamorphic",[])
    if len(consequential)!=49: die("wrong consequential record count")
    if len(metamorphic)!=8: die("wrong metamorphic record count")
    cids=[x.get("challenge_id") for x in consequential]; mids=[x.get("challenge_id") for x in metamorphic]
    if len(set(cids))!=49: die("duplicate consequential challenge id")
    if len(set(mids))!=8: die("duplicate metamorphic challenge id")

    false_negatives=sum(x.get("status")!="DETECTED" for x in consequential)
    false_positives=sum(x.get("status")!="STABLE" for x in metamorphic)
    ab_disagreements=sum(bool(x.get("A_normalized_detected"))!=bool(x.get("B_normalized_detected")) for x in consequential)
    unexplained_extra_kills=sum(len(x.get("unexplained_extra_changed_claims") or []) for x in consequential)
    if false_negatives: die(f"{false_negatives} false negatives")
    if false_positives: die(f"{false_positives} metamorphic false positives")
    if ab_disagreements: die(f"{ab_disagreements} A/B detection disagreements")
    if unexplained_extra_kills: die(f"{unexplained_extra_kills} unexplained extra kills")

    dynamic=set(); undetected_occurrences=[]
    for x in consequential:
        for ob,det in (x.get("target_obligation_detected") or {}).items():
            if det: dynamic.add(ob)
            else: undetected_occurrences.append({"challenge_id":x["challenge_id"],"obligation":ob})
    if len(dynamic)!=60: die(f"dynamic obligation union is {len(dynamic)} not 60")

    byid={x["challenge_id"]:x for x in consequential}
    for cid in ("C14_N2_PREREG_SOURCE_ACTION","C49_N2_PREREG_SOURCE_VARIANT_CROSS_BINDING_TWIN"):
        if cid not in byid: die(f"missing {cid}")
        x=byid[cid]
        if x.get("status")!="DETECTED" or not x.get("B_normalized_detected"): die(f"{cid} not detected by B")
        if x.get("B_detection_mode")!="FAIL_CLOSED": die(f"{cid} did not exercise fail-closed detection")

    pg=receipt.get("pass_gate",{})
    required={
      "consequential_mutation_false_negatives":0,
      "metamorphic_false_positives":0,
      "applicable_A_B_normalized_detection_disagreements":0,
      "unexplained_extra_kills":0,
      "dynamic_obligation_coverage":"60/60",
      "static_obligation_coverage":"60/60",
      "edge_coverage":"56/56",
      "authority_node_exercise":"19/19",
      "asymmetry_surface_coverage":"16/16",
      "new_scientific_measurements":0,
      "historical_experiment_reruns":0,
      "canonical_authority_modifications":0,
      "post_hoc_reselection":0,
      "original_C14_detected":True,
      "independent_C49_twin_detected":True
    }
    for k,v in required.items():
        if pg.get(k)!=v: die(f"campaign gate mismatch {k}")
    if preflight.get("status")!="PASS_POSTMISS_OUTER_IDENTITY_AND_FRESHNESS_GATE": die("freshness gate not PASS")
    if preflight.get("fresh_output_directory") is not True or preflight.get("challenge_results_reused") is not False: die("freshness semantics not satisfied")
    if preflight.get("scientific_authorities_modified") is not False or preflight.get("thresholds_modified") is not False: die("preflight noninterference failed")
    if evid.get("public_run_id")!=EXPECTED["run_id"] or evid.get("public_execution_head")!=EXPECTED["execution_head"]: die("evidence index run identity mismatch")
    if len(pristine)!=42: die("pristine B vector claim count != 42")

    matrix={
      "schema":"replaymark.artifact-v4.g6-public-detection-matrix.v1",
      "source_artifact_zip_sha256":outer_sha,
      "consequential":[{
        "ordinal":x.get("ordinal"),"challenge_id":x.get("challenge_id"),"status":x.get("status"),"node":x.get("node"),
        "obligations":x.get("obligations",[]),"target_obligation_detected":x.get("target_obligation_detected",{}),
        "A_normalized_detected":x.get("A_normalized_detected"),"B_normalized_detected":x.get("B_normalized_detected"),
        "B_detection_mode":x.get("B_detection_mode"),"B_rc":x.get("B_rc"),"changed_claims":x.get("changed_claims",[]),
        "unexplained_extra_changed_claims":x.get("unexplained_extra_changed_claims",[])
      } for x in consequential],
      "metamorphic":[{"ordinal":x.get("ordinal"),"challenge_id":x.get("challenge_id"),"status":x.get("status"),"B_vector_sha256":x.get("B_vector_sha256"),"B_rc":x.get("B_rc")} for x in metamorphic],
      "recomputed_summary":{
        "consequential_records":49,"metamorphic_records":8,"false_negatives":0,"false_positives":0,
        "A_B_detection_disagreements":0,"unexplained_extra_kills":0,"dynamic_obligation_union_count":60,
        "dynamic_obligation_union":sorted(dynamic),"undetected_target_occurrences":undetected_occurrences,
        "C14_fail_closed":True,"C49_fail_closed":True
      }
    }
    matrix_path=out/"G6_PUBLIC_DETECTION_MATRIX_V1.json"; dump(matrix,matrix_path)

    closure={
      "schema":"replaymark.artifact-v4.g6-public-closure-receipt.v1",
      "status":"PASS_G6_PUBLIC_EVIDENCE_CLOSURE",
      "method":"EVIDENCE_ONLY_INDEPENDENT_RECONSTRUCTION_NO_CHALLENGE_RERUN",
      "source":{"repository":"risu-research/frb-exec-2609","g5_run_id":EXPECTED["run_id"],"g5_execution_head":EXPECTED["execution_head"],"g5_artifact_id":EXPECTED["artifact_id"],"g5_artifact_name":EXPECTED["artifact_name"],"g5_artifact_zip_sha256":outer_sha,"g5_public_freeze_git_blob":EXPECTED["public_freeze_blob"],"g5_independent_audit_git_blob":EXPECTED["independent_audit_blob"]},
      "integrity":{"recursive_SHA256SUMS_entries_verified":checked,"campaign_receipt_sha256":sha256_file(extract/"G5_POSTMISS_CAMPAIGN_RECEIPT.json"),"case_results_sha256":sha256_file(extract/"G5_POSTMISS_CASE_RESULTS.json"),"evidence_index_sha256":sha256_file(extract/"G5_POSTMISS_EVIDENCE_INDEX.json"),"outer_preflight_sha256":sha256_file(extract/"G5_POSTMISS_OUTER_PREFLIGHT_RECEIPT.json"),"pristine_B_vector_sha256":sha256_file(extract/"PRISTINE_B_VECTOR.json"),"detection_matrix_sha256":sha256_file(matrix_path)},
      "recomputed_verdict":{"consequential":"49/49 DETECTED","metamorphic":"8/8 STABLE","false_negatives":0,"false_positives":0,"A_B_detection_disagreements":0,"unexplained_extra_kills":0,"dynamic_obligation_coverage":"60/60","static_obligation_coverage":pg["static_obligation_coverage"],"claim_to_authority_edge_coverage":pg["edge_coverage"],"authority_node_exercise":pg["authority_node_exercise"],"extraction_asymmetry_surface_coverage":pg["asymmetry_surface_coverage"],"C14_detected_fail_closed":True,"C49_detected_fail_closed":True},
      "noninterference":{"Verifier_A_rerun_in_G6":False,"Verifier_B_rerun_in_G6":False,"challenge_rerun_in_G6":False,"experiment_rerun_in_G6":False,"authority_modified_in_G6":False,"manuscript_modified_in_G6":False,"threshold_changed_in_G6":False,"prior_failure_reclassified_in_G6":False},
      "scope":{"public_receipt_is_not_yet_the_private_full_V4_failure_lineage_verdict":True,"next_step":"Bind this public evidence closure to the complete private G0-G5 gate chain and preserved failure ledger, then freeze final V4 verdict."}
    }
    receipt_path=out/"G6_PUBLIC_CLOSURE_RECEIPT_V1.json"; dump(closure,receipt_path)
    manifest_path=out/"SHA256SUMS_G6_PUBLIC.txt"
    manifest_path.write_text(f"{sha256_file(matrix_path)}  G6_PUBLIC_DETECTION_MATRIX_V1.json\n{sha256_file(receipt_path)}  G6_PUBLIC_CLOSURE_RECEIPT_V1.json\n",encoding="utf-8")
    print(json.dumps({"status":"PASS_G6_PUBLIC_EVIDENCE_CLOSURE","matrix_sha256":sha256_file(matrix_path),"receipt_sha256":sha256_file(receipt_path),"manifest_sha256":sha256_file(manifest_path),"recursive_entries_verified":checked},sort_keys=True))

if __name__=="__main__":
    main()
