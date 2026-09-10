from __future__ import annotations
import hashlib, importlib.util, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parent

def load(name): return json.loads((ROOT/name).read_text(encoding='utf-8'))
def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def sha(value): return hashlib.sha256(canonical(value)).hexdigest()

def import_semantics():
    p=ROOT/'ve2_transition_semantics_v1.py'
    spec=importlib.util.spec_from_file_location('ve2sem',p)
    mod=importlib.util.module_from_spec(spec); assert spec and spec.loader
    sys.modules['ve2sem']=mod; spec.loader.exec_module(mod); return mod

def main():
    m=import_semantics()
    meta=load('VE2_TRANSITION_META_CONSTITUTION_V1.json')
    t1n=load('VE2_T01_NATIVE_SEMANTICS_V1.json')
    t1e=load('VE2_T01_EXPECTED_FRONTIER_V1.json')
    t1x=load('VE2_T01_EXECUTION_STATE_MANIFEST_V1.json')
    t2n=load('VE2_T02_NATIVE_SEMANTICS_V1.json')
    t2e=load('VE2_T02_EXPECTED_FRONTIER_V1.json')
    t2x=load('VE2_T02_EXECUTION_STATE_MANIFEST_V1.json')
    rt=load('VE2_LABEL_FIREWALLED_RUNTIME_CONSTITUTION_V1.json')
    assert meta['parent_private_authority']['head']=='5faeccef2514885695b79a51c63a6284d99ceb89'
    assert meta['parent_private_authority']['public_census_pass_commit']=='4c4151a3675605218fed6a6847a7b22df96dc92b'
    assert meta['included_transitions']==['VE2-T01-NIGHT-ACTION-FAMILY','VE2-T02-WEEKLY-GUARD-REALIZATION']
    assert meta['uniform_claim_boundary']['endpoint']=='home-assistant.native-service-call'
    assert meta['result_hygiene']['current_ve2_home_assistant_scientific_cells']==0
    assert meta['result_hygiene']['current_ve2_replaymark_scientific_cells']==0

    assert t1e['rows']==m.t01_rows()
    assert t1e['counts']=={'states':2,'compatible':0,'retired':2}
    assert len(t1x['states'])==2
    assert [x['opaque_state_id'] for x in t1x['states']]==[x['execution_state_id'] for x in t1e['rows']]
    assert all(x['compatibility']=='RETIRED_BY_UPDATE' for x in t1e['rows'])
    assert t1n['expected_frontier_summary']=={'compatible':0,'retired':2,'reason':'At the frozen native-service-call boundary both old operations differ from the New Direct operations; ReplayMark cannot call a semantically substituted operation and still call it reuse.'}

    raw, quotient=m.t02_quotient()
    assert t2e['abstract_table']=={'row_count':144,'canonical_rows_sha256':sha(raw),'compatible':97,'retired':47}
    assert t2e['causal_path_quotient_table']['row_count']==42
    assert t2e['causal_path_quotient_table']['canonical_rows_sha256']==sha(quotient)
    assert t2e['causal_path_quotient_table']['execution_manifest_states_sha256']==sha(t2x['states'])
    assert t2e['causal_path_quotient_table']['compatible']==18 and t2e['causal_path_quotient_table']['retired']==24
    assert t2e['causal_path_quotient_table']['class_weights_sum']==144
    assert len(t2x['states'])==42
    assert [x['opaque_state_id'] for x in t2x['states']]==[x['execution_state_id'] for x in quotient]
    assert [x['fixture'] for x in t2x['states']]==[x['representative_fixture'] for x in quotient]
    assert sum(x['weight_in_144_state_superspace'] for x in quotient)==144
    assert t2n['finite_superspace']=={'reachable_state_count':144,'compatible_state_count':97,'retired_state_count':47}
    assert t2n['causal_path_preserving_quotient']['class_count']==42
    assert t2n['causal_path_preserving_quotient']['compatible_class_count']==18
    assert t2n['causal_path_preserving_quotient']['retired_class_count']==24

    forbidden=('compatibility','old_projected_action','new_projected_action','old_causal_path','new_causal_path','weight_in_144_state_superspace')
    for manifest in (t1x,t2x):
        rendered=json.dumps(manifest['states'],sort_keys=True)
        for token in forbidden: assert token not in rendered, (manifest['transition_id'], token)
    assert 'VE2_T01_EXPECTED_FRONTIER_V1.json' in rt['expectation_firewall']['producer_forbidden']
    assert 'VE2_T02_EXPECTED_FRONTIER_V1.json' in rt['expectation_firewall']['producer_forbidden']
    assert rt['scientific_exposure_at_freeze']=={'ve2_home_assistant_scientific_cells':0,'ve2_replaymark_scientific_cells':0,'frontier_result_seen':False}
    assert rt['promotion']['conjunctive_across_both_transitions'] is True

    print(json.dumps({
      'status':'PASS','scientific_cells':0,
      't01':{'states':2,'compatible':0,'retired':2,'rows_sha256':sha(t1e['rows'])},
      't02':{'abstract_states':144,'abstract_compatible':97,'abstract_retired':47,'classes':42,'class_compatible':18,'class_retired':24,'abstract_rows_sha256':sha(raw),'quotient_rows_sha256':sha(quotient),'execution_states_sha256':sha(t2x['states'])}
    },sort_keys=True))
if __name__=='__main__': main()
