from __future__ import annotations

"""V6 preflight adjudicator: unchanged v5 bootstrap/projection law."""

import json
from pathlib import Path
from typing import Any

import ve2_science_transport_preflight_validate_v4 as base

IMPLEMENTATION = "replaymark.ve2.science-transport-qualification-runtime.v6"
OUT_SCHEMA = "replaymark.ve2.science-transport-bootstrap-preflight-adjudication.v6"
PROJECTION_ID = "replaymark.ve2.registry-witness-exact-object-projection.v1"


def verify(path: Path) -> dict[str, Any]:
    old_impl = base.IMPLEMENTATION
    try:
        base.IMPLEMENTATION = IMPLEMENTATION
        inherited = base.verify(path)
    finally:
        base.IMPLEMENTATION = old_impl

    doc = json.loads(path.read_bytes())
    adapter = doc.get("bootstrap_adapter") or {}
    projection = adapter.get("evidence_projection") or {}
    base.require(projection.get("projection_id") == PROJECTION_ID, "projection id mismatch")
    base.require(projection.get("same_hass_object_identity") is True, "registry witness not bound to same HASS")
    base.require(projection.get("consumed_exactly_once") is True, "registry witness not single-consume")
    base.require(projection.get("manual_witness_reconstruction") is False, "manual witness reconstruction")
    base.require(projection.get("additional_home_assistant_setup_calls") == 0, "projection changed HA setup")
    base.require(projection.get("execution_semantics_changed_from_v4") is False, "projection changed setup semantics")
    base.require(projection.get("result_dependent_fallback") is False, "projection adaptive fallback")
    base.require(projection.get("retry_after_failure") is False, "projection retry")
    prior = projection.get("prior_adapter_sha256")
    base.require(isinstance(prior, str) and len(prior) == 64, "pre-projection digest missing")
    return {
        **inherited,
        "projection_id": PROJECTION_ID,
        "same_hass_object_identity": True,
        "consumed_exactly_once": True,
        "prior_adapter_sha256": prior,
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--t01-old", required=True)
    ap.add_argument("--t01-new", required=True)
    ap.add_argument("--t02", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = [verify(Path(args.t01_old)), verify(Path(args.t01_new)), verify(Path(args.t02))]
    base.require([r["role"] for r in rows] == ["T01_OLD_RUNTIME", "T01_NEW_RUNTIME", "T02_RUNTIME"], "role order mismatch")
    out = {
        "schema": OUT_SCHEMA,
        "status": "PASS",
        "roles": rows,
        "promotion": {
            "all_three_native_bootstraps": "PASS",
            "all_six_native_registry_loads": "PASS",
            "all_three_exact_registry_witness_projections": "PASS",
            "all_three_zero_neutral_invocations": True,
            "all_three_zero_scientific_cells": True,
            "frontier_result_seen": False,
            "eligible_for_neutral_transport_qualification": True
        }
    }
    out["validation_sha256"] = base.base.sha(out)
    Path(args.out).write_text(json.dumps(out, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","validation_sha256":out["validation_sha256"],"scientific_cells":0}, sort_keys=True))


if __name__ == "__main__":
    main()
