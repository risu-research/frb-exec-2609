from __future__ import annotations

"""Independent v4 zero-invocation bootstrap validator.

Reuses the frozen v3 adjudication law and adds exactly one new obligation:
both native registries must have been fully loaded, empty, and untouched by
manual ReplayMark registry mutation before automation materialization.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import ve2_science_transport_preflight_validate_v3 as base

OUT_SCHEMA = "replaymark.ve2.science-transport-bootstrap-preflight-adjudication.v4"
IMPLEMENTATION = "replaymark.ve2.science-transport-qualification-runtime.v4"
REGISTRY_CLOSURE_ID = "replaymark.ve2.native-device-entity-registry-closure.v1"


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def verify(path: Path) -> dict[str, Any]:
    inherited = base.verify(path)
    raw = path.read_bytes()
    doc = json.loads(raw)
    role = doc["role"]
    require(doc.get("implementation") == IMPLEMENTATION, f"{role} implementation mismatch")
    adapter = doc.get("bootstrap_adapter") or {}
    registries = adapter.get("registries") or {}
    require(registries.get("closure_id") == REGISTRY_CLOSURE_ID, f"{role} registry closure id mismatch")
    require(registries.get("order") == ["device_registry", "entity_registry"], f"{role} registry order mismatch")
    require(registries.get("result_dependent_fallback") is False, f"{role} registry adaptive fallback")
    require(registries.get("retry_after_failure") is False, f"{role} registry retry")

    summaries: dict[str, Any] = {}
    for key, collection in (("device_registry", "devices"), ("entity_registry", "entities")):
        reg = registries.get(key) or {}
        require(reg.get("data_registry_present_before") is False, f"{role}/{key} preexisting partial registry")
        require(reg.get("required_collection") == collection, f"{role}/{key} wrong collection")
        require(reg.get("required_collection_present_after") is True, f"{role}/{key} not fully loaded")
        require(reg.get("required_collection_count_after") == 0, f"{role}/{key} nonempty neutral registry")
        require(reg.get("manual_hass_data_registry_injection") is False, f"{role}/{key} manual data injection")
        require(reg.get("manual_registry_collection_assignment") is False, f"{role}/{key} manual collection assignment")
        require(reg.get("manual_loaded_event_manipulation") is False, f"{role}/{key} manual loaded-event mutation")
        require(reg.get("result_dependent_fallback") is False, f"{role}/{key} result-dependent fallback")
        require(reg.get("retry_after_failure") is False, f"{role}/{key} retry-after-failure")
        if reg.get("loaded_event_present") is True:
            require(reg.get("loaded_event_set_after") is True, f"{role}/{key} native loaded event not set")
        summaries[key] = {
            "registry_type": reg.get("registry_type"),
            "native_async_setup_present": reg.get("native_async_setup_present"),
            "native_async_setup_called": reg.get("native_async_setup_called"),
            "native_async_load_signature": reg.get("native_async_load_signature"),
            "load_empty_selected_by_signature": reg.get("load_empty_selected_by_signature"),
            "loaded_event_present": reg.get("loaded_event_present"),
            "loaded_event_set_after": reg.get("loaded_event_set_after"),
        }

    return {
        **inherited,
        "registry_closure_id": REGISTRY_CLOSURE_ID,
        "registries": summaries,
        "preflight_file_sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t01-old", required=True)
    ap.add_argument("--t01-new", required=True)
    ap.add_argument("--t02", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = [verify(Path(args.t01_old)), verify(Path(args.t01_new)), verify(Path(args.t02))]
    require([row["role"] for row in rows] == ["T01_OLD_RUNTIME", "T01_NEW_RUNTIME", "T02_RUNTIME"], "role order mismatch")
    out = {
        "schema": OUT_SCHEMA,
        "status": "PASS",
        "roles": rows,
        "promotion": {
            "all_three_native_bootstraps": "PASS",
            "all_six_native_registry_loads": "PASS",
            "all_three_zero_neutral_invocations": True,
            "all_three_zero_scientific_cells": True,
            "frontier_result_seen": False,
            "eligible_for_neutral_transport_qualification": True,
        },
    }
    out["validation_sha256"] = base.sha(out)
    Path(args.out).write_text(json.dumps(out, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","validation_sha256":out["validation_sha256"],"scientific_cells":0}, sort_keys=True))


if __name__ == "__main__":
    main()
