from __future__ import annotations

"""Build VE2 target-only ReplayMark contracts before any scientific open.

Only the frozen label-free execution manifests plus VE2_TARGET_ONLY_CONTRACT_SPEC_V1
are read. No Old behavior, expected frontier, class weight, New Direct result,
or source diff participates in compilation.
"""

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Mapping

from replaymark.compiled_contract import compile_explicit_contract
from replaymark.contracts import ClaimSpec, ProjectedAction

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "replaymark" / "VE2_TARGET_ONLY_CONTRACT_SPEC_V1.json"
T01_MANIFEST = ROOT / "replaymark" / "VE2_T01_EXECUTION_STATE_MANIFEST_V1.json"
T02_MANIFEST = ROOT / "replaymark" / "VE2_T02_EXECUTION_STATE_MANIFEST_V1.json"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def projected_action(target: str, operation: str, variant: object | None = None) -> ProjectedAction:
    if operation == "NO_ACTION":
        return ProjectedAction.from_mapping({
            "operation": "NO_ACTION",
            "concrete_target": target,
            "variant": "NO_ACTION",
        })
    return ProjectedAction.from_mapping({
        "operation": operation,
        "concrete_target": target,
        "variant": canonical_json({} if variant is None else variant),
    })


def t01_new(fixture: dict[str, object], target: str) -> ProjectedAction:
    state = fixture.get("schedule_state")
    if state == "off":
        return projected_action(target, "climate.set_preset_mode", {"preset_mode": "none"})
    if state == "on":
        return projected_action(target, "climate.set_preset_mode", {"preset_mode": "sleep"})
    raise ValueError(f"unknown T01 schedule_state: {state!r}")


def t02_new(fixture: dict[str, object], target: str, slot_presets: dict[int, str], vacation: str) -> ProjectedAction:
    tr = str(fixture["trigger_kind"])
    active = int(fixture["active_slot"])
    ep = bool(fixture["enable_presence_mode"])
    ph = bool(fixture["presence_home"])
    epa = bool(fixture["enable_pause_switch"])
    po = bool(fixture["pause_on"])
    anyone_home = True if not ep else ph
    schedule_paused = False if not epa else po

    if tr.startswith("slot"):
        n = int(tr[-1])
        if n != active:
            raise ValueError("slot trigger must bind its active_slot")
        if schedule_paused:
            return projected_action(target, "NO_ACTION")
        if ep and not anyone_home:
            return projected_action(target, "climate.set_preset_mode", {"preset_mode": vacation})
        return projected_action(target, "climate.set_preset_mode", {"preset_mode": slot_presets[n]})

    if tr == "startup":
        if schedule_paused:
            return projected_action(target, "NO_ACTION")
        if ep and not anyone_home:
            return projected_action(target, "climate.set_preset_mode", {"preset_mode": vacation})
        return projected_action(target, "climate.set_preset_mode", {"preset_mode": slot_presets[active]})

    if tr == "pause_off":
        if not epa or schedule_paused:
            return projected_action(target, "NO_ACTION")
        if ep and not anyone_home:
            return projected_action(target, "climate.set_preset_mode", {"preset_mode": vacation})
        return projected_action(target, "climate.set_preset_mode", {"preset_mode": slot_presets[active]})

    if tr == "arrived_home":
        if not ep or schedule_paused:
            return projected_action(target, "NO_ACTION")
        return projected_action(target, "climate.set_preset_mode", {"preset_mode": slot_presets[active]})

    if tr == "left_home":
        if not ep or schedule_paused or anyone_home:
            return projected_action(target, "NO_ACTION")
        return projected_action(target, "climate.set_preset_mode", {"preset_mode": vacation})

    raise ValueError(f"unknown T02 trigger_kind: {tr!r}")


class TargetOnlyModel:
    def __init__(self, transition: str, rows: tuple[tuple[str, dict[str, object], ProjectedAction], ...]):
        self._transition = transition
        self._rows = {sid: (fixture, act) for sid, fixture, act in rows}
        self._states = tuple(sorted(self._rows))
        semantic_rows = [
            {"fixture": self._rows[sid][0], "action": self._rows[sid][1].as_dict()}
            for sid in self._states
        ]
        self._fingerprint = sha256_bytes(canonical_bytes({
            "schema": "replaymark.ve2.target-only-provider.v1",
            "transition": transition,
            "rows": semantic_rows,
            "continuations": [],
        }))

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def decision_states(self) -> tuple[str, ...]:
        return self._states

    @property
    def continuation_alphabet(self) -> tuple[str, ...]:
        return ()

    def current_distribution(self, decision_state: str) -> Mapping[tuple[ProjectedAction, str], Fraction]:
        try:
            _fixture, act = self._rows[str(decision_state)]
        except KeyError as exc:
            raise KeyError(decision_state) from exc
        return {(act, str(decision_state)): Fraction(1, 1)}

    def advance_distribution(self, post_state: str, continuation: str):
        raise KeyError((post_state, continuation))

    def fixture(self, decision_state: str) -> dict[str, object]:
        return dict(self._rows[decision_state][0])

    def expected_action(self, decision_state: str) -> ProjectedAction:
        return self._rows[decision_state][1]


class FixtureEvidence:
    def __init__(self, model: TargetOnlyModel):
        self._model = model

    def observation_support(self, decision_state: str) -> tuple[str, ...]:
        return (canonical_json(self._model.fixture(decision_state)),)


def load_rows(spec: dict[str, object], manifest: dict[str, object], transition: str) -> tuple[tuple[str, dict[str, object], ProjectedAction], ...]:
    out = []
    if transition == "T01":
        target = str(spec["T01"]["target"])
        for row in manifest["states"]:
            fixture = dict(row["fixture"])
            out.append((str(row["opaque_state_id"]), fixture, t01_new(fixture, target)))
    elif transition == "T02":
        conf = spec["T02"]
        target = str(conf["target"])
        slots = {int(k): str(v) for k, v in conf["slot_presets"].items()}
        vacation = str(conf["vacation_preset"])
        for row in manifest["states"]:
            fixture = dict(row["fixture"])
            out.append((str(row["opaque_state_id"]), fixture, t02_new(fixture, target, slots, vacation)))
    else:
        raise KeyError(transition)
    if len({sid for sid, _, _ in out}) != len(out):
        raise AssertionError("duplicate opaque state id")
    if len({canonical_json(f) for _, f, _ in out}) != len(out):
        raise AssertionError("duplicate semantic fixture token")
    return tuple(out)


def build_one(transition: str, spec: dict[str, object], manifest: dict[str, object]):
    rows = load_rows(spec, manifest, transition)
    model = TargetOnlyModel(transition, rows)
    evidence = FixtureEvidence(model)
    claim = ClaimSpec(
        claim_id=f"replaymark.ve2.{transition.lower()}.native-service-call.h0.v1",
        dimensions=tuple(spec["claim"]["dimensions"]),
        horizon=int(spec["claim"]["horizon"]),
        consequence_endpoint=str(spec["claim"]["consequence_endpoint"]),
    )
    contract = compile_explicit_contract(
        model,
        claim,
        evidence,
        evidence_id=f"replaymark.ve2.{transition.lower()}.fixture-evidence.v1",
    )
    for sid in model.decision_states:
        token = canonical_json(model.fixture(sid))
        if contract.compatible_worlds(token) != (sid,):
            raise AssertionError((transition, sid, contract.compatible_worlds(token)))
        expected = claim.project(model.expected_action(sid))
        observed = contract.support_envelope.observation(token)
        if observed.guaranteed_support != (expected,) or observed.possible_support != (expected,):
            raise AssertionError((transition, sid, observed.canonical_record(), expected.as_dict()))
    text = contract.canonical_bytes().decode("utf-8")
    for forbidden in ("RETIRED_BY_UPDATE", "COMPATIBLE_ACROSS_VERSION", "old_projected_action", "weight_in_144_state_superspace"):
        if forbidden in text:
            raise AssertionError(("forbidden-contract-token", transition, forbidden))
    return contract, model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=False)

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    t01_manifest = json.loads(T01_MANIFEST.read_text(encoding="utf-8"))
    t02_manifest = json.loads(T02_MANIFEST.read_text(encoding="utf-8"))
    if spec["schema"] != "replaymark.ve2.target-only-contract-spec.v1":
        raise AssertionError("spec schema")
    if t01_manifest["schema"] != "replaymark.ve2.t01.execution-state-manifest.v1":
        raise AssertionError("T01 manifest schema")
    if t02_manifest["schema"] != "replaymark.ve2.t02.execution-state-manifest.v1":
        raise AssertionError("T02 manifest schema")

    receipts = {}
    for transition, manifest in (("T01", t01_manifest), ("T02", t02_manifest)):
        contract, model = build_one(transition, spec, manifest)
        record = contract.canonical_record()
        path = out / f"VE2_{transition}_TARGET_ONLY_COMPILED_CONTRACT_V1.json"
        payload = json.dumps(record, sort_keys=True, indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
        receipts[transition] = {
            "states": len(model.decision_states),
            "contract_fingerprint": contract.fingerprint(),
            "export_file_sha256": sha256_bytes(payload.encode("utf-8")),
            "claim_fingerprint": contract.claim_fingerprint,
            "target_provider_fingerprint": contract.target_provider_fingerprint,
            "target_semantic_digest": contract.target_semantic_digest,
            "target_snapshot_fingerprint": contract.target_snapshot_fingerprint,
            "evidence_semantics_fingerprint": contract.evidence_semantics_fingerprint,
            "evidence_relation_fingerprint": contract.evidence_relation_fingerprint,
            "quotient_fingerprint": contract.quotient_fingerprint,
            "support_envelope_fingerprint": contract.support_envelope_fingerprint,
            "predictive_witness_index_fingerprint": contract.predictive_witness_index_fingerprint,
            "contract_file": path.name,
        }

    receipt = {
        "schema": "replaymark.ve2.target-only-contract-freeze-receipt.v1",
        "status": "PASS_PRE_SCIENCE",
        "source_constitution": "f0cca6726b634a35c523b0caab89694bd7fb18e5",
        "inputs": {
            "spec_sha256": file_sha256(SPEC_PATH),
            "T01_manifest_sha256": file_sha256(T01_MANIFEST),
            "T02_manifest_sha256": file_sha256(T02_MANIFEST),
            "expected_frontier_files_read": False,
            "old_semantics_files_read": False,
            "new_direct_results_read": False
        },
        "contracts": receipts,
        "scientific_exposure": {
            "home_assistant_cells": 0,
            "replaymark_cells": 0,
            "frontier_result_seen": False
        }
    }
    receipt_path = out / "VE2_TARGET_ONLY_CONTRACT_FREEZE_RECEIPT_V1.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for path in sorted(out.iterdir()):
        print(path.name, file_sha256(path))
    print(json.dumps({"status": "PASS", "contracts": receipts}, sort_keys=True))


if __name__ == "__main__":
    main()
