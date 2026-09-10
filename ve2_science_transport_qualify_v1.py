from __future__ import annotations

"""Orthogonal pre-science transport qualification for VE2.

This program deliberately executes only synthetic neutral Home Assistant automations.
It never reads or mounts the VE2 T01/T02 blueprints, execution-state manifests,
expected-frontier tables, or Better Thermostat historical actions.

It qualifies two facts needed by the later scientific runner:
  1. an automation invocation can be double-witnessed by the native
     EVENT_AUTOMATION_TRIGGERED context and the native automation trace trigger
     variables; and
  2. on HA 2026.9.0, time-based trigger/delay maturation can be driven by the same
     scheduled-TimerHandle/time-tracker mechanism used by Home Assistant's own
     tests, without editing an automation's trigger or action definition.
"""

import argparse
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from typing import Any

from homeassistant import loader
from homeassistant.components import automation
from homeassistant.const import EVENT_CALL_SERVICE, EVENT_HOMEASSISTANT_START, EVENT_STATE_CHANGED, __version__ as HA_VERSION
from homeassistant.core import Context, CoreState, Event, HomeAssistant, ServiceCall, callback
from homeassistant.setup import async_setup_component

try:
    from homeassistant.components.trace import util as trace_api
except ImportError:  # HA 2022.10 layout
    import homeassistant.components.trace as trace_api

try:
    from homeassistant.util.async_ import get_scheduled_timer_handles
except ImportError:  # defensive; all admitted images are expected to provide this
    get_scheduled_timer_handles = None

SCHEMA = "replaymark.ve2.science-transport-qualification-runtime.v1"
CLOCK_DRIVER_ID = "replaymark.ve2.ha-test-equivalent-clock-driver.v1"
ALLOWED_VERSIONS = {"2022.10.0", "2026.1.0", "2026.9.0"}
NEUTRAL_ENTITY = "input_boolean.ve2_transport_probe"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _context_id(ctx: Any) -> str | None:
    if ctx is None:
        return None
    if isinstance(ctx, dict):
        value = ctx.get("id")
    else:
        value = getattr(ctx, "id", None)
    return None if value is None else str(value)


def _context_parent_id(ctx: Any) -> str | None:
    if ctx is None:
        return None
    if isinstance(ctx, dict):
        value = ctx.get("parent_id")
    else:
        value = getattr(ctx, "parent_id", None)
    return None if value is None else str(value)


def _json_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _trigger_witness(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AssertionError("trace trigger witness is not a mapping")
    platform = str(raw.get("platform", "")).lower().strip()
    family = {
        "state": "STATE",
        "time": "TIME",
        "homeassistant": "HOMEASSISTANT_START",
    }.get(platform)
    if family is None:
        raise AssertionError("trace trigger witness has unqualified platform: %r" % platform)
    selected: dict[str, Any] = {
        "platform": platform,
        "family": family,
        "id": _json_scalar(raw.get("id")),
        "idx": _json_scalar(raw.get("idx")),
        "alias": _json_scalar(raw.get("alias")),
        "description": _json_scalar(raw.get("description")),
    }
    if platform == "state":
        selected.update({
            "entity_id": _json_scalar(raw.get("entity_id")),
            "for": _json_scalar(raw.get("for")),
            "from_state_entity_id": _json_scalar(getattr(raw.get("from_state"), "entity_id", None)),
            "from_state": _json_scalar(getattr(raw.get("from_state"), "state", None)),
            "to_state_entity_id": _json_scalar(getattr(raw.get("to_state"), "entity_id", None)),
            "to_state": _json_scalar(getattr(raw.get("to_state"), "state", None)),
        })
    elif platform == "time":
        selected.update({"now": _json_scalar(raw.get("now"))})
    else:
        selected.update({"event": _json_scalar(raw.get("event"))})
    return selected


class Observer:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.automation_events: list[dict[str, Any]] = []
        self.service_events: list[dict[str, Any]] = []
        self.state_events: list[dict[str, Any]] = []
        self._unsubs: list[Any] = []

    def install(self) -> None:
        @callback
        def on_automation(event: Event) -> None:
            self.automation_events.append({
                "event_type": event.event_type,
                "data": copy.deepcopy(dict(event.data)),
                "context_id": str(event.context.id),
                "context_parent_id": None if event.context.parent_id is None else str(event.context.parent_id),
                "observed_ns": time.perf_counter_ns(),
            })

        @callback
        def on_service(event: Event) -> None:
            if str(event.data.get("domain")) != "test" or str(event.data.get("service")) != "capture":
                return
            self.service_events.append({
                "domain": "test",
                "service": "capture",
                "service_data": copy.deepcopy(dict(event.data.get("service_data") or {})),
                "context_id": str(event.context.id),
                "context_parent_id": None if event.context.parent_id is None else str(event.context.parent_id),
                "observed_ns": time.perf_counter_ns(),
            })

        @callback
        def on_state(event: Event) -> None:
            if str(event.data.get("entity_id")) != NEUTRAL_ENTITY:
                return
            old = event.data.get("old_state")
            new = event.data.get("new_state")
            self.state_events.append({
                "entity_id": NEUTRAL_ENTITY,
                "old_state": None if old is None else old.state,
                "new_state": None if new is None else new.state,
                "context_id": None if new is None else str(new.context.id),
                "context_parent_id": None if new is None or new.context.parent_id is None else str(new.context.parent_id),
                "observed_ns": time.perf_counter_ns(),
            })

        self._unsubs.append(self.hass.bus.async_listen(automation.EVENT_AUTOMATION_TRIGGERED, on_automation))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_CALL_SERVICE, on_service))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, on_state))

    def close(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()


async def _trace_trigger_for_context(hass: HomeAssistant, context_id: str) -> dict[str, Any]:
    contexts = await trace_api.async_list_contexts(hass, None)
    if context_id not in contexts:
        raise AssertionError("automation action context absent from native trace index")
    ref = contexts[context_id]
    key = "%s.%s" % (ref["domain"], ref["item_id"])
    trace = await trace_api.async_get_trace(hass, key, ref["run_id"])
    trace_context_id = _context_id(trace.get("context"))
    if trace_context_id != context_id:
        raise AssertionError("native trace context disagrees with automation-triggered event")
    trace_map = trace.get("trace") or {}
    trigger_elements: list[dict[str, Any]] = []
    for path, values in trace_map.items():
        if path == "trigger" or str(path).startswith("trigger/"):
            trigger_elements.extend(list(values or []))
    if len(trigger_elements) != 1:
        raise AssertionError("expected exactly one native trigger trace element, got %d" % len(trigger_elements))
    changed = trigger_elements[0].get("changed_variables") or {}
    raw_trigger = changed.get("trigger")
    if raw_trigger is None:
        raise AssertionError("native trigger trace element omitted run_variables['trigger']")
    return {
        "trace_ref": {"key": key, "run_id": ref["run_id"]},
        "trace_context_id": trace_context_id,
        "trigger": _trigger_witness(raw_trigger),
    }


def _drive_clock(hass: HomeAssistant, target_utc: datetime, *, fire_all: bool = False) -> dict[str, Any]:
    if HA_VERSION != "2026.9.0":
        raise AssertionError("clock driver is qualified only on HA 2026.9.0")
    if get_scheduled_timer_handles is None:
        raise AssertionError("Home Assistant scheduled-handle accessor unavailable")
    if target_utc.tzinfo is None:
        target_utc = target_utc.replace(tzinfo=timezone.utc)
    target_utc = target_utc.astimezone(timezone.utc)
    timestamp = target_utc.timestamp()
    resolution = time.get_clock_info("monotonic").resolution
    scheduled = 0
    fired = 0
    for task in list(get_scheduled_timer_handles(hass.loop)):
        if not isinstance(task, asyncio.TimerHandle) or task.cancelled():
            continue
        scheduled += 1
        mock_seconds_into_future = timestamp - time.time()
        future_seconds = task.when() - (hass.loop.time() + resolution)
        if fire_all or mock_seconds_into_future >= future_seconds:
            with (
                patch("homeassistant.helpers.event.time_tracker_utcnow", return_value=target_utc),
                patch("homeassistant.helpers.event.time_tracker_timestamp", return_value=timestamp),
            ):
                task._run()  # same private TimerHandle execution seam used by HA tests
                task.cancel()
            fired += 1
    return {
        "clock_driver_id": CLOCK_DRIVER_ID,
        "target_utc": target_utc.isoformat(),
        "scheduled_handles_seen": scheduled,
        "handles_fired": fired,
        "fire_all": fire_all,
        "blueprint_or_action_definition_mutated": False,
        "result_dependent_target_time": False,
    }


async def _wait_for_count(values: list[Any], count: int, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while len(values) < count:
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("timed out waiting for neutral transport witness")
        await asyncio.sleep(0.001)


def _set_running(hass: HomeAssistant) -> None:
    if hasattr(hass, "set_state"):
        hass.set_state(CoreState.running)
    else:
        hass.state = CoreState.running


async def _fresh_hass(case: str, trigger_config: Any, action_config: list[dict[str, Any]]) -> tuple[HomeAssistant, tempfile.TemporaryDirectory[str], Observer, str]:
    temp = tempfile.TemporaryDirectory(prefix="ve2-science-transport-%s-" % case)
    hass = HomeAssistant(temp.name)
    loader.async_setup(hass)
    hass.config.set_time_zone("UTC")
    _set_running(hass)

    await async_setup_component(hass, "trace", {})
    observer = Observer(hass)
    observer.install()

    async def capture(_call: ServiceCall) -> None:
        return None

    hass.services.async_register("test", "capture", capture)
    hass.states.async_set(NEUTRAL_ENTITY, "off")
    await hass.async_block_till_done()

    alias = "VE2 Transport %s" % case
    config = {
        "automation": {
            "id": "ve2_transport_%s" % case,
            "alias": alias,
            "trigger": trigger_config,
            "condition": [],
            "action": action_config,
            "mode": "single",
        }
    }
    ok = await async_setup_component(hass, automation.DOMAIN, config)
    if not ok:
        raise RuntimeError("neutral automation setup failed")
    await hass.async_block_till_done()
    entities = [state.entity_id for state in hass.states.async_all(automation.DOMAIN)]
    if len(entities) != 1:
        raise AssertionError("neutral qualification requires exactly one automation entity: %r" % entities)
    return hass, temp, observer, entities[0]


async def _finish_case(hass: HomeAssistant, temp: tempfile.TemporaryDirectory[str], observer: Observer) -> None:
    observer.close()
    try:
        await hass.async_stop()
    finally:
        temp.cleanup()


async def _collect_case(case: str, expected_family: str, hass: HomeAssistant, observer: Observer, automation_entity: str, *, root_context_id: str | None, clock_records: list[dict[str, Any]]) -> dict[str, Any]:
    await _wait_for_count(observer.automation_events, 1)
    await _wait_for_count(observer.service_events, 1)
    await hass.async_block_till_done()
    if len(observer.automation_events) != 1 or len(observer.service_events) != 1:
        raise AssertionError("neutral case must produce exactly one invocation and one service")
    inv = copy.deepcopy(observer.automation_events[0])
    svc = copy.deepcopy(observer.service_events[0])
    trace = await _trace_trigger_for_context(hass, inv["context_id"])
    witness = trace["trigger"]
    row = {
        "case": case,
        "expected_family_for_qualification_only": expected_family,
        "automation_entity": automation_entity,
        "automation_invocation_event": inv,
        "trace_witness": trace,
        "neutral_service_event": svc,
        "root_stimulus_context_id": root_context_id,
        "clock_records": clock_records,
        "checks": {
            "family_from_native_trace_exact": witness["family"] == expected_family,
            "automation_entity_exact": inv["data"].get("entity_id") == automation_entity,
            "event_trace_context_exact": inv["context_id"] == trace["trace_context_id"],
            "service_context_bound_to_invocation": svc["context_id"] == inv["context_id"],
            "fresh_context_not_root": root_context_id is None or inv["context_id"] != root_context_id,
            "invocation_parent_is_root_when_applicable": root_context_id is None or inv["context_parent_id"] == root_context_id,
            "single_invocation": len(observer.automation_events) == 1,
            "single_neutral_sink": len(observer.service_events) == 1,
        },
    }
    row["pass"] = all(row["checks"].values())
    row["row_sha256"] = _sha({k: v for k, v in row.items() if k != "row_sha256"})
    return row


async def run_state(case: str = "state") -> dict[str, Any]:
    trigger = [{"platform": "state", "entity_id": NEUTRAL_ENTITY, "from": "off", "to": "on", "id": "state_probe"}]
    action = [{"service": "test.capture", "data": {"marker": case}}]
    hass, temp, observer, entity = await _fresh_hass(case, trigger, action)
    try:
        root = Context()
        hass.states.async_set(NEUTRAL_ENTITY, "on", context=root)
        await hass.async_block_till_done()
        return await _collect_case(case, "STATE", hass, observer, entity, root_context_id=str(root.id), clock_records=[])
    finally:
        await _finish_case(hass, temp, observer)


async def run_state_for() -> dict[str, Any]:
    case = "state_for_120s"
    trigger = [{"platform": "state", "entity_id": NEUTRAL_ENTITY, "from": "off", "to": "on", "for": {"seconds": 120}, "id": "state_for_probe"}]
    action = [{"service": "test.capture", "data": {"marker": case}}]
    hass, temp, observer, entity = await _fresh_hass(case, trigger, action)
    try:
        root = Context()
        before = datetime.now(timezone.utc)
        hass.states.async_set(NEUTRAL_ENTITY, "on", context=root)
        await hass.async_block_till_done()
        if observer.automation_events or observer.service_events:
            raise AssertionError("state-for automation fired before duration matured")
        clock = _drive_clock(hass, before + timedelta(seconds=121))
        await hass.async_block_till_done()
        return await _collect_case(case, "STATE", hass, observer, entity, root_context_id=str(root.id), clock_records=[clock])
    finally:
        await _finish_case(hass, temp, observer)


async def run_time() -> dict[str, Any]:
    case = "time"
    target = datetime.now(timezone.utc) + timedelta(minutes=2)
    at = target.strftime("%H:%M:%S")
    trigger = [{"platform": "time", "at": at, "id": "time_probe"}]
    action = [{"service": "test.capture", "data": {"marker": case}}]
    hass, temp, observer, entity = await _fresh_hass(case, trigger, action)
    try:
        clock = _drive_clock(hass, target + timedelta(seconds=1))
        await hass.async_block_till_done()
        return await _collect_case(case, "TIME", hass, observer, entity, root_context_id=None, clock_records=[clock])
    finally:
        await _finish_case(hass, temp, observer)


async def run_startup_delay() -> dict[str, Any]:
    case = "homeassistant_start_delay_30s"
    trigger = [{"platform": "homeassistant", "event": "start", "id": "startup_probe"}]
    action = [{"delay": {"seconds": 30}}, {"service": "test.capture", "data": {"marker": case}}]
    hass, temp, observer, entity = await _fresh_hass(case, trigger, action)
    try:
        root = Context()
        before = datetime.now(timezone.utc)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_START, context=root)
        await _wait_for_count(observer.automation_events, 1)
        # Do not block on the intentionally pending 30 s script delay. The
        # action-start event proves the native invocation has begun; the next
        # step drives the HA timer that the unchanged delay is awaiting.
        await asyncio.sleep(0)
        if observer.service_events:
            raise AssertionError("startup delay service fired before delay matured")
        clock = _drive_clock(hass, before + timedelta(seconds=31))
        await hass.async_block_till_done()
        return await _collect_case(case, "HOMEASSISTANT_START", hass, observer, entity, root_context_id=str(root.id), clock_records=[clock])
    finally:
        await _finish_case(hass, temp, observer)


async def experiment(role: str) -> dict[str, Any]:
    if HA_VERSION not in ALLOWED_VERSIONS:
        raise AssertionError("unadmitted Home Assistant version: %s" % HA_VERSION)
    admitted = {
        "T01_OLD_RUNTIME": "2022.10.0",
        "T01_NEW_RUNTIME": "2026.1.0",
        "T02_RUNTIME": "2026.9.0",
    }
    if role not in admitted or admitted[role] != HA_VERSION:
        raise AssertionError("role/runtime mismatch: %s on %s" % (role, HA_VERSION))

    rows = [await run_state()]
    if role == "T02_RUNTIME":
        rows.extend([await run_state_for(), await run_time(), await run_startup_delay()])

    result = {
        "schema": SCHEMA,
        "status": "PASS" if all(row["pass"] for row in rows) else "FAIL",
        "role": role,
        "home_assistant_version": HA_VERSION,
        "qualification_scope": "ORTHOGONAL_NEUTRAL_AUTOMATIONS_ONLY",
        "rows": rows,
        "clock_driver_id": CLOCK_DRIVER_ID if role == "T02_RUNTIME" else None,
        "scientific_hygiene": {
            "transition_blueprint_executed": False,
            "T01_or_T02_execution_state_used": False,
            "expected_frontier_read": False,
            "historical_better_thermostat_action_dispatched": False,
            "scientific_cells": 0,
            "frontier_result_seen": False,
        },
    }
    result["result_sha256"] = _sha({k: v for k, v in result.items() if k != "result_sha256"})
    return result


async def _main(args: argparse.Namespace) -> None:
    try:
        result = await experiment(args.role)
    except Exception as exc:
        result = {
            "schema": SCHEMA,
            "status": "INFRASTRUCTURE_INCOMPLETE",
            "role": args.role,
            "home_assistant_version": HA_VERSION,
            "failure": "%s: %s" % (type(exc).__name__, exc),
            "rows": [],
            "scientific_hygiene": {
                "transition_blueprint_executed": False,
                "T01_or_T02_execution_state_used": False,
                "expected_frontier_read": False,
                "historical_better_thermostat_action_dispatched": False,
                "scientific_cells": 0,
                "frontier_result_seen": False,
            },
        }
        result["result_sha256"] = _sha({k: v for k, v in result.items() if k != "result_sha256"})
    payload = json.dumps(result, sort_keys=True, indent=2, default=str) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(json.dumps({"schema":"replaymark.ve2.science-transport-close.v1","role":args.role,"artifact_sha256":hashlib.sha256(payload.encode()).hexdigest(),"scientific_cells":0}, sort_keys=True))
    if result.get("status") != "PASS":
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=["T01_OLD_RUNTIME", "T01_NEW_RUNTIME", "T02_RUNTIME"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
