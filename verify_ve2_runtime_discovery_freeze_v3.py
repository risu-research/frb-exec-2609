import ast
import json
import pathlib

candidates=json.loads(pathlib.Path('VE2_RUNTIME_DISCOVERY_CANDIDATES_V1.json').read_text())
authority=json.loads(pathlib.Path('VE2_RUNTIME_DISCOVERY_PRE_RESULT_AUTHORITY_V3.json').read_text())
remediation=json.loads(pathlib.Path('VE2_RUNTIME_DISCOVERY_REMEDIATION_CONTRACT_V3.json').read_text())
failed=json.loads(pathlib.Path('VE2_RUNTIME_DISCOVERY_V2_FAILURE_RECEIPT.json').read_text())
coordinator=pathlib.Path('ve2_runtime_discovery_public_v3.py').read_text()
inside=pathlib.Path('ve2_runtime_inside_probe_v3.py').read_text()
ast.parse(coordinator); ast.parse(inside)

assert candidates['selection_is_first_pass_in_order'] is True
assert candidates['roles']['T01_OLD_HISTORY']['ordered_tags']==['2022.10.0','2022.9.0','2022.8.0','2022.7.0','2022.6.0','2022.5.0','2022.4.0','2022.3.0','2022.2.0','2022.1.0','2021.12.0']
assert candidates['roles']['T01_NEW_TARGET']['ordered_tags']==['2026.1.0','2026.2.0','2025.12.0']
assert candidates['roles']['T02_COMMON']['ordered_tags']==['2026.9.0','2026.8.0','2026.7.2']
assert authority['science_open_authorized'] is False
assert authority['v3_rules']['rerun_all_roles_from_first_candidate'] is True
assert remediation['science_open_authorized'] is False
assert failed['partial_selection_promotable'] is False
assert 'custom_components.better_thermostat.const' not in inside
assert 'custom_components.better_thermostat.climate' in inside
assert 'standalone_const_module_present' in inside
assert 'syntax_check_tree(comp)' in inside
assert 'requirement-not-importable:' in inside
assert coordinator.count('.resolve(')>=8
assert 'type=bind,src=' in coordinator
assert 'TRANSPORT_PREFLIGHT_FAILURE' in coordinator
assert 'DISCOVERY_INFRASTRUCTURE_FAILURE' in coordinator
assert 'SOURCE_RUNTIME_INCOMPATIBLE' in coordinator
assert 'rerun_all_roles_from_first_candidate' in coordinator
for forbidden in ('VE2_T01_EXPECTED_FRONTIER','VE2_T02_EXPECTED_FRONTIER','6d4b4ac7738885bcf','6292de3f4889bb69','c4c3d495df1659aa','f791b6b93ee3febe','ve2_transition_semantics_v1'):
    assert forbidden not in coordinator+inside
print(json.dumps({'status':'PASS','probe_revision':'v3','candidate_roles':3,'science':0},sort_keys=True))
