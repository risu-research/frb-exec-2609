from __future__ import annotations

"""Post-result adjudication for VE2 first-complete authority v2.

This program never executes a scientific worker. It first independently verifies
all sixteen immutable raw-stage reports and their raw seal. Only after that seal
has passed does it open the frozen expected-frontier/model material. It reports
preregistered-model fidelity and empirical ReplayMark/native-boundary performance
as separate axes; it never rewrites a frozen expectation.
"""

import argparse
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

AUTHORITY_HEAD = "727889c1254a76fe6f6596c2be7ade47dd96ee33"
RAW_SEAL_FILE_SHA256 = "3a73be12921d99aa1a903e602c02ef8e166067185cfaf577caf3fea6ee5b0769"
RAW_SEAL_CANONICAL_SHA256 = "9011d15657e38d604878446878ee8dd137ffb52912fef49471e54dd4fd0a62e5"
T01_FRONTIER_BLOB = "edad64a2b289f103712f9fe74877e713b8af5551"
T02_FRONTIER_BLOB = "76d4ecabf6938e13b719d6350deb191106df5c57"
MODEL_BLOB = "cc57cd825b6d8bf68d2c661efbdc5d6357699b53"
T02_OLD_BLUEPRINT_SHA256 = "5593911e8ef5db3cc29f1ab4bb6658538f6e68fecbd010de0527ecc41b5d4115"
EXPECTED_STAGE_KEYS = [
    "T01_R0_OLD_HISTORY", "T01_R1_OLD_HISTORY",
    "T01_R0_NEW_DIRECT", "T01_R1_NEW_DIRECT",
    "T01_R0_REPLAYMARK", "T01_R1_REPLAYMARK",
    "T01_R0_REPLAY_ALL", "T01_R1_REPLAY_ALL",
    "T02_R0_OLD_HISTORY", "T02_R1_OLD_HISTORY",
    "T02_R0_NEW_DIRECT", "T02_R1_NEW_DIRECT",
    "T02_R0_REPLAYMARK", "T02_R1_REPLAYMARK",
    "T02_R0_REPLAY_ALL", "T02_R1_REPLAY_ALL",
]


def cb(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha(value: object) -> str:
    return hashlib.sha256(cb(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha(path: Path) -> str:
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def verify_self_hash(value: dict[str, Any], key: str, message: str) -> None:
    supplied = value.get(key)
    body = dict(value)
    body.pop(key, None)
    require(isinstance(supplied, str) and supplied == sha(body), message)


def verify_checksums_file(raw_dir: Path) -> None:
    checks = raw_dir / "CHECKSUMS.sha256"
    require(checks.is_file(), "raw-checksums-missing")
    for line in checks.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        rel = rel.strip()
        if rel.startswith("*"):
            rel = rel[1:]
        target = raw_dir / rel
        require(target.is_file(), "raw-checksum-target-missing:" + rel)
        require(file_sha(target) == digest, "raw-checksum-mismatch:" + rel)


def stage_identity(key: str) -> tuple[str, int, str]:
    transition, replica, stage_name = key.split("_", 2)
    replica_id = int(replica[1:])
    stage = {
        "OLD_HISTORY": "old_history",
        "NEW_DIRECT": "new_direct",
        "REPLAYMARK": "replaymark",
        "REPLAY_ALL": "replay_all",
    }[stage_name]
    return transition, replica_id, stage


def verify_raw_authority(raw_dir: Path, raw_seal_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    require(file_sha(raw_seal_path) == RAW_SEAL_FILE_SHA256, "raw-seal-file-sha256")
    verify_checksums_file(raw_dir)
    seal = json.loads(raw_seal_path.read_bytes())
    require(seal.get("schema") == "replaymark.ve2.all-raw-stage-artifacts-sealed.v1", "raw-seal-schema")
    require(seal.get("status") == "ALL_16_RAW_STAGES_SEALED", "raw-seal-status")
    require(seal.get("authority_head") == AUTHORITY_HEAD, "raw-seal-authority")
    require(seal.get("raw_stage_artifacts") == 16, "raw-seal-stage-count")
    require(seal.get("scientific_cells") == 352, "raw-seal-cell-count")
    require(seal.get("scientific_summary_emitted") is False, "raw-seal-summary-firewall")
    require(seal.get("expected_frontier_read_before_raw_seal") is False, "raw-seal-frontier-firewall")
    require(seal.get("result_dependent_rerun_authorized") is False, "raw-seal-rerun-law")
    require(seal.get("successful_subset_carry_forward") is False, "raw-seal-carry-forward-law")
    verify_self_hash(seal, "seal_sha256", "raw-seal-canonical-digest")
    require(seal["seal_sha256"] == RAW_SEAL_CANONICAL_SHA256, "raw-seal-authority-digest")

    stages = seal.get("stages")
    require(isinstance(stages, list) and len(stages) == 16, "raw-seal-stage-list")
    require([row.get("stage_key") for row in stages] == EXPECTED_STAGE_KEYS, "raw-stage-order")
    docs: dict[str, dict[str, Any]] = {}
    total_rows = 0
    for entry in stages:
        key = entry["stage_key"]
        transition, replica, stage = stage_identity(key)
        report_path = raw_dir / entry["report_file"]
        validation_path = raw_dir / entry["validation_file"]
        require(file_sha(report_path) == entry["report_file_sha256"], "report-file-digest:" + key)
        require(file_sha(validation_path) == entry["validation_file_sha256"], "validation-file-digest:" + key)

        report = json.loads(report_path.read_bytes())
        validation = json.loads(validation_path.read_bytes())
        require(report.get("schema") == "replaymark.ve2.scientific-native-stage.v1", "report-schema:" + key)
        require(report.get("status") == "SEALED_RAW_STAGE", "report-status:" + key)
        require(report.get("transition") == transition and report.get("replica") == replica and report.get("stage") == stage, "report-identity:" + key)
        require(report.get("frontier_result_seen") is False and report.get("scientific_summary_emitted") is False, "report-firewall:" + key)
        supplied = report.get("result_sha256")
        body = dict(report); body.pop("result_sha256", None)
        require(supplied == sha(body) == entry["stage_result_sha256"], "report-self-digest:" + key)
        rows = report.get("rows")
        expected_rows = 2 if transition == "T01" else 42
        require(isinstance(rows, list) and len(rows) == expected_rows == entry["rows_verified"], "report-row-count:" + key)
        for row in rows:
            row_digest = row.get("row_sha256")
            row_body = dict(row); row_body.pop("row_sha256", None)
            require(row_digest == sha(row_body), "row-self-digest:" + key)
            require(row.get("status") == "COMPLETE_OBSERVED" and row.get("failure") is None, "row-incomplete:" + key)
        total_rows += len(rows)

        require(validation.get("schema") == "replaymark.ve2.raw-stage-independent-validation.v1", "validation-schema:" + key)
        require(validation.get("status") == "PASS", "validation-status:" + key)
        require(validation.get("transition") == transition and validation.get("replica") == replica and validation.get("stage") == stage, "validation-identity:" + key)
        require(validation.get("rows_verified") == expected_rows, "validation-row-count:" + key)
        require(validation.get("stage_result_sha256") == supplied, "validation-report-binding:" + key)
        verify_self_hash(validation, "validation_sha256", "validation-self-digest:" + key)
        docs[key] = report
    require(total_rows == 352, "raw-total-row-count")
    return seal, docs


def row_map(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["opaque_state_id"]): row for row in doc["rows"]}


def action_equal(a: object, b: object) -> bool:
    return a == b


def t01_analysis(docs: dict[str, dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    rows_expected = {row["execution_state_id"]: row for row in expected["rows"]}
    per = []
    for replica in (0, 1):
        old = row_map(docs[f"T01_R{replica}_OLD_HISTORY"])
        new = row_map(docs[f"T01_R{replica}_NEW_DIRECT"])
        rm = row_map(docs[f"T01_R{replica}_REPLAYMARK"])
        ra = row_map(docs[f"T01_R{replica}_REPLAY_ALL"])
        old_agree = new_agree = compatible = retired = admitted = blocked = unsafe = replay_all_retired = 0
        for sid, exp in rows_expected.items():
            oa = old[sid]["native_projected_action"]
            na = new[sid]["native_projected_action"]
            old_agree += action_equal(oa, exp["old_projected_action"])
            new_agree += action_equal(na, exp["new_projected_action"])
            is_compatible = action_equal(oa, na)
            compatible += is_compatible
            retired += not is_compatible
            admission = rm[sid]["presented_certificate"]["admission"]
            admitted += admission == "ADMIT_REUSE"
            blocked += admission == "BLOCK_REUSE"
            unsafe += (not is_compatible) and bool(rm[sid]["dispatch"]["attempted"])
            replay_all_retired += (not is_compatible) and bool(ra[sid]["dispatch"]["attempted"])
        prereg = {
            "compatible_history_executed": sum(
                1 for sid, exp in rows_expected.items()
                if exp["compatibility"] == "COMPATIBLE_ACROSS_VERSION" and rm[sid]["presented_certificate"]["admission"] == "ADMIT_REUSE"
            ),
            "direct_reference_disagreement": (2 - old_agree) + (2 - new_agree),
            "new_direct_source_agreement": f"{new_agree}/2",
            "old_native_source_agreement": f"{old_agree}/2",
            "retired_history_blocked_before_historical_sink": sum(
                1 for sid, exp in rows_expected.items()
                if exp["compatibility"] == "RETIRED_BY_UPDATE" and rm[sid]["presented_certificate"]["admission"] == "BLOCK_REUSE"
            ),
            "unsafe_retired_historical_dispatch": sum(
                1 for sid, exp in rows_expected.items()
                if exp["compatibility"] == "RETIRED_BY_UPDATE" and rm[sid]["dispatch"]["attempted"]
            ),
        }
        empirical_pass = (
            compatible == admitted == 0 and retired == blocked == 2 and unsafe == 0
            and all(rm[sid].get("caller_native_recovery") is False for sid in rm)
        )
        per.append({
            "replica": replica,
            "preregistered_metrics": prereg,
            "preregistered_exact_match": prereg == expected["promotion_per_replica"],
            "observed_native_boundary": {"compatible": compatible, "retired": retired},
            "replaymark": {"admit": admitted, "block": blocked, "unsafe_observed_retired_dispatch": unsafe},
            "replay_all_observed_retired_dispatch": replay_all_retired,
            "core_empirical_pass": empirical_pass,
        })
    return {
        "status": "PASS" if all(x["preregistered_exact_match"] and x["core_empirical_pass"] for x in per) else "FAIL",
        "per_replica": per,
    }


def t02_analysis(
    docs: dict[str, dict[str, Any]],
    expected: dict[str, Any],
    model: Any,
    model_source_path: Path,
    old_blueprint_path: Path,
) -> dict[str, Any]:
    abstract, quotient = model.t02_quotient()
    require(sha(abstract) == expected["abstract_table"]["canonical_rows_sha256"], "t02-model-abstract-digest")
    require(sha(quotient) == expected["causal_path_quotient_table"]["canonical_rows_sha256"], "t02-model-quotient-digest")
    require(len(quotient) == 42 and len(abstract) == 144, "t02-model-population")
    qmap = {row["execution_state_id"]: row for row in quotient}
    require(len(qmap) == 42, "t02-model-state-id-population")

    model_source = model_source_path.read_text(encoding="utf-8")
    require(git_blob_sha(model_source_path) == MODEL_BLOB, "model-source-git-blob")
    require('schedule_paused: object = "false" if not epa else po' in model_source, "model-truthiness-assumption-source")
    require("if bool(schedule_paused):" in model_source, "model-truthiness-branch-source")
    blueprint = old_blueprint_path.read_text(encoding="utf-8")
    require(file_sha(old_blueprint_path) == T02_OLD_BLUEPRINT_SHA256, "t02-old-blueprint-sha256")
    require("{% if not enable_pause_switch or pause_switch == '' %}false" in blueprint, "old-blueprint-false-literal-source")
    require('value_template: "{{ schedule_paused }}"' in blueprint, "old-blueprint-startup-paused-condition-source")

    per = []
    semantic_fingerprints = []
    all_old_mismatches: list[dict[str, Any]] | None = None
    all_classification_mismatches: list[dict[str, Any]] | None = None
    for replica in (0, 1):
        old = row_map(docs[f"T02_R{replica}_OLD_HISTORY"])
        new = row_map(docs[f"T02_R{replica}_NEW_DIRECT"])
        rm = row_map(docs[f"T02_R{replica}_REPLAYMARK"])
        ra = row_map(docs[f"T02_R{replica}_REPLAY_ALL"])
        require(set(old) == set(new) == set(rm) == set(ra) == set(qmap), "t02-state-population")

        old_agree = new_agree = 0
        native_compatible = native_retired = 0
        native_compatible_admitted = native_retired_blocked = 0
        unsafe_observed_retired = unnecessary_recovery = 0
        replay_all_retired_dispatch = 0
        model_compatible_admitted = model_retired_blocked = model_unsafe = 0
        old_mismatches: list[dict[str, Any]] = []
        new_mismatches: list[dict[str, Any]] = []
        classification_mismatches: list[dict[str, Any]] = []
        semantic_rows = []

        for sid in sorted(qmap):
            exp = qmap[sid]
            fixture = old[sid]["fixture"]
            require(fixture == new[sid]["fixture"] == rm[sid]["fixture"] == ra[sid]["fixture"], "t02-fixture-cross-arm:" + sid)
            require(fixture == exp["representative_fixture"], "t02-model-fixture-binding:" + sid)
            oa = old[sid]["native_projected_action"]
            na = new[sid]["native_projected_action"]
            model_oa = exp["old_projected_action"]
            model_na = exp["new_projected_action"]
            old_ok = action_equal(oa, model_oa)
            new_ok = action_equal(na, model_na)
            old_agree += old_ok
            new_agree += new_ok
            model_compatible = action_equal(model_oa, model_na)
            observed_compatible = action_equal(oa, na)
            native_compatible += observed_compatible
            native_retired += not observed_compatible
            admission = rm[sid]["presented_certificate"]["admission"]
            native_compatible_admitted += observed_compatible and admission == "ADMIT_REUSE"
            native_retired_blocked += (not observed_compatible) and admission == "BLOCK_REUSE"
            unsafe_observed_retired += (not observed_compatible) and bool(rm[sid]["dispatch"]["attempted"])
            unnecessary_recovery += rm[sid].get("caller_native_recovery") is not False
            replay_all_retired_dispatch += (not observed_compatible) and bool(ra[sid]["dispatch"]["attempted"])
            model_compatible_admitted += model_compatible and admission == "ADMIT_REUSE"
            model_retired_blocked += (not model_compatible) and admission == "BLOCK_REUSE"
            model_unsafe += (not model_compatible) and bool(rm[sid]["dispatch"]["attempted"])

            detail = {
                "execution_state_id": sid,
                "fixture": fixture,
                "weight_in_144_state_superspace": exp["weight_in_144_state_superspace"],
                "model_old_projected_action": model_oa,
                "observed_old_projected_action": oa,
                "model_new_projected_action": model_na,
                "observed_new_projected_action": na,
                "model_compatibility": "COMPATIBLE" if model_compatible else "RETIRED",
                "observed_native_compatibility": "COMPATIBLE" if observed_compatible else "RETIRED",
                "replaymark_admission": admission,
            }
            if not old_ok:
                old_mismatches.append(detail)
            if not new_ok:
                new_mismatches.append(detail)
            if model_compatible != observed_compatible:
                classification_mismatches.append(detail)
            semantic_rows.append({
                "execution_state_id": sid,
                "observed_old": oa,
                "observed_new": na,
                "replaymark_admission": admission,
                "replaymark_dispatch_attempted": rm[sid]["dispatch"]["attempted"],
                "replay_all_dispatch_attempted": ra[sid]["dispatch"]["attempted"],
            })

        prereg = {
            "old_native_source_agreement": f"{old_agree}/42",
            "new_direct_source_agreement": f"{new_agree}/42",
            "direct_reference_disagreement": (42 - old_agree) + (42 - new_agree),
            "replaymark_compatible_classes_executed": model_compatible_admitted,
            "replaymark_retired_classes_blocked": model_retired_blocked,
            "unnecessary_native_recovery": unnecessary_recovery,
            "unsafe_retired_historical_dispatch": model_unsafe,
            "weighted_abstract_frontier": dict(expected["promotion_per_replica"]["weighted_abstract_frontier"]),
        }
        empirical_pass = (
            native_compatible_admitted == native_compatible
            and native_retired_blocked == native_retired
            and unsafe_observed_retired == 0
            and unnecessary_recovery == 0
        )
        root_cluster = bool(old_mismatches) and all(
            row["fixture"].get("trigger_kind") == "startup"
            and row["fixture"].get("enable_pause_switch") is False
            for row in old_mismatches
        )
        per.append({
            "replica": replica,
            "preregistered_metrics": prereg,
            "preregistered_exact_match": prereg == expected["promotion_per_replica"],
            "auxiliary_model_fidelity": {
                "old_action_agreement": f"{old_agree}/42",
                "new_action_agreement": f"{new_agree}/42",
                "old_action_mismatch_count": len(old_mismatches),
                "new_action_mismatch_count": len(new_mismatches),
                "compatibility_classification_mismatch_count": len(classification_mismatches),
                "old_action_mismatches": old_mismatches,
                "new_action_mismatches": new_mismatches,
                "classification_mismatches": classification_mismatches,
                "all_old_mismatches_cluster_at_startup_with_pause_disabled": root_cluster,
            },
            "observed_native_boundary": {
                "compatible": native_compatible,
                "retired": native_retired,
            },
            "replaymark_empirical": {
                "observed_compatible_admitted": native_compatible_admitted,
                "observed_retired_blocked": native_retired_blocked,
                "unsafe_observed_retired_historical_dispatch": unsafe_observed_retired,
                "unnecessary_native_recovery": unnecessary_recovery,
            },
            "replay_all": {
                "observed_retired_historical_dispatch": replay_all_retired_dispatch,
            },
            "core_empirical_pass": empirical_pass,
        })
        semantic_fingerprints.append(sha(semantic_rows))
        if all_old_mismatches is None:
            all_old_mismatches = old_mismatches
            all_classification_mismatches = classification_mismatches
        else:
            require(old_mismatches == all_old_mismatches, "t02-old-mismatch-replica-disagreement")
            require(classification_mismatches == all_classification_mismatches, "t02-classification-mismatch-replica-disagreement")

    require(len(set(semantic_fingerprints)) == 1, "t02-semantic-replica-disagreement")
    old_mismatches = all_old_mismatches or []
    class_mismatches = all_classification_mismatches or []
    root_cause_supported = (
        len(old_mismatches) > 0
        and all(row["fixture"]["trigger_kind"] == "startup" and row["fixture"]["enable_pause_switch"] is False for row in old_mismatches)
        and all(row["observed_native_compatibility"] != row["model_compatibility"] for row in class_mismatches)
    )
    two = {
        "observed_compatible_instances": sum(x["observed_native_boundary"]["compatible"] for x in per),
        "observed_retired_instances": sum(x["observed_native_boundary"]["retired"] for x in per),
        "replaymark_observed_compatible_admitted": sum(x["replaymark_empirical"]["observed_compatible_admitted"] for x in per),
        "replaymark_observed_retired_blocked": sum(x["replaymark_empirical"]["observed_retired_blocked"] for x in per),
        "unsafe_observed_retired_historical_dispatch": sum(x["replaymark_empirical"]["unsafe_observed_retired_historical_dispatch"] for x in per),
        "replay_all_observed_retired_historical_dispatch": sum(x["replay_all"]["observed_retired_historical_dispatch"] for x in per),
    }
    return {
        "status": "CORE_METHOD_PASS_AUXILIARY_MODEL_FALSIFIED" if all(x["core_empirical_pass"] for x in per) and not all(x["preregistered_exact_match"] for x in per) else "OTHER",
        "per_replica": per,
        "two_replica_total": two,
        "semantic_replica_agreement": True,
        "root_cause_forensics": {
            "classification": "FROZEN_MODEL_FALSE_LITERAL_TRUTHINESS_ASSUMPTION_FALSIFIED_BY_NATIVE_EXECUTION" if root_cause_supported else "UNRESOLVED",
            "model_source_git_blob": MODEL_BLOB,
            "old_blueprint_sha256": T02_OLD_BLUEPRINT_SHA256,
            "mismatch_cluster": "startup_when_enable_pause_switch_false" if root_cause_supported else None,
            "interpretation": "The frozen auxiliary model treated its synthetic string value 'false' as truthy via Python bool(). Native Home Assistant execution did not exhibit that modeled block at these startup states; the immutable native rows therefore falsify that auxiliary assumption.",
        },
        "weighted_abstract_reconstruction": {
            "status": "WITHHELD_NOT_PROMOTED",
            "frozen_preregistered_counts": dict(expected["abstract_table"]),
            "reason": "The 144-state weighting and quotient classification were derived through the auxiliary transition model whose old-startup semantic assumption is falsified by the native result. No post-hoc reweighting is promoted as a preregistered result.",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--raw-seal", required=True)
    ap.add_argument("--t01-frontier", required=True)
    ap.add_argument("--t02-frontier", required=True)
    ap.add_argument("--model-source", required=True)
    ap.add_argument("--t02-old-blueprint", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    seal, docs = verify_raw_authority(raw_dir, Path(args.raw_seal))

    # Answer-bearing preregistration/model material is opened only after the
    # immutable 16-stage raw seal has independently passed above.
    t01_frontier = Path(args.t01_frontier)
    t02_frontier = Path(args.t02_frontier)
    require(git_blob_sha(t01_frontier) == T01_FRONTIER_BLOB, "t01-frontier-git-blob")
    require(git_blob_sha(t02_frontier) == T02_FRONTIER_BLOB, "t02-frontier-git-blob")
    t01_expected = json.loads(t01_frontier.read_bytes())
    t02_expected = json.loads(t02_frontier.read_bytes())
    model = importlib.import_module("ve2_transition_semantics_v1")

    t01 = t01_analysis(docs, t01_expected)
    t02 = t02_analysis(
        docs, t02_expected, model,
        Path(args.model_source), Path(args.t02_old_blueprint),
    )
    prereg_exact = t01["status"] == "PASS" and all(x["preregistered_exact_match"] for x in t02["per_replica"])
    core_pass = all(x["core_empirical_pass"] for x in t01["per_replica"]) and all(x["core_empirical_pass"] for x in t02["per_replica"])
    model_fidelity = all(
        x["auxiliary_model_fidelity"]["old_action_mismatch_count"] == 0
        and x["auxiliary_model_fidelity"]["new_action_mismatch_count"] == 0
        for x in t02["per_replica"]
    )

    result = {
        "schema": "replaymark.ve2.scientific-postrun-deviation-adjudication.v1",
        "status": "CORE_METHOD_PASS_AUXILIARY_MODEL_FALSIFIED" if core_pass and not model_fidelity and not prereg_exact else "OTHER",
        "authority": {
            "authority_head": AUTHORITY_HEAD,
            "raw_seal_file_sha256": RAW_SEAL_FILE_SHA256,
            "raw_seal_canonical_sha256": seal["seal_sha256"],
            "raw_stage_artifacts": 16,
            "scientific_cells": 352,
            "scientific_workers_rerun_for_this_analysis": False,
            "analysis_is_post_result": True,
        },
        "experimental_integrity": {
            "status": "PASS",
            "all_16_raw_stages_independently_validated": True,
            "raw_seal_verified_before_frontier_or_model_read": True,
            "frontier_read_before_raw_seal": False,
            "same_authority_rerun": False,
        },
        "preregistered_expected_frontier_exact_match": {
            "status": "PASS" if prereg_exact else "FAIL",
            "expectations_rewritten": False,
            "t01": t01,
            "t02_expected_quotient": {
                "compatible": t02_expected["causal_path_quotient_table"]["compatible"],
                "retired": t02_expected["causal_path_quotient_table"]["retired"],
            },
            "t02_per_replica": [x["preregistered_metrics"] for x in t02["per_replica"]],
        },
        "auxiliary_transition_model_fidelity": {
            "status": "PASS" if model_fidelity else "FAIL",
            "t02": [{
                "replica": x["replica"],
                **x["auxiliary_model_fidelity"],
            } for x in t02["per_replica"]],
            "root_cause_forensics": t02["root_cause_forensics"],
        },
        "core_replaymark_observed_native_boundary": {
            "status": "PASS" if core_pass else "FAIL",
            "claim_boundary": "home-assistant.native-service-call",
            "t01": [{
                "replica": x["replica"],
                "observed_native_boundary": x["observed_native_boundary"],
                "replaymark": x["replaymark"],
                "core_empirical_pass": x["core_empirical_pass"],
            } for x in t01["per_replica"]],
            "t02": [{
                "replica": x["replica"],
                "observed_native_boundary": x["observed_native_boundary"],
                "replaymark_empirical": x["replaymark_empirical"],
                "replay_all": x["replay_all"],
                "core_empirical_pass": x["core_empirical_pass"],
            } for x in t02["per_replica"]],
            "t02_two_replica_total": t02["two_replica_total"],
            "t02_semantic_replica_agreement": t02["semantic_replica_agreement"],
        },
        "weighted_abstract_reconstruction": t02["weighted_abstract_reconstruction"],
        "interpretation_law": {
            "negative_preregistered_exact_match_is_preserved": True,
            "auxiliary_model_is_not_repaired_post_hoc": True,
            "observed_native_boundary_is_reported_separately": True,
            "weighted_144_state_claim_is_withheld": True,
            "result_dependent_science_rerun_authorized": False,
        },
    }
    result["adjudication_sha256"] = sha(result)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "experimental_integrity": result["experimental_integrity"]["status"],
        "preregistered_exact_match": result["preregistered_expected_frontier_exact_match"]["status"],
        "auxiliary_model_fidelity": result["auxiliary_transition_model_fidelity"]["status"],
        "core_replaymark_observed_native_boundary": result["core_replaymark_observed_native_boundary"]["status"],
        "adjudication_sha256": result["adjudication_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
