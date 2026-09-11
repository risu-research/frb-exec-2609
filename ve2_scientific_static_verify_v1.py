from __future__ import annotations

"""Static proof obligations for the frozen VE2 scientific authority source.

This verifier does not execute scientific cells or import answer-bearing semantic
models. It inspects Python AST/source and the candidate workflow as text.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SCIENCE_WORKFLOW = ".github/workflows/ve2-authoritative-first-complete-v1.yml"
EXPECTED_STAGE_ORDER = [
    "T01_R0_OLD_HISTORY", "T01_R1_OLD_HISTORY",
    "T01_R0_NEW_DIRECT", "T01_R1_NEW_DIRECT",
    "T01_R0_REPLAYMARK", "T01_R1_REPLAYMARK",
    "T01_R0_REPLAY_ALL", "T01_R1_REPLAY_ALL",
    "T02_R0_OLD_HISTORY", "T02_R1_OLD_HISTORY",
    "T02_R0_NEW_DIRECT", "T02_R1_NEW_DIRECT",
    "T02_R0_REPLAYMARK", "T02_R1_REPLAYMARK",
    "T02_R0_REPLAY_ALL", "T02_R1_REPLAY_ALL",
]
RESULT_WORKERS = [
    "ve2_scientific_native_execution_v1.py",
    "ve2_scientific_native_execution_v2.py",
    "ve2_scientific_contract_runtime_v1.py",
    "ve2_scientific_independent_validate_v1.py",
    "ve2_scientific_raw_seal_v1.py",
]
FORBIDDEN_WORKER_IMPORTS = {
    "ve2_transition_semantics_v1",
    "ve2_scientific_postrun_adjudicate_v1",
    "ve2_scientific_postrun_adjudicate_v2",
    "ve2_scientific_postrun_adjudicate_v3",
}
FORBIDDEN_WORKER_STRING_LITERALS = {
    "VE2_T01_EXPECTED_FRONTIER_V1.json",
    "VE2_T02_EXPECTED_FRONTIER_V1.json",
    "RETIRED_BY_UPDATE",
    "COMPATIBLE_ACROSS_VERSION",
    "weight_in_144_state_superspace",
    "old_causal_path",
    "new_causal_path",
}
EXACT_IMAGES = {
    "ghcr.io/home-assistant/home-assistant@sha256:92a8fe2ba3ffa0217776dd44687a2f477dc6342e7135766e9599ad8952e3914e",
    "ghcr.io/home-assistant/home-assistant@sha256:97d63b3d0028b6b52ad8e5ac7b014c3404e69bf1656b5489eec48b59184e0bc7",
    "ghcr.io/home-assistant/home-assistant@sha256:372d991e58882a1d8c68c07e9aa3f3b509276e695355f73ccdb03baa70407293",
}


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module_imports(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def string_constants(tree: ast.AST) -> set[str]:
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def verify_worker(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imports = module_imports(tree)
    bad_imports = sorted(name for name in imports if name in FORBIDDEN_WORKER_IMPORTS)
    if bad_imports:
        raise AssertionError((path.name, "forbidden-worker-import", bad_imports))
    constants = string_constants(tree)
    bad_literals = sorted(FORBIDDEN_WORKER_STRING_LITERALS & constants)
    if bad_literals:
        raise AssertionError((path.name, "answer-bearing-worker-literal", bad_literals))
    if path.name == "ve2_scientific_contract_runtime_v1.py" and "compile_explicit_contract" in source:
        raise AssertionError("runtime-contract-recompile-surface")
    return {
        "path": str(path),
        "sha256": file_sha(path),
        "imports": sorted(imports),
        "answer_bearing_imports": 0,
        "answer_bearing_exact_literals": 0,
    }


def verify_native_v2(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    defs = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if defs != ["_load_history_v2"]:
        raise AssertionError(("native-v2-scope", defs))
    if "base._load_history = _load_history_v2" not in source or "base.main()" not in source:
        raise AssertionError("native-v2-delegation")
    for forbidden in ("_source_row", "_replay_row", "_stimulate_source", "_dispatch_behavior"):
        if f"def {forbidden}" in source or f"async def {forbidden}" in source:
            raise AssertionError(("native-v2-semantic-duplication", forbidden))


def verify_postrun_v3(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = module_imports(tree)
    if "ve2_scientific_postrun_adjudicate_v1" not in imports:
        raise AssertionError("postrun-v3-does-not-delegate-frozen-semantics")
    required = [
        "SCIENTIFIC_CELLS = 352",
        "RAW_STAGE_ARTIFACTS = 16",
        "def git_blob_sha",
        "git_blob_sha(t01_path) == base.T01_FRONTIER_SHA",
        "git_blob_sha(t02_path) == base.T02_FRONTIER_SHA",
    ]
    for value in required:
        if value not in source:
            raise AssertionError(("postrun-v3-required-proof", value))
    return {"path": str(path), "sha256": file_sha(path)}


def verify_workflow(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if "workflow_dispatch" in text:
        raise AssertionError("science-workflow-manual-dispatch-forbidden")
    if "- ve2-scientific-authority-v1" not in text:
        raise AssertionError("science-workflow-trigger-branch")
    if "contents: read" not in text or "contents: write" in text:
        raise AssertionError("science-workflow-content-permission")
    if "matrix:" in text or "strategy:" in text:
        raise AssertionError("science-workflow-parallel-matrix")
    if "cancel-in-progress: false" not in text:
        raise AssertionError("science-workflow-concurrency")
    for image in EXACT_IMAGES:
        if image not in text:
            raise AssertionError(("science-workflow-image-pin", image))
    for action_pin in (
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ):
        if action_pin not in text:
            raise AssertionError(("science-workflow-action-pin", action_pin))
    if text.count("docker run --rm --network none") != 1:
        raise AssertionError("science-worker-network-none")
    for whole_mount in ('-v "$PWD:/work', '-v "$PWD:/input', '-v "$PWD:/results'):
        if whole_mount in text:
            raise AssertionError(("whole-repository-or-root-mount", whole_mount))
    calls = re.findall(r"^\s*run_stage\s+(T0[12]_R[01]_(?:OLD_HISTORY|NEW_DIRECT|REPLAYMARK|REPLAY_ALL))\b", text, flags=re.MULTILINE)
    if calls != EXPECTED_STAGE_ORDER:
        raise AssertionError(("science-stage-order", calls))
    if text.count("run_stage T01_") != 8 or text.count("run_stage T02_") != 8:
        raise AssertionError("science-stage-count")
    raw_marker = "- name: Seal all raw stage artifacts before frontier access"
    post_marker = "- name: Independent post-run adjudication after complete raw seal only"
    if raw_marker not in text or post_marker not in text or text.index(raw_marker) >= text.index(post_marker):
        raise AssertionError("raw-seal-before-postrun-order")
    before_post = text[:text.index(post_marker)]
    after_post = text[text.index(post_marker):]
    for frontier in ("VE2_T01_EXPECTED_FRONTIER_V1.json", "VE2_T02_EXPECTED_FRONTIER_V1.json"):
        if frontier in before_post:
            raise AssertionError(("frontier-visible-before-raw-seal", frontier))
        if frontier not in after_post:
            raise AssertionError(("frontier-missing-postrun", frontier))
    if "ve2_transition_semantics_v1.py" in before_post:
        raise AssertionError("transition-semantics-visible-before-postrun")
    replaymark_lines = [line for line in text.splitlines() if re.search(r"run_stage T0[12]_R[01]_REPLAYMARK", line)]
    if len(replaymark_lines) != 4:
        raise AssertionError("replaymark-call-count")
    for line in replaymark_lines:
        if "NEW_DIRECT" in line or "NEW_BP" in line:
            raise AssertionError(("replaymark-new-direct-visibility", line))
        if "OLD_HISTORY_REPORT.json" not in line:
            raise AssertionError(("replaymark-history-handoff", line))
    if "ve2_scientific_raw_seal_v1.py" not in before_post:
        raise AssertionError("raw-seal-builder-missing")
    if "ve2_scientific_postrun_adjudicate_v3.py" not in after_post:
        raise AssertionError("selected-postrun-v3-missing")
    if "test \"$GITHUB_RUN_ATTEMPT\" = '1'" not in text:
        raise AssertionError("run-attempt-one-gate")
    if "VE2_SCIENTIFIC_STATIC_PASS_SEAL_V1.json" not in text or "VE2_SCIENTIFIC_AUTHORITY_OPEN_V1.json" not in text:
        raise AssertionError("science-open-lineage-gate")
    top_jobs = re.findall(r"^  ([A-Za-z0-9_-]+):\n    runs-on:", text, flags=re.MULTILINE)
    if top_jobs != ["authoritative-first-complete"]:
        raise AssertionError(("science-job-cardinality", top_jobs))
    return {
        "path": str(path),
        "sha256": file_sha(path),
        "serial_stage_calls": calls,
        "job_count": 1,
        "worker_network": "none",
        "worker_expected_frontier_mounts": 0,
        "worker_transition_semantics_mounts": 0,
        "replaymark_new_direct_output_mounts": 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-freeze", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    workers = [verify_worker(Path(name)) for name in RESULT_WORKERS]
    verify_native_v2(Path("ve2_scientific_native_execution_v2.py"))
    postrun = verify_postrun_v3(Path("ve2_scientific_postrun_adjudicate_v3.py"))
    workflow = verify_workflow(Path(SCIENCE_WORKFLOW))
    contract = json.loads(Path("VE2_SCIENTIFIC_STATIC_QUALIFICATION_CONTRACT_V1.json").read_bytes())
    if contract.get("status") != "FROZEN_PRE_SCIENCE" or contract.get("static_requirements", {}).get("scientific_cells_when_eventually_run") != 352:
        raise AssertionError("static-contract-identity")
    remediation = json.loads(Path("VE2_SCIENTIFIC_PREOPEN_REMEDIATION_HISTORY_V1.json").read_bytes())
    if remediation.get("status") != "FROZEN_BEFORE_SCIENTIFIC_OPEN":
        raise AssertionError("remediation-history-identity")
    result = {
        "schema": "replaymark.ve2.scientific-static-source-validation.v1",
        "status": "PASS",
        "source_freeze": args.source_freeze,
        "result_workers": workers,
        "postrun_selected": postrun,
        "science_workflow": workflow,
        "scientific_exposure": {
            "scientific_result_opened": False,
            "scientific_cells": 0,
            "frontier_result_seen": False,
        },
    }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    result["validation_sha256"] = hashlib.sha256(canonical).hexdigest()
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "validation_sha256": result["validation_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
