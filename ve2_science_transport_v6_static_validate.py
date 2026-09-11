from __future__ import annotations

"""Static pre-OPEN validator for the VE2 transport v6 lifecycle repair."""

import argparse
import ast
import json
from pathlib import Path

DIAGNOSIS_SEAL = "5f541f3976946ca21d3a911b49f6f0f69158d369"
V3_BLOB = "7b31244a3a4505399e5885b017fd81bb06209176"
V6_RUNTIME_BLOB = "941b80b1c42781094fc8b3bb1a83861d80ae01da"
PROOF_BLOB = "7807c5454a91e1adff98b5bef69b39379d7489d7"
STARTUP_CASE = "homeassistant_start_delay_30s"
STARTUP_FAMILY = "HOMEASSISTANT_START"


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-freeze", required=True)
    args = ap.parse_args()

    contract = json.loads(Path("VE2_SCIENCE_TRANSPORT_QUALIFICATION_CONTRACT_V6.json").read_text())
    remediation = json.loads(Path("VE2_SCIENCE_TRANSPORT_V6_LIFECYCLE_SIGNAL_REMEDIATION.json").read_text())
    proof = json.loads(Path("VE2_SCIENCE_TRANSPORT_V6_NATIVE_CONTEXT_APPLICABILITY_PROOF.json").read_text())
    opened = json.loads(Path("VE2_SCIENCE_TRANSPORT_QUALIFICATION_OPEN_V6.json").read_text())

    require(contract["schema"] == "replaymark.ve2.science-transport-qualification-contract.v6", "contract schema")
    require(contract["status"] == "FROZEN_PROSPECTIVE_PRE_SCIENCE", "contract status")
    require(contract["authority"]["t02_diagnosis_seal"] == DIAGNOSIS_SEAL, "contract diagnosis")
    require(contract["v6_delta"]["runtime_blob"] == V6_RUNTIME_BLOB, "contract runtime")
    require(contract["v6_delta"]["execution_semantic_changes"] == 1, "semantic delta count")
    require(contract["v6_delta"]["witness_applicability_changes"] == 1, "applicability delta count")
    require(contract["v6_delta"]["old_signal"] == "homeassistant_start", "old signal")
    require(contract["v6_delta"]["new_signal"] == "homeassistant_started", "new signal")
    require(contract["v6_delta"]["affects_only_case"] == STARTUP_CASE, "case scope")
    require(contract["v6_delta"]["collector_algorithm_changed"] is False, "collector algorithm")
    require(contract["v6_delta"]["clock_driver_changed"] is False, "clock driver")
    require(contract["v6_delta"]["wait_timeout_changed"] is False, "wait timeout")
    require(contract["inheritance"]["independent_transport_validator_changed"] is False, "final validator")
    require(contract["scientific_firewall"]["scientific_cells"] == 0, "science firewall")

    require(remediation["predecessor_diagnosis_seal"] == DIAGNOSIS_SEAL, "remediation diagnosis")
    require(remediation["source_evidence"]["native_listener_symbol"] == "EVENT_HOMEASSISTANT_STARTED", "listener symbol")
    require(remediation["source_evidence"]["native_listener_value"] == "homeassistant_started", "listener value")
    require(remediation["source_evidence"]["native_callback_event_argument_used_for_context"] is False, "event context use")
    require(remediation["source_evidence"]["native_action_invocation_supplies_context_argument"] is False, "action context arg")
    require(remediation["repair"]["execution_semantic_changes"] == 1, "remediation semantic count")
    require(remediation["repair"]["witness_applicability_changes"] == 1, "remediation applicability count")
    require(remediation["repair"]["collector_algorithm_changed"] is False, "remediation collector")
    require(remediation["repair"]["independent_validator_changed"] is False, "remediation validator")

    require(proof["schema"] == "replaymark.ve2.science-transport-v6-native-context-applicability-proof.v1", "proof schema")
    require(proof["status"] == "FROZEN_PROSPECTIVE_SOURCE_PROOF", "proof status")
    require(proof["diagnosis_seal"] == DIAGNOSIS_SEAL, "proof diagnosis")
    require(proof["home_assistant_source"]["trigger_file_blob"] == "4f96b25d281e706b8e8adf3f015d15af12960002", "trigger source blob")
    require(proof["home_assistant_source"]["official_test_file_blob"] == "c686f8273052b0891d7dec9c111d48b86abf79fa", "official test blob")
    require(proof["frozen_runner_source"]["blob"] == V3_BLOB, "proof v3 blob")
    require(proof["applicability_conclusion"]["startup_root_parent_obligation"] == "NOT_APPLICABLE", "parent applicability")
    for key in (
        "event_trace_context_identity_obligation",
        "service_invocation_context_identity_obligation",
        "fresh_automation_context_obligation",
        "single_invocation_obligation",
        "single_neutral_sink_obligation",
    ):
        require(proof["applicability_conclusion"][key] == "REMAINS_REQUIRED", key)
    require(proof["allowed_runtime_projection"]["case"] == STARTUP_CASE, "projection case")
    require(proof["allowed_runtime_projection"]["expected_family"] == STARTUP_FAMILY, "projection family")
    require(proof["allowed_runtime_projection"]["collector_algorithm_changed"] is False, "projection collector")
    require(proof["allowed_runtime_projection"]["independent_transport_validator_changed"] is False, "projection validator")

    require(opened == {
        "schema": "replaymark.ve2.science-transport-qualification-open.v6",
        "authority": "VE2_CROSS_VERSION_SCIENCE_TRANSPORT_PRE_SCIENCE_V6",
        "source_freeze_public_head": args.source_freeze,
        "diagnosis_seal": DIAGNOSIS_SEAL,
        "private_preopen_authority": "e8c32489b113724d20fb57b34d4464aeb4626c9d",
        "scientific_result_opened": False,
        "frontier_result_seen": False,
        "neutral_transport_rows_before_open": 0,
        "scientific_cells": 0,
        "same_authority_rerun": False,
    }, "OPEN marker")

    v3_source = Path("ve2_science_transport_qualify_v3.py").read_text()
    v3_tree = ast.parse(v3_source)
    functional: list[tuple[str, int]] = []
    for node in v3_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count = sum(
                1
                for n in ast.walk(node)
                if isinstance(n, ast.Name)
                and isinstance(n.ctx, ast.Load)
                and n.id == "EVENT_HOMEASSISTANT_START"
            )
            if count:
                functional.append((node.name, count))
    require(functional == [("run_startup_delay", 1)], f"v3 signal uses: {functional}")

    source = Path("ve2_science_transport_qualify_v6.py").read_text()
    tree = ast.parse(source)
    function_names = {
        n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    require(function_names == {"_collect_case_v6", "_install_v6", "main"}, f"v6 function surface: {function_names}")

    signal_assignments = []
    collector_assignments = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            target = n.targets[0]
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "v3":
                if target.attr == "EVENT_HOMEASSISTANT_START":
                    signal_assignments.append(n)
                if target.attr == "_collect_case":
                    collector_assignments.append(n)
    require(len(signal_assignments) == 1, "signal assignment count")
    require(isinstance(signal_assignments[0].value, ast.Name) and signal_assignments[0].value.id == "EVENT_HOMEASSISTANT_STARTED", "signal assignment rhs")
    require(len(collector_assignments) == 1, "collector assignment count")
    require(isinstance(collector_assignments[0].value, ast.Name) and collector_assignments[0].value.id == "_collect_case_v6", "collector assignment rhs")

    collect = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_collect_case_v6")
    root_null_assignments = []
    delegated_calls = []
    for n in ast.walk(collect):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Subscript):
            target = n.targets[0]
            if isinstance(target.value, ast.Name) and target.value.id == "kwargs":
                key = target.slice.value if isinstance(target.slice, ast.Constant) else None
                if key == "root_context_id":
                    root_null_assignments.append(n)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_ORIGINAL_COLLECT_CASE":
            delegated_calls.append(n)
    require(len(root_null_assignments) == 1, "root applicability assignment count")
    require(isinstance(root_null_assignments[0].value, ast.Constant) and root_null_assignments[0].value.value is None, "root applicability rhs")
    require(len(delegated_calls) == 1, "collector delegation count")
    require("case == STARTUP_CASE" in source and "family != STARTUP_FAMILY" in source, "startup scope guards")
    require("v5._install_v5()" in source, "v5 inheritance")

    forbidden = (
        "async_setup_component(", ".async_load(", ".async_setup(",
        "hass.services.", "hass.states.", "_drive_clock =", "_wait_for_count =",
    )
    for token in forbidden:
        require(token not in source, f"forbidden v6 surface: {token}")

    forbidden_science = {
        "VE2_T01_EXECUTION_STATE_MANIFEST_V1.json",
        "VE2_T02_EXECUTION_STATE_MANIFEST_V1.json",
        "VE2_T01_EXPECTED_FRONTIER_V1.json",
        "VE2_T02_EXPECTED_FRONTIER_V1.json",
        "VE2_T01_NATIVE_SEMANTICS_V1.json",
        "VE2_T02_NATIVE_SEMANTICS_V1.json",
    }
    strings = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    require(forbidden_science.isdisjoint(strings), "scientific input reference")

    print(json.dumps({
        "status": "PASS",
        "execution_semantic_changes": 1,
        "witness_applicability_changes": 1,
        "collector_algorithm_changed": False,
        "independent_transport_validator_changed": False,
        "scientific_cells": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
