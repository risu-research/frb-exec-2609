from __future__ import annotations

"""VE1 label-firewalled native execution producer.

This module contains orchestration only. It never loads the frozen answer table,
never computes a source-version frontier, and never prints per-state scientific
outcomes. Raw native evidence is retained for a later independent adjudicator.
"""

import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import Context

from agentmark_natural_controllers.better_thermostat import experiment_persisted_ownership as base
from agentmark_natural_controllers.better_thermostat import n2_horizon_runtime as horizon

from replaymark.runtime_ha_bt_execution_gate import HaBtCertifiedExecutionGate
from replaymark.runtime_ha_bt_shadow_bridge import certify_ha_bt_shadow_reuse
from replaymark_verification.ha_c2_bt_native_target import compile_c2_contract

SCHEMA = "replaymark.ve1.native-stage.v1"
ROW_SCHEMA = "replaymark.ve1.native-row.v1"
ABSENCE_SCHEMA = "replaymark.ve1.completed-boundary.v1"
HISTORICAL_SCHEMA = "replaymark.runtime.ha-bt-historical-action-record.v1"
EXPECTED_HA_VERSION = "2026.9.0"
CLOCK_DOMAIN = "python.perf_counter_ns"
CAPTURE_POINT = "homeassistant.event_bus.EVENT_CALL_SERVICE"
CLIMATE_ENTITY = "climate.agentmark_thermostat"
ENTITY_BINDINGS = {
    "presence": "input_boolean.agentmark_presence",
    "motion": "binary_sensor.agentmark_motion",
    "night": "input_boolean.agentmark_night",
    "enable": "input_boolean.agentmark_enable",
    "climate": CLIMATE_ENTITY,
}
STAGES = {"old_history", "new_direct", "replaymark", "replay_all"}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_ns() -> int:
    return time.perf_counter_ns()


def _onoff(value: bool) -> str:
    return "on" if value else "off"


def _load_state_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "replaymark.ve1.execution-state-manifest.v1":
        raise AssertionError("foreign VE1 execution-state manifest")
    if value.get("state_count") != 32:
        raise AssertionError("VE1 execution-state count changed")
    states = value.get("states")
    if not isinstance(states, list) or len(states) != 32:
        raise AssertionError("VE1 execution-state rows malformed")
    expected = []
    i = 0
    for presence in (False, True):
        for motion in (False, True):
            for night in (False, True):
                for current in ("away", "home", "comfort", "sleep"):
                    expected.append({"opaque_state_id": f"VE1-S{i:02d}", "fixture": {"presence": presence, "motion": motion, "night": night, "current_preset": current}})
                    i += 1
    if states != expected:
        raise AssertionError("VE1 execution-state manifest differs from frozen Cartesian projection")
    banned = {"target_preset", "old_expected_action", "new_expected_action", "compatibility", "expected_counts", "COMPATIBLE_ACROSS_VERSION", "RETIRED_BY_UPDATE"}
    for row in states:
        if any(token in json.dumps(row, sort_keys=True) for token in banned):
            raise AssertionError("answer-bearing field leaked into execution-state row")
    return value


def _raw_observation(hass: Any, *, label: str) -> dict[str, object]:
    snap = horizon.current_snapshot(hass, label=label)
    return {"schema": "replaymark.runtime.ha-bt-observation-record.v1", "capture_point": "homeassistant.states.snapshot", "clock_domain": CLOCK_DOMAIN, "entities": dict(ENTITY_BINDINGS), "snapshot": snap}


def _automation_entity(hass: Any) -> str:
    values = sorted(s.entity_id for s in hass.states.async_all() if s.entity_id.startswith("automation."))
    if len(values) != 1:
        raise AssertionError(("expected exactly one installed automation", values))
    return values[0]


async def _set_automation(hass: Any, entity: str, enabled: bool) -> None:
    await hass.services.async_call("automation", "turn_on" if enabled else "turn_off", {"entity_id": entity}, blocking=True)
    await hass.async_block_till_done()
    state = hass.states.get(entity)
    wanted = "on" if enabled else "off"
    if state is None or state.state != wanted:
        raise AssertionError(("automation state did not converge", entity, wanted))


async def _completion_boundary(hass: Any) -> dict[str, object]:
    started = _now_ns()
    passes = []
    for index in range(3):
        before = _now_ns()
        await hass.async_block_till_done()
        await asyncio.sleep(0)
        after = _now_ns()
        passes.append({"pass": index, "before_ns": before, "after_ns": after})
    return {"schema": ABSENCE_SCHEMA, "witness": "three_homeassistant_async_block_till_done_fixed_point_passes", "clock_domain": CLOCK_DOMAIN, "started_ns": started, "closed_ns": _now_ns(), "passes": passes}


def _parent_event(observer: horizon.HorizonObserver, *, start_index: int, context_id: str, old_state: str, new_state: str) -> dict[str, object]:
    candidates = [e for e in observer.state_events[start_index:] if str(e.get("entity_id")) == base.PRESENCE_ENTITY and str(e.get("old_state")) == old_state and str(e.get("new_state")) == new_state and str(e.get("context_id")) == context_id]
    if len(candidates) != 1:
        raise AssertionError(("presence parent-event cardinality", len(candidates)))
    event = candidates[0]
    return {"t_ns": int(event["t_ns"]), "entity_id": str(event["entity_id"]), "old_state": str(event["old_state"]), "new_state": str(event["new_state"]), "context_id": str(event["context_id"]), "context_parent_id": event.get("context_parent_id")}


def _normalize_service_data(event: Mapping[str, object]) -> dict[str, object]:
    data = dict(event.get("service_data") or {})
    if set(data) != {"entity_id", "preset_mode"}:
        raise AssertionError(("consequential service_data field set", sorted(data)))
    raw_target = data["entity_id"]
    if isinstance(raw_target, str):
        targets = [raw_target]
    elif isinstance(raw_target, (list, tuple)):
        targets = [str(v) for v in raw_target]
    else:
        raise AssertionError("unresolved consequential target")
    if targets != [CLIMATE_ENTITY]:
        raise AssertionError(("foreign consequential target", targets))
    preset = str(data["preset_mode"])
    if not preset or preset != preset.strip():
        raise AssertionError("noncanonical preset value")
    return {"entity_id": targets, "preset_mode": preset}


def _historical_record(event: Mapping[str, object], parent: Mapping[str, object]) -> dict[str, object]:
    if str(event.get("domain")) != "climate" or str(event.get("service")) != "set_preset_mode":
        raise AssertionError("foreign consequential service")
    service_data = _normalize_service_data(event)
    service_context = str(event.get("context_id") or "")
    service_parent = event.get("context_parent_id")
    if not service_context or service_parent is None or str(service_parent) != str(parent["context_id"]):
        raise AssertionError("historical service is not bound to retained parent transition")
    return {"schema": HISTORICAL_SCHEMA, "capture_point": CAPTURE_POINT, "clock_domain": CLOCK_DOMAIN, "service_event": {"t_ns": int(event["t_ns"]), "domain": "climate", "service": "set_preset_mode", "service_data": service_data, "context_id": service_context, "context_parent_id": str(service_parent)}, "parent_state_event": dict(parent)}


def _context_bound(event: Mapping[str, object], context_id: str) -> bool:
    child = str(event.get("context_id") or "")
    parent = event.get("context_parent_id")
    return child == context_id or (parent is not None and str(parent) == context_id)


async def _seed_current_preset(hass: Any, value: str) -> None:
    if value not in {"away", "home", "comfort", "sleep"}:
        raise AssertionError(("foreign fixture preset", value))
    hass.states.async_set(CLIMATE_ENTITY, "heat", {"preset_mode": value, "temperature": 20.0}, context=Context())
    await hass.async_block_till_done()
    state = hass.states.get(CLIMATE_ENTITY)
    if state is None or state.state != "heat" or state.attributes.get("preset_mode") != value:
        raise AssertionError("fixture climate state did not converge")


async def _fresh_for_fixture(*, blueprint: Path, qualification: dict[str, object], fixture: Mapping[str, object]) -> tuple[Any, Any, Any, dict[str, object], horizon.HorizonObserver, str]:
    final_presence = bool(fixture["presence"])
    hass, lab, temp, registry, observer = await horizon.fresh_native(blueprint_source=blueprint, qualification=qualification, presence=_onoff(not final_presence), motion=_onoff(bool(fixture["motion"])), night=_onoff(bool(fixture["night"])))
    entity = _automation_entity(hass)
    await _set_automation(hass, entity, False)
    if observer.service_events:
        raise AssertionError("consequential action occurred before fixture seeding")
    await _seed_current_preset(hass, str(fixture["current_preset"]))
    if observer.service_events:
        raise AssertionError("fixture seeding emitted consequential service action")
    return hass, lab, temp, registry, observer, entity


async def _cleanup(hass: Any, lab: Any, temp: Any, observer: horizon.HorizonObserver) -> None:
    observer.close()
    await base.cleanup_hass(hass, lab, temp)


async def _native_transition(*, hass: Any, observer: horizon.HorizonObserver, automation_entity: str, fixture: Mapping[str, object], label: str) -> dict[str, object]:
    final_presence = bool(fixture["presence"])
    old_state = _onoff(not final_presence)
    new_state = _onoff(final_presence)
    base_raw = _raw_observation(hass, label=f"{label}_base")
    before_state = len(observer.state_events)
    before_service = len(observer.service_events)
    await _set_automation(hass, automation_entity, True)
    if len(observer.service_events) != before_service:
        raise AssertionError("automation enable emitted consequential action")
    trigger = Context()
    hass.states.async_set(base.PRESENCE_ENTITY, new_state, context=trigger)
    completion = await _completion_boundary(hass)
    parent = _parent_event(observer, start_index=before_state, context_id=str(trigger.id), old_state=old_state, new_state=new_state)
    events = copy.deepcopy(observer.service_events[before_service:])
    await _set_automation(hass, automation_entity, False)
    if len(observer.service_events) != before_service + len(events):
        raise AssertionError("automation disable raced a consequential action")
    after = _raw_observation(hass, label=f"{label}_after")
    bound = [e for e in events if _context_bound(e, str(trigger.id))]
    foreign = [e for e in events if not _context_bound(e, str(trigger.id))]
    records = [_historical_record(event, parent) for event in bound]
    status = "COMPLETE_OBSERVED"
    reason = None
    if foreign or len(bound) > 1:
        status = "UNRESOLVED_RUNTIME"
        reason = "ambiguous consequential event cardinality or foreign invocation context"
    return {"status": status, "reason": reason, "base_raw_observation": base_raw, "parent_state_event": parent, "trigger_context_id": str(trigger.id), "completion_boundary": completion, "qualifying_service_events": bound, "foreign_service_events": foreign, "historical_action_records": records, "post_boundary_observation": after}


async def _caller_native_recovery(hass: Any, observer: horizon.HorizonObserver, automation_entity: str, *, label: str) -> dict[str, object]:
    before = len(observer.service_events)
    await _set_automation(hass, automation_entity, True)
    if len(observer.service_events) != before:
        raise AssertionError("automation enable emitted consequential action")
    trigger = Context()
    started = _now_ns()
    await hass.services.async_call("automation", "trigger", {"entity_id": automation_entity, "skip_condition": False}, blocking=True, context=trigger)
    completion = await _completion_boundary(hass)
    completed = _now_ns()
    events = copy.deepcopy(observer.service_events[before:])
    await _set_automation(hass, automation_entity, False)
    bound = [e for e in events if _context_bound(e, str(trigger.id))]
    foreign = [e for e in events if not _context_bound(e, str(trigger.id))]
    status = "COMPLETE_OBSERVED" if not foreign and len(bound) <= 1 else "UNRESOLVED_RUNTIME"
    reason = None if status == "COMPLETE_OBSERVED" else "caller-native recovery event boundary ambiguous"
    return {"schema": "replaymark.ve1.caller-native-recovery.v1", "status": status, "reason": reason, "channel": "CALLER_NATIVE_AUTOMATION_TRIGGER", "trigger_context_id": str(trigger.id), "started_ns": started, "completed_ns": completed, "completion_boundary": completion, "qualifying_service_events": bound, "foreign_service_events": foreign, "post_boundary_observation": _raw_observation(hass, label=f"{label}_caller_after")}


def _row_base(*, stage: str, replica: int, state: Mapping[str, object]) -> dict[str, object]:
    return {"schema": ROW_SCHEMA, "stage": stage, "replica": replica, "opaque_state_id": state["opaque_state_id"], "fixture": copy.deepcopy(state["fixture"]), "status": None, "failure": None}


async def _native_source_row(*, stage: str, replica: int, state: Mapping[str, object], blueprint: Path, qualification: dict[str, object]) -> dict[str, object]:
    row = _row_base(stage=stage, replica=replica, state=state)
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer, entity = await _fresh_for_fixture(blueprint=blueprint, qualification=qualification, fixture=state["fixture"])
        native = await _native_transition(hass=hass, observer=observer, automation_entity=entity, fixture=state["fixture"], label=f"ve1_{stage}_{replica}_{state['opaque_state_id']}")
        row.update({"status": native["status"], "failure": native["reason"], "registry": registry, "base_raw_observation": native["base_raw_observation"], "parent_state_event": native["parent_state_event"], "trigger_context_id": native["trigger_context_id"], "completion_boundary": native["completion_boundary"], "qualifying_service_events": native["qualifying_service_events"], "foreign_service_events": native["foreign_service_events"], "historical_action_records": native["historical_action_records"] if stage == "old_history" else [], "post_boundary_observation": native["post_boundary_observation"]})
    except Exception as exc:
        row["status"] = "INFRASTRUCTURE_INCOMPLETE"
        row["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if hass is not None and lab is not None and temp is not None and observer is not None:
            try:
                await _cleanup(hass, lab, temp, observer)
            except Exception as exc:
                if row["status"] == "COMPLETE_OBSERVED":
                    row["status"] = "INFRASTRUCTURE_INCOMPLETE"
                    row["failure"] = f"CLEANUP_FAILURE: {type(exc).__name__}: {exc}"
    row["record_sha256"] = _sha({k: v for k, v in row.items() if k != "record_sha256"})
    return row


def _old_rows(path: Path, replica: int) -> dict[str, Mapping[str, object]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema") != SCHEMA or report.get("stage") != "old_history" or int(report.get("replica")) != replica:
        raise AssertionError("foreign or mismatched Old-history report")
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != 32:
        raise AssertionError("Old-history population is not complete")
    out = {}
    for row in rows:
        key = str(row.get("opaque_state_id"))
        if key in out:
            raise AssertionError("duplicate Old-history opaque state")
        out[key] = row
    return out


def _single_historical(row: Mapping[str, object]) -> dict[str, object] | None:
    if row.get("status") != "COMPLETE_OBSERVED":
        return None
    values = list(row.get("historical_action_records") or [])
    if not values:
        return None
    if len(values) != 1:
        raise AssertionError("Old-history row has ambiguous historical record cardinality")
    return copy.deepcopy(values[0])


async def _replaymark_row(*, replica: int, state: Mapping[str, object], blueprint: Path, qualification: dict[str, object], old_row: Mapping[str, object]) -> dict[str, object]:
    row = _row_base(stage="replaymark", replica=replica, state=state)
    historical = _single_historical(old_row)
    if historical is None:
        row["status"] = "COMPLETE_PROTOCOL_NONEXECUTABLE"
        row["failure"] = "sealed Old-history row supplies no unique historical action"
        row["historical_source_record_sha256"] = old_row.get("record_sha256")
        row["record_sha256"] = _sha({k: v for k, v in row.items() if k != "record_sha256"})
        return row
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer, entity = await _fresh_for_fixture(blueprint=blueprint, qualification=qualification, fixture=state["fixture"])
        base_raw = _raw_observation(hass, label=f"ve1_replaymark_{replica}_{state['opaque_state_id']}_base")
        before_state = len(observer.state_events)
        before_service = len(observer.service_events)
        final_presence = bool(state["fixture"]["presence"])
        old_presence, new_presence = _onoff(not final_presence), _onoff(final_presence)
        trigger = Context()
        hass.states.async_set(base.PRESENCE_ENTITY, new_presence, context=trigger)
        target_boundary = await _completion_boundary(hass)
        if len(observer.service_events) != before_service:
            raise AssertionError("suspended target emitted consequential action before ReplayMark")
        parent = _parent_event(observer, start_index=before_state, context_id=str(trigger.id), old_state=old_presence, new_state=new_presence)
        contract = compile_c2_contract(0)
        certificate = certify_ha_bt_shadow_reuse(contract, base_raw_observation=base_raw, parent_state_event=parent, historical_raw_action=historical)
        gate = HaBtCertifiedExecutionGate()
        before_gate = len(observer.service_events)
        receipt = await gate.dispatch(hass, contract, base_raw_observation=base_raw, parent_state_event=parent, historical_raw_action=historical, presented_certificate=certificate)
        sink_boundary = await _completion_boundary(hass)
        sink_events = copy.deepcopy(observer.service_events[before_gate:])
        caller_native = None
        if not receipt.execution_performed:
            caller_native = await _caller_native_recovery(hass, observer, entity, label=f"ve1_replaymark_{replica}_{state['opaque_state_id']}")
        after = _raw_observation(hass, label=f"ve1_replaymark_{replica}_{state['opaque_state_id']}_after")
        status, failure = "COMPLETE_OBSERVED", None
        if receipt.execution_performed and len(sink_events) != 1:
            status, failure = "UNRESOLVED_RUNTIME", "historical sink cardinality is not one"
        if not receipt.execution_performed and sink_events:
            status, failure = "UNRESOLVED_RUNTIME", "blocked historical material crossed sink"
        if caller_native is not None and caller_native["status"] != "COMPLETE_OBSERVED":
            status, failure = "UNRESOLVED_RUNTIME", str(caller_native["reason"])
        row.update({"status": status, "failure": failure, "registry": registry, "historical_source_record_sha256": old_row.get("record_sha256"), "historical_raw_action": historical, "base_raw_observation": base_raw, "target_parent_state_event": parent, "target_transition_context_id": str(trigger.id), "target_transition_completion": target_boundary, "presented_certificate": certificate.canonical_record(), "presented_certificate_fingerprint": certificate.fingerprint(), "gate_receipt": receipt.canonical_record(), "gate_receipt_fingerprint": receipt.fingerprint(), "historical_sink_events": sink_events, "historical_sink_completion": sink_boundary, "caller_native": caller_native, "post_boundary_observation": after})
    except Exception as exc:
        row["status"] = "INFRASTRUCTURE_INCOMPLETE"
        row["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if hass is not None and lab is not None and temp is not None and observer is not None:
            try:
                await _cleanup(hass, lab, temp, observer)
            except Exception as exc:
                if row["status"] == "COMPLETE_OBSERVED":
                    row["status"] = "INFRASTRUCTURE_INCOMPLETE"
                    row["failure"] = f"CLEANUP_FAILURE: {type(exc).__name__}: {exc}"
    row["record_sha256"] = _sha({k: v for k, v in row.items() if k != "record_sha256"})
    return row


async def _replay_all_row(*, replica: int, state: Mapping[str, object], blueprint: Path, qualification: dict[str, object], old_row: Mapping[str, object]) -> dict[str, object]:
    row = _row_base(stage="replay_all", replica=replica, state=state)
    historical = _single_historical(old_row)
    if historical is None:
        row["status"] = "COMPLETE_PROTOCOL_NONEXECUTABLE"
        row["failure"] = "sealed Old-history row supplies no unique historical action"
        row["historical_source_record_sha256"] = old_row.get("record_sha256")
        row["record_sha256"] = _sha({k: v for k, v in row.items() if k != "record_sha256"})
        return row
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer, entity = await _fresh_for_fixture(blueprint=blueprint, qualification=qualification, fixture=state["fixture"])
        hass.states.async_set(base.PRESENCE_ENTITY, _onoff(bool(state["fixture"]["presence"])), context=Context())
        await _completion_boundary(hass)
        if observer.service_events:
            raise AssertionError("suspended Replay-All target emitted consequential action")
        pre = _raw_observation(hass, label=f"ve1_replay_all_{replica}_{state['opaque_state_id']}_pre")
        data = copy.deepcopy(historical["service_event"]["service_data"])
        before = len(observer.service_events)
        context = Context()
        started = _now_ns()
        await hass.services.async_call("climate", "set_preset_mode", data, blocking=True, context=context)
        completion = await _completion_boundary(hass)
        completed = _now_ns()
        events = copy.deepcopy(observer.service_events[before:])
        after = _raw_observation(hass, label=f"ve1_replay_all_{replica}_{state['opaque_state_id']}_after")
        status, failure = "COMPLETE_OBSERVED", None
        if len(events) != 1 or not _context_bound(events[0], str(context.id)):
            status, failure = "UNRESOLVED_RUNTIME", "Replay-All sink event cardinality/context mismatch"
        elif _normalize_service_data(events[0]) != data:
            status, failure = "UNRESOLVED_RUNTIME", "Replay-All sink changed historical service data"
        row.update({"status": status, "failure": failure, "registry": registry, "historical_source_record_sha256": old_row.get("record_sha256"), "historical_raw_action": historical, "pre_dispatch_observation": pre, "dispatch_context_id": str(context.id), "dispatch_started_ns": started, "dispatch_completed_ns": completed, "completion_boundary": completion, "sink_events": events, "post_boundary_observation": after})
    except Exception as exc:
        row["status"] = "INFRASTRUCTURE_INCOMPLETE"
        row["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if hass is not None and lab is not None and temp is not None and observer is not None:
            try:
                await _cleanup(hass, lab, temp, observer)
            except Exception as exc:
                if row["status"] == "COMPLETE_OBSERVED":
                    row["status"] = "INFRASTRUCTURE_INCOMPLETE"
                    row["failure"] = f"CLEANUP_FAILURE: {type(exc).__name__}: {exc}"
    row["record_sha256"] = _sha({k: v for k, v in row.items() if k != "record_sha256"})
    return row


async def experiment(args: argparse.Namespace) -> dict[str, object]:
    if args.stage not in STAGES or args.replica not in (0, 1):
        raise AssertionError("invalid stage or replica")
    if HA_VERSION != EXPECTED_HA_VERSION:
        raise AssertionError(("Home Assistant version mismatch", HA_VERSION, EXPECTED_HA_VERSION))
    manifest_path = Path(args.state_manifest)
    manifest = _load_state_manifest(manifest_path)
    blueprint = Path(args.blueprint)
    component = Path(args.ownership_component)
    old = None
    if args.stage in {"replaymark", "replay_all"}:
        if args.old_history is None:
            raise AssertionError("downstream stage requires sealed Old-history report")
        old = _old_rows(Path(args.old_history), args.replica)
    qualification, qtemp, qhass = await base.qualify_upstream_loader(component)
    rows = []
    try:
        for state in manifest["states"]:
            if args.stage in {"old_history", "new_direct"}:
                row = await _native_source_row(stage=args.stage, replica=args.replica, state=state, blueprint=blueprint, qualification=qualification)
            elif args.stage == "replaymark":
                row = await _replaymark_row(replica=args.replica, state=state, blueprint=blueprint, qualification=qualification, old_row=old[str(state["opaque_state_id"])])
            else:
                row = await _replay_all_row(replica=args.replica, state=state, blueprint=blueprint, qualification=qualification, old_row=old[str(state["opaque_state_id"])])
            rows.append(row)
    finally:
        try:
            await qhass.async_stop()
        finally:
            qtemp.cleanup()
    report = {"schema": SCHEMA, "mode": "AUTHORITATIVE_FIRST_COMPLETE_STAGE", "stage": args.stage, "replica": args.replica, "ha_version": HA_VERSION, "blueprint_git_blob_sha1": args.blueprint_git_blob, "blueprint_sha256": _file_sha(blueprint), "state_manifest_sha256": _file_sha(manifest_path), "state_count": 32, "sampling": "none", "rows": rows, "scientific_summary_emitted": False}
    report["report_sha256"] = _sha(report)
    return report


async def _run(args: argparse.Namespace) -> None:
    try:
        result = await experiment(args)
    except Exception as exc:
        result = {"schema": SCHEMA, "mode": "AUTHORITATIVE_FIRST_COMPLETE_STAGE", "stage": args.stage, "replica": args.replica, "fatal_failure": f"{type(exc).__name__}: {exc}", "rows": [], "scientific_summary_emitted": False}
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(json.dumps({"schema": "replaymark.ve1.producer-close.v1", "stage": args.stage, "replica": args.replica, "artifact_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "scientific_summary_emitted": False}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    parser.add_argument("--replica", required=True, type=int)
    parser.add_argument("--state-manifest", required=True)
    parser.add_argument("--blueprint", required=True)
    parser.add_argument("--blueprint-git-blob", required=True)
    parser.add_argument("--ownership-component", required=True)
    parser.add_argument("--old-history")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
