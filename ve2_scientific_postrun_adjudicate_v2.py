from __future__ import annotations

"""Prospective v2 post-run adjudicator.

Scientific semantics remain frozen in v1. V2 repairs only result-accounting
terminology after pre-science audit: there are 16 raw stage artifacts and 352
scientific row/cell instances (T01: 16, T02: 336) across both replicas.
"""

import argparse
import json
from pathlib import Path

import ve2_scientific_postrun_adjudicate_v1 as base

SCIENTIFIC_CELLS = 352
RAW_STAGE_ARTIFACTS = 16
T01_ROW_INSTANCES = 16
T02_ROW_INSTANCES = 336


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--raw-seal", required=True)
    ap.add_argument("--t01-frontier", required=True)
    ap.add_argument("--t02-frontier", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    seal, docs = base.verify_raw_seal(Path(args.raw_seal), raw_dir)
    base.require(len(docs) == RAW_STAGE_ARTIFACTS, "raw-stage-artifact-count")

    # Answer-bearing frontier files remain unopened until the complete raw seal
    # and all 16 independent stage validations have passed above.
    t01_path = Path(args.t01_frontier)
    t02_path = Path(args.t02_frontier)
    base.require(base.file_sha(t01_path) == base.T01_FRONTIER_SHA, "t01-frontier-raw-sha")
    base.require(base.file_sha(t02_path) == base.T02_FRONTIER_SHA, "t02-frontier-raw-sha")
    t01_expected = json.loads(t01_path.read_bytes())
    t02_expected = json.loads(t02_path.read_bytes())

    t01 = base.t01_adjudicate(docs, t01_expected)
    t02 = base.t02_adjudicate(docs, t02_expected)
    result = {
        "schema": "replaymark.ve2.independent-postrun-adjudication.v2",
        "status": "PASS" if t01["status"] == "PASS" and t02["status"] == "PASS" else "FAIL",
        "raw_seal_sha256": seal["seal_sha256"],
        "t01": t01,
        "t02": t02,
        "accounting": {
            "raw_stage_artifacts": RAW_STAGE_ARTIFACTS,
            "scientific_cells": SCIENTIFIC_CELLS,
            "scientific_row_instances": SCIENTIFIC_CELLS,
            "t01_row_instances": T01_ROW_INSTANCES,
            "t02_row_instances": T02_ROW_INSTANCES,
            "formula": "(2 states * 4 arms * 2 replicas) + (42 states * 4 arms * 2 replicas) = 352",
        },
        "frontier_read_only_after_raw_seal": True,
        "result_dependent_rerun_authorized": False,
    }
    base.require(
        result["accounting"]["t01_row_instances"] + result["accounting"]["t02_row_instances"]
        == result["accounting"]["scientific_cells"],
        "scientific-accounting-sum",
    )
    result["adjudication_sha256"] = base.sha(result)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "raw_stage_artifacts": RAW_STAGE_ARTIFACTS,
        "scientific_cells": SCIENTIFIC_CELLS,
        "adjudication_sha256": result["adjudication_sha256"],
    }, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
