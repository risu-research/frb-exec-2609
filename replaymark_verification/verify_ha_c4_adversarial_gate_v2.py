from __future__ import annotations

"""HA-C4 harness correction v2.

The first harness executed all twelve frozen cases and constructed a promotion
record in which every substantive criterion was True, but then incorrectly
required *every* record value to be True even though
``latency_participates_in_promotion`` is intentionally False.  This wrapper
preserves the exact frozen case constructors and expectations from v1 and only
corrects that terminal meta-assertion.  It does not change the HA-C3 gate,
protocol, carrier choice, adversarial inputs, or expected outcomes.
"""

import argparse
import asyncio
import json
from pathlib import Path

from replaymark_verification import verify_ha_c4_adversarial_gate as v1

SCHEMA = v1.SCHEMA


async def qualify(fixture_path: Path) -> dict[str, object]:
    pack = v1._load_fixture(fixture_path)
    cells = v1.build_shadow_cells(pack)
    valid, other_valid, invalid = v1._baselines(cells)

    cases: dict[str, object] = {}
    cases.update(await v1.positive_controls(valid, invalid))
    cases["C4-A1-UNRESOLVED"] = await v1.unresolved_case(valid)
    cases["C4-A2-MALFORMED-OBSERVATION"] = await v1.malformed_observation_case(valid)
    cases["C4-A3-FOREIGN-ACTION"] = await v1.foreign_action_case(valid)
    cases["C4-A4-CROSS-TASK-CERTIFICATE"] = await v1.cross_task_certificate_case(valid, other_valid)
    cases["C4-A5-CERTIFICATE-CANONICAL-BYTE-MUTATION"] = await v1.certificate_byte_mutation_case(valid)
    cases["C4-A6-RAW-AFTER-CERTIFICATION-MUTATION"] = await v1.raw_after_certification_mutation_case(valid)
    cases["C4-A7-DUPLICATE-SEQUENTIAL"] = await v1.duplicate_sequential_case(valid)
    cases["C4-A8-DUPLICATE-CONCURRENT-32"] = await v1.duplicate_concurrent_case(valid)
    cases["C4-A9-SINK-EXCEPTION"] = await v1.sink_exception_case(valid)
    cases["C4-A10-STATIC-SURFACE-AUDIT"] = v1.static_surface_case()

    if len(cases) != 12 or any(row.get("status") != "PASS" for row in cases.values()):
        raise AssertionError("C4 case matrix did not close completely")

    pre_sink_zero = all(
        int(cases[key]["historical_sink_calls"]) == 0
        for key in (
            "C4-P1-INVALID-CONTROL",
            "C4-A1-UNRESOLVED",
            "C4-A2-MALFORMED-OBSERVATION",
            "C4-A3-FOREIGN-ACTION",
            "C4-A4-CROSS-TASK-CERTIFICATE",
            "C4-A5-CERTIFICATE-CANONICAL-BYTE-MUTATION",
            "C4-A6-RAW-AFTER-CERTIFICATION-MUTATION",
        )
    )
    trust_failures_not_unresolved = all(
        cases[key]["classified_as_semantic_unresolved"] is False
        for key in (
            "C4-A2-MALFORMED-OBSERVATION",
            "C4-A3-FOREIGN-ACTION",
            "C4-A4-CROSS-TASK-CERTIFICATE",
            "C4-A5-CERTIFICATE-CANONICAL-BYTE-MUTATION",
            "C4-A6-RAW-AFTER-CERTIFICATION-MUTATION",
        )
    )

    substantive = {
        "all_12_cases_pass": True,
        "pre_sink_adversarial_cases_zero_historical_calls": pre_sink_zero,
        "trust_failures_never_reclassified_as_semantic_unresolved": trust_failures_not_unresolved,
        "sequential_duplicate_total_historical_calls_one": cases["C4-A7-DUPLICATE-SEQUENTIAL"]["total_historical_sink_calls"] == 1,
        "concurrent_32_duplicate_total_historical_calls_one": cases["C4-A8-DUPLICATE-CONCURRENT-32"]["total_historical_sink_calls"] == 1,
        "sink_exception_exactly_one_failing_attempt": cases["C4-A9-SINK-EXCEPTION"]["initial_historical_sink_attempts"] == 1,
        "sink_exception_retry_attempts_zero": cases["C4-A9-SINK-EXCEPTION"]["retry_sink_attempts"] == 0,
        "sink_exception_native_fallback_calls_zero": cases["C4-A9-SINK-EXCEPTION"]["native_fallback_calls"] == 0,
        "sink_exception_regeneration_calls_zero": cases["C4-A9-SINK-EXCEPTION"]["regeneration_calls"] == 0,
        "static_repair_surface_zero": all(cases["C4-A10-STATIC-SURFACE-AUDIT"][k] == 0 for k in (
            "fallback_surface", "retry_surface", "regeneration_surface",
            "native_automation_trigger_surface", "caller_action_override_parameters",
        )),
    }
    if not all(value is True for value in substantive.values()):
        raise AssertionError(("C4 substantive promotion criterion failed", substantive))

    promotion = dict(substantive)
    promotion["latency_participates_in_promotion"] = False

    return {
        "schema": SCHEMA,
        "status": "PASS",
        "headline_role": "ARTIFACT_TRUST_BOUNDARY_CLOSURE_NOT_SCIENTIFIC_HEADLINE",
        "frozen_c3_gate_blob": v1.C3_GATE_BLOB,
        "fixture_package_sha256": v1.FIXTURE_PACKAGE_SHA256,
        "harness_correction": {
            "version": 2,
            "scope": "terminal promotion meta-assertion only",
            "frozen_cases_changed": False,
            "expected_outcomes_changed": False,
            "c3_gate_changed": False,
            "latency_participates_in_promotion": False,
        },
        "baseline_cells": {
            "valid": valid.cell_id,
            "cross_task_valid": other_valid.cell_id,
            "invalid": invalid.cell_id,
        },
        "cases": cases,
        "promotion": promotion,
        "scope": {
            "historical_sink": "exact HA-C3 gate delegate boundary with spy/fault injection",
            "live_home_assistant_controller_execution": False,
            "new_scientific_population": False,
            "performance_claim": False,
            "durable_cross_process_exactly_once_claim": False,
        },
    }


async def _run(args: argparse.Namespace) -> None:
    result = await qualify(Path(args.fixture))
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
