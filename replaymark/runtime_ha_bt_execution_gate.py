from __future__ import annotations

"""Home Assistant Better-Thermostat native execution gate for HA-C3.

The gate owns only the historical Home Assistant service sink. It reconstructs
the exact frozen C2 shadow certificate from raw runtime material, byte-compares
that certificate to the presented certificate, re-applies the existing
no-fallback admission policy, and executes the exact historical service only for
ADMIT_REUSE.

BLOCK_REUSE never enters a native path here. Caller-owned native recovery remains
outside ReplayMark. A certificate is consumed before an admitted delegate call,
so sink failure cannot cause retry or native fallback.
"""

from dataclasses import dataclass
import hashlib
import json
import time

from homeassistant.core import Context

from .compiled_contract import ExplicitCompiledContract
from .execution_admission import ExecutionAdmissionDisposition, admit_validated_runtime_certificate
from .runtime_ha_bt_action import parse_ha_bt_historical_action_record
from .runtime_ha_bt_shadow_bridge import HaBtShadowCertificate, certify_ha_bt_shadow_reuse

SCHEMA = "replaymark.runtime.ha-bt-execution-receipt.v1"
GATE_ID = "replaymark.ha-bt-certified-execution-gate.v1"
_RULE_RECORD = {
    "schema": "replaymark.runtime.ha-bt-execution-gate-semantics.v1",
    "input": "frozen C2 raw observation/event/action plus presented HaBtShadowCertificate",
    "certificate_validation": "recompute-and-exact-canonical-byte-compare",
    "admission_authority": "admit_validated_runtime_certificate",
    "admit": "execute exact historical climate.set_preset_mode once",
    "block": "zero historical service calls",
    "single_use": "certificate consumed before delegate",
    "fallback": False,
    "retry": False,
    "regeneration": False,
    "native_recovery": "caller-owned outside gate",
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


GATE_SEMANTIC_DIGEST = _sha(_canonical_json_bytes(_RULE_RECORD))


@dataclass(frozen=True)
class HaBtExecutionReceipt:
    schema_version: str
    gate_id: str
    gate_semantic_digest: str
    presented_certificate_fingerprint: str
    recomputed_certificate_fingerprint: str
    admission_disposition: ExecutionAdmissionDisposition
    execution_performed: bool
    historical_service_data: dict[str, object] | None
    historical_service_data_sha256: str | None
    dispatch_context_id: str | None
    dispatch_started_ns: int | None
    dispatch_completed_ns: int | None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA or self.gate_id != GATE_ID:
            raise ValueError("foreign HA-BT execution receipt")
        if self.gate_semantic_digest != GATE_SEMANTIC_DIGEST:
            raise ValueError("foreign HA-BT execution-gate semantics")
        if self.presented_certificate_fingerprint != self.recomputed_certificate_fingerprint:
            raise ValueError("execution receipt records certificate mismatch")
        if self.admission_disposition is ExecutionAdmissionDisposition.BLOCK_REUSE:
            if self.execution_performed:
                raise ValueError("BLOCK_REUSE cannot record historical execution")
            if any(value is not None for value in (
                self.historical_service_data,
                self.historical_service_data_sha256,
                self.dispatch_context_id,
                self.dispatch_started_ns,
                self.dispatch_completed_ns,
            )):
                raise ValueError("BLOCK_REUSE receipt contains sink material")
        else:
            if not self.execution_performed:
                raise ValueError("ADMIT_REUSE must record historical execution")
            if (
                self.historical_service_data is None
                or self.historical_service_data_sha256 is None
                or self.dispatch_context_id is None
                or self.dispatch_started_ns is None
                or self.dispatch_completed_ns is None
            ):
                raise ValueError("ADMIT_REUSE receipt lacks sink material")
            if self.dispatch_completed_ns < self.dispatch_started_ns:
                raise ValueError("historical dispatch completion precedes start")
            if _sha(_canonical_json_bytes(self.historical_service_data)) != self.historical_service_data_sha256:
                raise ValueError("historical service-data digest mismatch")

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "gate_id": self.gate_id,
            "gate_semantic_digest": self.gate_semantic_digest,
            "presented_certificate_fingerprint": self.presented_certificate_fingerprint,
            "recomputed_certificate_fingerprint": self.recomputed_certificate_fingerprint,
            "admission_disposition": self.admission_disposition.value,
            "execution_performed": self.execution_performed,
            "historical_service_data": self.historical_service_data,
            "historical_service_data_sha256": self.historical_service_data_sha256,
            "dispatch_context_id": self.dispatch_context_id,
            "dispatch_started_ns": self.dispatch_started_ns,
            "dispatch_completed_ns": self.dispatch_completed_ns,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_record())

    def fingerprint(self) -> str:
        return _sha(self.canonical_bytes())


class HaBtCertifiedExecutionGate:
    """Single-use validating owner of the historical HA service sink."""

    def __init__(self) -> None:
        self._consumed_certificate_fingerprints: set[str] = set()

    async def dispatch(
        self,
        hass: object,
        contract: ExplicitCompiledContract,
        *,
        base_raw_observation: object,
        parent_state_event: object,
        historical_raw_action: object,
        presented_certificate: HaBtShadowCertificate,
    ) -> HaBtExecutionReceipt:
        if not isinstance(contract, ExplicitCompiledContract):
            raise TypeError("contract must be ExplicitCompiledContract")
        if not isinstance(presented_certificate, HaBtShadowCertificate):
            raise TypeError("presented_certificate must be HaBtShadowCertificate")

        recomputed = certify_ha_bt_shadow_reuse(
            contract,
            base_raw_observation=base_raw_observation,
            parent_state_event=parent_state_event,
            historical_raw_action=historical_raw_action,
        )
        if recomputed.canonical_bytes() != presented_certificate.canonical_bytes():
            raise ValueError("presented HA-BT certificate differs from raw-material recomputation")
        if recomputed.fingerprint() != presented_certificate.fingerprint():
            raise ValueError("presented HA-BT certificate fingerprint mismatch")

        admission = admit_validated_runtime_certificate(presented_certificate.runtime_certificate)
        if admission.canonical_bytes() != presented_certificate.admission.canonical_bytes():
            raise ValueError("presented HA-BT admission differs from frozen admission policy")

        cert_fp = presented_certificate.fingerprint()
        if cert_fp in self._consumed_certificate_fingerprints:
            raise RuntimeError("HA-BT runtime certificate already consumed")

        if admission.disposition is ExecutionAdmissionDisposition.BLOCK_REUSE:
            self._consumed_certificate_fingerprints.add(cert_fp)
            return HaBtExecutionReceipt(
                schema_version=SCHEMA,
                gate_id=GATE_ID,
                gate_semantic_digest=GATE_SEMANTIC_DIGEST,
                presented_certificate_fingerprint=cert_fp,
                recomputed_certificate_fingerprint=recomputed.fingerprint(),
                admission_disposition=admission.disposition,
                execution_performed=False,
                historical_service_data=None,
                historical_service_data_sha256=None,
                dispatch_context_id=None,
                dispatch_started_ns=None,
                dispatch_completed_ns=None,
            )

        record = parse_ha_bt_historical_action_record(historical_raw_action)
        service_data = dict(record.canonical_record()["service_event"]["service_data"])

        # Consume before crossing the external service boundary. A delegate
        # exception can therefore neither be retried nor converted to native
        # fallback by this gate.
        self._consumed_certificate_fingerprints.add(cert_fp)
        context = Context()
        started = time.perf_counter_ns()
        await hass.services.async_call(
            record.domain,
            record.service,
            service_data,
            blocking=True,
            context=context,
        )
        completed = time.perf_counter_ns()
        return HaBtExecutionReceipt(
            schema_version=SCHEMA,
            gate_id=GATE_ID,
            gate_semantic_digest=GATE_SEMANTIC_DIGEST,
            presented_certificate_fingerprint=cert_fp,
            recomputed_certificate_fingerprint=recomputed.fingerprint(),
            admission_disposition=admission.disposition,
            execution_performed=True,
            historical_service_data=service_data,
            historical_service_data_sha256=_sha(_canonical_json_bytes(service_data)),
            dispatch_context_id=str(context.id),
            dispatch_started_ns=started,
            dispatch_completed_ns=completed,
        )


def ha_bt_execution_gate_rule_record() -> dict[str, object]:
    return json.loads(_canonical_json_bytes(_RULE_RECORD).decode("utf-8"))


__all__ = (
    "GATE_ID",
    "GATE_SEMANTIC_DIGEST",
    "HaBtCertifiedExecutionGate",
    "HaBtExecutionReceipt",
    "ha_bt_execution_gate_rule_record",
)
