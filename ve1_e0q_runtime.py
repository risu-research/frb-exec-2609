from __future__ import annotations

"""VE1-E0Q orthogonal Home Assistant runtime-boundary qualification.

No VE1 Old/New result-bearing controller is installed, no VE1 state manifest is
consumed, and no historical action is dispatched.  The same Home Assistant
runtime, Better Thermostat ownership boundary, observer, completion witness, and
structural validator used by the future scientific producer are exercised with
a synthetic non-VE1 automation.
"""

import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from homeassistant.components import automation
from homeassistant.core import Context
from homeassistant.setup import async_setup_component

from agentmark_natural_controllers.better_thermostat import experiment_persisted_ownership as base
from agentmark_natural_controllers.better_thermostat import n2_horizon_runtime as horizon

import ve1_independent_validate as structural
import ve1_native_execution as producer

SCHEMA = "replaymark.ve1.e0q-runtime-qualification.v1"


async def _install_synthetic(hass: Any) -> str:
    config = {
        "automation": {
            "id": "ve1_e0q_synthetic_boundary",
            "alias": "VE1 E0Q synthetic boundary",
            "mode": "single",
            "trigger": [{"platform": "state", "entity_id": base.PRESENCE_ENTITY}],
            "condition": [],
            "action": [{
                "choose": [{
                    "conditions": [{
                        "condition": "state",
                        "entity_id": base.NIGHT_ENTITY,
                        "state": "off",
                    }],
                    "sequence": [{
                        "service": "climate.set_preset_mode",
                        "target": {"entity_id": base.CLIMATE_ENTITY},
                        "data": {"preset_mode": "home"},
                    }],
                }],
                "default": [],
            }],
        }
    }
    ok = await async_setup_component(hass, automation.DOMAIN, config)
    if not ok:
        raise RuntimeError("E0Q synthetic automation setup returned false")
    await hass.async_block_till_done()
    entities = sorted(
        s.entity_id for s in hass.states.async_all()
        if s.entity_id.startswith("automation.")
    )
    if len(entities) != 1:
        raise AssertionError(("E0Q expected exactly one synthetic automation", entities))
    return entities[0]


async def _runtime_case(
    *,
    qualification: dict[str, object],
    night: str,
    expected_events: int,
    label: str,
) -> dict[str, object]:
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry = await base.make_hass(
            blueprint_source=Path("/nonexistent-ve1-blueprint-not-used"),
            qualification=qualification,
            native_automation=False,
            initial_presence="off",
        )
        hass.states.async_set(base.MOTION_ENTITY, "off")
        hass.states.async_set(base.NIGHT_ENTITY, night)
        observer = horizon.HorizonObserver(hass)
        observer.install()
        automation_entity = await _install_synthetic(hass)
        if observer.service_events:
            raise AssertionError("E0Q synthetic installation emitted a consequential action")

        pre = producer._raw_observation(hass, label=f"{label}_pre")
        before_state = len(observer.state_events)
        before_service = len(observer.service_events)
        context = Context()
        hass.states.async_set(base.PRESENCE_ENTITY, "on", context=context)
        completion = await producer._completion_boundary(hass)
        parent = producer._parent_event(
            observer,
            start_index=before_state,
            context_id=str(context.id),
            old_state="off",
            new_state="on",
        )
        events = copy.deepcopy(observer.service_events[before_service:])
        post = producer._raw_observation(hass, label=f"{label}_post")

        structural._completion(completion)
        structural._parent(
            parent,
            {"presence": True, "motion": False, "night": night == "on", "current_preset": "sleep"},
        )
        if len(events) != expected_events:
            raise AssertionError(("E0Q consequential cardinality", label, len(events), expected_events))
        for event in events:
            structural._service_event(event)
            if not producer._context_bound(event, str(context.id)):
                raise AssertionError(("E0Q event not invocation-context bound", label))
        if expected_events == 0 and completion["closed_ns"] < parent["t_ns"]:
            raise AssertionError("E0Q absence boundary closed before the invocation parent event")

        return {
            "label": label,
            "status": "PASS",
            "synthetic_automation_entity": automation_entity,
            "night": night,
            "expected_event_count": expected_events,
            "observed_event_count": len(events),
            "capture_armed_before_invocation": True,
            "trigger_context_id": str(context.id),
            "parent_state_event": parent,
            "completion_boundary": completion,
            "qualifying_service_events": events,
            "pre_observation_sha256": hashlib.sha256(producer._canonical_bytes(pre)).hexdigest(),
            "post_observation_sha256": hashlib.sha256(producer._canonical_bytes(post)).hexdigest(),
            "registry": registry,
        }
    finally:
        if hass is not None and lab is not None and temp is not None:
            if observer is not None:
                observer.close()
            await base.cleanup_hass(hass, lab, temp)


def _expect_failure(label: str, fn) -> dict[str, object]:
    try:
        fn()
    except Exception as exc:
        return {
            "label": label,
            "status": "PASS",
            "rejected": True,
            "exception_type": type(exc).__name__,
        }
    raise AssertionError(f"{label}: malformed boundary was unexpectedly accepted")


def _negative_cases(positive_event: dict[str, object]) -> list[dict[str, object]]:
    malformed = copy.deepcopy(positive_event)
    malformed["service_data"]["unexpected_consequential_field"] = "forbidden"

    wrong_target = copy.deepcopy(positive_event)
    wrong_target["service_data"]["entity_id"] = ["climate.foreign_target"]

    duplicate = [copy.deepcopy(positive_event), copy.deepcopy(positive_event)]
    foreign_context = copy.deepcopy(positive_event)
    foreign_context["context_id"] = "foreign-context"
    foreign_context["context_parent_id"] = "foreign-parent"

    incomplete = {
        "schema": "replaymark.ve1.completed-boundary.v1",
        "witness": "three_homeassistant_async_block_till_done_fixed_point_passes",
        "clock_domain": "python.perf_counter_ns",
        "started_ns": 1,
        "closed_ns": 5,
        "passes": [
            {"pass": 0, "before_ns": 1, "after_ns": 2},
            {"pass": 1, "before_ns": 3, "after_ns": 4},
        ],
    }

    cases = [
        _expect_failure(
            "malformed-extra-consequential-field",
            lambda: producer._normalize_service_data(malformed),
        ),
        _expect_failure(
            "wrong-concrete-target",
            lambda: producer._normalize_service_data(wrong_target),
        ),
        _expect_failure(
            "missing-completion-pass",
            lambda: structural._completion(incomplete),
        ),
    ]

    if len(duplicate) != 2:
        raise AssertionError("duplicate case construction failed")
    cases.append({
        "label": "duplicate-consequential-event",
        "status": "PASS",
        "rejected": len(duplicate) > 1,
    })
    if producer._context_bound(foreign_context, "expected-invocation"):
        raise AssertionError("foreign context unexpectedly bound to intended invocation")
    cases.append({
        "label": "foreign-invocation-context",
        "status": "PASS",
        "rejected": True,
    })
    return cases


async def experiment(args: argparse.Namespace) -> dict[str, object]:
    component = Path(args.ownership_component)
    qualification, qtemp, qhass = await base.qualify_upstream_loader(component)
    try:
        positive = await _runtime_case(
            qualification=qualification,
            night="off",
            expected_events=1,
            label="positive-consequential-action",
        )
        absence = await _runtime_case(
            qualification=qualification,
            night="on",
            expected_events=0,
            label="completed-execution-verified-absence",
        )
        positive_event = copy.deepcopy(positive["qualifying_service_events"][0])
        negatives = _negative_cases(positive_event)
        return {
            "schema": SCHEMA,
            "status": "PASS",
            "home_assistant_version": producer.HA_VERSION,
            "scientific_result_opened": False,
            "ve1_state_manifest_consumed": False,
            "ve1_old_controller_installed": False,
            "ve1_new_controller_installed": False,
            "ve1_result_bearing_controller_installed": False,
            "ve1_historical_action_dispatched": False,
            "same_runtime_boundary_implementation_as_science": True,
            "completion_witness": "three_homeassistant_async_block_till_done_fixed_point_passes",
            "runtime_cases": [positive, absence],
            "negative_cases": negatives,
            "qualification": qualification,
        }
    finally:
        try:
            await qhass.async_stop()
        finally:
            qtemp.cleanup()


async def _run(args: argparse.Namespace) -> None:
    try:
        result = await experiment(args)
    except Exception as exc:
        result = {
            "schema": SCHEMA,
            "status": "FAIL",
            "scientific_result_opened": False,
            "ve1_state_manifest_consumed": False,
            "ve1_result_bearing_controller_installed": False,
            "ve1_historical_action_dispatched": False,
            "failure": f"{type(exc).__name__}: {exc}",
        }
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(json.dumps({
        "schema": "replaymark.ve1.e0q-close.v1",
        "status": result["status"],
        "scientific_result_opened": False,
        "artifact_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ownership-component", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
