from __future__ import annotations
import json, pathlib
ROOT=pathlib.Path(__file__).resolve().parent
C=ROOT/'VE2_VERSION_EVOLUTION_CENSUS_CONSTITUTION_V2.json'
M=ROOT/'VE2_UPSTREAM_CORPUS_MANIFEST_V2.json'
I=ROOT/'VE2_CENSUS_V1_INVALIDATION_AND_RECOVERY_V1.json'

def load(p): return json.loads(p.read_text())
def main():
    c,m,i=map(load,(C,M,I))
    assert c['schema']=='replaymark.ve2.version-evolution-census-constitution.v2'
    assert m['schema']=='replaymark.ve2.upstream-corpus-manifest.v2'
    assert i['schema']=='replaymark.ve2.census-v1-invalidation-and-recovery.v1'
    assert c['upstream_snapshot']==m['upstream_snapshot']=='d24bcf2da30b8dbaaf99c0a14ec91f3c3b58e942'
    assert c['recovery_authority']['public_result_seal_commit']==m['raw_recovery']['public_result_seal_commit']==i['recovery']['result_seal_commit']=='d9914c6814a79244733a72024a2bc006cc592ec9'
    assert m['file_count']==7 and m['file_version_count']==16 and m['adjacent_pair_count']==9
    assert c['classification_lock']['expected_pairs']==9
    assert m['included_count']==2 and m['excluded_count']==7
    assert c['classification_lock']['expected_included']==2 and c['classification_lock']['expected_excluded']==7
    pairs=m['pair_records']
    assert len(pairs)==9
    keys={(x['path'],x['old_commit'],x['new_commit']) for x in pairs}
    assert len(keys)==9
    hist=m['complete_file_touch_histories']
    rebuilt=set(); nvers=0
    for filename,versions in hist.items():
        nvers += len(versions)
        for a,b in zip(versions,versions[1:]):
            rebuilt.add((filename if filename.startswith('blueprints/') else f'blueprints/{filename}',a['commit'],b['commit']))
    assert nvers==16 and rebuilt==keys
    included=[x['pair_id'] for x in pairs if x['classification']=='INCLUDED']
    excluded=[x['pair_id'] for x in pairs if x['classification']=='EXCLUDED']
    assert included==m['included_transition_ids']==['VE2-T01-NIGHT-ACTION-FAMILY','VE2-T02-WEEKLY-GUARD-REALIZATION']
    assert excluded==m['excluded_pair_ids'] and len(excluded)==7
    for x in pairs:
        for k in ('old_blob','new_blob'):
            assert len(x[k])==40 and all(ch in '0123456789abcdef' for ch in x[k])
        for k in ('patch_sha256','old_source_sha256','new_source_sha256','old_psych_ast_sha256','new_psych_ast_sha256','old_thermostat_action_projection_sha256','new_thermostat_action_projection_sha256'):
            assert len(x[k])==64 and all(ch in '0123456789abcdef' for ch in x[k])
        assert x['thermostat_projection_equal'] is (x['classification']=='EXCLUDED')
    assert c['scientific_hygiene']=={'frontier_prediction_opened':False,'no_runtime_design_until_public_census_pass':True,'ve2_home_assistant_scientific_cells':0,'ve2_replaymark_scientific_cells':0,'ve2_scientific_result_opened':False}
    assert m['scientific_result_opened'] is False and m['ve2_home_assistant_scientific_cells']==0 and m['ve2_replaymark_scientific_cells']==0 and m['frontier_prediction_opened'] is False
    assert i['result_exposure_at_invalidation']=={'frontier_prediction_opened':False,'ve2_home_assistant_scientific_cells':0,'ve2_replaymark_scientific_cells':0}
    assert i['preserved_failed_public_runs'][0]['run_id']==34483538569
    assert i['preserved_failed_public_runs'][1]['run_id']==34483837087
    assert i['recovery']['artifact_zip_sha256']=='cd46b110e8bcca395b90c7a004995eb668bc532b3d1af5bf71c8cd8efd863013'
    print(json.dumps({'status':'PASS','pairs':9,'included':included,'excluded_count':7,'scientific_cells':0},sort_keys=True))
if __name__=='__main__': main()
