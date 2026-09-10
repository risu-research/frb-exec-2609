from __future__ import annotations

"""Independent structural validator for VE2 pre-science transport qualification.

The validator has no access to VE2 scientific expected-frontier files. It judges
only whether the neutral-automation transport witnesses establish the frozen
cross-version invocation/clock contract while scientific exposure remains zero.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "replaymark.ve2.science-transport-independent-validation.v1"
RUNTIME_SCHEMA = "replaymark.ve2.science-transport-qualification-runtime.v1"
CLOCK_DRIVER_ID = "replaymark.ve2.ha-test-equivalent-clock-driver.v1"
EXPECTED = {
    "T01_OLD_RUNTIME": {"version": "2022.10.0", "cases": {"state": "STATE"}},
    "T01_NEW_RUNTIME": {"version": "2026.1.0", "cases": {"state": "STATE"}},
    "T02_RUNTIME": {
        "version": "2026.9.0",
        "cases": {
            "state": "STATE",
            "state_for_120s": "STATE",
            "time": "TIME",
            "homeassistant_start_delay_30s": "HOMEASSISTANT_START",
        },
    },
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def verify_row(role: str, row: dict[str, Any], expected_family: str) -> dict[str, Any]:
    recorded = row.get("row_sha256")
    body = {k: v for k, v in row.items() if k != "row_sha256"}
    require(recorded == sha(body), "%s/%s row digest mismatch" % (role, row.get("case")))
    require(row.get("expected_family_for_qualification_only") == expected_family, "qualification case family changed")
    require(row.get("pass") is True, "producer did not close row PASS")
    checks = row.get("checks") or {}
    required_checks = {
        "family_from_native_trace_exact",
        "automation_entity_exact",
        "event_trace_context_exact",
        "service_context_bound_to_invocation",
        "fresh_context_not_root",
        "invocation_parent_is_root_when_applicable",
        "single_invocation",
        "single_neutral_sink",
    }
    require(set(checks) == required_checks, "row checks set changed")
    require(all(value is True for value in checks.values()), "row has failed witness check")

    inv = row["automation_invocation_event"]
    trace = row["trace_witness"]
    svc = row["neutral_service_event"]
    trigger = trace["trigger"]
    require(inv["data"].get("entity_id") == row["automation_entity"], "automation entity mismatch")
    require(inv["context_id"] == trace["trace_context_id"], "event/trace context mismatch")
    require(svc["context_id"] == inv["context_id"], "service not bound to invocation context")
    require(trigger["family"] == expected_family, "native trace family mismatch")
    require(trigger["platform"] in {"state", "time", "homeassistant"}, "foreign trigger platform")
    root = row.get("root_stimulus_context_id")
    if root is not None:
        require(inv["context_id"] != root, "automation failed to create fresh context")
        require(inv["context_parent_id"] == root, "fresh automation context not linked to root stimulus")

    clock = row.get("clock_records") or []
    if row["case"] == "state":
        require(clock == [], "immediate state case unexpectedly used clock transport")
    elif role == "T02_RUNTIME":
        require(len(clock) == 1, "clock-qualified case lacks exact one clock record")
        c = clock[0]
        require(c["clock_driver_id"] == CLOCK_DRIVER_ID, "clock driver identity mismatch")
        require(c["handles_fired"] >= 1, "clock transport fired no Home Assistant timer handle")
        require(c["blueprint_or_action_definition_mutated"] is False, "clock transport mutated automation semantics")
        require(c["result_dependent_target_time"] is False, "clock target was result-dependent")
    else:
        require(clock == [], "non-2026.9 role used unqualified clock transport")

    return {
        "case": row["case"],
        "family": trigger["family"],
        "event_context": inv["context_id"],
        "trace_context": trace["trace_context_id"],
        "service_context": svc["context_id"],
        "clock_handles_fired": sum(int(c["handles_fired"]) for c in clock),
        "row_sha256": recorded,
    }


def verify_role(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    doc = json.loads(raw)
    require(doc.get("schema") == RUNTIME_SCHEMA, "foreign runtime schema")
    role = doc.get("role")
    require(role in EXPECTED, "foreign runtime role")
    exp = EXPECTED[role]
    require(doc.get("status") == "PASS", "%s runtime not PASS" % role)
    require(doc.get("home_assistant_version") == exp["version"], "%s HA version mismatch" % role)
    recorded = doc.get("result_sha256")
    require(recorded == sha({k: v for k, v in doc.items() if k != "result_sha256"}), "%s result digest mismatch" % role)
    hygiene = doc.get("scientific_hygiene") or {}
    require(hygiene == {
        "transition_blueprint_executed": False,
        "T01_or_T02_execution_state_used": False,
        "expected_frontier_read": False,
        "historical_better_thermostat_action_dispatched": False,
        "scientific_cells": 0,
        "frontier_result_seen": False,
    }, "%s scientific-hygiene record changed" % role)
    rows = doc.get("rows") or []
    by_case = {row.get("case"): row for row in rows}
    require(len(by_case) == len(rows), "%s duplicate case" % role)
    require(set(by_case) == set(exp["cases"]), "%s case population mismatch" % role)
    verified = [verify_row(role, by_case[case], family) for case, family in exp["cases"].items()]
    if role == "T02_RUNTIME":
        require(doc.get("clock_driver_id") == CLOCK_DRIVER_ID, "T02 clock driver id mismatch")
    else:
        require(doc.get("clock_driver_id") is None, "%s unexpectedly declares clock driver" % role)
    return {
        "role": role,
        "home_assistant_version": exp["version"],
        "runtime_file_sha256": hashlib.sha256(raw).hexdigest(),
        "runtime_result_sha256": recorded,
        "cases": verified,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--t01-old", required=True)
    parser.add_argument("--t01-new", required=True)
    parser.add_argument("--t02", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    roles = [verify_role(Path(args.t01_old)), verify_role(Path(args.t01_new)), verify_role(Path(args.t02))]
    require([row["role"] for row in roles] == ["T01_OLD_RUNTIME", "T01_NEW_RUNTIME", "T02_RUNTIME"], "role order mismatch")
    result = {
        "schema": SCHEMA,
        "status": "PASS",
        "authority": "VE2_CROSS_VERSION_SCIENCE_TRANSPORT_PRE_SCIENCE_V1",
        "roles": roles,
        "promotion": {
            "cross_version_invocation_double_witness": "PASS",
            "T02_clock_transport": "PASS",
            "scientific_cells": 0,
            "frontier_result_seen": False,
            "transition_blueprint_executed": False,
            "eligible_for_scientific_capsule_freeze": True,
        },
    }
    result["validation_sha256"] = sha(result)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","validation_sha256":result["validation_sha256"],"scientific_cells":0}, sort_keys=True))


if __name__ == "__main__":
    main()
