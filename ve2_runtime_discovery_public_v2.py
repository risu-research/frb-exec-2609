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
AUTHORITY = "VE2_RUNTIME_DISCOVERY_PRE_RESULT_AUTHORITY_V1.json"
REMEDIATION = "VE2_RUNTIME_DISCOVERY_REMEDIATION_CONTRACT_V2_MIRROR.json"
FAILED_V1 = "VE2_RUNTIME_DISCOVERY_V1_FAILURE_RECEIPT_MIRROR.json"
TRANSPORT_PREFLIGHT_IMAGE = (
    "ghcr.io/home-assistant/home-assistant@"
    "sha256:372d991e58882a1d8c68c07e9aa3f3b509276e695355f73ccdb03baa70407293"
)

SOURCE_FACTS = {
    "T01_OLD_HISTORY": {"commit":"cd4c3121c92f59d5ac1f3533424bc570209ce6ef","blueprint":"blueprints/night_mode.yaml","blueprint_sha256":"9a2b545288a3cae15f497796cb9001e6a142fc02c6150df6b11975d79f6083d8","hacs_minimum":"2021.12.0","manifest_version":"1.0.0-dev"},
    "T01_NEW_TARGET": {"commit":"96ae2f87b3b1a1b095dbf1f74f37f63fbc34c32f","blueprint":"blueprints/night_mode.yaml","blueprint_sha256":"9c2a4b03d57a59d6b13a34b0bf4031104c19abafa8331e1b329861f45eeef363","hacs_minimum":"2025.12.0","manifest_version":"1.8.0-dev"},
    "T02_OLD": {"commit":"ac189909982c5edea1260e767027d6fad90ef4bd","blueprint":"blueprints/weekly_heating_schedule.yaml","blueprint_sha256":"5593911e8ef5db3cc29f1ab4bb6658538f6e68fecbd010de0527ecc41b5d4115","hacs_minimum":"2025.12.0","manifest_version":"1.8.1-dev"},
    "T02_NEW": {"commit":"5b4496de5659fd2c6ec5c67a9797e6659797866c","blueprint":"blueprints/weekly_heating_schedule.yaml","blueprint_sha256":"45375bb3a0a09b5ae7db9bdc038a73fcbec80425ec38e858e89633cb1dfdf37e","hacs_minimum":"2026.7.2","manifest_version":"1.9.0"},
}

class DiscoveryInfrastructureFailure(RuntimeError):
    pass


def run(args, cwd=None, check=True, text=True):
    return subprocess.run(args, cwd=cwd, check=check, text=text, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def output(args, cwd=None):
    return run(args, cwd=cwd).stdout.strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def source_bytes(repo: pathlib.Path, commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=repo)


def ruby_psych_parse(path: pathlib.Path) -> None:
    run(["ruby", "-rpsych", "-e", "Psych.parse_file(ARGV[0]); puts 'PASS'", str(path)])


def materialize(repo: pathlib.Path, commit: str, dst: pathlib.Path) -> None:
    dst.mkdir(parents=True, exist_ok=False)
    p1 = subprocess.Popen(["git", "archive", "--format=tar", commit], cwd=repo, stdout=subprocess.PIPE)
    p2 = subprocess.run(["tar", "-xf", "-", "-C", str(dst)], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p1.stdout:
        p1.stdout.close()
    rc = p1.wait()
    if rc != 0 or p2.returncode != 0:
        raise RuntimeError(f"git-archive-failed:{rc}:{p2.returncode}:{p2.stdout.decode(errors='replace')}")


def source_identity(repo: pathlib.Path, role: str, dst_root: pathlib.Path) -> dict[str, Any]:
    f = SOURCE_FACTS[role]
    commit = f["commit"]
    bp = f["blueprint"]
    bp_raw = source_bytes(repo, commit, bp)
    if sha256_bytes(bp_raw) != f["blueprint_sha256"]:
        raise AssertionError(("blueprint-sha", role))
    manifest_raw = source_bytes(repo, commit, "custom_components/better_thermostat/manifest.json")
    hacs_raw = source_bytes(repo, commit, "hacs.json")
    manifest = json.loads(manifest_raw)
    hacs = json.loads(hacs_raw)
    if manifest.get("version") != f["manifest_version"]:
        raise AssertionError(("manifest-version", role, manifest.get("version")))
    if hacs.get("homeassistant") != f["hacs_minimum"]:
        raise AssertionError(("hacs-minimum", role, hacs.get("homeassistant")))
    full_tree = output(["git", "rev-parse", f"{commit}^{{tree}}"], cwd=repo)
    component_tree = output(["git", "rev-parse", f"{commit}:custom_components/better_thermostat"], cwd=repo)
    bp_blob = output(["git", "rev-parse", f"{commit}:{bp}"], cwd=repo)
    source_dir = (dst_root / role.lower()).resolve()
    materialize(repo, commit, source_dir)
    ruby_psych_parse(source_dir / bp)
    services = (source_dir / "custom_components/better_thermostat/services.yaml").read_text(encoding="utf-8")
    climate = (source_dir / "custom_components/better_thermostat/climate.py").read_text(encoding="utf-8")
    if role == "T01_OLD_HISTORY":
        for token in ("set_temp_target_temperature", "restore_saved_target_temperature"):
            if token not in services:
                raise AssertionError(("old-services-yaml-missing", token))
        for token in ("SERVICE_SET_TEMP_TARGET_TEMPERATURE", "SERVICE_RESTORE_SAVED_TARGET_TEMPERATURE"):
            if token not in climate:
                raise AssertionError(("old-climate-registration-missing", token))
    if role == "T01_NEW_TARGET":
        for token in ("set_temp_target_temperature", "restore_saved_target_temperature"):
            if token in services:
                raise AssertionError(("new-services-yaml-still-has-old", token))
        for token in ("SERVICE_SET_TEMP_TARGET_TEMPERATURE", "SERVICE_RESTORE_SAVED_TARGET_TEMPERATURE"):
            if token in climate:
                raise AssertionError(("new-climate-still-registers-old", token))
    return {
        "role": role, "commit": commit, "commit_tree_sha1": full_tree, "component_tree_sha1": component_tree,
        "blueprint_path": bp, "blueprint_blob_sha1": bp_blob, "blueprint_sha256": sha256_bytes(bp_raw),
        "manifest_blob_sha1": output(["git", "rev-parse", f"{commit}:custom_components/better_thermostat/manifest.json"], cwd=repo),
        "manifest_sha256": sha256_bytes(manifest_raw), "manifest_version": manifest.get("version"),
        "manifest_requirements": manifest.get("requirements") or [],
        "hacs_blob_sha1": output(["git", "rev-parse", f"{commit}:hacs.json"], cwd=repo),
        "hacs_sha256": sha256_bytes(hacs_raw), "hacs_minimum": hacs.get("homeassistant"),
        "blueprint_psych_parse": "PASS", "source_dir": str(source_dir),
    }


def image_identity(tag: str) -> dict[str, Any]:
    ref = f"{IMAGE_REPO}:{tag}"
    pull = run(["docker", "pull", ref], check=False)
    if pull.returncode != 0:
        return {"tag":tag,"reference":ref,"available":False,"pull_output":pull.stdout[-4000:]}
    repo_digests = json.loads(output(["docker", "image", "inspect", ref, "--format", "{{json .RepoDigests}}"] ))
    matching = sorted(x for x in repo_digests if x.startswith(IMAGE_REPO + "@sha256:"))
    if not matching:
        raise DiscoveryInfrastructureFailure(("no-repodigest", ref, repo_digests))
    return {"tag":tag,"reference":ref,"available":True,"repo_digest":matching[0],
            "image_id":output(["docker","image","inspect",ref,"--format","{{.Id}}"]),
            "os":output(["docker","image","inspect",ref,"--format","{{.Os}}"]),
            "architecture":output(["docker","image","inspect",ref,"--format","{{.Architecture}}"])}


def transport_preflight(work: pathlib.Path) -> dict[str, Any]:
    host_dir = (work / "transport-preflight").resolve()
    host_dir.mkdir(parents=True, exist_ok=False)
    (host_dir / "sentinel.txt").write_text("VE2_TRANSPORT_SENTINEL_V2\n", encoding="utf-8")
    if not host_dir.is_absolute():
        raise DiscoveryInfrastructureFailure("transport-preflight-host-path-not-absolute")
    pull = run(["docker", "pull", TRANSPORT_PREFLIGHT_IMAGE], check=False)
    if pull.returncode != 0:
        raise DiscoveryInfrastructureFailure("transport-preflight-image-pull-failed:" + pull.stdout[-2000:])
    code = "import pathlib; p=pathlib.Path('/transport/sentinel.txt'); assert p.read_text()=='VE2_TRANSPORT_SENTINEL_V2\\n'; print('PASS')"
    proc = run([
        "docker","run","--rm","--network","none","--read-only","--tmpfs","/tmp:rw,nosuid,nodev,size=16m",
        "--volume",f"{host_dir}:/transport:ro","--entrypoint","python",TRANSPORT_PREFLIGHT_IMAGE,"-c",code
    ], check=False)
    if proc.returncode != 0 or proc.stdout.strip().splitlines()[-1:] != ["PASS"]:
        raise DiscoveryInfrastructureFailure("transport-preflight-failed:" + proc.stdout[-3000:])
    return {"status":"PASS","host_path_absolute":True,"image":TRANSPORT_PREFLIGHT_IMAGE,"docker_exit":0}


def inside_probe(image: dict[str, Any], source: dict[str, Any], inside_script: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    source_bind = pathlib.Path(source["source_dir"]).resolve(strict=True)
    script_bind = inside_script.resolve(strict=True)
    result_path = (work / ("inside-" + source["role"].lower() + "-" + image["tag"].replace(".", "_") + ".json")).resolve()
    for p in (source_bind, script_bind, result_path.parent):
        if not p.is_absolute():
            raise DiscoveryInfrastructureFailure("non-absolute-bind-path:" + str(p))
    sentinel = {"schema":"replaymark.ve2.host-probe-sentinel.v2","status":"UNWRITTEN"}
    result_path.write_text(json.dumps(sentinel, sort_keys=True) + "\n", encoding="utf-8")
    cmd = ["docker","run","--rm","--network","none","--read-only","--tmpfs","/tmp:rw,nosuid,nodev,size=64m",
           "--env","PYTHONDONTWRITEBYTECODE=1","--env","HOME=/tmp","--env","VE2_PROBE_OUT=/result.json",
           "--volume",f"{source_bind}:/probe:ro","--volume",f"{script_bind}:/ve2_inside_probe.py:ro",
           "--volume",f"{result_path}:/result.json","--entrypoint","python",image["reference"],"/ve2_inside_probe.py"]
    proc = run(cmd, check=False)
    try:
        result = load_json(result_path)
    except Exception as exc:
        raise DiscoveryInfrastructureFailure("unreadable-inside-result:" + repr(exc))
    probe_result_present = result.get("schema") == "replaymark.ve2.runtime-inside-probe.v1"
    if not probe_result_present:
        raise DiscoveryInfrastructureFailure(
            "inside-probe-did-not-write-result:docker_exit=%s:tail=%s" % (proc.returncode, proc.stdout[-2000:])
        )
    result["docker_exit"] = proc.returncode
    result["docker_output_tail"] = proc.stdout[-5000:]
    result["result_sha256"] = sha256_file(result_path)
    result["source_role"] = source["role"]
    result["probe_result_present"] = True
    result["host_bind_paths_absolute"] = True
    if result.get("status") == "PASS" and proc.returncode != 0:
        raise DiscoveryInfrastructureFailure("probe-pass-with-nonzero-docker-exit")
    if result.get("status") == "PASS" and result.get("home_assistant_version") != image["tag"]:
        result["status"] = "FAIL"
        result["version_mismatch"] = {"expected":image["tag"],"observed":result.get("home_assistant_version")}
    return result


def candidate_probe(tag: str, sources: list[dict[str, Any]], inside_script: pathlib.Path, work: pathlib.Path, preferred_digest: str | None = None) -> dict[str, Any]:
    image = image_identity(tag)
    attempt = {"tag":tag,"image":image,"source_probes":[],"status":"FAIL"}
    if not image["available"]:
        attempt["failure_class"] = "IMAGE_UNAVAILABLE"
        return attempt
    if preferred_digest and tag == "2026.9.0" and image["repo_digest"] != IMAGE_REPO + "@" + preferred_digest:
        attempt["failure_class"] = "PREFERRED_DIGEST_MISMATCH"
        attempt["expected_digest"] = IMAGE_REPO + "@" + preferred_digest
        return attempt
    for source in sources:
        r = inside_probe(image, source, inside_script, work)
        attempt["source_probes"].append(r)
        if r.get("status") != "PASS" or r.get("docker_exit") != 0:
            attempt["failure_class"] = "SOURCE_RUNTIME_INCOMPATIBLE"
            return attempt
    attempt["status"] = "PASS"
    return attempt


def choose(tags: list[str], sources: list[dict[str, Any]], inside_script: pathlib.Path, work: pathlib.Path, preferred_digest: str | None = None):
    attempts = []
    for tag in tags:
        a = candidate_probe(tag, sources, inside_script, work, preferred_digest)
        attempts.append(a)
        if a["status"] == "PASS":
            return a, attempts
    return None, attempts


def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument("--inside-probe",required=True);ap.add_argument("--work",required=True);ap.add_argument("--out",required=True);args=ap.parse_args()
    work=pathlib.Path(args.work).resolve();out=pathlib.Path(args.out).resolve();work.mkdir(parents=True,exist_ok=True);out.parent.mkdir(parents=True,exist_ok=True)
    result={"schema":"replaymark.ve2.runtime-discovery-result.v2","status":"FAIL","scientific_result_opened":False,"frontier_result_seen":False,"ve2_home_assistant_scientific_cells":0,"ve2_replaymark_scientific_cells":0,"transition_fixture_executed":False,"historical_action_dispatched":False,"v1_failed_run_preserved":True}
    try:
        constitution=load_json(pathlib.Path(CONSTITUTION));candidates=load_json(pathlib.Path(CANDIDATES));authority=load_json(pathlib.Path(AUTHORITY));remediation=load_json(pathlib.Path(REMEDIATION));failed=load_json(pathlib.Path(FAILED_V1))
        if constitution["hard_rules"]["first_PASS_candidate_is_selected"] is not True: raise AssertionError("first-pass law not frozen")
        if authority["science_open_authorized"] is not False: raise AssertionError("discovery authority unexpectedly authorizes science")
        if remediation["status"] != "FROZEN_PROSPECTIVE_PRE_V2_EXECUTION": raise AssertionError("remediation contract not frozen")
        if failed["public_execution"]["run_id"] != 34506501065 or failed["rerun_of_v1_authority_authorized"] is not False: raise AssertionError("v1 failure receipt mismatch")
        result["transport_preflight"] = transport_preflight(work)
        repo=work/"better_thermostat";run(["git","clone","--quiet","--no-tags",UPSTREAM,str(repo)])
        for f in SOURCE_FACTS.values(): run(["git","cat-file","-e",f'{f["commit"]}^{{commit}}'],cwd=repo)
        srcroot=(work/"sources").resolve();srcroot.mkdir()
        identities={role:source_identity(repo,role,srcroot) for role in ("T01_OLD_HISTORY","T01_NEW_TARGET","T02_OLD","T02_NEW")}
        roles=candidates["roles"]
        t01_old,a1=choose(roles["T01_OLD_HISTORY"]["ordered_tags"],[identities["T01_OLD_HISTORY"]],pathlib.Path(args.inside_probe),work)
        t01_new,a2=choose(roles["T01_NEW_TARGET"]["ordered_tags"],[identities["T01_NEW_TARGET"]],pathlib.Path(args.inside_probe),work)
        t02,a3=choose(roles["T02_COMMON"]["ordered_tags"],[identities["T02_OLD"],identities["T02_NEW"]],pathlib.Path(args.inside_probe),work,roles["T02_COMMON"]["preferred_common_digest"])
        result["source_identities"]={k:{kk:vv for kk,vv in v.items() if kk!="source_dir"} for k,v in identities.items()}
        result["attempts"]={"T01_OLD_HISTORY":a1,"T01_NEW_TARGET":a2,"T02_COMMON":a3}
        result["selected"]={"T01_OLD_HISTORY":t01_old,"T01_NEW_TARGET":t01_new,"T02_COMMON":t02}
        if not all((t01_old,t01_new,t02)): result["failure_class"]="NO_PASSING_CANDIDATE_IN_FROZEN_LATTICE"
        else: result["status"]="PASS"
    except DiscoveryInfrastructureFailure as exc:
        result["failure_class"]="DISCOVERY_INFRASTRUCTURE_FAILURE";result["error_type"]=type(exc).__name__;result["error"]=str(exc);result["traceback"]=traceback.format_exc()
    except Exception as exc:
        result["failure_class"]=result.get("failure_class","DISCOVERY_RUNNER_FAILURE");result["error_type"]=type(exc).__name__;result["error"]=str(exc);result["traceback"]=traceback.format_exc()
    payload=json.dumps(result,sort_keys=True,indent=2)+"\n";out.write_text(payload,encoding="utf-8")
    print(json.dumps({"status":result["status"],"science":0,"failure_class":result.get("failure_class"),"result_sha256":sha256_bytes(payload.encode()),"selected_tags":{k:(v["tag"] if isinstance(v,dict) and "tag" in v else None) for k,v in (result.get("selected") or {}).items()}},sort_keys=True))
    return 0 if result["status"]=="PASS" else 4

if __name__=="__main__": sys.exit(main())
