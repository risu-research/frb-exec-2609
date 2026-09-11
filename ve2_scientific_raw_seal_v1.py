from __future__ import annotations

"""Seal all sixteen VE2 raw stages before any scientific adjudication.

This module is stdlib-only and answer-blind. It verifies stage and independent
validation identities/digests, fixes the exact serial order, and emits the sole
handoff that authorizes post-run frontier access.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "replaymark.ve2.all-raw-stage-artifacts-sealed.v1"
STAGE_SCHEMA = "replaymark.ve2.scientific-native-stage.v1"
VALIDATION_SCHEMA = "replaymark.ve2.raw-stage-independent-validation.v1"
STAGE_KEYS = [
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
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value: object) -> str:
    return hashlib.sha256(cb(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_key(key: str) -> tuple[str, int, str]:
    parts = key.split("_")
    transition = parts[0]
    replica = int(parts[1][1:])
    stage = "_".join(parts[2:]).lower()
    if transition not in {"T01", "T02"} or replica not in {0, 1} or stage not in {
        "old_history", "new_direct", "replaymark", "replay_all"
    }:
        raise AssertionError(("stage-key", key))
    return transition, replica, stage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--authority-head", required=True)
    args = ap.parse_args()
    root = Path(args.raw_dir)
    rows: list[dict[str, Any]] = []
    scientific_cells = 0
    for key in STAGE_KEYS:
        transition, replica, stage = parse_key(key)
        report_name = f"{key}_REPORT.json"
        validation_name = f"{key}_VALIDATION.json"
        report_path = root / report_name
        validation_path = root / validation_name
        if not report_path.is_file() or not validation_path.is_file():
            raise AssertionError(("raw-stage-file-missing", key))
        report = json.loads(report_path.read_bytes())
        validation = json.loads(validation_path.read_bytes())
        if report.get("schema") != STAGE_SCHEMA or report.get("status") != "SEALED_RAW_STAGE":
            raise AssertionError(("raw-stage-report-status", key))
        if report.get("transition") != transition or report.get("replica") != replica or report.get("stage") != stage:
            raise AssertionError(("raw-stage-report-identity", key))
        report_body = dict(report)
        report_result = report_body.pop("result_sha256", None)
        if report_result != sha(report_body):
            raise AssertionError(("raw-stage-report-result-digest", key))
        if validation.get("schema") != VALIDATION_SCHEMA or validation.get("status") != "PASS":
            raise AssertionError(("raw-stage-validation-status", key))
        if validation.get("transition") != transition or validation.get("replica") != replica or validation.get("stage") != stage:
            raise AssertionError(("raw-stage-validation-identity", key))
        if validation.get("stage_result_sha256") != report_result:
            raise AssertionError(("raw-stage-validation-binding", key))
        if report.get("scientific_summary_emitted") is not False or report.get("frontier_result_seen") is not False:
            raise AssertionError(("raw-stage-firewall", key))
        count = int(report.get("state_count"))
        expected = 2 if transition == "T01" else 42
        if count != expected or validation.get("rows_verified") != expected:
            raise AssertionError(("raw-stage-row-count", key))
        scientific_cells += count
        rows.append({
            "stage_key": key,
            "report_file": report_name,
            "validation_file": validation_name,
            "report_file_sha256": file_sha(report_path),
            "validation_file_sha256": file_sha(validation_path),
            "stage_result_sha256": report_result,
            "rows_verified": expected,
        })
    if scientific_cells != 352:
        raise AssertionError(("scientific-cell-accounting", scientific_cells))
    result = {
        "schema": SCHEMA,
        "status": "ALL_16_RAW_STAGES_SEALED",
        "authority_head": args.authority_head,
        "stages": rows,
        "raw_stage_artifacts": 16,
        "scientific_cells": 352,
        "scientific_summary_emitted": False,
        "expected_frontier_read_before_raw_seal": False,
        "successful_subset_carry_forward": False,
        "result_dependent_rerun_authorized": False,
    }
    result["seal_sha256"] = sha(result)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "scientific_cells": 352, "seal_sha256": result["seal_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
