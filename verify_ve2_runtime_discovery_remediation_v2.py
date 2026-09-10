from __future__ import annotations
import ast, json, pathlib
R=pathlib.Path(__file__).resolve().parent
rem=json.loads((R/'VE2_RUNTIME_DISCOVERY_REMEDIATION_CONTRACT_V2_MIRROR.json').read_text())
fail=json.loads((R/'VE2_RUNTIME_DISCOVERY_V1_FAILURE_RECEIPT_MIRROR.json').read_text())
pub=json.loads((R/'VE2_RUNTIME_DISCOVERY_PUBLIC_CONTRACT_V2.json').read_text())
cand=json.loads((R/'VE2_RUNTIME_DISCOVERY_CANDIDATES_V1.json').read_text())
code=(R/'ve2_runtime_discovery_public_v2.py').read_text()
ast.parse(code)
assert rem['status']=='FROZEN_PROSPECTIVE_PRE_V2_EXECUTION'
assert rem['failed_public_run']['run_id']==34506501065
assert fail['public_execution']['run_id']==34506501065
assert fail['rerun_of_v1_authority_authorized'] is False
assert pub['candidate_lattice_unchanged'] is True and pub['inside_probe_unchanged'] is True
assert pub['science_open_authorized'] is False and pub['v1_rerun_authorized'] is False
assert cand['roles']['T01_OLD_HISTORY']['ordered_tags']==['2022.10.0','2022.9.0','2022.8.0','2022.7.0','2022.6.0','2022.5.0','2022.4.0','2022.3.0','2022.2.0','2022.1.0','2021.12.0']
assert cand['roles']['T01_NEW_TARGET']['ordered_tags']==['2026.1.0','2026.2.0','2025.12.0']
assert cand['roles']['T02_COMMON']['ordered_tags']==['2026.9.0','2026.8.0','2026.7.2']
for required in ('resolve(strict=True)','transport_preflight','probe_result_present','DISCOVERY_INFRASTRUCTURE_FAILURE','host_bind_paths_absolute'):
    assert required in code, required
for forbidden in ('VE2_T01_EXPECTED_FRONTIER','VE2_T02_EXPECTED_FRONTIER','6d4b4ac7738885bcf','6292de3f4889bb69','c4c3d495df1659aa','f791b6b93ee3febe','ve2_transition_semantics_v1','verify_ve2_transition_freeze_v1'):
    assert forbidden not in code, forbidden
print(json.dumps({'status':'PASS','science':0,'candidate_lattice_unchanged':True,'v1_preserved':True},sort_keys=True))
