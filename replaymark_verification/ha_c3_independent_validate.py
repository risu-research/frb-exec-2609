from __future__ import annotations

"""Independent pure-JSON validator for HA-C3 live execution.

This module imports no ReplayMark production code, compiled contract, execution
gate, Home Assistant module, or C2 native target.  It reconstructs target support
literally from retained raw state/event material and checks execution provenance
against that independent support judgment.
"""

import argparse
import json
from pathlib import Path
from typing import Mapping

CLIMATE_ENTITY = "climate.agentmark_thermostat"


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"{name} must be a mapping")
    return value


def _bool_state(value: object) -> bool:
    if value == "on":
        return True
    if value == "off":
        return False
    raise AssertionError(("non-binary HA state", value))


def _state_from_boundary(base_raw: object, parent_event: object) -> tuple[bool, bool, bool, str]:
    raw = _mapping(base_raw, "base observation")
    snap = dict(_mapping(raw["snapshot"], "snapshot"))
    event = _mapping(parent_event, "parent event")
    role = {
        "input_boolean.agentmark_presence": "presence",
        "input_boolean.agentmark_night": "night",
    }.get(str(event["entity_id"]))
    if role is None:
        raise AssertionError("foreign target trigger entity")
    if snap[role] != event["old_state"]:
        raise AssertionError("target parent old_state does not match base observation")
    if int(event["t_ns"]) < int(snap["t_ns"]):
        raise AssertionError("target parent event precedes base observation")
    snap[role] = event["new_state"]
    preset = str(snap["climate_preset"])
    if preset not in {"away", "home", "comfort", "sleep"}:
        raise AssertionError(("foreign current preset", preset))
    return (
        _bool_state(snap["presence"]),
        _bool_state(snap["motion"]),
        _bool_state(snap["night"]),
        preset,
    )


def _literal_projection(state: tuple[bool, bool, bool, str]) -> dict[str, str]:
    presence, motion, night, current = state
    desired = "sleep" if night else "away" if not presence else "comfort" if motion else "home"
    if current == desired:
        return {
            "operation": "NO_ACTION",
            "concrete_target": CLIMATE_ENTITY,
            "variant": "NO_ACTION",
        }
    return {
        "operation": "climate.set_preset_mode",
        "concrete_target": CLIMATE_ENTITY,
        "variant": json.dumps({"preset_mode": desired}, sort_keys=True, separators=(",", ":")),
    }


def _service_projection(event: object) -> dict[str, str]:
    e = _mapping(event, "service event")
    if str(e.get("domain")) != "climate" or str(e.get("service")) != "set_preset_mode":
        raise AssertionError(("foreign consequential service", e.get("domain"), e.get("service")))
    data = _mapping(e["service_data"], "service_data")
    if set(data) != {"entity_id", "preset_mode"}:
        raise AssertionError(("unexpected service_data fields", sorted(data)))
    raw_target = data["entity_id"]
    if isinstance(raw_target, str):
        targets = [raw_target]
    elif isinstance(raw_target, (list, tuple)):
        targets = [str(x) for x in raw_target]
    else:
        raise AssertionError("unresolved service target")
    if targets != [CLIMATE_ENTITY]:
        raise AssertionError(("foreign service target", targets))
    preset = str(data["preset_mode"])
    return {
        "operation": "climate.set_preset_mode",
        "concrete_target": CLIMATE_ENTITY,
        "variant": json.dumps({"preset_mode": preset}, sort_keys=True, separators=(",", ":")),
    }


def _historical_projection(raw: object) -> dict[str, str]:
    return _service_projection(_mapping(raw, "historical raw action")["service_event"])


def _after_preset(raw: object) -> str:
    return str(_mapping(_mapping(raw, "after observation")["snapshot"], "after snapshot")["climate_preset"])


def _preset_from_projection(projection: Mapping[str, str]) -> str:
    if projection["operation"] == "NO_ACTION":
        raise AssertionError("HA-C3 result-bearing support unexpectedly became NO_ACTION")
    value = json.loads(projection["variant"])
    return str(value["preset_mode"])


def _validate_decision(
    family: str,
    index: int,
    direct: Mapping[str, object],
    gate: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, int]]:
    if gate.get("pipeline_failure") is not None or gate.get("native_failure") is not None:
        raise AssertionError(("gate decision failure", family, index, gate.get("pipeline_failure"), gate.get("native_failure")))

    direct_support = _literal_projection(
        _state_from_boundary(direct["base_raw_observation"], direct["parent_state_event"])
    )
    direct_projection = _service_projection(direct["service_event"])
    if direct_projection != direct_support:
        raise AssertionError(("Direct disagrees with literal target law", family, index, direct_projection, direct_support))

    support = _literal_projection(
        _state_from_boundary(gate["base_raw_observation"], gate["parent_state_event"])
    )
    if support != direct_support:
        raise AssertionError(("Direct and ReplayMark target states imply different consequences", family, index, support, direct_support))

    historical = _historical_projection(gate["historical_raw_action"])
    if gate.get("historical_projection") != historical:
        raise AssertionError(("producer historical projection mismatch", family, index))
    valid = historical == support
    expected_admission = "ADMIT_REUSE" if valid else "BLOCK_REUSE"

    receipt = _mapping(gate["gate_receipt"], "gate receipt")
    if receipt["admission_disposition"] != expected_admission:
        raise AssertionError(("gate admission disagrees with independent support", family, index, receipt["admission_disposition"], expected_admission))
    presented_fp = str(gate["presented_certificate_fingerprint"])
    if presented_fp != str(receipt["presented_certificate_fingerprint"]):
        raise AssertionError(("presented certificate fingerprint lost at gate", family, index))
    if str(receipt["presented_certificate_fingerprint"]) != str(receipt["recomputed_certificate_fingerprint"]):
        raise AssertionError(("gate receipt records certificate/raw mismatch", family, index))

    historical_events = list(gate.get("historical_service_events") or [])
    native = gate.get("caller_native")
    metrics = {
        "decisions": 1,
        "admit": 0,
        "block": 0,
        "safe_history_executed": 0,
        "blocked_native_restored": 0,
        "unsafe_historical_calls": 0,
        "unnecessary_native_recoveries": 0,
        "certificate_raw_mismatch_admitted": 0,
        "direct_reference_disagreements": 0,
    }

    if valid:
        metrics["admit"] = 1
        if receipt["execution_performed"] is not True:
            raise AssertionError(("safe history was not executed", family, index))
        if len(historical_events) != 1:
            raise AssertionError(("safe history sink cardinality", family, index, len(historical_events)))
        actual_historical = _service_projection(historical_events[0])
        if actual_historical != historical or historical != support:
            raise AssertionError(("admitted historical sink action changed", family, index, actual_historical, historical, support))
        if native is not None:
            metrics["unnecessary_native_recoveries"] += 1
            raise AssertionError(("safe history also entered caller-native path", family, index))
        if str(historical_events[0].get("context_id")) != str(receipt["dispatch_context_id"]):
            raise AssertionError(("historical service event not bound to gate dispatch context", family, index))
        metrics["safe_history_executed"] = 1
        final_projection = actual_historical
    else:
        metrics["block"] = 1
        if receipt["execution_performed"] is not False:
            metrics["unsafe_historical_calls"] += 1
            raise AssertionError(("unsupported history marked executed", family, index))
        if historical_events:
            metrics["unsafe_historical_calls"] += len(historical_events)
            raise AssertionError(("blocked history reached sink", family, index, len(historical_events)))
        if not isinstance(native, Mapping) or native.get("channel") != "CALLER_NATIVE_AUTOMATION_TRIGGER":
            raise AssertionError(("blocked history did not enter caller-owned native path", family, index))
        native_event = _mapping(native["service_event"], "caller-native service event")
        native_projection = _service_projection(native_event)
        if native_projection != support or native.get("projection") != support:
            raise AssertionError(("caller-native consequence disagrees with literal target law", family, index, native_projection, support))
        trigger = str(native["trigger_context_id"])
        native_context = str(native_event.get("context_id"))
        native_parent = native_event.get("context_parent_id")
        if native_context != trigger and (native_parent is None or str(native_parent) != trigger):
            raise AssertionError(("caller-native action lacks invocation context binding", family, index))
        if int(native["completed_ns"]) < int(native["started_ns"]):
            raise AssertionError(("caller-native completion precedes invocation", family, index))
        metrics["blocked_native_restored"] = 1
        final_projection = native_projection

    expected_preset = _preset_from_projection(support)
    if _after_preset(gate["after_raw_observation"]) != expected_preset:
        raise AssertionError(("ReplayMark target final preset mismatch", family, index))
    if _after_preset(direct["after_raw_observation"]) != expected_preset:
        metrics["direct_reference_disagreements"] += 1
        raise AssertionError(("Direct final preset mismatch", family, index))
    if final_projection != direct_projection:
        metrics["direct_reference_disagreements"] += 1
        raise AssertionError(("final ReplayMark consequence differs from Direct", family, index, final_projection, direct_projection))

    return {
        "family": family,
        "decision_index": index,
        "target_support": support,
        "historical_projection": historical,
        "direct_projection": direct_projection,
        "independently_valid_history": valid,
        "expected_admission": expected_admission,
        "observed_admission": receipt["admission_disposition"],
        "final_projection": final_projection,
        "pass": True,
    }, metrics


def validate(report: Mapping[str, object]) -> dict[str, object]:
    if report.get("schema") != "replaymark.ha-c3.live-native-execution.v1":
        raise AssertionError("foreign HA-C3 report schema")
    if report.get("mode") != "AUTHORITATIVE_LIVE_FIRST_COMPLETE":
        raise AssertionError("HA-C3 validator received non-scientific mode")
    if report.get("fatal_failure") is not None:
        raise AssertionError(("producer fatal failure", report.get("fatal_failure")))
    if report.get("native_path_qualification", {}).get("status") != "PASS":
        raise AssertionError("caller-native path was not prequalified")
    if report.get("carrier_population") != {"n2": 10, "n2b_pairs": 10, "sampling": "none"}:
        raise AssertionError(("carrier population changed", report.get("carrier_population")))
    if report.get("planned_live_decisions") != 30:
        raise AssertionError("planned decision count changed")

    families = list(report.get("families") or [])
    if len(families) != 20:
        raise AssertionError(("family count", len(families)))
    n2 = [f for f in families if f.get("family") == "N2"]
    n2b = [f for f in families if f.get("family") == "N2b"]
    if len(n2) != 10 or len(n2b) != 10:
        raise AssertionError(("family strata", len(n2), len(n2b)))
    if sorted(int(f["carrier_ordinal"]) for f in n2) != list(range(10)):
        raise AssertionError("N2 carrier ordinals changed")
    if sorted(int(f["carrier_ordinal"]) for f in n2b) != list(range(10)):
        raise AssertionError("N2b carrier ordinals changed")

    totals = {
        "decisions": 0,
        "admit": 0,
        "block": 0,
        "safe_history_executed": 0,
        "blocked_native_restored": 0,
        "unsafe_historical_calls": 0,
        "unnecessary_native_recoveries": 0,
        "certificate_raw_mismatch_admitted": 0,
        "direct_reference_disagreements": 0,
        "n2b_cutovers": 0,
    }
    details: list[dict[str, object]] = []

    for family_row in families:
        family = str(family_row["family"])
        direct = _mapping(family_row["direct"], "Direct family")
        gate = _mapping(family_row["gate"], "gate family")
        if direct.get("status") != "COMPLETE" or gate.get("status") != "COMPLETE":
            raise AssertionError(("incomplete family", family, family_row["carrier_ordinal"], direct.get("failure"), gate.get("failure")))
        direct_decisions = list(direct.get("decisions") or [])
        gate_decisions = list(gate.get("decisions") or [])
        expected_len = 1 if family == "N2" else 2
        if len(direct_decisions) != expected_len or len(gate_decisions) != expected_len:
            raise AssertionError(("family decision cardinality", family, len(direct_decisions), len(gate_decisions)))
        family_details = []
        for index in range(expected_len):
            detail, metrics = _validate_decision(family, index, direct_decisions[index], gate_decisions[index])
            family_details.append(detail)
            details.append({"carrier_ordinal": family_row["carrier_ordinal"], **detail})
            for key, value in metrics.items():
                totals[key] += value
        if family == "N2":
            if family_details[0]["observed_admission"] != "BLOCK_REUSE":
                raise AssertionError("N2 did not realize frozen BLOCK pattern")
        else:
            if [d["observed_admission"] for d in family_details] != ["ADMIT_REUSE", "BLOCK_REUSE"]:
                raise AssertionError(("N2b did not realize ADMIT->BLOCK cutover", family_row["carrier_ordinal"]))
            totals["n2b_cutovers"] += 1

    expected = {
        "decisions": 30,
        "admit": 10,
        "block": 20,
        "safe_history_executed": 10,
        "blocked_native_restored": 20,
        "unsafe_historical_calls": 0,
        "unnecessary_native_recoveries": 0,
        "certificate_raw_mismatch_admitted": 0,
        "direct_reference_disagreements": 0,
        "n2b_cutovers": 10,
    }
    if totals != expected:
        raise AssertionError(("HA-C3 per-replica promotion totals", totals, expected))

    return {
        "schema": "replaymark.ha-c3.independent-validation.v1",
        "status": "PASS",
        "replica": report["replica"],
        "imports_replaymark": False,
        "imports_homeassistant": False,
        "metrics": totals,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    try:
        result = validate(report)
        rc = 0
    except Exception as exc:
        result = {
            "schema": "replaymark.ha-c3.independent-validation.v1",
            "status": "FAIL",
            "replica": report.get("replica"),
            "failure": f"{type(exc).__name__}: {exc}",
            "imports_replaymark": False,
            "imports_homeassistant": False,
        }
        rc = 1
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
