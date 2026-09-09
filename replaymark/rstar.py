from __future__ import annotations

"""The theorem-induced maximal certified reuse rule R*.

This module implements exactly one binary semantic consequence of a frozen
three-valued adjudication:

    VALID       -> REUSE
    INVALID     -> DO_NOT_REUSE
    UNRESOLVED  -> DO_NOT_REUSE

`DO_NOT_REUSE` is intentionally *not* a regeneration command. It says only that
historical reuse is not certified by the current fixed evidence. What happens
next (regenerate, refine evidence, abort, etc.) is an execution policy and remains
outside this module.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .adjudicator import Adjudication
from .contracts import ProjectedAction, Verdict


_SCHEMA = "replaymark.rstar.maximal-certified-reuse.v1"


class ReuseDisposition(str, Enum):
    """Binary theorem domain for fixed-evidence historical reuse entitlement."""

    REUSE = "REUSE"
    DO_NOT_REUSE = "DO_NOT_REUSE"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class RStarDecision:
    """Auditable maximal-certified-reuse decision derived from adjudication.

    The decision intentionally preserves the three-valued verdict even though
    R* collapses INVALID and UNRESOLVED to the same binary reuse disposition.
    This prevents later execution policy from losing why reuse was not certified.
    """

    schema_version: str
    adjudication_fingerprint: str
    support_envelope_fingerprint: str
    claim_fingerprint: str
    evidence_fingerprint: str
    depth: int
    token: str
    projected_action: ProjectedAction
    verdict: Verdict
    disposition: ReuseDisposition

    def __post_init__(self) -> None:
        if not isinstance(self.projected_action, ProjectedAction):
            raise TypeError("projected_action must be ProjectedAction")
        if not isinstance(self.verdict, Verdict):
            raise TypeError("verdict must be Verdict")
        if not isinstance(self.disposition, ReuseDisposition):
            raise TypeError("disposition must be ReuseDisposition")
        if isinstance(self.depth, bool) or not isinstance(self.depth, int):
            raise TypeError("depth must be an integer")
        if self.depth < 0:
            raise ValueError("depth must be >= 0")
        for name, value in (
            ("adjudication_fingerprint", self.adjudication_fingerprint),
            ("support_envelope_fingerprint", self.support_envelope_fingerprint),
            ("claim_fingerprint", self.claim_fingerprint),
            ("evidence_fingerprint", self.evidence_fingerprint),
            ("token", self.token),
        ):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty canonical token")

        expected = (
            ReuseDisposition.REUSE
            if self.verdict is Verdict.VALID
            else ReuseDisposition.DO_NOT_REUSE
        )
        if self.disposition is not expected:
            raise ValueError(
                "R* disposition is inconsistent with the fixed-evidence theorem: "
                "REUSE iff verdict is VALID"
            )

    @property
    def reuse_certified(self) -> bool:
        """Whether fixed-evidence support soundness certifies historical reuse."""

        return self.disposition is ReuseDisposition.REUSE

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "adjudication_fingerprint": self.adjudication_fingerprint,
            "support_envelope_fingerprint": self.support_envelope_fingerprint,
            "claim_fingerprint": self.claim_fingerprint,
            "evidence_fingerprint": self.evidence_fingerprint,
            "depth": self.depth,
            "token": self.token,
            "projected_action": self.projected_action.as_dict(),
            "verdict": self.verdict.value,
            "disposition": self.disposition.value,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.canonical_record())

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def maximal_certified_reuse(adjudication: Adjudication) -> RStarDecision:
    """Return R*(e,z): REUSE iff the adjudicated action is VALID.

    This is the unique pointwise-maximal choice among fixed-evidence binary
    policies ordered DO_NOT_REUSE < REUSE subject to support soundness. No
    fallback action is selected here.
    """

    if not isinstance(adjudication, Adjudication):
        raise TypeError("adjudication must be an Adjudication")

    disposition = (
        ReuseDisposition.REUSE
        if adjudication.verdict is Verdict.VALID
        else ReuseDisposition.DO_NOT_REUSE
    )

    return RStarDecision(
        schema_version=_SCHEMA,
        adjudication_fingerprint=adjudication.fingerprint(),
        support_envelope_fingerprint=adjudication.support_envelope_fingerprint,
        claim_fingerprint=adjudication.claim_fingerprint,
        evidence_fingerprint=adjudication.evidence_fingerprint,
        depth=adjudication.depth,
        token=adjudication.token,
        projected_action=adjudication.projected_action,
        verdict=adjudication.verdict,
        disposition=disposition,
    )


__all__ = (
    "RStarDecision",
    "ReuseDisposition",
    "maximal_certified_reuse",
)
