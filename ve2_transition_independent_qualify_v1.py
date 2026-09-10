import argparse,hashlib,json,pathlib,subprocess,sys
from collections import defaultdict
U="https://github.com/KartoffelToby/better_thermostat.git"; P={1:"comfort",2:"eco",3:"home",4:"sleep"}
T1=("cd4c3121c92f59d5ac1f3533424bc570209ce6ef","96ae2f87b3b1a1b095dbf1f74f37f63fbc34c32f","blueprints/night_mode.yaml","8788f64ee1f6dfd25cdaaa42183b2ee94591e1f0","19c99196ed611729338f01bc77ea1b5deda7aa02","9a2b545288a3cae15f497796cb9001e6a142fc02c6150df6b11975d79f6083d8","9c2a4b03d57a59d6b13a34b0bf4031104c19abafa8331e1b329861f45eeef363","ddf6a1316693bf521969669f74e77e1f7dc71508ea856b45aedecbf9426c1ffd","climate.ve2_t01_thermostat")
T2=("ac189909982c5edea1260e767027d6fad90ef4bd","5b4496de5659fd2c6ec5c67a9797e6659797866c","blueprints/weekly_heating_schedule.yaml","2172a1a3ad1955132911aa0fd0f8a546ab6e2b76","3255957740ec44285d866d8be7d78bf905c1257c","5593911e8ef5db3cc29f1ab4bb6658538f6e68fecbd010de0527ecc41b5d4115","45375bb3a0a09b5ae7db9bdc038a73fcbec80425ec38e858e89633cb1dfdf37e","1559c4938ccd883ca1e8b2f2b08ac71c1bb8615a35776adc89f76de4c9254648","climate.ve2_t02_thermostat")
F=("6d4b4ac7738885bcf1226161d84726926b15d3139502dd5e31499a4850328f2a","6292de3f4889bb69491faf40cdc3c421576ea750e4d70cb032a6b0bbc81c60ae","c4c3d495df1659aaf94fb1d517b9fdd483759344c429e58aa51a45d415b74c25","f791b6b93ee3febe483c9f85aa977db04c3e431479bf4404f5c9d7d6194fed94")
def C(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def H(x):return hashlib.sha256(x if isinstance(x,bytes) else C(x).encode()).hexdigest()
def S(*a,cwd=None,b=False):return subprocess.check_output(a,cwd=cwd,stderr=subprocess.STDOUT) if b else subprocess.check_output(a,cwd=cwd,text=True,stderr=subprocess.STDOUT).strip()
def A(t,o,d=None):return {"operation":o,"concrete_target":t,"variant":"NO_ACTION" if o=="NO_ACTION" else C({} if d is None else d)}
def pair(r,t,out,n):
 o,nw=S("git","show",f"{t[0]}:{t[2]}",cwd=r,b=True),S("git","show",f"{t[1]}:{t[2]}",cwd=r,b=True);d=S("git","diff","--no-ext-diff","--unified=20",t[0],t[1],"--",t[2],cwd=r,b=True)
 assert S("git","rev-parse",f"{t[0]}:{t[2]}",cwd=r)==t[3] and S("git","rev-parse",f"{t[1]}:{t[2]}",cwd=r)==t[4] and (H(o),H(nw),H(d))==t[5:8]
 (out/f"{n}_OLD.yaml").write_bytes(o);(out/f"{n}_NEW.yaml").write_bytes(nw);(out/f"{n}_PATCH.diff").write_bytes(d);return o.decode(),nw.decode()
def old(f):
 tr,a,ep,ph,epa,po=[f[k] for k in ("trigger_kind","active_slot","enable_presence_mode","presence_home","enable_pause_switch","pause_on")];ah="true" if not ep else ph;sp="false" if not epa else po;t=T2[8]
 if tr.startswith("slot"):
  n=int(tr[-1]);return (A(t,"NO_ACTION"),"slot:blocked_by_schedule_paused_truthiness") if bool(sp) else ((A(t,"climate.set_preset_mode",{"preset_mode":"away"}),"slot:vacation") if ep and not bool(ah) else (A(t,"climate.set_preset_mode",{"preset_mode":P[n]}),"slot:normal"))
 if tr=="startup":
  return (A(t,"NO_ACTION"),"startup:blocked_by_schedule_paused_truthiness") if bool(sp) else ((A(t,"climate.set_preset_mode",{"preset_mode":"away"}),"startup:vacation") if ep and not bool(ah) else (A(t,"climate.set_preset_mode",{"preset_mode":P[4]}),"startup:normal:old_active_slot_string_mismatch"))
 if tr=="pause_off":
  return (A(t,"NO_ACTION"),"pause_off:feature_disabled") if not epa else ((A(t,"climate.set_preset_mode",{"preset_mode":"away"}),"pause_off:vacation") if ep and not bool(ah) else (A(t,"climate.set_preset_mode",{"preset_mode":P[4]}),"pause_off:normal:old_active_slot_string_mismatch"))
 if tr=="arrived_home":
  return (A(t,"NO_ACTION"),"arrived_home:feature_disabled") if not ep else ((A(t,"NO_ACTION"),"arrived_home:blocked_by_schedule_paused_truthiness") if bool(sp) else (A(t,"climate.set_preset_mode",{"preset_mode":P[4]}),"arrived_home:normal:old_active_slot_string_mismatch"))
 return (A(t,"NO_ACTION"),"left_home:feature_disabled") if not ep else ((A(t,"NO_ACTION"),"left_home:blocked_by_schedule_paused_truthiness") if bool(sp) else ((A(t,"NO_ACTION"),"left_home:presence_still_home") if ph else (A(t,"climate.set_preset_mode",{"preset_mode":"away"}),"left_home:vacation")))
def new(f):
 tr,a,ep,ph,epa,po=[f[k] for k in ("trigger_kind","active_slot","enable_presence_mode","presence_home","enable_pause_switch","pause_on")];ah=True if not ep else ph;sp=False if not epa else po;t=T2[8]
 if tr.startswith("slot"):
  n=int(tr[-1]);return (A(t,"NO_ACTION"),"slot:blocked_by_schedule_paused") if sp else ((A(t,"climate.set_preset_mode",{"preset_mode":"away"}),"slot:vacation") if ep and not ah else (A(t,"climate.set_preset_mode",{"preset_mode":P[n]}),"slot:normal"))
 if tr=="startup":
  return (A(t,"NO_ACTION"),"startup:blocked_by_schedule_paused") if sp else ((A(t,"climate.set_preset_mode",{"preset_mode":"away"}),"startup:vacation") if ep and not ah else (A(t,"climate.set_preset_mode",{"preset_mode":P[a]}),"startup:normal"))
 if tr=="pause_off":
  return (A(t,"NO_ACTION"),"pause_off:feature_disabled") if not epa else ((A(t,"NO_ACTION"),"pause_off:still_paused") if sp else ((A(t,"climate.set_preset_mode",{"preset_mode":"away"}),"pause_off:vacation") if ep and not ah else (A(t,"climate.set_preset_mode",{"preset_mode":P[a]}),"pause_off:normal")))
 if tr=="arrived_home":
  return (A(t,"NO_ACTION"),"arrived_home:feature_disabled") if not ep else ((A(t,"NO_ACTION"),"arrived_home:blocked_by_schedule_paused") if sp else (A(t,"climate.set_preset_mode",{"preset_mode":P[a]}),"arrived_home:normal"))
 return (A(t,"NO_ACTION"),"left_home:feature_disabled") if not ep else ((A(t,"NO_ACTION"),"left_home:blocked_by_schedule_paused") if sp else ((A(t,"NO_ACTION"),"left_home:presence_still_home") if ah else (A(t,"climate.set_preset_mode",{"preset_mode":"away"}),"left_home:vacation")))
def derive():
 R=[]
 for tr in ("slot1","slot2","slot3","slot4","startup","pause_off","arrived_home","left_home"):
  for a in ((int(tr[-1]),) if tr.startswith("slot") else (1,2,3,4)):
   for ep in (False,True):
    for ph in ((True,) if tr=="arrived_home" else ((False,) if tr=="left_home" else ((False,True) if ep else (False,)))):
     for epa in (False,True):
      for po in ((False,) if tr=="pause_off" else ((False,True) if epa else (False,))):
       f=dict(trigger_kind=tr,active_slot=a,enable_presence_mode=ep,presence_home=ph,enable_pause_switch=epa,pause_on=po);oa,op=old(f);na,np=new(f);R.append(dict(fixture=f,old_projected_action=oa,new_projected_action=na,old_causal_path=op,new_causal_path=np,compatibility="COMPATIBLE_ACROSS_VERSION" if oa==na else "RETIRED_BY_UPDATE"))
 R.sort(key=lambda r:C(r["fixture"]))
 for i,r in enumerate(R):r["abstract_state_id"]=f"VE2-T02-A{i:03d}"
 G=defaultdict(list)
 for r in R:G[C({k:r[k] for k in ("old_projected_action","new_projected_action","old_causal_path","new_causal_path")})].append(r)
 for m in G.values():m.sort(key=lambda r:C(r["fixture"]))
 Z=sorted([(m[0],m) for m in G.values()],key=lambda x:C(x[0]["fixture"]));Q=[];M={}
 for i,(r,m) in enumerate(Z):
  sid=f"VE2-T02-S{i:02d}"
  for x in m:M[C(x["fixture"])]=sid
  Q.append(dict(execution_state_id=sid,representative_fixture=r["fixture"],weight_in_144_state_superspace=len(m),old_projected_action=r["old_projected_action"],new_projected_action=r["new_projected_action"],old_causal_path=r["old_causal_path"],new_causal_path=r["new_causal_path"],compatibility=r["compatibility"]))
 for r in R:r["execution_state_id"]=M[C(r["fixture"])]
 return R,Q
def main():
 p=argparse.ArgumentParser();p.add_argument("--work",required=True);p.add_argument("--out",required=True);a=p.parse_args();w,o=pathlib.Path(a.work),pathlib.Path(a.out);w.mkdir(parents=True,exist_ok=True);o.mkdir(parents=True,exist_ok=True);r=w/"bt";subprocess.check_call(["git","clone","--quiet","--no-tags",U,str(r)])
 o1,n1=pair(r,T1,o,"T01_NIGHT");o2,n2=pair(r,T2,o,"T02_WEEKLY");os=S("git","show",f'{T1[0]}:custom_components/better_thermostat/services.yaml',cwd=r);ns=S("git","show",f'{T1[1]}:custom_components/better_thermostat/services.yaml',cwd=r);oc=S("git","show",f'{T1[0]}:custom_components/better_thermostat/climate.py',cwd=r)
 assert all(x in o1 for x in ("better_thermostat.set_temp_target_temperature","better_thermostat.restore_saved_target_temperature")) and all(x in n1 for x in ("climate.set_preset_mode","preset_mode: sleep","preset_mode: none"));assert all(x in os and x not in ns for x in ("set_temp_target_temperature:","restore_saved_target_temperature:")) and all(x in oc for x in ("SERVICE_SET_TEMP_TARGET_TEMPERATURE","SERVICE_RESTORE_SAVED_TARGET_TEMPERATURE","async_register_entity_service"));assert "{% if active_slot == '1' %}" in o2 and "{% if active_slot | int == 1 %}" in n2 and "{% if not enable_pause_switch or pause_switch == '' %}false" in o2 and "{{ false }}" in n2
 for x in ("presence_entity_selection: !input presence_entity","pause_switch_selection: !input pause_switch","namespace(home=false)","namespace(paused=false)",'value_template: "{{ not schedule_paused }}"','value_template: "{{ not anyone_home }}"'):assert x in n2
 R1=[]
 for i,(s,oo,od,no,nd,op,np) in enumerate((("off","better_thermostat.restore_saved_target_temperature",{},"climate.set_preset_mode",{"preset_mode":"none"},"schedule:off:restore_saved_target_temperature","schedule:off:set_preset_none"),("on","better_thermostat.set_temp_target_temperature",{"temperature":18.0},"climate.set_preset_mode",{"preset_mode":"sleep"},"schedule:on:set_temp_target_temperature","schedule:on:set_preset_sleep"))):
  oa,na=A(T1[8],oo,od),A(T1[8],no,nd);R1.append(dict(analysis_state_id=f"VE2-T01-A{i:02d}",execution_state_id=f"VE2-T01-S{i:02d}",fixture={"schedule_state":s},old_projected_action=oa,new_projected_action=na,old_causal_path=op,new_causal_path=np,compatibility="COMPATIBLE_ACROSS_VERSION" if oa==na else "RETIRED_BY_UPDATE"))
 R,Q=derive();m1=json.load(open("VE2_T01_EXECUTION_STATE_MANIFEST_V1.json"));m2=json.load(open("VE2_T02_EXECUTION_STATE_MANIFEST_V1.json"));e1=json.load(open("VE2_T01_EXPECTED_FRONTIER_V1.json"));e2=json.load(open("VE2_T02_EXPECTED_FRONTIER_V1.json"))
 assert H(R1)==F[0] and e1["rows"]==R1 and H(R)==F[1] and H(Q)==F[2] and H(m2["states"])==F[3] and len(R)==144 and len(Q)==42 and sum(x["compatibility"]=="COMPATIBLE_ACROSS_VERSION" for x in R)==97 and sum(x["compatibility"]=="COMPATIBLE_ACROSS_VERSION" for x in Q)==18 and sum(x["weight_in_144_state_superspace"] for x in Q)==144;assert [x["fixture"] for x in m2["states"]]==[x["representative_fixture"] for x in Q] and [x["opaque_state_id"] for x in m2["states"]]==[x["execution_state_id"] for x in Q]
 for m in (m1,m2):
  z=json.dumps(m["states"],sort_keys=True)
  for x in ("compatibility","old_projected_action","new_projected_action","old_causal_path","new_causal_path","weight_in_144_state_superspace"):assert x not in z
 (o/"T01_ROWS.json").write_text(json.dumps(R1,sort_keys=True,indent=2)+"\n");(o/"T02_ABSTRACT_ROWS.json").write_text(json.dumps(R,sort_keys=True,indent=2)+"\n");(o/"T02_QUOTIENT_ROWS.json").write_text(json.dumps(Q,sort_keys=True,indent=2)+"\n");v={"schema":"replaymark.ve2.transition-static-semantic-qualification.v1","status":"PASS","private_authority_head":"3b941bce64dbb5c38a1125fb007f9eaa102dceb4","T01":{"states":2,"compatible":0,"retired":2,"rows_sha256":H(R1)},"T02":{"abstract_states":144,"compatible":97,"retired":47,"abstract_rows_sha256":H(R),"classes":42,"class_compatible":18,"class_retired":24,"quotient_rows_sha256":H(Q),"execution_states_sha256":H(m2["states"])},"independence":{"private_generator_executed":False,"private_verifier_executed":False,"upstream_git_verified":True},"scientific_exposure":{"frontier_result_seen":False,"ve2_home_assistant_scientific_cells":0,"ve2_replaymark_scientific_cells":0}};(o/"VE2_PUBLIC_TRANSITION_QUALIFICATION_V1.json").write_text(json.dumps(v,sort_keys=True,indent=2)+"\n");print(json.dumps(v,sort_keys=True))
if __name__=="__main__":main()
