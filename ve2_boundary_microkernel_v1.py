from __future__ import annotations

"""VE2 version-spanning Home Assistant boundary microkernel.

This module contains only result-agnostic observation, context-binding,
completion, cardinality, and structural-validation primitives.  It does not
encode T01/T02 state, frontier labels, Better Thermostat actions, or expected
scientific outcomes.  The exact Git blob of this file is frozen by VE2-E0Q and
must be reused by later VE2 scientific execution.
"""

import copy
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from homeassistant.const import EVENT_CALL_SERVICE, EVENT_STATE_CHANGED

CLOCK_DOMAIN = "python.perf_counter_ns"
COMPLETION_WITNESS = "three_homeassistant_async_block_till_done_fixed_point_passes"
SERVICE_EVENT_SCHEMA = "replaymark.ve2.boundary-service-event.v1"
STATE_EVENT_SCHEMA = "replaymark.ve2.boundary-state-event.v1"
COMPLETION_SCHEMA = "replaymark.ve2.completed-boundary.v1"


def _context_id(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _json_scalar_or_tree(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_scalar_or_tree(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_scalar_or_tree(v) for v in value]
    if isinstance(value, set):
        return [_json_scalar_or_tree(v) for v in sorted(value, key=repr)]
    return {"__type__": type(value).__name__, "__repr__": repr(value)}


def _state_name(state: Any) -> str | None:
    return None if state is None else str(getattr(state, "state", None))


@dataclass
class BoundaryObserver:
    hass: Any

    def __post_init__(self) -> None:
        self.state_events: list[dict[str, Any]] = []
        self.service_events: list[dict[str, Any]] = []
        self._unsubs: list[Callable[[], None]] = []

    def install(self) -> None:
        if self._unsubs:
            raise RuntimeError("boundary observer already installed")

        def on_state(event: Any) -> None:
            data = event.data
            context = event.context
            self.state_events.append(
                {
                    "schema": STATE_EVENT_SCHEMA,
                    "clock_domain": CLOCK_DOMAIN,
                    "t_ns": time.perf_counter_ns(),
                    "entity_id": str(data.get("entity_id")),
                    "old_state": _state_name(data.get("old_state")),
                    "new_state": _state_name(data.get("new_state")),
                    "context_id": _context_id(getattr(context, "id", None)),
                    "context_parent_id": _context_id(getattr(context, "parent_id", None)),
                }
            )

        def on_service(event: Any) -> None:
            data = event.data
            context = event.context
            self.service_events.append(
                {
                    "schema": SERVICE_EVENT_SCHEMA,
                    "clock_domain": CLOCK_DOMAIN,
                    "t_ns": time.perf_counter_ns(),
                    "domain": str(data.get("domain")),
                    "service": str(data.get("service")),
                    "service_data": _json_scalar_or_tree(data.get("service_data") or {}),
                    "context_id": _context_id(getattr(context, "id", None)),
                    "context_parent_id": _context_id(getattr(context, "parent_id", None)),
                }
            )

        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, on_state))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_CALL_SERVICE, on_service))

    def close(self) -> None:
        while self._unsubs:
            unsub = self._unsubs.pop()
            unsub()


async def completion_boundary(hass: Any) -> dict[str, Any]:
    started_ns = time.perf_counter_ns()
    passes: list[dict[str, int]] = []
    for index in range(3):
        before_ns = time.perf_counter_ns()
        await hass.async_block_till_done()
        after_ns = time.perf_counter_ns()
        passes.append({"pass": index, "before_ns": before_ns, "after_ns": after_ns})
    closed_ns = time.perf_counter_ns()
    value = {
        "schema": COMPLETION_SCHEMA,
        "witness": COMPLETION_WITNESS,
        "clock_domain": CLOCK_DOMAIN,
        "started_ns": started_ns,
        "closed_ns": closed_ns,
        "passes": passes,
    }
    validate_completion(value)
    return value


def validate_completion(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {"schema", "witness", "clock_domain", "started_ns", "closed_ns", "passes"}:
        raise ValueError("completion-field-set")
    if value["schema"] != COMPLETION_SCHEMA:
        raise ValueError("completion-schema")
    if value["witness"] != COMPLETION_WITNESS:
        raise ValueError("completion-witness")
    if value["clock_domain"] != CLOCK_DOMAIN:
        raise ValueError("completion-clock-domain")
    passes = value["passes"]
    if not isinstance(passes, list) or len(passes) != 3:
        raise ValueError("completion-pass-count")
    cursor = int(value["started_ns"])
    for index, item in enumerate(passes):
        if set(item) != {"pass", "before_ns", "after_ns"} or item["pass"] != index:
            raise ValueError("completion-pass-shape")
        before_ns = int(item["before_ns"])
        after_ns = int(item["after_ns"])
        if before_ns < cursor or after_ns < before_ns:
            raise ValueError("completion-nonmonotonic-pass")
        cursor = after_ns
    if int(value["closed_ns"]) < cursor:
        raise ValueError("completion-close-before-pass")
    return value


def validate_state_event(value: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "schema", "clock_domain", "t_ns", "entity_id", "old_state", "new_state",
        "context_id", "context_parent_id",
    }
    if set(value) != expected:
        raise ValueError("state-event-field-set")
    if value["schema"] != STATE_EVENT_SCHEMA or value["clock_domain"] != CLOCK_DOMAIN:
        raise ValueError("state-event-schema-or-clock")
    if not isinstance(value["entity_id"], str) or not value["entity_id"]:
        raise ValueError("state-event-entity")
    if not isinstance(value["t_ns"], int):
        raise ValueError("state-event-time")
    return value


def validate_service_event(
    value: dict[str, Any],
    *,
    allowed_service_data_keys: set[str] | None = None,
    required_service_data_keys: set[str] | None = None,
) -> dict[str, Any]:
    expected = {
        "schema", "clock_domain", "t_ns", "domain", "service", "service_data",
        "context_id", "context_parent_id",
    }
    if set(value) != expected:
        raise ValueError("service-event-field-set")
    if value["schema"] != SERVICE_EVENT_SCHEMA or value["clock_domain"] != CLOCK_DOMAIN:
        raise ValueError("service-event-schema-or-clock")
    if not isinstance(value["t_ns"], int):
        raise ValueError("service-event-time")
    if not isinstance(value["domain"], str) or not value["domain"]:
        raise ValueError("service-event-domain")
    if not isinstance(value["service"], str) or not value["service"]:
        raise ValueError("service-event-service")
    data = value["service_data"]
    if not isinstance(data, dict):
        raise ValueError("service-event-data")
    keys = set(data)
    if allowed_service_data_keys is not None and not keys <= allowed_service_data_keys:
        raise ValueError("service-event-unexpected-data-key")
    if required_service_data_keys is not None and not required_service_data_keys <= keys:
        raise ValueError("service-event-missing-data-key")
    return value


def context_bound(value: dict[str, Any], invocation_context_id: str) -> bool:
    validate_service_event(value)
    return (
        value["context_id"] == invocation_context_id
        or value["context_parent_id"] == invocation_context_id
    )


def select_parent_state_event(
    events: list[dict[str, Any]],
    *,
    start_index: int,
    entity_id: str,
    old_state: str,
    new_state: str,
    invocation_context_id: str,
) -> dict[str, Any]:
    matches = []
    for event in events[start_index:]:
        validate_state_event(event)
        if (
            event["entity_id"] == entity_id
            and event["old_state"] == old_state
            and event["new_state"] == new_state
            and event["context_id"] == invocation_context_id
        ):
            matches.append(event)
    if len(matches) != 1:
        raise ValueError(f"parent-state-cardinality:{len(matches)}")
    return copy.deepcopy(matches[0])


def qualifying_service_events(
    events: list[dict[str, Any]],
    *,
    start_index: int,
    domain: str,
    service: str,
    invocation_context_id: str,
) -> list[dict[str, Any]]:
    out = []
    for event in events[start_index:]:
        validate_service_event(event)
        if (
            event["domain"] == domain
            and event["service"] == service
            and context_bound(event, invocation_context_id)
        ):
            out.append(copy.deepcopy(event))
    return out


def require_exact_cardinality(values: Iterable[Any], expected: int) -> list[Any]:
    materialized = list(values)
    if len(materialized) != expected:
        raise ValueError(f"cardinality:{len(materialized)}:{expected}")
    return materialized


def require_event_within_boundary(
    parent: dict[str, Any],
    event: dict[str, Any] | None,
    completion: dict[str, Any],
) -> None:
    validate_state_event(parent)
    validate_completion(completion)
    if int(completion["started_ns"]) > int(completion["closed_ns"]):
        raise ValueError("invalid-completion-window")
    if int(parent["t_ns"]) > int(completion["closed_ns"]):
        raise ValueError("parent-after-completion")
    if event is not None:
        validate_service_event(event)
        if int(event["t_ns"]) < int(parent["t_ns"]):
            raise ValueError("service-before-parent")
        if int(event["t_ns"]) > int(completion["closed_ns"]):
            raise ValueError("service-after-completion")
