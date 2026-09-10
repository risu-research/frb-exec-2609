from __future__ import annotations

"""VE2 E0R generic invocation and Historical Behavior microkernel v1.

Pre-science, transition-label-free runtime boundary. It canonicalizes only native
Home Assistant trigger payloads, already-qualified service/absence boundaries,
and single-use execution ownership. It does not know T01/T02 expected frontiers,
Old-vs-New compatibility, class weights, source diffs, or scientific outcomes.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Callable

INVOCATION_SCHEMA = "replaymark.ve2.native-invocation-witness.v1"
BEHAVIOR_SCHEMA = "replaymark.ve2.historical-behavior-capsule.v1"
EXECUTION_SCHEMA = "replaymark.ve2.behavior-execution-receipt.v1"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _context_id(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "id", value)
    return None if raw is None else str(raw)


def _state_projection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        entity_id = value.get("entity_id")
        state = value.get("state")
        context = value.get("context")
        context_id = None if context is None else context.get("id") if isinstance(context, dict) else _context_id(context)
    else:
        entity_id = getattr(value, "entity_id", None)
        state = getattr(value, "state", None)
        context_id = _context_id(getattr(value, "context", None))
    if not isinstance(entity_id, str) or not entity_id:
        raise ValueError("state-projection-entity")
    if not isinstance(state, str) or not state:
        raise ValueError("state-projection-state")
    return {"entity_id": entity_id, "state": state, "context_id": context_id}


def canonicalize_native_trigger(run_variables: dict[str, Any], context: Any, *, observed_ns: int) -> dict[str, Any]:
    if not isinstance(run_variables, dict) or set(run_variables) != {"trigger"}:
        raise ValueError("run-variables-shape")
    trigger = run_variables["trigger"]
    if not isinstance(trigger, dict):
        raise ValueError("trigger-not-mapping")
    for key in ("id", "idx", "platform", "description"):
        if key not in trigger:
            raise ValueError("trigger-missing:" + key)
    trigger_id = trigger["id"]
    idx = trigger["idx"]
    platform = trigger["platform"]
    description = trigger["description"]
    alias = trigger.get("alias")
    if not isinstance(trigger_id, str) or not trigger_id:
        raise ValueError("trigger-id")
    if not isinstance(idx, str) or not idx:
        raise ValueError("trigger-idx")
    if alias is not None and not isinstance(alias, str):
        raise ValueError("trigger-alias")
    if not isinstance(platform, str) or not isinstance(description, str):
        raise ValueError("trigger-platform-description")
    if isinstance(observed_ns, bool) or not isinstance(observed_ns, int) or observed_ns < 0:
        raise ValueError("observed-ns")

    common = {
        "id": trigger_id,
        "idx": idx,
        "alias": alias,
        "platform": platform,
        "description": description,
    }
    if platform == "state":
        required = {"entity_id", "from_state", "to_state", "for"}
        if not required <= set(trigger):
            raise ValueError("state-trigger-missing-native-field")
        if not isinstance(trigger["entity_id"], str) or not trigger["entity_id"]:
            raise ValueError("state-trigger-entity")
        extra = {
            "entity_id": trigger["entity_id"],
            "from_state": _state_projection(trigger["from_state"]),
            "to_state": _state_projection(trigger["to_state"]),
            "for_seconds": None if trigger["for"] is None else float(trigger["for"].total_seconds()),
        }
        family = "STATE"
    elif platform == "time":
        if "now" not in trigger:
            raise ValueError("time-trigger-missing-now")
        now = trigger["now"]
        if not isinstance(now, datetime):
            raise ValueError("time-trigger-now-type")
        entity_id = trigger.get("entity_id")
        if entity_id is not None and not isinstance(entity_id, str):
            raise ValueError("time-trigger-entity")
        extra = {"now_iso": now.isoformat(), "entity_id": entity_id}
        family = "TIME"
    elif platform == "homeassistant":
        if trigger.get("event") != "start":
            raise ValueError("homeassistant-trigger-not-start")
        extra = {"event": "start"}
        family = "HOMEASSISTANT_START"
    else:
        raise ValueError("unsupported-trigger-platform:" + platform)

    value = {
        "schema": INVOCATION_SCHEMA,
        "family": family,
        "observed_ns": observed_ns,
        "action_context_id": _context_id(context),
        "raw_keyset": sorted(str(k) for k in trigger),
        "native": {**common, **extra},
    }
    value["fingerprint"] = digest(value)
    return value


def validate_invocation(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != INVOCATION_SCHEMA:
        raise ValueError("invocation-schema")
    supplied = value.get("fingerprint")
    body = dict(value); body.pop("fingerprint", None)
    if supplied != digest(body):
        raise ValueError("invocation-fingerprint")
    if value.get("family") not in {"STATE", "TIME", "HOMEASSISTANT_START"}:
        raise ValueError("invocation-family")
    return value


def service_behavior(*, invocation: dict[str, Any], target: str, service_event: dict[str, Any]) -> dict[str, Any]:
    validate_invocation(invocation)
    if not isinstance(target, str) or not target:
        raise ValueError("behavior-target")
    if not isinstance(service_event, dict):
        raise ValueError("service-event")
    for key in ("domain", "service", "service_data", "context_id", "context_parent_id", "sequence", "t_ns"):
        if key not in service_event:
            raise ValueError("service-event-missing:" + key)
    data = service_event["service_data"]
    if not isinstance(data, dict):
        raise ValueError("service-data")
    value = {
        "schema": BEHAVIOR_SCHEMA,
        "kind": "SERVICE",
        "invocation_fingerprint": invocation["fingerprint"],
        "projected_action": {
            "operation": f"{service_event['domain']}.{service_event['service']}",
            "concrete_target": target,
            "variant": json.dumps({k: data[k] for k in sorted(data) if k != "entity_id"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False),
        },
        "native_service_event": service_event,
        "absence_certificate": None,
    }
    value["fingerprint"] = digest(value)
    return value


def no_action_behavior(*, invocation: dict[str, Any], target: str, absence_certificate: dict[str, Any]) -> dict[str, Any]:
    validate_invocation(invocation)
    if not isinstance(target, str) or not target:
        raise ValueError("behavior-target")
    if not isinstance(absence_certificate, dict) or absence_certificate.get("qualified") is not True:
        raise ValueError("absence-not-qualified")
    if absence_certificate.get("qualifying_service_count") != 0:
        raise ValueError("absence-nonzero-service")
    value = {
        "schema": BEHAVIOR_SCHEMA,
        "kind": "CERTIFIED_NO_ACTION",
        "invocation_fingerprint": invocation["fingerprint"],
        "projected_action": {"operation": "NO_ACTION", "concrete_target": target, "variant": "NO_ACTION"},
        "native_service_event": None,
        "absence_certificate": absence_certificate,
    }
    value["fingerprint"] = digest(value)
    return value


def validate_behavior(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != BEHAVIOR_SCHEMA:
        raise ValueError("behavior-schema")
    supplied = value.get("fingerprint")
    body = dict(value); body.pop("fingerprint", None)
    if supplied != digest(body):
        raise ValueError("behavior-fingerprint")
    kind = value.get("kind")
    if kind == "SERVICE":
        if value.get("native_service_event") is None or value.get("absence_certificate") is not None:
            raise ValueError("service-behavior-shape")
    elif kind == "CERTIFIED_NO_ACTION":
        if value.get("native_service_event") is not None:
            raise ValueError("no-action-has-service")
        cert = value.get("absence_certificate")
        if not isinstance(cert, dict) or cert.get("qualified") is not True or cert.get("qualifying_service_count") != 0:
            raise ValueError("no-action-absence")
    else:
        raise ValueError("behavior-kind")
    return value


@dataclass
class SingleUseBehaviorGate:
    consumed: set[str]

    def __init__(self) -> None:
        self.consumed = set()

    def execute(self, behavior: dict[str, Any], *, admission: str, delegate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        validate_behavior(behavior)
        fp = str(behavior["fingerprint"])
        if fp in self.consumed:
            raise RuntimeError("behavior-already-consumed")
        if admission not in {"ADMIT_REUSE", "BLOCK_REUSE"}:
            raise ValueError("admission")
        self.consumed.add(fp)
        delegated = False
        certified_noop = False
        if admission == "ADMIT_REUSE":
            if behavior["kind"] == "SERVICE":
                delegate(behavior["native_service_event"])
                delegated = True
            else:
                certified_noop = True
        value = {
            "schema": EXECUTION_SCHEMA,
            "behavior_fingerprint": fp,
            "admission": admission,
            "consumed_before_delegate": True,
            "service_delegated": delegated,
            "certified_noop_reuse": certified_noop,
            "historical_sink_calls": 1 if delegated else 0,
            "fallback": False,
            "retry": False,
            "regeneration": False,
        }
        value["fingerprint"] = digest(value)
        return value
