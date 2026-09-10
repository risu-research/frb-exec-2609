from __future__ import annotations

"""SA1 raw-only native Home Assistant source-adequacy producer.

This producer deliberately does not import ReplayMark's expected semantic model,
SA1 expected table, q/R*, or any gate. It enumerates only the prospectively
frozen profile axes, executes the exact pinned Home Assistant automation, and
preserves raw state/service material. Expected outputs are compared later by an
independent pure-JSON validator.
"""

import argparse
import asyncio
import copy
import json
from pathlib import Path
from typing import Any

from homeassistant.components import automation
from homeassistant.const import EVENT_STATE_CHANGED, __version__ as HA_VERSION
from homeassistant.core import Context, Event, callback
from homeassistant.setup import async_setup_component

from agentmark_natural_controllers.better_thermostat import experiment_persisted_ownership as base

SCHEMA = "replaymark.sa1.native-source-adequacy-raw.v1"
EXPECTED_HA_VERSION = "2026.9.0"
PROFILE_PRESETS = ("away", "comfort", "home", "sleep")


def _state_id(presence: bool, motion: bool, night: bool, current_preset: str) -> str:
    return json.dumps([presence, motion, night, current_preset], separators=(",", ":"))


def _snapshot(hass: Any) -> dict[str, object]:
    def state(entity_id: str) -> str | None:
        value = hass.states.get(entity_id)
        return None if value is None else value.state

    climate = hass.states.get(base.CLIMATE_ENTITY)
    return {
        "presence": state(base.PRESENCE_ENTITY),
        "motion": state(base.MOTION_ENTITY),
        "night": state(base.NIGHT_ENTITY),
        "enable": state(base.ENABLE_ENTITY),
        "climate_entity": base.CLIMATE_ENTITY,
        "climate_state": None if climate is None else climate.state,
        "climate_preset": None if climate is None else climate.attributes.get("preset_mode"),
    }


class StateObserver:
    def __init__(self, hass: Any):
        self.events: list[dict[str, object]] = []

        @callback
        def on_state(event: Event) -> None:
            entity_id = str(event.data.get("entity_id"))
            if entity_id not in {
                base.PRESENCE_ENTITY,
                base.MOTION_ENTITY,
                base.NIGHT_ENTITY,
                base.ENABLE_ENTITY,
                base.CLIMATE_ENTITY,
            }:
                return
            old = event.data.get("old_state")
            new = event.data.get("new_state")
            self.events.append({
                "entity_id": entity_id,
                "old_state": None if old is None else old.state,
                "new_state": None if new is None else new.state,
                "old_attributes": {} if old is None else dict(old.attributes),
                "new_attributes": {} if new is None else dict(new.attributes),
                "context_id": str(event.context.id),
                "context_parent_id": None if event.context.parent_id is None else str(event.context.parent_id),
            })

        self._unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, on_state)

    def close(self) -> None:
        self._unsub()


async def _install_native_automation(hass: Any, temp: Any, registry: dict[str, object], blueprint: Path) -> str:
    destination = Path(temp.name) / "blueprints" / "automation" / "agentmark" / "better_thermostat_lean.yaml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(blueprint.read_bytes())
    ok = await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            "automation": {
                "use_blueprint": {
                    "path": base.BLUEPRINT_REL,
                    "input": {
                        "climate_device": registry["device_id"],
                        "presence_group": base.PRESENCE_ENTITY,
                        "motion_group": base.MOTION_ENTITY,
                        "night_mode_entity": base.NIGHT_ENTITY,
                        "enable_switch": base.ENABLE_ENTITY,
                        "writeback_enable": False,
                        "writeback_bounds_enable": False,
                        "boost_entity": "",
                        "eco_entity": "",
                        "activity_entity": "",
                    },
                }
            }
        },
    )
    if not ok:
        raise RuntimeError("native Better Thermostat automation setup returned false")
    await hass.async_block_till_done()
    entities = sorted(s.entity_id for s in hass.states.async_all() if s.entity_id.startswith("automation."))
    if len(entities) != 1:
        raise AssertionError(("expected exactly one native automation entity", entities))
    return entities[0]


async def _run_cell(
    *,
    blueprint: Path,
    qualification: dict[str, object],
    presence: bool,
    motion: bool,
    night: bool,
    current_preset: str,
) -> dict[str, object]:
    target_presence = "on" if presence else "off"
    pre_presence = "off" if presence else "on"
    hass, lab, temp, registry = await base.make_hass(
        blueprint_source=blueprint,
        qualification=qualification,
        native_automation=False,
        initial_presence=pre_presence,
    )
    state_observer = StateObserver(hass)
    try:
        # Seed all non-trigger coordinates before the native automation exists.
        # Presence is deliberately held at the opposite value so the measured
        # decision is caused by one real state trigger, not automation.trigger().
        hass.states.async_set(base.MOTION_ENTITY, "on" if motion else "off")
        hass.states.async_set(base.NIGHT_ENTITY, "on" if night else "off")
        hass.states.async_set(
            base.CLIMATE_ENTITY,
            "heat",
            {"preset_mode": current_preset, "temperature": 20.0},
        )
        hass.states.async_set(base.ENABLE_ENTITY, "on")
        await hass.async_block_till_done()

        automation_entity = await _install_native_automation(hass, temp, registry, blueprint)
        await hass.async_block_till_done()
        setup_calls = copy.deepcopy(lab.events)
        before_calls = len(lab.events)
        before_states = len(state_observer.events)
        pretrigger = _snapshot(hass)

        trigger_context = Context()
        hass.states.async_set(base.PRESENCE_ENTITY, target_presence, context=trigger_context)
        # Home Assistant state mutation is synchronous. Capture the exact target
        # decision condition before yielding to the event loop that runs the
        # automation action.
        decision_snapshot = _snapshot(hass)
        await hass.async_block_till_done()
        await asyncio.sleep(0)
        await hass.async_block_till_done()

        measured_calls = copy.deepcopy(lab.events[before_calls:])
        measured_states = copy.deepcopy(state_observer.events[before_states:])
        postdecision = _snapshot(hass)
        return {
            "state_id": _state_id(presence, motion, night, current_preset),
            "axes": {
                "presence": presence,
                "motion": motion,
                "night": night,
                "current_preset": current_preset,
            },
            "automation_entity": automation_entity,
            "registry": registry,
            "pretrigger_snapshot": pretrigger,
            "decision_snapshot": decision_snapshot,
            "trigger": {
                "entity_id": base.PRESENCE_ENTITY,
                "old_state": pre_presence,
                "new_state": target_presence,
                "context_id": str(trigger_context.id),
            },
            "setup_call_events": setup_calls,
            "measured_state_events": measured_states,
            "measured_service_events": measured_calls,
            "postdecision_snapshot": postdecision,
            "producer_error": None,
        }
    finally:
        state_observer.close()
        await base.cleanup_hass(hass, lab, temp)


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if HA_VERSION != EXPECTED_HA_VERSION:
        raise AssertionError(("unexpected Home Assistant version", HA_VERSION))
    qualification, qualification_temp, qualification_hass = await base.qualify_upstream_loader(args.ownership_component)
    cells: list[dict[str, object]] = []
    try:
        for presence in (False, True):
            for motion in (False, True):
                for night in (False, True):
                    for current_preset in PROFILE_PRESETS:
                        axes = {
                            "presence": presence,
                            "motion": motion,
                            "night": night,
                            "current_preset": current_preset,
                        }
                        try:
                            cell = await _run_cell(
                                blueprint=args.blueprint,
                                qualification=qualification,
                                **axes,
                            )
                        except Exception as exc:  # preserve the complete prospective population
                            cell = {
                                "state_id": _state_id(**axes),
                                "axes": axes,
                                "producer_error": {"type": type(exc).__name__, "message": str(exc)},
                            }
                        cells.append(cell)
    finally:
        try:
            await qualification_hass.async_stop()
        finally:
            qualification_temp.cleanup()

    return {
        "schema": SCHEMA,
        "replica": args.replica,
        "home_assistant_version": HA_VERSION,
        "profile_configuration": {
            "enable": True,
            "boost_entity": "UNSET",
            "eco_entity": "UNSET",
            "activity_entity": "UNSET",
            "writeback_enable": False,
            "writeback_bounds_enable": False,
        },
        "upstream_qualification": qualification,
        "cell_count": len(cells),
        "cells": cells,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blueprint", type=Path, required=True)
    parser.add_argument("--ownership-component", type=Path, required=True)
    parser.add_argument("--replica", type=int, choices=(0, 1), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": SCHEMA,
        "replica": args.replica,
        "cells": len(result["cells"]),
        "producer_errors": sum(cell.get("producer_error") is not None for cell in result["cells"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
