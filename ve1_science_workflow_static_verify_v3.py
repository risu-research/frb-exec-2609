from __future__ import annotations

"""Pre-scientific static qualification for VE1 process-isolated transport v3."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

WORKFLOW = Path(".github/workflows/ve1-authoritative-first-complete-v3.yml")
QUALIFICATION_WORKFLOW = Path(".github/workflows/ve1-science-transport-qualification-v3.yml")
TRANSPORT = Path("ve1_stage_transport_v3.py")
REMEDIATION = Path("VE1_POST_OPEN_REMEDIATION_V3.json")
V2_SEAL = Path("VE1_POST_OPEN_INFRASTRUCTURE_INCOMPLETE_SEAL_V2.json")
PRODUCER = Path("ve1_native_execution.py")
VALIDATOR = Path("ve1_independent_validate.py")
ADJUDICATOR = Path("ve1_postrun_adjudicate.py")
STATE = Path("VE1_EXECUTION_STATE_MANIFEST_V1_MIRROR.json")

BASE = "e02008a518408fae8a2a85b8d67d7cd81c18eb62"
PRIVATE = "7c53b5bdc70b600156380877a406b5988d35125a"
V2_SEAL_SHA256 = "055df628df72df5aeb2523f0166a6dfbb186c9656efd3802ac6f60b76f887ecb"
EXPECTED_BLOBS = {
    STATE: "3e09ced267657616f045f9e34e194d49f8cdfbfc",
    PRODUCER: "40e76789335eed7d15c9a2523717d7d7bcf185fd",
    VALIDATOR: "3e0ff68988e25ab2c6fe1f90c49c289b68c9fe36",
    ADJUDICATOR: "1c6ce57de123a3a35ec45f316b21938152b09d4d",
}
ALLOWED_SOURCE_DELTA = [
    ".github/workflows/ve1-authoritative-first-complete-v3.yml",
    ".github/workflows/ve1-science-transport-qualification-v3.yml",
    "VE1_POST_OPEN_REMEDIATION_V3.json",
    "ve1_science_workflow_static_verify_v3.py",
    "ve1_stage_transport_v3.py",
]
FORBIDDEN_ANSWER_TOKENS = [
    "VE1_EXPECTED_CROSS_VERSION_TABLE_V2",
    "0ef80acf64bcc192837ee17f6b57ab2e79ee4182c9b793d8cf388d59d2558c20",
    "COMPATIBLE_ACROSS_VERSION",
    "RETIRED_BY_UPDATE",
    "old_expected_action",
    "new_expected_action",
    "expected_counts",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def extract_run_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        match = re.match(r"^(\s*)run:\s*\|\s*$", lines[i])
        if not match:
            i += 1
            continue
        base = len(match.group(1))
        i += 1
        raw: list[str] = []
        while i < len(lines):
            line = lines[i]
            if line.strip() and len(line) - len(line.lstrip(" ")) <= base:
                break
            raw.append(line)
            i += 1
        nonblank = [len(x) - len(x.lstrip(" ")) for x in raw if x.strip()]
        assert nonblank, "empty run block"
        cut = min(nonblank)
        blocks.append("\n".join(x[cut:] if x.strip() else "" for x in raw) + "\n")
    return blocks


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.add(node.module or "")
    return out


def assert_no_shell_true(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_run = isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "subprocess" and func.attr == "run"
        if not is_run:
            continue
        for keyword in node.keywords:
            if keyword.arg == "shell":
                assert not (isinstance(keyword.value, ast.Constant) and keyword.value.value is True), "subprocess shell=True forbidden"


def verify() -> dict[str, Any]:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    qualification_workflow = QUALIFICATION_WORKFLOW.read_text(encoding="utf-8")
    transport = TRANSPORT.read_text(encoding="utf-8")
    remediation = json.loads(REMEDIATION.read_text(encoding="utf-8"))
    v2 = json.loads(V2_SEAL.read_text(encoding="utf-8"))

    assert sha256(V2_SEAL) == V2_SEAL_SHA256
    assert v2["classification"] == "POST_OPEN_INFRASTRUCTURE_INCOMPLETE"
    assert v2["scientific_open_event_occurred"] is True
    assert v2["promotion"] is False
    assert v2["rerun_same_authority_authorized"] is False
    assert v2["scientific_result_reuse_authorized"] is False
    assert v2["fresh_successor_required"] is True
    assert v2["workflow_run_id"] == 34467293478

    assert workflow.splitlines()[0].endswith("first complete v3")
    assert "ve1-authoritative-first-complete-v3" in workflow
    assert "VE1_SCIENTIFIC_AUTHORITY_OPEN_V3.json" in workflow
    assert "VE1_TRANSPORT_QUALIFICATION_PASS_V3.json" in workflow
    assert "fetch-depth: 0" in workflow
    assert "GITHUB_RUN_ATTEMPT" in workflow
    assert "fail-fast: false" in workflow
    assert "replica: [0, 1]" in workflow
    assert "docker run" not in workflow, "scientific workflow must delegate Docker execution to isolated transport process"
    assert "run_stage ()" not in workflow
    assert "old_report=" not in workflow
    assert "chmod -R" not in workflow
    assert workflow.count("ve1_stage_transport_v3.py run-stage") == 4
    assert workflow.count("--old-history \"$SEALED_OLD_REPORT\"") == 2
    assert workflow.count("--old-history-sha256 \"$SEALED_OLD_DIGEST\"") == 2
    assert 'readonly SEALED_OLD_REPORT=' in workflow
    assert "readonly SEALED_OLD_DIGEST" in workflow
    assert workflow.count("current_old_digest=") == 3
    positions = [
        workflow.index("--stage old_history"),
        workflow.index("--stage new_direct"),
        workflow.index("--stage replaymark"),
        workflow.index("--stage replay_all"),
    ]
    assert positions == sorted(positions)
    assert "ve1-first-complete-v3-r" in workflow
    assert "ve1-first-complete-aggregate-v3" in workflow

    assert qualification_workflow.splitlines()[0] == "name: VE1 pre-scientific transport qualification v3"
    assert "ve1-transport-qualification-v3" in qualification_workflow
    assert "VE1_TRANSPORT_QUALIFICATION_OPEN_V3.json" in qualification_workflow
    assert "ve1_stage_transport_v3.py qualify" in qualification_workflow
    assert "result_bearing_controller_invocations" in qualification_workflow

    assert "<<" not in workflow
    assert "<<" not in qualification_workflow
    workflow_blocks = extract_run_blocks(workflow)
    qualification_blocks = extract_run_blocks(qualification_workflow)
    assert len(workflow_blocks) >= 10
    assert len(qualification_blocks) >= 5
    for family, blocks in (("science", workflow_blocks), ("qualification", qualification_blocks)):
        for index, block in enumerate(blocks):
            result = subprocess.run(["bash", "-n"], input=block, text=True, capture_output=True)
            assert result.returncode == 0, (family, index, result.stderr)

    for token in FORBIDDEN_ANSWER_TOKENS:
        for text in (workflow, qualification_workflow, transport, REMEDIATION.read_text(encoding="utf-8")):
            assert token not in text, token

    for path in (TRANSPORT, PRODUCER, VALIDATOR, ADJUDICATOR, Path(__file__)):
        ast.parse(path.read_text(encoding="utf-8"))
    allowed_imports = {
        "__future__", "argparse", "hashlib", "json", "os", "pathlib", "shutil", "stat", "subprocess", "sys", "typing"
    }
    assert imports(TRANSPORT) <= allowed_imports, imports(TRANSPORT) - allowed_imports
    assert_no_shell_true(TRANSPORT)
    transport_tree = ast.parse(transport)
    forbidden_dynamic_calls = {"__import__", "eval", "exec", "compile"}
    for node in ast.walk(transport_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden_dynamic_calls, node.func.id
    assert "importlib" not in imports(TRANSPORT)
    assert "target_preset" not in transport
    assert "compatibility" not in transport
    assert "f\"{report}:/results/REPORT.json\"" in transport
    assert "f\"{history.resolve()}:/sealed-old/REPORT.json:ro\"" in transport
    assert "_prepare_host_report(report)" in transport
    assert "_seal_host_report(report, owner)" in transport
    assert "assert _mode(history) == 0o444" in transport
    assert "_assert_digest(history, history_digest" in transport

    for path, expected in EXPECTED_BLOBS.items():
        assert git("hash-object", "--no-filters", str(path)) == expected, path

    assert remediation["schema"] == "replaymark.ve1.post-open-remediation.v3"
    assert remediation["status"] == "FROZEN_POST_OPEN_REMEDIATION"
    assert remediation["authority"] == "POST_OPEN_INFRASTRUCTURE_INCOMPLETE_SUCCESSOR"
    assert remediation["scientific_result_opened"] is False
    assert remediation["scientific_cells"] == 0
    assert remediation["private_constitution_head"] == PRIVATE
    assert remediation["v2_authority"]["forensic_seal_head"] == BASE
    assert remediation["v2_authority"]["forensic_seal_sha256"] == V2_SEAL_SHA256
    assert remediation["v2_authority"]["workflow_run_id"] == 34467293478
    assert remediation["v2_evidence_handling"]["successful_subset_reused"] is False
    assert remediation["v2_evidence_handling"]["scientific_values_consulted_for_successor_design"] is False
    assert remediation["fresh_successor"]["both_replicas_restart_at_state_zero"] is True
    assert remediation["fresh_successor"]["reuse_prior_scientific_rows"] is False
    scope = remediation["remediation_scope"]
    for key in (
        "scientific_producer_changed", "scientific_structural_validator_changed",
        "scientific_postrun_adjudicator_changed", "state_manifest_changed",
        "expected_table_changed", "old_source_changed", "new_source_changed",
        "measurement_boundary_changed", "absence_semantics_changed",
        "promotion_criteria_changed", "replaymark_semantics_changed", "runtime_image_changed",
    ):
        assert scope[key] is False, key
    assert scope["transport_architecture_changed"] is True

    source_candidate = git("rev-parse", "HEAD^")
    marker_delta = git("diff", "--name-only", f"{source_candidate}..HEAD").splitlines()
    assert marker_delta == ["VE1_TRANSPORT_QUALIFICATION_OPEN_V3.json"], marker_delta
    source_delta = git("diff", "--name-only", f"{BASE}..{source_candidate}").splitlines()
    assert source_delta == ALLOWED_SOURCE_DELTA, source_delta

    return {
        "schema": "replaymark.ve1.science-workflow-static-audit.v3",
        "status": "PASS",
        "scientific_result_opened": False,
        "scientific_cells": 0,
        "result_bearing_controller_invocations": 0,
        "base_evidence_head": BASE,
        "source_candidate_head": source_candidate,
        "v2_post_open_seal_sha256": V2_SEAL_SHA256,
        "science_run_block_count": len(workflow_blocks),
        "qualification_run_block_count": len(qualification_blocks),
        "all_run_blocks_bash_n_pass": True,
        "heredoc_operator_count": 0,
        "shell_function_state_sharing_forbidden": True,
        "stage_process_isolation_required": True,
        "single_file_output_mount_required": True,
        "digest_bound_read_only_history_required": True,
        "subprocess_shell_true_forbidden": True,
        "scientific_code_blobs_unchanged": {str(k): v for k, v in EXPECTED_BLOBS.items()},
        "source_files_sha256": {
            str(WORKFLOW): sha256(WORKFLOW),
            str(QUALIFICATION_WORKFLOW): sha256(QUALIFICATION_WORKFLOW),
            str(TRANSPORT): sha256(TRANSPORT),
            str(REMEDIATION): sha256(REMEDIATION),
            str(Path(__file__)): sha256(Path(__file__)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = verify()
    except Exception as exc:
        value = {
            "schema": "replaymark.ve1.science-workflow-static-audit.v3",
            "status": "FAIL",
            "scientific_result_opened": False,
            "scientific_cells": 0,
            "result_bearing_controller_invocations": 0,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        out.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    out.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
