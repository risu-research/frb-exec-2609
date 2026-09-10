from __future__ import annotations

"""Replicated aggregate for SA1 source-adequacy closure."""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("validation0", type=Path)
    parser.add_argument("validation1", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(args.validation0.read_text()), json.loads(args.validation1.read_text())]
    if {row.get("replica") for row in rows} != {0, 1}:
        raise AssertionError("SA1 aggregate requires replicas 0 and 1 exactly once")
    rows.sort(key=lambda row: row["replica"])
    total_exact = sum(int(row.get("exact_rows", 0)) for row in rows)
    total_calls = sum(int(row.get("observed_exact_service_calls", 0)) for row in rows)
    total_no_calls = sum(int(row.get("observed_no_consequential_call_rows", 0)) for row in rows)
    passed = (
        all(row.get("pass") is True for row in rows)
        and all(row.get("total_rows") == 32 for row in rows)
        and total_exact == 64
        and total_calls == 48
        and total_no_calls == 16
    )
    result = {
        "schema": "replaymark.sa1.replicated-aggregate.v1",
        "pass": passed,
        "replicas": [
            {
                "replica": row["replica"],
                "pass": row["pass"],
                "exact_rows": row["exact_rows"],
                "service_calls": row["observed_exact_service_calls"],
                "no_call_rows": row["observed_no_consequential_call_rows"],
            }
            for row in rows
        ],
        "total_native_cells": 64,
        "exact_frozen_table_agreements": total_exact,
        "observed_exact_service_calls": total_calls,
        "observed_no_consequential_call_rows": total_no_calls,
        "unexpected_or_missing_native_outcomes": 64 - total_exact,
    }
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
