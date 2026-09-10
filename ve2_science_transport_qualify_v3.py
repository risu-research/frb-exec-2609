from __future__ import annotations

"""VE2 cross-version pre-science transport qualifier v3.

This program executes only synthetic neutral Home Assistant automations. It
never reads or mounts VE2 scientific state manifests, expected frontiers,
transition blueprints, or Better Thermostat historical behaviors.

V3 is a prospective successor to the pre-neutral v2 failure. It closes the
entire minimal native Home Assistant bootstrap surface before any neutral
stimulus is emitted:
  * construct HomeAssistant by constructor capability;
  * import the normal HA bootstrap prerequisite graph before old automation;
  * install ConfigEntries exactly once;
  * prepare the loader using the already-E0Q-qualified capability strategy;
  * initialize entity/condition/trigger helper subsystems only when their
    native setup entrypoints exist; and
  * set UTC only if the constructor did not already provide the source-proven
    UTC default.

Every compatibility choice is made from API presence before case execution.
There is no retry after a failed API call and no result-dependent fallback.
"""

import argparse
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import tempfile
import time
from typing import Any
from unittest.mock import patch

from homeassistant import loader
from homeassistant.core import Context, CoreState, Event, HomeAssistant, ServiceCall, callback

SCHEMA = "replaymark.ve2.science-transport-qualification-runtime.v1"
IMPLEMENTATION = "replaymark.ve2.science-transport-qualification-runtime.v3"
PREFLIGHT_SCHEMA = "replaymark.ve2.science-transport-bootstrap-preflight.v3"
CLOCK_DRIVER_ID = "replaymark.ve2.ha-test-equivalent-clock-driver.v1"
ALLOWED_VERSIONS = {"2022.10.0", "2026.1.0", "2026.9.0"}
AUTOMATION_DOMAIN = "automation"
TRACE_DOMAIN = "trace"
EVENT_AUTOMATION_TRIGGERED = "automation_triggered"
EVENT_CALL_SERVICE = "call_service"
EVENT_STATE_CHANGED = "state_changed"
EVENT_HOMEASSISTANT_START = "homeassistant_start"
EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
NEUTRAL_ENTITY = "input_boolean.ve2_transport_probe"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ha_version() -> str:
    try:
        return importlib.metadata.version("homeassistant")
    except Exception:
        import homeassistant.const as ha_const

        value = getattr(ha_const, "__version__", None)
        return "UNKNOWN" if value is None else str(value)


HA_VERSION = _ha_version()


def _context_id(ctx: Any) -> str | None:
    if ctx is None:
        return None
    if isinstance(ctx, dict):
        value = ctx.get("id")
    else:
        value = getattr(ctx, "id", None)
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
        raise AssertionError("unqualified native trigger platform: %r" % platform)
    selected: dict[str, Any] = {
        "platform": platform,
        "family": family,
        "id": _json_scalar(raw.get("id")),
        "idx": _json_scalar(raw.get("idx")),
        "alias": _json_scalar(raw.get("alias")),
        "description": _json_scalar(raw.get("description")),
    }
    if platform == "state":
        selected.update(
            {
                "entity_id": _json_scalar(raw.get("entity_id")),
                "for": _json_scalar(raw.get("for")),
                "from_state_entity_id": _json_scalar(
                    getattr(raw.get("from_state"), "entity_id", None)
                ),
                "from_state": _json_scalar(getattr(raw.get("from_state"), "state", None)),
                "to_state_entity_id": _json_scalar(
                    getattr(raw.get("to_state"), "entity_id", None)
                ),
                "to_state": _json_scalar(getattr(raw.get("to_state"), "state", None)),
            }
        )
    elif platform == "time":
        selected["now"] = _json_scalar(raw.get("now"))
    else:
        selected["event"] = _json_scalar(raw.get("event"))
    return selected


def _construct_hass(config_dir: str) -> tuple[HomeAssistant, dict[str, Any]]:
    signature = inspect.signature(HomeAssistant.__init__)
    config = signature.parameters.get("config_dir")
    required = bool(
        config is not None
        and config.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and config.default is inspect.Parameter.empty
    )
    if required:
        hass = HomeAssistant(config_dir)
        strategy = "REQUIRED_CONFIG_DIR_POSITIONAL"
    else:
        hass = HomeAssistant()
        hass.config.config_dir = config_dir
        strategy = "NOARG_THEN_SET_CONFIG_DIR"
    return hass, {
        "strategy": strategy,
        "signature": {
            name: str(param)
            for name, param in signature.parameters.items()
            if name != "self"
        },
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


def _prepare_import_graph() -> dict[str, Any]:
    """Import the normal HA bootstrap prerequisite graph before automation.

    HA 2022.10's official bootstrap imports config_entries/entity machinery
    before integration setup. This prospective import ordering removes the
    bare-process circularity without retrying a failed automation import.
    """
    bootstrap = importlib.import_module("homeassistant.bootstrap")
    config_entries = importlib.import_module("homeassistant.config_entries")
    setup_mod = importlib.import_module("homeassistant.setup")
    return {
        "bootstrap_module": str(getattr(bootstrap, "__file__", "")),
        "config_entries_module": config_entries,
        "setup_module": setup_mod,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


def _prepare_config_entries(hass: HomeAssistant, imports: dict[str, Any]) -> dict[str, Any]:
    existing = getattr(hass, "config_entries", None)
    if existing is not None:
        manager = existing
        strategy = "CONSTRUCTOR_ALREADY_INITIALIZED"
    else:
        cls = imports["config_entries_module"].ConfigEntries
        signature = inspect.signature(cls.__init__)
        manager = cls(hass, {"_": "VE2_NEUTRAL_TRANSPORT_BOOTSTRAP"})
        hass.config_entries = manager
        strategy = "NATIVE_CONFIG_ENTRIES_HASS_CONFIG"

    initialized = getattr(manager, "_initialized", None)
    initialized_set = False
    if initialized is not None and callable(getattr(initialized, "set", None)):
        initialized.set()
        initialized_set = True

    shutdown = getattr(manager, "_async_shutdown", None)
    shutdown_registered = False
    if callable(shutdown):
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown)
        shutdown_registered = True

    return {
        "strategy": strategy,
        "manager_type": type(manager).__name__,
        "initialized_event_present": initialized is not None,
        "initialized_event_set_prospectively": initialized_set,
        "shutdown_hook_registered": shutdown_registered,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


def _prepare_loader(hass: HomeAssistant) -> dict[str, Any]:
    key = loader.DATA_INTEGRATIONS
    before = key in hass.data
    custom_key = getattr(loader, "DATA_CUSTOM_COMPONENTS", None)
    custom_seeded = False
    if custom_key is not None and custom_key not in hass.data:
        hass.data[custom_key] = {}
        custom_seeded = True

    setup = getattr(loader, "async_setup", None)
    present = callable(setup)
    if not before and present:
        setup(hass)
        strategy = "EXPLICIT_ASYNC_SETUP_API_PRESENT"
    elif not before:
        strategy = "LEGACY_NATIVE_LAZY_ASYNC_GET_INTEGRATION"
    else:
        strategy = "ALREADY_INITIALIZED"
    return {
        "strategy": strategy,
        "data_integrations_present_before": before,
        "loader_async_setup_api_present": present,
        "data_integrations_present_after": key in hass.data,
        "custom_components_cache_seeded": custom_seeded,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


async def _call_optional_setup(module_name: str, hass: HomeAssistant) -> dict[str, Any]:
    module = importlib.import_module(module_name)
    setup = getattr(module, "async_setup", None)
    if not callable(setup):
        return {
            "module": module_name,
            "async_setup_present": False,
            "strategy": "LEGACY_NO_EXPLICIT_SETUP_ENTRYPOINT",
            "result_dependent_fallback": False,
            "retry_after_failure": False,
        }
    result = setup(hass)
    if inspect.isawaitable(result):
        await result
        awaitable = True
    else:
        awaitable = False
    return {
        "module": module_name,
        "async_setup_present": True,
        "async_setup_awaitable": awaitable,
        "strategy": "NATIVE_ASYNC_SETUP_API_PRESENT",
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


async def _prepare_helper_substrate(hass: HomeAssistant) -> dict[str, Any]:
    # The order mirrors the relevant portion of HA's own test substrate:
    # entity -> condition -> trigger. Old HA simply lacks some entrypoints.
    entity = await _call_optional_setup("homeassistant.helpers.entity", hass)
    condition = await _call_optional_setup("homeassistant.helpers.condition", hass)
    trigger = await _call_optional_setup("homeassistant.helpers.trigger", hass)
    return {
        "entity": entity,
        "condition": condition,
        "trigger": trigger,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


async def _prepare_timezone(hass: HomeAssistant) -> dict[str, Any]:
    before = str(getattr(hass.config, "time_zone", ""))
    sync_setter = getattr(hass.config, "set_time_zone", None)
    async_setter = getattr(hass.config, "async_set_time_zone", None)
    if before == "UTC":
        strategy = "SOURCE_DEFAULT_UTC_VERIFIED_NO_MUTATION"
    elif callable(sync_setter):
        sync_setter("UTC")
        strategy = "SYNC_SET_TIME_ZONE_API_PRESENT"
    elif callable(async_setter):
        await async_setter("UTC")
        strategy = "ASYNC_SET_TIME_ZONE_API_PRESENT"
    else:
        raise AssertionError(("no-qualified-timezone-api", before))
    after = str(getattr(hass.config, "time_zone", ""))
    if after != "UTC":
        raise AssertionError(("timezone-not-utc", before, after, strategy))
    return {
        "strategy": strategy,
        "time_zone_before": before,
        "time_zone_after": after,
        "sync_setter_present": callable(sync_setter),
        "async_setter_present": callable(async_setter),
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


def _set_running(hass: HomeAssistant) -> dict[str, Any]:
    setter = getattr(hass, "set_state", None)
    if callable(setter):
        setter(CoreState.running)
        strategy = "SET_STATE_API_PRESENT"
    else:
        hass.state = CoreState.running
        strategy = "DIRECT_CORESTATE_COMPATIBILITY"
    if hass.state is not CoreState.running:
        raise AssertionError(("hass-not-running", str(hass.state)))
    return {"strategy": strategy, "state": str(hass.state)}


async def _prepare_native_substrate(
    hass: HomeAssistant, imports: dict[str, Any]
) -> dict[str, Any]:
    config_entries = _prepare_config_entries(hass, imports)
    loader_adapter = _prepare_loader(hass)
    if hasattr(hass.config, "skip_pip"):
        hass.config.skip_pip = True
    if hasattr(hass.config, "skip_pip_packages"):
        hass.config.skip_pip_packages = []
    timezone = await _prepare_timezone(hass)
    helper = await _prepare_helper_substrate(hass)

    automation_mod = importlib.import_module("homeassistant.components.automation")
    native_event = getattr(automation_mod, "EVENT_AUTOMATION_TRIGGERED", None)
    native_domain = getattr(automation_mod, "DOMAIN", AUTOMATION_DOMAIN)
    if native_event != EVENT_AUTOMATION_TRIGGERED:
        raise AssertionError(("automation-triggered-event-identity", native_event))
    if native_domain != AUTOMATION_DOMAIN:
        raise AssertionError(("automation-domain-identity", native_domain))

    try:
        trace_api = importlib.import_module("homeassistant.components.trace.util")
        trace_strategy = "COMPONENT_TRACE_UTIL"
    except ModuleNotFoundError as exc:
        if exc.name not in {
            "homeassistant.components.trace.util",
            "homeassistant.components.trace",
        }:
            raise
        trace_api = importlib.import_module("homeassistant.components.trace")
        trace_strategy = "COMPONENT_TRACE_ROOT"

    async_setup_component = getattr(imports["setup_module"], "async_setup_component", None)
    if not callable(async_setup_component):
        raise AssertionError("async_setup_component unavailable")

    return {
        "config_entries": config_entries,
        "loader": loader_adapter,
        "timezone": timezone,
        "helpers": helper,
        "automation_module": str(getattr(automation_mod, "__file__", "")),
        "trace_strategy": trace_strategy,
        "trace_api": trace_api,
        "async_setup_component": async_setup_component,
        "native_event": native_event,
        "native_domain": native_domain,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


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
            self.automation_events.append(
                {
                    "event_type": event.event_type,
                    "data": copy.deepcopy(dict(event.data)),
                    "context_id": str(event.context.id),
                    "context_parent_id": None
                    if event.context.parent_id is None
                    else str(event.context.parent_id),
                    "observed_ns": time.perf_counter_ns(),
                }
            )

        @callback
        def on_service(event: Event) -> None:
            if (
                str(event.data.get("domain")) != "test"
                or str(event.data.get("service")) != "capture"
            ):
                return
            self.service_events.append(
                {
                    "domain": "test",
                    "service": "capture",
                    "service_data": copy.deepcopy(dict(event.data.get("service_data") or {})),
                    "context_id": str(event.context.id),
                    "context_parent_id": None
                    if event.context.parent_id is None
                    else str(event.context.parent_id),
                    "observed_ns": time.perf_counter_ns(),
                }
            )

        @callback
        def on_state(event: Event) -> None:
            if str(event.data.get("entity_id")) != NEUTRAL_ENTITY:
                return
            old = event.data.get("old_state")
            new = event.data.get("new_state")
            self.state_events.append(
                {
                    "entity_id": NEUTRAL_ENTITY,
                    "old_state": None if old is None else old.state,
                    "new_state": None if new is None else new.state,
                    "context_id": None if new is None else str(new.context.id),
                    "context_parent_id": None
                    if new is None or new.context.parent_id is None
                    else str(new.context.parent_id),
                    "observed_ns": time.perf_counter_ns(),
                }
            )

        self._unsubs.append(
            self.hass.bus.async_listen(EVENT_AUTOMATION_TRIGGERED, on_automation)
        )
        self._unsubs.append(self.hass.bus.async_listen(EVENT_CALL_SERVICE, on_service))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, on_state))

    def close(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()


async def _trace_trigger_for_context(
    hass: HomeAssistant, trace_api: Any, context_id: str
) -> dict[str, Any]:
    raw_contexts = await trace_api.async_list_contexts(hass, None)
    contexts = {str(key): value for key, value in raw_contexts.items()}
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
        raise AssertionError(
            "expected exactly one native trigger trace element, got %d"
            % len(trigger_elements)
        )
    changed = trigger_elements[0].get("changed_variables") or {}
    raw_trigger = changed.get("trigger")
    if raw_trigger is None:
        raise AssertionError("native trace trigger element omitted run_variables['trigger']")
    return {
        "trace_ref": {"key": key, "run_id": ref["run_id"]},
        "trace_context_id": trace_context_id,
        "trigger": _trigger_witness(raw_trigger),
    }


def _scheduled_handle_accessor():
    module = importlib.import_module("homeassistant.util.async_")
    accessor = getattr(module, "get_scheduled_timer_handles", None)
    if not callable(accessor):
        raise AssertionError("Home Assistant scheduled-handle accessor unavailable")
    return accessor


def _drive_clock(
    hass: HomeAssistant, target_utc: datetime, *, fire_all: bool = False
) -> dict[str, Any]:
    if HA_VERSION != "2026.9.0":
        raise AssertionError("clock driver is qualified only on HA 2026.9.0")
    get_scheduled_timer_handles = _scheduled_handle_accessor()
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
                patch(
                    "homeassistant.helpers.event.time_tracker_utcnow",
                    return_value=target_utc,
                ),
                patch(
                    "homeassistant.helpers.event.time_tracker_timestamp",
                    return_value=timestamp,
                ),
            ):
                task._run()
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


async def _fresh_hass(
    case: str,
    trigger_config: Any,
    action_config: list[dict[str, Any]],
) -> tuple[HomeAssistant, tempfile.TemporaryDirectory[str], Observer, str, dict[str, Any], Any]:
    temp = tempfile.TemporaryDirectory(prefix="ve2-science-transport-%s-" % case)
    imports = _prepare_import_graph()
    hass, constructor = _construct_hass(temp.name)
    substrate = await _prepare_native_substrate(hass, imports)
    state_adapter = _set_running(hass)
    async_setup_component = substrate["async_setup_component"]

    trace_ok = await async_setup_component(hass, TRACE_DOMAIN, {})
    if not trace_ok:
        raise RuntimeError("neutral trace integration setup failed")

    observer = Observer(hass)
    observer.install()

    async def capture(_call: ServiceCall) -> None:
        return None

    hass.services.async_register("test", "capture", capture)
    hass.states.async_set(NEUTRAL_ENTITY, "off")
    await hass.async_block_till_done()

    alias = "VE2 Transport %s" % case
    config = {
        AUTOMATION_DOMAIN: [
            {
                "id": "ve2_transport_%s" % case,
                "alias": alias,
                "trigger": trigger_config,
                "condition": [],
                "action": action_config,
                "mode": "single",
            }
        ]
    }
    ok = await async_setup_component(hass, AUTOMATION_DOMAIN, config)
    if not ok:
        raise RuntimeError("neutral automation setup failed")
    await hass.async_block_till_done()
    entities = [state.entity_id for state in hass.states.async_all(AUTOMATION_DOMAIN)]
    if len(entities) != 1:
        raise AssertionError(
            "neutral qualification requires exactly one automation entity: %r" % entities
        )

    adapter = {
        "constructor": constructor,
        "imports": {
            "bootstrap_module": substrate.get("automation_module") and imports["bootstrap_module"],
            "result_dependent_fallback": False,
            "retry_after_failure": False,
        },
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
    return hass, temp, observer, entities[0], adapter, substrate["trace_api"]


async def _finish_case(
    hass: HomeAssistant,
    temp: tempfile.TemporaryDirectory[str],
    observer: Observer,
) -> None:
    observer.close()
    try:
        await hass.async_stop()
    finally:
        temp.cleanup()


async def _collect_case(
    case: str,
    expected_family: str,
    hass: HomeAssistant,
    observer: Observer,
    automation_entity: str,
    adapter: dict[str, Any],
    trace_api: Any,
    *,
    root_context_id: str | None,
    clock_records: list[dict[str, Any]],
) -> dict[str, Any]:
    await _wait_for_count(observer.automation_events, 1)
    await _wait_for_count(observer.service_events, 1)
    await hass.async_block_till_done()
    if len(observer.automation_events) != 1 or len(observer.service_events) != 1:
        raise AssertionError("neutral case must produce exactly one invocation and one service")
    inv = copy.deepcopy(observer.automation_events[0])
    svc = copy.deepcopy(observer.service_events[0])
    trace = await _trace_trigger_for_context(hass, trace_api, inv["context_id"])
    witness = trace["trigger"]
    row = {
        "case": case,
        "expected_family_for_qualification_only": expected_family,
        "automation_entity": automation_entity,
        "bootstrap_adapter": adapter,
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
            "fresh_context_not_root": root_context_id is None
            or inv["context_id"] != root_context_id,
            "invocation_parent_is_root_when_applicable": root_context_id is None
            or inv["context_parent_id"] == root_context_id,
            "single_invocation": len(observer.automation_events) == 1,
            "single_neutral_sink": len(observer.service_events) == 1,
        },
    }
    row["pass"] = all(row["checks"].values())
    row["row_sha256"] = _sha({k: v for k, v in row.items() if k != "row_sha256"})
    return row


async def bootstrap_preflight(role: str) -> dict[str, Any]:
    case = "bootstrap_preflight"
    trigger = [
        {
            "platform": "state",
            "entity_id": NEUTRAL_ENTITY,
            "from": "off",
            "to": "on",
            "id": "preflight_probe",
        }
    ]
    action = [{"service": "test.capture", "data": {"marker": case}}]
    hass, temp, observer, entity, adapter, trace_api = await _fresh_hass(case, trigger, action)
    try:
        await hass.async_block_till_done()
        raw_contexts = await trace_api.async_list_contexts(hass, None)
        result = {
            "schema": PREFLIGHT_SCHEMA,
            "implementation": IMPLEMENTATION,
            "status": "PASS",
            "role": role,
            "home_assistant_version": HA_VERSION,
            "automation_entity": entity,
            "bootstrap_adapter": adapter,
            "checks": {
                "zero_automation_invocations": len(observer.automation_events) == 0,
                "zero_neutral_service_calls": len(observer.service_events) == 0,
                "zero_native_trace_contexts": len(raw_contexts) == 0,
                "automation_entity_materialized": bool(entity.startswith("automation.")),
            },
            "scientific_hygiene": {
                "transition_blueprint_executed": False,
                "T01_or_T02_execution_state_used": False,
                "expected_frontier_read": False,
                "historical_better_thermostat_action_dispatched": False,
                "neutral_trigger_stimulus_emitted": False,
                "neutral_automation_invocations": 0,
                "scientific_cells": 0,
                "frontier_result_seen": False,
            },
        }
        if not all(result["checks"].values()):
            result["status"] = "FAIL"
        result["result_sha256"] = _sha(
            {k: v for k, v in result.items() if k != "result_sha256"}
        )
        return result
    finally:
        await _finish_case(hass, temp, observer)


async def run_state(case: str = "state") -> dict[str, Any]:
    trigger = [
        {
            "platform": "state",
            "entity_id": NEUTRAL_ENTITY,
            "from": "off",
            "to": "on",
            "id": "state_probe",
        }
    ]
    action = [{"service": "test.capture", "data": {"marker": case}}]
    hass, temp, observer, entity, adapter, trace_api = await _fresh_hass(case, trigger, action)
    try:
        root = Context()
        hass.states.async_set(NEUTRAL_ENTITY, "on", context=root)
        await hass.async_block_till_done()
        return await _collect_case(
            case,
            "STATE",
            hass,
            observer,
            entity,
            adapter,
            trace_api,
            root_context_id=str(root.id),
            clock_records=[],
        )
    finally:
        await _finish_case(hass, temp, observer)


async def run_state_for() -> dict[str, Any]:
    case = "state_for_120s"
    trigger = [
        {
            "platform": "state",
            "entity_id": NEUTRAL_ENTITY,
            "from": "off",
            "to": "on",
            "for": {"seconds": 120},
            "id": "state_for_probe",
        }
    ]
    action = [{"service": "test.capture", "data": {"marker": case}}]
    hass, temp, observer, entity, adapter, trace_api = await _fresh_hass(case, trigger, action)
    try:
        root = Context()
        before = datetime.now(timezone.utc)
        hass.states.async_set(NEUTRAL_ENTITY, "on", context=root)
        await hass.async_block_till_done()
        if observer.automation_events or observer.service_events:
            raise AssertionError("state-for automation fired before duration matured")
        clock = _drive_clock(hass, before + timedelta(seconds=121))
        await hass.async_block_till_done()
        return await _collect_case(
            case,
            "STATE",
            hass,
            observer,
            entity,
            adapter,
            trace_api,
            root_context_id=str(root.id),
            clock_records=[clock],
        )
    finally:
        await _finish_case(hass, temp, observer)


async def run_time() -> dict[str, Any]:
    case = "time"
    target = datetime.now(timezone.utc) + timedelta(minutes=2)
    at = target.strftime("%H:%M:%S")
    trigger = [{"platform": "time", "at": at, "id": "time_probe"}]
    action = [{"service": "test.capture", "data": {"marker": case}}]
    hass, temp, observer, entity, adapter, trace_api = await _fresh_hass(case, trigger, action)
    try:
        clock = _drive_clock(hass, target + timedelta(seconds=1))
        await hass.async_block_till_done()
        return await _collect_case(
            case,
            "TIME",
            hass,
            observer,
            entity,
            adapter,
            trace_api,
            root_context_id=None,
            clock_records=[clock],
        )
    finally:
        await _finish_case(hass, temp, observer)


async def run_startup_delay() -> dict[str, Any]:
    case = "homeassistant_start_delay_30s"
    trigger = [
        {
            "platform": "homeassistant",
            "event": "start",
            "id": "startup_probe",
        }
    ]
    action = [
        {"delay": {"seconds": 30}},
        {"service": "test.capture", "data": {"marker": case}},
    ]
    hass, temp, observer, entity, adapter, trace_api = await _fresh_hass(case, trigger, action)
    try:
        root = Context()
        before = datetime.now(timezone.utc)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_START, context=root)
        await _wait_for_count(observer.automation_events, 1)
        await asyncio.sleep(0)
        if observer.service_events:
            raise AssertionError("startup delay service fired before delay matured")
        clock = _drive_clock(hass, before + timedelta(seconds=31))
        await hass.async_block_till_done()
        return await _collect_case(
            case,
            "HOMEASSISTANT_START",
            hass,
            observer,
            entity,
            adapter,
            trace_api,
            root_context_id=str(root.id),
            clock_records=[clock],
        )
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
        "implementation": IMPLEMENTATION,
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
    result["result_sha256"] = _sha(
        {k: v for k, v in result.items() if k != "result_sha256"}
    )
    return result


async def _main(args: argparse.Namespace) -> None:
    diagnostic: dict[str, Any] = {
        "schema": PREFLIGHT_SCHEMA if args.preflight_only else SCHEMA,
        "implementation": IMPLEMENTATION,
        "role": args.role,
        "home_assistant_version": HA_VERSION,
        "phase": "PRE_CASE_BOOTSTRAP" if args.preflight_only else "NEUTRAL_CASES",
        "scientific_hygiene": {
            "transition_blueprint_executed": False,
            "T01_or_T02_execution_state_used": False,
            "expected_frontier_read": False,
            "historical_better_thermostat_action_dispatched": False,
            "scientific_cells": 0,
            "frontier_result_seen": False,
        },
    }
    try:
        if args.preflight_only:
            result = await bootstrap_preflight(args.role)
        else:
            result = await experiment(args.role)
    except Exception as exc:
        result = {
            **diagnostic,
            "status": "INFRASTRUCTURE_INCOMPLETE",
            "failure": "%s: %s" % (type(exc).__name__, exc),
            "rows": [],
        }
        result["result_sha256"] = _sha(
            {k: v for k, v in result.items() if k != "result_sha256"}
        )
    payload = json.dumps(result, sort_keys=True, indent=2, default=str) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": "replaymark.ve2.science-transport-close.v3",
                "role": args.role,
                "mode": "PREFLIGHT" if args.preflight_only else "QUALIFICATION",
                "artifact_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "scientific_cells": 0,
            },
            sort_keys=True,
        )
    )
    if result.get("status") != "PASS":
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--role",
        required=True,
        choices=["T01_OLD_RUNTIME", "T01_NEW_RUNTIME", "T02_RUNTIME"],
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
