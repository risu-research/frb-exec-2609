from __future__ import annotations

"""Independent post-execution validator for fresh VE2-E0Q v2."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROLES = ("T01_OLD_HISTORY", "T01_NEW_TARGET", "T02_OLD", "T02_NEW")
EXPECTED_LOADER = {
    "T01_OLD_HISTORY": "LEGACY_NATIVE_LAZY_ASYNC_GET_INTEGRATION",
    "T01_NEW_TARGET": "EXPLICIT_ASYNC_SETUP_API_PRESENT",
    "T02_OLD": "EXPLICIT_ASYNC_SETUP_API_PRESENT",
    "T02_NEW": "EXPLICIT_ASYNC_SETUP_API_PRESENT",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_epoch(epoch: dict[str, Any]) -> None:
    assert epoch["schema"] == "replaymark.ve2.boundary-capture-epoch.v2"
    assert epoch["clock_domain"] == "python.perf_counter_ns"
    for key in ("armed_ns", "state_start_index", "service_start_index", "sequence_floor"):
        assert isinstance(epoch[key], int) and epoch[key] >= 0


def validate_completion(value: dict[str, Any]) -> None:
    assert value["schema"] == "replaymark.ve2.completed-boundary.v2"
    assert value["witness"] == "three_homeassistant_async_block_till_done_fixed_point_passes"
    assert value["clock_domain"] == "python.perf_counter_ns"
    assert [x["pass"] for x in value["passes"]] == [0, 1, 2]
    cursor = value["started_ns"]
    for item in value["passes"]:
        assert item["before_ns"] >= cursor
        assert item["after_ns"] >= item["before_ns"]
        cursor = item["after_ns"]
    assert value["closed_ns"] >= cursor


def validate_role(result: dict[str, Any], expected: dict[str, Any], boundary_blob: str) -> None:
    role = expected["role"]
    assert result["schema"] == "replaymark.ve2.e0q-role-result.v2"
    assert result["status"] == "PASS"
    assert result["role"] == role
    assert result["expected_ha_version"] == expected["ha_version"]
    assert result["observed_ha_version"] == expected["ha_version"]
    assert result["exact_ha_image"] == expected["ha_image"]
    assert result["source_commit"] == expected["source_commit"]
    assert result["component_tree_sha1"] == expected["component_tree_sha1"]
    assert result["manifest_sha256"] == expected["manifest_sha256"]
    assert result["manifest_version"] == expected["manifest_version"]
    assert result["boundary_git_blob"] == boundary_blob
    assert result["same_boundary_blob_required_for_future_science"] is True
    assert result["diagnostic_phase"] == "complete"

    for flag in (
        "scientific_result_opened", "frontier_result_seen", "transition_blueprint_mounted",
        "execution_state_manifest_mounted", "expected_frontier_mounted",
        "historical_action_dispatched", "climate_or_better_thermostat_action_invoked",
    ):
        assert result[flag] is False
    assert result["synthetic_service_domain"] == "ve2_e0q"
    assert result["synthetic_service"] == "sink"

    loader = result["loader"]
    assert loader["status"] == "PASS"
    assert loader["loader_domain"] == "better_thermostat"
    assert loader["loader_version"] == expected["manifest_version"]
    assert loader["module_file"] == "/config/custom_components/better_thermostat/__init__.py"
    assert loader["manifest_file"] == "/config/custom_components/better_thermostat/manifest.json"
    assert loader["real_config_path_verified"] is True
    adapter = loader["adapter"]
    assert adapter["strategy"] == EXPECTED_LOADER[role]
    assert adapter["result_dependent_fallback"] is False
    assert adapter["retry_after_failure"] is False
    if role == "T01_OLD_HISTORY":
        assert adapter["loader_async_setup_api_present"] is False
        assert adapter["data_integrations_present_before"] is False
        assert adapter["data_integrations_present_after_adapter"] is False
    else:
        assert adapter["loader_async_setup_api_present"] is True
        assert adapter["data_integrations_present_before"] is False
        assert adapter["data_integrations_present_after_adapter"] is True

    boundary = result["boundary"]
    assert boundary["status"] == "PASS"
    assert boundary["observer_callback_mode"] == "HOMEASSISTANT_CORE_CALLBACK"

    positive = boundary["positive"]
    epoch = positive["capture_epoch"]
    validate_epoch(epoch)
    assert positive["observed_event_count"] == 1
    assert len(positive["qualifying_service_events"]) == 1
    parent = positive["parent_state_event"]
    event = positive["qualifying_service_events"][0]
    completion = positive["completion_boundary"]
    validate_completion(completion)
    assert parent["schema"] == "replaymark.ve2.boundary-state-event.v2"
    assert event["schema"] == "replaymark.ve2.boundary-service-event.v2"
    assert parent["context_id"] == positive["invocation_context_id"]
    assert event["context_id"] == positive["invocation_context_id"] or event["context_parent_id"] == positive["invocation_context_id"]
    assert event["domain"] == "ve2_e0q" and event["service"] == "sink"
    assert event["service_data"] == {"token": "positive"}
    assert parent["sequence"] > epoch["sequence_floor"]
    assert event["sequence"] > epoch["sequence_floor"]
    assert parent["sequence"] < event["sequence"]
    assert epoch["armed_ns"] <= parent["t_ns"] <= event["t_ns"] <= completion["closed_ns"]

    absence = boundary["verified_absence"]
    absence_epoch = absence["capture_epoch"]
    validate_epoch(absence_epoch)
    validate_completion(absence["completion_boundary"])
    absence_parent = absence["parent_state_event"]
    assert absence["observed_event_count"] == 0
    assert absence["qualifying_service_events"] == []
    assert absence_parent["context_id"] == absence["invocation_context_id"]
    assert absence_parent["sequence"] > absence_epoch["sequence_floor"]
    assert absence_epoch["armed_ns"] <= absence_parent["t_ns"] <= absence["completion_boundary"]["closed_ns"]

    negatives = boundary["negative_cases"]
    assert [x["label"] for x in negatives] == [
        "foreign-context", "duplicate-event", "malformed-event",
        "incomplete-completion", "sequence-regression",
    ]
    assert all(x["status"] == "PASS" and x["rejected"] is True for x in negatives)
    calls = boundary["sink_handler_calls"]
    assert len(calls) == 1
    assert calls[0]["context_id"] == positive["invocation_context_id"]
    assert calls[0]["data"] == {"token": "positive"}
    assert result["constructor_strategy"] in {"REQUIRED_CONFIG_DIR_POSITIONAL", "NOARG_THEN_SET_CONFIG_DIR"}
    assert isinstance(result["component_canonical_sha256"], str) and len(result["component_canonical_sha256"]) == 64


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--boundary-blob", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    results_dir = Path(args.results)
    contract = load(Path(args.contract))
    assert contract["schema"] == "replaymark.ve2.e0q-public-execution-contract.v2"
    assert contract["boundary_git_blob"] == args.boundary_blob
    assert tuple(contract["roles"]) == ROLES

    summaries = {}
    for role in ROLES:
        expected = dict(contract["roles"][role]); expected["role"] = role
        exit_path = results_dir / f"{role}.exit"
        assert exit_path.read_text(encoding="utf-8").strip() == "0"
        result_path = results_dir / f"{role}.json"
        result = load(result_path)
        validate_role(result, expected, args.boundary_blob)
        summaries[role] = {
            "result_sha256": sha256_file(result_path),
            "component_canonical_sha256": result["component_canonical_sha256"],
            "constructor_strategy": result["constructor_strategy"],
            "loader_strategy": result["loader"]["adapter"]["strategy"],
            "positive_parent_sequence": result["boundary"]["positive"]["parent_state_event"]["sequence"],
            "positive_service_sequence": result["boundary"]["positive"]["qualifying_service_events"][0]["sequence"],
            "positive_events": 1,
            "absence_events": 0,
        }

    payload = {
        "schema": "replaymark.ve2.e0q-independent-validation.v2",
        "status": "PASS",
        "boundary_git_blob": args.boundary_blob,
        "roles": summaries,
        "all_four_roles_pass": True,
        "partial_role_pass_promotable": False,
        "v1_partial_pass_carried": False,
        "scientific_result_opened": False,
        "frontier_result_seen": False,
        "ve2_home_assistant_scientific_cells": 0,
        "ve2_replaymark_scientific_cells": 0,
    }
    Path(args.out).write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","roles":list(ROLES),"v1_partial_pass_carried":False}, sort_keys=True))


if __name__ == "__main__":
    main()
