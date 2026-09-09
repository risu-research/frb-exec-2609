from __future__ import annotations

"""Independent literal semantic oracle for HA-C2.

This module imports no ReplayMark production code and no C2 native-target lift.
It reconstructs the target pre-service state from raw retained HA material,
computes the frozen thermostat law literally, and compares exact C0
action-instance identity.  The complete-domain oracle also parses canonical
state tokens itself so the 320-check audit does not derive its expected answer
from the production/native-lift implementation under test.
"""

import json
from typing import Mapping

CLIMATE_ENTITY = "climate.agentmark_thermostat"
_PRESETS = frozenset(("away", "home", "comfort", "sleep"))


def _strict_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"{name} must be mapping")
    return value


def _onoff(value: object) -> bool:
    if value == "on":
        return True
    if value == "off":
        return False
    raise AssertionError(("non-binary state", value))


def reconstruct_state(
    base_raw_observation: object,
    parent_state_event: object,
) -> tuple[bool, bool, bool, str]:
    top = _strict_mapping(base_raw_observation, "base observation")
    snap = dict(_strict_mapping(top["snapshot"], "base snapshot"))
    event = _strict_mapping(parent_state_event, "parent event")
    role = {
        "input_boolean.agentmark_presence": "presence",
        "input_boolean.agentmark_night": "night",
    }.get(event["entity_id"])
    if role is None:
        raise AssertionError("oracle received foreign trigger entity")
    if snap[role] != event["old_state"]:
        raise AssertionError("oracle old_state mismatch")
    if int(event["t_ns"]) < int(snap["t_ns"]):
        raise AssertionError("oracle trigger precedes base snapshot")
    snap[role] = event["new_state"]
    preset = str(snap["climate_preset"])
    if preset not in _PRESETS:
        raise AssertionError(("foreign climate preset", preset))
    return (
        _onoff(snap["presence"]),
        _onoff(snap["motion"]),
        _onoff(snap["night"]),
        preset,
    )


def parse_evidence_token(token: object) -> tuple[bool, bool, bool, str]:
    """Parse one modeled state token without importing ReplayMark/C2 model code."""
    if not isinstance(token, str) or not token or token != token.strip():
        raise AssertionError("evidence token must be a canonical non-empty string")
    try:
        raw = json.loads(token)
    except json.JSONDecodeError as exc:
        raise AssertionError(("malformed evidence token", token)) from exc
    if not isinstance(raw, list) or len(raw) != 4:
        raise AssertionError(("foreign evidence token shape", token))
    presence, motion, night, preset = raw
    if not all(isinstance(x, bool) for x in (presence, motion, night)):
        raise AssertionError(("non-boolean modeled state", token))
    if not isinstance(preset, str) or preset not in _PRESETS:
        raise AssertionError(("foreign modeled preset", token))
    canonical = json.dumps(raw, separators=(",", ":"), ensure_ascii=False).lower()
    if canonical != token:
        raise AssertionError(("non-canonical evidence token", token, canonical))
    return presence, motion, night, preset


def evidence_token(state: tuple[bool, bool, bool, str]) -> str:
    presence, motion, night, preset = state
    if not all(isinstance(x, bool) for x in (presence, motion, night)):
        raise AssertionError("oracle state booleans are malformed")
    if preset not in _PRESETS:
        raise AssertionError(("foreign oracle preset", preset))
    return json.dumps(list(state), separators=(",", ":"), ensure_ascii=False).lower()


def target_preset(state: tuple[bool, bool, bool, str]) -> str:
    presence, motion, night, _preset = state
    if night:
        return "sleep"
    if not presence:
        return "away"
    if motion:
        return "comfort"
    return "home"


def target_action(state: tuple[bool, bool, bool, str]) -> dict[str, object]:
    desired = target_preset(state)
    if state[3] == desired:
        return {
            "concrete_target": CLIMATE_ENTITY,
            "operation": "NO_ACTION",
            "variant": "NO_ACTION",
        }
    return {
        "concrete_target": CLIMATE_ENTITY,
        "operation": "climate.set_preset_mode",
        "variant": json.dumps(
            {"preset_mode": desired},
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def expected_action_for_evidence_token(token: object) -> dict[str, object]:
    """Literal complete-domain expected action for one canonical modeled token."""
    return target_action(parse_evidence_token(token))


def raw_service_projection(raw_action: object) -> dict[str, object]:
    top = _strict_mapping(raw_action, "raw action")
    svc = _strict_mapping(top["service_event"], "service event")
    data = _strict_mapping(svc["service_data"], "service data")
    targets = data["entity_id"]
    if not isinstance(targets, list) or len(targets) != 1:
        raise AssertionError("oracle requires one exact target")
    return {
        "concrete_target": targets[0],
        "operation": f"{svc['domain']}.{svc['service']}",
        "variant": json.dumps(
            {"preset_mode": data["preset_mode"]},
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def expected_cell(
    base_raw_observation: object,
    parent_state_event: object,
    historical_raw_action: object,
    target_direct_raw_action: object,
) -> dict[str, object]:
    state = reconstruct_state(base_raw_observation, parent_state_event)
    support = target_action(state)
    historical = raw_service_projection(historical_raw_action)
    direct = raw_service_projection(target_direct_raw_action)
    if direct != support:
        raise AssertionError(
            ("raw Direct action disagrees with literal frozen target law", direct, support, state)
        )
    valid = historical == support
    return {
        "evidence_token": evidence_token(state),
        "target_support": support,
        "historical_projection": historical,
        "direct_projection": direct,
        "verdict": "VALID" if valid else "INVALID",
        "reuse_disposition": "REUSE" if valid else "DO_NOT_REUSE",
        "admission": "ADMIT_REUSE" if valid else "BLOCK_REUSE",
    }


__all__ = (
    "evidence_token",
    "expected_action_for_evidence_token",
    "expected_cell",
    "parse_evidence_token",
    "raw_service_projection",
    "reconstruct_state",
    "target_action",
)
