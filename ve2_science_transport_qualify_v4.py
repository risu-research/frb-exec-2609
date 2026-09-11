from __future__ import annotations

"""VE2 transport v4: prospective native-registry closure over frozen v3.

V3 proved that constructor selection, ConfigEntries, loader, timezone selection,
helper-trigger bootstrap, automation import ordering, and total failure evidence
all reach the native automation materialization boundary with zero trigger
stimuli.  Its sole common blocker was that Home Assistant's device/entity
registries had not been fully loaded before state-trigger validation and entity
platform registration.

V4 deliberately reuses the exact v3 neutral transport implementation and
changes only the pre-case native substrate ordering.  It fully loads the
native device registry and then the native entity registry through each frozen
HA runtime's official async load API before helper and automation setup.
No registry internals are synthesized or assigned by ReplayMark.
"""

import asyncio
import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import ve2_science_transport_qualify_v3 as v3

IMPLEMENTATION = "replaymark.ve2.science-transport-qualification-runtime.v4"
REGISTRY_CLOSURE_ID = "replaymark.ve2.native-device-entity-registry-closure.v1"


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _load_native_registry(
    hass: Any,
    module_name: str,
    *,
    required_collection: str,
) -> dict[str, Any]:
    """Fully load one native HA registry without synthetic internals.

    Selection is entirely prospective from the callable signature.  If a
    runtime exposes load_empty, v4 requests an empty native load because each
    neutral case uses a fresh temporary config directory and has no historical
    registry population.  Older runtimes execute their native no-keyword load.
    """
    module = importlib.import_module(module_name)
    data_key = getattr(module, "DATA_REGISTRY")
    present_before = data_key in hass.data
    if present_before:
        raise AssertionError(
            ("registry-present-before-v4-native-load", module_name, str(data_key))
        )

    setup = getattr(module, "async_setup", None)
    setup_called = False
    if callable(setup):
        await _await_if_needed(setup(hass))
        setup_called = True

    load = getattr(module, "async_load", None)
    if not callable(load):
        raise AssertionError(("native-registry-async-load-missing", module_name))
    signature = inspect.signature(load)
    kwargs: dict[str, Any] = {}
    if "load_empty" in signature.parameters:
        kwargs["load_empty"] = True
    await _await_if_needed(load(hass, **kwargs))

    async_get = getattr(module, "async_get", None)
    if not callable(async_get):
        raise AssertionError(("native-registry-async-get-missing", module_name))
    registry = async_get(hass)
    if inspect.isawaitable(registry):
        registry = await registry

    if not hasattr(registry, required_collection):
        raise AssertionError(
            ("native-registry-not-fully-loaded", module_name, required_collection)
        )
    collection = getattr(registry, required_collection)
    try:
        count = len(collection)
    except TypeError:
        count = len(list(collection))
    if count != 0:
        raise AssertionError(
            ("neutral-registry-not-empty", module_name, required_collection, count)
        )

    loaded_event = getattr(registry, "_loaded_event", None)
    loaded_event_present = loaded_event is not None
    loaded_event_set = None
    if loaded_event_present and callable(getattr(loaded_event, "is_set", None)):
        loaded_event_set = bool(loaded_event.is_set())
        if not loaded_event_set:
            raise AssertionError(("native-registry-loaded-event-not-set", module_name))

    return {
        "module": module_name,
        "registry_type": type(registry).__name__,
        "data_registry_present_before": present_before,
        "native_async_setup_present": callable(setup),
        "native_async_setup_called": setup_called,
        "native_async_load_signature": str(signature),
        "load_empty_selected_by_signature": "load_empty" in signature.parameters,
        "required_collection": required_collection,
        "required_collection_present_after": True,
        "required_collection_count_after": count,
        "loaded_event_present": loaded_event_present,
        "loaded_event_set_after": loaded_event_set,
        "manual_hass_data_registry_injection": False,
        "manual_registry_collection_assignment": False,
        "manual_loaded_event_manipulation": False,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


async def _prepare_registries(hass: Any) -> dict[str, Any]:
    device = await _load_native_registry(
        hass,
        "homeassistant.helpers.device_registry",
        required_collection="devices",
    )
    entity = await _load_native_registry(
        hass,
        "homeassistant.helpers.entity_registry",
        required_collection="entities",
    )
    return {
        "closure_id": REGISTRY_CLOSURE_ID,
        "order": ["device_registry", "entity_registry"],
        "device_registry": device,
        "entity_registry": entity,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


async def _prepare_native_substrate_v4(
    hass: Any,
    imports: dict[str, Any],
) -> dict[str, Any]:
    config_entries = v3._prepare_config_entries(hass, imports)
    loader_adapter = v3._prepare_loader(hass)
    if hasattr(hass.config, "skip_pip"):
        hass.config.skip_pip = True
    if hasattr(hass.config, "skip_pip_packages"):
        hass.config.skip_pip_packages = []
    timezone = await v3._prepare_timezone(hass)

    # V4's sole semantic delta from v3: full native registry closure occurs
    # before entity/condition/trigger helper setup or automation import.
    registries = await _prepare_registries(hass)
    helper = await v3._prepare_helper_substrate(hass)

    automation_mod = importlib.import_module("homeassistant.components.automation")
    native_event = getattr(
        automation_mod, "EVENT_AUTOMATION_TRIGGERED", None
    )
    native_domain = getattr(automation_mod, "DOMAIN", v3.AUTOMATION_DOMAIN)
    if native_event != v3.EVENT_AUTOMATION_TRIGGERED:
        raise AssertionError(("automation-triggered-event-identity", native_event))
    if native_domain != v3.AUTOMATION_DOMAIN:
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

    async_setup_component = getattr(
        imports["setup_module"], "async_setup_component", None
    )
    if not callable(async_setup_component):
        raise AssertionError("async_setup_component unavailable")

    return {
        "config_entries": config_entries,
        "loader": loader_adapter,
        "timezone": timezone,
        "registries": registries,
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


def _install_v4() -> None:
    v3.IMPLEMENTATION = IMPLEMENTATION
    v3._prepare_native_substrate = _prepare_native_substrate_v4


def main() -> None:
    _install_v4()
    v3.main()


if __name__ == "__main__":
    main()
