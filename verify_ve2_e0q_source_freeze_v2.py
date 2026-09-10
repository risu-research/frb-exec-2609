from __future__ import annotations

"""Static verifier for VE2-E0Q v2 prospective remediation source freeze."""

import argparse
import ast
import json
import subprocess
from pathlib import Path

PUBLIC_V1_FAILURE_SEAL = "1583bc3d714e7b328d7b095cfb873ed6c346457d"
PRIVATE_V2_REMEDIATION_AUTHORITY = "05fc7b4c63171ddbc25bc274cc6e087acc92dceb"
REMEDIATION_BLOB = "1442738f903b56937586b8a7113362b9e269703c"
BOUNDARY_BLOB = "765680028bde49ead76a22bebe5aace1bfbea60e"
RUNTIME_BLOB = "9f1946ba8afa3477068a1487fdbd5311c1e0e0ef"
VALIDATOR_BLOB = "90073f5ec0a59ac09d02ae7f2f3fad180e2f28c1"
CONTRACT_BLOB = "0e6a282f6e5f6f32a41135797bbe4ce5bcc8d7b1"
V1_CONSTITUTION_BLOB = "3e2c9737e485d45498e6df7780fa8bb5a652e196"
V1_AUTHORITY_BLOB = "ec0f610d85ed138c7dd1b4f18da12b9a3739accb"
V1_CONTRACT_BLOB = "3855c7fd12a25658fbff17c8d65b3841b858b1a0"
ROLES = ("T01_OLD_HISTORY", "T01_NEW_TARGET", "T02_OLD", "T02_NEW")
SOURCE_FREEZE_PATHS = {
    ".github/workflows/ve2-e0q-v2.yml",
    "VE2_E0Q_REMEDIATION_CONTRACT_V2_MIRROR.json",
    "VE2_E0Q_PUBLIC_EXECUTION_CONTRACT_V2.json",
    "ve2_boundary_microkernel_v2.py",
    "ve2_e0q_role_runtime_v2.py",
    "ve2_e0q_independent_validate_v2.py",
    "verify_ve2_e0q_source_freeze_v2.py",
}
IDENTITY_FIELDS = (
    "source_commit", "component_tree_sha1", "manifest_sha256", "manifest_version",
    "ha_version", "ha_image",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def blob(path: str) -> str:
    return git("hash-object", "--no-filters", path)


def load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require_blob(path: str, expected: str) -> None:
    observed = blob(path)
    if observed != expected:
        raise AssertionError(("blob", path, observed, expected))


def ancestry_and_delta(source_freeze: str) -> None:
    if git("rev-parse", f"{source_freeze}^") != PUBLIC_V1_FAILURE_SEAL:
        raise AssertionError("v2-source-freeze-not-direct-child-of-v1-failure-seal")
    rows = git("diff", "--name-status", PUBLIC_V1_FAILURE_SEAL, source_freeze).splitlines()
    parsed = [(r.split("\t", 1)[0], r.split("\t", 1)[1]) for r in rows if r]
    if {p for _, p in parsed} != SOURCE_FREEZE_PATHS:
        raise AssertionError(("source-freeze-path-set", parsed))
    if any(status != "A" for status, _ in parsed):
        raise AssertionError(("source-freeze-not-additive-only", parsed))


def python_semantics() -> None:
    paths = [
        Path("ve2_boundary_microkernel_v2.py"),
        Path("ve2_e0q_role_runtime_v2.py"),
        Path("ve2_e0q_independent_validate_v2.py"),
    ]
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    boundary = paths[0].read_text(encoding="utf-8")
    runtime = paths[1].read_text(encoding="utf-8")
    validator = paths[2].read_text(encoding="utf-8")

    for token in (
        "from homeassistant.core import callback",
        "@callback\n        def on_state",
        "@callback\n        def on_service",
        '"sequence": self._next_sequence()',
        '"armed_ns": time.perf_counter_ns()',
        '"sequence_floor": self._sequence',
        'raise ValueError("service-sequence-not-after-parent")',
        'raise ValueError("service-time-not-after-parent")',
        "for index in range(3)",
    ):
        if token not in boundary:
            raise AssertionError(("boundary-required-token", token))

    for token in (
        'strategy = "LEGACY_NATIVE_LAZY_ASYNC_GET_INTEGRATION"',
        'strategy = "EXPLICIT_ASYNC_SETUP_API_PRESENT"',
        '"result_dependent_fallback": False',
        '"retry_after_failure": False',
        'DOMAIN = "ve2_e0q"',
        'SERVICE = "sink"',
        '"sequence-regression"',
        '"scientific_result_opened": False',
        '"historical_action_dispatched": False',
    ):
        if token not in runtime:
            raise AssertionError(("runtime-required-token", token))

    forbidden_runtime = (
        "night_mode.yaml", "weekly_heating_schedule.yaml",
        "VE2_T01_EXPECTED_FRONTIER", "VE2_T02_EXPECTED_FRONTIER",
        "VE2_T01_EXECUTION_STATE_MANIFEST", "VE2_T02_EXECUTION_STATE_MANIFEST",
        "climate.set_", "set_preset_mode", "set_temperature", "sleep(",
    )
    for token in forbidden_runtime:
        if token in runtime:
            raise AssertionError(("runtime-forbidden-token", token))
    if "except Exception" in runtime.split("def prepare_loader",1)[1].split("async def verify_loader",1)[0]:
        raise AssertionError("loader-adapter-has-result-dependent-exception-fallback")

    for token in (
        '"v1_partial_pass_carried": False',
        'assert parent["sequence"] < event["sequence"]',
        'assert epoch["armed_ns"] <= parent["t_ns"] <= event["t_ns"] <= completion["closed_ns"]',
        '"sequence-regression"',
        '"ve2_home_assistant_scientific_cells": 0',
    ):
        if token not in validator:
            raise AssertionError(("validator-required-token", token))


def contract_checks() -> dict:
    remediation = load("VE2_E0Q_REMEDIATION_CONTRACT_V2_MIRROR.json")
    contract = load("VE2_E0Q_PUBLIC_EXECUTION_CONTRACT_V2.json")
    v1 = load("VE2_E0Q_PUBLIC_EXECUTION_CONTRACT_V1.json")
    assert remediation["schema"] == "replaymark.ve2.e0q-remediation-contract.v2"
    assert remediation["status"] == "FROZEN_PROSPECTIVE_PRE_V2_EXECUTION"
    assert remediation["failed_public_authority"]["public_failure_seal"] == PUBLIC_V1_FAILURE_SEAL
    assert remediation["v2_promotion"]["fresh_all_four_roles"] is True
    assert remediation["v2_promotion"]["same_authority_rerun"] is False
    assert remediation["observer_ordering_law"]["ordering_assertion_removed"] is False
    assert remediation["loader_adapter_law"]["result_dependent_fallback"] is False

    assert contract["schema"] == "replaymark.ve2.e0q-public-execution-contract.v2"
    assert contract["private_remediation_authority"] == PRIVATE_V2_REMEDIATION_AUTHORITY
    assert contract["parent_public_failure_seal"] == PUBLIC_V1_FAILURE_SEAL
    assert contract["v1_partial_pass_carried"] is False
    assert contract["boundary_git_blob"] == BOUNDARY_BLOB
    assert contract["runtime_driver_git_blob"] == RUNTIME_BLOB
    assert contract["independent_validator_git_blob"] == VALIDATOR_BLOB
    assert tuple(contract["roles"]) == ROLES
    assert contract["promotion"]["run_attempt"] == 1
    assert contract["promotion"]["fresh_roles_required"] == list(ROLES)
    assert contract["promotion"]["all_roles_must_pass"] is True
    assert contract["promotion"]["same_boundary_blob_all_roles"] is True
    assert contract["promotion"]["same_authority_rerun"] is False
    assert contract["promotion"]["negative_cases"] == [
        "foreign-context", "duplicate-event", "malformed-event",
        "incomplete-completion", "sequence-regression",
    ]
    assert contract["scientific_boundary"] == {
        "scientific_result_opened": False,
        "frontier_result_seen": False,
        "ve2_home_assistant_scientific_cells": 0,
        "ve2_replaymark_scientific_cells": 0,
    }
    for role in ROLES:
        for field in IDENTITY_FIELDS:
            assert contract["roles"][role][field] == v1["roles"][role][field]
        assert contract["roles"][role]["ha_image"].startswith(
            "ghcr.io/home-assistant/home-assistant@sha256:"
        )
    return contract


def workflow_checks(path: Path, contract: dict) -> None:
    text = path.read_text(encoding="utf-8")
    required = (
        "branches:\n      - ve2-e0q-v2",
        "GITHUB_RUN_ATTEMPT",
        "PUBLIC_V1_FAILURE_SEAL",
        "PRIVATE_V2_REMEDIATION_AUTHORITY",
        "--network none",
        "--read-only",
        "$PWD/capsule:/capsule:ro",
        "/config:ro",
        "ve2_e0q_role_runtime_v2.py",
        "ve2_e0q_independent_validate_v2.py",
        "actions/upload-artifact@v4",
        "ve2-e0q-first-complete-v2",
        "Surface E0Q-v2 PASS only after immutable artifact upload",
    )
    for token in required:
        if token not in text:
            raise AssertionError(("workflow-required-token", token))
    for forbidden in (
        "workflow_dispatch", "pip install", "pip3 install", "docker exec",
        "ve2_e0q_role_runtime_v1.py", "ve2_e0q_independent_validate_v1.py",
    ):
        if forbidden in text:
            raise AssertionError(("workflow-forbidden-token", forbidden))
    for forbidden_path in contract["forbidden_container_inputs"]:
        if forbidden_path in text:
            raise AssertionError(("forbidden-scientific-input-referenced-by-workflow", forbidden_path))
    upload = text.index("Upload immutable E0Q-v2 first-complete capsule")
    surface = text.index("Surface E0Q-v2 PASS only after immutable artifact upload")
    if upload >= surface:
        raise AssertionError("pass-surface-before-artifact-upload")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--source-freeze", required=True)
    args = ap.parse_args()

    ancestry_and_delta(args.source_freeze)
    require_blob("VE2_E0Q_CONSTITUTION_V1_MIRROR.json", V1_CONSTITUTION_BLOB)
    require_blob("VE2_E0Q_PRE_RESULT_AUTHORITY_V1_MIRROR.json", V1_AUTHORITY_BLOB)
    require_blob("VE2_E0Q_PUBLIC_EXECUTION_CONTRACT_V1.json", V1_CONTRACT_BLOB)
    require_blob("VE2_E0Q_REMEDIATION_CONTRACT_V2_MIRROR.json", REMEDIATION_BLOB)
    require_blob("ve2_boundary_microkernel_v2.py", BOUNDARY_BLOB)
    require_blob("ve2_e0q_role_runtime_v2.py", RUNTIME_BLOB)
    require_blob("ve2_e0q_independent_validate_v2.py", VALIDATOR_BLOB)
    require_blob("VE2_E0Q_PUBLIC_EXECUTION_CONTRACT_V2.json", CONTRACT_BLOB)

    contract = contract_checks()
    python_semantics()
    workflow_checks(Path(args.workflow), contract)
    print(json.dumps({
        "schema": "replaymark.ve2.e0q-source-freeze-static.v2",
        "status": "PASS",
        "parent_public_v1_failure_seal": PUBLIC_V1_FAILURE_SEAL,
        "private_v2_remediation_authority": PRIVATE_V2_REMEDIATION_AUTHORITY,
        "boundary_git_blob": BOUNDARY_BLOB,
        "fresh_roles": list(ROLES),
        "additive_only_delta": True,
        "scientific_cells": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
