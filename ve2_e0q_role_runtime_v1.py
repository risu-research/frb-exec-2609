from __future__ import annotations

"""VE2-E0Q per-role runtime driver.

Runs inside one exact Home Assistant OCI substrate. It resolves the exact
Better Thermostat custom-component identity from /config, then exercises only
the shared VE2 boundary microkernel using the synthetic ve2_e0q.sink service.
No T01/T02 blueprint, state manifest, expected frontier, historical action, or
climate/Better-Thermostat service is executed.
"""

import argparse
import asyncio
import copy
import hashlib
import importlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import sys
from typing import Any

from homeassistant import loader
from homeassistant.core import Context, HomeAssistant

import ve2_boundary_microkernel_v1 as boundary

DOMAIN = "ve2_e0q"
SERVICE = "sink"
TRIGGER_ENTITY = "sensor.ve2_e0q_trigger"
SCHEMA = "replaymark.ve2.e0q-role-result.v1"
SOURCE_IDENTITY_PATH = Path("/config/VE2_SOURCE_IDENTITY.json")
COMPONENT_DIR = Path("/config/custom_components/better_thermostat")


def canonical_component_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for path in files:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        body = path.read_bytes()
        digest.update(len(rel).to_bytes(8, "big"))
        digest.update(rel)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def home_assistant_version() -> str:
    try:
        return importlib.metadata.version("homeassistant")
    except Exception:
        import homeassistant.const as ha_const
        value = getattr(ha_const, "__version__", None)
        return "UNKNOWN" if value is None else str(value)


def construct_hass() -> tuple[HomeAssistant, str, dict[str, str]]:
    signature = inspect.signature(HomeAssistant.__init__)
    config = signature.parameters.get("config_dir")
    required = bool(
        config is not None
        and config.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and config.default is inspect.Parameter.empty
    )
    if required:
        hass = HomeAssistant("/config")
        strategy = "REQUIRED_CONFIG_DIR_POSITIONAL"
    else:
        hass = HomeAssistant()
        hass.config.config_dir = "/config"
        strategy = "NOARG_THEN_SET_CONFIG_DIR"
    summary = {
        name: str(param)
        for name, param in signature.parameters.items()
        if name != "self"
    }
    return hass, strategy, summary


def load_source_identity(args: argparse.Namespace) -> dict[str, Any]:
    value = json.loads(SOURCE_IDENTITY_PATH.read_text(encoding="utf-8"))
    expected = {
        "role": args.role,
        "source_commit": args.source_commit,
        "component_tree_sha1": args.component_tree_sha1,
        "manifest_sha256": args.manifest_sha256,
        "manifest_version": args.manifest_version,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise AssertionError(("source-identity", key, value.get(key), expected_value))
    if value.get("component_canonical_sha256") != canonical_component_sha256(COMPONENT_DIR):
        raise AssertionError("component-canonical-sha256")
    manifest_path = COMPONENT_DIR / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != args.manifest_sha256:
        raise AssertionError("manifest-sha256")
    manifest = json.loads(manifest_bytes)
    if manifest.get("domain") != "better_thermostat":
        raise AssertionError(("manifest-domain", manifest.get("domain")))
    if manifest.get("version") != args.manifest_version:
        raise AssertionError(("manifest-version", manifest.get("version")))
    return value


async def verify_loader(hass: HomeAssistant, args: argparse.Namespace) -> dict[str, Any]:
    sys.path.insert(0, "/config")
    importlib.invalidate_caches()
    loader.async_setup(hass)
    integration = await loader.async_get_integration(hass, "better_thermostat")
    manifest = dict(getattr(integration, "manifest", {}) or {})
    if manifest.get("domain") != "better_thermostat":
        raise AssertionError(("loader-domain", manifest.get("domain")))
    if manifest.get("version") != args.manifest_version:
        raise AssertionError(("loader-version", manifest.get("version"), args.manifest_version))
    module = importlib.import_module("custom_components.better_thermostat")
    module_file = Path(str(module.__file__)).resolve()
    root = COMPONENT_DIR.resolve()
    if module_file != root / "__init__.py":
        raise AssertionError(("loader-module-origin", str(module_file), str(root)))
    manifest_file = root / "manifest.json"
    if not manifest_file.is_file():
        raise AssertionError("loader-manifest-not-at-real-config-path")
    return {
        "status": "PASS",
        "loader_domain": manifest.get("domain"),
        "loader_version": manifest.get("version"),
        "module_file": str(module_file),
        "manifest_file": str(manifest_file),
        "real_config_path_verified": True,
    }


def _expect_rejection(label: str, fn) -> dict[str, Any]:
    try:
        fn()
    except Exception as exc:
        return {
            "label": label,
            "status": "PASS",
            "rejected": True,
            "exception_type": type(exc).__name__,
        }
    raise AssertionError(label + ": malformed evidence unexpectedly accepted")


async def run_boundary(hass: HomeAssistant) -> dict[str, Any]:
    sink_calls: list[dict[str, Any]] = []

    async def sink_handler(call: Any) -> None:
        sink_calls.append(
            {
                "context_id": str(call.context.id),
                "context_parent_id": None if call.context.parent_id is None else str(call.context.parent_id),
                "data": dict(call.data),
            }
        )

    hass.services.async_register(DOMAIN, SERVICE, sink_handler)
    hass.states.async_set(TRIGGER_ENTITY, "idle")
    await hass.async_block_till_done()

    observer = boundary.BoundaryObserver(hass)
    observer.install()
    try:
        positive_state_start = len(observer.state_events)
        positive_service_start = len(observer.service_events)
        positive_context = Context()
        positive_context_id = str(positive_context.id)
        hass.states.async_set(TRIGGER_ENTITY, "positive", context=positive_context)
        await hass.services.async_call(
            DOMAIN,
            SERVICE,
            {"token": "positive"},
            blocking=True,
            context=positive_context,
        )
        positive_completion = await boundary.completion_boundary(hass)
        positive_parent = boundary.select_parent_state_event(
            observer.state_events,
            start_index=positive_state_start,
            entity_id=TRIGGER_ENTITY,
            old_state="idle",
            new_state="positive",
            invocation_context_id=positive_context_id,
        )
        positive_events = boundary.qualifying_service_events(
            observer.service_events,
            start_index=positive_service_start,
            domain=DOMAIN,
            service=SERVICE,
            invocation_context_id=positive_context_id,
        )
        positive_events = boundary.require_exact_cardinality(positive_events, 1)
        positive_event = positive_events[0]
        boundary.validate_service_event(
            positive_event,
            allowed_service_data_keys={"token"},
            required_service_data_keys={"token"},
        )
        if positive_event["service_data"] != {"token": "positive"}:
            raise AssertionError(("positive-service-data", positive_event["service_data"]))
        boundary.require_event_within_boundary(
            positive_parent,
            positive_event,
            positive_completion,
        )

        absence_state_start = len(observer.state_events)
        absence_service_start = len(observer.service_events)
        absence_context = Context()
        absence_context_id = str(absence_context.id)
        hass.states.async_set(TRIGGER_ENTITY, "absence", context=absence_context)
        absence_completion = await boundary.completion_boundary(hass)
        absence_parent = boundary.select_parent_state_event(
            observer.state_events,
            start_index=absence_state_start,
            entity_id=TRIGGER_ENTITY,
            old_state="positive",
            new_state="absence",
            invocation_context_id=absence_context_id,
        )
        absence_events = boundary.qualifying_service_events(
            observer.service_events,
            start_index=absence_service_start,
            domain=DOMAIN,
            service=SERVICE,
            invocation_context_id=absence_context_id,
        )
        boundary.require_exact_cardinality(absence_events, 0)
        boundary.require_event_within_boundary(
            absence_parent,
            None,
            absence_completion,
        )

        foreign = copy.deepcopy(positive_event)
        foreign["context_id"] = "foreign-context"
        foreign["context_parent_id"] = "foreign-parent"
        malformed = copy.deepcopy(positive_event)
        malformed["unexpected_top_level"] = True
        incomplete = copy.deepcopy(positive_completion)
        incomplete["passes"] = incomplete["passes"][:2]

        negatives = [
            _expect_rejection(
                "foreign-context",
                lambda: boundary.require_exact_cardinality(
                    [foreign] if boundary.context_bound(foreign, positive_context_id) else [],
                    1,
                ),
            ),
            _expect_rejection(
                "duplicate-event",
                lambda: boundary.require_exact_cardinality(
                    [copy.deepcopy(positive_event), copy.deepcopy(positive_event)],
                    1,
                ),
            ),
            _expect_rejection(
                "malformed-event",
                lambda: boundary.validate_service_event(malformed),
            ),
            _expect_rejection(
                "incomplete-completion",
                lambda: boundary.validate_completion(incomplete),
            ),
        ]

        if len(sink_calls) != 1:
            raise AssertionError(("sink-handler-cardinality", len(sink_calls)))
        if sink_calls[0]["context_id"] != positive_context_id:
            raise AssertionError("sink-handler-context")

        return {
            "status": "PASS",
            "positive": {
                "invocation_context_id": positive_context_id,
                "parent_state_event": positive_parent,
                "completion_boundary": positive_completion,
                "qualifying_service_events": positive_events,
                "observed_event_count": 1,
            },
            "verified_absence": {
                "invocation_context_id": absence_context_id,
                "parent_state_event": absence_parent,
                "completion_boundary": absence_completion,
                "qualifying_service_events": absence_events,
                "observed_event_count": 0,
            },
            "negative_cases": negatives,
            "sink_handler_calls": sink_calls,
        }
    finally:
        observer.close()


async def experiment(args: argparse.Namespace) -> dict[str, Any]:
    identity = load_source_identity(args)
    observed_ha = home_assistant_version()
    if observed_ha != args.expected_ha_version:
        raise AssertionError(("ha-version", observed_ha, args.expected_ha_version))
    hass, constructor_strategy, constructor_signature = construct_hass()
    loader_result = await verify_loader(hass, args)
    boundary_result = await run_boundary(hass)
    return {
        "schema": SCHEMA,
        "status": "PASS",
        "role": args.role,
        "expected_ha_version": args.expected_ha_version,
        "observed_ha_version": observed_ha,
        "exact_ha_image": args.ha_image,
        "source_commit": args.source_commit,
        "component_tree_sha1": args.component_tree_sha1,
        "component_canonical_sha256": identity["component_canonical_sha256"],
        "manifest_sha256": args.manifest_sha256,
        "manifest_version": args.manifest_version,
        "boundary_git_blob": args.boundary_blob,
        "constructor_strategy": constructor_strategy,
        "constructor_signature": constructor_signature,
        "loader": loader_result,
        "boundary": boundary_result,
        "scientific_result_opened": False,
        "frontier_result_seen": False,
        "transition_blueprint_mounted": False,
        "execution_state_manifest_mounted": False,
        "expected_frontier_mounted": False,
        "historical_action_dispatched": False,
        "climate_or_better_thermostat_action_invoked": False,
        "synthetic_service_domain": DOMAIN,
        "synthetic_service": SERVICE,
        "same_boundary_blob_required_for_future_science": True,
    }


async def _run(args: argparse.Namespace) -> int:
    try:
        result = await experiment(args)
    except Exception as exc:
        result = {
            "schema": SCHEMA,
            "status": "FAIL",
            "role": args.role,
            "boundary_git_blob": args.boundary_blob,
            "scientific_result_opened": False,
            "frontier_result_seen": False,
            "transition_blueprint_mounted": False,
            "execution_state_manifest_mounted": False,
            "expected_frontier_mounted": False,
            "historical_action_dispatched": False,
            "climate_or_better_thermostat_action_invoked": False,
            "failure_type": type(exc).__name__,
            "failure": str(exc),
        }
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(json.dumps(
        {
            "schema": "replaymark.ve2.e0q-role-close.v1",
            "role": args.role,
            "status": result["status"],
            "scientific_cells": 0,
            "result_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        },
        sort_keys=True,
    ))
    return 0 if result["status"] == "PASS" else 4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--expected-ha-version", required=True)
    parser.add_argument("--ha-image", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--component-tree-sha1", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--manifest-version", required=True)
    parser.add_argument("--boundary-blob", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
