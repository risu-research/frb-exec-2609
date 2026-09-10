from __future__ import annotations

"""Static pre-open verifier for VE2-E0Q public source freeze v1."""

import argparse
import ast
import json
import subprocess
from pathlib import Path

EXPECTED_CONSTITUTION_BLOB = "3e2c9737e485d45498e6df7780fa8bb5a652e196"
EXPECTED_AUTHORITY_BLOB = "ec0f610d85ed138c7dd1b4f18da12b9a3739accb"
EXPECTED_BOUNDARY_BLOB = "0e566517bbb83c8573b0835e850ab5020ac97988"
EXPECTED_RUNTIME_BLOB = "d0ee64c170dbee64ef94aca10d0565ea739d5b98"
EXPECTED_VALIDATOR_BLOB = "85f50eb12c39960ad0b8852f0595f5e584288400"
EXPECTED_CONTRACT_BLOB = "3855c7fd12a25658fbff17c8d65b3841b858b1a0"
ROLES = ("T01_OLD_HISTORY", "T01_NEW_TARGET", "T02_OLD", "T02_NEW")


def blob(path: str) -> str:
    return subprocess.check_output(["git", "hash-object", "--no-filters", path], text=True).strip()


def load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require_blob(path: str, expected: str) -> None:
    observed = blob(path)
    if observed != expected:
        raise AssertionError(("blob", path, observed, expected))


def static_python_checks() -> None:
    boundary_path = Path("ve2_boundary_microkernel_v1.py")
    runtime_path = Path("ve2_e0q_role_runtime_v1.py")
    validator_path = Path("ve2_e0q_independent_validate_v1.py")
    for path in (boundary_path, runtime_path, validator_path):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    boundary = boundary_path.read_text(encoding="utf-8")
    runtime = runtime_path.read_text(encoding="utf-8")

    for forbidden in (
        "night_mode.yaml",
        "weekly_heating_schedule.yaml",
        "VE2_T01_EXPECTED_FRONTIER",
        "VE2_T02_EXPECTED_FRONTIER",
        "VE2_T01_EXECUTION_STATE_MANIFEST",
        "VE2_T02_EXECUTION_STATE_MANIFEST",
        "climate.set_",
        "set_preset_mode",
        "set_temperature",
    ):
        if forbidden in runtime:
            raise AssertionError(("runtime-forbidden-token", forbidden))

    if "inspect.signature(HomeAssistant.__init__)" not in runtime:
        raise AssertionError("constructor-adapter-not-signature-derived")
    if 'DOMAIN = "ve2_e0q"' not in runtime or 'SERVICE = "sink"' not in runtime:
        raise AssertionError("synthetic-service-not-frozen")
    if "for index in range(3)" not in boundary:
        raise AssertionError("three-pass-completion-not-frozen")
    if "time.perf_counter_ns()" not in boundary:
        raise AssertionError("clock-domain-not-implemented")
    if "EVENT_STATE_CHANGED" not in boundary or "EVENT_CALL_SERVICE" not in boundary:
        raise AssertionError("required-event-types-not-observed")


def workflow_checks(path: Path, contract: dict) -> None:
    text = path.read_text(encoding="utf-8")
    required = (
        "GITHUB_RUN_ATTEMPT",
        "--network none",
        "--read-only",
        "$PWD/capsule:/capsule:ro",
        "/config:ro",
        "$PWD/results:/results",
        "actions/upload-artifact@v4",
        "ve2_e0q_independent_validate_v1.py",
        "Surface E0Q PASS only after immutable artifact upload",
    )
    for token in required:
        if token not in text:
            raise AssertionError(("workflow-required-token", token))
    for forbidden in ("pip install", "pip3 install", "docker exec"):
        if forbidden in text:
            raise AssertionError(("workflow-forbidden-token", forbidden))
    for forbidden_path in contract["forbidden_container_inputs"]:
        mount_forms = (
            f"-v $PWD/{forbidden_path}",
            f'-v "$PWD/{forbidden_path}',
            f"--volume $PWD/{forbidden_path}",
            f'--volume "$PWD/{forbidden_path}',
        )
        if any(form in text for form in mount_forms):
            raise AssertionError(("forbidden-container-input-mounted", forbidden_path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", required=True)
    args = parser.parse_args()

    require_blob("VE2_E0Q_CONSTITUTION_V1_MIRROR.json", EXPECTED_CONSTITUTION_BLOB)
    require_blob("VE2_E0Q_PRE_RESULT_AUTHORITY_V1_MIRROR.json", EXPECTED_AUTHORITY_BLOB)
    require_blob("ve2_boundary_microkernel_v1.py", EXPECTED_BOUNDARY_BLOB)
    require_blob("ve2_e0q_role_runtime_v1.py", EXPECTED_RUNTIME_BLOB)
    require_blob("ve2_e0q_independent_validate_v1.py", EXPECTED_VALIDATOR_BLOB)
    require_blob("VE2_E0Q_PUBLIC_EXECUTION_CONTRACT_V1.json", EXPECTED_CONTRACT_BLOB)

    constitution = load("VE2_E0Q_CONSTITUTION_V1_MIRROR.json")
    authority = load("VE2_E0Q_PRE_RESULT_AUTHORITY_V1_MIRROR.json")
    contract = load("VE2_E0Q_PUBLIC_EXECUTION_CONTRACT_V1.json")

    assert constitution["schema"] == "replaymark.ve2.e0q-constitution.v1"
    assert authority["schema"] == "replaymark.ve2.e0q-pre-result-authority.v1"
    assert contract["schema"] == "replaymark.ve2.e0q-public-execution-contract.v1"
    assert contract["private_e0q_authority"] == "227e4e75528d8b73d7225ef68bc2c63d29978be5"
    assert contract["parent_runtime_discovery_public_result_seal"] == "395ccd138b93c5c40a17fd906d497df1851cfeb1"
    assert contract["boundary_git_blob"] == EXPECTED_BOUNDARY_BLOB
    assert contract["runtime_driver_git_blob"] == EXPECTED_RUNTIME_BLOB
    assert contract["independent_validator_git_blob"] == EXPECTED_VALIDATOR_BLOB
    assert tuple(contract["roles"]) == ROLES
    assert contract["capsule_files"] == ["ve2_boundary_microkernel_v1.py", "ve2_e0q_role_runtime_v1.py"]
    assert contract["promotion"]["run_attempt"] == 1
    assert contract["promotion"]["same_authority_rerun"] is False
    assert contract["scientific_boundary"] == {
        "scientific_result_opened": False,
        "frontier_result_seen": False,
        "ve2_home_assistant_scientific_cells": 0,
        "ve2_replaymark_scientific_cells": 0,
    }

    selected = constitution["selected_substrates"]
    for role in ROLES:
        c = contract["roles"][role]
        assert selected[role]["source_commit"] == c["source_commit"]
        assert selected[role]["ha_image"] == c["ha_image"]
        assert c["ha_image"].startswith("ghcr.io/home-assistant/home-assistant@sha256:")
        assert len(c["component_tree_sha1"]) == 40
        assert len(c["manifest_sha256"]) == 64

    assert authority["selected_source_commits"]["T01_OLD_HISTORY"] == contract["roles"]["T01_OLD_HISTORY"]["source_commit"]
    assert authority["selected_source_commits"]["T01_NEW_TARGET"] == contract["roles"]["T01_NEW_TARGET"]["source_commit"]
    assert authority["selected_source_commits"]["T02_OLD"] == contract["roles"]["T02_OLD"]["source_commit"]
    assert authority["selected_source_commits"]["T02_NEW"] == contract["roles"]["T02_NEW"]["source_commit"]
    assert authority["science_open_authorized"] is False
    assert authority["scientific_result_opened"] is False

    static_python_checks()
    workflow_checks(Path(args.workflow), contract)
    print(json.dumps({
        "schema": "replaymark.ve2.e0q-source-freeze-static.v1",
        "status": "PASS",
        "boundary_git_blob": EXPECTED_BOUNDARY_BLOB,
        "roles": list(ROLES),
        "scientific_cells": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
