from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .contracts import ProjectedAction, Scalar

class RealizationStage(str, Enum):
    OBSERVATION = "OBSERVATION"
    HISTORICAL_ACTION = "HISTORICAL_ACTION"

class RealizationFailureCode(str, Enum):
    MALFORMED_INPUT = "MALFORMED_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    DUPLICATE_INPUT = "DUPLICATE_INPUT"
    CLOCK_DOMAIN_MISMATCH = "CLOCK_DOMAIN_MISMATCH"
    OUT_OF_BOUNDARY = "OUT_OF_BOUNDARY"
    AMBIGUOUS_REALIZATION = "AMBIGUOUS_REALIZATION"
    UNKNOWN_SEMANTIC_VALUE = "UNKNOWN_SEMANTIC_VALUE"
    INTERNAL_INCONSISTENCY = "INTERNAL_INCONSISTENCY"

@dataclass(frozen=True)
class RealizationFailure:
    schema_version: str
    stage: RealizationStage
    code: RealizationFailureCode
    realizer_id: str
    message: str
    raw_record_digest: str | None
    details: tuple[tuple[str, Scalar], ...] = ()

class RealizationError(ValueError):
    def __init__(self, failure: RealizationFailure):
        self.failure = failure
        super().__init__(f"{failure.stage.value}:{failure.code.value}: {failure.message}")

@dataclass(frozen=True)
class RealizationProvenance:
    stage: RealizationStage
    realizer_id: str
    realizer_semantic_digest: str
    source_schema: str
    raw_record_digest: str

@dataclass(frozen=True)
class RealizedObservation:
    evidence_token: str
    clock_domain: str
    boundary_timestamp_ns: int
    source_event_timestamp_ns: int | None
    provenance: RealizationProvenance

@dataclass(frozen=True)
class RealizedHistoricalAction:
    schema_version: str
    action: ProjectedAction
    provenance: RealizationProvenance

def observation_provenance(*, realizer_id: str, realizer_semantic_digest: str, source_schema: str, raw_record_digest: str) -> RealizationProvenance:
    return RealizationProvenance(RealizationStage.OBSERVATION, realizer_id, realizer_semantic_digest, source_schema, raw_record_digest)

def historical_action_provenance(*, realizer_id: str, realizer_semantic_digest: str, source_schema: str, raw_record_digest: str) -> RealizationProvenance:
    return RealizationProvenance(RealizationStage.HISTORICAL_ACTION, realizer_id, realizer_semantic_digest, source_schema, raw_record_digest)

def realized_observation(*, evidence_token: str, clock_domain: str, boundary_timestamp_ns: int, source_event_timestamp_ns: int | None, provenance: RealizationProvenance) -> RealizedObservation:
    return RealizedObservation(evidence_token, clock_domain, boundary_timestamp_ns, source_event_timestamp_ns, provenance)
