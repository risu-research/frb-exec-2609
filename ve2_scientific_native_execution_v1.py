from __future__ import annotations

"""VE2 label-firewalled scientific stage producer.

Old/New source stages execute the exact pinned Home Assistant blueprint. Replay
stages consume only the sealed historical-behavior handoff. This producer has no
analysis table, no source-diff logic, and no scientific outcome oracle.
"""

import argparse
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
from unittest.mock import patch

from homeassistant.const import EVENT_CALL_SERVICE, EVENT_STATE_CHANGED, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Context, Event, ServiceCall, callback

import ve2_science_transport_qualify_v3 as transport_v3
import ve2_science_transport_qualify_v4 as transport_v4  # noqa: F401
import ve2_science_transport_qualify_v5 as transport_v5  # noqa: F401
import ve2_science_transport_qualify_v6 as transport_v6
import ve2_e0r_semantic_boundary_v1 as e0r
from ve2_scientific_contract_runtime_v1 import load_strict_contract, canonical_bytes

SCHEMA = "replaymark.ve2.scientific-native-stage.v1"
ROW_SCHEMA = "replaymark.ve2.scientific-native-row.v1"
ABSENCE_SCHEMA = "replaymark.ve2.scientific-fixed-point-absence.v1"
TARGETS = {
    "T01": "climate.ve2_t01_thermostat",
    "T02": "climate.ve2_t02_thermostat",
}
EXPECTED_CONTRACT = {
    "T01": (
        "c42254e9556da27f0cc760c379b311d002dc775131b79a6cc3ab0af8b2a34b50",
        "22f621ada3862f85ead9769ea0b13c6b68807b078ee76de25c53b422a3a1cedb",
    ),
    "T02": (
        "450b2fb1752900eda757a705e590d060aeca30d51dc5d0b05803bb71555ff409",
        "a72f240ccbd5d6b4f81868189b962c831dbbce881531d1fca57f4d663d761b2c",
    ),
}
STAGES = {"old_history", "new_direct", "replaymark", "replay_all"}


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_ns() -> int:
    return time.perf_counter_ns()


def _load_manifest(path: Path, transition: str) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    expected_schema = {
        "T01": "replaymark.ve2.t01.execution-state-manifest.v1",
        "T02": "replaymark.ve2.t02.execution-state-manifest.v1",
    }[transition]
    expected_count = {"T01": 2, "T02": 42}[transition]
    if value.get("schema") != expected_schema or value.get("state_count") != expected_count:
        raise AssertionError("execution-manifest-identity")
    rows = value.get("states")
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise AssertionError("execution-manifest-population")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"opaque_state_id", "fixture"}:
            raise AssertionError("execution-manifest-row-shape")
        sid = row["opaque_state_id"]
        if not isinstance(sid, str) or sid in seen or not isinstance(row["fixture"], dict):
            raise AssertionError("execution-manifest-row-identity")
        seen.add(sid)
    return value


class Observer:
    def __init__(self, hass: Any) -> None:
        self.hass = hass
        self.automation_events: list[dict[str, Any]] = []
        self.service_events: list[dict[str, Any]] = []
        self.state_events: list[dict[str, Any]] = []
        self._unsubs: list[Any] = []
        self._sequence = 0

    def install(self) -> None:
        @callback
        def on_automation(event: Event) -> None:
            self.automation_events.append({
                "event_type": event.event_type,
                "data": copy.deepcopy(dict(event.data)),
                "context_id": str(event.context.id),
                "context_parent_id": None if event.context.parent_id is None else str(event.context.parent_id),
                "observed_ns": _now_ns(),
            })

        @callback
        def on_service(event: Event) -> None:
            domain = str(event.data.get("domain"))
            service = str(event.data.get("service"))
            if domain not in {"climate", "better_thermostat"}:
                return
            self._sequence += 1
            self.service_events.append({
                "domain": domain,
                "service": service,
                "service_data": copy.deepcopy(dict(event.data.get("service_data") or {})),
                "context_id": str(event.context.id),
                "context_parent_id": None if event.context.parent_id is None else str(event.context.parent_id),
                "sequence": self._sequence,
                "t_ns": _now_ns(),
            })

        @callback
        def on_state(event: Event) -> None:
            entity = str(event.data.get("entity_id"))
            if entity not in {
                "schedule.ve2_t01_night",
                "input_boolean.ve2_pause",
                "binary_sensor.ve2_presence",
            }:
                return
            old = event.data.get("old_state")
            new = event.data.get("new_state")
            self.state_events.append({
                "entity_id": entity,
                "old_state": None if old is None else old.state,
                "new_state": None if new is None else new.state,
                "context_id": None if new is None else str(new.context.id),
                "context_parent_id": None if new is None or new.context.parent_id is None else str(new.context.parent_id),
                "observed_ns": _now_ns(),
            })

        automation_event = transport_v3.EVENT_AUTOMATION_TRIGGERED
        self._unsubs.append(self.hass.bus.async_listen(automation_event, on_automation))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_CALL_SERVICE, on_service))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, on_state))

    def close(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()


async def _fixed_point(hass: Any, observer: Observer, before_services: int) -> dict[str, Any]:
    passes = []
    for index in range(3):
        before = _now_ns()
        await hass.async_block_till_done()
        await asyncio.sleep(0)
        after = _now_ns()
        passes.append({"pass": index, "before_ns": before, "after_ns": after})
    count = len(observer.service_events) - before_services
    return {
        "schema": ABSENCE_SCHEMA,
        "qualified": count == 0,
        "qualifying_service_count": count,
        "witness": "three_homeassistant_async_block_till_done_fixed_point_passes",
        "passes": passes,
        "closed_ns": _now_ns(),
    }


async def _wait(values: list[Any], count: int, timeout: float = 4.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while len(values) < count:
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(("witness-timeout", count, len(values)))
        await asyncio.sleep(0.001)


def _service_target(event: dict[str, Any]) -> list[str]:
    raw = (event.get("service_data") or {}).get("entity_id")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [str(v) for v in raw]
    raise AssertionError("native-service-target-unresolved")


async def _raw_trigger_for_context(hass: Any, trace_api: Any, context_id: str) -> dict[str, Any]:
    raw_contexts = await trace_api.async_list_contexts(hass, None)
    contexts = {str(key): value for key, value in raw_contexts.items()}
    if context_id not in contexts:
        raise AssertionError("automation-context-absent-from-trace-index")
    ref = contexts[context_id]
    key = "%s.%s" % (ref["domain"], ref["item_id"])
    trace = await trace_api.async_get_trace(hass, key, ref["run_id"])
    if transport_v3._context_id(trace.get("context")) != context_id:
        raise AssertionError("trace-context-mismatch")
    elements = []
    for path, values in (trace.get("trace") or {}).items():
        if path == "trigger" or str(path).startswith("trigger/"):
            elements.extend(list(values or []))
    if len(elements) != 1:
        raise AssertionError(("trigger-trace-cardinality", len(elements)))
    changed = elements[0].get("changed_variables") or {}
    raw = changed.get("trigger")
    if not isinstance(raw, dict):
        raise AssertionError("trace-trigger-missing")
    return raw


def _register_services(hass: Any, *, old_t01: bool, target_runtime: bool) -> None:
    async def inert(_call: ServiceCall) -> None:
        return None
    if old_t01:
        hass.services.async_register("better_thermostat", "set_temp_target_temperature", inert)
        hass.services.async_register("better_thermostat", "restore_saved_target_temperature", inert)
        hass.services.async_register("better_thermostat", "save_current_target_temperature", inert)
    if target_runtime:
        hass.services.async_register("climate", "set_preset_mode", inert)


async def _fresh_base(case: str, *, old_t01: bool, target_runtime: bool) -> tuple[Any, Any, Observer, dict[str, Any], Any]:
    temp = tempfile.TemporaryDirectory(prefix="ve2-science-%s-" % case)
    imports = transport_v3._prepare_import_graph()
    hass, constructor = transport_v3._construct_hass(temp.name)
    substrate = await transport_v3._prepare_native_substrate(hass, imports)
    state_adapter = transport_v3._set_running(hass)
    ok = await substrate["async_setup_component"](hass, transport_v3.TRACE_DOMAIN, {})
    if not ok:
        raise RuntimeError("trace-setup-failed")
    observer = Observer(hass)
    observer.install()
    _register_services(hass, old_t01=old_t01, target_runtime=target_runtime)
    adapter = {
        "constructor": constructor,
        "config_entries": substrate["config_entries"],
        "loader": substrate["loader"],
        "timezone": substrate["timezone"],
        "helpers": substrate["helpers"],
        "automation_module": substrate["automation_module"],
        "trace_strategy": substrate["trace_strategy"],
        "core_state": state_adapter,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }
    adapter["adapter_sha256"] = _sha(adapter)
    return hass, temp, observer, adapter, substrate["trace_api"]


async def _finish(hass: Any, temp: Any, observer: Observer) -> None:
    observer.close()
    try:
        await hass.async_stop()
    finally:
        temp.cleanup()


def _copy_blueprint(temp: Any, source: Path) -> None:
    target = Path(temp.name) / "blueprints" / "automation" / "replaymark" / "science.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def _t01_inputs(old: bool) -> dict[str, Any]:
    value = {
        "night_times_schedule": "schedule.ve2_t01_night",
        "thermostat_target": {"entity_id": "climate.ve2_t01_thermostat"},
    }
    if old:
        value["night_temp"] = 18.0
    return value


def _sec_to_clock(sec: int) -> str:
    sec %= 86400
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def _t02_time_plan(active_slot: int, trigger_kind: str) -> tuple[dict[str, str], datetime | None]:
    now = datetime.now(timezone.utc)
    if now.isoweekday() > 5:
        raise RuntimeError("t02-frozen-day-profile-requires-weekday")
    sec = now.hour * 3600 + now.minute * 60 + now.second
    if not (3600 <= sec <= 18 * 3600):
        raise RuntimeError("t02-clock-window-outside-frozen-safe-range")
    target: datetime | None = None
    if trigger_kind.startswith("slot"):
        n = int(trigger_kind[-1])
        if n != active_slot:
            raise AssertionError("slot-trigger-active-slot-binding")
        target = now + timedelta(seconds=60)
        target_sec = sec + 60
        weekday: list[int] = []
        for slot in range(1, 5):
            if slot < n:
                weekday.append(sec - (n - slot) * 600)
            elif slot == n:
                weekday.append(target_sec)
            else:
                weekday.append(target_sec + (slot - n) * 600)
    else:
        weekday = []
        for slot in range(1, 5):
            if slot < active_slot:
                weekday.append(sec - (active_slot - slot) * 600 - 60)
            elif slot == active_slot:
                weekday.append(sec - 60)
            else:
                weekday.append(sec + (slot - active_slot) * 600)
    if min(weekday) <= 0 or max(weekday) >= 21 * 3600:
        raise RuntimeError("t02-derived-time-plan-outside-safe-range")
    plan: dict[str, str] = {}
    for slot, value in enumerate(weekday, 1):
        plan[f"slot{slot}_time_weekday"] = _sec_to_clock(value)
    # Non-current day-type triggers are deliberately later than the selected
    # current-day stimulus so the qualified clock driver cannot fire them.
    base = max(weekday[-1] + 1800, sec + 7200)
    if base + 7 * 300 >= 23 * 3600:
        base = 19 * 3600
    for slot in range(1, 5):
        plan[f"slot{slot}_time_saturday"] = _sec_to_clock(base + (slot - 1) * 300)
        plan[f"slot{slot}_time_sunday"] = _sec_to_clock(base + 1200 + (slot - 1) * 300)
    return plan, target


def _t02_inputs(fixture: dict[str, Any]) -> tuple[dict[str, Any], datetime | None]:
    plan, target = _t02_time_plan(int(fixture["active_slot"]), str(fixture["trigger_kind"]))
    value: dict[str, Any] = {
        **plan,
        "thermostat_target": {"entity_id": "climate.ve2_t02_thermostat"},
        "enable_presence_mode": bool(fixture["enable_presence_mode"]),
        "presence_entity": "binary_sensor.ve2_presence",
        "vacation_preset": "away",
        "enable_pause_switch": bool(fixture["enable_pause_switch"]),
        "pause_switch": "input_boolean.ve2_pause",
        "notify_target": "notify.notify",
        "enable_notify": False,
    }
    presets = {1: "comfort", 2: "eco", 3: "home", 4: "sleep"}
    for slot in range(1, 5):
        for day in ("weekday", "saturday", "sunday"):
            value[f"slot{slot}_preset_{day}"] = presets[slot]
    return value, target


async def _install_blueprint(hass: Any, temp: Any, trace_api: Any, source: Path, inputs: dict[str, Any], *, alias: str) -> str:
    _copy_blueprint(temp, source)
    config = {
        "automation": [
            {
                "id": "ve2_science_" + hashlib.sha256(alias.encode()).hexdigest()[:16],
                "alias": alias,
                "use_blueprint": {"path": "replaymark/science.yaml", "input": inputs},
            }
        ]
    }
    imports = transport_v3._prepare_import_graph()
    setup = getattr(imports["setup_module"], "async_setup_component")
    ok = await setup(hass, "automation", config)
    if not ok:
        raise RuntimeError("blueprint-automation-setup-failed")
    await hass.async_block_till_done()
    entities = [s.entity_id for s in hass.states.async_all("automation")]
    if len(entities) != 1:
        raise AssertionError(("automation-entity-cardinality", entities))
    contexts = await trace_api.async_list_contexts(hass, None)
    if contexts:
        raise AssertionError("native-trace-exists-before-stimulus")
    return entities[0]


async def _fresh_source(
    transition: str,
    state: dict[str, Any],
    blueprint: Path,
    *,
    old_source: bool,
) -> tuple[Any, Any, Observer, dict[str, Any], Any, str, datetime | None]:
    old_t01 = transition == "T01" and old_source
    hass, temp, observer, adapter, trace_api = await _fresh_base(
        "%s-%s-%s" % (transition, "old" if old_source else "new", state["opaque_state_id"]),
        old_t01=old_t01,
        target_runtime=not old_t01,
    )
    if transition == "T01":
        fixture = state["fixture"]
        final = str(fixture["schedule_state"])
        initial = "off" if final == "on" else "on"
        hass.states.async_set("schedule.ve2_t01_night", initial)
        hass.states.async_set(TARGETS[transition], "heat", {"preset_mode": "none", "temperature": 20.0})
        inputs = _t01_inputs(old_source)
        target_time = None
    else:
        fixture = state["fixture"]
        trigger = str(fixture["trigger_kind"])
        presence = "on" if bool(fixture["presence_home"]) else "off"
        pause = "on" if bool(fixture["pause_on"]) else "off"
        if trigger == "arrived_home":
            presence = "off"
        elif trigger == "left_home":
            presence = "on"
        if trigger == "pause_off":
            pause = "on"
        hass.states.async_set("binary_sensor.ve2_presence", presence)
        hass.states.async_set("input_boolean.ve2_pause", pause)
        hass.states.async_set(TARGETS[transition], "heat", {"preset_mode": "none", "temperature": 20.0})
        inputs, target_time = _t02_inputs(fixture)
    await hass.async_block_till_done()
    if observer.automation_events or observer.service_events:
        raise AssertionError("consequential-event-during-fixture-seeding")
    entity = await _install_blueprint(
        hass,
        temp,
        trace_api,
        blueprint,
        inputs,
        alias="VE2 Science %s %s %s" % (transition, "OLD" if old_source else "NEW", state["opaque_state_id"]),
    )
    if observer.automation_events or observer.service_events:
        raise AssertionError("consequential-event-during-blueprint-install")
    return hass, temp, observer, adapter, trace_api, entity, target_time


async def _stimulate_source(
    transition: str,
    state: dict[str, Any],
    hass: Any,
    observer: Observer,
    trace_api: Any,
    entity: str,
    target_time: datetime | None,
) -> dict[str, Any]:
    before_a = len(observer.automation_events)
    before_s = len(observer.service_events)
    root = Context()
    clock_records: list[dict[str, Any]] = []
    fixture = state["fixture"]
    if transition == "T01":
        hass.states.async_set("schedule.ve2_t01_night", str(fixture["schedule_state"]), context=root)
        await _wait(observer.automation_events, before_a + 1)
        await hass.async_block_till_done()
    else:
        trigger = str(fixture["trigger_kind"])
        if trigger.startswith("slot"):
            if target_time is None:
                raise AssertionError("slot-target-time-missing")
            with patch("homeassistant.util.dt.now", return_value=target_time + timedelta(seconds=1)):
                clock_records.append(transport_v3._drive_clock(hass, target_time + timedelta(seconds=1)))
                await _wait(observer.automation_events, before_a + 1)
                await hass.async_block_till_done()
        elif trigger == "startup":
            started = datetime.now(timezone.utc)
            hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED, context=root)
            await _wait(observer.automation_events, before_a + 1)
            clock_records.append(transport_v3._drive_clock(hass, started + timedelta(seconds=31)))
            await hass.async_block_till_done()
        elif trigger == "pause_off":
            hass.states.async_set("input_boolean.ve2_pause", "off", context=root)
            await _wait(observer.automation_events, before_a + 1)
            await hass.async_block_till_done()
        elif trigger == "arrived_home":
            hass.states.async_set("binary_sensor.ve2_presence", "on", context=root)
            await _wait(observer.automation_events, before_a + 1)
            await hass.async_block_till_done()
        elif trigger == "left_home":
            started = datetime.now(timezone.utc)
            hass.states.async_set("binary_sensor.ve2_presence", "off", context=root)
            await hass.async_block_till_done()
            clock_records.append(transport_v3._drive_clock(hass, started + timedelta(seconds=121)))
            await _wait(observer.automation_events, before_a + 1)
            await hass.async_block_till_done()
        else:
            raise AssertionError("unknown-trigger-kind")
    absence = await _fixed_point(hass, observer, before_s)
    invocations = copy.deepcopy(observer.automation_events[before_a:])
    services = copy.deepcopy(observer.service_events[before_s:])
    if len(invocations) != 1:
        raise AssertionError(("native-invocation-cardinality", len(invocations)))
    if len(services) > 1:
        raise AssertionError(("consequential-service-cardinality", len(services)))
    inv_event = invocations[0]
    raw_trigger = await _raw_trigger_for_context(hass, trace_api, inv_event["context_id"])
    invocation = e0r.canonicalize_native_trigger(
        {"trigger": raw_trigger},
        inv_event["context_id"],
        observed_ns=int(inv_event["observed_ns"]),
    )
    if services:
        event = services[0]
        if _service_target(event) != [TARGETS[transition]]:
            raise AssertionError(("service-target", _service_target(event)))
        behavior = e0r.service_behavior(
            invocation=invocation,
            target=TARGETS[transition],
            service_event=event,
        )
    else:
        behavior = e0r.no_action_behavior(
            invocation=invocation,
            target=TARGETS[transition],
            absence_certificate=absence,
        )
    return {
        "automation_entity": entity,
        "root_stimulus_context_id": str(root.id),
        "automation_invocation_event": inv_event,
        "invocation_witness": invocation,
        "historical_behavior": behavior,
        "qualifying_service_events": services,
        "absence_certificate": absence,
        "clock_records": clock_records,
        "state_events": copy.deepcopy(observer.state_events),
    }


async def _source_row(
    transition: str,
    stage: str,
    replica: int,
    state: dict[str, Any],
    blueprint: Path,
    *,
    old_source: bool,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": ROW_SCHEMA,
        "transition": transition,
        "stage": stage,
        "replica": replica,
        "opaque_state_id": state["opaque_state_id"],
        "fixture": copy.deepcopy(state["fixture"]),
        "status": "INFRASTRUCTURE_INCOMPLETE",
        "failure": None,
    }
    hass = temp = observer = None
    try:
        hass, temp, observer, adapter, trace_api, entity, target_time = await _fresh_source(
            transition, state, blueprint, old_source=old_source
        )
        evidence = await _stimulate_source(
            transition, state, hass, observer, trace_api, entity, target_time
        )
        row.update({
            "status": "COMPLETE_OBSERVED",
            "bootstrap_adapter": adapter,
            **evidence,
            "native_projected_action": evidence["historical_behavior"]["projected_action"],
        })
        if stage != "old_history":
            row.pop("historical_behavior", None)
    except Exception as exc:
        row["failure"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if hass is not None and temp is not None and observer is not None:
            try:
                await _finish(hass, temp, observer)
            except Exception as exc:
                if row["status"] == "COMPLETE_OBSERVED":
                    row["status"] = "INFRASTRUCTURE_INCOMPLETE"
                    row["failure"] = "CLEANUP_FAILURE: %s: %s" % (type(exc).__name__, exc)
    row["row_sha256"] = _sha({k: v for k, v in row.items() if k != "row_sha256"})
    return row


def _load_history(path: Path, transition: str, replica: int, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    doc = json.loads(path.read_bytes())
    if doc.get("schema") != SCHEMA or doc.get("stage") != "old_history":
        raise AssertionError("historical-handoff-stage")
    if doc.get("transition") != transition or doc.get("replica") != replica:
        raise AssertionError("historical-handoff-identity")
    if doc.get("manifest_sha256") != _sha_manifest_bytes(manifest):
        raise AssertionError("historical-handoff-manifest")
    supplied = doc.get("result_sha256")
    body = dict(doc); body.pop("result_sha256", None)
    if supplied != _sha(body):
        raise AssertionError("historical-handoff-digest")
    rows = doc.get("rows")
    if not isinstance(rows, list) or len(rows) != manifest["state_count"]:
        raise AssertionError("historical-handoff-row-count")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        rr = dict(row)
        row_hash = rr.pop("row_sha256", None)
        if row_hash != _sha(rr):
            raise AssertionError("historical-row-digest")
        if row.get("status") != "COMPLETE_OBSERVED":
            raise AssertionError("historical-row-incomplete")
        behavior = row.get("historical_behavior")
        e0r.validate_behavior(behavior)
        sid = row.get("opaque_state_id")
        if not isinstance(sid, str) or sid in out:
            raise AssertionError("historical-row-id")
        out[sid] = row
    expected = [r["opaque_state_id"] for r in manifest["states"]]
    if list(out) != expected:
        raise AssertionError("historical-row-order")
    return out


def _sha_manifest_bytes(manifest: dict[str, Any]) -> str:
    # Stage reports bind the exact mounted manifest bytes separately in main;
    # handoff comparison uses its canonical content to avoid path dependence.
    return _sha(manifest)


async def _fresh_target(transition: str, state_id: str) -> tuple[Any, Any, Observer, dict[str, Any]]:
    hass, temp, observer, adapter, _trace_api = await _fresh_base(
        "%s-target-%s" % (transition, state_id),
        old_t01=False,
        target_runtime=True,
    )
    target = TARGETS[transition]
    hass.states.async_set(target, "heat", {"preset_mode": "none", "temperature": 20.0})
    await hass.async_block_till_done()
    return hass, temp, observer, adapter


async def _dispatch_behavior(hass: Any, observer: Observer, behavior: dict[str, Any]) -> dict[str, Any]:
    e0r.validate_behavior(behavior)
    before = len(observer.service_events)
    started = _now_ns()
    attempted = behavior["kind"] == "SERVICE"
    error = None
    if attempted:
        native = behavior["native_service_event"]
        try:
            await hass.services.async_call(
                str(native["domain"]),
                str(native["service"]),
                copy.deepcopy(dict(native["service_data"])),
                blocking=True,
                context=Context(),
            )
        except Exception as exc:
            error = "%s: %s" % (type(exc).__name__, exc)
    await hass.async_block_till_done()
    observed = copy.deepcopy(observer.service_events[before:])
    return {
        "attempted": attempted,
        "error": error,
        "observed_consequential_service_events": observed,
        "attempted_at_ns": started,
        "completed_at_ns": _now_ns(),
        "retry": False,
        "fallback": False,
    }


async def _replay_row(
    transition: str,
    stage: str,
    replica: int,
    state: dict[str, Any],
    history_row: dict[str, Any],
    *,
    contract_view: Any | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": ROW_SCHEMA,
        "transition": transition,
        "stage": stage,
        "replica": replica,
        "opaque_state_id": state["opaque_state_id"],
        "fixture": copy.deepcopy(state["fixture"]),
        "status": "INFRASTRUCTURE_INCOMPLETE",
        "failure": None,
    }
    hass = temp = observer = None
    try:
        behavior = copy.deepcopy(history_row["historical_behavior"])
        e0r.validate_behavior(behavior)
        hass, temp, observer, adapter = await _fresh_target(transition, state["opaque_state_id"])
        row["bootstrap_adapter"] = adapter
        row["historical_behavior_fingerprint"] = behavior["fingerprint"]
        if stage == "replaymark":
            if contract_view is None:
                raise AssertionError("contract-view-missing")
            presented = contract_view.certificate(state["fixture"], behavior)
            recomputed = contract_view.verify_presented_certificate(state["fixture"], behavior, presented)
            delegated: list[dict[str, Any]] = []
            gate = e0r.SingleUseBehaviorGate()
            receipt = gate.execute(
                behavior,
                admission=recomputed["admission"],
                delegate=lambda native: delegated.append(copy.deepcopy(native)),
            )
            if receipt["service_delegated"] != (len(delegated) == 1):
                raise AssertionError("gate-delegate-cardinality")
            if len(delegated) > 1:
                raise AssertionError("gate-multiple-delegate")
            dispatch = await _dispatch_behavior(hass, observer, behavior) if delegated else {
                "attempted": False,
                "error": None,
                "observed_consequential_service_events": [],
                "attempted_at_ns": None,
                "completed_at_ns": _now_ns(),
                "retry": False,
                "fallback": False,
            }
            row.update({
                "presented_certificate": presented,
                "execution_gate_recomputed_certificate": recomputed,
                "behavior_gate_receipt": receipt,
                "dispatch": dispatch,
                "caller_native_recovery": False,
                "regeneration": False,
            })
        else:
            if contract_view is not None:
                raise AssertionError("replay-all-must-not-have-contract-view")
            dispatch = await _dispatch_behavior(hass, observer, behavior)
            row.update({
                "dispatch": dispatch,
                "semantic_authorization": False,
                "caller_native_recovery": False,
                "regeneration": False,
            })
        row["status"] = "COMPLETE_OBSERVED"
    except Exception as exc:
        row["failure"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        if hass is not None and temp is not None and observer is not None:
            try:
                await _finish(hass, temp, observer)
            except Exception as exc:
                if row["status"] == "COMPLETE_OBSERVED":
                    row["status"] = "INFRASTRUCTURE_INCOMPLETE"
                    row["failure"] = "CLEANUP_FAILURE: %s: %s" % (type(exc).__name__, exc)
    row["row_sha256"] = _sha({k: v for k, v in row.items() if k != "row_sha256"})
    return row


async def _preflight(transition: str, blueprint: Path, *, old_source: bool) -> dict[str, Any]:
    fake = {
        "opaque_state_id": "PREFLIGHT",
        "fixture": {"schedule_state": "off"} if transition == "T01" else {
            "active_slot": 1,
            "enable_pause_switch": False,
            "enable_presence_mode": False,
            "pause_on": False,
            "presence_home": False,
            "trigger_kind": "startup",
        },
    }
    hass = temp = observer = None
    try:
        hass, temp, observer, adapter, trace_api, entity, _target = await _fresh_source(
            transition, fake, blueprint, old_source=old_source
        )
        await hass.async_block_till_done()
        contexts = await trace_api.async_list_contexts(hass, None)
        checks = {
            "automation_entity_materialized": entity.startswith("automation."),
            "zero_automation_invocations": len(observer.automation_events) == 0,
            "zero_consequential_services": len(observer.service_events) == 0,
            "zero_native_trace_contexts": len(contexts) == 0,
        }
        return {
            "schema": "replaymark.ve2.scientific-blueprint-preflight.v1",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "transition": transition,
            "source_role": "OLD" if old_source else "NEW",
            "home_assistant_version": transport_v3.HA_VERSION,
            "blueprint_sha256": _file_sha(blueprint),
            "bootstrap_adapter": adapter,
            "checks": checks,
            "scientific_hygiene": {
                "scientific_result_opened": False,
                "scientific_cells": 0,
                "trigger_stimulus_emitted": False,
                "frontier_result_seen": False,
            },
        }
    finally:
        if hass is not None and temp is not None and observer is not None:
            await _finish(hass, temp, observer)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    transport_v6._install_v6()
    transition = args.transition
    if args.preflight_only:
        return await _preflight(transition, Path(args.blueprint), old_source=args.source_role == "old")
    stage = args.stage
    replica = args.replica
    manifest_path = Path(args.manifest)
    manifest = _load_manifest(manifest_path, transition)
    manifest_raw_sha = _file_sha(manifest_path)
    rows: list[dict[str, Any]] = []
    if stage in {"old_history", "new_direct"}:
        if not args.blueprint:
            raise AssertionError("source-stage-blueprint-required")
        old_source = stage == "old_history"
        for state in manifest["states"]:
            rows.append(await _source_row(
                transition, stage, replica, state, Path(args.blueprint), old_source=old_source
            ))
    else:
        if not args.history:
            raise AssertionError("replay-stage-history-required")
        history = _load_history(Path(args.history), transition, replica, manifest)
        view = None
        if stage == "replaymark":
            if not args.contract:
                raise AssertionError("replaymark-contract-required")
            raw_sha, fp = EXPECTED_CONTRACT[transition]
            view = load_strict_contract(
                args.contract,
                args.manifest,
                expected_raw_sha256=raw_sha,
                expected_contract_fingerprint=fp,
            )
        elif args.contract:
            raise AssertionError("replay-all-contract-forbidden")
        for state in manifest["states"]:
            rows.append(await _replay_row(
                transition, stage, replica, state, history[state["opaque_state_id"]], contract_view=view
            ))
    result = {
        "schema": SCHEMA,
        "status": "SEALED_RAW_STAGE" if all(row["status"] == "COMPLETE_OBSERVED" for row in rows) else "RAW_STAGE_INCOMPLETE",
        "transition": transition,
        "stage": stage,
        "replica": replica,
        "home_assistant_version": transport_v3.HA_VERSION,
        "manifest_sha256": manifest_raw_sha,
        "manifest_canonical_sha256": _sha(manifest),
        "state_count": manifest["state_count"],
        "rows": rows,
        "scientific_summary_emitted": False,
        "frontier_result_seen": False,
    }
    result["result_sha256"] = _sha(result)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transition", choices=["T01", "T02"], required=True)
    ap.add_argument("--stage", choices=sorted(STAGES))
    ap.add_argument("--replica", type=int, choices=[0, 1], default=0)
    ap.add_argument("--manifest")
    ap.add_argument("--blueprint")
    ap.add_argument("--history")
    ap.add_argument("--contract")
    ap.add_argument("--out", required=True)
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--source-role", choices=["old", "new"])
    args = ap.parse_args()
    if not args.preflight_only and (args.stage is None or args.manifest is None):
        ap.error("stage and manifest required")
    if args.preflight_only and (args.blueprint is None or args.source_role is None):
        ap.error("preflight requires blueprint and source-role")
    result = asyncio.run(_run(args))
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "transition": result.get("transition"),
        "stage": result.get("stage"),
        "rows": result.get("state_count", 0),
        "scientific_summary_emitted": False,
    }, sort_keys=True))
    if result["status"] not in {"SEALED_RAW_STAGE", "PASS"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
