from __future__ import annotations

"""Strict H=0 runtime view over already-sealed VE2 compiled-contract exports.

This module never invokes the ReplayMark compiler. It verifies the exact export
bytes and immutable manifest relationship, then exposes only support-membership
adjudication needed by the execution gate. It knows no Old/New compatibility
labels, class weights, expected frontiers, source diffs, or scientific outcome.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

CONTRACT_SCHEMA = "replaymark.compiled-contract.explicit.v1"
COMPILER_ID = "replaymark.reference-packager.explicit.v1"
CERT_SCHEMA = "replaymark.ve2.scientific-reuse-certificate.v1"
DIMENSIONS = ("concrete_target", "operation", "variant")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_token(fixture: dict[str, Any]) -> str:
    if not isinstance(fixture, dict):
        raise ValueError("fixture-not-mapping")
    return canonical_bytes(fixture).decode("utf-8")


def _action_key(value: dict[str, Any]) -> bytes:
    if not isinstance(value, dict) or set(value) != set(DIMENSIONS):
        raise ValueError("projected-action-shape")
    if not all(isinstance(value[key], str) and value[key] for key in DIMENSIONS):
        raise ValueError("projected-action-value")
    return canonical_bytes({key: value[key] for key in DIMENSIONS})


def _check_fp(value: dict[str, Any], key: str) -> None:
    fp = value.get(key)
    if not isinstance(fp, str) or len(fp) != 64:
        raise ValueError("fingerprint:" + key)


@dataclass(frozen=True)
class StrictContractView:
    contract_sha256: str
    contract_fingerprint: str
    claim_fingerprint: str
    support_envelope_fingerprint: str
    quotient_fingerprint: str
    manifest_state_ids: tuple[str, ...]
    support_by_token: dict[str, tuple[frozenset[bytes], frozenset[bytes]]]

    def certificate(self, fixture: dict[str, Any], behavior: dict[str, Any]) -> dict[str, Any]:
        token = evidence_token(fixture)
        if token not in self.support_by_token:
            raise ValueError("observation-outside-sealed-contract")
        if not isinstance(behavior, dict):
            raise ValueError("behavior-not-mapping")
        if behavior.get("schema") != "replaymark.ve2.historical-behavior-capsule.v1":
            raise ValueError("behavior-schema")
        supplied = behavior.get("fingerprint")
        body = dict(behavior)
        body.pop("fingerprint", None)
        if supplied != digest(body):
            raise ValueError("behavior-fingerprint")
        projected = behavior.get("projected_action")
        key = _action_key(projected)
        guaranteed, possible = self.support_by_token[token]
        in_guaranteed = key in guaranteed
        in_possible = key in possible
        if in_guaranteed:
            verdict = "VALID"
            admission = "ADMIT_REUSE"
        elif not in_possible:
            verdict = "INVALID"
            admission = "BLOCK_REUSE"
        else:
            verdict = "UNRESOLVED"
            admission = "BLOCK_REUSE"
        value = {
            "schema": CERT_SCHEMA,
            "contract_raw_sha256": self.contract_sha256,
            "contract_fingerprint": self.contract_fingerprint,
            "claim_fingerprint": self.claim_fingerprint,
            "support_envelope_fingerprint": self.support_envelope_fingerprint,
            "quotient_fingerprint": self.quotient_fingerprint,
            "evidence_token": token,
            "behavior_fingerprint": supplied,
            "historical_projected_action": projected,
            "guaranteed_support_member": in_guaranteed,
            "possible_support_member": in_possible,
            "semantic_verdict": verdict,
            "admission": admission,
            "execution_performed": False,
            "fallback": False,
            "retry": False,
            "regeneration": False,
        }
        value["fingerprint"] = digest(value)
        return value

    def verify_presented_certificate(
        self,
        fixture: dict[str, Any],
        behavior: dict[str, Any],
        presented: dict[str, Any],
    ) -> dict[str, Any]:
        recomputed = self.certificate(fixture, behavior)
        if canonical_bytes(recomputed) != canonical_bytes(presented):
            raise RuntimeError("presented-certificate-does-not-match-independent-recomputation")
        return recomputed


def load_strict_contract(
    contract_path: str | Path,
    manifest_path: str | Path,
    *,
    expected_raw_sha256: str,
    expected_contract_fingerprint: str,
) -> StrictContractView:
    contract_path = Path(contract_path)
    manifest_path = Path(manifest_path)
    if raw_sha256(contract_path) != expected_raw_sha256:
        raise ValueError("contract-raw-sha256")
    contract = json.loads(contract_path.read_bytes())
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError("contract-schema")
    if contract.get("compiler_id") != COMPILER_ID:
        raise ValueError("contract-compiler-id")
    if digest(contract) != expected_contract_fingerprint:
        raise ValueError("contract-canonical-fingerprint")

    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("contract-artifacts")
    quotient = artifacts.get("bounded_quotient")
    evidence_image = artifacts.get("evidence_image")
    evidence_semantics = artifacts.get("evidence_semantics")
    envelope = artifacts.get("support_envelope")
    if not all(isinstance(x, dict) for x in (quotient, evidence_image, evidence_semantics, envelope)):
        raise ValueError("contract-required-artifact")

    claim = quotient.get("claim")
    if not isinstance(claim, dict):
        raise ValueError("claim")
    if claim.get("horizon") != 0 or quotient.get("horizon") != 0 or envelope.get("depth") != 0:
        raise ValueError("nonzero-horizon")
    if tuple(claim.get("dimensions") or ()) != DIMENSIONS:
        raise ValueError("claim-dimensions")
    if quotient.get("continuation_alphabet") != []:
        raise ValueError("nonempty-continuation-alphabet")

    manifest = contract.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("contract-manifest")
    for key in (
        "claim_fingerprint",
        "support_envelope_fingerprint",
        "quotient_fingerprint",
        "evidence_relation_fingerprint",
        "evidence_semantics_fingerprint",
    ):
        _check_fp(manifest, key)
    if envelope.get("claim_fingerprint") != manifest["claim_fingerprint"]:
        raise ValueError("envelope-claim-binding")
    if envelope.get("quotient_fingerprint") != manifest["quotient_fingerprint"]:
        raise ValueError("envelope-quotient-binding")
    if evidence_image.get("claim_fingerprint") != manifest["claim_fingerprint"]:
        raise ValueError("evidence-image-claim-binding")
    if evidence_semantics.get("relation_fingerprint") != manifest["evidence_relation_fingerprint"]:
        raise ValueError("evidence-relation-binding")

    runtime_manifest = json.loads(manifest_path.read_bytes())
    states = runtime_manifest.get("states")
    if not isinstance(states, list) or runtime_manifest.get("state_count") != len(states):
        raise ValueError("runtime-manifest-state-count")
    forbidden = set(runtime_manifest.get("forbidden_runtime_fields") or [])
    serialized_manifest = canonical_bytes(runtime_manifest).decode("utf-8")
    for word in forbidden:
        if isinstance(word, str) and word and word in serialized_manifest and word not in serialized_manifest.split('"forbidden_runtime_fields"',1)[1]:
            raise ValueError("runtime-manifest-forbidden-payload")

    expected_ids: list[str] = []
    token_to_id: dict[str, str] = {}
    for row in states:
        if not isinstance(row, dict) or set(row) != {"opaque_state_id", "fixture"}:
            raise ValueError("runtime-manifest-row-shape")
        sid = row["opaque_state_id"]
        fixture = row["fixture"]
        if not isinstance(sid, str) or not sid:
            raise ValueError("runtime-state-id")
        token = evidence_token(fixture)
        if token in token_to_id:
            raise ValueError("duplicate-runtime-evidence-token")
        expected_ids.append(sid)
        token_to_id[token] = sid

    decision_states = quotient.get("decision_states")
    if not isinstance(decision_states, list) or set(decision_states) != set(expected_ids):
        raise ValueError("decision-state-manifest-mismatch")
    observations = envelope.get("observations")
    if not isinstance(observations, list):
        raise ValueError("support-observations")
    support_by_token: dict[str, tuple[frozenset[bytes], frozenset[bytes]]] = {}
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("support-observation-row")
        token = row.get("token")
        if token not in token_to_id:
            raise ValueError("support-token-not-in-runtime-manifest")
        guaranteed_raw = row.get("guaranteed_support")
        possible_raw = row.get("possible_support")
        q_blocks = row.get("q_blocks")
        if not isinstance(guaranteed_raw, list) or not isinstance(possible_raw, list) or not isinstance(q_blocks, list) or not q_blocks:
            raise ValueError("support-row-shape")
        guaranteed = frozenset(_action_key(x) for x in guaranteed_raw)
        possible = frozenset(_action_key(x) for x in possible_raw)
        if not guaranteed <= possible or not possible:
            raise ValueError("support-envelope-order")
        support_by_token[token] = (guaranteed, possible)
    if set(support_by_token) != set(token_to_id):
        raise ValueError("support-runtime-token-population")

    image_rows = evidence_image.get("observations")
    derived = (evidence_semantics.get("derived_evidence_spec") or {}).get("observations")
    if not isinstance(image_rows, list) or not isinstance(derived, list):
        raise ValueError("evidence-observation-shape")
    image_map = {row.get("token"): tuple(row.get("compatible_states") or []) for row in image_rows}
    derived_map = {row.get("token"): tuple(row.get("compatible_states") or []) for row in derived}
    if set(image_map) != set(token_to_id) or set(derived_map) != set(token_to_id):
        raise ValueError("evidence-token-population")
    for token, sid in token_to_id.items():
        if image_map[token] != (sid,) or derived_map[token] != (sid,):
            raise ValueError("evidence-token-state-binding")

    return StrictContractView(
        contract_sha256=expected_raw_sha256,
        contract_fingerprint=expected_contract_fingerprint,
        claim_fingerprint=manifest["claim_fingerprint"],
        support_envelope_fingerprint=manifest["support_envelope_fingerprint"],
        quotient_fingerprint=manifest["quotient_fingerprint"],
        manifest_state_ids=tuple(expected_ids),
        support_by_token=support_by_token,
    )
