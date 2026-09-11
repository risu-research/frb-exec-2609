#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

PROTOCOL_COMMIT = "6e4721894f24f27b69e4f2f2396defc77a581b60"
GATE1_COMMIT = "b947810edf2c6b408c36cbccdd081484cf57374f"
CONSTITUTION_COMMIT = "633abb9cdbef509dc5baf87d2cb2820b649e7965"
HA_IMAGE = "ghcr.io/home-assistant/home-assistant@sha256:372d991e58882a1d8c68c07e9aa3f3b509276e695355f73ccdb03baa70407293"

REPOS = [
    {"repository": "Blackymas/NSPanel_HA_Blueprint", "default_branch": "main", "head": "05ecefde2bac5db8bc96c02148058518d78a06fb"},
    {"repository": "EPMatt/awesome-ha-blueprints", "default_branch": "main", "head": "79b7c6b65a0d19de0863d588c600803cbc879a34"},
    {"repository": "Sian-Lee-SA/Home-Assistant-Switch-Manager", "default_branch": "master", "head": "4b600075fae2d7bab5673afbfd28df5a8ac77e6b"},
    {"repository": "SirGoodenough/HA_Blueprints", "default_branch": "master", "head": "abfe45f22ad06e11a8ca9bab302fb6e5ab3cf107"},
]

NONSEM_BP_META = {"name", "description", "author", "source_url"}
NONCONSEQUENTIAL_DOMAINS = {"notify", "persistent_notification", "logbook", "system_log"}
EXTERNAL_TRIGGER_TYPES = {"mqtt", "calendar", "webhook", "zone", "geo_location", "conversation"}
FAMILIES = [
    "ACTION_OPERATION",
    "TARGET_BINDING",
    "CONSEQUENTIAL_PARAMETER",
    "ACTION_NO_ACTION_CONTROL",
    "CAUSAL_GUARD",
]
ZERO_SHA = "0" * 40
JINJA_RE = re.compile(r"({{)|({%)")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(*parts: str) -> str:
    h = hashlib.sha256()
    for i, part in enumerate(parts):
        if i:
            h.update(b"\0")
        h.update(part.encode("utf-8"))
    return h.hexdigest()


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    return subprocess.run(cmd, cwd=cwd, env=env, check=check, text=text, capture_output=True)


def git(repo: Path, *args: str, check: bool = True) -> str:
    cp = run(["git", *args], cwd=repo, check=check)
    return cp.stdout


class TaggedSafeLoader(yaml.SafeLoader):
    pass


def _unknown_tag(loader: TaggedSafeLoader, tag_suffix: str, node: yaml.Node) -> Any:
    tag = node.tag
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node)
    else:
        value = None
    return {"__tag__": tag, "value": value}


TaggedSafeLoader.add_multi_constructor("", _unknown_tag)


def generic_parse(raw: str) -> dict[str, Any]:
    try:
        data = yaml.load(raw, Loader=TaggedSafeLoader)
        return {"ok": True, "data": data, "error": None}
    except Exception as e:
        return {"ok": False, "data": None, "error": f"{type(e).__name__}: {e}"}


def is_automation_blueprint(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("blueprint"), dict) and data["blueprint"].get("domain") == "automation"


def canonical(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): canonical(obj[k]) for k in sorted(obj, key=lambda x: str(x))}
    if isinstance(obj, list):
        return [canonical(x) for x in obj]
    if isinstance(obj, tuple):
        return [canonical(x) for x in obj]
    if isinstance(obj, set):
        return sorted(canonical(x) for x in obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def canonical_json(obj: Any) -> str:
    return json.dumps(canonical(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def semantic_document(data: Any) -> Any:
    obj = copy.deepcopy(data)
    if isinstance(obj, dict) and isinstance(obj.get("blueprint"), dict):
        for key in NONSEM_BP_META:
            obj["blueprint"].pop(key, None)
    return canonical(obj)


def key_first(d: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return default


def action_root(data: dict[str, Any]) -> Any:
    return key_first(data, ("actions", "action"), [])


def trigger_root(data: dict[str, Any]) -> Any:
    return key_first(data, ("triggers", "trigger"), [])


def condition_root(data: dict[str, Any]) -> Any:
    return key_first(data, ("conditions", "condition"), [])


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def is_static_service(value: Any) -> bool:
    return isinstance(value, str) and "." in value and not JINJA_RE.search(value)


def service_domain(value: str) -> str:
    return value.split(".", 1)[0]


def iter_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_dicts(v)


def collect_service_nodes(data: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = []
    for d in iter_dicts(action_root(data)):
        op = d.get("service", d.get("action"))
        if isinstance(op, str) or (isinstance(op, dict) and "__tag__" in op):
            nodes.append(d)
    return nodes


def operation_value(node: dict[str, Any]) -> Any:
    return node.get("service", node.get("action"))


def consequential_nodes(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for node in collect_service_nodes(data):
        op = operation_value(node)
        if not is_static_service(op):
            continue
        domain = service_domain(op)
        if domain in NONCONSEQUENTIAL_DOMAINS or domain == "script":
            continue
        out.append(node)
    return out


TARGET_KEYS = {"target", "entity_id", "device_id", "area_id"}
SERVICE_KEYS = {"service", "action"}
NONPARAM_KEYS = SERVICE_KEYS | TARGET_KEYS | {"alias", "enabled", "continue_on_error", "response_variable"}


def target_projection(node: dict[str, Any]) -> Any:
    out: dict[str, Any] = {}
    if "target" in node:
        out["target"] = node["target"]
    for k in ("entity_id", "device_id", "area_id"):
        if k in node:
            out[k] = node[k]
    data = node.get("data", node.get("data_template"))
    if isinstance(data, dict):
        targetish = {k: v for k, v in data.items() if k in TARGET_KEYS}
        if targetish:
            out["data_target"] = targetish
    return canonical(out)


def parameter_projection(node: dict[str, Any]) -> Any:
    out = {}
    for k, v in node.items():
        if k in NONPARAM_KEYS:
            continue
        if k in ("data", "data_template") and isinstance(v, dict):
            out[k] = {dk: dv for dk, dv in v.items() if dk not in TARGET_KEYS}
        else:
            out[k] = v
    return canonical(out)


def has_jinja(obj: Any) -> bool:
    if isinstance(obj, str):
        return bool(JINJA_RE.search(obj))
    if isinstance(obj, dict):
        return any(has_jinja(k) or has_jinja(v) for k, v in obj.items())
    if isinstance(obj, list):
        return any(has_jinja(v) for v in obj)
    return False


def consequential_runtime_template(data: dict[str, Any]) -> bool:
    for node in collect_service_nodes(data):
        op = operation_value(node)
        if isinstance(op, str) and is_static_service(op):
            domain = service_domain(op)
            if domain in NONCONSEQUENTIAL_DOMAINS or domain == "script":
                continue
            if has_jinja(target_projection(node)) or has_jinja(parameter_projection(node)):
                return True
        else:
            return True
    return False


def device_or_external_dependency(data: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for d in iter_dicts(data):
        typ = d.get("platform", d.get("trigger"))
        if isinstance(typ, str) and typ == "device":
            reasons.append("device_trigger_or_condition")
        cond = d.get("condition")
        if isinstance(cond, str) and cond == "device":
            reasons.append("device_condition")
        if "device_id" in d and "domain" in d and "type" in d and not isinstance(d.get("service", d.get("action")), str):
            reasons.append("device_action")
    for trig in as_list(trigger_root(data)):
        if isinstance(trig, dict):
            typ = trig.get("platform", trig.get("trigger"))
            if isinstance(typ, str) and typ in EXTERNAL_TRIGGER_TYPES:
                reasons.append(f"external_trigger:{typ}")
    return (bool(reasons), sorted(set(reasons)))


def guard_objects(data: dict[str, Any]) -> list[Any]:
    objs: list[Any] = []
    objs.extend(as_list(condition_root(data)))
    for d in iter_dicts(action_root(data)):
        for key in ("conditions", "condition", "if", "while", "until", "wait_template"):
            if key not in d:
                continue
            val = d[key]
            if key in ("if", "while", "until", "conditions", "condition"):
                objs.extend(as_list(val))
            else:
                objs.append(val)
        if "choose" in d:
            for choice in as_list(d["choose"]):
                if isinstance(choice, dict) and "conditions" in choice:
                    objs.extend(as_list(choice["conditions"]))
    dedup: dict[str, Any] = {}
    for obj in objs:
        dedup[canonical_json(obj)] = canonical(obj)
    return [dedup[k] for k in sorted(dedup)]


def trigger_alternatives(data: dict[str, Any]) -> int:
    return max(1, len(as_list(trigger_root(data))))


def static_domain_upper_bound(data_old: dict[str, Any], data_new: dict[str, Any]) -> tuple[int, int, int]:
    guards: dict[str, Any] = {}
    for data in (data_old, data_new):
        for g in guard_objects(data):
            guards[canonical_json(g)] = g
    k = len(guards)
    t = max(trigger_alternatives(data_old), trigger_alternatives(data_new))
    if k > 20:
        return (2**21, k, t)
    return (t * (2 ** k), k, t)


def service_projection(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for node in consequential_nodes(data):
        out.append({"operation": operation_value(node), "target": target_projection(node), "parameters": parameter_projection(node)})
    return out


def strip_call_payloads(obj: Any) -> Any:
    if isinstance(obj, list):
        return [strip_call_payloads(x) for x in obj]
    if not isinstance(obj, dict):
        return canonical(obj)
    d = {}
    op = obj.get("service", obj.get("action"))
    is_call = isinstance(op, str) and "." in op
    for k, v in obj.items():
        if is_call and (k in SERVICE_KEYS or k in TARGET_KEYS or k in ("data", "data_template")):
            if k in SERVICE_KEYS:
                d["__SERVICE_CALL__"] = True
            continue
        d[k] = strip_call_payloads(v)
    return canonical(d)


def guard_projection(data: dict[str, Any]) -> Any:
    return canonical({"trigger": trigger_root(data), "condition": condition_root(data), "nested_guards": guard_objects(data)})


def detected_families(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    fam: list[str] = []
    old_proj = service_projection(old)
    new_proj = service_projection(new)
    if [x["operation"] for x in old_proj] != [x["operation"] for x in new_proj]:
        fam.append("ACTION_OPERATION")
    if [x["target"] for x in old_proj] != [x["target"] for x in new_proj]:
        fam.append("TARGET_BINDING")
    if [x["parameters"] for x in old_proj] != [x["parameters"] for x in new_proj]:
        fam.append("CONSEQUENTIAL_PARAMETER")
    if canonical_json(strip_call_payloads(action_root(old))) != canonical_json(strip_call_payloads(action_root(new))):
        fam.append("ACTION_NO_ACTION_CONTROL")
    if canonical_json(guard_projection(old)) != canonical_json(guard_projection(new)):
        fam.append("CAUSAL_GUARD")
    return [f for f in FAMILIES if f in fam]


def pair_classification(old_parse: dict[str, Any], new_parse: dict[str, Any], old_native: dict[str, Any], new_native: dict[str, Any]) -> dict[str, Any]:
    old = old_parse["data"] if old_parse["ok"] else None
    new = new_parse["data"] if new_parse["ok"] else None
    base = {
        "classification": "EXCLUDE",
        "primary_reason": None,
        "change_families": [],
        "primary_family": None,
        "static_domain_upper_bound": None,
        "causal_predicate_count": None,
        "trigger_alternative_count": None,
        "dependency_flags": [],
    }
    if not (old_parse["ok"] and new_parse["ok"] and is_automation_blueprint(old) and is_automation_blueprint(new)):
        base["primary_reason"] = "EXCLUDE_NOT_BOTH_AUTOMATION_BLUEPRINTS"
        return base
    if not (old_native.get("ok") and new_native.get("ok")):
        base["primary_reason"] = "EXCLUDE_NATIVE_BLUEPRINT_PARSE_OR_COMMON_RUNTIME_FAILURE"
        base["native_errors"] = {"old": old_native.get("error"), "new": new_native.get("error")}
        return base
    if canonical_json(semantic_document(old)) == canonical_json(semantic_document(new)):
        base["primary_reason"] = "EXCLUDE_FORMATTING_METADATA_OR_NONCONSEQUENTIAL_HELPER_ONLY"
        return base
    old_conseq = consequential_nodes(old)
    new_conseq = consequential_nodes(new)
    if not old_conseq and not new_conseq:
        base["primary_reason"] = "EXCLUDE_NO_CONSEQUENTIAL_DEVICE_CONTROL_PATH"
        return base
    dep_old, dep_old_flags = device_or_external_dependency(old)
    dep_new, dep_new_flags = device_or_external_dependency(new)
    base["dependency_flags"] = sorted(set(dep_old_flags + dep_new_flags))
    if dep_old or dep_new:
        base["primary_reason"] = "EXCLUDE_REQUIRED_EXTERNAL_OR_DEVICE_PLATFORM_DEPENDENCY"
        return base
    ub, k, t = static_domain_upper_bound(old, new)
    base["static_domain_upper_bound"] = ub
    base["causal_predicate_count"] = k
    base["trigger_alternative_count"] = t
    if consequential_runtime_template(old) or consequential_runtime_template(new) or ub > 32:
        base["primary_reason"] = "EXCLUDE_UNBOUNDED_OR_STATE_CAP_EXCEEDS_32"
        return base
    fam = detected_families(old, new)
    base["change_families"] = fam
    if not fam:
        base["primary_reason"] = "EXCLUDE_STRUCTURAL_CHANGE_CANNOT_AFFECT_CLAIM"
        return base
    primary = fam[0]
    base["classification"] = "INCLUDE"
    base["primary_family"] = primary
    base["primary_reason"] = f"INCLUDE_{primary}"
    return base


def parse_raw_diff(raw: str) -> list[dict[str, Any]]:
    out = []
    for line in raw.splitlines():
        if not line.startswith(":"):
            continue
        parts = line.split("\t")
        meta = parts[0].split()
        if len(meta) < 5:
            continue
        old_mode = meta[0][1:]
        new_mode = meta[1]
        old_blob = meta[2]
        new_blob = meta[3]
        status = meta[4]
        if status.startswith("R") or status.startswith("C"):
            if len(parts) < 3:
                continue
            old_path, new_path = parts[1], parts[2]
        else:
            if len(parts) < 2:
                continue
            old_path = new_path = parts[1]
        if not (old_path.lower().endswith((".yaml", ".yml")) or new_path.lower().endswith((".yaml", ".yml"))):
            continue
        out.append({
            "status": status,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "old_blob": None if old_blob == ZERO_SHA else old_blob,
            "new_blob": None if new_blob == ZERO_SHA else new_blob,
            "old_path": old_path,
            "new_path": new_path,
        })
    return out


def cat_blob(repo: Path, sha: str, cache: dict[str, str]) -> str:
    if sha in cache:
        return cache[sha]
    cp = run(["git", "cat-file", "blob", sha], cwd=repo, text=False)
    raw = cp.stdout
    rawb = raw.encode() if isinstance(raw, str) else raw
    text = rawb.decode("utf-8", errors="replace")
    cache[sha] = text
    return text


def clone_repo(spec: dict[str, str], root: Path) -> Path:
    safe = spec["repository"].replace("/", "__")
    dest = root / safe
    url = f"https://github.com/{spec['repository']}.git"
    cp = run(["git", "clone", "--filter=blob:none", "--no-tags", "--no-checkout", "--single-branch", "--branch", spec["default_branch"], url, str(dest)], check=False)
    if cp.returncode != 0:
        raise RuntimeError(f"clone failed {spec['repository']}: {cp.stderr}")
    chk = run(["git", "cat-file", "-e", f"{spec['head']}^{{commit}}"], cwd=dest, check=False)
    if chk.returncode != 0:
        fetch = run(["git", "fetch", "--no-tags", "origin", spec["head"]], cwd=dest, check=False)
        if fetch.returncode != 0:
            raise RuntimeError(f"frozen head unavailable {spec['repository']} {spec['head']}: {fetch.stderr}")
    actual = git(dest, "rev-parse", spec["head"]).strip()
    if actual != spec["head"]:
        raise RuntimeError(f"head mismatch {spec['repository']}: {actual}")
    return dest


def enumerate_repo(spec: dict[str, str], repo: Path, stage_root: Path) -> dict[str, Any]:
    head = spec["head"]
    commits = [x for x in git(repo, "rev-list", "--first-parent", "--reverse", head).splitlines() if x]
    all_commit_count = int(git(repo, "rev-list", "--count", head).strip())
    blob_cache: dict[str, str] = {}
    parse_cache: dict[str, dict[str, Any]] = {}
    lineages: dict[int, dict[str, Any]] = {}
    path_to_lineage: dict[str, int] = {}
    next_lid = 1
    all_mainline_blobs: set[str] = set()

    def ensure_lineage(path: str, blob: str | None) -> int:
        nonlocal next_lid
        if path in path_to_lineage:
            return path_to_lineage[path]
        lid = next_lid
        next_lid += 1
        lineages[lid] = {"_internal_id": lid, "earliest_path": path, "earliest_blob": blob, "paths": [path], "events": [], "blobs": []}
        path_to_lineage[path] = lid
        return lid

    def add_blob(lid: int, sha: str | None):
        if sha and sha not in lineages[lid]["blobs"]:
            lineages[lid]["blobs"].append(sha)
            all_mainline_blobs.add(sha)

    if commits:
        root_commit = commits[0]
        root_raw = git(repo, "diff-tree", "--root", "-r", "-M60%", "--raw", root_commit)
        for ch in parse_raw_diff(root_raw):
            if ch["new_blob"] is None:
                continue
            lid = ensure_lineage(ch["new_path"], ch["new_blob"])
            add_blob(lid, ch["new_blob"])
            lineages[lid]["events"].append({"commit": root_commit, "kind": "CREATION", **ch})

    for parent, child in zip(commits, commits[1:]):
        raw = git(repo, "diff-tree", "-r", "-M60%", "--raw", parent, child)
        for ch in parse_raw_diff(raw):
            st = ch["status"]
            old_path, new_path = ch["old_path"], ch["new_path"]
            old_blob, new_blob = ch["old_blob"], ch["new_blob"]
            if st.startswith("R"):
                lid = path_to_lineage.get(old_path)
                if lid is None:
                    lid = ensure_lineage(old_path, old_blob)
                path_to_lineage.pop(old_path, None)
                path_to_lineage[new_path] = lid
                if new_path not in lineages[lid]["paths"]:
                    lineages[lid]["paths"].append(new_path)
                add_blob(lid, old_blob)
                add_blob(lid, new_blob)
                kind = "RENAME_CONTENT_CHANGE" if old_blob and new_blob and old_blob != new_blob else "RENAME_ONLY"
            elif st.startswith("D"):
                lid = path_to_lineage.get(old_path)
                if lid is None:
                    lid = ensure_lineage(old_path, old_blob)
                add_blob(lid, old_blob)
                path_to_lineage.pop(old_path, None)
                kind = "DELETION"
            elif st.startswith("A"):
                lid = ensure_lineage(new_path, new_blob)
                add_blob(lid, new_blob)
                kind = "CREATION"
            else:
                lid = path_to_lineage.get(new_path)
                if lid is None:
                    lid = ensure_lineage(new_path, old_blob or new_blob)
                add_blob(lid, old_blob)
                add_blob(lid, new_blob)
                kind = "CONTENT_CHANGE" if old_blob and new_blob and old_blob != new_blob else "NONPAIR_CHANGE"
            lineages[lid]["events"].append({"commit": child, "parent": parent, "kind": kind, **ch})

    for lid, lin in lineages.items():
        for sha in lin["blobs"]:
            if sha not in parse_cache:
                parse_cache[sha] = generic_parse(cat_blob(repo, sha, blob_cache))
        lin["candidate_automation_blueprint"] = any(parse_cache[sha]["ok"] and is_automation_blueprint(parse_cache[sha]["data"]) for sha in lin["blobs"])

    candidates = {lid: lin for lid, lin in lineages.items() if lin["candidate_automation_blueprint"]}

    dag_raw = git(repo, "log", "--raw", "-M60%", "--format=__COMMIT__%H", head, "--", "*.yaml", "*.yml")
    dag_blob_set: set[str] = set()
    for ch in parse_raw_diff(dag_raw):
        if ch["old_blob"]:
            dag_blob_set.add(ch["old_blob"])
        if ch["new_blob"]:
            dag_blob_set.add(ch["new_blob"])
    off_mainline = sorted(dag_blob_set - all_mainline_blobs)
    off_mainline_auto: list[str] = []
    for sha in off_mainline:
        try:
            p = generic_parse(cat_blob(repo, sha, blob_cache))
        except Exception:
            continue
        if p["ok"] and is_automation_blueprint(p["data"]):
            off_mainline_auto.append(sha)

    repo_key = spec["repository"].replace("/", "__")
    stage_dir = stage_root / "blobs"
    stage_dir.mkdir(parents=True, exist_ok=True)
    for lin in candidates.values():
        for sha in lin["blobs"]:
            key = f"{repo_key}__{sha}"
            out_path = stage_dir / f"{key}.yaml"
            if not out_path.exists():
                out_path.write_text(cat_blob(repo, sha, blob_cache), encoding="utf-8")

    pair_records = []
    event_records = []
    for lid, lin in sorted(candidates.items()):
        earliest_blob = lin["earliest_blob"] or (lin["blobs"][0] if lin["blobs"] else "")
        stable_lineage_id = sha256_text(spec["repository"], lin["earliest_path"], earliest_blob)
        for ev in lin["events"]:
            rec = {
                "lineage_id": stable_lineage_id,
                "commit": ev["commit"],
                "parent": ev.get("parent"),
                "kind": ev["kind"],
                "status": ev["status"],
                "old_path": ev["old_path"],
                "new_path": ev["new_path"],
                "old_blob": ev["old_blob"],
                "new_blob": ev["new_blob"],
            }
            event_records.append(rec)
            if ev["old_blob"] and ev["new_blob"] and ev["old_blob"] != ev["new_blob"]:
                pair_records.append({
                    "pair_id": sha256_text(spec["repository"], stable_lineage_id, ev["old_blob"], ev["new_blob"]),
                    "lineage_id": stable_lineage_id,
                    "commit": ev["commit"],
                    "parent": ev.get("parent"),
                    "old_path": ev["old_path"],
                    "new_path": ev["new_path"],
                    "old_blob": ev["old_blob"],
                    "new_blob": ev["new_blob"],
                })

    lineage_records = []
    for _, lin in sorted(candidates.items()):
        earliest_blob = lin["earliest_blob"] or (lin["blobs"][0] if lin["blobs"] else "")
        lineage_records.append({
            "lineage_id": sha256_text(spec["repository"], lin["earliest_path"], earliest_blob),
            "earliest_path": lin["earliest_path"],
            "paths": lin["paths"],
            "blob_count": len(lin["blobs"]),
            "event_count": len(lin["events"]),
        })

    return {
        "repository": spec["repository"],
        "default_branch": spec["default_branch"],
        "frozen_head": head,
        "first_parent_commit_count": len(commits),
        "reachable_commit_count": all_commit_count,
        "candidate_lineages": lineage_records,
        "events": event_records,
        "pairs": pair_records,
        "_parse_cache": parse_cache,
        "dag_coverage_audit": {
            "all_ancestry_yaml_blob_count": len(dag_blob_set),
            "mainline_yaml_blob_count": len(all_mainline_blobs),
            "off_mainline_only_yaml_blob_count": len(off_mainline),
            "off_mainline_only_automation_blueprint_blob_count": len(off_mainline_auto),
            "off_mainline_only_automation_blueprint_blob_sha256": sha256_bytes(("\n".join(off_mainline_auto) + ("\n" if off_mainline_auto else "")).encode()),
        },
    }


def run_native_validator(stage_root: Path, validator_path: Path) -> dict[str, Any]:
    manifest = []
    seen = set()
    for p in sorted((stage_root / "blobs").glob("*.yaml")):
        key = p.stem
        if key in seen:
            continue
        seen.add(key)
        manifest.append({"key": key, "relative_path": f"blobs/{p.name}"})
    manifest_path = stage_root / "native_manifest.json"
    result_path = stage_root / "native_results.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    pull = run(["docker", "pull", HA_IMAGE], check=False)
    if pull.returncode != 0:
        raise RuntimeError(f"docker pull failed: {pull.stderr}")
    cp = run([
        "docker", "run", "--rm",
        "-v", f"{stage_root.resolve()}:/work",
        "-v", f"{validator_path.resolve()}:/validator.py:ro",
        HA_IMAGE,
        "python", "/validator.py", "/work/native_manifest.json", "/work/native_results.json",
    ], check=False)
    if cp.returncode != 0:
        raise RuntimeError(f"native validator container failed: {cp.stderr}\n{cp.stdout}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def aggregate_and_classify(repo_results: list[dict[str, Any]], native: dict[str, Any]) -> dict[str, Any]:
    included = 0
    included_repos: set[str] = set()
    primary_families: set[str] = set()
    reason_counts = Counter()
    family_counts = Counter()
    repo_summaries = []
    for rr in repo_results:
        repo_key = rr["repository"].replace("/", "__")
        parse_cache = rr.pop("_parse_cache")
        for pair in rr["pairs"]:
            old_sha, new_sha = pair["old_blob"], pair["new_blob"]
            old_n = native.get(f"{repo_key}__{old_sha}", {"ok": False, "error": "missing native validation"})
            new_n = native.get(f"{repo_key}__{new_sha}", {"ok": False, "error": "missing native validation"})
            cls = pair_classification(parse_cache[old_sha], parse_cache[new_sha], old_n, new_n)
            pair.update({
                **cls,
                "native_parser": {
                    "old": {"ok": bool(old_n.get("ok")), "error": old_n.get("error")},
                    "new": {"ok": bool(new_n.get("ok")), "error": new_n.get("error")},
                },
            })
            reason_counts[pair["primary_reason"]] += 1
            for f in pair["change_families"]:
                family_counts[f] += 1
            if pair["classification"] == "INCLUDE":
                included += 1
                included_repos.add(rr["repository"])
                if pair["primary_family"]:
                    primary_families.add(pair["primary_family"])
        repo_includes = sum(1 for p in rr["pairs"] if p["classification"] == "INCLUDE")
        repo_summaries.append({
            "repository": rr["repository"],
            "candidate_lineage_count": len(rr["candidate_lineages"]),
            "adjacent_content_changing_pair_count": len(rr["pairs"]),
            "include_count": repo_includes,
            "exclude_count": len(rr["pairs"]) - repo_includes,
        })
    go = included >= 6 and len(included_repos) >= 3 and len(primary_families) >= 3
    return {
        "schema": "replaymark.ve3.upstream-census.v1",
        "status": "GATE_2_GO_TO_PRE_SCIENCE_QUALIFICATION" if go else "VE3_STOPPED_PRE_SCIENCE",
        "authority_role": "EXHAUSTIVE_ADJACENT_VERSION_CENSUS",
        "lineage": {
            "constitution_commit": CONSTITUTION_COMMIT,
            "gate_1_repository_universe_commit": GATE1_COMMIT,
            "gate_2_census_protocol_commit": PROTOCOL_COMMIT,
        },
        "method_firewall": {
            "native_old_or_new_action_execution": False,
            "old_new_projected_output_comparison": False,
            "compatibility_frontier_computed": False,
            "replaymark_executed": False,
            "replay_all_executed": False,
            "target_semantic_snapshot_built": False,
            "target_attestation_run": False,
            "scientific_cells": 0,
        },
        "gate_2_decision": {
            "included_transition_count": included,
            "distinct_repositories_with_included_transition": len(included_repos),
            "distinct_primary_change_families": len(primary_families),
            "included_repositories": sorted(included_repos),
            "primary_change_families": sorted(primary_families),
            "requirements": {
                "included_transitions_at_least": 6,
                "distinct_repositories_at_least": 3,
                "distinct_primary_change_families_at_least": 3,
            },
            "go": go,
            "on_fail": "VE3_STOPPED_PRE_SCIENCE; no substitution; return immediately to manuscript v81 integration.",
        },
        "aggregate": {
            "repository_summaries": repo_summaries,
            "classification_reason_counts": dict(sorted(reason_counts.items())),
            "change_family_tag_counts": dict(sorted(family_counts.items())),
            "total_candidate_lineages": sum(len(r["candidate_lineages"]) for r in repo_results),
            "total_adjacent_content_changing_pairs": sum(len(r["pairs"]) for r in repo_results),
        },
        "repositories": repo_results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--validator", required=True)
    ap.add_argument("--work-root", default=None)
    args = ap.parse_args()
    root = Path(args.work_root) if args.work_root else Path(tempfile.mkdtemp(prefix="ve3-census-"))
    root.mkdir(parents=True, exist_ok=True)
    stage_root = root / "native-stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    repos_root = root / "repos"
    repos_root.mkdir(parents=True, exist_ok=True)
    repo_results = []
    clone_receipts = []
    for spec in REPOS:
        repo = clone_repo(spec, repos_root)
        actual_head = git(repo, "rev-parse", spec["head"]).strip()
        clone_receipts.append({"repository": spec["repository"], "frozen_head": spec["head"], "verified_head": actual_head, "head_match": actual_head == spec["head"]})
        repo_results.append(enumerate_repo(spec, repo, stage_root))
    native = run_native_validator(stage_root, Path(args.validator))
    census = aggregate_and_classify(repo_results, native)
    census["source_receipts"] = {
        "frozen_repository_heads": clone_receipts,
        "native_validator_image": HA_IMAGE,
        "native_validator_result_count": len(native),
    }
    out_bytes = (json.dumps(census, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out_bytes)
    print(json.dumps({
        "status": census["status"],
        "go": census["gate_2_decision"]["go"],
        "included_transition_count": census["gate_2_decision"]["included_transition_count"],
        "distinct_repositories": census["gate_2_decision"]["distinct_repositories_with_included_transition"],
        "distinct_primary_families": census["gate_2_decision"]["distinct_primary_change_families"],
        "total_pairs": census["aggregate"]["total_adjacent_content_changing_pairs"],
        "sha256": sha256_bytes(out_bytes),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
