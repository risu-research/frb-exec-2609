from __future__ import annotations

"""Pre-scientific structural qualification for the HA-C3 execution gate.

This module consumes only already-open HA-C2 archived material.  It opens no new
live Home Assistant target result.  It verifies sink cardinality, exact action
bytes, certificate/raw binding, duplicate rejection, and consume-before-delegate
failure semantics.
"""

import argparse
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from replaymark.runtime_ha_bt_execution_gate import HaBtCertifiedExecutionGate
from replaymark.runtime_ha_bt_shadow_bridge import certify_ha_bt_shadow_reuse
from replaymark_verification.build_ha_c2_shadow_cells import build_shadow_cells
from replaymark_verification.ha_c2_bt_native_target import compile_c2_contract

FIXTURE_PACKAGE_SHA256 = "297ec8740a4604e60b3b64b150a2489bb4ada2ddaf988f0202bdaf8649204ab1"
FIXTURE_DECODED_SHA256 = "d34de50c920643fcc9ed1d59c5127e09f2aa8d6805c11287739ee4267b865774"


class _FakeServices:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail = fail

    async def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, object],
        *,
        blocking: bool,
        context: object,
    ) -> None:
        self.calls.append(
            {
                "domain": domain,
                "service": service,
                "service_data": copy.deepcopy(service_data),
                "blocking": blocking,
                "context_id": str(context.id),
            }
        )
        if self.fail:
            raise RuntimeError("synthetic HA-C3 sink failure")


class _FakeHass:
    def __init__(self, *, fail: bool = False) -> None:
        self.services = _FakeServices(fail=fail)


def _load_fixture(path: Path) -> dict[str, object]:
    package = path.read_bytes()
    if hashlib.sha256(package).hexdigest() != FIXTURE_PACKAGE_SHA256:
        raise AssertionError("C1 fixture package digest changed")
    decoded = gzip.decompress(base64.b64decode(package))
    if hashlib.sha256(decoded).hexdigest() != FIXTURE_DECODED_SHA256:
        raise AssertionError("C1 decoded fixture digest changed")
    value = json.loads(decoded)
    if value.get("schema") != "replaymark.ha-c1.archived-fixtures.v1":
        raise AssertionError("foreign C1 fixture schema")
    return value


def _expected_service_data(raw: dict[str, object]) -> dict[str, object]:
    return copy.deepcopy(raw["service_event"]["service_data"])


async def qualify(fixture_path: Path) -> dict[str, object]:
    cells = build_shadow_cells(_load_fixture(fixture_path))
    admit_cell = next(c for c in cells if c.family == "N2b" and c.decision_index == 0)
    block_cell = next(c for c in cells if c.family == "N2")
    h1 = compile_c2_contract(1)
    h0 = compile_c2_contract(0)

    admit_cert = certify_ha_bt_shadow_reuse(
        h1,
        base_raw_observation=admit_cell.target_base_raw_observation,
        parent_state_event=admit_cell.target_parent_state_event,
        historical_raw_action=admit_cell.historical_raw_action,
    )
    if admit_cert.admission.disposition.value != "ADMIT_REUSE":
        raise AssertionError("archived positive control is no longer ADMIT_REUSE")
    block_cert = certify_ha_bt_shadow_reuse(
        h0,
        base_raw_observation=block_cell.target_base_raw_observation,
        parent_state_event=block_cell.target_parent_state_event,
        historical_raw_action=block_cell.historical_raw_action,
    )
    if block_cert.admission.disposition.value != "BLOCK_REUSE":
        raise AssertionError("archived negative control is no longer BLOCK_REUSE")

    admit_hass = _FakeHass()
    admit_gate = HaBtCertifiedExecutionGate()
    receipt = await admit_gate.dispatch(
        admit_hass,
        h1,
        base_raw_observation=admit_cell.target_base_raw_observation,
        parent_state_event=admit_cell.target_parent_state_event,
        historical_raw_action=admit_cell.historical_raw_action,
        presented_certificate=admit_cert,
    )
    if not receipt.execution_performed or receipt.admission_disposition.value != "ADMIT_REUSE":
        raise AssertionError("ADMIT control did not execute")
    if len(admit_hass.services.calls) != 1:
        raise AssertionError("ADMIT control did not cross sink exactly once")
    call = admit_hass.services.calls[0]
    if call["domain"] != "climate" or call["service"] != "set_preset_mode":
        raise AssertionError("ADMIT control crossed foreign service sink")
    if call["service_data"] != _expected_service_data(admit_cell.historical_raw_action):
        raise AssertionError("ADMIT control rewrote historical service data")
    if call["context_id"] != receipt.dispatch_context_id:
        raise AssertionError("ADMIT receipt lost dispatch context binding")

    duplicate_rejected = False
    try:
        await admit_gate.dispatch(
            admit_hass,
            h1,
            base_raw_observation=admit_cell.target_base_raw_observation,
            parent_state_event=admit_cell.target_parent_state_event,
            historical_raw_action=admit_cell.historical_raw_action,
            presented_certificate=admit_cert,
        )
    except RuntimeError:
        duplicate_rejected = True
    if not duplicate_rejected or len(admit_hass.services.calls) != 1:
        raise AssertionError("duplicate certificate reached historical sink")

    block_hass = _FakeHass()
    block_gate = HaBtCertifiedExecutionGate()
    block_receipt = await block_gate.dispatch(
        block_hass,
        h0,
        base_raw_observation=block_cell.target_base_raw_observation,
        parent_state_event=block_cell.target_parent_state_event,
        historical_raw_action=block_cell.historical_raw_action,
        presented_certificate=block_cert,
    )
    if block_receipt.execution_performed or block_receipt.admission_disposition.value != "BLOCK_REUSE":
        raise AssertionError("BLOCK control executed history")
    if block_hass.services.calls:
        raise AssertionError("BLOCK control reached historical sink")

    mutated = copy.deepcopy(admit_cell.historical_raw_action)
    old_preset = mutated["service_event"]["service_data"]["preset_mode"]
    mutated["service_event"]["service_data"]["preset_mode"] = "home" if old_preset != "home" else "away"
    mismatch_hass = _FakeHass()
    mismatch_gate = HaBtCertifiedExecutionGate()
    mismatch_rejected = False
    try:
        await mismatch_gate.dispatch(
            mismatch_hass,
            h1,
            base_raw_observation=admit_cell.target_base_raw_observation,
            parent_state_event=admit_cell.target_parent_state_event,
            historical_raw_action=mutated,
            presented_certificate=admit_cert,
        )
    except ValueError:
        mismatch_rejected = True
    if not mismatch_rejected or mismatch_hass.services.calls:
        raise AssertionError("certificate/raw mismatch reached historical sink")

    failing_hass = _FakeHass(fail=True)
    failing_gate = HaBtCertifiedExecutionGate()
    first_failed = False
    try:
        await failing_gate.dispatch(
            failing_hass,
            h1,
            base_raw_observation=admit_cell.target_base_raw_observation,
            parent_state_event=admit_cell.target_parent_state_event,
            historical_raw_action=admit_cell.historical_raw_action,
            presented_certificate=admit_cert,
        )
    except RuntimeError as exc:
        if "synthetic HA-C3 sink failure" not in str(exc):
            raise
        first_failed = True
    retry_rejected = False
    try:
        await failing_gate.dispatch(
            failing_hass,
            h1,
            base_raw_observation=admit_cell.target_base_raw_observation,
            parent_state_event=admit_cell.target_parent_state_event,
            historical_raw_action=admit_cell.historical_raw_action,
            presented_certificate=admit_cert,
        )
    except RuntimeError as exc:
        if "already consumed" not in str(exc):
            raise
        retry_rejected = True
    if not first_failed or not retry_rejected or len(failing_hass.services.calls) != 1:
        raise AssertionError("consume-before-delegate failure semantics changed")

    return {
        "schema": "replaymark.ha-c3.execution-gate-preflight.v1",
        "status": "PASS",
        "scientific_result_opened": False,
        "admit_exact_sink_calls": 1,
        "block_sink_calls": 0,
        "duplicate_rejected": True,
        "mismatch_rejected_before_sink": True,
        "sink_failure_consumed_before_delegate": True,
        "sink_failure_retry_rejected": True,
        "native_fallback_inside_gate": False,
    }


async def _main(args: argparse.Namespace) -> None:
    result = await qualify(Path(args.fixture))
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")


def main() -> None:
    import asyncio
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
