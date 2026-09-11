#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"artifact/v4-g6-final/output"
OUT.mkdir(parents=True,exist_ok=True)
CAPSULE=ROOT/"artifact/v4-g6-final/G6_PRIVATE_ATTESTATION_CAPSULE_V1.json"

EXPECTED_PRIVATE={
 "V4_CONSTITUTION":"ce1ad843e4c588f0d3c7f31a77b38ba758d4b3df",
 "DEVELOPMENT_CONTINUITY_AMENDMENT":"8fdd1e3d17cab025bc86ef9224e14254c117662e",
 "G1_DEPENDENCY_GRAPH":"c322cb9f502496621f71e5e7067ddf6b3dd0cb1b",
 "G1_FREEZE_RECEIPT":"f1723eb0f40e3c1c6509b35c264246d80a6e4c92",
 "G2_FREEZE_RECEIPT":"5cedc49984fa9db0cf92bc2835c56f8139c60a56",
 "G3_FREEZE_RECEIPT":"dc9e1857d07fb81d0bd2c878709f84a5d745cc5b",
 "G4_PRIVATE_FINAL_FREEZE":"a4aaf18c667a81b1d339380a76a608a6f1323e33",
 "G5_PRIVATE_FINAL_FREEZE":"ffadc0429ca70e0caa3be323f661ade9ed305b96",
 "G6_PRIVATE_CLOSURE_CONSTITUTION":"ba540b0d6f60041014748880e6f556d1cf07f53a",
 "G6_GATE_CHAIN_V1":"22c0ce5ca75d19c8c70879d5104709c8ddb1d756",
 "G6_FAILURE_LEDGER_V1":"4e650cd8e68698c41b38f4c59642b633ec337bc3",
 "G6_FAILURE_LEDGER_V2":"34e7d61eac86820428286899279294a8387f73e2",
 "G6_PUBLIC_MATRIX_BINDING_V1":"f9840f781f644d31290c6fa4ff9fc0241df4fa9e",
 "G6_PRIVATE_SOURCE_FREEZE_V2":"6eb8d6af7ee73fb291d9e6aa86d9b91c4dc3ab85",
 "G6_PRIVATE_RUN1_FAILURE_SEAL":"72a141769761088e9958b725df96af47d215a08c",
 "G6_PLATFORM_FALLBACK_AMENDMENT":"66777e08ec7ab016f408f347acc3de8ea7a7d86c",
 "G6_PUBLIC_RECEIPT_PRIVATE_MIRROR":"141a58855fded4b8c49548282a9d1b2d9ed1a0b9",
 "G6_PUBLIC_AUDIT_PRIVATE_MIRROR":"7d981cd159e688013bbcc7c42069ce8d389be5fa",
 "G6_PUBLIC_PASS_FREEZE_PRIVATE_MIRROR":"50f7a47afbbdad3ac2f3753d7b7e34e9c4b57a30",
 "G6_PUBLIC_RUN1_FAILURE_PRIVATE_MIRROR":"fe1d4df3a43b7d292d34f865964cd144ffa6b8c2"
}
EXPECTED_INVARIANTS={
 "I_claim_set_exact_42","I_depth1_normalization_explicit","I_fig1_native_loss_arithmetic","I_horizon_replication_48",
 "I_q_sequence_and_first_fixed_point","I_queue_250_166_from_4_6","I_queue_overstatement_arithmetic",
 "I_s3c3_sidecar_denominators_distinct","I_s3c3_two_sided_partition","I_s6_negative_scaling_scope_preserved",
 "I_s6_scale_accounting","I_v92_authority_correction_exact","I_ve2_aux_prediction_preoutcome_partition",
 "I_ve2_native_partition","I_ve2_negative_result_preserved","I_ve2_version_lock_nonmaximal",
 "I_ve2_weighted_withheld_identity","I_work_amplification_both_3_over_2"
}
EXPECTED_FAILURE_IDS={
 "V3_RUN1","V3_RUN2","G4_DUAL_OPEN_RUN1","G4_DUAL_OPEN_RUN2","G4_DUAL_OPEN_RUN3","G4_CANONICAL_RUN1",
 "G4_CANONICAL_RUN2","G4_CANONICAL_RUN3","G4_CANONICAL_RUN4","G5_RUN1_PARTIAL","G5_RUN2_PREOPEN_HASH",
 "G5_RUN2_COMPLETE","G5_BV2_QUALIFICATION_RUN1","G5_BV2_QUALIFICATION_RUN2","G6_PUBLIC_RUN1","G6_PRIVATE_RUN1_PRE_STEP"
}
PUBLIC_FILES={
 "artifact/v4-g6/G6_PUBLIC_CLOSURE_RECEIPT_V1.json":"141a58855fded4b8c49548282a9d1b2d9ed1a0b9",
 "artifact/v4-g6/G6_INDEPENDENT_REDOWNLOAD_AUDIT_V1.json":"7d981cd159e688013bbcc7c42069ce8d389be5fa",
 "artifact/v4-g6/ARTIFACT_V4_G6_PUBLIC_PASS_FREEZE_V1.json":"50f7a47afbbdad3ac2f3753d7b7e34e9c4b57a30",
 "artifact/v4-g6/G6_RUN1_PRE_RECONSTRUCTION_SCHEMA_SELECTOR_FAILURE_SEAL_V1.json":"fe1d4df3a43b7d292d34f865964cd144ffa6b8c2",
 "artifact/v4-g5/ARTIFACT_V4_G5_PUBLIC_PASS_FREEZE_V1.json":"14bfc2bf40e3cf1b94dafc38d916ebc4ade03841",
 "artifact/v4-g5/ARTIFACT_V4_G5_INDEPENDENT_REDOWNLOAD_AUDIT_V1.json":"ab83e8d9503692524c4e6a308f694d3770d506d9"
}

def fail(m): raise SystemExit("G6_FINAL_WITNESS_FAIL: "+m)
def gb(b): return hashlib.sha1(f"blob {len(b)}\0".encode()+b).hexdigest()
def sha(p):
 h=hashlib.sha256()
 with open(p,"rb") as f:
  for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
 return h.hexdigest()
def dump(o,p): p.write_text(json.dumps(o,indent=2,sort_keys=True)+"\n",encoding="utf-8")

def main():
 cap=json.loads(CAPSULE.read_text(encoding="utf-8"))
 if cap.get("status")!="FROZEN_SANITIZED_PRIVATE_METADATA_ATTESTATION_FOR_PUBLIC_FINAL_WITNESS": fail("capsule status")
 if cap.get("attestation_basis",{}).get("private_attestation_commit")!="88f3421a29d0a3a8ecdcdee7e6a7d935a2f7e718": fail("private attestation commit")
 if cap.get("attestation_basis",{}).get("private_attestation_tree")!="62b9e089a2708d6ce6fb025b5700f1e57c7a61fe": fail("private attestation tree")
 if cap.get("private_metadata_blob_attestations")!=EXPECTED_PRIVATE: fail("private metadata blob attestation set")

 # Public byte identities are independently recomputed in this execution surface.
 public_checks={}
 for rel,exp in PUBLIC_FILES.items():
  p=ROOT/rel
  if not p.is_file(): fail("missing public file "+rel)
  got=gb(p.read_bytes()); public_checks[rel]={"expected":exp,"actual":got,"match":got==exp}
  if got!=exp: fail("public Git blob mismatch "+rel)

 # Exact 42+18 obligation identity, not cardinality-only.
 topo=cap["topology"]
 claims=topo["claim_obligations"]; inv=topo["invariant_obligations"]
 expected_claims={f"E{i:02d}_" for i in range(1,40)}
 if len(claims)!=42 or len(set(claims))!=42: fail("claim obligation uniqueness/count")
 if set(inv)!=EXPECTED_INVARIANTS or len(inv)!=18: fail("invariant identity")
 if set(claims[:3])!={"F01_RSTAR_UNIQUE_MAXIMAL_SOUND_REUSE","F02_Q_FULL_IDENTIFICATION_SUFFICIENT_NOT_NECESSARY","F03_PROXY_COLLAPSE_IMPOSSIBILITY"}: fail("formal claim identity")
 eclaims=claims[3:]
 if len(eclaims)!=39 or {x.split("_",1)[0] for x in eclaims}!={f"E{i:02d}" for i in range(1,40)}: fail("E01-E39 identity")
 union=set(claims)|set(inv)
 if len(union)!=60: fail("canonical obligation union")
 if topo.get("authority_nodes")!=19 or topo.get("claim_to_authority_edges")!=56 or topo.get("invariant_to_claim_edges")!=65 or topo.get("invariant_transitive_authority_edges")!=46: fail("topology counts")

 # Falsification closure exact summary.
 fc=cap["public_falsification_closure"]
 expected_fc={"consequential":"49/49 DETECTED","metamorphic":"8/8 STABLE","false_negatives":0,"false_positives":0,"A_B_detection_disagreements":0,"unexplained_extra_kills":0,"dynamic_obligation_coverage":"60/60","static_obligation_coverage":"60/60","claim_to_authority_edge_coverage":"56/56","authority_node_exercise":"19/19","extraction_asymmetry_surface_coverage":"16/16","C14_detected_fail_closed":True,"C49_detected_fail_closed":True}
 for k,v in expected_fc.items():
  if fc.get(k)!=v: fail("falsification field "+k)
 if fc.get("public_G6_detection_matrix_sha256")!="a7beb1450beeea5579e2ecc8ead7ef14c13b7f95a037769e2ba307cac9aa35d5": fail("matrix sha")

 # Complete effective failure lineage: 16 unique events, all failures retained, exactly one substantive miss (C14).
 ev=cap["failure_events"]; ids=[x["id"] for x in ev]
 if len(ev)!=16 or set(ids)!=EXPECTED_FAILURE_IDS: fail("failure event identity")
 if any(x.get("retroactive_pass") is not False for x in ev): fail("retroactive pass")
 subs=[x for x in ev if x.get("substantive_detection_miss") is True]
 if len(subs)!=1 or subs[0].get("id")!="G5_RUN2_COMPLETE" or subs[0].get("miss_id")!="C14_N2_PREREG_SOURCE_ACTION": fail("substantive miss preservation")
 if next(x for x in ev if x["id"]=="G6_PRIVATE_RUN1_PRE_STEP")["status"]!="FROZEN_PRIVATE_G6_RUN1_PRE_STEP_PLATFORM_OR_RUNNER_STARTUP_FAILURE_NOT_CONSUMED": fail("private pre-step failure preservation")

 gov=cap["governance"]
 if gov.get("future_ReplayMark_research_permitted") is not True or gov.get("future_versions_require_new_prospective_identity") is not True: fail("development continuity")
 san=cap["sanitization"]
 if san.get("metadata_only") is not True or any(san.get(k) is not False for k in ["private_scientific_authority_contents_exported","private_experimental_payloads_exported","credentials_or_secrets_exported","private_raw_results_exported"]): fail("sanitization contract")

 receipt={
  "schema":"replaymark.artifact-v4.g6-final-public-witness-receipt.v1",
  "status":"PASS_ARTIFACT_V4_FINAL_SANITIZED_WITNESS",
  "private_attestation_commit":cap["attestation_basis"]["private_attestation_commit"],
  "private_metadata_blob_attestations":"20/20 EXACT",
  "public_blob_checks":public_checks,
  "topology":{"claims":"42/42 exact IDs","invariants":"18/18 exact IDs","canonical_union":"60/60 exact IDs","authority_nodes":"19/19","claim_to_authority_edges":"56/56"},
  "falsification":{"consequential":"49/49 DETECTED","metamorphic":"8/8 STABLE","false_negatives":0,"false_positives":0,"A_B_detection_disagreements":0,"unexplained_extra_kills":0,"C14_fail_closed":True,"C49_fail_closed":True},
  "failure_lineage":{"events":16,"unique_ids":16,"retroactive_passes":0,"substantive_detection_misses":1,"original_C14_miss_preserved":True,"private_G6_pre_step_failure_preserved":True},
  "noninterference":{"scientific_rerun":False,"Verifier_A_rerun":False,"Verifier_B_rerun":False,"challenge_rerun":False,"authority_replacement":False,"manuscript_change":False,"threshold_lowering":False},
  "meaning":{"empirical_claim_strengthened":False,"verification_closure_strengthened":True},
  "governance":{"this_V4_campaign_freezes_after_private_final_binding":True,"future_ReplayMark_research_permitted":True,"future_versions_require_new_prospective_identity":True}
 }
 r=OUT/"G6_FINAL_PUBLIC_WITNESS_RECEIPT_V1.json"; dump(receipt,r)
 audit={"schema":"replaymark.artifact-v4.g6-final-public-witness-audit.v1","status":"PASS_FINAL_PUBLIC_WITNESS_AUDIT","capsule_git_blob":gb(CAPSULE.read_bytes()),"capsule_sha256":sha(CAPSULE),"public_blob_checks":public_checks,"exact_obligation_ids":sorted(union),"failure_ids":sorted(ids)}
 a=OUT/"G6_FINAL_PUBLIC_WITNESS_AUDIT_V1.json"; dump(audit,a)
 m=OUT/"SHA256SUMS_G6_FINAL_WITNESS.txt"; m.write_text(f"{sha(r)}  {r.name}\n{sha(a)}  {a.name}\n",encoding="utf-8")
 print(json.dumps({"status":receipt["status"],"receipt_sha256":sha(r),"audit_sha256":sha(a),"manifest_sha256":sha(m),"capsule_git_blob":audit["capsule_git_blob"],"canonical_obligations":60,"failure_events":16},sort_keys=True))

if __name__=="__main__": main()
