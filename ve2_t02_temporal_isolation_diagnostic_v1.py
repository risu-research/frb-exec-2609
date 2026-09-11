from __future__ import annotations

"""Non-promotable T02 temporal isolation diagnostic.

This diagnostic executes exactly one existing v5 neutral transport case in a
fresh process.  It does not alter the Home Assistant setup, trigger, action,
clock transport, or witness semantics.  Observation-only wrappers journal the
boundaries around v5 fresh-HASS materialization, the inherited clock driver,
and inherited witness collection so a timeout can be localized without
changing the executed neutral case.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Awaitable, Callable

import ve2_science_transport_qualify_v3 as v3
import ve2_science_transport_qualify_v4 as v4  # imported to pin exact inherited layer
import ve2_science_transport_qualify_v5 as v5

SCHEMA = "replaymark.ve2.t02-temporal-isolation-diagnostic.v1"
DIAGNOSTIC_ID = "NON_PROMOTABLE_T02_TEMPORAL_ISOLATION_DIAGNOSTIC_V1"
EXPECTED_HA = "2026.9.0"
V5_FAILURE_SEAL = "c17d2506e465b9bb3ac71cb04cb7c10c0360ba01"
CASE_ORDER = ["state", "state_for_120s", "time", "homeassistant_start_delay_30s"]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exc(exc: BaseException) -> dict[str, Any]:
    return {"type": type(exc).__name__, "message": str(exc)}


async def _execute(case: str) -> dict[str, Any]:
    if v3.HA_VERSION != EXPECTED_HA:
        raise AssertionError(("diagnostic-runtime-mismatch", v3.HA_VERSION, EXPECTED_HA))

    # Install the exact v5 evidence-projection layer first.  Everything below
    # is observation-only and delegates to the already-frozen implementation.
    v5._install_v5()

    journal: list[dict[str, Any]] = []
    seq = 0

    def mark(event: str, **fields: Any) -> None:
        nonlocal seq
        seq += 1
        journal.append(
            {
                "seq": seq,
                "event": event,
                "observed_ns": time.perf_counter_ns(),
                **fields,
            }
        )

    original_fresh = v3._fresh_hass
    original_drive = v3._drive_clock
    original_collect = v3._collect_case

    async def observed_fresh(*args: Any, **kwargs: Any):
        mark("FRESH_HASS_BEGIN")
        try:
            result = await original_fresh(*args, **kwargs)
        except Exception as exc:
            mark("FRESH_HASS_ERROR", failure=_exc(exc))
            raise
        mark("FRESH_HASS_END")
        return result

    def observed_drive(*args: Any, **kwargs: Any):
        mark("CLOCK_DRIVER_BEGIN", fire_all=bool(kwargs.get("fire_all", False)))
        try:
            result = original_drive(*args, **kwargs)
        except Exception as exc:
            mark("CLOCK_DRIVER_ERROR", failure=_exc(exc))
            raise
        mark(
            "CLOCK_DRIVER_END",
            scheduled=result.get("scheduled") if isinstance(result, dict) else None,
            fired=result.get("fired") if isinstance(result, dict) else None,
        )
        return result

    async def observed_collect(*args: Any, **kwargs: Any):
        mark("WITNESS_COLLECTION_BEGIN")
        try:
            result = await original_collect(*args, **kwargs)
        except Exception as exc:
            mark("WITNESS_COLLECTION_ERROR", failure=_exc(exc))
            raise
        mark("WITNESS_COLLECTION_END", row_pass=bool(result.get("pass")))
        return result

    v3._fresh_hass = observed_fresh
    v3._drive_clock = observed_drive
    v3._collect_case = observed_collect

    calls: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
        "state": lambda: v3.run_state(),
        "state_for_120s": v3.run_state_for,
        "time": v3.run_time,
        "homeassistant_start_delay_30s": v3.run_startup_delay,
    }
    if case not in calls:
        raise AssertionError(("unknown-diagnostic-case", case))

    mark("CASE_BEGIN", case=case)
    row: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    try:
        row = await calls[case]()
        status = "PASS" if bool(row.get("pass")) else "ROW_FAIL"
        mark("CASE_END", case=case, row_pass=bool(row.get("pass")))
    except Exception as exc:
        failure = _exc(exc)
        status = "EXCEPTION"
        mark("CASE_ERROR", case=case, failure=failure)

    capsule: dict[str, Any] = {
        "schema": SCHEMA,
        "diagnostic_id": DIAGNOSTIC_ID,
        "status": status,
        "case": case,
        "case_order_index": CASE_ORDER.index(case),
        "home_assistant_version": v3.HA_VERSION,
        "inherited_transport_implementation": v3.IMPLEMENTATION,
        "v5_failure_seal": V5_FAILURE_SEAL,
        "row": row,
        "failure": failure,
        "journal": journal,
        "observation_law": {
            "fresh_hass_wrapper_delegates_exactly_once": True,
            "clock_driver_wrapper_delegates_exactly_once_when_called": True,
            "witness_collection_wrapper_delegates_exactly_once_when_called": True,
            "trigger_definition_mutated": False,
            "action_definition_mutated": False,
            "clock_target_mutated": False,
            "wait_timeout_mutated": False,
            "home_assistant_setup_calls_added": 0,
            "result_dependent_fallback": False,
            "retry_after_failure": False,
        },
        "scientific_hygiene": {
            "diagnostic_non_promotable": True,
            "scientific_result_opened": False,
            "frontier_result_seen": False,
            "scientific_cells": 0,
            "expected_frontier_read": False,
            "T01_or_T02_execution_state_used": False,
            "transition_blueprint_executed": False,
            "historical_better_thermostat_action_dispatched": False,
        },
    }
    capsule["capsule_sha256"] = _sha(capsule)
    return capsule


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=CASE_ORDER)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = asyncio.run(_execute(args.case))
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps(
            {
                "diagnostic_id": DIAGNOSTIC_ID,
                "case": args.case,
                "status": result["status"],
                "scientific_cells": 0,
                "capsule_sha256": result["capsule_sha256"],
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
