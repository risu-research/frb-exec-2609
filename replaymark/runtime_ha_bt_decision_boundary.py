from __future__ import annotations

"""Mechanical reconstruction of a pre-service HA-BT observation boundary.

The transformation applies exactly one retained Home Assistant binary state event
to an already-C1-qualified snapshot. It contains no Better Thermostat controller
law and does not inspect the service action produced after that event.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .runtime_ha_bt_observation import (
    HA_BT_CLOCK_DOMAIN,
    HaBtObservationRecord,
    parse_ha_bt_observation_record,
)

SCHEMA = "replaymark.runtime.ha-bt-decision-boundary.v1"
BUILDER_ID = "replaymark.ha-bt-pre-service-boundary.v1"
_ALLOWED_TRIGGER_ENTITIES = {
    "input_boolean.agentmark_presence": "presence",
    "input_boolean.agentmark_night": "night",
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_event(raw: object) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("parent_state_event must be a mapping")
    expected = {"t_ns", "entity_id", "old_state", "new_state", "context_id", "context_parent_id"}
    if set(raw) != expected:
        raise ValueError("parent_state_event field set is not exact")
    if isinstance(raw["t_ns"], bool) or not isinstance(raw["t_ns"], int) or raw["t_ns"] < 0:
        raise ValueError("parent_state_event.t_ns must be a non-negative integer")
    for name in ("entity_id", "old_state", "new_state", "context_id"):
        if not isinstance(raw[name], str) or not raw[name] or raw[name] != raw[name].strip():
            raise ValueError(f"parent_state_event.{name} must be canonical")
    if raw["context_parent_id"] is not None and (
        not isinstance(raw["context_parent_id"], str)
        or not raw["context_parent_id"]
        or raw["context_parent_id"] != raw["context_parent_id"].strip()
    ):
        raise ValueError("parent_state_event.context_parent_id must be canonical or null")
    if raw["entity_id"] not in _ALLOWED_TRIGGER_ENTITIES:
        raise ValueError("parent_state_event entity is outside the frozen trigger set")
    if raw["old_state"] not in {"on", "off"} or raw["new_state"] not in {"on", "off"}:
        raise ValueError("parent_state_event is not binary")
    if raw["old_state"] == raw["new_state"]:
        raise ValueError("parent_state_event does not change state")
    return raw


@dataclass(frozen=True)
class HaBtDecisionBoundary:
    schema_version: str
    builder_id: str
    base_observation_fingerprint: str
    parent_event_fingerprint: str
    trigger_context_id: str
    reconstructed_raw_observation: dict[str, object]

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "builder_id": self.builder_id,
            "base_observation_fingerprint": self.base_observation_fingerprint,
            "parent_event_fingerprint": self.parent_event_fingerprint,
            "trigger_context_id": self.trigger_context_id,
            "reconstructed_raw_observation": self.reconstructed_raw_observation,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_record())

    def fingerprint(self) -> str:
        return _sha(self.canonical_bytes())


def reconstruct_ha_bt_pre_service_boundary(
    base_raw_observation: object,
    parent_state_event: object,
) -> HaBtDecisionBoundary:
    base: HaBtObservationRecord = parse_ha_bt_observation_record(base_raw_observation)
    event = _strict_event(parent_state_event)
    if base.clock_domain != HA_BT_CLOCK_DOMAIN:
        raise ValueError("base observation is outside the frozen clock domain")
    if event["t_ns"] < base.boundary_timestamp_ns:
        raise ValueError("trigger event precedes the retained base observation")

    role = _ALLOWED_TRIGGER_ENTITIES[str(event["entity_id"])]
    base_record = base.canonical_record()
    snapshot = dict(base_record["snapshot"])
    if snapshot[role] != event["old_state"]:
        raise ValueError("trigger old_state disagrees with retained base observation")
    snapshot[role] = event["new_state"]
    snapshot["t_ns"] = event["t_ns"]
    snapshot["label"] = f"c2_pre_service_{role}"
    reconstructed = {
        "schema": base_record["schema"],
        "capture_point": base_record["capture_point"],
        "clock_domain": base_record["clock_domain"],
        "entities": dict(base_record["entities"]),
        "snapshot": snapshot,
    }
    parsed = parse_ha_bt_observation_record(reconstructed)
    if parsed.canonical_record() != reconstructed:
        raise AssertionError("reconstructed boundary is not C1-canonical")
    return HaBtDecisionBoundary(
        schema_version=SCHEMA,
        builder_id=BUILDER_ID,
        base_observation_fingerprint=base.fingerprint(),
        parent_event_fingerprint=_sha(_canonical_json_bytes(dict(event))),
        trigger_context_id=str(event["context_id"]),
        reconstructed_raw_observation=reconstructed,
    )


__all__ = (
    "BUILDER_ID",
    "HaBtDecisionBoundary",
    "reconstruct_ha_bt_pre_service_boundary",
)
