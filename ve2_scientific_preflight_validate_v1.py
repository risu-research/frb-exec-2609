from __future__ import annotations

"""Independent stdlib validator for VE2 zero-stimulus blueprint preflights."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED = {
    "T01_OLD": ("T01", "OLD", "2022.10.0", "9a2b545288a3cae15f497796cb9001e6a142fc02c6150df6b11975d79f6083d8"),
    "T01_NEW": ("T01", "NEW", "2026.1.0", "9c2a4b03d57a59d6b13a34b0bf4031104c19abafa8331e1b329861f45eeef363"),
    "T02_OLD": ("T02", "OLD", "2026.9.0", "5593911e8ef5db3cc29f1ab4bb6658538f6e68fecbd010de0527ecc41b5d4115"),
    "T02_NEW": ("T02", "NEW", "2026.9.0", "45375bb3a0a09b5ae7db9bdc038a73fcbec80425ec38e858e89633cb1dfdf37e"),
}


def cb(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value: object) -> str:
    return hashlib.sha256(cb(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(path: Path, role: str) -> dict[str, Any]:
    transition, source_role, version, blueprint_sha = EXPECTED[role]
    doc = json.loads(path.read_bytes())
    if doc.get("schema") != "replaymark.ve2.scientific-blueprint-preflight.v1":
        raise AssertionError((role, "schema"))
    if doc.get("status") != "PASS":
        raise AssertionError((role, "status"))
    if doc.get("transition") != transition or doc.get("source_role") != source_role:
        raise AssertionError((role, "identity"))
    if doc.get("home_assistant_version") != version:
        raise AssertionError((role, "ha-version", doc.get("home_assistant_version")))
    if doc.get("blueprint_sha256") != blueprint_sha:
        raise AssertionError((role, "blueprint-sha"))
    checks = doc.get("checks")
    expected_checks = {
        "automation_entity_materialized": True,
        "zero_automation_invocations": True,
        "zero_consequential_services": True,
        "zero_native_trace_contexts": True,
    }
    if checks != expected_checks:
        raise AssertionError((role, "checks", checks))
    hygiene = doc.get("scientific_hygiene")
    expected_hygiene = {
        "scientific_result_opened": False,
        "scientific_cells": 0,
        "trigger_stimulus_emitted": False,
        "frontier_result_seen": False,
    }
    if hygiene != expected_hygiene:
        raise AssertionError((role, "hygiene", hygiene))
    adapter = doc.get("bootstrap_adapter")
    if not isinstance(adapter, dict):
        raise AssertionError((role, "adapter"))
    if adapter.get("result_dependent_fallback") is not False or adapter.get("retry_after_failure") is not False:
        raise AssertionError((role, "adaptive-bootstrap"))
    return {
        "role": role,
        "status": "PASS",
        "file_sha256": file_sha(path),
        "home_assistant_version": version,
        "blueprint_sha256": blueprint_sha,
        "bootstrap_adapter_sha256": adapter.get("adapter_sha256"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    for role in EXPECTED:
        ap.add_argument("--" + role.lower().replace("_", "-"), required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    paths = {
        "T01_OLD": Path(args.t01_old),
        "T01_NEW": Path(args.t01_new),
        "T02_OLD": Path(args.t02_old),
        "T02_NEW": Path(args.t02_new),
    }
    rows = [validate(paths[role], role) for role in EXPECTED]
    result = {
        "schema": "replaymark.ve2.scientific-blueprint-preflight-independent-validation.v1",
        "status": "PASS",
        "roles": rows,
        "all_four_zero_stimulus": True,
        "scientific_exposure": {
            "scientific_result_opened": False,
            "scientific_cells": 0,
            "frontier_result_seen": False,
            "trigger_stimulus_emitted": False,
        },
    }
    result["validation_sha256"] = sha(result)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "roles": 4, "validation_sha256": result["validation_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
