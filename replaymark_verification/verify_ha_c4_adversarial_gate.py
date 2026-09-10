from __future__ import annotations

"""HA-C4 adversarial trust-boundary qualification.

This is deliberately not a new live scientific headline.  It attacks the exact
frozen HA-C3 historical execution gate with semantic ambiguity, malformed or
foreign raw material, certificate/raw binding violations, duplicate
consumption, and an injected delegate exception.  The matrix distinguishes
semantic BLOCK from pre-admission trust failure and proves that a sink exception
cannot become retry, regeneration, or gate-owned native fallback.
"""

import argparse
import ast
import asyncio
import base64
import copy
import gzip
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from replaymark.compiled_contract import compile_explicit_contract
from replaymark.contracts import ClaimSpec, EvidenceSpec, Verdict
from replaymark.execution_admission import ExecutionAdmissionDisposition
from replaymark.runtime_ha_bt_decision_boundary import reconstruct_ha_bt_pre_service_boundary
from replaymark.runtime_ha_bt_execution_gate import (
    HaBtCertifiedExecutionGate,
    ha_bt_execution_gate_rule_record,
)
from replaymark.runtime_ha_bt_observation import realize_ha_bt_observation
from replaymark.runtime_ha_bt_shadow_bridge import HaBtShadowCertificate, certify_ha_bt_shadow_reuse
from replaymark_verification.build_ha_c2_shadow_cells import ShadowCell, build_shadow_cells
from replaymark_verification.evidence_models import model_from_expected_inverse
from replaymark_verification.ha_c2_bt_native_target import compile_c2_contract
from replaymark_verification.models import TableTargetModel

SCHEMA = "replaymark.ha-c4.adversarial-gate-qualification.v1"
FIXTURE_PACKAGE_SHA256 = "297ec8740a4604e60b3b64b150a2489bb4ada2ddaf988f0202bdaf8649204ab1"
C3_GATE_BLOB = "ec8d445bcf6659bead696fa4868ff7778123dbf6"


class _SpyServices:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def async_call(
        self,
        domain: object,
        service: object,
        service_data: object,
        *,
        blocking: object = False,
        context: object = None,
    ) -> None:
        self.calls.append(
            {
                "domain": domain,
                "service": service,
                "service_data": copy.deepcopy(service_data),
                "blocking": blocking,
                "context_id": None if context is None else str(getattr(context, "id", None)),
            }
        )
        # Force an async scheduling point after the gate has consumed the
        # certificate but before the delegate returns.  This makes the 32-way
        # duplicate test adversarial to event-loop interleaving rather than a
        # merely sequential loop.
        await asyncio.sleep(0)
        if self.fail:
            raise RuntimeError("injected C4 historical sink exception")


class _SpyHass(SimpleNamespace):
    services: _SpyServices


def _hass(*, fail: bool = False) -> _SpyHass:
    return _SpyHass(services=_SpyServices(fail=fail))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_fixture(path: Path) -> dict[str, object]:
    package = path.read_bytes()
    actual = _sha256_bytes(package)
    if actual != FIXTURE_PACKAGE_SHA256:
        raise AssertionError(("C1 fixture package digest changed", actual))
    decoded = gzip.decompress(base64.b64decode(package))
    value = json.loads(decoded)
    if value.get("schema") != "replaymark.ha-c1.archived-fixtures.v1":
        raise AssertionError("foreign C1 fixture schema")
    return value


def _baselines(cells: list[ShadowCell]) -> tuple[ShadowCell, ShadowCell, ShadowCell]:
    valid = sorted(
        (c for c in cells if c.family == "N2b" and c.decision_index == 0),
        key=lambda c: c.cell_id,
    )
    invalid = sorted((c for c in cells if c.family == "N2"), key=lambda c: c.cell_id)
    if len(valid) != 10 or len(invalid) != 10:
        raise AssertionError(("frozen C2 carrier population changed", len(valid), len(invalid)))
    return valid[0], valid[1], invalid[0]


def _cert(contract: Any, cell: ShadowCell) -> HaBtShadowCertificate:
    return certify_ha_bt_shadow_reuse(
        contract,
        base_raw_observation=copy.deepcopy(cell.target_base_raw_observation),
        parent_state_event=copy.deepcopy(cell.target_parent_state_event),
        historical_raw_action=copy.deepcopy(cell.historical_raw_action),
    )


def _historical_service_material(cell: ShadowCell) -> tuple[str, str, dict[str, object]]:
    event = dict(cell.historical_raw_action["service_event"])
    return str(event["domain"]), str(event["service"]), copy.deepcopy(dict(event["service_data"]))


def _exception_record(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


async def _expect_pre_sink_rejection(
    *,
    label: str,
    thunk: Callable[[_SpyHass], Awaitable[object]],
) -> dict[str, object]:
    hass = _hass()
    try:
        await thunk(hass)
    except Exception as exc:
        record = _exception_record(exc)
    else:
        raise AssertionError(f"{label} unexpectedly returned an execution receipt")
    if hass.services.calls:
        raise AssertionError((label, "trust failure reached historical sink", hass.services.calls))
    return {
        "status": "PASS",
        "admission_receipt": None,
        "historical_sink_calls": 0,
        "exception": record,
        "classified_as_semantic_unresolved": False,
    }


def _unresolved_contract(cell: ShadowCell):
    boundary = reconstruct_ha_bt_pre_service_boundary(
        copy.deepcopy(cell.target_base_raw_observation),
        copy.deepcopy(cell.target_parent_state_event),
    )
    observation = realize_ha_bt_observation(boundary.reconstructed_raw_observation)
    token = observation.evidence_token

    # The historical HA action projects to climate.set_preset_mode on this
    # verification-only H=0 claim.  One compatible world supports it and the
    # other supports NO_ACTION: possible but not guaranteed => UNRESOLVED.
    target = TableTargetModel(
        outputs=("climate.set_preset_mode", "NO_ACTION"),
        continuations=("tick",),
        next_state=((0,), (1,)),
    )
    claim = ClaimSpec(
        "ha-c4-synthetic-ambiguity-h0-v1",
        ("operation",),
        0,
        "artifact-trust-boundary-only",
    )
    evidence = EvidenceSpec(
        "ha-c4-synthetic-ambiguity-evidence-v1",
        ((token, ("s0", "s1")),),
    )
    contract = compile_explicit_contract(
        target,
        claim,
        model_from_expected_inverse(target, evidence),
        evidence_id=evidence.evidence_id,
    )
    return contract, token


async def positive_controls(valid: ShadowCell, invalid: ShadowCell) -> dict[str, object]:
    h1 = compile_c2_contract(1)
    h0 = compile_c2_contract(0)

    valid_cert = _cert(h1, valid)
    if valid_cert.runtime_certificate.adjudication.verdict is not Verdict.VALID:
        raise AssertionError("C4 valid control ceased to be VALID")
    vh = _hass()
    vreceipt = await HaBtCertifiedExecutionGate().dispatch(
        vh,
        h1,
        base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
        parent_state_event=copy.deepcopy(valid.target_parent_state_event),
        historical_raw_action=copy.deepcopy(valid.historical_raw_action),
        presented_certificate=valid_cert,
    )
    if vreceipt.admission_disposition is not ExecutionAdmissionDisposition.ADMIT_REUSE:
        raise AssertionError("C4 valid control did not admit")
    if len(vh.services.calls) != 1:
        raise AssertionError(("valid control sink cardinality", len(vh.services.calls)))
    domain, service, data = _historical_service_material(valid)
    call = vh.services.calls[0]
    if (call["domain"], call["service"], call["service_data"]) != (domain, service, data):
        raise AssertionError("valid control did not delegate the exact historical service material")

    invalid_cert = _cert(h0, invalid)
    if invalid_cert.runtime_certificate.adjudication.verdict is not Verdict.INVALID:
        raise AssertionError("C4 invalid control ceased to be INVALID")
    ih = _hass()
    ireceipt = await HaBtCertifiedExecutionGate().dispatch(
        ih,
        h0,
        base_raw_observation=copy.deepcopy(invalid.target_base_raw_observation),
        parent_state_event=copy.deepcopy(invalid.target_parent_state_event),
        historical_raw_action=copy.deepcopy(invalid.historical_raw_action),
        presented_certificate=invalid_cert,
    )
    if ireceipt.admission_disposition is not ExecutionAdmissionDisposition.BLOCK_REUSE:
        raise AssertionError("C4 invalid control did not block")
    if ih.services.calls:
        raise AssertionError("INVALID control reached historical sink")

    return {
        "C4-P0-VALID-CONTROL": {
            "status": "PASS",
            "verdict": "VALID",
            "admission": "ADMIT_REUSE",
            "historical_sink_calls": 1,
            "exact_historical_material": True,
        },
        "C4-P1-INVALID-CONTROL": {
            "status": "PASS",
            "verdict": "INVALID",
            "admission": "BLOCK_REUSE",
            "historical_sink_calls": 0,
        },
    }


async def unresolved_case(valid: ShadowCell) -> dict[str, object]:
    contract, token = _unresolved_contract(valid)
    cert = _cert(contract, valid)
    if cert.runtime_certificate.adjudication.verdict is not Verdict.UNRESOLVED:
        raise AssertionError(("synthetic ambiguity did not yield UNRESOLVED", cert.runtime_certificate.adjudication.verdict.value))
    if cert.admission.disposition is not ExecutionAdmissionDisposition.BLOCK_REUSE:
        raise AssertionError("UNRESOLVED was not mapped to BLOCK_REUSE")
    hass = _hass()
    receipt = await HaBtCertifiedExecutionGate().dispatch(
        hass,
        contract,
        base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
        parent_state_event=copy.deepcopy(valid.target_parent_state_event),
        historical_raw_action=copy.deepcopy(valid.historical_raw_action),
        presented_certificate=cert,
    )
    if receipt.admission_disposition is not ExecutionAdmissionDisposition.BLOCK_REUSE:
        raise AssertionError("gate changed UNRESOLVED admission")
    if hass.services.calls:
        raise AssertionError("UNRESOLVED reached historical sink")
    return {
        "status": "PASS",
        "verdict": "UNRESOLVED",
        "admission": "BLOCK_REUSE",
        "historical_sink_calls": 0,
        "well_formed_ha_runtime_material": True,
        "ambiguous_evidence_token_sha256": _sha256_bytes(token.encode("utf-8")),
        "trust_failure": False,
    }


async def malformed_observation_case(valid: ShadowCell) -> dict[str, object]:
    contract = compile_c2_contract(1)
    cert = _cert(contract, valid)
    malformed = copy.deepcopy(valid.target_base_raw_observation)
    del malformed["snapshot"]["motion"]

    async def thunk(hass: _SpyHass):
        return await HaBtCertifiedExecutionGate().dispatch(
            hass,
            contract,
            base_raw_observation=malformed,
            parent_state_event=copy.deepcopy(valid.target_parent_state_event),
            historical_raw_action=copy.deepcopy(valid.historical_raw_action),
            presented_certificate=cert,
        )

    result = await _expect_pre_sink_rejection(label="malformed observation", thunk=thunk)
    result["mutation"] = "delete snapshot.motion"
    return result


async def foreign_action_case(valid: ShadowCell) -> dict[str, object]:
    contract = compile_c2_contract(1)
    cert = _cert(contract, valid)
    foreign = copy.deepcopy(valid.historical_raw_action)
    foreign["service_event"]["service_data"]["entity_id"] = ["climate.c4_foreign_target"]

    async def thunk(hass: _SpyHass):
        return await HaBtCertifiedExecutionGate().dispatch(
            hass,
            contract,
            base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
            parent_state_event=copy.deepcopy(valid.target_parent_state_event),
            historical_raw_action=foreign,
            presented_certificate=cert,
        )

    result = await _expect_pre_sink_rejection(label="foreign action", thunk=thunk)
    result["mutation"] = "historical target entity -> climate.c4_foreign_target"
    return result


async def cross_task_certificate_case(valid: ShadowCell, other_valid: ShadowCell) -> dict[str, object]:
    contract = compile_c2_contract(1)
    cert_a = _cert(contract, valid)
    cert_b = _cert(contract, other_valid)
    if cert_a.canonical_bytes() == cert_b.canonical_bytes():
        raise AssertionError("cross-task certificates unexpectedly byte-identical")

    async def thunk(hass: _SpyHass):
        return await HaBtCertifiedExecutionGate().dispatch(
            hass,
            contract,
            base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
            parent_state_event=copy.deepcopy(valid.target_parent_state_event),
            historical_raw_action=copy.deepcopy(valid.historical_raw_action),
            presented_certificate=cert_b,
        )

    result = await _expect_pre_sink_rejection(label="cross-task certificate", thunk=thunk)
    result.update({
        "raw_cell": valid.cell_id,
        "presented_certificate_cell": other_valid.cell_id,
        "certificate_exact": False,
    })
    return result


async def certificate_byte_mutation_case(valid: ShadowCell) -> dict[str, object]:
    contract = compile_c2_contract(1)
    cert = _cert(contract, valid)
    mutated = copy.deepcopy(cert)
    original = mutated.bridge_semantic_digest
    replacement = ("0" if original[0] != "0" else "1") + original[1:]
    object.__setattr__(mutated, "bridge_semantic_digest", replacement)
    if not isinstance(mutated, HaBtShadowCertificate):
        raise AssertionError("mutated certificate lost runtime type")
    if mutated.canonical_bytes() == cert.canonical_bytes():
        raise AssertionError("canonical-byte mutation did not change certificate bytes")

    async def thunk(hass: _SpyHass):
        return await HaBtCertifiedExecutionGate().dispatch(
            hass,
            contract,
            base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
            parent_state_event=copy.deepcopy(valid.target_parent_state_event),
            historical_raw_action=copy.deepcopy(valid.historical_raw_action),
            presented_certificate=mutated,
        )

    result = await _expect_pre_sink_rejection(label="certificate canonical-byte mutation", thunk=thunk)
    result.update({
        "mutated_field": "bridge_semantic_digest",
        "canonical_bytes_changed": True,
        "certificate_exact": False,
    })
    return result


async def raw_after_certification_mutation_case(valid: ShadowCell) -> dict[str, object]:
    contract = compile_c2_contract(1)
    cert = _cert(contract, valid)
    raw = copy.deepcopy(valid.target_base_raw_observation)
    original_label = str(raw["snapshot"]["label"])
    raw["snapshot"]["label"] = original_label + "-c4-after-certification-mutation"

    # The label is provenance-bearing but not one of the four evidence-token
    # coordinates.  This is intentionally stronger than a semantic mutation:
    # even when the evidence token stays the same, raw-material binding must fail.
    before_boundary = reconstruct_ha_bt_pre_service_boundary(
        copy.deepcopy(valid.target_base_raw_observation),
        copy.deepcopy(valid.target_parent_state_event),
    )
    after_boundary = reconstruct_ha_bt_pre_service_boundary(
        copy.deepcopy(raw),
        copy.deepcopy(valid.target_parent_state_event),
    )
    before_token = realize_ha_bt_observation(before_boundary.reconstructed_raw_observation).evidence_token
    after_token = realize_ha_bt_observation(after_boundary.reconstructed_raw_observation).evidence_token
    if before_token != after_token:
        raise AssertionError("C4 provenance-only raw mutation unexpectedly changed semantic evidence token")

    async def thunk(hass: _SpyHass):
        return await HaBtCertifiedExecutionGate().dispatch(
            hass,
            contract,
            base_raw_observation=raw,
            parent_state_event=copy.deepcopy(valid.target_parent_state_event),
            historical_raw_action=copy.deepcopy(valid.historical_raw_action),
            presented_certificate=cert,
        )

    result = await _expect_pre_sink_rejection(label="raw mutation after certification", thunk=thunk)
    result.update({
        "mutation": "snapshot.label only",
        "semantic_evidence_token_unchanged": True,
        "provenance_binding_rejected": True,
    })
    return result


async def duplicate_sequential_case(valid: ShadowCell) -> dict[str, object]:
    contract = compile_c2_contract(1)
    cert = _cert(contract, valid)
    hass = _hass()
    gate = HaBtCertifiedExecutionGate()
    first = await gate.dispatch(
        hass,
        contract,
        base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
        parent_state_event=copy.deepcopy(valid.target_parent_state_event),
        historical_raw_action=copy.deepcopy(valid.historical_raw_action),
        presented_certificate=cert,
    )
    if first.admission_disposition is not ExecutionAdmissionDisposition.ADMIT_REUSE:
        raise AssertionError("sequential duplicate control first call did not admit")
    try:
        await gate.dispatch(
            hass,
            contract,
            base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
            parent_state_event=copy.deepcopy(valid.target_parent_state_event),
            historical_raw_action=copy.deepcopy(valid.historical_raw_action),
            presented_certificate=cert,
        )
    except Exception as exc:
        second = _exception_record(exc)
    else:
        raise AssertionError("sequential duplicate executed twice")
    if len(hass.services.calls) != 1:
        raise AssertionError(("sequential duplicate sink cardinality", len(hass.services.calls)))
    return {
        "status": "PASS",
        "first_admission": "ADMIT_REUSE",
        "second_exception": second,
        "total_historical_sink_calls": 1,
        "second_historical_sink_calls": 0,
    }


async def duplicate_concurrent_case(valid: ShadowCell) -> dict[str, object]:
    contract = compile_c2_contract(1)
    cert = _cert(contract, valid)
    hass = _hass()
    gate = HaBtCertifiedExecutionGate()

    async def worker() -> str:
        try:
            receipt = await gate.dispatch(
                hass,
                contract,
                base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
                parent_state_event=copy.deepcopy(valid.target_parent_state_event),
                historical_raw_action=copy.deepcopy(valid.historical_raw_action),
                presented_certificate=cert,
            )
            if receipt.admission_disposition is not ExecutionAdmissionDisposition.ADMIT_REUSE:
                raise AssertionError("concurrent duplicate winner did not admit")
            return "ADMIT_REUSE"
        except RuntimeError as exc:
            if "already consumed" not in str(exc):
                raise
            return "DUPLICATE_CONSUMPTION"

    results = await asyncio.gather(*(worker() for _ in range(32)))
    admitted = results.count("ADMIT_REUSE")
    duplicates = results.count("DUPLICATE_CONSUMPTION")
    if (admitted, duplicates, len(hass.services.calls)) != (1, 31, 1):
        raise AssertionError(("concurrent single-use boundary", admitted, duplicates, len(hass.services.calls)))
    return {
        "status": "PASS",
        "callers": 32,
        "admitted": admitted,
        "duplicate_rejections": duplicates,
        "total_historical_sink_calls": len(hass.services.calls),
        "event_loop_interleaving_forced_at_delegate": True,
    }


async def sink_exception_case(valid: ShadowCell) -> dict[str, object]:
    contract = compile_c2_contract(1)
    cert = _cert(contract, valid)
    hass = _hass(fail=True)
    gate = HaBtCertifiedExecutionGate()

    try:
        await gate.dispatch(
            hass,
            contract,
            base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
            parent_state_event=copy.deepcopy(valid.target_parent_state_event),
            historical_raw_action=copy.deepcopy(valid.historical_raw_action),
            presented_certificate=cert,
        )
    except Exception as exc:
        first_exception = _exception_record(exc)
    else:
        raise AssertionError("injected historical sink exception was hidden")
    if len(hass.services.calls) != 1:
        raise AssertionError(("sink exception initial attempt cardinality", len(hass.services.calls)))

    try:
        await gate.dispatch(
            hass,
            contract,
            base_raw_observation=copy.deepcopy(valid.target_base_raw_observation),
            parent_state_event=copy.deepcopy(valid.target_parent_state_event),
            historical_raw_action=copy.deepcopy(valid.historical_raw_action),
            presented_certificate=cert,
        )
    except Exception as exc:
        second_exception = _exception_record(exc)
    else:
        raise AssertionError("failed historical side effect was retried")
    if len(hass.services.calls) != 1:
        raise AssertionError("sink exception caused a second historical delegate call")

    return {
        "status": "PASS",
        "initial_historical_sink_attempts": 1,
        "initial_exception": first_exception,
        "second_dispatch_exception": second_exception,
        "certificate_consumed_before_delegate": "already consumed" in second_exception["message"],
        "retry_sink_attempts": 0,
        "native_fallback_calls": 0,
        "regeneration_calls": 0,
        "exception_propagates": True,
    }


def static_surface_case() -> dict[str, object]:
    gate_file = Path(inspect.getsourcefile(HaBtCertifiedExecutionGate) or "")
    source = gate_file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    async_call_sites = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "async_call"
    ]
    if len(async_call_sites) != 1:
        raise AssertionError(("historical sink call-site count", len(async_call_sites)))

    dispatch_node = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "dispatch"
    )
    dispatch_source = ast.get_source_segment(source, dispatch_node) or ""
    constants = {
        node.value for node in ast.walk(dispatch_node)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    if "automation" in constants or "trigger" in constants:
        raise AssertionError("gate contains a native automation trigger surface")

    signature = inspect.signature(HaBtCertifiedExecutionGate.dispatch)
    forbidden_params = {
        "fallback", "retry", "regenerate", "regeneration", "native",
        "native_fallback", "action_override", "domain_override", "service_override",
    }
    overlapping = set(signature.parameters) & forbidden_params
    if overlapping:
        raise AssertionError(("forbidden execution-surface parameters", sorted(overlapping)))

    add_lines: list[int] = []
    delegate_lines: list[int] = []
    for node in ast.walk(dispatch_node):
        if isinstance(node, ast.Call):
            segment = ast.get_source_segment(source, node) or ""
            if "_consumed_certificate_fingerprints.add" in segment:
                add_lines.append(node.lineno)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "async_call":
                delegate_lines.append(node.lineno)
    if not add_lines or len(delegate_lines) != 1 or max(add_lines) >= delegate_lines[0]:
        raise AssertionError(("certificate consumption is not structurally before delegate", add_lines, delegate_lines))

    rule = ha_bt_execution_gate_rule_record()
    if rule["fallback"] is not False or rule["retry"] is not False or rule["regeneration"] is not False:
        raise AssertionError("frozen gate rule unexpectedly exposes repair behavior")

    return {
        "status": "PASS",
        "historical_sink_call_sites": 1,
        "fallback_surface": 0,
        "retry_surface": 0,
        "regeneration_surface": 0,
        "native_automation_trigger_surface": 0,
        "caller_action_override_parameters": 0,
        "certificate_consumption_precedes_delegate_structurally": True,
        "dispatch_source_sha256": _sha256_bytes(dispatch_source.encode("utf-8")),
    }


async def qualify(fixture_path: Path) -> dict[str, object]:
    pack = _load_fixture(fixture_path)
    cells = build_shadow_cells(pack)
    valid, other_valid, invalid = _baselines(cells)

    controls = await positive_controls(valid, invalid)
    cases: dict[str, object] = {}
    cases.update(controls)
    cases["C4-A1-UNRESOLVED"] = await unresolved_case(valid)
    cases["C4-A2-MALFORMED-OBSERVATION"] = await malformed_observation_case(valid)
    cases["C4-A3-FOREIGN-ACTION"] = await foreign_action_case(valid)
    cases["C4-A4-CROSS-TASK-CERTIFICATE"] = await cross_task_certificate_case(valid, other_valid)
    cases["C4-A5-CERTIFICATE-CANONICAL-BYTE-MUTATION"] = await certificate_byte_mutation_case(valid)
    cases["C4-A6-RAW-AFTER-CERTIFICATION-MUTATION"] = await raw_after_certification_mutation_case(valid)
    cases["C4-A7-DUPLICATE-SEQUENTIAL"] = await duplicate_sequential_case(valid)
    cases["C4-A8-DUPLICATE-CONCURRENT-32"] = await duplicate_concurrent_case(valid)
    cases["C4-A9-SINK-EXCEPTION"] = await sink_exception_case(valid)
    cases["C4-A10-STATIC-SURFACE-AUDIT"] = static_surface_case()

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
    promotion = {
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
        "latency_participates_in_promotion": False,
    }
    if not all(value is True for value in promotion.values()):
        raise AssertionError(("C4 promotion criterion failed", promotion))

    return {
        "schema": SCHEMA,
        "status": "PASS",
        "headline_role": "ARTIFACT_TRUST_BOUNDARY_CLOSURE_NOT_SCIENTIFIC_HEADLINE",
        "frozen_c3_gate_blob": C3_GATE_BLOB,
        "fixture_package_sha256": FIXTURE_PACKAGE_SHA256,
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
