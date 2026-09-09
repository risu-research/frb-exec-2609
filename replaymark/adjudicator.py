from __future__ import annotations

"""Three-valued support adjudication over a frozen support envelope.

This module implements exactly one semantic step:

    (recorded action z, S_C^-(e), S_C^+(e))
        -> VALID / INVALID / UNRESOLVED

It does not decide whether to reuse, regenerate, refine evidence, or abort. Those
are policy stages and remain out of scope here.
"""

from dataclasses import dataclass
import hashlib
import json

from .contracts import ClaimSpec, ProjectedAction, Verdict
from .support_envelope import SupportEnvelope


_SCHEMA = "replaymark.adjudication.v1"


class AdjudicationError(ValueError):
    """Base class for fail-closed adjudication errors."""


class ClaimArtifactMismatchError(AdjudicationError):
    """Raised when the supplied claim is not the claim sealed into the envelope."""


class MalformedSupportEnvelopeError(AdjudicationError):
    """Raised when an envelope row violates the adjudicator's required invariants."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_row_for_claim(row, claim: ClaimSpec) -> None:
    if not row.q_blocks:
        raise MalformedSupportEnvelopeError(
            f"evidence token {row.token!r} has no predictive q blocks"
        )
    guaranteed = tuple(row.guaranteed_support)
    possible = tuple(row.possible_support)
    if not possible:
        raise MalformedSupportEnvelopeError(
            f"evidence token {row.token!r} has empty possible support"
        )
    if len(set(guaranteed)) != len(guaranteed):
        raise MalformedSupportEnvelopeError(
            f"evidence token {row.token!r} has duplicate guaranteed-support actions"
        )
    if len(set(possible)) != len(possible):
        raise MalformedSupportEnvelopeError(
            f"evidence token {row.token!r} has duplicate possible-support actions"
        )
    if not set(guaranteed).issubset(set(possible)):
        raise MalformedSupportEnvelopeError(
            f"evidence token {row.token!r} violates S^- subseteq S^+"
        )

    expected = tuple(claim.dimensions)
    for action in guaranteed + possible:
        if not isinstance(action, ProjectedAction):
            raise MalformedSupportEnvelopeError(
                f"evidence token {row.token!r} contains a non-ProjectedAction support element"
            )
        actual = tuple(key for key, _value in action.dimensions)
        if actual != expected:
            raise MalformedSupportEnvelopeError(
                f"support action dimensions {actual!r} do not match claim dimensions "
                f"{expected!r} for token {row.token!r}"
            )


@dataclass(frozen=True)
class Adjudication:
    """Auditable three-valued classification of one recorded action."""

    schema_version: str
    support_envelope_fingerprint: str
    claim_fingerprint: str
    evidence_fingerprint: str
    depth: int
    token: str
    projected_action: ProjectedAction
    in_guaranteed_support: bool
    in_possible_support: bool
    verdict: Verdict

    def __post_init__(self) -> None:
        if not isinstance(self.projected_action, ProjectedAction):
            raise TypeError("projected_action must be ProjectedAction")
        if not isinstance(self.verdict, Verdict):
            raise TypeError("verdict must be Verdict")
        expected = (
            Verdict.VALID
            if self.in_guaranteed_support
            else Verdict.UNRESOLVED
            if self.in_possible_support
            else Verdict.INVALID
        )
        if self.verdict is not expected:
            raise ValueError(
                "verdict is inconsistent with guaranteed/possible support membership"
            )
        if self.in_guaranteed_support and not self.in_possible_support:
            raise ValueError("membership invariant violated: S^- must be a subset of S^+")

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "support_envelope_fingerprint": self.support_envelope_fingerprint,
            "claim_fingerprint": self.claim_fingerprint,
            "evidence_fingerprint": self.evidence_fingerprint,
            "depth": self.depth,
            "token": self.token,
            "projected_action": self.projected_action.as_dict(),
            "in_guaranteed_support": self.in_guaranteed_support,
            "in_possible_support": self.in_possible_support,
            "verdict": self.verdict.value,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_record())

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def adjudicate_support(
    envelope: SupportEnvelope,
    claim: ClaimSpec,
    observation: str,
    recorded_action: ProjectedAction,
) -> Adjudication:
    """Return the exact support verdict for one recorded action under evidence.

    The supplied action may contain dimensions beyond the benchmark claim. The
    adjudicator projects it through the exact ClaimSpec sealed into the support
    artifact, so irrelevant adapter coordinates cannot affect the verdict.

    Semantics are exactly:

      VALID       iff z in S_C^-(e)
      INVALID     iff z notin S_C^+(e)
      UNRESOLVED  iff z in S_C^+(e) \\ S_C^-(e)
    """

    if not isinstance(envelope, SupportEnvelope):
        raise TypeError("envelope must be a SupportEnvelope")
    if not isinstance(claim, ClaimSpec):
        raise TypeError("claim must be ClaimSpec")
    if not isinstance(recorded_action, ProjectedAction):
        raise TypeError("recorded_action must be ProjectedAction")
    if not isinstance(observation, str) or not observation.strip():
        raise ValueError("observation must be a non-empty string")
    if observation != observation.strip():
        raise ValueError("observation must not contain leading/trailing whitespace")

    claim_fp = claim.fingerprint()
    if envelope.claim_fingerprint != claim_fp:
        raise ClaimArtifactMismatchError(
            "supplied ClaimSpec does not match the claim sealed into the support envelope"
        )
    if envelope.depth < 0:
        raise MalformedSupportEnvelopeError("support envelope has negative q depth")

    row = envelope.observation(observation)
    _validate_row_for_claim(row, claim)
    projected = claim.project(recorded_action)

    guaranteed = set(row.guaranteed_support)
    possible = set(row.possible_support)
    in_guaranteed = projected in guaranteed
    in_possible = projected in possible

    if in_guaranteed:
        verdict = Verdict.VALID
    elif not in_possible:
        verdict = Verdict.INVALID
    else:
        verdict = Verdict.UNRESOLVED

    return Adjudication(
        schema_version=_SCHEMA,
        support_envelope_fingerprint=envelope.fingerprint(),
        claim_fingerprint=claim_fp,
        evidence_fingerprint=envelope.evidence_fingerprint,
        depth=envelope.depth,
        token=observation,
        projected_action=projected,
        in_guaranteed_support=in_guaranteed,
        in_possible_support=in_possible,
        verdict=verdict,
    )


__all__ = (
    "Adjudication",
    "AdjudicationError",
    "ClaimArtifactMismatchError",
    "MalformedSupportEnvelopeError",
    "adjudicate_support",
)
