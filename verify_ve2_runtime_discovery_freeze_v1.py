from __future__ import annotations
import json, pathlib
R=pathlib.Path(__file__).resolve().parent
c=json.loads((R/'VE2_RUNTIME_DISCOVERY_CONSTITUTION_V1.json').read_text())
x=json.loads((R/'VE2_RUNTIME_DISCOVERY_CANDIDATES_V1.json').read_text())
assert c['status']=='FROZEN_PRE_RUNTIME_DISCOVERY_PRE_SCIENCE'
assert c['parent_private_receipt']=='c018e958c797ff5ae5339b5ce42d8ad3fdc9811b'
assert c['public_transition_semantic_pass']=='8fde248ed981e48eecc166f39d818551f1c6559b'
assert c['scientific_exposure']=={'ve2_home_assistant_scientific_cells':0,'ve2_replaymark_scientific_cells':0,'frontier_result_seen':False}
assert c['hard_rules']['first_PASS_candidate_is_selected'] is True
assert c['hard_rules']['candidate_order_may_change_after_probe'] is False
assert c['hard_rules']['transition_scientific_fixture_may_execute_during_discovery'] is False
assert x['roles']['T01_OLD_HISTORY']['ordered_tags'][0]=='2022.10.0'
assert x['roles']['T01_OLD_HISTORY']['ordered_tags'][-1]=='2021.12.0'
assert x['roles']['T01_NEW_TARGET']['ordered_tags']==['2026.1.0','2026.2.0','2025.12.0']
assert x['roles']['T02_COMMON']['ordered_tags']==['2026.9.0','2026.8.0','2026.7.2']
assert x['roles']['T02_COMMON']['preferred_common_digest']=='sha256:372d991e58882a1d8c68c07e9aa3f3b509276e695355f73ccdb03baa70407293'
assert x['selection_is_first_pass_in_order'] is True and x['scientific_cells']==0
print(json.dumps({'status':'PASS','roles':3,'science':0},sort_keys=True))
