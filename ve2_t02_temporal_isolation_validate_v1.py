from __future__ import annotations

"""Independent adjudicator for the non-promotable T02 isolation diagnostic."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "replaymark.ve2.t02-temporal-isolation-diagnostic.v1"
OUT_SCHEMA = "replaymark.ve2.t02-temporal-isolation-adjudication.v1"
DIAGNOSTIC_ID = "NON_PROMOTABLE_T02_TEMPORAL_ISOLATION_DIAGNOSTIC_V1"
V5_FAILURE_SEAL = "c17d2506e465b9bb3ac71cb04cb7c10c0360ba01"
EXPECTED_HA = "2026.9.0"
CASE_ORDER = ["state", "state_for_120s", "time", "homeassistant_start_delay_30s"]


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def verify_capsule(path: Path, expected_case: str) -> dict[str, Any]:
    data = json.loads(path.read_text())
    assert data["schema"] == SCHEMA
    assert data["diagnostic_id"] == DIAGNOSTIC_ID
    assert data["case"] == expected_case
    assert data["case_order_index"] == CASE_ORDER.index(expected_case)
    assert data["home_assistant_version"] == EXPECTED_HA
    assert data["inherited_transport_implementation"] == "replaymark.ve2.science-transport-qualification-runtime.v5"
    assert data["v5_failure_seal"] == V5_FAILURE_SEAL

    presented = data.pop("capsule_sha256")
    assert presented == sha(data)
    data["capsule_sha256"] = presented

    law = data["observation_law"]
    assert law["fresh_hass_wrapper_delegates_exactly_once"] is True
    assert law["clock_driver_wrapper_delegates_exactly_once_when_called"] is True
    assert law["witness_collection_wrapper_delegates_exactly_once_when_called"] is True
    assert law["trigger_definition_mutated"] is False
    assert law["action_definition_mutated"] is False
    assert law["clock_target_mutated"] is False
    assert law["wait_timeout_mutated"] is False
    assert law["home_assistant_setup_calls_added"] == 0
    assert law["result_dependent_fallback"] is False
    assert law["retry_after_failure"] is False

    hygiene = data["scientific_hygiene"]
    assert hygiene["diagnostic_non_promotable"] is True
    assert hygiene["scientific_result_opened"] is False
    assert hygiene["frontier_result_seen"] is False
    assert hygiene["scientific_cells"] == 0
    assert hygiene["expected_frontier_read"] is False
    assert hygiene["T01_or_T02_execution_state_used"] is False
    assert hygiene["transition_blueprint_executed"] is False
    assert hygiene["historical_better_thermostat_action_dispatched"] is False

    events = [item["event"] for item in data["journal"]]
    assert events and events[0] == "CASE_BEGIN"
    assert events.count("FRESH_HASS_BEGIN") == 1
    assert events.count("FRESH_HASS_END") + events.count("FRESH_HASS_ERROR") == 1

    if data["status"] == "PASS":
        assert isinstance(data["row"], dict) and data["row"].get("pass") is True
        assert data["failure"] is None
        assert events[-1] == "CASE_END"
        assert events.count("WITNESS_COLLECTION_END") == 1
    else:
        assert data["status"] in {"ROW_FAIL", "EXCEPTION"}
        if data["status"] == "EXCEPTION":
            assert data["row"] is None
            assert isinstance(data["failure"], dict)
            assert events[-1] == "CASE_ERROR"
    return data


def classify(data: dict[str, Any]) -> str:
    if data["status"] == "PASS":
        return "PASS"
    events = [item["event"] for item in data["journal"]]
    if "FRESH_HASS_ERROR" in events:
        return "FRESH_HASS_OR_NATIVE_SETUP"
    if "CLOCK_DRIVER_ERROR" in events:
        return "CLOCK_DRIVER_EXCEPTION"
    if "WITNESS_COLLECTION_ERROR" in events:
        if "CLOCK_DRIVER_END" in events:
            return "POST_CLOCK_NATIVE_TRIGGER_OR_WITNESS_TIMEOUT"
        return "NATIVE_TRIGGER_OR_WITNESS_TIMEOUT"
    if data["status"] == "ROW_FAIL":
        return "COMPLETED_ROW_FAILED_INVARIANT"
    return "CASE_BODY_BEFORE_WITNESS_COLLECTION"


def main() -> None:
    parser = argparse.ArgumentParser()
    for case in CASE_ORDER:
        parser.add_argument("--" + case.replace("_", "-"), required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    paths = {
        "state": Path(args.state),
        "state_for_120s": Path(args.state_for_120s),
        "time": Path(args.time),
        "homeassistant_start_delay_30s": Path(args.homeassistant_start_delay_30s),
    }
    capsules = {case: verify_capsule(paths[case], case) for case in CASE_ORDER}
    statuses = {case: capsules[case]["status"] for case in CASE_ORDER}
    layers = {case: classify(capsules[case]) for case in CASE_ORDER}
    failing = [case for case in CASE_ORDER if statuses[case] != "PASS"]
    passing = [case for case in CASE_ORDER if statuses[case] == "PASS"]

    out: dict[str, Any] = {
        "schema": OUT_SCHEMA,
        "diagnostic_id": DIAGNOSTIC_ID,
        "status": "DIAGNOSED" if failing else "ALL_ISOLATED_CASES_PASS",
        "case_order": CASE_ORDER,
        "case_status": statuses,
        "case_failure_layer": layers,
        "passing_cases": passing,
        "failing_cases": failing,
        "earliest_failing_case_in_original_order": failing[0] if failing else None,
        "earliest_failing_layer": layers[failing[0]] if failing else None,
        "repair_selection_authorized": bool(failing),
        "transport_promotion_authorized": False,
        "scientific_promotion_authorized": False,
        "scientific_cells": 0,
        "frontier_result_seen": False,
        "interpretation_law": {
            "each_case_ran_in_an_independent_clean_process": True,
            "existing_v5_neutral_case_functions_only": True,
            "diagnostic_does_not_change_transport_pass_criteria": True,
            "diagnostic_does_not_establish_a_transport_PASS": True,
            "only_a_successor_prospective_repair_may_be_selected_from_this_result": True,
        },
        "capsule_sha256": {case: capsules[case]["capsule_sha256"] for case in CASE_ORDER},
    }
    out["adjudication_sha256"] = sha(out)
    Path(args.out).write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": out["status"], "failing_cases": failing, "scientific_cells": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
