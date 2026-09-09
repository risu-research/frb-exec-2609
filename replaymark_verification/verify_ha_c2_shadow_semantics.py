from __future__ import annotations

"""Authoritative HA-C2 shadow semantic closure verifier."""

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path

from replaymark.contracts import ProjectedAction
from replaymark.runtime_ha_bt_action import realize_ha_bt_historical_action
from replaymark.runtime_ha_bt_shadow_bridge import certify_ha_bt_shadow_reuse
from replaymark_verification.build_ha_c2_shadow_cells import (
    build_shadow_cells,
    cells_manifest,
)
from replaymark_verification.ha_c2_bt_native_target import (
    CLIMATE_ENTITY,
    HaC2BetterThermostatNativeTarget,
    compile_c2_contract,
    verify_native_target_lift,
)
from replaymark_verification.ha_c2_literal_oracle import (
    expected_action_for_evidence_token,
    expected_cell,
)

C1_COMPRESSED_SHA256 = "297ec8740a4604e60b3b64b150a2489bb4ada2ddaf988f0202bdaf8649204ab1"
C1_DECODED_SHA256 = "d34de50c920643fcc9ed1d59c5127e09f2aa8d6805c11287739ee4267b865774"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_c1_fixture(path: Path) -> dict[str, object]:
    packaged = path.read_bytes()
    if _sha(packaged) != C1_COMPRESSED_SHA256:
        raise AssertionError("C1 compressed fixture digest mismatch")
    decoded = gzip.decompress(base64.b64decode(packaged))
    if _sha(decoded) != C1_DECODED_SHA256:
        raise AssertionError("C1 decoded fixture digest mismatch")
    pack = json.loads(decoded)
    if pack.get("schema") != "replaymark.ha-c1.archived-fixtures.v1":
        raise AssertionError("foreign C1 fixture")
    return pack


def _candidate_actions() -> tuple[ProjectedAction, ...]:
    rows = []
    for preset in ("away", "home", "comfort", "sleep"):
        rows.append(
            ProjectedAction.from_mapping(
                {
                    "operation": "climate.set_preset_mode",
                    "concrete_target": CLIMATE_ENTITY,
                    "variant": json.dumps(
                        {"preset_mode": preset},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
        )
    rows.append(
        ProjectedAction.from_mapping(
            {
                "operation": "NO_ACTION",
                "concrete_target": CLIMATE_ENTITY,
                "variant": "NO_ACTION",
            }
        )
    )
    return tuple(rows)


def exhaustive_contract_oracle(contract, horizon: int) -> dict[str, object]:
    """Differentially challenge one compiled contract against the literal oracle.

    Expected actions are derived only by ``ha_c2_literal_oracle``.  In particular,
    this function does not call ``native_action_for_state`` or ``parse_state`` from
    the C2 native-target lift, preventing the implementation under test from
    supplying its own expected answer.
    """

    target = HaC2BetterThermostatNativeTarget()
    checks = valid = invalid = unresolved = 0
    candidates = _candidate_actions()
    if len(target.decision_states) != 32 or len(candidates) != 5:
        raise AssertionError("HA-C2 exhaustive domain changed")

    for state in target.decision_states:
        expected = expected_action_for_evidence_token(state)
        if contract.compatible_worlds(state) != (state,):
            raise AssertionError(
                ("exact-state evidence ceased to be singleton", horizon, state)
            )
        for candidate in candidates:
            adjudication = contract.adjudicate(state, candidate)
            reuse = contract.certify_reuse(state, candidate)
            candidate_projection = candidate.project(contract.claim.dimensions).as_dict()
            should_valid = candidate_projection == expected
            expected_verdict = "VALID" if should_valid else "INVALID"
            if adjudication.verdict.value != expected_verdict:
                raise AssertionError(
                    (
                        "contract/oracle mismatch",
                        horizon,
                        state,
                        candidate.as_dict(),
                        adjudication.verdict.value,
                        expected_verdict,
                    )
                )
            expected_reuse = "REUSE" if should_valid else "DO_NOT_REUSE"
            if reuse.disposition.value != expected_reuse:
                raise AssertionError(
                    ("R* mismatch", horizon, state, candidate.as_dict())
                )
            checks += 1
            valid += int(should_valid)
            invalid += int(not should_valid)
            unresolved += int(adjudication.verdict.value == "UNRESOLVED")

    if (checks, valid, invalid, unresolved) != (160, 32, 128, 0):
        raise AssertionError(
            ("unexpected exhaustive audit cardinality", horizon, checks, valid, invalid, unresolved)
        )
    return {
        "horizon": horizon,
        "checks": checks,
        "valid": valid,
        "invalid": invalid,
        "unresolved": unresolved,
        "oracle": "independent-literal-no-native-lift-import",
        "status": "PASS",
    }


def run(fixture_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    pack = load_c1_fixture(fixture_path)
    cells = build_shadow_cells(pack)
    manifest = cells_manifest(cells)
    manifest_digest = _sha(_canonical_json_bytes(manifest))

    # This qualification is intentionally completed before any archived C2 cell
    # enters production semantic adjudication.
    lift = verify_native_target_lift()
    contract_h0 = compile_c2_contract(0)
    contract_h1 = compile_c2_contract(1)
    exhaustive = [
        exhaustive_contract_oracle(contract_h0, 0),
        exhaustive_contract_oracle(contract_h1, 1),
    ]
    if sum(row["checks"] for row in exhaustive) != 320:
        raise AssertionError("HA-C2 exhaustive contract count changed")

    per_cell = []
    n2b_pairs: dict[tuple[int, int], dict[int, dict[str, object]]] = {}
    verdict_counts = {"VALID": 0, "INVALID": 0, "UNRESOLVED": 0}
    admission_counts = {"ADMIT_REUSE": 0, "BLOCK_REUSE": 0}

    for cell in cells:
        contract = contract_h0 if cell.family == "N2" else contract_h1
        oracle = expected_cell(
            cell.target_base_raw_observation,
            cell.target_parent_state_event,
            cell.historical_raw_action,
            cell.target_direct_raw_action,
        )
        production = certify_ha_bt_shadow_reuse(
            contract,
            base_raw_observation=cell.target_base_raw_observation,
            parent_state_event=cell.target_parent_state_event,
            historical_raw_action=cell.historical_raw_action,
        )
        direct_realized = realize_ha_bt_historical_action(cell.target_direct_raw_action)
        direct_projection = direct_realized.action.project(contract.claim.dimensions).as_dict()
        historical_projection = (
            production.runtime_certificate.adjudication.projected_action.as_dict()
        )
        compatible = contract.compatible_worlds(production.observation.evidence_token)

        if production.observation.evidence_token != oracle["evidence_token"]:
            raise AssertionError(("observation token mismatch", cell.cell_id))
        if compatible != (oracle["evidence_token"],):
            raise AssertionError(
                ("compatible world mismatch", cell.cell_id, compatible, oracle["evidence_token"])
            )
        if historical_projection != oracle["historical_projection"]:
            raise AssertionError(
                (
                    "historical action projection mismatch",
                    cell.cell_id,
                    historical_projection,
                    oracle["historical_projection"],
                )
            )
        if direct_projection != oracle["direct_projection"]:
            raise AssertionError(
                (
                    "Direct action projection mismatch",
                    cell.cell_id,
                    direct_projection,
                    oracle["direct_projection"],
                )
            )
        if production.runtime_certificate.adjudication.verdict.value != oracle["verdict"]:
            raise AssertionError(
                (
                    "verdict mismatch",
                    cell.cell_id,
                    production.runtime_certificate.adjudication.verdict.value,
                    oracle["verdict"],
                )
            )
        if (
            production.runtime_certificate.reuse_decision.disposition.value
            != oracle["reuse_disposition"]
        ):
            raise AssertionError(("R* mismatch", cell.cell_id))
        if production.admission.disposition.value != oracle["admission"]:
            raise AssertionError(("admission mismatch", cell.cell_id))
        if production.execution_performed:
            raise AssertionError(("shadow execution occurred", cell.cell_id))

        verdict_counts[oracle["verdict"]] += 1
        admission_counts[oracle["admission"]] += 1
        row = {
            "cell_id": cell.cell_id,
            "family": cell.family,
            "replica": cell.replica,
            "trial_ordinal": cell.trial_ordinal,
            "decision_index": cell.decision_index,
            "source_row_index": cell.source_row_index,
            "target_row_index": cell.target_row_index,
            "historical_precedes_target_base": (
                cell.historical_timestamp_ns < cell.target_base_timestamp_ns
            ),
            "evidence_token": oracle["evidence_token"],
            "compatible_worlds": list(compatible),
            "historical_projection": historical_projection,
            "direct_projection": direct_projection,
            "oracle_target_support": oracle["target_support"],
            "verdict": oracle["verdict"],
            "reuse_disposition": oracle["reuse_disposition"],
            "admission": oracle["admission"],
            "runtime_certificate_fingerprint": production.runtime_certificate.fingerprint(),
            "shadow_certificate_fingerprint": production.fingerprint(),
            "execution_performed": False,
        }
        if not row["historical_precedes_target_base"]:
            raise AssertionError(("historical carrier is not prior", cell.cell_id))
        per_cell.append(row)
        if cell.family == "N2b":
            pair_local = int(cell.cell_id.split("-p")[1].split("-d")[0])
            n2b_pairs.setdefault((cell.replica, pair_local), {})[
                cell.decision_index
            ] = row

    for pair, rows in n2b_pairs.items():
        if set(rows) != {0, 1}:
            raise AssertionError(("incomplete N2b pair", pair, sorted(rows)))
        if not (
            rows[0]["verdict"] == "VALID"
            and rows[0]["admission"] == "ADMIT_REUSE"
            and rows[1]["verdict"] == "INVALID"
            and rows[1]["admission"] == "BLOCK_REUSE"
        ):
            raise AssertionError(("N2b cutover mismatch", pair, rows))

    if len(n2b_pairs) != 10 or len(per_cell) != 30:
        raise AssertionError(("C2 completion count", len(n2b_pairs), len(per_cell)))

    details = {
        "schema": "replaymark.ha-c2.shadow-semantic-details.v1",
        "cell_manifest_sha256": manifest_digest,
        "cell_manifest": manifest,
        "target_lift": lift,
        "exhaustive_contract_oracle": exhaustive,
        "cells": per_cell,
    }
    result = {
        "schema": "replaymark.ha-c2.shadow-semantic-result.v1",
        "decision": "PASS",
        "c1_fixture_sha256": C1_DECODED_SHA256,
        "cell_manifest_sha256": manifest_digest,
        "n1_status": "PRE_INPUT_INELIGIBLE",
        "n1_reason": (
            "C0 v1 forbids reopening semantic modeling; C1 froze no N1 realizer "
            "and C0/C1 froze no preexisting ReplayMark compiled N1 semantic lift."
        ),
        "n2_cells": len([r for r in per_cell if r["family"] == "N2"]),
        "n2b_pairs": len(n2b_pairs),
        "n2b_decisions": len([r for r in per_cell if r["family"] == "N2b"]),
        "total_raw_shadow_decisions": len(per_cell),
        "verdict_counts": verdict_counts,
        "admission_counts": admission_counts,
        "n2b_cutover_pairs": len(n2b_pairs),
        "exhaustive_contract_checks": sum(x["checks"] for x in exhaustive),
        "exhaustive_oracle_independent_of_native_lift": True,
        "target_lift_q_counts_h0_h1_h2": lift["q_class_counts_h0_h1_h2"],
        "contract_h0_fingerprint": contract_h0.fingerprint(),
        "contract_h1_fingerprint": contract_h1.fingerprint(),
        "shadow_sink_opened": False,
        "all_production_oracle_agree": True,
    }
    return result, details


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--fixture",
        type=Path,
        default=(
            Path(__file__).resolve().parent
            / "fixtures"
            / "HA_C1_ARCHIVED_FIXTURES_V1.json.gz.b64"
        ),
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--details-out", type=Path, required=True)
    args = ap.parse_args()
    result, details = run(args.fixture)
    args.out.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    args.details_out.write_text(
        json.dumps(details, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
