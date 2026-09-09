from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from fractions import Fraction
from typing import Mapping, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from .adjudicator import Adjudication
    from .predictive_witness import PredictiveContinuationWitness
    from .rstar import RStarDecision


Scalar = str | int | bool | None


def _require_token(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{name} must not contain leading/trailing whitespace")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ProjectedAction:
    """Canonical, hashable action coordinates.

    The action is substrate-neutral. Adapters name dimensions; a ClaimSpec
    selects which dimensions are consequential. Missing dimensions are never
    guessed: projecting onto an absent dimension fails closed.
    """

    dimensions: tuple[tuple[str, Scalar], ...]

    def __post_init__(self) -> None:
        normalized: list[tuple[str, Scalar]] = []
        seen: set[str] = set()
        for key, value in self.dimensions:
            key = _require_token("action dimension", key)
            if key in seen:
                raise ValueError(f"duplicate action dimension: {key!r}")
            if isinstance(value, float):
                raise TypeError("action dimensions do not accept float values")
            if not (value is None or isinstance(value, (str, int, bool))):
                raise TypeError(
                    f"unsupported action dimension value for {key!r}: "
                    f"{type(value).__name__}"
                )
            seen.add(key)
            normalized.append((key, value))
        if not normalized:
            raise ValueError("ProjectedAction requires at least one dimension")
        object.__setattr__(self, "dimensions", tuple(sorted(normalized)))

    @classmethod
    def from_mapping(cls, dimensions: Mapping[str, Scalar]) -> "ProjectedAction":
        return cls(tuple(dimensions.items()))

    def as_dict(self) -> dict[str, Scalar]:
        return dict(self.dimensions)

    def project(self, dimension_names: tuple[str, ...]) -> "ProjectedAction":
        requested = tuple(_require_token("claim dimension", x) for x in dimension_names)
        if len(set(requested)) != len(requested):
            raise ValueError("claim projection contains duplicate dimensions")
        available = self.as_dict()
        missing = [name for name in requested if name not in available]
        if missing:
            raise KeyError(
                "action is missing claim-required dimensions: "
                + ", ".join(repr(x) for x in missing)
            )
        return ProjectedAction(tuple((name, available[name]) for name in requested))

    def canonical_key(self) -> tuple[tuple[str, Scalar], ...]:
        return self.dimensions


@dataclass(frozen=True)
class ClaimSpec:
    """Normative benchmark claim boundary.

    `dimensions` declares which adapter-supplied action coordinates count as
    consequential. `horizon` is claim-bound and must not be tuned post outcome.
    """

    claim_id: str
    dimensions: tuple[str, ...]
    horizon: int
    consequence_endpoint: str

    def __post_init__(self) -> None:
        _require_token("claim_id", self.claim_id)
        _require_token("consequence_endpoint", self.consequence_endpoint)
        normalized = tuple(
            sorted(_require_token("claim dimension", x) for x in self.dimensions)
        )
        if not normalized:
            raise ValueError("ClaimSpec requires at least one consequential dimension")
        if len(set(normalized)) != len(normalized):
            raise ValueError("ClaimSpec dimensions must be unique")
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise TypeError("ClaimSpec.horizon must be an integer")
        if self.horizon < 0:
            raise ValueError("ClaimSpec.horizon must be >= 0")
        object.__setattr__(self, "dimensions", normalized)

    def project(self, action: ProjectedAction) -> ProjectedAction:
        return action.project(self.dimensions)

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": "replaymark.claim.v1",
            "claim_id": self.claim_id,
            "dimensions": list(self.dimensions),
            "horizon": self.horizon,
            "consequence_endpoint": self.consequence_endpoint,
        }

    def fingerprint(self) -> str:
        return _sha256_json(self.canonical_record())


@dataclass(frozen=True)
class EvidenceSpec:
    """Finite, explicit evidence semantics for replay-time uncertainty.

    Each observation token denotes exactly the target *decision states or
    histories* still compatible with retained evidence. Tokens may overlap.
    Unknown observations are not assigned a meaning and therefore fail closed.

    Production authoring no longer constructs this inverse map by hand. The
    compiler derives it from a forward ObservationSupportModel; EvidenceSpec is
    retained as the canonical low-level extensional IR used by the mathematics
    and independent definition oracles.
    """

    evidence_id: str
    observations: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        _require_token("evidence_id", self.evidence_id)
        normalized: list[tuple[str, tuple[str, ...]]] = []
        seen_tokens: set[str] = set()
        for token, states in self.observations:
            token = _require_token("evidence token", token)
            if token in seen_tokens:
                raise ValueError(f"duplicate evidence token: {token!r}")
            clean_states = tuple(sorted({_require_token("decision state id", s) for s in states}))
            if not clean_states:
                raise ValueError(f"evidence token {token!r} has no compatible states")
            seen_tokens.add(token)
            normalized.append((token, clean_states))
        if not normalized:
            raise ValueError("EvidenceSpec requires at least one observation token")
        object.__setattr__(self, "observations", tuple(sorted(normalized)))

    def compatible_states(self, observation: str) -> tuple[str, ...]:
        observation = _require_token("observation", observation)
        by_token = dict(self.observations)
        if observation not in by_token:
            raise KeyError(f"unknown evidence observation: {observation!r}")
        return by_token[observation]

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": "replaymark.evidence.v1",
            "evidence_id": self.evidence_id,
            "observations": [
                {"token": token, "compatible_states": list(states)}
                for token, states in self.observations
            ],
        }

    def fingerprint(self) -> str:
        return _sha256_json(self.canonical_record())


class Verdict(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNRESOLVED = "UNRESOLVED"


@runtime_checkable
class TargetModel(Protocol):
    """Claim-independent two-phase reactive target semantics.

    ReplayMark's predictive object is a *decision condition/history*: a point
    immediately before the controller emits the current claim-relevant action.
    The model therefore separates the current controller decision from the next
    admitted environmental continuation:

      decision_state --current_distribution--> (action, post_state)
      post_state --advance_distribution(continuation)--> next decision_state

    This separation is essential. It represents both controllers whose current
    feedback is part of the decision condition (e.g. E3b) and controllers whose
    current state already contains the feedback variables (e.g. the thermostat)
    without smuggling a future input into the current output definition.

    Probabilities are exact Fractions at the boundary. The first bounded
    q_{C,H} compiler intentionally accepts only deterministic point-mass models;
    stochastic models remain representable here for a future, separately proved
    compiler rather than being silently given probabilistic-bisimulation
    semantics.
    """

    @property
    def fingerprint(self) -> str: ...

    @property
    def decision_states(self) -> tuple[str, ...]: ...

    @property
    def continuation_alphabet(self) -> tuple[str, ...]: ...

    def current_distribution(
        self,
        decision_state: str,
    ) -> Mapping[tuple[ProjectedAction, str], Fraction]:
        """Exact mass over (full action coordinates, post-decision state)."""
        ...

    def advance_distribution(
        self,
        post_state: str,
        continuation: str,
    ) -> Mapping[str, Fraction]:
        """Exact mass over the next decision states after one continuation."""
        ...


@runtime_checkable
class CompiledContract(Protocol):
    """Frozen semantic boundary of a compiled ReplayMark contract.

    This protocol deliberately exposes *certificates and semantic provenance*,
    not an execution policy or storage layout. A concrete bitset, BDD, table, or
    other verified backend may implement the contract, but all implementations
    must be observationally equivalent at this boundary.

    Inputs named `observation_token` are already-canonical retained-evidence
    tokens. Raw sensor/event canonicalization is outside this contract. Likewise,
    a REUSE result certifies historical *projected-decision reuse* under the
    declared claim/evidence model; it does not execute the historical action or
    choose a fallback for DO_NOT_REUSE.
    """

    @property
    def schema_version(self) -> str: ...

    @property
    def compiler_id(self) -> str: ...

    def canonical_bytes(self) -> bytes: ...

    def fingerprint(self) -> str: ...

    @property
    def claim(self) -> ClaimSpec: ...

    @property
    def claim_fingerprint(self) -> str: ...

    @property
    def target_provider_fingerprint(self) -> str: ...

    @property
    def target_semantic_digest(self) -> str: ...

    @property
    def target_snapshot_fingerprint(self) -> str: ...

    @property
    def evidence_semantics_fingerprint(self) -> str: ...

    @property
    def evidence_relation_fingerprint(self) -> str: ...

    @property
    def quotient_fingerprint(self) -> str: ...

    @property
    def support_envelope_fingerprint(self) -> str: ...

    @property
    def predictive_witness_index_fingerprint(self) -> str: ...

    def compatible_worlds(self, observation_token: str) -> tuple[str, ...]: ...

    def adjudicate(
        self,
        observation_token: str,
        historical_action: ProjectedAction,
    ) -> Adjudication: ...

    def certify_reuse(
        self,
        observation_token: str,
        historical_action: ProjectedAction,
    ) -> RStarDecision: ...

    def reuse_counterexample_world(
        self,
        observation_token: str,
        historical_action: ProjectedAction,
    ) -> str | None: ...

    def predictive_witness(
        self,
        left_world: str,
        right_world: str,
    ) -> PredictiveContinuationWitness | None: ...


__all__ = (
    "ClaimSpec",
    "TargetModel",
    "EvidenceSpec",
    "ProjectedAction",
    "CompiledContract",
    "Verdict",
)
