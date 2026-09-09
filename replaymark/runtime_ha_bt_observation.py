from __future__ import annotations

"""Strict Home Assistant state snapshot -> ReplayMark evidence realization.

This module performs substrate realization only.  It does not know controller
rules, HOME/AWAY/COMFORT semantics, q(C,H), adjudication, R*, execution, or
fallback.  The evidence token is a lossless canonical identity of the frozen
controller state coordinates observed at the snapshot boundary.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, NoReturn, Sequence

from .contracts import Scalar
from .runtime_realization import (
    RealizationError,
    RealizationFailure,
    RealizationFailureCode,
    RealizationStage,
    RealizedObservation,
    observation_provenance,
    realized_observation,
)

HA_BT_RAW_OBSERVATION_SCHEMA = "replaymark.runtime.ha-bt-observation-record.v1"
HA_BT_OBSERVATION_CAPTURE_POINT = "homeassistant.states.snapshot"
HA_BT_OBSERVATION_REALIZER_ID = "replaymark.ha-bt-observation-realizer.v1"
HA_BT_CLOCK_DOMAIN = "python.perf_counter_ns"

_FAILURE_SCHEMA = "replaymark.runtime.realization-failure.v1"

_EXPECTED_ENTITIES = {
    "presence": "input_boolean.agentmark_presence",
    "motion": "binary_sensor.agentmark_motion",
    "night": "input_boolean.agentmark_night",
    "enable": "input_boolean.agentmark_enable",
    "climate": "climate.agentmark_thermostat",
}

_SNAPSHOT_FIELDS = {
    "label",
    "t_ns",
    "presence",
    "motion",
    "night",
    "enable",
    "climate_state",
    "climate_preset",
}

_RULE_RECORD = {
    "schema": "replaymark.realizer-semantics.ha-bt-observation.v1",
    "source_schema": HA_BT_RAW_OBSERVATION_SCHEMA,
    "capture_point": HA_BT_OBSERVATION_CAPTURE_POINT,
    "clock_domain": HA_BT_CLOCK_DOMAIN,
    "entity_binding": dict(_EXPECTED_ENTITIES),
    "state_coordinates": ["presence", "motion", "night", "climate_preset"],
    "scope_guards": {"enable": "on", "climate_state": "heat"},
    "token": "canonical JSON [presence_bool,motion_bool,night_bool,climate_preset]",
    "semantic_labels_from_caller": False,
    "controller_logic": False,
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


HA_BT_OBSERVATION_REALIZER_SEMANTIC_DIGEST = _sha256(_canonical_json_bytes(_RULE_RECORD))


def _best_effort_digest(raw: object) -> str | None:
    try:
        return _sha256(_canonical_json_bytes(raw))
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError):
        return None


def _fail(*, code: RealizationFailureCode, message: str, raw: object, details: Sequence[tuple[str, Scalar]] = ()) -> NoReturn:
    raise RealizationError(
        RealizationFailure(
            schema_version=_FAILURE_SCHEMA,
            stage=RealizationStage.OBSERVATION,
            code=code,
            realizer_id=HA_BT_OBSERVATION_REALIZER_ID,
            message=message,
            raw_record_digest=_best_effort_digest(raw),
            details=tuple(details),
        )
    )


def _canonical_token(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise TypeError(f"{name} must be a non-empty canonical string")
    value.encode("utf-8")
    return value


def _on_off(name: str, value: object, *, raw: object) -> bool:
    if value == "on":
        return True
    if value == "off":
        return False
    _fail(
        code=RealizationFailureCode.UNKNOWN_SEMANTIC_VALUE,
        message=f"{name} must be Home Assistant 'on' or 'off'",
        raw=raw,
        details=((name, str(value)),),
    )


@dataclass(frozen=True)
class HaBtObservationRecord:
    schema_version: str
    capture_point: str
    clock_domain: str
    entities: tuple[tuple[str, str], ...]
    label: str
    boundary_timestamp_ns: int
    presence: bool
    motion: bool
    night: bool
    enable: bool
    climate_state: str
    climate_preset: str

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "capture_point": self.capture_point,
            "clock_domain": self.clock_domain,
            "entities": dict(self.entities),
            "snapshot": {
                "label": self.label,
                "t_ns": self.boundary_timestamp_ns,
                "presence": "on" if self.presence else "off",
                "motion": "on" if self.motion else "off",
                "night": "on" if self.night else "off",
                "enable": "on" if self.enable else "off",
                "climate_state": self.climate_state,
                "climate_preset": self.climate_preset,
            },
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_record())

    def fingerprint(self) -> str:
        return _sha256(self.canonical_bytes())

    def evidence_token(self) -> str:
        return json.dumps(
            [self.presence, self.motion, self.night, self.climate_preset],
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


def parse_ha_bt_observation_record(raw: object) -> HaBtObservationRecord:
    if not isinstance(raw, Mapping):
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message="HA observation record must be a mapping", raw=raw)
    expected = {"schema", "capture_point", "clock_domain", "entities", "snapshot"}
    missing = sorted(expected - set(raw))
    unknown = sorted(set(raw) - expected, key=repr)
    if missing:
        _fail(code=RealizationFailureCode.MISSING_REQUIRED_FIELD, message="HA observation record is missing a required field", raw=raw, details=(("field", missing[0]),))
    if unknown:
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message="HA observation record contains an unknown field", raw=raw, details=(("field", repr(unknown[0])),))
    if raw["schema"] != HA_BT_RAW_OBSERVATION_SCHEMA:
        _fail(code=RealizationFailureCode.UNKNOWN_SEMANTIC_VALUE, message="foreign HA observation schema", raw=raw)
    if raw["capture_point"] != HA_BT_OBSERVATION_CAPTURE_POINT:
        _fail(code=RealizationFailureCode.UNKNOWN_SEMANTIC_VALUE, message="unsupported HA observation capture point", raw=raw)
    if raw["clock_domain"] != HA_BT_CLOCK_DOMAIN:
        _fail(code=RealizationFailureCode.CLOCK_DOMAIN_MISMATCH, message="HA observation uses a foreign clock domain", raw=raw)

    entities = raw["entities"]
    if not isinstance(entities, Mapping):
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message="entities must be a mapping", raw=raw)
    if set(entities) != set(_EXPECTED_ENTITIES):
        missing_entity = sorted(set(_EXPECTED_ENTITIES) - set(entities))
        extra_entity = sorted(set(entities) - set(_EXPECTED_ENTITIES), key=repr)
        code = RealizationFailureCode.MISSING_REQUIRED_FIELD if missing_entity else RealizationFailureCode.MALFORMED_INPUT
        field = missing_entity[0] if missing_entity else repr(extra_entity[0])
        _fail(code=code, message="HA observation entity-role set is not exact", raw=raw, details=(("entity_role", field),))
    for role, expected_id in _EXPECTED_ENTITIES.items():
        if entities[role] != expected_id:
            _fail(code=RealizationFailureCode.OUT_OF_BOUNDARY, message="HA observation is bound to a foreign entity", raw=raw, details=(("entity_role", role), ("entity_id", str(entities[role]))))

    snap = raw["snapshot"]
    if not isinstance(snap, Mapping):
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message="snapshot must be a mapping", raw=raw)
    missing = sorted(_SNAPSHOT_FIELDS - set(snap))
    unknown = sorted(set(snap) - _SNAPSHOT_FIELDS, key=repr)
    if missing:
        _fail(code=RealizationFailureCode.MISSING_REQUIRED_FIELD, message="HA snapshot is missing a required field", raw=raw, details=(("field", missing[0]),))
    if unknown:
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message="HA snapshot contains an unknown field", raw=raw, details=(("field", repr(unknown[0])),))

    try:
        label = _canonical_token("snapshot label", snap["label"])
        ts = snap["t_ns"]
        if isinstance(ts, bool) or not isinstance(ts, int) or ts < 0:
            raise TypeError("t_ns must be a non-negative integer")
        climate_state = _canonical_token("climate_state", snap["climate_state"])
        climate_preset = _canonical_token("climate_preset", snap["climate_preset"])
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        _fail(code=RealizationFailureCode.MALFORMED_INPUT, message=str(exc), raw=raw)

    presence = _on_off("presence", snap["presence"], raw=raw)
    motion = _on_off("motion", snap["motion"], raw=raw)
    night = _on_off("night", snap["night"], raw=raw)
    enable = _on_off("enable", snap["enable"], raw=raw)
    if not enable:
        _fail(code=RealizationFailureCode.OUT_OF_BOUNDARY, message="frozen HA controller is disabled", raw=raw)
    if climate_state != "heat":
        _fail(code=RealizationFailureCode.OUT_OF_BOUNDARY, message="frozen thermostat is outside the qualified heat-mode scope", raw=raw, details=(("climate_state", climate_state),))

    return HaBtObservationRecord(
        schema_version=HA_BT_RAW_OBSERVATION_SCHEMA,
        capture_point=HA_BT_OBSERVATION_CAPTURE_POINT,
        clock_domain=HA_BT_CLOCK_DOMAIN,
        entities=tuple(sorted((str(k), str(v)) for k, v in entities.items())),
        label=label,
        boundary_timestamp_ns=ts,
        presence=presence,
        motion=motion,
        night=night,
        enable=enable,
        climate_state=climate_state,
        climate_preset=climate_preset,
    )


def realize_ha_bt_observation(raw: object) -> RealizedObservation:
    record = parse_ha_bt_observation_record(raw)
    provenance = observation_provenance(
        realizer_id=HA_BT_OBSERVATION_REALIZER_ID,
        realizer_semantic_digest=HA_BT_OBSERVATION_REALIZER_SEMANTIC_DIGEST,
        source_schema=HA_BT_RAW_OBSERVATION_SCHEMA,
        raw_record_digest=record.fingerprint(),
    )
    return realized_observation(
        evidence_token=record.evidence_token(),
        clock_domain=record.clock_domain,
        boundary_timestamp_ns=record.boundary_timestamp_ns,
        source_event_timestamp_ns=None,
        provenance=provenance,
    )


def ha_bt_observation_realizer_rule_record() -> dict[str, object]:
    return json.loads(_canonical_json_bytes(_RULE_RECORD).decode("utf-8"))


__all__ = (
    "HA_BT_RAW_OBSERVATION_SCHEMA",
    "HA_BT_OBSERVATION_CAPTURE_POINT",
    "HA_BT_OBSERVATION_REALIZER_ID",
    "HA_BT_OBSERVATION_REALIZER_SEMANTIC_DIGEST",
    "HaBtObservationRecord",
    "parse_ha_bt_observation_record",
    "realize_ha_bt_observation",
    "ha_bt_observation_realizer_rule_record",
)
