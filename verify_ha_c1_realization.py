from __future__ import annotations
import copy, hashlib, json, sys
from pathlib import Path

from replaymark.runtime_ha_bt_observation import realize_ha_bt_observation
from replaymark.runtime_ha_bt_action import realize_ha_bt_historical_action
from replaymark.runtime_realization import RealizationError, RealizationFailureCode
from ha_c1_literal_oracle import observation_expected, action_expected

HERE=Path(__file__).resolve().parent
FIX=HERE/'fixtures'/'HA_C1_ARCHIVED_FIXTURES_V1.json'


def expect_failure(fn, raw, code):
    try:
        fn(raw)
    except RealizationError as exc:
        assert exc.failure.code is code, (exc.failure.code, code, exc)
        return
    raise AssertionError(f"expected fail-closed {code.value}")


def main():
    pack=json.loads(FIX.read_text())
    assert pack['schema']=='replaymark.ha-c1.archived-fixtures.v1'
    obs=pack['observations']; actions=pack['actions']
    assert len(obs)==144 and len(actions)==72
    obs_tokens={}
    for item in obs:
        raw=item['raw']; exp=observation_expected(raw); got=realize_ha_bt_observation(raw)
        assert got.evidence_token==exp['evidence_token']
        assert got.clock_domain==exp['clock_domain']
        assert got.boundary_timestamp_ns==exp['boundary_timestamp_ns']
        assert got.source_event_timestamp_ns is None
        obs_tokens[got.evidence_token]=obs_tokens.get(got.evidence_token,0)+1
    presets={}
    for item in actions:
        raw=item['raw']; exp=action_expected(raw); got=realize_ha_bt_historical_action(raw)
        assert got.action.as_dict()==exp, (got.action.as_dict(),exp)
        presets[exp['preset_mode']]=presets.get(exp['preset_mode'],0)+1

    o=copy.deepcopy(obs[0]['raw'])
    bad=copy.deepcopy(o); bad['entities']['climate']='climate.foreign'; expect_failure(realize_ha_bt_observation,bad,RealizationFailureCode.OUT_OF_BOUNDARY)
    bad=copy.deepcopy(o); del bad['snapshot']['climate_preset']; expect_failure(realize_ha_bt_observation,bad,RealizationFailureCode.MISSING_REQUIRED_FIELD)
    bad=copy.deepcopy(o); bad['snapshot']['motion']='unknown'; expect_failure(realize_ha_bt_observation,bad,RealizationFailureCode.UNKNOWN_SEMANTIC_VALUE)
    bad=copy.deepcopy(o); bad['snapshot']['temperature']=21; expect_failure(realize_ha_bt_observation,bad,RealizationFailureCode.MALFORMED_INPUT)

    a=copy.deepcopy(actions[0]['raw'])
    bad=copy.deepcopy(a); bad['service_event']['service_data']['entity_id']=['climate.foreign']; expect_failure(realize_ha_bt_historical_action,bad,RealizationFailureCode.OUT_OF_BOUNDARY)
    bad=copy.deepcopy(a); bad['service_event']['context_parent_id']='01FOREIGNCONTEXT'; expect_failure(realize_ha_bt_historical_action,bad,RealizationFailureCode.OUT_OF_BOUNDARY)
    bad=copy.deepcopy(a); bad['service_event']['service_data']['entity_id']=['climate.agentmark_thermostat','climate.agentmark_thermostat']; expect_failure(realize_ha_bt_historical_action,bad,RealizationFailureCode.DUPLICATE_INPUT)
    bad=copy.deepcopy(a); del bad['service_event']['service_data']['preset_mode']; expect_failure(realize_ha_bt_historical_action,bad,RealizationFailureCode.MISSING_REQUIRED_FIELD)
    bad=copy.deepcopy(a); bad['service_event']['service_data']['temperature']=21; expect_failure(realize_ha_bt_historical_action,bad,RealizationFailureCode.MALFORMED_INPUT)
    bad=copy.deepcopy(a); bad['service_event']['service']='set_temperature'; expect_failure(realize_ha_bt_historical_action,bad,RealizationFailureCode.UNKNOWN_SEMANTIC_VALUE)

    result={
      'schema':'replaymark.ha-c1.realization-qualification-result.v1',
      'decision':'PASS',
      'fixture_sha256':hashlib.sha256(FIX.read_bytes()).hexdigest(),
      'observation_count':len(obs),
      'observation_unique_tokens':len(obs_tokens),
      'action_count':len(actions),
      'action_presets':presets,
      'negative_cases':10,
      'oracle_independent_imports':True,
    }
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__=='__main__': main()
