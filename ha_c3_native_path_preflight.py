from __future__ import annotations

"""Non-scientific qualification of the caller-owned HA automation invocation path.

The exact external automation is executed both by its natural state trigger and
through Home Assistant's native automation.trigger service while the caller owns
suspension/resumption.  No ReplayMark gate or historical carrier is involved.
"""

import argparse
import asyncio
import json
from pathlib import Path
import time
from typing import Any

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import Context

from agentmark_natural_controllers.better_thermostat import experiment_persisted_ownership as base
from agentmark_natural_controllers.better_thermostat import n2_horizon_runtime as horizon

EXPECTED_HA_VERSION = "2026.9.0"


def _projection(event: dict[str, object]) -> dict[str, object]:
    if str(event.get("domain")) != "climate" or str(event.get("service")) != "set_preset_mode":
        raise AssertionError(("foreign consequential event", event))
    data = dict(event.get("service_data") or {})
    raw_target = data.get("entity_id")
    targets = [raw_target] if isinstance(raw_target, str) else list(raw_target or [])
    targets = [str(value) for value in targets]
    if targets != [base.CLIMATE_ENTITY]:
        raise AssertionError(("foreign target", targets))
    if set(data) != {"entity_id", "preset_mode"}:
        raise AssertionError(("unexpected service_data", data))
    return {
        "operation": "climate.set_preset_mode",
        "concrete_target": base.CLIMATE_ENTITY,
        "variant": json.dumps({"preset_mode": str(data["preset_mode"])}, sort_keys=True, separators=(",", ":")),
    }


def _automation_entity(hass: Any) -> str:
    entities = sorted(
        state.entity_id for state in hass.states.async_all()
        if state.entity_id.startswith("automation.")
    )
    if len(entities) != 1:
        raise AssertionError(("expected exactly one automation", entities))
    return entities[0]


async def _set_enabled(hass: Any, entity: str, enabled: bool) -> None:
    await hass.services.async_call(
        "automation",
        "turn_on" if enabled else "turn_off",
        {"entity_id": entity},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = hass.states.get(entity)
    expected = "on" if enabled else "off"
    if state is None or state.state != expected:
        raise AssertionError(("automation state", None if state is None else state.state, expected))


async def _wait_one(observer: horizon.HorizonObserver, before: int) -> dict[str, object]:
    await horizon.wait_for_service_count(observer, before + 1, timeout_s=2.0)
    await hass_yield()
    if len(observer.service_events) != before + 1:
        raise AssertionError(("service cardinality", before, len(observer.service_events)))
    return dict(observer.service_events[before])


async def hass_yield() -> None:
    await asyncio.sleep(0)


async def _caller_trigger(hass: Any, observer: horizon.HorizonObserver, entity: str) -> dict[str, object]:
    before = len(observer.service_events)
    await _set_enabled(hass, entity, True)
    if len(observer.service_events) != before:
        raise AssertionError("turn_on emitted consequential action")
    context = Context()
    started = time.perf_counter_ns()
    await hass.services.async_call(
        "automation",
        "trigger",
        {"entity_id": entity, "skip_condition": False},
        blocking=True,
        context=context,
    )
    await hass.async_block_till_done()
    event = await _wait_one(observer, before)
    completed = time.perf_counter_ns()
    await _set_enabled(hass, entity, False)
    if len(observer.service_events) != before + 1:
        raise AssertionError("turn_off raced consequential action")
    event_context = str(event.get("context_id"))
    event_parent = event.get("context_parent_id")
    if event_context != str(context.id) and (event_parent is None or str(event_parent) != str(context.id)):
        raise AssertionError(("manual trigger context not bound", str(context.id), event_context, event_parent))
    return {
        "projection": _projection(event),
        "trigger_context_id": str(context.id),
        "service_context_id": event_context,
        "service_context_parent_id": event_parent,
        "started_ns": started,
        "completed_ns": completed,
    }


async def _fresh(
    *, blueprint: Path, qualification: dict[str, object], motion: str, presence: str
):
    return await horizon.fresh_native(
        blueprint_source=blueprint,
        qualification=qualification,
        presence=presence,
        motion=motion,
        night="off",
    )


async def _cleanup(hass: Any, lab: Any, temp: Any, observer: horizon.HorizonObserver) -> None:
    observer.close()
    await base.cleanup_hass(hass, lab, temp)


async def _natural_away(blueprint: Path, qualification: dict[str, object]) -> dict[str, object]:
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer = await _fresh(
            blueprint=blueprint, qualification=qualification, motion="off", presence="on"
        )
        before = len(observer.service_events)
        hass.states.async_set(base.PRESENCE_ENTITY, "off", context=Context())
        await hass.async_block_till_done()
        return _projection(await _wait_one(observer, before))
    finally:
        if hass is not None:
            await _cleanup(hass, lab, temp, observer)


async def _manual_away(blueprint: Path, qualification: dict[str, object]) -> dict[str, object]:
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer = await _fresh(
            blueprint=blueprint, qualification=qualification, motion="off", presence="on"
        )
        entity = _automation_entity(hass)
        await _set_enabled(hass, entity, False)
        hass.states.async_set(base.PRESENCE_ENTITY, "off", context=Context())
        await hass.async_block_till_done()
        if observer.service_events:
            raise AssertionError("suspended away transition emitted service")
        return dict((await _caller_trigger(hass, observer, entity))["projection"])
    finally:
        if hass is not None:
            await _cleanup(hass, lab, temp, observer)


async def _natural_comfort(blueprint: Path, qualification: dict[str, object]) -> dict[str, object]:
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer = await _fresh(
            blueprint=blueprint, qualification=qualification, motion="on", presence="on"
        )
        before = len(observer.service_events)
        hass.states.async_set(base.PRESENCE_ENTITY, "off", context=Context())
        await hass.async_block_till_done()
        await _wait_one(observer, before)  # natural AWAY setup step
        before = len(observer.service_events)
        hass.states.async_set(base.PRESENCE_ENTITY, "on", context=Context())
        await hass.async_block_till_done()
        return _projection(await _wait_one(observer, before))
    finally:
        if hass is not None:
            await _cleanup(hass, lab, temp, observer)


async def _manual_comfort(blueprint: Path, qualification: dict[str, object]) -> dict[str, object]:
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer = await _fresh(
            blueprint=blueprint, qualification=qualification, motion="on", presence="off"
        )
        entity = _automation_entity(hass)
        await _set_enabled(hass, entity, False)
        # Exact C3 d1 pre-state: the preceding admitted d0 leaves preset=away.
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": [base.CLIMATE_ENTITY], "preset_mode": "away"},
            blocking=True,
        )
        await hass.async_block_till_done()
        observer.service_events.clear()
        hass.states.async_set(base.PRESENCE_ENTITY, "on", context=Context())
        await hass.async_block_till_done()
        if observer.service_events:
            raise AssertionError("suspended comfort transition emitted service")
        return dict((await _caller_trigger(hass, observer, entity))["projection"])
    finally:
        if hass is not None:
            await _cleanup(hass, lab, temp, observer)


async def run(args: argparse.Namespace) -> dict[str, object]:
    if HA_VERSION != EXPECTED_HA_VERSION:
        raise AssertionError(("HA version", HA_VERSION, EXPECTED_HA_VERSION))
    blueprint = Path(args.blueprint)
    component = Path(args.ownership_component)
    qualification, qtemp, qhass = await base.qualify_upstream_loader(component)
    try:
        natural_away = await _natural_away(blueprint, qualification)
        manual_away = await _manual_away(blueprint, qualification)
        natural_comfort = await _natural_comfort(blueprint, qualification)
        manual_comfort = await _manual_comfort(blueprint, qualification)
        result = {
            "schema": "replaymark.ha-c3.caller-native-path-preflight.v1",
            "scientific_result_opened": False,
            "ha_version": HA_VERSION,
            "away": {"natural": natural_away, "caller_managed": manual_away, "equal": natural_away == manual_away},
            "comfort": {"natural": natural_comfort, "caller_managed": manual_comfort, "equal": natural_comfort == manual_comfort},
        }
        result["status"] = "PASS" if result["away"]["equal"] and result["comfort"]["equal"] else "FAIL"
        return result
    finally:
        try:
            await qhass.async_stop()
        finally:
            qtemp.cleanup()


async def _main(args: argparse.Namespace) -> None:
    try:
        result = await run(args)
        rc = 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        result = {
            "schema": "replaymark.ha-c3.caller-native-path-preflight.v1",
            "scientific_result_opened": False,
            "status": "FAIL",
            "failure": f"{type(exc).__name__}: {exc}",
        }
        rc = 1
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")
    raise SystemExit(rc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blueprint", required=True)
    parser.add_argument("--ownership-component", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
