from __future__ import annotations

"""Strict Home Assistant Better-Thermostat-profile service-call record -> historical action realization.

The realizer preserves concrete service identity and rendered parameters.  It
does not accept a semantic verdict, controller label, expected preset, or
caller-supplied same-task flag.  Context linkage is proven from the raw service
event and its retained parent state event before any semantic certification.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, NoReturn, Sequence

from .contracts import ProjectedAction, Scalar
from .runtime_realization import (
    RealizationError,
    RealizationFailure,
    RealizationFailureCode,
    RealizationStage,
    RealizedHistoricalAction,
    historical_action_provenance,
)

HA_BT_RAW_ACTION_SCHEMA = "replaymark.runtime.ha-bt-historical-action-record.v1"
HA_BT_ACTION_CAPTURE_POINT = "homeassistant.event_bus.EVENT_CALL_SERVICE"
HA_BT_ACTION_REALIZER_ID = "replaymark.ha-bt-historical-action-realizer.v1"
HA_BT_CLOCK_DOMAIN = "python.perf_counter_ns"
HA_BT_FROZEN_TARGET_ENTITY = "climate.agentmark_thermostat"

_FAILURE_SCHEMA = "replaymark.runtime.realization-failure.v1"
_ACTION_SCHEMA = "replaymark.runtime.realized-historical-action.v1"

_RULE_RECORD = {
    "schema": "replaymark.realizer-semantics.ha-bt-historical-action.v1",
    "source_schema": HA_BT_RAW_ACTION_SCHEMA,
    "capture_point": HA_BT_ACTION_CAPTURE_POINT,
    "clock_domain": HA_BT_CLOCK_DOMAIN,
    "service": {"domain": "climate", "service": "set_preset_mode"},
    "target": HA_BT_FROZEN_TARGET_ENTITY,
    "service_data": {"required": ["entity_id", "preset_mode"], "unknown_fields": "reject"},
    "context": {"service_context_parent_must_equal_parent_state_context": True, "parent_timestamp_must_not_follow_service": True},
    "projected_coordinates": ["operation", "target_class", "variant", "concrete_target", "service_domain", "service_name", "preset_mode"],
    "preset_semantic_whitelist": False,
    "semantic_verdict_from_caller": False,
    "execution": False,
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


HA_BT_ACTION_REALIZER_SEMANTIC_DIGEST = _sha256(_canonical_json_bytes(_RULE_RECORD))


def _best_effort_digest(raw: object) -> str | None:
    try:
        return _sha256(_canonical_json_bytes(raw))
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError):
        return None


def _fail(*, code: RealizationFailureCode, message: str, raw: object, details: Sequence[tuple[str, Scalar]] = ()) -> NoReturn:
    raise RealizationError(
        RealizationFailure(
            schema_version=_FAILURE_SCHEMA,
            stage=RealizationStage.HISTORICAL_ACTION,
            code=code,
            realizer_id=HA_BT_ACTION_REALIZER_ID,
            message=message,
            raw_record_digest=_best_effort_digest(raw),
            details=tuple(details),
        )
    )


def _token(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise TypeError(f"{name} must be a non-empty canonical string")
    value.encode("utf-8")
    return value


def _ns(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f"{name} must be a non-negative integer nanosecond timestamp")
    return value


@dataclass(frozen=True)
class HaBtHistoricalActionRecord:
    schema_version: str
    capture_point: str
    clock_domain: str
    service_timestamp_ns: int
    domain: str
    service: str
    concrete_target: str
    preset_mode: str
    context_id: str
    context_parent_id: str
    parent_state_timestamp_ns: int
    parent_state_entity_id: str
    parent_state_old_state: str
    parent_state_new_state: str
    parent_state_context_id: str
    parent_state_context_parent_id: str | None

    def variant(self) -> str:
        return json.dumps({"preset_mode": self.preset_mode}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "capture_point": self.capture_point,
            "clock_domain": self.clock_domain,
            "service_event": {
                "t_ns": self.service_timestamp_ns,
                "domain": self.domain,
                "service": self.service,
                "service_data": {"entity_id": [self.concrete_target], "preset_mode": self.preset_mode},
                "context_id": self.context_id,
                "context_parent_id": self.context_parent_id,
            },
            "parent_state_event": {
                "t_ns": self.parent_state_timestamp_ns,
                "entity_id": self.parent_state_entity_id,
                "old_state": self.parent_state_old_state,
                "new_state": self.parent_state_new_state,
                "context_id": self.parent_state_context_id,
                "context_parent_id": self.parent_state_context_parent_id,
            },
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_record())

    def fingerprint(self) -> str:
        return _sha256(self.canonical_bytes())


def _strict_keys(value: object, expected: set[str], *, raw: object, name: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message=f"{name} must be a mapping", raw=raw)
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected, key=repr)
    if missing:
        _fail(code=RealizationFailureCode.MISSING_REQUIRED_FIELD, message=f"{name} is missing a required field", raw=raw, details=(("field", missing[0]),))
    if unknown:
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message=f"{name} contains an unknown field", raw=raw, details=(("field", repr(unknown[0])),))
    return value


def parse_ha_bt_historical_action_record(raw: object) -> HaBtHistoricalActionRecord:
    top = _strict_keys(raw, {"schema", "capture_point", "clock_domain", "service_event", "parent_state_event"}, raw=raw, name="HA historical-action record")
    if top["schema"] != HA_BT_RAW_ACTION_SCHEMA:
        _fail(code=RealizationFailureCode.UNKNOWN_SEMANTIC_VALUE, message="foreign HA historical-action schema", raw=raw)
    if top["capture_point"] != HA_BT_ACTION_CAPTURE_POINT:
        _fail(code=RealizationFailureCode.UNKNOWN_SEMANTIC_VALUE, message="unsupported HA action capture point", raw=raw)
    if top["clock_domain"] != HA_BT_CLOCK_DOMAIN:
        _fail(code=RealizationFailureCode.CLOCK_DOMAIN_MISMATCH, message="HA action uses a foreign clock domain", raw=raw)
    svc = _strict_keys(top["service_event"], {"t_ns", "domain", "service", "service_data", "context_id", "context_parent_id"}, raw=raw, name="HA service event")
    parent = _strict_keys(top["parent_state_event"], {"t_ns", "entity_id", "old_state", "new_state", "context_id", "context_parent_id"}, raw=raw, name="HA parent state event")
    data = _strict_keys(svc["service_data"], {"entity_id", "preset_mode"}, raw=raw, name="HA consequential service_data")

    try:
        service_ts = _ns("service_event.t_ns", svc["t_ns"])
        parent_ts = _ns("parent_state_event.t_ns", parent["t_ns"])
        domain = _token("service domain", svc["domain"])
        service = _token("service name", svc["service"])
        context_id = _token("service context_id", svc["context_id"])
        context_parent_id = _token("service context_parent_id", svc["context_parent_id"])
        parent_context_id = _token("parent state context_id", parent["context_id"])
        parent_entity = _token("parent state entity_id", parent["entity_id"])
        parent_old = _token("parent state old_state", parent["old_state"])
        parent_new = _token("parent state new_state", parent["new_state"])
        parent_parent = parent["context_parent_id"]
        if parent_parent is not None:
            parent_parent = _token("parent state context_parent_id", parent_parent)
        preset = _token("preset_mode", data["preset_mode"])
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message=str(exc), raw=raw)

    if (domain, service) != ("climate", "set_preset_mode"):
        _fail(code=RealizationFailureCode.UNKNOWN_SEMANTIC_VALUE, message="historical service is outside the frozen consequential action family", raw=raw, details=(("domain", domain), ("service", service)))
    targets = data["entity_id"]
    if not isinstance(targets, (list, tuple)):
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message="service_data.entity_id must be a finite sequence", raw=raw)
    if len(targets) == 0:
        _fail(code=RealizationFailureCode.MISSING_REQUIRED_FIELD, message="historical service has no resolved target entity", raw=raw)
    if len(targets) > 1:
        code = RealizationFailureCode.DUPLICATE_INPUT if len(set(map(str, targets))) < len(targets) else RealizationFailureCode.AMBIGUOUS_REALIZATION
        _fail(code=code, message="historical service must resolve to exactly one target entity", raw=raw, details=(("target_count", len(targets)),))
    target = _token("resolved target entity", targets[0])
    if target != HA_BT_FROZEN_TARGET_ENTITY:
        _fail(code=RealizationFailureCode.OUT_OF_BOUNDARY, message="historical service targets a foreign entity", raw=raw, details=(("entity_id", target),))
    if parent_entity not in {"input_boolean.agentmark_presence", "input_boolean.agentmark_night"}:
        _fail(code=RealizationFailureCode.OUT_OF_BOUNDARY, message="historical service parent is outside the frozen trigger entity set", raw=raw, details=(("parent_entity_id", parent_entity),))
    if parent_old not in {"on", "off"} or parent_new not in {"on", "off"} or parent_old == parent_new:
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message="parent state event is not a canonical binary state transition", raw=raw)
    if context_parent_id != parent_context_id:
        _fail(code=RealizationFailureCode.OUT_OF_BOUNDARY, message="historical service is bound to a foreign Home Assistant context", raw=raw, details=(("service_parent", context_parent_id), ("retained_parent", parent_context_id)))
    if parent_ts > service_ts:
        _fail(code=RealizationFailureCode.OUT_OF_BOUNDARY, message="parent state event occurs after historical service issue", raw=raw)

    record = HaBtHistoricalActionRecord(
        schema_version=HA_BT_RAW_ACTION_SCHEMA,
        capture_point=HA_BT_ACTION_CAPTURE_POINT,
        clock_domain=HA_BT_CLOCK_DOMAIN,
        service_timestamp_ns=service_ts,
        domain=domain,
        service=service,
        concrete_target=target,
        preset_mode=preset,
        context_id=context_id,
        context_parent_id=context_parent_id,
        parent_state_timestamp_ns=parent_ts,
        parent_state_entity_id=parent_entity,
        parent_state_old_state=parent_old,
        parent_state_new_state=parent_new,
        parent_state_context_id=parent_context_id,
        parent_state_context_parent_id=parent_parent,
    )
    if record.canonical_record() != raw:
        _fail(code=RealizationFailureCode.INTERNAL_INCONSISTENCY, message="parsed HA action does not round-trip to exact raw record", raw=raw)
    return record


def realize_ha_bt_historical_action(raw: object) -> RealizedHistoricalAction:
    record = parse_ha_bt_historical_action_record(raw)
    action = ProjectedAction.from_mapping(
        {
            "operation": f"{record.domain}.{record.service}",
            "target_class": record.concrete_target.split(".", 1)[0],
            "variant": record.variant(),
            "concrete_target": record.concrete_target,
            "service_domain": record.domain,
            "service_name": record.service,
            "preset_mode": record.preset_mode,
        }
    )
    provenance = historical_action_provenance(
        realizer_id=HA_BT_ACTION_REALIZER_ID,
        realizer_semantic_digest=HA_BT_ACTION_REALIZER_SEMANTIC_DIGEST,
        source_schema=HA_BT_RAW_ACTION_SCHEMA,
        raw_record_digest=record.fingerprint(),
    )
    return RealizedHistoricalAction(schema_version=_ACTION_SCHEMA, action=action, provenance=provenance)


def ha_bt_action_realizer_rule_record() -> dict[str, object]:
    return json.loads(_canonical_json_bytes(_RULE_RECORD).decode("utf-8"))


__all__ = (
    "HA_BT_RAW_ACTION_SCHEMA",
    "HA_BT_ACTION_CAPTURE_POINT",
    "HA_BT_ACTION_REALIZER_ID",
    "HA_BT_ACTION_REALIZER_SEMANTIC_DIGEST",
    "HA_BT_FROZEN_TARGET_ENTITY",
    "HaBtHistoricalActionRecord",
    "parse_ha_bt_historical_action_record",
    "realize_ha_bt_historical_action",
    "ha_bt_action_realizer_rule_record",
)
