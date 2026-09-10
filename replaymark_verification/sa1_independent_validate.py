from __future__ import annotations

"""Pure-JSON independent validator for SA1.

No ReplayMark production module, Home Assistant module, expected-table
materializer, or native producer is imported.  The validator only compares the
pre-live frozen expected table with retained raw native-execution material.
"""

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_ROWS_SHA256 = "e70b8db3ee6d2644c46dc2c8c6bef9d11b86e98a1cd2f59947632308b798c9c0"
EXPECTED_HA_VERSION = "2026.9.0"
CLIMATE_ENTITY = "climate.agentmark_thermostat"
PRESENCE_ENTITY = "input_boolean.agentmark_presence"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _rows_sha(rows: object) -> str:
    return hashlib.sha256(_canonical(rows)).hexdigest()


def _expected_decision_snapshot(row: dict[str, object]) -> dict[str, object]:
    axes = row["inputs"]
    return {
        "presence": "on" if axes["presence"] else "off",
        "motion": "on" if axes["motion"] else "off",
        "night": "on" if axes["night"] else "off",
        "enable": "on",
        "climate_entity": CLIMATE_ENTITY,
        "climate_state": "heat",
        "climate_preset": axes["current_preset"],
    }


def _service_observation(events: list[dict[str, object]]) -> dict[str, object] | None:
    if not events:
        return None
    if len(events) != 1:
        raise AssertionError(("unexpected consequential service cardinality", len(events)))
    event = events[0]
    if set(event) != {
        "t_ns", "domain", "service", "service_data", "operation", "target_class",
        "variant", "context_id", "context_parent_id", "presence_state_at_issue",
        "climate_preset_before_issue",
    }:
        raise AssertionError(("unexpected retained service-event fields", sorted(event)))
    if event["domain"] != "climate" or event["service"] != "set_preset_mode":
        raise AssertionError(("unexpected consequential service", event["domain"], event["service"]))
    data = dict(event["service_data"])
    raw_target = data.get("entity_id")
    if isinstance(raw_target, str):
        targets = [raw_target]
    elif isinstance(raw_target, list):
        targets = [str(v) for v in raw_target]
    else:
        raise AssertionError(("unresolved native target", raw_target))
    if targets != [CLIMATE_ENTITY] or set(data) != {"entity_id", "preset_mode"}:
        raise AssertionError(("native service coordinates are not exact", data))
    return {
        "domain": "climate",
        "service": "set_preset_mode",
        "target_entity": CLIMATE_ENTITY,
        "service_data": {"preset_mode": str(data["preset_mode"])},
    }


def validate(raw: dict[str, object], expected: dict[str, object]) -> dict[str, object]:
    if raw.get("schema") != "replaymark.sa1.native-source-adequacy-raw.v1":
        raise AssertionError("foreign SA1 raw schema")
    if raw.get("home_assistant_version") != EXPECTED_HA_VERSION:
        raise AssertionError("unexpected Home Assistant version")
    if raw.get("profile_configuration") != {
        "enable": True,
        "boost_entity": "UNSET",
        "eco_entity": "UNSET",
        "activity_entity": "UNSET",
        "writeback_enable": False,
        "writeback_bounds_enable": False,
    }:
        raise AssertionError("SA1 profile configuration changed")
    if expected.get("status") != "FROZEN_EXPECTED_PRE_LIVE":
        raise AssertionError("expected table is not pre-live frozen authority")
    rows = expected.get("rows")
    if not isinstance(rows, list) or len(rows) != 32 or _rows_sha(rows) != EXPECTED_ROWS_SHA256:
        raise AssertionError("expected semantic table identity changed")
    expected_by_id = {row["state_id"]: row for row in rows}
    if len(expected_by_id) != 32:
        raise AssertionError("expected semantic table state ids are not unique")

    cells = raw.get("cells")
    if not isinstance(cells, list) or len(cells) != 32 or raw.get("cell_count") != 32:
        raise AssertionError("native producer did not preserve the complete 32-state population")
    if len({cell.get("state_id") for cell in cells}) != 32 or {cell.get("state_id") for cell in cells} != set(expected_by_id):
        raise AssertionError("native state population differs from frozen expected population")

    details: list[dict[str, object]] = []
    exact = 0
    observed_calls = 0
    observed_no_calls = 0
    for cell in cells:
        state_id = cell["state_id"]
        row = expected_by_id[state_id]
        reasons: list[str] = []
        if cell.get("producer_error") is not None:
            reasons.append("producer_error")
        if cell.get("axes") != row.get("inputs"):
            reasons.append("axis_identity_mismatch")
        if cell.get("setup_call_events") != []:
            reasons.append("setup_contamination")

        exp_decision = _expected_decision_snapshot(row)
        if cell.get("decision_snapshot") != exp_decision:
            reasons.append("decision_snapshot_mismatch")
        pretrigger = cell.get("pretrigger_snapshot")
        if not isinstance(pretrigger, dict):
            reasons.append("missing_pretrigger_snapshot")
        else:
            opposite = "off" if row["inputs"]["presence"] else "on"
            if pretrigger.get("presence") != opposite:
                reasons.append("pretrigger_presence_not_opposite")
            for key in ("motion", "night", "enable", "climate_entity", "climate_state", "climate_preset"):
                if pretrigger.get(key) != exp_decision.get(key):
                    reasons.append(f"pretrigger_{key}_mismatch")

        trigger = cell.get("trigger")
        if not isinstance(trigger, dict):
            reasons.append("missing_trigger")
            trigger_context = None
        else:
            trigger_context = trigger.get("context_id")
            if trigger.get("entity_id") != PRESENCE_ENTITY:
                reasons.append("wrong_trigger_entity")
            if trigger.get("new_state") != exp_decision["presence"]:
                reasons.append("wrong_trigger_target_state")

        state_events = cell.get("measured_state_events")
        if not isinstance(state_events, list):
            reasons.append("missing_state_events")
            presence_matches = []
        else:
            presence_matches = [
                e for e in state_events
                if e.get("entity_id") == PRESENCE_ENTITY
                and e.get("context_id") == trigger_context
                and e.get("new_state") == exp_decision["presence"]
            ]
            if len(presence_matches) != 1:
                reasons.append("trigger_state_event_not_unique")

        service_events = cell.get("measured_service_events")
        try:
            observed_service = _service_observation(service_events if isinstance(service_events, list) else [])
        except Exception:
            observed_service = {"INVALID": True}
            reasons.append("malformed_or_multiple_service_events")
        expected_service = row.get("expected_native_service")
        if observed_service != expected_service:
            reasons.append("native_service_mismatch")

        if observed_service is None:
            observed_no_calls += 1
        elif observed_service != {"INVALID": True}:
            observed_calls += 1
            event = service_events[0]
            bound = event.get("context_id") == trigger_context or event.get("context_parent_id") == trigger_context
            if not bound:
                reasons.append("service_not_bound_to_trigger_context")

        post = cell.get("postdecision_snapshot")
        if not isinstance(post, dict):
            reasons.append("missing_postdecision_snapshot")
        else:
            if post.get("presence") != exp_decision["presence"] or post.get("motion") != exp_decision["motion"] or post.get("night") != exp_decision["night"]:
                reasons.append("postdecision_environment_drift")
            if post.get("climate_entity") != CLIMATE_ENTITY or post.get("climate_state") != "heat":
                reasons.append("postdecision_climate_identity_mismatch")
            if post.get("climate_preset") != row.get("expected_target_preset"):
                reasons.append("postdecision_preset_mismatch")

        passed = not reasons
        exact += int(passed)
        details.append({"state_id": state_id, "pass": passed, "reasons": reasons})

    passed = exact == 32 and observed_calls == 24 and observed_no_calls == 8
    return {
        "schema": "replaymark.sa1.independent-validation.v1",
        "replica": raw.get("replica"),
        "pass": passed,
        "exact_rows": exact,
        "total_rows": 32,
        "observed_exact_service_calls": observed_calls,
        "observed_no_consequential_call_rows": observed_no_calls,
        "expected_rows_sha256": EXPECTED_ROWS_SHA256,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    parser.add_argument("expected", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    result = validate(raw, expected)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("replica", "pass", "exact_rows", "observed_exact_service_calls", "observed_no_consequential_call_rows")}, sort_keys=True))
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
