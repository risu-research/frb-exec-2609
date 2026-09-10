from __future__ import annotations

"""Independent pure-JSON structural validator for sealed VE1 stage evidence.

It imports no Home Assistant, ReplayMark, AgentMark, target model, source parser,
execution gate, or expected-answer table. It checks only raw-evidence integrity,
fixture realization, context/cardinality boundaries, and cryptographic records.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping

STAGES = {"old_history", "new_direct", "replaymark", "replay_all"}
ROW_STATUSES = {
    "COMPLETE_OBSERVED",
    "COMPLETE_PROTOCOL_NONEXECUTABLE",
    "UNRESOLVED_RUNTIME",
    "INFRASTRUCTURE_INCOMPLETE",
}
CLOCK_DOMAIN = "python.perf_counter_ns"
CLIMATE_ENTITY = "climate.agentmark_thermostat"
ENTITY_BINDINGS = {
    "presence": "input_boolean.agentmark_presence",
    "motion": "binary_sensor.agentmark_motion",
    "night": "input_boolean.agentmark_night",
    "enable": "input_boolean.agentmark_enable",
    "climate": CLIMATE_ENTITY,
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"{name} must be a mapping")
    return value


def _completion(value: object) -> None:
    c = _mapping(value, "completion boundary")
    if (
        c.get("schema") != "replaymark.ve1.completed-boundary.v1"
        or c.get("witness") != "three_homeassistant_async_block_till_done_fixed_point_passes"
        or c.get("clock_domain") != CLOCK_DOMAIN
    ):
        raise AssertionError("completion witness changed")
    started, closed = int(c["started_ns"]), int(c["closed_ns"])
    if closed < started:
        raise AssertionError("completion closes before it starts")
    passes = list(c.get("passes") or [])
    if len(passes) != 3:
        raise AssertionError("completion witness pass count changed")
    last = started
    for index, item in enumerate(passes):
        p = _mapping(item, "completion pass")
        before, after = int(p["before_ns"]), int(p["after_ns"])
        if p.get("pass") != index or before < last or after < before:
            raise AssertionError("completion-pass order changed")
        last = after
    if closed < last:
        raise AssertionError("completion close precedes final pass")


def _observation(
    value: object,
    fixture: Mapping[str, object],
    *,
    presence_mode: str,
    require_current_preset: bool,
) -> None:
    o = _mapping(value, "raw observation")
    if (
        o.get("schema") != "replaymark.runtime.ha-bt-observation-record.v1"
        or o.get("capture_point") != "homeassistant.states.snapshot"
        or o.get("clock_domain") != CLOCK_DOMAIN
    ):
        raise AssertionError("observation boundary changed")
    if dict(_mapping(o.get("entities"), "observation entities")) != ENTITY_BINDINGS:
        raise AssertionError("observation entity binding changed")
    snap = _mapping(o.get("snapshot"), "observation snapshot")
    required = {
        "label", "t_ns", "presence", "motion", "night", "enable",
        "climate_state", "climate_preset",
    }
    if set(snap) != required:
        raise AssertionError("observation snapshot field set changed")
    final_presence = "on" if fixture["presence"] else "off"
    expected_presence = (
        ("off" if fixture["presence"] else "on")
        if presence_mode == "opposite"
        else final_presence
    )
    if presence_mode not in {"opposite", "final"}:
        raise AssertionError("invalid structural presence mode")
    if snap["presence"] != expected_presence:
        raise AssertionError(("fixture presence mismatch", presence_mode, snap["presence"]))
    if snap["motion"] != ("on" if fixture["motion"] else "off"):
        raise AssertionError("fixture motion mismatch")
    if snap["night"] != ("on" if fixture["night"] else "off"):
        raise AssertionError("fixture night mismatch")
    if snap["enable"] != "on" or snap["climate_state"] != "heat":
        raise AssertionError("observation left frozen scope")
    if require_current_preset and snap["climate_preset"] != fixture["current_preset"]:
        raise AssertionError("pre-action climate fixture mismatch")
    if isinstance(snap["t_ns"], bool) or not isinstance(snap["t_ns"], int) or snap["t_ns"] < 0:
        raise AssertionError("observation timestamp malformed")


def _parent(value: object, fixture: Mapping[str, object]) -> None:
    p = _mapping(value, "parent state event")
    expected = {"t_ns", "entity_id", "old_state", "new_state", "context_id", "context_parent_id"}
    if set(p) != expected or p["entity_id"] != "input_boolean.agentmark_presence":
        raise AssertionError("parent transition changed")
    final = "on" if fixture["presence"] else "off"
    old = "off" if fixture["presence"] else "on"
    if p["old_state"] != old or p["new_state"] != final:
        raise AssertionError("parent transition does not realize fixture presence")
    if not isinstance(p["context_id"], str) or not p["context_id"]:
        raise AssertionError("parent transition lacks context identity")


def _service_event(value: object) -> None:
    e = _mapping(value, "service event")
    if e.get("domain") != "climate" or e.get("service") != "set_preset_mode":
        raise AssertionError("foreign consequential service")
    data = _mapping(e.get("service_data"), "service_data")
    if set(data) != {"entity_id", "preset_mode"}:
        raise AssertionError("consequential service_data field set changed")
    raw_target = data["entity_id"]
    targets = [raw_target] if isinstance(raw_target, str) else list(raw_target or [])
    if targets != [CLIMATE_ENTITY]:
        raise AssertionError("foreign consequential target")
    preset = data["preset_mode"]
    if not isinstance(preset, str) or not preset or preset != preset.strip():
        raise AssertionError("noncanonical preset_mode")
    if (
        not isinstance(e.get("context_id"), str)
        or not e.get("context_id")
        or isinstance(e.get("t_ns"), bool)
        or not isinstance(e.get("t_ns"), int)
        or int(e["t_ns"]) < 0
    ):
        raise AssertionError("noncanonical consequential event")


def _historical(value: object) -> None:
    h = _mapping(value, "historical action")
    if (
        h.get("schema") != "replaymark.runtime.ha-bt-historical-action-record.v1"
        or h.get("capture_point") != "homeassistant.event_bus.EVENT_CALL_SERVICE"
        or h.get("clock_domain") != CLOCK_DOMAIN
    ):
        raise AssertionError("historical-action boundary changed")
    e = _mapping(h.get("service_event"), "historical service event")
    p = _mapping(h.get("parent_state_event"), "historical parent event")
    _service_event(e)
    if e.get("context_parent_id") != p.get("context_id") or int(p["t_ns"]) > int(e["t_ns"]):
        raise AssertionError("historical action lost parent binding")


def _verify_record_digest(row: Mapping[str, object]) -> None:
    observed = str(row.get("record_sha256") or "")
    if len(observed) != 64:
        raise AssertionError("row lacks record digest")
    if _sha({k: v for k, v in row.items() if k != "record_sha256"}) != observed:
        raise AssertionError("row record digest mismatch")


def _validate_native(row: Mapping[str, object], stage: str) -> None:
    fixture = _mapping(row["fixture"], "fixture")
    if row["status"] != "COMPLETE_OBSERVED":
        return
    _observation(
        row["base_raw_observation"], fixture,
        presence_mode="opposite", require_current_preset=True,
    )
    _parent(row["parent_state_event"], fixture)
    _completion(row["completion_boundary"])
    events = list(row.get("qualifying_service_events") or [])
    foreign = list(row.get("foreign_service_events") or [])
    if foreign or len(events) > 1:
        raise AssertionError("completed native row has ambiguous event boundary")
    trigger = str(row["trigger_context_id"])
    for event in events:
        _service_event(event)
        if event.get("context_id") != trigger and event.get("context_parent_id") != trigger:
            raise AssertionError("native consequential event is not trigger-context bound")
    _observation(
        row["post_boundary_observation"], fixture,
        presence_mode="final", require_current_preset=False,
    )
    historical = list(row.get("historical_action_records") or [])
    if stage == "old_history":
        if len(historical) != len(events):
            raise AssertionError("Old-history wrapper cardinality differs from raw event cardinality")
        for value in historical:
            _historical(value)
    elif historical:
        raise AssertionError("non-Old native stage emitted historical wrapper")


def _validate_caller(value: object, fixture: Mapping[str, object]) -> None:
    c = _mapping(value, "caller-native recovery")
    if (
        c.get("schema") != "replaymark.ve1.caller-native-recovery.v1"
        or c.get("status") != "COMPLETE_OBSERVED"
        or c.get("channel") != "CALLER_NATIVE_AUTOMATION_TRIGGER"
    ):
        raise AssertionError("caller-native recovery boundary changed")
    _completion(c["completion_boundary"])
    events = list(c.get("qualifying_service_events") or [])
    if c.get("foreign_service_events") or len(events) > 1:
        raise AssertionError("caller-native recovery event boundary ambiguous")
    trigger = str(c["trigger_context_id"])
    for event in events:
        _service_event(event)
        if event.get("context_id") != trigger and event.get("context_parent_id") != trigger:
            raise AssertionError("caller-native event is not trigger-context bound")
    if int(c["completed_ns"]) < int(c["started_ns"]):
        raise AssertionError("caller-native completion precedes invocation")
    _observation(
        c["post_boundary_observation"], fixture,
        presence_mode="final", require_current_preset=False,
    )


def _validate_replaymark(row: Mapping[str, object]) -> None:
    if row["status"] == "COMPLETE_PROTOCOL_NONEXECUTABLE":
        if row.get("historical_raw_action") is not None:
            raise AssertionError("nonexecutable ReplayMark row unexpectedly contains history")
        return
    if row["status"] != "COMPLETE_OBSERVED":
        return
    fixture = _mapping(row["fixture"], "fixture")
    _historical(row["historical_raw_action"])
    _observation(
        row["base_raw_observation"], fixture,
        presence_mode="opposite", require_current_preset=True,
    )
    _parent(row["target_parent_state_event"], fixture)
    _completion(row["target_transition_completion"])
    cert = _mapping(row["presented_certificate"], "certificate")
    receipt = _mapping(row["gate_receipt"], "gate receipt")
    if (
        str(row["presented_certificate_fingerprint"])
        != str(receipt.get("presented_certificate_fingerprint"))
        or receipt.get("presented_certificate_fingerprint")
        != receipt.get("recomputed_certificate_fingerprint")
    ):
        raise AssertionError("gate certificate identity mismatch")
    sink = list(row.get("historical_sink_events") or [])
    if bool(receipt.get("execution_performed")):
        if len(sink) != 1 or row.get("caller_native") is not None:
            raise AssertionError("executed ReplayMark sink/recovery cardinality mismatch")
        _service_event(sink[0])
        dispatch = str(receipt.get("dispatch_context_id") or "")
        if sink[0].get("context_id") != dispatch and sink[0].get("context_parent_id") != dispatch:
            raise AssertionError("historical sink event is not gate-dispatch bound")
    else:
        if sink:
            raise AssertionError("nonexecuted ReplayMark row crossed historical sink")
        _validate_caller(row["caller_native"], fixture)
    _completion(row["historical_sink_completion"])
    _observation(
        row["post_boundary_observation"], fixture,
        presence_mode="final", require_current_preset=False,
    )
    if cert.get("execution_performed") is not False:
        raise AssertionError("shadow certificate unexpectedly owns execution")


def _validate_replay_all(row: Mapping[str, object]) -> None:
    if row["status"] == "COMPLETE_PROTOCOL_NONEXECUTABLE":
        if row.get("historical_raw_action") is not None:
            raise AssertionError("nonexecutable Replay-All row unexpectedly contains history")
        return
    if row["status"] != "COMPLETE_OBSERVED":
        return
    fixture = _mapping(row["fixture"], "fixture")
    _historical(row["historical_raw_action"])
    _observation(
        row["pre_dispatch_observation"], fixture,
        presence_mode="final", require_current_preset=True,
    )
    _completion(row["completion_boundary"])
    events = list(row.get("sink_events") or [])
    if len(events) != 1:
        raise AssertionError("completed Replay-All row lacks exactly one sink event")
    _service_event(events[0])
    dispatch = str(row["dispatch_context_id"])
    if events[0].get("context_id") != dispatch and events[0].get("context_parent_id") != dispatch:
        raise AssertionError("Replay-All event is not dispatch-context bound")
    if int(row["dispatch_completed_ns"]) < int(row["dispatch_started_ns"]):
        raise AssertionError("Replay-All completion precedes dispatch")
    _observation(
        row["post_boundary_observation"], fixture,
        presence_mode="final", require_current_preset=False,
    )


def validate(report: Mapping[str, object]) -> dict[str, object]:
    if (
        report.get("schema") != "replaymark.ve1.native-stage.v1"
        or report.get("mode") != "AUTHORITATIVE_FIRST_COMPLETE_STAGE"
    ):
        raise AssertionError("foreign VE1 report")
    stage, replica = str(report.get("stage")), int(report.get("replica"))
    if stage not in STAGES or replica not in (0, 1) or report.get("fatal_failure") is not None:
        raise AssertionError("invalid or failed VE1 stage report")
    if (
        report.get("ha_version") != "2026.9.0"
        or report.get("state_count") != 32
        or report.get("sampling") != "none"
        or report.get("scientific_summary_emitted") is not False
    ):
        raise AssertionError("VE1 stage contract changed")
    rows = list(report.get("rows") or [])
    if len(rows) != 32 or [r.get("opaque_state_id") for r in rows] != [
        f"VE1-S{i:02d}" for i in range(32)
    ]:
        raise AssertionError("VE1 row population/order changed")

    status_counts = {name: 0 for name in sorted(ROW_STATUSES)}
    for row in rows:
        r = _mapping(row, "row")
        if (
            r.get("schema") != "replaymark.ve1.native-row.v1"
            or r.get("stage") != stage
            or int(r.get("replica")) != replica
            or r.get("status") not in ROW_STATUSES
        ):
            raise AssertionError("VE1 row identity/status changed")
        status_counts[str(r["status"])] += 1
        _verify_record_digest(r)
        if stage in {"old_history", "new_direct"}:
            _validate_native(r, stage)
        elif stage == "replaymark":
            _validate_replaymark(r)
        else:
            _validate_replay_all(r)

    body = dict(report)
    observed = str(body.pop("report_sha256"))
    if _sha(body) != observed:
        raise AssertionError("VE1 report digest mismatch")
    return {
        "schema": "replaymark.ve1.independent-structural-validation.v1",
        "status": "PASS",
        "stage": stage,
        "replica": replica,
        "rows": 32,
        "row_status_counts": status_counts,
        "scientific_interpretation_performed": False,
        "imports_production_semantics": False,
        "imports_homeassistant": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = validate(json.loads(Path(args.report).read_text(encoding="utf-8")))
    Path(args.out).write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {"status": "PASS", "stage": result["stage"], "replica": result["replica"]},
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
