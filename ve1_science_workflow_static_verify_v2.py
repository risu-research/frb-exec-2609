from __future__ import annotations

"""Pre-scientific static qualification for VE1 scientific workflow remediation v2."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

WORKFLOW = Path(".github/workflows/ve1-authoritative-first-complete-v2.yml")
STATIC_WORKFLOW = Path(".github/workflows/ve1-science-workflow-static-v2.yml")
TRANSPORT = Path("ve1_science_transport_v2.py")
REMEDIATION = Path("VE1_PRE_INPUT_FAILURE_REMEDIATION_V2.json")
PRODUCER = Path("ve1_native_execution.py")
VALIDATOR = Path("ve1_independent_validate.py")
ADJUDICATOR = Path("ve1_postrun_adjudicate.py")
STATE = Path("VE1_EXECUTION_STATE_MANIFEST_V1_MIRROR.json")

BASE = "ea9fc4225d408009dc42b06f756cc46dda1fe771"
PRIVATE = "7c53b5bdc70b600156380877a406b5988d35125a"
EXPECTED_BLOBS = {
    STATE: "3e09ced267657616f045f9e34e194d49f8cdfbfc",
    PRODUCER: "40e76789335eed7d15c9a2523717d7d7bcf185fd",
    VALIDATOR: "3e0ff68988e25ab2c6fe1f90c49c289b68c9fe36",
    ADJUDICATOR: "1c6ce57de123a3a35ec45f316b21938152b09d4d",
}
ALLOWED_SOURCE_DELTA = [
    ".github/workflows/ve1-authoritative-first-complete-v2.yml",
    ".github/workflows/ve1-science-workflow-static-v2.yml",
    "VE1_PRE_INPUT_FAILURE_REMEDIATION_V2.json",
    "ve1_science_transport_v2.py",
    "ve1_science_workflow_static_verify_v2.py",
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
        m = re.match(r"^(\s*)run:\s*\|\s*$", lines[i])
        if not m:
            i += 1
            continue
        base = len(m.group(1))
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


def verify() -> dict[str, Any]:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    static_workflow = STATIC_WORKFLOW.read_text(encoding="utf-8")
    transport = TRANSPORT.read_text(encoding="utf-8")
    remediation = json.loads(REMEDIATION.read_text(encoding="utf-8"))

    assert "first complete v2" in workflow.splitlines()[0]
    assert "ve1-authoritative-first-complete-v2" in workflow
    assert "VE1_SCIENTIFIC_AUTHORITY_OPEN_V2.json" in workflow
    assert "fetch-depth: 0" in workflow
    assert "GITHUB_RUN_ATTEMPT" in workflow
    assert "fail-fast: false" in workflow
    assert "replica: [0, 1]" in workflow
    assert workflow.count("docker run --rm --network none") == 2
    assert "-v \"$PWD:/\"" not in workflow
    assert "-v \"$PWD/results/new_direct" not in workflow
    assert "ve1-first-complete-v2-r" in workflow
    assert "ve1-first-complete-aggregate-v2" in workflow
    assert "<<" not in workflow, "heredoc operator forbidden in v2 scientific workflow"
    assert "<<" not in static_workflow, "heredoc operator forbidden in v2 static workflow"

    positions = [
        workflow.index('run_stage old_history '),
        workflow.index('run_stage new_direct '),
        workflow.index('run_stage replaymark '),
        workflow.index('run_stage replay_all '),
    ]
    assert positions == sorted(positions)
    assert workflow.count('run_stage old_history ') == 1
    assert workflow.count('run_stage new_direct ') == 1
    assert workflow.count('run_stage replaymark ') == 1
    assert workflow.count('run_stage replay_all ') == 1

    for token in FORBIDDEN_ANSWER_TOKENS:
        assert token not in workflow, token
        assert token not in transport, token

    run_blocks = extract_run_blocks(workflow)
    assert len(run_blocks) >= 10
    for index, block in enumerate(run_blocks):
        result = subprocess.run(["bash", "-n"], input=block, text=True, capture_output=True)
        assert result.returncode == 0, (index, result.stderr)

    static_blocks = extract_run_blocks(static_workflow)
    for index, block in enumerate(static_blocks):
        result = subprocess.run(["bash", "-n"], input=block, text=True, capture_output=True)
        assert result.returncode == 0, ("static", index, result.stderr)

    for path in (TRANSPORT, PRODUCER, VALIDATOR, ADJUDICATOR, Path(__file__)):
        ast.parse(path.read_text(encoding="utf-8"))

    allowed_imports = {
        "__future__", "argparse", "hashlib", "json", "os", "pathlib", "typing"
    }
    assert imports(TRANSPORT) <= allowed_imports
    lowered = transport.lower()
    assert "import replaymark" not in lowered
    assert "import homeassistant" not in lowered
    assert "better_thermostat" in transport
    assert "target_preset" not in transport
    assert "compatibility" not in transport

    for path, expected in EXPECTED_BLOBS.items():
        assert git("hash-object", "--no-filters", str(path)) == expected, path

    assert remediation["status"] == "FROZEN_PRE_RESULT_REMEDIATION"
    assert remediation["authority"] == "PRE_INPUT_FAILURE_NOT_CONSUMED"
    assert remediation["private_constitution_head"] == PRIVATE
    failed = remediation["failed_v1"]
    assert failed["run_id"] == 34465860182
    assert failed["constitution_open_event_occurred"] is False
    assert failed["result_bearing_controller_invocations"] == 0
    assert failed["old_history_cells"] == 0
    assert failed["new_direct_cells"] == 0
    assert failed["replaymark_cells"] == 0
    assert failed["replay_all_cells"] == 0
    assert all(v is True for v in (
        failed["replica_artifacts"]["r0"]["stage_checksums_all_null"],
        failed["replica_artifacts"]["r1"]["stage_checksums_all_null"],
        failed["independent_redownload_verification"]["r0_zip_digest_match"],
        failed["independent_redownload_verification"]["r1_zip_digest_match"],
    ))
    scope = remediation["remediation_scope"]
    for key in (
        "scientific_producer_changed", "scientific_structural_validator_changed",
        "scientific_postrun_adjudicator_changed", "state_manifest_changed",
        "expected_table_changed", "old_source_changed", "new_source_changed",
        "measurement_boundary_changed", "absence_semantics_changed",
        "promotion_criteria_changed", "replaymark_semantics_changed",
        "runtime_image_changed",
    ):
        assert scope[key] is False, key

    source_candidate = git("rev-parse", "HEAD^")
    marker_delta = git("diff", "--name-only", f"{source_candidate}..HEAD").splitlines()
    assert marker_delta == ["VE1_WORKFLOW_REMEDIATION_STATIC_OPEN_V2.json"], marker_delta
    source_delta = git("diff", "--name-only", f"{BASE}..{source_candidate}").splitlines()
    assert source_delta == ALLOWED_SOURCE_DELTA, source_delta

    return {
        "schema": "replaymark.ve1.science-workflow-static-audit.v2",
        "status": "PASS",
        "scientific_result_opened": False,
        "scientific_cells": 0,
        "base_evidence_head": BASE,
        "source_candidate_head": source_candidate,
        "failed_v1_run_preserved": 34465860182,
        "run_block_count": len(run_blocks),
        "all_run_blocks_bash_n_pass": True,
        "heredoc_operator_count": 0,
        "scientific_code_blobs_unchanged": {str(k): v for k, v in EXPECTED_BLOBS.items()},
        "source_files_sha256": {
            str(WORKFLOW): sha256(WORKFLOW),
            str(STATIC_WORKFLOW): sha256(STATIC_WORKFLOW),
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
            "schema": "replaymark.ve1.science-workflow-static-audit.v2",
            "status": "FAIL",
            "scientific_result_opened": False,
            "scientific_cells": 0,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        out.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    out.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
