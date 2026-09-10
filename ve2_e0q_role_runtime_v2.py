from __future__ import annotations

"""VE2-E0Q per-role runtime driver v2.

Prospective repair of E0Q-v1 harness-only failures.  The driver resolves the
exact Better Thermostat source from /config and exercises only the shared v2
boundary microkernel with synthetic ve2_e0q.sink.  No result-bearing blueprint,
state manifest, frontier label, historical action, or climate/BT action is used.
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

import ve2_boundary_microkernel_v2 as boundary

DOMAIN = "ve2_e0q"
SERVICE = "sink"
TRIGGER_ENTITY = "sensor.ve2_e0q_trigger"
SCHEMA = "replaymark.ve2.e0q-role-result.v2"
SOURCE_IDENTITY_PATH = Path("/config/VE2_SOURCE_IDENTITY.json")
COMPONENT_DIR = Path("/config/custom_components/better_thermostat")


def canonical_component_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        body = path.read_bytes()
        digest.update(len(rel).to_bytes(8, "big")); digest.update(rel)
        digest.update(len(body).to_bytes(8, "big")); digest.update(body)
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
    return hass, strategy, {
        name: str(param) for name, param in signature.parameters.items() if name != "self"
    }


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
    observed_component = canonical_component_sha256(COMPONENT_DIR)
    if value.get("component_canonical_sha256") != observed_component:
        raise AssertionError("component-canonical-sha256")
    manifest_bytes = (COMPONENT_DIR / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != args.manifest_sha256:
        raise AssertionError("manifest-sha256")
    manifest = json.loads(manifest_bytes)
    if manifest.get("domain") != "better_thermostat" or manifest.get("version") != args.manifest_version:
        raise AssertionError(("manifest-identity", manifest.get("domain"), manifest.get("version")))
    return value


def prepare_loader(hass: HomeAssistant) -> dict[str, Any]:
    """Prospectively frozen API-surface adapter; never retries after a failure."""
    key = loader.DATA_INTEGRATIONS
    cache_present_before = key in hass.data
    setup = getattr(loader, "async_setup", None)
    setup_api_present = callable(setup)
    if not cache_present_before and setup_api_present:
        setup(hass)
        strategy = "EXPLICIT_ASYNC_SETUP_API_PRESENT"
    elif not cache_present_before:
        strategy = "LEGACY_NATIVE_LAZY_ASYNC_GET_INTEGRATION"
    else:
        strategy = "ALREADY_INITIALIZED_BY_CONSTRUCTOR"
    return {
        "strategy": strategy,
        "data_integrations_present_before": cache_present_before,
        "loader_async_setup_api_present": setup_api_present,
        "data_integrations_present_after_adapter": key in hass.data,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }


async def verify_loader(hass: HomeAssistant, args: argparse.Namespace) -> dict[str, Any]:
    sys.path.insert(0, "/config")
    importlib.invalidate_caches()
    adapter = prepare_loader(hass)
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
    if not (root / "manifest.json").is_file():
        raise AssertionError("loader-manifest-not-at-real-config-path")
    return {
        "status": "PASS",
        "adapter": adapter,
        "loader_domain": manifest.get("domain"),
        "loader_version": manifest.get("version"),
        "module_file": str(module_file),
        "manifest_file": str(root / "manifest.json"),
        "real_config_path_verified": True,
    }


def _expect_rejection(label: str, fn) -> dict[str, Any]:
    try:
        fn()
    except Exception as exc:
        return {"label": label, "status": "PASS", "rejected": True, "exception_type": type(exc).__name__}
    raise AssertionError(label + ": malformed evidence unexpectedly accepted")


async def run_boundary(hass: HomeAssistant, diagnostic: dict[str, Any]) -> dict[str, Any]:
    sink_calls: list[dict[str, Any]] = []

    async def sink_handler(call: Any) -> None:
        sink_calls.append({
            "context_id": str(call.context.id),
            "context_parent_id": None if call.context.parent_id is None else str(call.context.parent_id),
            "data": dict(call.data),
        })

    hass.services.async_register(DOMAIN, SERVICE, sink_handler)
    hass.states.async_set(TRIGGER_ENTITY, "idle")
    await hass.async_block_till_done()

    observer = boundary.BoundaryObserver(hass)
    observer.install()
    try:
        diagnostic["phase"] = "positive_capture"
        positive_epoch = observer.arm_epoch()
        positive_context = Context()
        positive_context_id = str(positive_context.id)
        hass.states.async_set(TRIGGER_ENTITY, "positive", context=positive_context)
        await hass.services.async_call(DOMAIN, SERVICE, {"token": "positive"}, blocking=True, context=positive_context)
        positive_completion = await boundary.completion_boundary(hass)
        positive_parent = boundary.select_parent_state_event(
            observer.state_events,
            epoch=positive_epoch,
            entity_id=TRIGGER_ENTITY,
            old_state="idle",
            new_state="positive",
            invocation_context_id=positive_context_id,
        )
        positive_events = boundary.require_exact_cardinality(
            boundary.qualifying_service_events(
                observer.service_events,
                epoch=positive_epoch,
                domain=DOMAIN,
                service=SERVICE,
                invocation_context_id=positive_context_id,
            ),
            1,
        )
        positive_event = positive_events[0]
        boundary.validate_service_event(
            positive_event,
            allowed_service_data_keys={"token"},
            required_service_data_keys={"token"},
        )
        if positive_event["service_data"] != {"token": "positive"}:
            raise AssertionError(("positive-service-data", positive_event["service_data"]))
        boundary.require_positive_boundary(positive_epoch, positive_parent, positive_event, positive_completion)
        diagnostic["positive_capture"] = {
            "epoch": positive_epoch,
            "parent": positive_parent,
            "event": positive_event,
            "completion": positive_completion,
        }

        diagnostic["phase"] = "absence_capture"
        absence_epoch = observer.arm_epoch()
        absence_context = Context()
        absence_context_id = str(absence_context.id)
        hass.states.async_set(TRIGGER_ENTITY, "absence", context=absence_context)
        absence_completion = await boundary.completion_boundary(hass)
        absence_parent = boundary.select_parent_state_event(
            observer.state_events,
            epoch=absence_epoch,
            entity_id=TRIGGER_ENTITY,
            old_state="positive",
            new_state="absence",
            invocation_context_id=absence_context_id,
        )
        absence_events = boundary.qualifying_service_events(
            observer.service_events,
            epoch=absence_epoch,
            domain=DOMAIN,
            service=SERVICE,
            invocation_context_id=absence_context_id,
        )
        boundary.require_absence_boundary(absence_epoch, absence_parent, absence_events, absence_completion)
        diagnostic["absence_capture"] = {
            "epoch": absence_epoch,
            "parent": absence_parent,
            "events": absence_events,
            "completion": absence_completion,
        }

        diagnostic["phase"] = "negative_validation"
        foreign = copy.deepcopy(positive_event)
        foreign["context_id"] = "foreign-context"
        foreign["context_parent_id"] = "foreign-parent"
        malformed = copy.deepcopy(positive_event)
        malformed["unexpected_top_level"] = True
        incomplete = copy.deepcopy(positive_completion)
        incomplete["passes"] = incomplete["passes"][:2]
        sequence_regression = copy.deepcopy(positive_event)
        sequence_regression["sequence"] = positive_parent["sequence"]
        negatives = [
            _expect_rejection(
                "foreign-context",
                lambda: boundary.require_exact_cardinality(
                    [foreign] if boundary.context_bound(foreign, positive_context_id) else [], 1
                ),
            ),
            _expect_rejection(
                "duplicate-event",
                lambda: boundary.require_exact_cardinality([copy.deepcopy(positive_event), copy.deepcopy(positive_event)], 1),
            ),
            _expect_rejection("malformed-event", lambda: boundary.validate_service_event(malformed)),
            _expect_rejection("incomplete-completion", lambda: boundary.validate_completion(incomplete)),
            _expect_rejection(
                "sequence-regression",
                lambda: boundary.require_positive_boundary(
                    positive_epoch, positive_parent, sequence_regression, positive_completion
                ),
            ),
        ]
        if len(sink_calls) != 1 or sink_calls[0]["context_id"] != positive_context_id:
            raise AssertionError(("sink-handler", sink_calls))

        diagnostic["phase"] = "complete"
        return {
            "status": "PASS",
            "positive": {
                "capture_epoch": positive_epoch,
                "invocation_context_id": positive_context_id,
                "parent_state_event": positive_parent,
                "completion_boundary": positive_completion,
                "qualifying_service_events": positive_events,
                "observed_event_count": 1,
            },
            "verified_absence": {
                "capture_epoch": absence_epoch,
                "invocation_context_id": absence_context_id,
                "parent_state_event": absence_parent,
                "completion_boundary": absence_completion,
                "qualifying_service_events": absence_events,
                "observed_event_count": 0,
            },
            "negative_cases": negatives,
            "sink_handler_calls": sink_calls,
            "observer_callback_mode": "HOMEASSISTANT_CORE_CALLBACK",
        }
    finally:
        observer.close()


async def experiment(args: argparse.Namespace, diagnostic: dict[str, Any]) -> dict[str, Any]:
    diagnostic["phase"] = "source_identity"
    identity = load_source_identity(args)
    observed_ha = home_assistant_version()
    if observed_ha != args.expected_ha_version:
        raise AssertionError(("ha-version", observed_ha, args.expected_ha_version))

    diagnostic["phase"] = "construct_hass"
    hass, constructor_strategy, constructor_signature = construct_hass()
    diagnostic["constructor_strategy"] = constructor_strategy

    diagnostic["phase"] = "loader"
    loader_result = await verify_loader(hass, args)
    diagnostic["loader"] = loader_result

    diagnostic["phase"] = "boundary"
    boundary_result = await run_boundary(hass, diagnostic)
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
        "diagnostic_phase": "complete",
    }


async def _run(args: argparse.Namespace) -> int:
    diagnostic: dict[str, Any] = {"phase": "start"}
    try:
        result = await experiment(args, diagnostic)
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
            "diagnostic": diagnostic,
        }
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(json.dumps({
        "schema": "replaymark.ve2.e0q-role-close.v2",
        "role": args.role,
        "status": result["status"],
        "scientific_cells": 0,
        "result_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }, sort_keys=True))
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
