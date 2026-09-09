from __future__ import annotations

"""Shadow-only HA-BT bridge from C1-qualified material to frozen ReplayMark semantics.

No Home Assistant service sink, retry, regeneration, or fallback exists here.
The module reconstructs the pre-service evidence boundary mechanically, invokes
the frozen C1 realizers, delegates semantic judgment to ExplicitCompiledContract,
and maps the validated certificate through the already-frozen admission policy.
"""

from dataclasses import dataclass
import hashlib
import json

from .compiled_contract import ExplicitCompiledContract
from .execution_admission import CertifiedExecutionAdmission, admit_validated_runtime_certificate
from .runtime_contract_identity import verified_runtime_contract_identity
from .runtime_ha_bt_action import realize_ha_bt_historical_action
from .runtime_ha_bt_decision_boundary import HaBtDecisionBoundary, reconstruct_ha_bt_pre_service_boundary
from .runtime_ha_bt_observation import realize_ha_bt_observation
from .runtime_realization import RealizedHistoricalAction, RealizedObservation, RuntimeReuseCertificate

SCHEMA = "replaymark.runtime.ha-bt-shadow-certificate.v1"
BRIDGE_ID = "replaymark.ha-bt-shadow-semantic-bridge.v1"
_RUNTIME_CERT_SCHEMA = "replaymark.runtime.reuse-certificate.v1"
_RULE_RECORD = {
    "schema": "replaymark.runtime.ha-bt-shadow-bridge-semantics.v1",
    "input": "C1-qualified HA-BT raw observation/action plus retained parent state event",
    "boundary_reconstruction": "mechanical single-event application only",
    "semantic_authority": "ExplicitCompiledContract",
    "admission_authority": "admit_validated_runtime_certificate",
    "execution": False,
    "historical_sink": False,
    "fallback": False,
    "retry": False,
    "regeneration": False,
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


BRIDGE_SEMANTIC_DIGEST = _sha(_canonical_json_bytes(_RULE_RECORD))


@dataclass(frozen=True)
class HaBtShadowCertificate:
    schema_version: str
    bridge_id: str
    bridge_semantic_digest: str
    contract_fingerprint: str
    claim_fingerprint: str
    boundary: HaBtDecisionBoundary
    observation: RealizedObservation
    historical_action: RealizedHistoricalAction
    runtime_certificate: RuntimeReuseCertificate
    admission: CertifiedExecutionAdmission
    execution_performed: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA or self.bridge_id != BRIDGE_ID:
            raise ValueError("foreign HA-BT shadow certificate")
        if self.bridge_semantic_digest != BRIDGE_SEMANTIC_DIGEST:
            raise ValueError("foreign HA-BT shadow bridge semantics")
        if self.execution_performed:
            raise ValueError("HA-C2 is shadow-only")
        if self.runtime_certificate.contract_fingerprint != self.contract_fingerprint:
            raise ValueError("runtime certificate contract mismatch")
        if self.runtime_certificate.claim_fingerprint != self.claim_fingerprint:
            raise ValueError("runtime certificate claim mismatch")
        if self.runtime_certificate.observation.fingerprint() != self.observation.fingerprint():
            raise ValueError("runtime certificate observation mismatch")
        if self.runtime_certificate.historical_action.fingerprint() != self.historical_action.fingerprint():
            raise ValueError("runtime certificate historical-action mismatch")
        if self.admission.runtime_certificate_fingerprint != self.runtime_certificate.fingerprint():
            raise ValueError("shadow admission is not bound to runtime certificate")

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "bridge_id": self.bridge_id,
            "bridge_semantic_digest": self.bridge_semantic_digest,
            "contract_fingerprint": self.contract_fingerprint,
            "claim_fingerprint": self.claim_fingerprint,
            "boundary": self.boundary.canonical_record(),
            "observation": self.observation.canonical_record(),
            "historical_action": self.historical_action.canonical_record(),
            "runtime_certificate": self.runtime_certificate.canonical_record(),
            "admission": self.admission.canonical_record(),
            "execution_performed": self.execution_performed,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_record())

    def fingerprint(self) -> str:
        return _sha(self.canonical_bytes())


def certify_ha_bt_shadow_reuse(
    contract: ExplicitCompiledContract,
    *,
    base_raw_observation: object,
    parent_state_event: object,
    historical_raw_action: object,
) -> HaBtShadowCertificate:
    if not isinstance(contract, ExplicitCompiledContract):
        raise TypeError("contract must be ExplicitCompiledContract")

    boundary = reconstruct_ha_bt_pre_service_boundary(base_raw_observation, parent_state_event)
    observation = realize_ha_bt_observation(boundary.reconstructed_raw_observation)
    historical_action = realize_ha_bt_historical_action(historical_raw_action)

    identity = verified_runtime_contract_identity(contract)
    adjudication = contract.adjudicate(observation.evidence_token, historical_action.action)
    reuse_decision = contract.certify_reuse(observation.evidence_token, historical_action.action)
    runtime = RuntimeReuseCertificate(
        schema_version=_RUNTIME_CERT_SCHEMA,
        contract_fingerprint=identity.contract_fingerprint,
        claim_fingerprint=identity.claim_fingerprint,
        observation=observation,
        historical_action=historical_action,
        adjudication=adjudication,
        reuse_decision=reuse_decision,
    )
    admission = admit_validated_runtime_certificate(runtime)
    return HaBtShadowCertificate(
        schema_version=SCHEMA,
        bridge_id=BRIDGE_ID,
        bridge_semantic_digest=BRIDGE_SEMANTIC_DIGEST,
        contract_fingerprint=identity.contract_fingerprint,
        claim_fingerprint=identity.claim_fingerprint,
        boundary=boundary,
        observation=observation,
        historical_action=historical_action,
        runtime_certificate=runtime,
        admission=admission,
        execution_performed=False,
    )


def ha_bt_shadow_bridge_rule_record() -> dict[str, object]:
    return json.loads(_canonical_json_bytes(_RULE_RECORD).decode("utf-8"))


__all__ = (
    "BRIDGE_ID",
    "BRIDGE_SEMANTIC_DIGEST",
    "HaBtShadowCertificate",
    "certify_ha_bt_shadow_reuse",
    "ha_bt_shadow_bridge_rule_record",
)
