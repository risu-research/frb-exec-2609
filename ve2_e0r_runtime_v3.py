from __future__ import annotations

"""Orthogonal VE2-E0R runtime qualification.

Exercises native Home Assistant STATE/TIME/HOMEASSISTANT_START trigger payloads,
the already-qualified VE2 E0Q v2 boundary, SERVICE/CERTIFIED_NO_ACTION historical
behavior capsules, and single-use execution ownership. It executes no T01/T02
blueprint, no frozen VE2 scientific fixture, and no historical Better Thermostat
action.
"""

import argparse
import asyncio
import copy
from datetime import datetime, timedelta
import inspect
import json
from pathlib import Path
import time
from typing import Any

from homeassistant import loader
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import trigger as trigger_helper

import ve2_boundary_microkernel_v2 as boundary
import ve2_e0r_semantic_boundary_v1 as e0r

STATE_ENTITY = "sensor.ve2_e0r_state_trigger"
BOUNDARY_ENTITY = "sensor.ve2_e0r_behavior_anchor"
DOMAIN = "ve2_e0r"
SERVICE = "sink"


def construct_hass() -> HomeAssistant:
    sig = inspect.signature(HomeAssistant.__init__)
    p = sig.parameters.get("config_dir")
    required = bool(p is not None and p.default is inspect.Parameter.empty and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))
    if required:
        return HomeAssistant("/config")
    hass = HomeAssistant()
    hass.config.config_dir = "/config"
    return hass


def prepare_loader(hass: HomeAssistant) -> dict[str, Any]:
    key = loader.DATA_INTEGRATIONS
    before = key in hass.data
    setup = getattr(loader, "async_setup", None)
    if not before and callable(setup):
        setup(hass)
        strategy = "EXPLICIT_ASYNC_SETUP"
    elif before:
        strategy = "ALREADY_INITIALIZED"
    else:
        strategy = "LAZY_NATIVE"
    return {"strategy": strategy, "cache_before": before, "cache_after": key in hass.data}


def log_cb(*_args: Any, **_kwargs: Any) -> None:
    return None


async def native_trigger_case(hass: HomeAssistant, family: str) -> tuple[dict[str, Any], Any]:
    fired = asyncio.Event()
    captured: dict[str, Any] = {}

    async def action(run_variables: dict[str, Any], context: Context | None = None) -> None:
        if fired.is_set():
            raise AssertionError("trigger-fired-more-than-once")
        captured["run_variables"] = run_variables
        captured["context"] = context
        captured["observed_ns"] = time.perf_counter_ns()
        fired.set()

    if family == "STATE":
        hass.states.async_set(STATE_ENTITY, "off")
        await hass.async_block_till_done()
        config = [{"platform": "state", "entity_id": STATE_ENTITY, "from": "off", "to": "on", "id": "e0r_state"}]
    elif family == "TIME":
        target = datetime.now().astimezone() + timedelta(seconds=4)
        config = [{"platform": "time", "at": target.strftime("%H:%M:%S"), "id": "e0r_time"}]
    elif family == "HOMEASSISTANT_START":
        config = [{"platform": "homeassistant", "event": "start", "id": "e0r_startup"}]
    else:
        raise KeyError(family)

    validated = await trigger_helper.async_validate_trigger_config(hass, config)
    remove = await trigger_helper.async_initialize_triggers(
        hass, validated, action, "automation", "ve2_e0r_orthogonal", log_cb, variables={}
    )
    if remove is None:
        raise AssertionError("trigger-attach-returned-none:" + family)
    try:
        if family == "STATE":
            ctx = Context()
            captured["stimulus_context"] = ctx
            hass.states.async_set(STATE_ENTITY, "on", context=ctx)
        elif family == "HOMEASSISTANT_START":
            hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        # TIME is delivered only by the native time helper at the configured instant.
        try:
            await asyncio.wait_for(fired.wait(), timeout=12.0)
        except TimeoutError as exc:
            raise RuntimeError("INFRASTRUCTURE_INCOMPLETE:native-trigger-timeout:" + family) from exc
        await hass.async_block_till_done()
        witness = e0r.canonicalize_native_trigger(
            captured["run_variables"], captured.get("context"), observed_ns=int(captured["observed_ns"])
        )
        e0r.validate_invocation(witness)
        expected_id = {"STATE": "e0r_state", "TIME": "e0r_time", "HOMEASSISTANT_START": "e0r_startup"}[family]
        if witness["family"] != family or witness["native"]["id"] != expected_id:
            raise AssertionError(("native-trigger-identity", family, witness))
        if family == "STATE":
            if witness["native"]["entity_id"] != STATE_ENTITY:
                raise AssertionError("state-entity")
            if witness["native"]["from_state"]["state"] != "off" or witness["native"]["to_state"]["state"] != "on":
                raise AssertionError("state-transition")
            if witness["action_context_id"] != str(captured["stimulus_context"].id):
                raise AssertionError("state-action-context")
        if family == "TIME" and not witness["native"]["now_iso"]:
            raise AssertionError("time-native-now")
        if family == "HOMEASSISTANT_START" and witness["native"]["event"] != "start":
            raise AssertionError("startup-event")
        return witness, captured.get("context")
    finally:
        remove()
        await hass.async_block_till_done()


async def behavior_cases(hass: HomeAssistant, invocation: dict[str, Any], invocation_context: Context | None) -> dict[str, Any]:
    if invocation_context is None:
        raise AssertionError("state invocation context required for orthogonal behavior case")
    sink_calls: list[dict[str, Any]] = []

    async def sink_handler(call: Any) -> None:
        sink_calls.append({"context_id": str(call.context.id), "data": dict(call.data)})

    hass.services.async_register(DOMAIN, SERVICE, sink_handler)
    hass.states.async_set(BOUNDARY_ENTITY, "idle")
    await hass.async_block_till_done()
    observer = boundary.BoundaryObserver(hass)
    observer.install()
    try:
        epoch = observer.arm_epoch()
        hass.states.async_set(BOUNDARY_ENTITY, "service", context=invocation_context)
        await hass.services.async_call(
            DOMAIN, SERVICE,
            {"entity_id": ["climate.ve2_e0r_orthogonal"], "preset_mode": "orthogonal"},
            blocking=True, context=invocation_context,
        )
        completion = await boundary.completion_boundary(hass)
        parent = boundary.select_parent_state_event(
            observer.state_events, epoch=epoch, entity_id=BOUNDARY_ENTITY,
            old_state="idle", new_state="service", invocation_context_id=str(invocation_context.id),
        )
        events = boundary.require_exact_cardinality(
            boundary.qualifying_service_events(
                observer.service_events, epoch=epoch, domain=DOMAIN, service=SERVICE,
                invocation_context_id=str(invocation_context.id),
            ), 1,
        )
        service_event = events[0]
        boundary.require_positive_boundary(epoch, parent, service_event, completion)
        service_capsule = e0r.service_behavior(
            invocation=invocation, target="climate.ve2_e0r_orthogonal", service_event=service_event
        )
        e0r.validate_behavior(service_capsule)

        epoch2 = observer.arm_epoch()
        hass.states.async_set(BOUNDARY_ENTITY, "absence", context=invocation_context)
        completion2 = await boundary.completion_boundary(hass)
        parent2 = boundary.select_parent_state_event(
            observer.state_events, epoch=epoch2, entity_id=BOUNDARY_ENTITY,
            old_state="service", new_state="absence", invocation_context_id=str(invocation_context.id),
        )
        events2 = boundary.qualifying_service_events(
            observer.service_events, epoch=epoch2, domain=DOMAIN, service=SERVICE,
            invocation_context_id=str(invocation_context.id),
        )
        boundary.require_absence_boundary(epoch2, parent2, events2, completion2)
        absence_certificate = {
            "schema": "replaymark.ve2.qualified-absence-certificate.v1",
            "qualified": True,
            "qualifying_service_count": 0,
            "epoch": epoch2,
            "parent": parent2,
            "completion": completion2,
        }
        no_action_capsule = e0r.no_action_behavior(
            invocation=invocation, target="climate.ve2_e0r_orthogonal", absence_certificate=absence_certificate
        )
        e0r.validate_behavior(no_action_capsule)

        delegated: list[dict[str, Any]] = []
        gate_service = e0r.SingleUseBehaviorGate()
        admit_service = gate_service.execute(service_capsule, admission="ADMIT_REUSE", delegate=lambda ev: delegated.append(ev))
        if admit_service["historical_sink_calls"] != 1 or len(delegated) != 1:
            raise AssertionError("service-admit-cardinality")
        duplicate_rejected = False
        try:
            gate_service.execute(service_capsule, admission="ADMIT_REUSE", delegate=lambda ev: delegated.append(ev))
        except RuntimeError:
            duplicate_rejected = True
        if not duplicate_rejected:
            raise AssertionError("single-use-duplicate-not-rejected")

        gate_noop = e0r.SingleUseBehaviorGate()
        admit_noop = gate_noop.execute(no_action_capsule, admission="ADMIT_REUSE", delegate=lambda _ev: (_ for _ in ()).throw(AssertionError("noop delegated")))
        if admit_noop["historical_sink_calls"] != 0 or admit_noop["certified_noop_reuse"] is not True:
            raise AssertionError("noop-admit")

        block_service = e0r.SingleUseBehaviorGate().execute(service_capsule, admission="BLOCK_REUSE", delegate=lambda _ev: (_ for _ in ()).throw(AssertionError("blocked service delegated")))
        block_noop = e0r.SingleUseBehaviorGate().execute(no_action_capsule, admission="BLOCK_REUSE", delegate=lambda _ev: (_ for _ in ()).throw(AssertionError("blocked noop delegated")))
        if block_service["historical_sink_calls"] or block_noop["historical_sink_calls"]:
            raise AssertionError("block-crossed-sink")

        consume_before_failure = e0r.SingleUseBehaviorGate()
        delegate_failed = False
        try:
            consume_before_failure.execute(service_capsule, admission="ADMIT_REUSE", delegate=lambda _ev: (_ for _ in ()).throw(RuntimeError("synthetic-delegate-failure")))
        except RuntimeError as exc:
            if "synthetic-delegate-failure" not in str(exc):
                raise
            delegate_failed = True
        if not delegate_failed:
            raise AssertionError("delegate-failure-not-observed")
        retry_rejected = False
        try:
            consume_before_failure.execute(service_capsule, admission="ADMIT_REUSE", delegate=lambda _ev: None)
        except RuntimeError as exc:
            if "behavior-already-consumed" in str(exc):
                retry_rejected = True
        if not retry_rejected:
            raise AssertionError("consume-before-delegate-not-enforced")

        negatives = []
        tampered = copy.deepcopy(service_capsule); tampered["projected_action"]["operation"] = "tampered"
        for name, value in (("tampered_fingerprint", tampered),):
            try:
                e0r.validate_behavior(value)
            except Exception as exc:
                negatives.append({"case": name, "rejected": True, "type": type(exc).__name__})
            else:
                raise AssertionError(name)
        bad_absence = copy.deepcopy(absence_certificate); bad_absence["qualifying_service_count"] = 1
        try:
            e0r.no_action_behavior(invocation=invocation, target="climate.ve2_e0r_orthogonal", absence_certificate=bad_absence)
        except Exception as exc:
            negatives.append({"case": "nonzero_absence", "rejected": True, "type": type(exc).__name__})
        else:
            raise AssertionError("nonzero-absence-accepted")

        return {
            "service_boundary": {"epoch": epoch, "parent": parent, "event": service_event, "completion": completion},
            "absence_boundary": absence_certificate,
            "service_behavior": service_capsule,
            "no_action_behavior": no_action_capsule,
            "admit_service": admit_service,
            "admit_no_action": admit_noop,
            "block_service": block_service,
            "block_no_action": block_noop,
            "duplicate_rejected": duplicate_rejected,
            "delegate_failure_consumed_before_retry": retry_rejected,
            "negative_cases": negatives,
            "native_sink_handler_calls_during_boundary_fixture": len(sink_calls),
        }
    finally:
        observer.close()


async def main_async(out: Path) -> None:
    hass = construct_hass()
    loader_info = prepare_loader(hass)
    await trigger_helper.async_setup(hass)
    state_witness, state_context = await native_trigger_case(hass, "STATE")
    time_witness, _ = await native_trigger_case(hass, "TIME")
    startup_witness, _ = await native_trigger_case(hass, "HOMEASSISTANT_START")
    behaviors = await behavior_cases(hass, state_witness, state_context)

    result = {
        "schema": "replaymark.ve2.e0r-runtime-qualification.v1",
        "status": "PASS",
        "home_assistant_version": __import__("importlib.metadata").metadata.version("homeassistant"),
        "loader": loader_info,
        "native_invocations": {
            "STATE": state_witness,
            "TIME": time_witness,
            "HOMEASSISTANT_START": startup_witness,
        },
        "historical_behavior": behaviors,
        "qualified_families": ["STATE", "TIME", "HOMEASSISTANT_START", "SERVICE", "CERTIFIED_NO_ACTION"],
        "timeout_as_no_action": False,
        "transition_blueprint_executed": False,
        "scientific_fixture_executed": False,
        "historical_better_thermostat_action_dispatched": False,
        "scientific_result_opened": False,
        "frontier_result_seen": False,
        "ve2_home_assistant_scientific_cells": 0,
        "ve2_replaymark_scientific_cells": 0,
    }
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "families": result["qualified_families"]}, sort_keys=True))


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); args = ap.parse_args()
    asyncio.run(main_async(Path(args.out)))


if __name__ == "__main__":
    main()
