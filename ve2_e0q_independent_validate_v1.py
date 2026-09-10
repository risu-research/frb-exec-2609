from __future__ import annotations

"""Independent post-execution validator for VE2-E0Q v1."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROLES = ("T01_OLD_HISTORY", "T01_NEW_TARGET", "T02_OLD", "T02_NEW")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_role(result: dict[str, Any], expected: dict[str, Any], boundary_blob: str) -> None:
    assert result["schema"] == "replaymark.ve2.e0q-role-result.v1"
    assert result["status"] == "PASS"
    assert result["role"] == expected["role"]
    assert result["expected_ha_version"] == expected["ha_version"]
    assert result["observed_ha_version"] == expected["ha_version"]
    assert result["exact_ha_image"] == expected["ha_image"]
    assert result["source_commit"] == expected["source_commit"]
    assert result["component_tree_sha1"] == expected["component_tree_sha1"]
    assert result["manifest_sha256"] == expected["manifest_sha256"]
    assert result["manifest_version"] == expected["manifest_version"]
    assert result["boundary_git_blob"] == boundary_blob
    assert result["same_boundary_blob_required_for_future_science"] is True

    assert result["scientific_result_opened"] is False
    assert result["frontier_result_seen"] is False
    assert result["transition_blueprint_mounted"] is False
    assert result["execution_state_manifest_mounted"] is False
    assert result["expected_frontier_mounted"] is False
    assert result["historical_action_dispatched"] is False
    assert result["climate_or_better_thermostat_action_invoked"] is False
    assert result["synthetic_service_domain"] == "ve2_e0q"
    assert result["synthetic_service"] == "sink"

    loader = result["loader"]
    assert loader["status"] == "PASS"
    assert loader["loader_domain"] == "better_thermostat"
    assert loader["loader_version"] == expected["manifest_version"]
    assert loader["module_file"] == "/config/custom_components/better_thermostat/__init__.py"
    assert loader["manifest_file"] == "/config/custom_components/better_thermostat/manifest.json"
    assert loader["real_config_path_verified"] is True

    boundary = result["boundary"]
    assert boundary["status"] == "PASS"

    positive = boundary["positive"]
    assert positive["observed_event_count"] == 1
    assert len(positive["qualifying_service_events"]) == 1
    pos_parent = positive["parent_state_event"]
    pos_event = positive["qualifying_service_events"][0]
    pos_completion = positive["completion_boundary"]
    assert pos_parent["context_id"] == positive["invocation_context_id"]
    assert (
        pos_event["context_id"] == positive["invocation_context_id"]
        or pos_event["context_parent_id"] == positive["invocation_context_id"]
    )
    assert pos_event["domain"] == "ve2_e0q"
    assert pos_event["service"] == "sink"
    assert pos_event["service_data"] == {"token": "positive"}
    assert len(pos_completion["passes"]) == 3
    assert [x["pass"] for x in pos_completion["passes"]] == [0, 1, 2]
    assert pos_parent["t_ns"] <= pos_event["t_ns"] <= pos_completion["closed_ns"]

    absence = boundary["verified_absence"]
    assert absence["observed_event_count"] == 0
    assert absence["qualifying_service_events"] == []
    assert absence["parent_state_event"]["context_id"] == absence["invocation_context_id"]
    assert len(absence["completion_boundary"]["passes"]) == 3
    assert absence["parent_state_event"]["t_ns"] <= absence["completion_boundary"]["closed_ns"]

    negatives = boundary["negative_cases"]
    assert [x["label"] for x in negatives] == [
        "foreign-context", "duplicate-event", "malformed-event", "incomplete-completion"
    ]
    assert all(x["status"] == "PASS" and x["rejected"] is True for x in negatives)

    calls = boundary["sink_handler_calls"]
    assert len(calls) == 1
    assert calls[0]["context_id"] == positive["invocation_context_id"]
    assert calls[0]["data"] == {"token": "positive"}

    assert result["constructor_strategy"] in {
        "REQUIRED_CONFIG_DIR_POSITIONAL",
        "NOARG_THEN_SET_CONFIG_DIR",
    }
    assert isinstance(result["component_canonical_sha256"], str)
    assert len(result["component_canonical_sha256"]) == 64


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--boundary-blob", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    results_dir = Path(args.results)
    contract = load(Path(args.contract))
    assert contract["schema"] == "replaymark.ve2.e0q-public-execution-contract.v1"
    assert contract["boundary_git_blob"] == args.boundary_blob
    expected_roles = contract["roles"]
    assert tuple(expected_roles) == ROLES

    role_summaries = {}
    for role in ROLES:
        expected = dict(expected_roles[role])
        expected["role"] = role
        result_path = results_dir / f"{role}.json"
        exit_path = results_dir / f"{role}.exit"
        assert exit_path.read_text(encoding="utf-8").strip() == "0"
        result = load(result_path)
        validate_role(result, expected, args.boundary_blob)
        role_summaries[role] = {
            "result_sha256": sha256_file(result_path),
            "component_canonical_sha256": result["component_canonical_sha256"],
            "constructor_strategy": result["constructor_strategy"],
            "loader_real_config_path_verified": True,
            "positive_events": 1,
            "absence_events": 0,
        }

    payload = {
        "schema": "replaymark.ve2.e0q-independent-validation.v1",
        "status": "PASS",
        "boundary_git_blob": args.boundary_blob,
        "roles": role_summaries,
        "all_four_roles_pass": True,
        "partial_role_pass_promotable": False,
        "scientific_result_opened": False,
        "frontier_result_seen": False,
        "ve2_home_assistant_scientific_cells": 0,
        "ve2_replaymark_scientific_cells": 0,
    }
    Path(args.out).write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "roles": list(ROLES)}, sort_keys=True))


if __name__ == "__main__":
    main()
