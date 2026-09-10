from __future__ import annotations

"""Materialize the prospectively frozen SA1 expected semantic table.

This is a pre-live authority tool.  It reads only the already-frozen HA-C2 native
TargetModel and its claim projection.  It does not import Home Assistant, parse
the external YAML/Jinja source, read C3/C4 results, or inspect any SA1 native
execution output.
"""

import argparse
import hashlib
import json
from pathlib import Path

from replaymark_verification.ha_c2_bt_native_target import (
    CLIMATE_ENTITY,
    HaC2BetterThermostatNativeTarget,
    c2_claim,
    parse_state,
)

SCHEMA = "replaymark.sa1.expected-semantic-table.v1"
PROTOCOL_COMMIT = "bae8e1527e1d0daa66af53b57c58a6f232d9b80a"
PARENT_C5_HEAD = "c7e04dad2426bec10449dfdde7a6644eb24ec694"
NATIVE_TARGET_GIT_BLOB = "f28c7e04fd033dd3774c110f1954ce2ae851cd99"
LEGACY_MODEL_GIT_BLOB = "dc798178962351e869abd6134c7c34d9152ed0e6"
EXPECTED_ROW_COUNT = 32


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _row(target: HaC2BetterThermostatNativeTarget, state_id: str) -> dict[str, object]:
    law = target.current_distribution(state_id)
    if len(law) != 1:
        raise AssertionError("SA1 expected table requires frozen deterministic point-mass semantics")
    (full_action, post_state), mass = next(iter(law.items()))
    if mass.numerator != 1 or mass.denominator != 1:
        raise AssertionError("SA1 expected table requires unit point mass")

    presence, motion, night, current_preset = parse_state(state_id)
    _post_presence, _post_motion, _post_night, target_preset = parse_state(post_state)
    if (presence, motion, night) != (_post_presence, _post_motion, _post_night):
        raise AssertionError("frozen current transition unexpectedly changed environmental coordinates")

    full = full_action.as_dict()
    claim_action = c2_claim(0).project(full_action).as_dict()
    operation = str(full["operation"])
    if operation == "NO_ACTION":
        expected_outcome = "NO_CONSEQUENTIAL_CALL"
        native_service = None
        if current_preset != target_preset:
            raise AssertionError("NO_ACTION row does not already occupy target preset")
    elif operation == "climate.set_preset_mode":
        expected_outcome = "EXACT_HA_SERVICE_CALL"
        native_service = {
            "domain": full["service_domain"],
            "service": full["service_name"],
            "target_entity": full["concrete_target"],
            "service_data": {"preset_mode": full["preset_mode"]},
        }
        if native_service != {
            "domain": "climate",
            "service": "set_preset_mode",
            "target_entity": CLIMATE_ENTITY,
            "service_data": {"preset_mode": target_preset},
        }:
            raise AssertionError("frozen native action has unexpected consequential coordinates")
    else:
        raise AssertionError(f"unexpected frozen SA1 operation: {operation!r}")

    return {
        "state_id": state_id,
        "inputs": {
            "presence": presence,
            "motion": motion,
            "night": night,
            "current_preset": current_preset,
        },
        "expected_target_preset": target_preset,
        "expected_outcome": expected_outcome,
        "expected_claim_action": claim_action,
        "expected_native_service": native_service,
        "expected_post_state": post_state,
    }


def build_table() -> dict[str, object]:
    target = HaC2BetterThermostatNativeTarget()
    rows = [_row(target, state_id) for state_id in target.decision_states]
    if len(rows) != EXPECTED_ROW_COUNT:
        raise AssertionError(("unexpected SA1 profile state count", len(rows)))
    if len({row["state_id"] for row in rows}) != EXPECTED_ROW_COUNT:
        raise AssertionError("SA1 expected table contains duplicate state ids")
    if [row["state_id"] for row in rows] != sorted(row["state_id"] for row in rows):
        raise AssertionError("SA1 expected rows are not canonical by state id")

    outcome_counts = {
        "EXACT_HA_SERVICE_CALL": sum(row["expected_outcome"] == "EXACT_HA_SERVICE_CALL" for row in rows),
        "NO_CONSEQUENTIAL_CALL": sum(row["expected_outcome"] == "NO_CONSEQUENTIAL_CALL" for row in rows),
    }
    if sum(outcome_counts.values()) != EXPECTED_ROW_COUNT:
        raise AssertionError("SA1 outcome accounting does not close")

    rows_digest = _sha256(rows)
    return {
        "schema": SCHEMA,
        "status": "FROZEN_EXPECTED_PRE_LIVE",
        "protocol_commit": PROTOCOL_COMMIT,
        "parent_c5_head": PARENT_C5_HEAD,
        "source_authority": {
            "native_target_path": "replaymark_verification/ha_c2_bt_native_target.py",
            "native_target_git_blob": NATIVE_TARGET_GIT_BLOB,
            "legacy_model_path": "replaymark_verification/models.py",
            "legacy_model_git_blob": LEGACY_MODEL_GIT_BLOB,
            "derivation": "extensional current_distribution rows from already-frozen HA-C2 native TargetModel; no live/native result input"
        },
        "profile": {
            "name": "Better Thermostat frozen four-preset evaluation profile",
            "states": EXPECTED_ROW_COUNT,
            "claim_dimensions": ["operation", "concrete_target", "variant"],
            "climate_entity": CLIMATE_ENTITY,
        },
        "outcome_counts": outcome_counts,
        "rows_sha256": rows_digest,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    table = build_table()
    args.output.write_text(
        json.dumps(table, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "PASS",
        "rows": len(table["rows"]),
        "rows_sha256": table["rows_sha256"],
        "outcome_counts": table["outcome_counts"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
