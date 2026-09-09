from __future__ import annotations

"""Aggregate exactly two independently hosted HA-C3 validation records."""

import argparse
import json
from pathlib import Path

EXPECTED_PER_REPLICA = {
    "decisions": 30,
    "admit": 10,
    "block": 20,
    "safe_history_executed": 10,
    "blocked_native_restored": 20,
    "unsafe_historical_calls": 0,
    "unnecessary_native_recoveries": 0,
    "certificate_raw_mismatch_admitted": 0,
    "direct_reference_disagreements": 0,
    "n2b_cutovers": 10,
}
EXPECTED_TOTAL = {key: value * 2 for key, value in EXPECTED_PER_REPLICA.items()}
for key in (
    "unsafe_historical_calls",
    "unnecessary_native_recoveries",
    "certificate_raw_mismatch_admitted",
    "direct_reference_disagreements",
):
    EXPECTED_TOTAL[key] = 0


def aggregate(paths: list[Path]) -> dict[str, object]:
    if len(paths) != 2:
        raise AssertionError(("HA-C3 requires exactly two replica validations", len(paths)))
    values = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    replicas = sorted(int(value["replica"]) for value in values)
    if replicas != [0, 1]:
        raise AssertionError(("replica identities", replicas))
    for value in values:
        if value.get("schema") != "replaymark.ha-c3.independent-validation.v1":
            raise AssertionError("foreign HA-C3 validation schema")
        if value.get("status") != "PASS":
            raise AssertionError(("replica did not pass", value.get("replica"), value.get("failure")))
        if value.get("metrics") != EXPECTED_PER_REPLICA:
            raise AssertionError(("per-replica metrics changed", value.get("replica"), value.get("metrics"), EXPECTED_PER_REPLICA))

    total = {key: 0 for key in EXPECTED_TOTAL}
    for value in values:
        for key in total:
            total[key] += int(value["metrics"][key])
    if total != EXPECTED_TOTAL:
        raise AssertionError(("replicated aggregate metrics", total, EXPECTED_TOTAL))

    criteria = {
        "both_replicas_complete": True,
        "planned_decisions_60": total["decisions"] == 60,
        "safe_history_executed_20": total["safe_history_executed"] == 20,
        "blocked_native_restored_40": total["blocked_native_restored"] == 40,
        "unsafe_historical_calls_zero": total["unsafe_historical_calls"] == 0,
        "unnecessary_native_recoveries_zero": total["unnecessary_native_recoveries"] == 0,
        "certificate_raw_mismatch_admitted_zero": total["certificate_raw_mismatch_admitted"] == 0,
        "direct_reference_disagreements_zero": total["direct_reference_disagreements"] == 0,
        "n2b_cutovers_20": total["n2b_cutovers"] == 20,
    }
    if not all(criteria.values()):
        raise AssertionError(("promotion criterion failed", criteria))
    return {
        "schema": "replaymark.ha-c3.replicated-aggregate.v1",
        "status": "PASS",
        "replicas": replicas,
        "metrics": total,
        "criteria": criteria,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("validations", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    paths = [Path(value) for value in args.validations]
    try:
        result = aggregate(paths)
        rc = 0
    except Exception as exc:
        result = {
            "schema": "replaymark.ha-c3.replicated-aggregate.v1",
            "status": "FAIL",
            "failure": f"{type(exc).__name__}: {exc}",
        }
        rc = 1
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
