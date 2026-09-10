from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import traceback
from typing import Any

UPSTREAM = "https://github.com/KartoffelToby/better_thermostat.git"
IMAGE_REPO = "ghcr.io/home-assistant/home-assistant"
CONSTITUTION = "VE2_RUNTIME_DISCOVERY_CONSTITUTION_V1.json"
CANDIDATES = "VE2_RUNTIME_DISCOVERY_CANDIDATES_V1.json"
AUTHORITY = "VE2_RUNTIME_DISCOVERY_PRE_RESULT_AUTHORITY_V3.json"
REMEDIATION = "VE2_RUNTIME_DISCOVERY_REMEDIATION_CONTRACT_V3.json"
FAILED_V2 = "VE2_RUNTIME_DISCOVERY_V2_FAILURE_RECEIPT.json"
INSIDE_SCHEMA = "replaymark.ve2.runtime-inside-probe.v3"
PREFLIGHT_IMAGE = "ghcr.io/home-assistant/home-assistant@sha256:372d991e58882a1d8c68c07e9aa3f3b509276e695355f73ccdb03baa70407293"

SOURCE_FACTS = {
    "T01_OLD_HISTORY": {"commit":"cd4c3121c92f59d5ac1f3533424bc570209ce6ef","blueprint":"blueprints/night_mode.yaml","blueprint_sha256":"9a2b545288a3cae15f497796cb9001e6a142fc02c6150df6b11975d79f6083d8","hacs_minimum":"2021.12.0","manifest_version":"1.0.0-dev"},
    "T01_NEW_TARGET": {"commit":"96ae2f87b3b1a1b095dbf1f74f37f63fbc34c32f","blueprint":"blueprints/night_mode.yaml","blueprint_sha256":"9c2a4b03d57a59d6b13a34b0bf4031104c19abafa8331e1b329861f45eeef363","hacs_minimum":"2025.12.0","manifest_version":"1.8.0-dev"},
    "T02_OLD": {"commit":"ac189909982c5edea1260e767027d6fad90ef4bd","blueprint":"blueprints/weekly_heating_schedule.yaml","blueprint_sha256":"5593911e8ef5db3cc29f1ab4bb6658538f6e68fecbd010de0527ecc41b5d4115","hacs_minimum":"2025.12.0","manifest_version":"1.8.1-dev"},
    "T02_NEW": {"commit":"5b4496de5659fd2c6ec5c67a9797e6659797866c","blueprint":"blueprints/weekly_heating_schedule.yaml","blueprint_sha256":"45375bb3a0a09b5ae7db9bdc038a73fcbec80425ec38e858e89633cb1dfdf37e","hacs_minimum":"2026.7.2","manifest_version":"1.9.0"},
}

class InfrastructureFailure(RuntimeError):
    def __init__(self, detail: dict[str, Any]):
        super().__init__(detail.get("failure_class", "DISCOVERY_INFRASTRUCTURE_FAILURE"))
        self.detail = detail

def run(args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

def output(args, cwd=None): return run(args, cwd=cwd).stdout.strip()
def sha256_bytes(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def sha256_file(path: pathlib.Path) -> str: return sha256_bytes(path.read_bytes())
def load_json(path: pathlib.Path) -> Any: return json.loads(path.read_text(encoding="utf-8"))
def source_bytes(repo: pathlib.Path, commit: str, path: str) -> bytes: return subprocess.check_output(["git","show",f"{commit}:{path}"],cwd=repo)

def materialize(repo: pathlib.Path, commit: str, dst: pathlib.Path) -> None:
    dst = dst.resolve(); dst.mkdir(parents=True, exist_ok=False)
    p1 = subprocess.Popen(["git","archive","--format=tar",commit],cwd=repo,stdout=subprocess.PIPE)
    p2 = subprocess.run(["tar","-xf","-","-C",str(dst)],stdin=p1.stdout,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if p1.stdout: p1.stdout.close()
    rc = p1.wait()
    if rc or p2.returncode: raise RuntimeError(f"git-archive-failed:{rc}:{p2.returncode}:{p2.stdout.decode(errors='replace')}")

def source_identity(repo: pathlib.Path, role: str, dst_root: pathlib.Path) -> dict[str, Any]:
    f=SOURCE_FACTS[role]; commit=f["commit"]; bp=f["blueprint"]
    bp_raw=source_bytes(repo,commit,bp); manifest_raw=source_bytes(repo,commit,"custom_components/better_thermostat/manifest.json"); hacs_raw=source_bytes(repo,commit,"hacs.json")
    manifest=json.loads(manifest_raw); hacs=json.loads(hacs_raw)
    assert sha256_bytes(bp_raw)==f["blueprint_sha256"]
    assert manifest.get("version")==f["manifest_version"]
    assert hacs.get("homeassistant")==f["hacs_minimum"]
    source_dir=(dst_root/role.lower()).resolve(); materialize(repo,commit,source_dir)
    services=(source_dir/"custom_components/better_thermostat/services.yaml").read_text(encoding="utf-8")
    climate=(source_dir/"custom_components/better_thermostat/climate.py").read_text(encoding="utf-8")
    if role=="T01_OLD_HISTORY":
        assert "set_temp_target_temperature" in services and "restore_saved_target_temperature" in services
        assert "SERVICE_SET_TEMP_TARGET_TEMPERATURE" in climate and "SERVICE_RESTORE_SAVED_TARGET_TEMPERATURE" in climate
    if role=="T01_NEW_TARGET":
        assert "set_temp_target_temperature" not in services and "restore_saved_target_temperature" not in services
        assert "SERVICE_SET_TEMP_TARGET_TEMPERATURE" not in climate and "SERVICE_RESTORE_SAVED_TARGET_TEMPERATURE" not in climate
    return {"role":role,"commit":commit,"commit_tree_sha1":output(["git","rev-parse",f"{commit}^{{tree}}"],cwd=repo),"component_tree_sha1":output(["git","rev-parse",f"{commit}:custom_components/better_thermostat"],cwd=repo),"blueprint_path":bp,"blueprint_blob_sha1":output(["git","rev-parse",f"{commit}:{bp}"],cwd=repo),"blueprint_sha256":sha256_bytes(bp_raw),"manifest_sha256":sha256_bytes(manifest_raw),"manifest_version":manifest.get("version"),"manifest_requirements":manifest.get("requirements") or [],"hacs_sha256":sha256_bytes(hacs_raw),"hacs_minimum":hacs.get("homeassistant"),"standalone_const_py_present":(source_dir/"custom_components/better_thermostat/const.py").is_file(),"source_dir":str(source_dir)}

def image_identity(tag: str) -> dict[str, Any]:
    ref=f"{IMAGE_REPO}:{tag}"; pull=run(["docker","pull",ref],check=False)
    if pull.returncode: return {"tag":tag,"reference":ref,"available":False,"pull_output":pull.stdout[-3000:]}
    digests=json.loads(output(["docker","image","inspect",ref,"--format","{{json .RepoDigests}}"])); matching=sorted(x for x in digests if x.startswith(IMAGE_REPO+"@sha256:"))
    if not matching: raise InfrastructureFailure({"failure_class":"IMAGE_IDENTITY_FAILURE","tag":tag,"digests":digests})
    return {"tag":tag,"reference":ref,"available":True,"repo_digest":matching[0],"image_id":output(["docker","image","inspect",ref,"--format","{{.Id}}"]),"os":output(["docker","image","inspect",ref,"--format","{{.Os}}"]),"architecture":output(["docker","image","inspect",ref,"--format","{{.Architecture}}"])}

def transport_preflight(work: pathlib.Path) -> dict[str, Any]:
    root=(work/"transport-preflight").resolve(); root.mkdir(); sentinel=(root/"sentinel.txt").resolve(); sentinel.write_text("VE2_V3_ABSOLUTE_BIND\n")
    proc=run(["docker","run","--rm","--network","none","--read-only","--mount",f"type=bind,src={sentinel},dst=/sentinel.txt,readonly","--entrypoint","python",PREFLIGHT_IMAGE,"-c","assert open('/sentinel.txt').read()=='VE2_V3_ABSOLUTE_BIND\\n'; print('PASS')"],check=False)
    if proc.returncode or proc.stdout.strip().splitlines()[-1:] != ["PASS"]: raise InfrastructureFailure({"failure_class":"TRANSPORT_PREFLIGHT_FAILURE","docker_exit":proc.returncode,"tail":proc.stdout[-2000:]})
    return {"status":"PASS","host_path_absolute":sentinel.is_absolute(),"docker_exit":0,"image":PREFLIGHT_IMAGE}

def inside_probe(image: dict[str, Any], source: dict[str, Any], inside_script: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    source_dir=pathlib.Path(source["source_dir"]).resolve(strict=True); script=inside_script.resolve(strict=True); work=work.resolve(strict=True)
    result_path=(work/("inside-"+source["role"].lower()+"-"+image["tag"].replace(".","_")+".json")).resolve(); result_path.write_text('{"status":"NOT_STARTED"}\n')
    for p in (source_dir,script,result_path):
        if not p.is_absolute(): raise InfrastructureFailure({"failure_class":"NON_ABSOLUTE_BIND_PATH","path":str(p)})
    cmd=["docker","run","--rm","--network","none","--read-only","--tmpfs","/tmp:rw,nosuid,nodev,size=64m","--env","PYTHONDONTWRITEBYTECODE=1","--env","HOME=/tmp","--env","VE2_PROBE_OUT=/result.json","--mount",f"type=bind,src={source_dir},dst=/probe,readonly","--mount",f"type=bind,src={script},dst=/ve2_inside_probe.py,readonly","--mount",f"type=bind,src={result_path},dst=/result.json","--entrypoint","python",image["reference"],"/ve2_inside_probe.py"]
    proc=run(cmd,check=False)
    try: result=load_json(result_path)
    except Exception as exc: raise InfrastructureFailure({"failure_class":"UNREADABLE_PROBE_RESULT","docker_exit":proc.returncode,"error":repr(exc),"tail":proc.stdout[-2000:]})
    started=result.get("schema")==INSIDE_SCHEMA
    if not started: raise InfrastructureFailure({"failure_class":"PRE_PROBE_CONTAINER_LAUNCH_FAILURE","docker_exit":proc.returncode,"tail":proc.stdout[-3000:],"inside_result":result})
    result.update({"probe_started":True,"docker_exit":proc.returncode,"docker_output_tail":proc.stdout[-4000:],"result_sha256":sha256_file(result_path),"source_role":source["role"],"host_bind_paths_absolute":True})
    if result.get("status")=="PASS" and proc.returncode: raise InfrastructureFailure({"failure_class":"PASS_WITH_NONZERO_CONTAINER_EXIT","probe":result})
    if result.get("status")=="PASS" and result.get("home_assistant_version")!=image["tag"]: result["status"]="FAIL"; result["version_mismatch"]={"expected":image["tag"],"observed":result.get("home_assistant_version")}
    return result

def candidate_probe(tag: str, sources: list[dict[str, Any]], inside_script: pathlib.Path, work: pathlib.Path, preferred_digest: str|None=None) -> dict[str, Any]:
    image=image_identity(tag); attempt={"tag":tag,"image":image,"source_probes":[],"status":"FAIL"}
    if not image["available"]: attempt["failure_class"]="IMAGE_UNAVAILABLE"; return attempt
    if preferred_digest and tag=="2026.9.0" and image["repo_digest"]!=IMAGE_REPO+"@"+preferred_digest: attempt["failure_class"]="PREFERRED_DIGEST_MISMATCH"; return attempt
    for source in sources:
        r=inside_probe(image,source,inside_script,work); attempt["source_probes"].append(r)
        if r.get("status")!="PASS" or r.get("docker_exit")!=0: attempt["failure_class"]="SOURCE_RUNTIME_INCOMPATIBLE"; return attempt
    attempt["status"]="PASS"; return attempt

def choose(tags, sources, inside_script, work, preferred_digest=None):
    attempts=[]
    for tag in tags:
        a=candidate_probe(tag,sources,inside_script,work,preferred_digest); attempts.append(a)
        if a["status"]=="PASS": return a,attempts
    return None,attempts

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--inside-probe",required=True); ap.add_argument("--work",required=True); ap.add_argument("--out",required=True); args=ap.parse_args()
    work=pathlib.Path(args.work).resolve(); out=pathlib.Path(args.out).resolve(); work.mkdir(parents=True,exist_ok=True); out.parent.mkdir(parents=True,exist_ok=True)
    result={"schema":"replaymark.ve2.runtime-discovery-result.v3","status":"FAIL","scientific_result_opened":False,"frontier_result_seen":False,"ve2_home_assistant_scientific_cells":0,"ve2_replaymark_scientific_cells":0,"transition_fixture_executed":False,"historical_action_dispatched":False,"rerun_all_roles_from_first_candidate":True}
    try:
        constitution=load_json(pathlib.Path(CONSTITUTION)); candidates=load_json(pathlib.Path(CANDIDATES)); authority=load_json(pathlib.Path(AUTHORITY)); remediation=load_json(pathlib.Path(REMEDIATION)); failed=load_json(pathlib.Path(FAILED_V2))
        assert constitution["hard_rules"]["first_PASS_candidate_is_selected"] is True; assert authority["science_open_authorized"] is False; assert remediation["science_open_authorized"] is False; assert failed["partial_selection_promotable"] is False
        result["transport_preflight"]=transport_preflight(work)
        repo=(work/"better_thermostat").resolve(); run(["git","clone","--quiet","--no-tags",UPSTREAM,str(repo)])
        for f in SOURCE_FACTS.values(): run(["git","cat-file","-e",f'{f["commit"]}^{{commit}}'],cwd=repo)
        srcroot=(work/"sources").resolve(); srcroot.mkdir(); identities={r:source_identity(repo,r,srcroot) for r in ("T01_OLD_HISTORY","T01_NEW_TARGET","T02_OLD","T02_NEW")}
        result["source_identities"]={k:{kk:vv for kk,vv in v.items() if kk!="source_dir"} for k,v in identities.items()}; roles=candidates["roles"]; attempts={}
        t01o,attempts["T01_OLD_HISTORY"]=choose(roles["T01_OLD_HISTORY"]["ordered_tags"],[identities["T01_OLD_HISTORY"]],pathlib.Path(args.inside_probe),work)
        t01n,attempts["T01_NEW_TARGET"]=choose(roles["T01_NEW_TARGET"]["ordered_tags"],[identities["T01_NEW_TARGET"]],pathlib.Path(args.inside_probe),work)
        t02,attempts["T02_COMMON"]=choose(roles["T02_COMMON"]["ordered_tags"],[identities["T02_OLD"],identities["T02_NEW"]],pathlib.Path(args.inside_probe),work,roles["T02_COMMON"]["preferred_common_digest"])
        result["attempts"]=attempts; result["selected"]={"T01_OLD_HISTORY":t01o,"T01_NEW_TARGET":t01n,"T02_COMMON":t02}
        if all((t01o,t01n,t02)): result["status"]="PASS"
        else: result["failure_class"]="NO_PASSING_CANDIDATE_IN_FROZEN_LATTICE"
    except InfrastructureFailure as exc: result["failure_class"]="DISCOVERY_INFRASTRUCTURE_FAILURE"; result["infrastructure_failure"]=exc.detail
    except Exception as exc: result["failure_class"]="DISCOVERY_RUNNER_FAILURE"; result["error_type"]=type(exc).__name__; result["error"]=str(exc); result["traceback"]=traceback.format_exc()
    payload=json.dumps(result,sort_keys=True,indent=2)+"\n"; out.write_text(payload); print(json.dumps({"status":result["status"],"failure_class":result.get("failure_class"),"science":0,"result_sha256":sha256_bytes(payload.encode()),"selected_tags":{k:(v["tag"] if isinstance(v,dict) and "tag" in v else None) for k,v in (result.get("selected") or {}).items()}},sort_keys=True)); return 0 if result["status"]=="PASS" else 4

if __name__=="__main__": sys.exit(main())
