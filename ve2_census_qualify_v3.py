from __future__ import annotations
import argparse, hashlib, json, pathlib, subprocess, tempfile, traceback
from typing import Any

SNAPSHOT='d24bcf2da30b8dbaaf99c0a14ec91f3c3b58e942'
UPSTREAM='https://github.com/KartoffelToby/better_thermostat.git'
MANIFEST=pathlib.Path('VE2_UPSTREAM_CORPUS_MANIFEST_V2.json')
CONSTITUTION=pathlib.Path('VE2_VERSION_EVOLUTION_CENSUS_CONSTITUTION_V2.json')
INVALIDATION=pathlib.Path('VE2_CENSUS_V1_INVALIDATION_AND_RECOVERY_V1.json')
AUTHORITY=pathlib.Path('VE2_PRE_RESULT_CENSUS_AUTHORITY_V2.json')
EXPECTED_FILES=['blueprints/battery_low_notify.yaml','blueprints/device_error_notify.yaml','blueprints/heating_active_notify.yaml','blueprints/humidity_high_alert.yaml','blueprints/night_mode.yaml','blueprints/presence_away_preset.yaml','blueprints/weekly_heating_schedule.yaml']
EXPECTED_INCLUDED=['VE2-T01-NIGHT-ACTION-FAMILY','VE2-T02-WEEKLY-GUARD-REALIZATION']
RUBY_AST=r'''require 'psych'; require 'json'; require 'digest'; def norm(n); h={'class'=>n.class.name}; [:value,:tag,:anchor,:style,:implicit,:quoted].each{|m| h[m.to_s]=n.send(m) if n.respond_to?(m)}; h['children']=n.children.map{|c| norm(c)} if n.respond_to?(:children) && n.children; h; end; print Digest::SHA256.hexdigest(JSON.generate(norm(Psych.parse_file(ARGV[0]))))'''
RUBY_OBJ=r'''require 'psych'; require 'json'; print JSON.generate(Psych.unsafe_load_file(ARGV[0]))'''

def sh(*args:str,cwd:pathlib.Path|None=None,raw=False):
    return subprocess.check_output(args,cwd=cwd,stderr=subprocess.STDOUT) if raw else subprocess.check_output(args,cwd=cwd,text=True,stderr=subprocess.STDOUT).strip()
def sha256_bytes(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def canon_hash(o:Any)->str:return hashlib.sha256(json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def file_versions(repo:pathlib.Path,path:str):
    commits=sh('git','log','--format=%H','--reverse',SNAPSHOT,'--',path,cwd=repo).splitlines(); out=[]
    for c in commits:
        try:b=sh('git','rev-parse',f'{c}:{path}',cwd=repo)
        except subprocess.CalledProcessError:continue
        if not out or out[-1]['blob']!=b:out.append({'commit':c,'blob':b})
    return out
def source_bytes(repo:pathlib.Path,c:str,p:str)->bytes:return sh('git','show',f'{c}:{p}',cwd=repo,raw=True)
def diff_bytes(repo:pathlib.Path,a:str,b:str,p:str)->bytes:return sh('git','diff','--no-ext-diff','--unified=20',a,b,'--',p,cwd=repo,raw=True)
def ruby_eval(raw:bytes,script:str)->str:
    with tempfile.NamedTemporaryFile(suffix='.yaml') as f:
        f.write(raw);f.flush();return subprocess.check_output(['ruby','-e',script,f.name],text=True)
def yaml_obj(raw:bytes)->Any:return json.loads(ruby_eval(raw,RUBY_OBJ))
def psych_fp(raw:bytes)->str:return ruby_eval(raw,RUBY_AST)
def is_tsvc(s:Any)->bool:return isinstance(s,str) and (s.startswith('climate.') or s.startswith('better_thermostat.'))
def projection(x:Any)->Any:
    if isinstance(x,list):
        ys=[projection(v) for v in x];return [v for v in ys if v not in (None,{},[])]
    if not isinstance(x,dict):return x
    if 'service' in x:return {k:x[k] for k in ('service','data','target') if k in x} if is_tsvc(x['service']) else None
    if 'if' in x and 'then' in x:
        t=projection(x['then']);e=projection(x.get('else',[]))
        if not t and not e:return None
        r={'if':x['if'],'then':t}
        if 'else' in x:r['else']=e
        return r
    if 'choose' in x:
        choices=[]
        for c in x.get('choose') or []:
            seq=projection(c.get('sequence',[]))
            if seq:choices.append({'conditions':c.get('conditions',[]),'sequence':seq})
        d=projection(x.get('default',[]))
        if not choices and not d:return None
        r={'choose':choices}
        if 'default' in x:r['default']=d
        return r
    r={}
    for k,v in x.items():
        pv=projection(v)
        if pv not in (None,{},[]):r[k]=pv
    return r or None
def services(x:Any)->list[str]:
    out=[]
    if isinstance(x,dict):
        if isinstance(x.get('service'),str):out.append(x['service'])
        for v in x.values():out.extend(services(v))
    elif isinstance(x,list):
        for v in x:out.extend(services(v))
    return out
def norm_singleton_entity_ids(x:Any)->Any:
    if isinstance(x,list):return [norm_singleton_entity_ids(v) for v in x]
    if isinstance(x,dict):
        r={k:norm_singleton_entity_ids(v) for k,v in x.items()}
        if isinstance(r.get('entity_id'),list) and len(r['entity_id'])==1:r['entity_id']=r['entity_id'][0]
        return r
    return x

def independent_classify(pair,old_raw,new_raw,old_obj,new_obj,old_proj,new_proj,old_ast,new_ast):
    key=(pair['path'],pair['old_commit'],pair['new_commit']);old_text=old_raw.decode();new_text=new_raw.decode();old_sv=services(old_obj.get('action'));new_sv=services(new_obj.get('action'))
    if key==('blueprints/battery_low_notify.yaml','d496da5f283db323673d97efc27d6193791c17ac','544d429ecc9da1e1780ddf0a043acecc3334207d'):
        assert not any(is_tsvc(s) for s in old_sv+new_sv);assert old_ast==new_ast;return 'EXCLUDED','VE2-X01-BATTERY-WHITESPACE'
    if key==('blueprints/humidity_high_alert.yaml','d496da5f283db323673d97efc27d6193791c17ac','ac189909982c5edea1260e767027d6fad90ef4bd'):
        assert not any(is_tsvc(s) for s in old_sv+new_sv);assert 'switch.turn_on' in old_sv and 'switch.turn_on' in new_sv;return 'EXCLUDED','VE2-X02-HUMIDITY-NONTHERMOSTAT'
    if key==('blueprints/night_mode.yaml','3785543e30e7af52a742e9ba129527147c813480','c6d9f4cd15dd381f803b96ac3d184d2ff41db4fb'):
        assert old_obj['action']==new_obj['action'] and old_obj['trigger']==new_obj['trigger'];assert old_text.replace('/tree/master/blueprints/night_mode.yaml','/blob/master/blueprints/night_mode.yaml')==new_text;return 'EXCLUDED','VE2-X03-NIGHT-SOURCE-URL'
    if key==('blueprints/night_mode.yaml','c6d9f4cd15dd381f803b96ac3d184d2ff41db4fb','cd4c3121c92f59d5ac1f3533424bc570209ce6ef'):
        assert old_obj['action']==new_obj['action'];assert norm_singleton_entity_ids(old_obj['trigger'])==norm_singleton_entity_ids(new_obj['trigger']);assert old_proj==new_proj;return 'EXCLUDED','VE2-X04-NIGHT-SELECTOR'
    if key==('blueprints/night_mode.yaml','cd4c3121c92f59d5ac1f3533424bc570209ce6ef','96ae2f87b3b1a1b095dbf1f74f37f63fbc34c32f'):
        assert old_obj['action'][0]['if']==new_obj['action'][0]['if'];assert old_sv==['better_thermostat.set_temp_target_temperature','better_thermostat.restore_saved_target_temperature'];assert new_sv==['climate.set_preset_mode','climate.set_preset_mode'];assert 'preset_mode: sleep' in new_text and 'preset_mode: none' in new_text;assert old_proj!=new_proj;return 'INCLUDED','VE2-T01-NIGHT-ACTION-FAMILY'
    if key==('blueprints/presence_away_preset.yaml','d496da5f283db323673d97efc27d6193791c17ac','ac189909982c5edea1260e767027d6fad90ef4bd'):
        assert old_proj==new_proj;assert old_sv.count('climate.set_preset_mode')==new_sv.count('climate.set_preset_mode')==2;assert 'enable_notify' not in old_text and 'enable_notify' in new_text;return 'EXCLUDED','VE2-X05-PRESENCE-NOTIFICATION'
    if key==('blueprints/weekly_heating_schedule.yaml','d496da5f283db323673d97efc27d6193791c17ac','ac189909982c5edea1260e767027d6fad90ef4bd'):
        assert old_proj==new_proj;assert 'enable_notify' not in old_text and 'enable_notify' in new_text;assert 'binary_sensor.bt_presence_placeholder' in new_text and 'input_boolean.bt_schedule_pause_placeholder' in new_text;return 'EXCLUDED','VE2-X06-WEEKLY-NONTHERMOSTAT'
    if key==('blueprints/weekly_heating_schedule.yaml','ac189909982c5edea1260e767027d6fad90ef4bd','5b4496de5659fd2c6ec5c67a9797e6659797866c'):
        assert old_proj!=new_proj;assert "{% if active_slot == '1' %}" in old_text and '{% if active_slot | int == 1 %}' in new_text;assert '%}true' in old_text and '{{ true }}' in new_text;assert '%}false' in old_text and '{{ false }}' in new_text;assert 'presence_entity_selection: !input presence_entity' in new_text and 'namespace(home=false)' in new_text;assert 'pause_switch_selection: !input pause_switch' in new_text and 'namespace(paused=false)' in new_text;assert 'value_template: "{{ not schedule_paused }}"' in new_text;return 'INCLUDED','VE2-T02-WEEKLY-GUARD-REALIZATION'
    if key==('blueprints/weekly_heating_schedule.yaml','5b4496de5659fd2c6ec5c67a9797e6659797866c','544d429ecc9da1e1780ddf0a043acecc3334207d'):
        assert old_ast==new_ast;assert old_obj==new_obj;assert old_proj==new_proj;return 'EXCLUDED','VE2-X07-WEEKLY-REINDENT'
    raise AssertionError(('UNCLASSIFIED_PAIR',key))

def verify(work):
    manifest=json.loads(MANIFEST.read_text());constitution=json.loads(CONSTITUTION.read_text());authority=json.loads(AUTHORITY.read_text())
    assert constitution['classification_lock']=={'expected_excluded':7,'expected_included':2,'expected_pairs':9,'included_ids':EXPECTED_INCLUDED};assert authority['source_freeze_commit']=='97be3f7dbd33dccb60981760c705dac4ffbda69f'
    repo=work/'better_thermostat';subprocess.check_call(['git','clone','--quiet','--no-tags',UPSTREAM,str(repo)]);sh('git','cat-file','-e',f'{SNAPSHOT}^{{commit}}',cwd=repo)
    paths=sorted(x for x in sh('git','ls-tree','-r','--name-only',SNAPSHOT,'--','blueprints',cwd=repo).splitlines() if x.startswith('blueprints/') and '/' not in x[len('blueprints/'):]);assert paths==EXPECTED_FILES
    histories={p:file_versions(repo,p) for p in paths};assert histories==manifest['complete_file_touch_histories'];assert sum(map(len,histories.values()))==16
    decisions=[];actual_pairs=[];frozen={(x['path'],x['old_commit'],x['new_commit']):x for x in manifest['pair_records']}
    for p,hist in histories.items():
        for a,b in zip(hist,hist[1:]):
            key=(p,a['commit'],b['commit']);assert key in frozen;fr=frozen[key];old_raw=source_bytes(repo,a['commit'],p);new_raw=source_bytes(repo,b['commit'],p);patch=diff_bytes(repo,a['commit'],b['commit'],p)
            assert a['blob']==fr['old_blob'] and b['blob']==fr['new_blob'];assert sha256_bytes(old_raw)==fr['old_source_sha256'];assert sha256_bytes(new_raw)==fr['new_source_sha256'];assert sha256_bytes(patch)==fr['patch_sha256']
            old_ast=psych_fp(old_raw);new_ast=psych_fp(new_raw);assert old_ast==fr['old_psych_ast_sha256'];assert new_ast==fr['new_psych_ast_sha256'];old_obj=yaml_obj(old_raw);new_obj=yaml_obj(new_raw);old_proj=projection(old_obj.get('action'));new_proj=projection(new_obj.get('action'));oph,nph=canon_hash(old_proj),canon_hash(new_proj)
            assert oph==fr['old_thermostat_action_projection_sha256'] and nph==fr['new_thermostat_action_projection_sha256'];assert (old_proj==new_proj)==fr['thermostat_projection_equal'];cls,pid=independent_classify(fr,old_raw,new_raw,old_obj,new_obj,old_proj,new_proj,old_ast,new_ast);assert cls==fr['classification'] and pid==fr['pair_id']
            decisions.append({'pair_id':pid,'classification':cls,'path':p,'old_commit':a['commit'],'new_commit':b['commit'],'old_blob':a['blob'],'new_blob':b['blob'],'old_source_sha256':sha256_bytes(old_raw),'new_source_sha256':sha256_bytes(new_raw),'patch_sha256':sha256_bytes(patch),'old_psych_ast_sha256':old_ast,'new_psych_ast_sha256':new_ast,'old_projection_sha256':oph,'new_projection_sha256':nph,'projection_equal':old_proj==new_proj});actual_pairs.append(key)
    assert len(actual_pairs)==9 and len(set(actual_pairs))==9 and set(actual_pairs)==set(frozen);included=[d['pair_id'] for d in decisions if d['classification']=='INCLUDED'];excluded=[d['pair_id'] for d in decisions if d['classification']=='EXCLUDED'];assert included==EXPECTED_INCLUDED and len(excluded)==7
    return {'schema':'replaymark.ve2.public-corrected-census-qualification.v3','status':'PASS','upstream_snapshot':SNAPSHOT,'file_count':7,'file_version_count':16,'adjacent_pair_count':9,'included_count':2,'excluded_count':7,'included_ids':included,'decisions':decisions,'ruby_version':sh('ruby','-v'),'psych_version':sh('ruby','-rpsych','-e','print Psych::VERSION'),'scientific_result_opened':False,'frontier_prediction_opened':False,'ve2_home_assistant_scientific_cells':0,'ve2_replaymark_scientific_cells':0,'corpus_membership_changed_during_run':False}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--work',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();work=pathlib.Path(a.work);out=pathlib.Path(a.out);work.mkdir(parents=True,exist_ok=True);out.parent.mkdir(parents=True,exist_ok=True)
    try:v=verify(work)
    except Exception as e:v={'schema':'replaymark.ve2.public-corrected-census-qualification.v3','status':'FAIL','error_type':type(e).__name__,'error':repr(e),'traceback':traceback.format_exc(),'scientific_result_opened':False,'frontier_prediction_opened':False,'ve2_home_assistant_scientific_cells':0,'ve2_replaymark_scientific_cells':0}
    out.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
    if v['status']!='PASS':raise SystemExit(1)
if __name__=='__main__':main()
