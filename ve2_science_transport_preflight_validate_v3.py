from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "replaymark.ve2.science-transport-bootstrap-preflight.v3"
OUT_SCHEMA = "replaymark.ve2.science-transport-bootstrap-preflight-adjudication.v3"
EXPECTED = {
    "T01_OLD_RUNTIME": "2022.10.0",
    "T01_NEW_RUNTIME": "2026.1.0",
    "T02_RUNTIME": "2026.9.0",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def walk_no_fallback(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}"
            if key in {"result_dependent_fallback", "retry_after_failure"}:
                require(item is False, f"forbidden adaptive fallback at {here}")
            walk_no_fallback(item, here)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            walk_no_fallback(item, f"{path}[{i}]")


def verify(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    doc = json.loads(raw)
    require(doc.get("schema") == SCHEMA, "foreign preflight schema")
    role = doc.get("role")
    require(role in EXPECTED, "foreign preflight role")
    require(doc.get("home_assistant_version") == EXPECTED[role], f"{role} version mismatch")
    require(doc.get("status") == "PASS", f"{role} preflight not PASS")
    recorded = doc.get("result_sha256")
    require(recorded == sha({k: v for k, v in doc.items() if k != "result_sha256"}), f"{role} result digest mismatch")
    require(str(doc.get("automation_entity", "")).startswith("automation."), f"{role} automation entity missing")
    checks = doc.get("checks") or {}
    require(checks == {
        "zero_automation_invocations": True,
        "zero_neutral_service_calls": True,
        "zero_native_trace_contexts": True,
        "automation_entity_materialized": True,
    }, f"{role} zero-invocation checks mismatch")
    hygiene = doc.get("scientific_hygiene") or {}
    require(hygiene == {
        "transition_blueprint_executed": False,
        "T01_or_T02_execution_state_used": False,
        "expected_frontier_read": False,
        "historical_better_thermostat_action_dispatched": False,
        "neutral_trigger_stimulus_emitted": False,
        "neutral_automation_invocations": 0,
        "scientific_cells": 0,
        "frontier_result_seen": False,
    }, f"{role} scientific hygiene mismatch")
    adapter = doc.get("bootstrap_adapter")
    require(isinstance(adapter, dict), f"{role} adapter absent")
    walk_no_fallback(adapter)
    trigger_setup = (((adapter.get("helpers") or {}).get("trigger") or {}))
    if role == "T01_OLD_RUNTIME":
        require(trigger_setup.get("async_setup_present") is False, "2022.10 unexpectedly used new trigger setup")
    else:
        require(trigger_setup.get("async_setup_present") is True, f"{role} failed to initialize native trigger helper")
    tz = adapter.get("timezone") or {}
    require(tz.get("time_zone_after") == "UTC", f"{role} not UTC")
    return {
        "role": role,
        "home_assistant_version": EXPECTED[role],
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "result_sha256": recorded,
        "adapter_sha256": adapter.get("adapter_sha256"),
        "constructor_strategy": (adapter.get("constructor") or {}).get("strategy"),
        "loader_strategy": (adapter.get("loader") or {}).get("strategy"),
        "trigger_setup_strategy": trigger_setup.get("strategy"),
        "timezone_strategy": tz.get("strategy"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t01-old", required=True)
    ap.add_argument("--t01-new", required=True)
    ap.add_argument("--t02", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = [verify(Path(args.t01_old)), verify(Path(args.t01_new)), verify(Path(args.t02))]
    require([r["role"] for r in rows] == ["T01_OLD_RUNTIME", "T01_NEW_RUNTIME", "T02_RUNTIME"], "preflight role order mismatch")
    out = {
        "schema": OUT_SCHEMA,
        "status": "PASS",
        "roles": rows,
        "promotion": {
            "all_three_native_bootstraps": "PASS",
            "all_three_zero_neutral_invocations": True,
            "all_three_zero_scientific_cells": True,
            "frontier_result_seen": False,
            "eligible_for_neutral_transport_qualification": True,
        },
    }
    out["validation_sha256"] = sha(out)
    Path(args.out).write_text(json.dumps(out, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","validation_sha256":out["validation_sha256"],"scientific_cells":0}, sort_keys=True))


if __name__ == "__main__":
    main()
