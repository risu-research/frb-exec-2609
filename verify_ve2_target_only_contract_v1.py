from __future__ import annotations

"""Independent structural verifier for the pre-science VE2 target-only contracts.

This verifier does not import the builder or ReplayMark compiler. It reconstructs
only the frozen New target action law from label-free fixtures and checks the
serialized compiled-contract artifacts and their receipt.
"""

import argparse
import hashlib
import json
from pathlib import Path


def cjson(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pa(target: str, operation: str, variant: object | None = None) -> dict[str, object]:
    if operation == "NO_ACTION":
        return {"operation": "NO_ACTION", "concrete_target": target, "variant": "NO_ACTION"}
    return {"operation": operation, "concrete_target": target, "variant": cjson({} if variant is None else variant)}


def expected_t01(f: dict[str, object]) -> dict[str, object]:
    if f == {"schedule_state": "off"}:
        return pa("climate.ve2_t01_thermostat", "climate.set_preset_mode", {"preset_mode": "none"})
    if f == {"schedule_state": "on"}:
        return pa("climate.ve2_t01_thermostat", "climate.set_preset_mode", {"preset_mode": "sleep"})
    raise AssertionError(("unexpected-t01-fixture", f))


def expected_t02(f: dict[str, object]) -> dict[str, object]:
    tr = str(f["trigger_kind"]); active = int(f["active_slot"])
    ep = bool(f["enable_presence_mode"]); ph = bool(f["presence_home"])
    epa = bool(f["enable_pause_switch"]); po = bool(f["pause_on"])
    target = "climate.ve2_t02_thermostat"
    slots = {1: "comfort", 2: "eco", 3: "home", 4: "sleep"}
    paused = po if epa else False
    anyone_home = ph if ep else True
    if tr.startswith("slot"):
        n = int(tr[-1]); assert n == active
        if paused: return pa(target, "NO_ACTION")
        if ep and not anyone_home: return pa(target, "climate.set_preset_mode", {"preset_mode": "away"})
        return pa(target, "climate.set_preset_mode", {"preset_mode": slots[n]})
    if tr == "startup":
        if paused: return pa(target, "NO_ACTION")
        if ep and not anyone_home: return pa(target, "climate.set_preset_mode", {"preset_mode": "away"})
        return pa(target, "climate.set_preset_mode", {"preset_mode": slots[active]})
    if tr == "pause_off":
        if not epa or paused: return pa(target, "NO_ACTION")
        if ep and not anyone_home: return pa(target, "climate.set_preset_mode", {"preset_mode": "away"})
        return pa(target, "climate.set_preset_mode", {"preset_mode": slots[active]})
    if tr == "arrived_home":
        if not ep or paused: return pa(target, "NO_ACTION")
        return pa(target, "climate.set_preset_mode", {"preset_mode": slots[active]})
    if tr == "left_home":
        if not ep or paused or anyone_home: return pa(target, "NO_ACTION")
        return pa(target, "climate.set_preset_mode", {"preset_mode": "away"})
    raise AssertionError(("unexpected-t02-trigger", tr))


def verify_one(root: Path, generated: Path, receipt: dict[str, object], transition: str) -> dict[str, object]:
    manifest_path = root / "replaymark" / f"VE2_{transition}_EXECUTION_STATE_MANIFEST_V1.json"
    manifest = json.loads(manifest_path.read_text())
    rows = {str(row["opaque_state_id"]): dict(row["fixture"]) for row in manifest["states"]}
    expected_n = 2 if transition == "T01" else 42
    assert len(rows) == expected_n
    assert len({cjson(f) for f in rows.values()}) == expected_n

    rec = receipt["contracts"][transition]
    path = generated / rec["contract_file"]
    raw = path.read_bytes(); obj = json.loads(raw)
    assert sha(raw) == rec["export_file_sha256"]
    assert sha(cjson(obj).encode()) == rec["contract_fingerprint"]
    assert obj["schema"] == "replaymark.compiled-contract.explicit.v1"
    man = obj["manifest"]
    for key in (
        "claim_fingerprint", "target_provider_fingerprint", "target_semantic_digest",
        "target_snapshot_fingerprint", "evidence_semantics_fingerprint",
        "evidence_relation_fingerprint", "quotient_fingerprint",
        "support_envelope_fingerprint", "predictive_witness_index_fingerprint",
    ):
        assert man[key] == rec[key], (transition, key)

    snap = obj["artifacts"]["target_snapshot"]["semantic_snapshot"]
    current = snap["current"]["current_laws"]
    assert len(current) == expected_n
    by_state = {str(row["decision_state"]): row for row in current}
    assert set(by_state) == set(rows)
    expected_fn = expected_t01 if transition == "T01" else expected_t02
    for sid, fixture in rows.items():
        branches = by_state[sid]["branches"]
        assert len(branches) == 1
        assert branches[0]["mass"] == {"numerator": 1, "denominator": 1}
        assert branches[0]["post_state"] == sid
        assert branches[0]["action"] == expected_fn(fixture), (transition, sid, fixture, branches[0]["action"])

    evidence = obj["artifacts"]["evidence_semantics"]
    supports = {str(row["decision_state"]): tuple(row["tokens"]) for row in evidence["world_observation_supports"]}
    assert set(supports) == set(rows)
    for sid, fixture in rows.items():
        assert supports[sid] == (cjson(fixture),)

    envelope = obj["artifacts"]["support_envelope"]
    obs = {str(row["token"]): row for row in envelope["observations"]}
    assert len(obs) == expected_n
    for sid, fixture in rows.items():
        token = cjson(fixture); expected = expected_fn(fixture)
        assert obs[token]["guaranteed_support"] == [expected]
        assert obs[token]["possible_support"] == [expected]

    text = cjson(obj)
    for forbidden in ("RETIRED_BY_UPDATE", "COMPATIBLE_ACROSS_VERSION", "old_projected_action", "weight_in_144_state_superspace"):
        assert forbidden not in text
    return {
        "transition": transition,
        "states": expected_n,
        "contract_fingerprint": rec["contract_fingerprint"],
        "target_semantic_digest": rec["target_semantic_digest"],
        "fixture_tokens_unique": True,
        "new_target_law_exact": True,
        "expected_frontier_material_absent": True,
    }


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--generated", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(); root = Path(__file__).resolve().parents[1]; gen = Path(a.generated)
    receipt = json.loads((gen / "VE2_TARGET_ONLY_CONTRACT_FREEZE_RECEIPT_V1.json").read_text())
    assert receipt["schema"] == "replaymark.ve2.target-only-contract-freeze-receipt.v1"
    assert receipt["status"] == "PASS_PRE_SCIENCE"
    assert receipt["inputs"]["expected_frontier_files_read"] is False
    assert receipt["inputs"]["old_semantics_files_read"] is False
    result = {
        "schema": "replaymark.ve2.target-only-contract-independent-validation.v1",
        "status": "PASS",
        "T01": verify_one(root, gen, receipt, "T01"),
        "T02": verify_one(root, gen, receipt, "T02"),
        "scientific_result_opened": False,
        "scientific_cells": 0,
    }
    Path(a.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
