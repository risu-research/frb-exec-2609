from __future__ import annotations

"""Verification/offline native-action lift of the already-frozen Better Thermostat model.

This module is not a Home Assistant runtime adapter. It preserves the frozen
32-state controller law and continuation system while expressing each current
decision at the exact C0 Home Assistant action-instance boundary.
"""

from fractions import Fraction
import hashlib
import json
from typing import Mapping

from replaymark.compiled_contract import ExplicitCompiledContract, compile_explicit_contract
from replaymark.contracts import ClaimSpec, ProjectedAction
from replaymark.q_compiler import compile_bounded_q
from replaymark_verification.models import BetterThermostatFrozenModel

CLIMATE_ENTITY = "climate.agentmark_thermostat"
CONTINUATIONS = ("presence_toggle", "motion_toggle", "night_toggle", "tick")
PRESETS = ("away", "home", "comfort", "sleep")
CLAIM_DIMENSIONS = ("operation", "concrete_target", "variant")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _hash_record(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def encode_state(presence: bool, motion: bool, night: bool, preset: str) -> str:
    if preset not in PRESETS:
        raise ValueError(preset)
    return json.dumps([presence, motion, night, preset], separators=(",", ":")).lower()


def parse_state(value: str) -> tuple[bool, bool, bool, str]:
    raw = json.loads(value)
    if not isinstance(raw, list) or len(raw) != 4:
        raise KeyError(value)
    p, m, n, preset = raw
    if not isinstance(p, bool) or not isinstance(m, bool) or not isinstance(n, bool):
        raise KeyError(value)
    if preset not in PRESETS:
        raise KeyError(value)
    return p, m, n, preset


def target_preset(state: tuple[bool, bool, bool, str]) -> str:
    presence, motion, night, _preset = state
    if night:
        return "sleep"
    if not presence:
        return "away"
    if motion:
        return "comfort"
    return "home"


def native_action_for_state(state: tuple[bool, bool, bool, str]) -> ProjectedAction:
    desired = target_preset(state)
    current = state[3]
    if current == desired:
        return ProjectedAction.from_mapping({
            "operation": "NO_ACTION",
            "target_class": "climate",
            "concrete_target": CLIMATE_ENTITY,
            "variant": "NO_ACTION",
            "service_domain": "climate",
            "service_name": "NO_ACTION",
            "preset_mode": current,
        })
    return ProjectedAction.from_mapping({
        "operation": "climate.set_preset_mode",
        "target_class": "climate",
        "concrete_target": CLIMATE_ENTITY,
        "variant": json.dumps({"preset_mode": desired}, sort_keys=True, separators=(",", ":")),
        "service_domain": "climate",
        "service_name": "set_preset_mode",
        "preset_mode": desired,
    })


class HaC2BetterThermostatNativeTarget:
    """Exact native-action lift of the frozen deterministic thermostat semantics."""

    def __init__(self) -> None:
        self._decision_states = tuple(sorted(
            encode_state(p, m, n, preset)
            for p in (False, True)
            for m in (False, True)
            for n in (False, True)
            for preset in PRESETS
        ))
        self._state_set = set(self._decision_states)
        self._fingerprint = _hash_record({
            "schema": "replaymark.verify.ha-c2-bt-native-target.v1",
            "base_model": "BetterThermostatFrozenModel",
            "state_domain": list(self._decision_states),
            "continuations": list(CONTINUATIONS),
            "claim_action_boundary": list(CLAIM_DIMENSIONS),
            "target": CLIMATE_ENTITY,
            "law": "night?sleep:!presence?away:motion?comfort:home; no-action-if-at-target",
        })

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def decision_states(self) -> tuple[str, ...]:
        return self._decision_states

    @property
    def continuation_alphabet(self) -> tuple[str, ...]:
        return CONTINUATIONS

    def current_distribution(self, decision_state: str) -> Mapping[tuple[ProjectedAction, str], Fraction]:
        state = parse_state(str(decision_state))
        if str(decision_state) not in self._state_set:
            raise KeyError(decision_state)
        action = native_action_for_state(state)
        post = encode_state(state[0], state[1], state[2], target_preset(state))
        return {(action, post): Fraction(1, 1)}

    def advance_distribution(self, post_state: str, continuation: str) -> Mapping[str, Fraction]:
        p, m, n, preset = parse_state(str(post_state))
        continuation = str(continuation)
        if continuation not in CONTINUATIONS:
            raise KeyError(continuation)
        if continuation == "presence_toggle":
            p = not p
        elif continuation == "motion_toggle":
            m = not m
        elif continuation == "night_toggle":
            n = not n
        nxt = encode_state(p, m, n, preset)
        if nxt not in self._state_set:
            raise KeyError(nxt)
        return {nxt: Fraction(1, 1)}


class ExactStateObservationModel:
    """Each exact C1 evidence token denotes exactly its matching modeled state."""

    def __init__(self, states: tuple[str, ...]) -> None:
        self._states = frozenset(states)

    def observation_support(self, decision_state: str) -> tuple[str, ...]:
        state = str(decision_state)
        if state not in self._states:
            raise KeyError(state)
        return (state,)


def c2_claim(horizon: int) -> ClaimSpec:
    if horizon not in (0, 1):
        raise ValueError("HA-C2 freezes only H=0 and H=1 contracts")
    return ClaimSpec(
        claim_id=f"ha-c2-bt-native-action-h{horizon}-v1",
        dimensions=CLAIM_DIMENSIONS,
        horizon=horizon,
        consequence_endpoint="home-assistant.native-service-call",
    )


def compile_c2_contract(horizon: int) -> ExplicitCompiledContract:
    target = HaC2BetterThermostatNativeTarget()
    return compile_explicit_contract(
        target,
        c2_claim(horizon),
        ExactStateObservationModel(target.decision_states),
        evidence_id=f"ha-c2-bt-exact-state-h{horizon}-v1",
    )


def _partition_groups(quotient, depth: int) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted(tuple(members) for _block, members in quotient.layer(depth).blocks))


def verify_native_target_lift() -> dict[str, object]:
    """Exhaustively prove that native action packaging preserves frozen BT semantics."""
    old = BetterThermostatFrozenModel()
    new = HaC2BetterThermostatNativeTarget()
    if old.decision_states != new.decision_states:
        raise AssertionError("native lift changed decision-state domain")
    if old.continuation_alphabet != new.continuation_alphabet:
        raise AssertionError("native lift changed continuation alphabet")

    for state in old.decision_states:
        old_law = old.current_distribution(state)
        new_law = new.current_distribution(state)
        if len(old_law) != 1 or len(new_law) != 1:
            raise AssertionError("frozen deterministic law ceased to be point-mass")
        (old_action, old_post), old_mass = next(iter(old_law.items()))
        (new_action, new_post), new_mass = next(iter(new_law.items()))
        if old_mass != Fraction(1, 1) or new_mass != Fraction(1, 1) or old_post != new_post:
            raise AssertionError("native lift changed current transition")
        old_op = old_action.as_dict()["operation"]
        desired = target_preset(parse_state(state))
        expected_old = "NO_ACTION" if parse_state(state)[3] == desired else f"SET_{desired.upper()}"
        if old_op != expected_old:
            raise AssertionError((state, old_op, expected_old))
        if new_action != native_action_for_state(parse_state(state)):
            raise AssertionError("native lift action packaging mismatch")
        for continuation in old.continuation_alphabet:
            if old.advance_distribution(old_post, continuation) != new.advance_distribution(new_post, continuation):
                raise AssertionError(("continuation mismatch", state, continuation))

    q_counts: list[int] = []
    partition_equal = True
    for horizon in (0, 1, 2):
        old_claim = ClaimSpec(
            claim_id=f"ha-c2-old-equivalence-h{horizon}",
            dimensions=("operation",),
            horizon=horizon,
            consequence_endpoint="verification-only",
        )
        new_claim = ClaimSpec(
            claim_id=f"ha-c2-new-equivalence-h{horizon}",
            dimensions=CLAIM_DIMENSIONS,
            horizon=horizon,
            consequence_endpoint="verification-only",
        )
        old_q = compile_bounded_q(old, old_claim)
        new_q = compile_bounded_q(new, new_claim)
        for depth in range(horizon + 1):
            if _partition_groups(old_q, depth) != _partition_groups(new_q, depth):
                partition_equal = False
                raise AssertionError(("q partition changed under native lift", horizon, depth))
        q_counts.append(len(new_q.layer(horizon).blocks))

    if q_counts != [5, 14, 16]:
        raise AssertionError(("unexpected frozen q counts", q_counts))
    return {
        "schema": "replaymark.ha-c2.target-lift-qualification.v1",
        "status": "PASS",
        "states": len(new.decision_states),
        "continuations": len(new.continuation_alphabet),
        "q_class_counts_h0_h1_h2": q_counts,
        "partition_equal_to_frozen_model": partition_equal,
        "native_target_fingerprint": new.fingerprint,
    }


__all__ = (
    "CLAIM_DIMENSIONS",
    "CLIMATE_ENTITY",
    "ExactStateObservationModel",
    "HaC2BetterThermostatNativeTarget",
    "c2_claim",
    "compile_c2_contract",
    "encode_state",
    "native_action_for_state",
    "parse_state",
    "target_preset",
    "verify_native_target_lift",
)
