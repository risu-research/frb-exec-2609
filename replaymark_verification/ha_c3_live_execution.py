from __future__ import annotations

"""Live HA-C3 producer over the complete frozen HA-C2 carrier population.

Scientific semantics are inherited unchanged.  This module supplies only the
fresh Home Assistant target/runtime orchestration needed to compare an
independent natural Direct instance with a separate ReplayMark-controlled
instance whose historical sink is owned by the HA-C3 execution gate.
"""

import argparse
import asyncio
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Iterable

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import Context

from agentmark_natural_controllers.better_thermostat import experiment_persisted_ownership as base
from agentmark_natural_controllers.better_thermostat import n2_horizon_runtime as horizon

from replaymark.execution_admission import ExecutionAdmissionDisposition
from replaymark.runtime_ha_bt_execution_gate import HaBtCertifiedExecutionGate
from replaymark.runtime_ha_bt_observation import (
    HA_BT_CLOCK_DOMAIN,
    HA_BT_OBSERVATION_CAPTURE_POINT,
    HA_BT_RAW_OBSERVATION_SCHEMA,
)
from replaymark.runtime_ha_bt_shadow_bridge import certify_ha_bt_shadow_reuse
from replaymark_verification.build_ha_c2_shadow_cells import ShadowCell, build_shadow_cells
from replaymark_verification.ha_c2_bt_native_target import compile_c2_contract

SCHEMA = "replaymark.ha-c3.live-native-execution.v1"
FIXTURE_PACKAGE_SHA256 = "297ec8740a4604e60b3b64b150a2489bb4ada2ddaf988f0202bdaf8649204ab1"
FIXTURE_DECODED_SHA256 = "d34de50c920643fcc9ed1d59c5127e09f2aa8d6805c11287739ee4267b865774"
EXPECTED_HA_VERSION = "2026.9.0"

_ENTITY_BINDINGS = {
    "presence": base.PRESENCE_ENTITY,
    "motion": base.MOTION_ENTITY,
    "night": base.NIGHT_ENTITY,
    "enable": base.ENABLE_ENTITY,
    "climate": base.CLIMATE_ENTITY,
}


def _now_ns() -> int:
    return time.perf_counter_ns()


def _load_fixture(path: Path) -> dict[str, object]:
    package = path.read_bytes()
    actual = hashlib.sha256(package).hexdigest()
    if actual != FIXTURE_PACKAGE_SHA256:
        raise AssertionError(("C1 fixture package digest changed", actual))
    decoded = gzip.decompress(base64.b64decode(package))
    decoded_sha = hashlib.sha256(decoded).hexdigest()
    if decoded_sha != FIXTURE_DECODED_SHA256:
        raise AssertionError(("C1 decoded fixture digest changed", decoded_sha))
    value = json.loads(decoded)
    if value.get("schema") != "replaymark.ha-c1.archived-fixtures.v1":
        raise AssertionError("foreign C1 fixture schema")
    return value


def _raw_observation(hass: Any, *, label: str) -> dict[str, object]:
    snap = horizon.current_snapshot(hass, label=label)
    return {
        "schema": HA_BT_RAW_OBSERVATION_SCHEMA,
        "capture_point": HA_BT_OBSERVATION_CAPTURE_POINT,
        "clock_domain": HA_BT_CLOCK_DOMAIN,
        "entities": dict(_ENTITY_BINDINGS),
        "snapshot": snap,
    }


def _parent_event(event: dict[str, object]) -> dict[str, object]:
    return {
        "t_ns": int(event["t_ns"]),
        "entity_id": str(event["entity_id"]),
        "old_state": str(event["old_state"]),
        "new_state": str(event["new_state"]),
        "context_id": str(event["context_id"]),
        "context_parent_id": event.get("context_parent_id"),
    }


def _service_projection(event: dict[str, object]) -> dict[str, object]:
    if str(event.get("domain")) != "climate" or str(event.get("service")) != "set_preset_mode":
        raise AssertionError(("foreign consequential service", event))
    data = dict(event.get("service_data") or {})
    raw_target = data.get("entity_id")
    if isinstance(raw_target, str):
        targets = [raw_target]
    elif isinstance(raw_target, (list, tuple)):
        targets = [str(x) for x in raw_target]
    else:
        raise AssertionError(("unresolved climate target", raw_target))
    if targets != [base.CLIMATE_ENTITY]:
        raise AssertionError(("foreign climate target", targets))
    if set(data) != {"entity_id", "preset_mode"}:
        raise AssertionError(("unexpected consequential service_data", data))
    preset = str(data["preset_mode"])
    return {
        "operation": "climate.set_preset_mode",
        "concrete_target": base.CLIMATE_ENTITY,
        "variant": json.dumps({"preset_mode": preset}, sort_keys=True, separators=(",", ":")),
    }


def _historical_projection(raw: dict[str, object]) -> dict[str, object]:
    event = dict(raw["service_event"])
    return _service_projection(event)


def _find_transition(
    observer: horizon.HorizonObserver,
    *,
    start_index: int,
    entity_id: str,
    old_state: str,
    new_state: str,
    context_id: str,
) -> dict[str, object]:
    matches = [
        e
        for e in observer.state_events[start_index:]
        if str(e.get("entity_id")) == entity_id
        and str(e.get("old_state")) == old_state
        and str(e.get("new_state")) == new_state
        and str(e.get("context_id")) == context_id
    ]
    if len(matches) != 1:
        raise AssertionError(("target transition cardinality", entity_id, old_state, new_state, context_id, len(matches)))
    return _parent_event(matches[0])


def _automation_entity(hass: Any) -> str:
    entities = sorted(
        state.entity_id
        for state in hass.states.async_all()
        if state.entity_id.startswith("automation.")
    )
    if len(entities) != 1:
        raise AssertionError(("expected one installed automation entity", entities))
    return entities[0]


async def _set_automation(hass: Any, entity_id: str, enabled: bool) -> None:
    await hass.services.async_call(
        "automation",
        "turn_on" if enabled else "turn_off",
        {"entity_id": entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    expected = "on" if enabled else "off"
    if state is None or state.state != expected:
        raise AssertionError(("automation state did not converge", entity_id, None if state is None else state.state, expected))


async def _transition_presence(
    hass: Any,
    observer: horizon.HorizonObserver,
    *,
    old_state: str,
    new_state: str,
) -> dict[str, object]:
    current = hass.states.get(base.PRESENCE_ENTITY)
    if current is None or current.state != old_state:
        raise AssertionError(("presence precondition", None if current is None else current.state, old_state))
    start = len(observer.state_events)
    context = Context()
    hass.states.async_set(base.PRESENCE_ENTITY, new_state, context=context)
    await hass.async_block_till_done()
    return _find_transition(
        observer,
        start_index=start,
        entity_id=base.PRESENCE_ENTITY,
        old_state=old_state,
        new_state=new_state,
        context_id=str(context.id),
    )


async def _fresh_runtime(
    *,
    blueprint: Path,
    qualification: dict[str, object],
    motion: str,
    presence: str = "on",
) -> tuple[Any, Any, Any, dict[str, object], horizon.HorizonObserver, str]:
    hass, lab, temp, registry, observer = await horizon.fresh_native(
        blueprint_source=blueprint,
        qualification=qualification,
        presence=presence,
        motion=motion,
        night="off",
    )
    entity = _automation_entity(hass)
    return hass, lab, temp, registry, observer, entity


async def _cleanup_runtime(hass: Any, lab: Any, temp: Any, observer: horizon.HorizonObserver) -> None:
    observer.close()
    await base.cleanup_hass(hass, lab, temp)


async def _wait_exact_new_service(
    observer: horizon.HorizonObserver,
    *,
    before: int,
    timeout_s: float = 2.0,
) -> dict[str, object]:
    await horizon.wait_for_service_count(observer, before + 1, timeout_s=timeout_s)
    await asyncio.sleep(0)
    if len(observer.service_events) != before + 1:
        raise AssertionError(("consequential service cardinality", before, len(observer.service_events)))
    return copy.deepcopy(observer.service_events[before])


async def _caller_native_once(
    hass: Any,
    observer: horizon.HorizonObserver,
    automation_entity: str,
) -> dict[str, object]:
    """Caller invokes the unchanged target automation once; ReplayMark is absent."""
    before = len(observer.service_events)
    started = _now_ns()
    await _set_automation(hass, automation_entity, True)
    if len(observer.service_events) != before:
        raise AssertionError("automation.turn_on itself emitted a consequential action")

    trigger_context = Context()
    await hass.services.async_call(
        "automation",
        "trigger",
        {"entity_id": automation_entity, "skip_condition": False},
        blocking=True,
        context=trigger_context,
    )
    await hass.async_block_till_done()
    event = await _wait_exact_new_service(observer, before=before)
    completed = _now_ns()

    # Re-suspend before any subsequent target transition.
    await _set_automation(hass, automation_entity, False)
    if len(observer.service_events) != before + 1:
        raise AssertionError("automation.turn_off emitted or raced a consequential action")

    event_context = str(event.get("context_id"))
    event_parent = event.get("context_parent_id")
    context_bound = event_context == str(trigger_context.id) or (
        event_parent is not None and str(event_parent) == str(trigger_context.id)
    )
    if not context_bound:
        raise AssertionError(("caller-native action not bound to trigger context", str(trigger_context.id), event_context, event_parent))

    return {
        "schema": "replaymark.ha-c3.caller-native-invocation.v1",
        "channel": "CALLER_NATIVE_AUTOMATION_TRIGGER",
        "automation_entity": automation_entity,
        "trigger_context_id": str(trigger_context.id),
        "started_ns": started,
        "completed_ns": completed,
        "context_bound": True,
        "service_event": event,
        "projection": _service_projection(event),
    }


async def _direct_family(
    *,
    blueprint: Path,
    qualification: dict[str, object],
    family: str,
) -> dict[str, object]:
    motion = "off" if family == "N2" else "on"
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer, automation_entity = await _fresh_runtime(
            blueprint=blueprint, qualification=qualification, motion=motion
        )
        decisions: list[dict[str, object]] = []
        transitions = [("on", "off")] if family == "N2" else [("on", "off"), ("off", "on")]
        for index, (old, new) in enumerate(transitions):
            base_raw = _raw_observation(hass, label=f"c3_direct_{family}_d{index}_base")
            before = len(observer.service_events)
            parent = await _transition_presence(hass, observer, old_state=old, new_state=new)
            event = await _wait_exact_new_service(observer, before=before)
            after = _raw_observation(hass, label=f"c3_direct_{family}_d{index}_after")
            decisions.append(
                {
                    "decision_index": index,
                    "base_raw_observation": base_raw,
                    "parent_state_event": parent,
                    "service_event": event,
                    "projection": _service_projection(event),
                    "after_raw_observation": after,
                }
            )
        return {
            "schema": "replaymark.ha-c3.direct-family.v1",
            "family": family,
            "status": "COMPLETE",
            "automation_entity": automation_entity,
            "registry": registry,
            "decisions": decisions,
            "failure": None,
        }
    except Exception as exc:
        return {
            "schema": "replaymark.ha-c3.direct-family.v1",
            "family": family,
            "status": "FAILED",
            "decisions": [],
            "failure": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if hass is not None and lab is not None and temp is not None and observer is not None:
            await _cleanup_runtime(hass, lab, temp, observer)


async def _gate_family(
    *,
    blueprint: Path,
    qualification: dict[str, object],
    family: str,
    historical_actions: list[dict[str, object]],
) -> dict[str, object]:
    motion = "off" if family == "N2" else "on"
    horizon_value = 0 if family == "N2" else 1
    transitions = [("on", "off")] if family == "N2" else [("on", "off"), ("off", "on")]
    if len(historical_actions) != len(transitions):
        raise AssertionError(("historical action cardinality", family, len(historical_actions), len(transitions)))

    hass = lab = temp = observer = None
    decisions: list[dict[str, object]] = []
    try:
        hass, lab, temp, registry, observer, automation_entity = await _fresh_runtime(
            blueprint=blueprint, qualification=qualification, motion=motion
        )
        await _set_automation(hass, automation_entity, False)
        if observer.service_events:
            raise AssertionError("consequential action occurred before suspended C3 target")

        contract = compile_c2_contract(horizon_value)
        gate = HaBtCertifiedExecutionGate()

        for index, ((old, new), historical_raw_action) in enumerate(zip(transitions, historical_actions)):
            row: dict[str, object] = {
                "decision_index": index,
                "historical_raw_action": copy.deepcopy(historical_raw_action),
                "historical_projection": _historical_projection(historical_raw_action),
                "pipeline_failure": None,
                "native_failure": None,
            }
            before_transition_services = len(observer.service_events)
            try:
                base_raw = _raw_observation(hass, label=f"c3_gate_{family}_d{index}_base")
                parent = await _transition_presence(hass, observer, old_state=old, new_state=new)
                if len(observer.service_events) != before_transition_services:
                    raise AssertionError("suspended target emitted consequential action before gate")

                cert = certify_ha_bt_shadow_reuse(
                    contract,
                    base_raw_observation=base_raw,
                    parent_state_event=parent,
                    historical_raw_action=historical_raw_action,
                )
                row["base_raw_observation"] = base_raw
                row["parent_state_event"] = parent
                row["presented_certificate"] = cert.canonical_record()
                row["presented_certificate_fingerprint"] = cert.fingerprint()

                before_gate = len(observer.service_events)
                receipt = await gate.dispatch(
                    hass,
                    contract,
                    base_raw_observation=base_raw,
                    parent_state_event=parent,
                    historical_raw_action=historical_raw_action,
                    presented_certificate=cert,
                )
                historical_events = copy.deepcopy(observer.service_events[before_gate:])
                row["gate_receipt"] = receipt.canonical_record()
                row["gate_receipt_fingerprint"] = receipt.fingerprint()
                row["historical_service_events"] = historical_events

                native = None
                if receipt.admission_disposition is ExecutionAdmissionDisposition.BLOCK_REUSE:
                    native = await _caller_native_once(hass, observer, automation_entity)
                row["caller_native"] = native
                row["after_raw_observation"] = _raw_observation(
                    hass, label=f"c3_gate_{family}_d{index}_after"
                )
            except Exception as exc:
                row["pipeline_failure"] = f"{type(exc).__name__}: {exc}"
                row.setdefault("base_raw_observation", None)
                row.setdefault("parent_state_event", None)
                row.setdefault("presented_certificate", None)
                row.setdefault("presented_certificate_fingerprint", None)
                row.setdefault("gate_receipt", None)
                row.setdefault("gate_receipt_fingerprint", None)
                row.setdefault("historical_service_events", [])
                row.setdefault("caller_native", None)
                row.setdefault("after_raw_observation", None)
                decisions.append(row)
                # A pipeline/sink/native failure is not semantic BLOCK and cannot
                # authorize fallback. Preserve the incomplete remainder instead
                # of trying to repair state in the scientific run.
                for missing in range(index + 1, len(transitions)):
                    decisions.append(
                        {
                            "decision_index": missing,
                            "historical_raw_action": copy.deepcopy(historical_actions[missing]),
                            "historical_projection": _historical_projection(historical_actions[missing]),
                            "pipeline_failure": "NOT_EXECUTED_AFTER_PRIOR_FAILURE",
                            "native_failure": None,
                            "base_raw_observation": None,
                            "parent_state_event": None,
                            "presented_certificate": None,
                            "presented_certificate_fingerprint": None,
                            "gate_receipt": None,
                            "gate_receipt_fingerprint": None,
                            "historical_service_events": [],
                            "caller_native": None,
                            "after_raw_observation": None,
                        }
                    )
                break
            else:
                decisions.append(row)

        return {
            "schema": "replaymark.ha-c3.gate-family.v1",
            "family": family,
            "status": "COMPLETE" if len(decisions) == len(transitions) and all(d["pipeline_failure"] is None for d in decisions) else "FAILED",
            "automation_entity": automation_entity,
            "registry": registry,
            "decisions": decisions,
            "failure": None,
        }
    except Exception as exc:
        while len(decisions) < len(transitions):
            idx = len(decisions)
            decisions.append(
                {
                    "decision_index": idx,
                    "historical_raw_action": copy.deepcopy(historical_actions[idx]),
                    "historical_projection": _historical_projection(historical_actions[idx]),
                    "pipeline_failure": f"FAMILY_SETUP_FAILURE: {type(exc).__name__}: {exc}",
                    "native_failure": None,
                    "base_raw_observation": None,
                    "parent_state_event": None,
                    "presented_certificate": None,
                    "presented_certificate_fingerprint": None,
                    "gate_receipt": None,
                    "gate_receipt_fingerprint": None,
                    "historical_service_events": [],
                    "caller_native": None,
                    "after_raw_observation": None,
                }
            )
        return {
            "schema": "replaymark.ha-c3.gate-family.v1",
            "family": family,
            "status": "FAILED",
            "decisions": decisions,
            "failure": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if hass is not None and lab is not None and temp is not None and observer is not None:
            await _cleanup_runtime(hass, lab, temp, observer)


def _group_carriers(cells: Iterable[ShadowCell]) -> tuple[list[ShadowCell], list[tuple[ShadowCell, ShadowCell]]]:
    n2 = sorted((c for c in cells if c.family == "N2"), key=lambda c: c.cell_id)
    raw_n2b = sorted((c for c in cells if c.family == "N2b"), key=lambda c: (c.replica, c.trial_ordinal, c.decision_index))
    grouped: dict[tuple[int, int], list[ShadowCell]] = {}
    for cell in raw_n2b:
        grouped.setdefault((cell.replica, cell.trial_ordinal), []).append(cell)
    pairs: list[tuple[ShadowCell, ShadowCell]] = []
    for key in sorted(grouped):
        pair = sorted(grouped[key], key=lambda c: c.decision_index)
        if [c.decision_index for c in pair] != [0, 1]:
            raise AssertionError(("malformed N2b carrier pair", key))
        pairs.append((pair[0], pair[1]))
    if len(n2) != 10 or len(pairs) != 10:
        raise AssertionError(("frozen carrier population changed", len(n2), len(pairs)))
    return n2, pairs


async def _natural_projection(
    *,
    blueprint: Path,
    qualification: dict[str, object],
    motion: str,
    sequence: list[tuple[str, str]],
) -> list[dict[str, object]]:
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer, automation_entity = await _fresh_runtime(
            blueprint=blueprint, qualification=qualification, motion=motion
        )
        out = []
        for old, new in sequence:
            before = len(observer.service_events)
            await _transition_presence(hass, observer, old_state=old, new_state=new)
            event = await _wait_exact_new_service(observer, before=before)
            out.append(_service_projection(event))
        return out
    finally:
        if hass is not None and lab is not None and temp is not None and observer is not None:
            await _cleanup_runtime(hass, lab, temp, observer)


async def _manual_projection(
    *,
    blueprint: Path,
    qualification: dict[str, object],
    target: str,
) -> dict[str, object]:
    motion = "off" if target == "away" else "on"
    initial_presence = "on" if target == "away" else "off"
    hass = lab = temp = observer = None
    try:
        hass, lab, temp, registry, observer, automation_entity = await _fresh_runtime(
            blueprint=blueprint,
            qualification=qualification,
            motion=motion,
            presence=initial_presence,
        )
        await _set_automation(hass, automation_entity, False)
        if target == "comfort":
            # Reproduce the exact C3 d1 pre-state: presence=off, motion=on,
            # current preset=away. This setup action is outside the result-bearing
            # invocation and is discarded from the comparison channel.
            await hass.services.async_call(
                "climate",
                "set_preset_mode",
                {"entity_id": [base.CLIMATE_ENTITY], "preset_mode": "away"},
                blocking=True,
            )
            await hass.async_block_till_done()
            observer.service_events.clear()
            old, new = "off", "on"
        else:
            old, new = "on", "off"
        before = len(observer.service_events)
        await _transition_presence(hass, observer, old_state=old, new_state=new)
        if len(observer.service_events) != before:
            raise AssertionError("suspended prequalification target emitted consequential action")
        native = await _caller_native_once(hass, observer, automation_entity)
        return dict(native["projection"])
    finally:
        if hass is not None and lab is not None and temp is not None and observer is not None:
            await _cleanup_runtime(hass, lab, temp, observer)


async def qualify_caller_native_path(
    *,
    blueprint: Path,
    qualification: dict[str, object],
) -> dict[str, object]:
    natural_away = (await _natural_projection(
        blueprint=blueprint,
        qualification=qualification,
        motion="off",
        sequence=[("on", "off")],
    ))[0]
    manual_away = await _manual_projection(
        blueprint=blueprint, qualification=qualification, target="away"
    )

    natural_n2b = await _natural_projection(
        blueprint=blueprint,
        qualification=qualification,
        motion="on",
        sequence=[("on", "off"), ("off", "on")],
    )
    natural_comfort = natural_n2b[1]
    manual_comfort = await _manual_projection(
        blueprint=blueprint, qualification=qualification, target="comfort"
    )

    result = {
        "schema": "replaymark.ha-c3.caller-native-equivalence.v1",
        "scientific_result_opened": False,
        "away": {"natural": natural_away, "caller_managed": manual_away, "equal": natural_away == manual_away},
        "comfort": {"natural": natural_comfort, "caller_managed": manual_comfort, "equal": natural_comfort == manual_comfort},
    }
    result["status"] = "PASS" if result["away"]["equal"] and result["comfort"]["equal"] else "FAIL"
    return result


async def experiment(args: argparse.Namespace) -> dict[str, object]:
    if HA_VERSION != EXPECTED_HA_VERSION:
        raise AssertionError(("Home Assistant version mismatch", HA_VERSION, EXPECTED_HA_VERSION))

    blueprint = Path(args.blueprint)
    fixture = Path(args.fixture)
    component = Path(args.ownership_component)
    blueprint_sha = hashlib.sha256(blueprint.read_bytes()).hexdigest()
    if blueprint_sha != base.EXPECTED_BLUEPRINT_SHA256:
        raise AssertionError(("blueprint digest mismatch", blueprint_sha, base.EXPECTED_BLUEPRINT_SHA256))

    pack = _load_fixture(fixture)
    cells = build_shadow_cells(pack)
    n2, n2b_pairs = _group_carriers(cells)

    qualification, qualification_temp, qualification_hass = await base.qualify_upstream_loader(component)
    try:
        native_qualification = await qualify_caller_native_path(
            blueprint=blueprint, qualification=qualification
        )
        if args.qualify_native_path_only:
            return {
                "schema": SCHEMA,
                "mode": "PRE_SCIENTIFIC_NATIVE_PATH_QUALIFICATION",
                "replica": args.replica,
                "ha_version": HA_VERSION,
                "blueprint_sha256": blueprint_sha,
                "native_path_qualification": native_qualification,
                "scientific_result_opened": False,
            }
        if native_qualification["status"] != "PASS":
            raise RuntimeError("caller-native path did not pass pre-live equivalence qualification")

        families: list[dict[str, object]] = []
        for ordinal, carrier in enumerate(n2):
            direct = await _direct_family(
                blueprint=blueprint, qualification=qualification, family="N2"
            )
            gate = await _gate_family(
                blueprint=blueprint,
                qualification=qualification,
                family="N2",
                historical_actions=[copy.deepcopy(carrier.historical_raw_action)],
            )
            families.append(
                {
                    "carrier_ordinal": ordinal,
                    "family": "N2",
                    "archived_carrier_ids": [carrier.cell_id],
                    "archived_source": {"replica": carrier.replica, "source_row_index": carrier.source_row_index},
                    "direct": direct,
                    "gate": gate,
                }
            )

        for ordinal, (d0, d1) in enumerate(n2b_pairs):
            direct = await _direct_family(
                blueprint=blueprint, qualification=qualification, family="N2b"
            )
            gate = await _gate_family(
                blueprint=blueprint,
                qualification=qualification,
                family="N2b",
                historical_actions=[copy.deepcopy(d0.historical_raw_action), copy.deepcopy(d1.historical_raw_action)],
            )
            families.append(
                {
                    "carrier_ordinal": ordinal,
                    "family": "N2b",
                    "archived_carrier_ids": [d0.cell_id, d1.cell_id],
                    "archived_source": {"replica": d0.replica, "source_row_index": d0.source_row_index},
                    "direct": direct,
                    "gate": gate,
                }
            )

        return {
            "schema": SCHEMA,
            "mode": "AUTHORITATIVE_LIVE_FIRST_COMPLETE",
            "replica": args.replica,
            "ha_version": HA_VERSION,
            "blueprint_sha256": blueprint_sha,
            "fixture_package_sha256": FIXTURE_PACKAGE_SHA256,
            "native_path_qualification": native_qualification,
            "carrier_population": {"n2": len(n2), "n2b_pairs": len(n2b_pairs), "sampling": "none"},
            "planned_live_decisions": 30,
            "families": families,
        }
    finally:
        try:
            await qualification_hass.async_stop()
        finally:
            qualification_temp.cleanup()


async def _run(args: argparse.Namespace) -> None:
    try:
        result = await experiment(args)
    except Exception as exc:
        result = {
            "schema": SCHEMA,
            "mode": "PRE_SCIENTIFIC_NATIVE_PATH_QUALIFICATION" if args.qualify_native_path_only else "AUTHORITATIVE_LIVE_FIRST_COMPLETE",
            "replica": args.replica,
            "fatal_failure": f"{type(exc).__name__}: {exc}",
            "families": [],
            "planned_live_decisions": 30 if not args.qualify_native_path_only else 0,
        }
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")
    if args.qualify_native_path_only:
        if result.get("native_path_qualification", {}).get("status") != "PASS":
            raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blueprint", required=True)
    parser.add_argument("--ownership-component", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--replica", type=int, required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--qualify-native-path-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
