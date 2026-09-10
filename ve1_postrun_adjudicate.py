from __future__ import annotations

"""Independent post-run VE1 scientific adjudicator.

Runs only after all stage capsules are sealed. It imports no ReplayMark,
Home Assistant, AgentMark, source parser, or execution gate.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping

EXPECTED_ROWS_SHA256 = "0ef80acf64bcc192837ee17f6b57ab2e79ee4182c9b793d8cf388d59d2558c20"
CLIMATE_ENTITY = "climate.agentmark_thermostat"
PRESETS = ("away", "home", "comfort", "sleep")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"{name} must be a mapping")
    return value


def _desired(presence: bool, motion: bool, night: bool) -> str:
    return "sleep" if night else ("away" if not presence else ("comfort" if motion else "home"))


def _expected_rows() -> list[dict[str, object]]:
    rows = []
    for presence in (False, True):
        for motion in (False, True):
            for night in (False, True):
                wanted = _desired(presence, motion, night)
                for current in PRESETS:
                    action = {"operation": "climate.set_preset_mode", "target": CLIMATE_ENTITY, "service_data": {"preset_mode": wanted}}
                    new_action = action if current != wanted else {"operation": "NO_ACTION"}
                    rows.append({"state_id": f"p{int(presence)}-m{int(motion)}-n{int(night)}-cur-{current}", "presence": presence, "motion": motion, "night": night, "current_preset": current, "target_preset": wanted, "old_expected_action": action, "new_expected_action": new_action, "compatibility": "COMPATIBLE_ACROSS_VERSION" if new_action == action else "RETIRED_BY_UPDATE"})
    digest = hashlib.sha256(_canonical_bytes(rows)).hexdigest()
    if digest != EXPECTED_ROWS_SHA256:
        raise AssertionError(("frozen expected-row digest mismatch", digest))
    return rows


def _load(path: str, stage: str, replica: int) -> Mapping[str, object]:
    value = _mapping(json.loads(Path(path).read_text(encoding="utf-8")), "stage report")
    if value.get("schema") != "replaymark.ve1.native-stage.v1" or value.get("stage") != stage or int(value.get("replica")) != replica or value.get("fatal_failure") is not None:
        raise AssertionError(("foreign, mismatched, or failed VE1 stage", stage, replica))
    rows = list(value.get("rows") or [])
    if len(rows) != 32 or [r.get("opaque_state_id") for r in rows] != [f"VE1-S{i:02d}" for i in range(32)]:
        raise AssertionError(("incomplete or reordered stage population", stage, replica))
    return value


def _projection_from_event(event: object) -> dict[str, object]:
    e = _mapping(event, "service event")
    if e.get("domain") != "climate" or e.get("service") != "set_preset_mode":
        raise AssertionError("foreign consequential service")
    data = _mapping(e.get("service_data"), "service_data")
    raw_target = data.get("entity_id")
    targets = [raw_target] if isinstance(raw_target, str) else list(raw_target or [])
    if targets != [CLIMATE_ENTITY]:
        raise AssertionError(("foreign service target", targets))
    return {"operation": "climate.set_preset_mode", "target": CLIMATE_ENTITY, "service_data": {"preset_mode": str(data["preset_mode"])}}


def _native_projection(row: Mapping[str, object], field: str = "qualifying_service_events") -> dict[str, object]:
    if row.get("status") != "COMPLETE_OBSERVED":
        raise AssertionError(("row is not complete", row.get("opaque_state_id"), row.get("status")))
    events = list(row.get(field) or [])
    if len(events) == 0:
        return {"operation": "NO_ACTION"}
    if len(events) != 1:
        raise AssertionError(("ambiguous native event cardinality", row.get("opaque_state_id"), len(events)))
    return _projection_from_event(events[0])


def _post_preset(observation: object) -> str:
    return str(_mapping(_mapping(observation, "post observation")["snapshot"], "post snapshot")["climate_preset"])


def _caller_projection(value: object) -> dict[str, object]:
    c = _mapping(value, "caller-native recovery")
    if c.get("status") != "COMPLETE_OBSERVED":
        raise AssertionError("caller-native recovery is incomplete")
    events = list(c.get("qualifying_service_events") or [])
    if not events:
        return {"operation": "NO_ACTION"}
    if len(events) != 1:
        raise AssertionError("caller-native recovery event cardinality is ambiguous")
    return _projection_from_event(events[0])


def _row_fixture(row: Mapping[str, object]) -> tuple[bool, bool, bool, str]:
    f = _mapping(row["fixture"], "fixture")
    return bool(f["presence"]), bool(f["motion"]), bool(f["night"]), str(f["current_preset"])


def _expected_key(row: Mapping[str, object]) -> tuple[bool, bool, bool, str]:
    return bool(row["presence"]), bool(row["motion"]), bool(row["night"]), str(row["current_preset"])


def _rows_by_fixture(report: Mapping[str, object]) -> dict[tuple[bool, bool, bool, str], Mapping[str, object]]:
    out = {}
    for row in report["rows"]:
        key = _row_fixture(row)
        if key in out:
            raise AssertionError(("duplicate raw fixture", key))
        out[key] = row
    return out


def adjudicate_one(replica: int, old_report: Mapping[str, object], direct_report: Mapping[str, object], replaymark_report: Mapping[str, object], replay_all_report: Mapping[str, object], expected_rows: list[dict[str, object]]) -> dict[str, object]:
    old, direct, rm, ra = map(_rows_by_fixture, (old_report, direct_report, replaymark_report, replay_all_report))
    keys = [_expected_key(e) for e in expected_rows]
    if set(old) != set(keys) or set(direct) != set(keys) or set(rm) != set(keys) or set(ra) != set(keys):
        raise AssertionError("stage fixture populations are not identical")
    metrics = {"states": 32, "old_native_source_agreement": 0, "new_direct_source_agreement": 0, "compatible_history_executed": 0, "retired_history_blocked": 0, "unsafe_retired_historical_calls": 0, "unnecessary_native_recoveries": 0, "direct_reference_disagreements": 0, "replay_all_retired_calls": 0, "version_lock_compatible_histories_discarded": 0}
    rows_out, failures = [], []
    for expected in expected_rows:
        key = _expected_key(expected)
        o, d, r, a = old[key], direct[key], rm[key], ra[key]
        state_id, wanted = str(o["opaque_state_id"]), str(expected["target_preset"])
        old_expected, new_expected = expected["old_expected_action"], expected["new_expected_action"]
        compatible = expected["compatibility"] == "COMPATIBLE_ACROSS_VERSION"
        row_result = {"opaque_state_id": state_id, "fixture": {"presence": key[0], "motion": key[1], "night": key[2], "current_preset": key[3]}, "expected_class": expected["compatibility"], "checks": {}}
        try:
            old_actual = _native_projection(o)
            old_ok = old_actual == old_expected
            row_result["checks"]["old_native_source_agreement"] = old_ok
            metrics["old_native_source_agreement"] += int(old_ok)
            direct_actual = _native_projection(d)
            direct_ok = direct_actual == new_expected
            row_result["checks"]["new_direct_source_agreement"] = direct_ok
            metrics["new_direct_source_agreement"] += int(direct_ok)
            if compatible:
                metrics["version_lock_compatible_histories_discarded"] += 1
            if r.get("status") == "COMPLETE_PROTOCOL_NONEXECUTABLE":
                row_result["checks"]["replaymark_executable"] = False
                failures.append(f"{state_id}: ReplayMark nonexecutable from sealed history")
            elif r.get("status") != "COMPLETE_OBSERVED":
                row_result["checks"]["replaymark_executable"] = False
                failures.append(f"{state_id}: ReplayMark row {r.get('status')}")
            else:
                row_result["checks"]["replaymark_executable"] = True
                receipt = _mapping(r["gate_receipt"], "gate receipt")
                observed_admission = str(receipt["admission_disposition"])
                sink, caller = list(r.get("historical_sink_events") or []), r.get("caller_native")
                if compatible:
                    good = observed_admission == "ADMIT_REUSE" and receipt.get("execution_performed") is True and len(sink) == 1 and _projection_from_event(sink[0]) == old_expected and caller is None
                    row_result["checks"]["replaymark_compatible_history_executed"] = good
                    metrics["compatible_history_executed"] += int(good)
                    metrics["unnecessary_native_recoveries"] += int(caller is not None)
                else:
                    unsafe = observed_admission != "BLOCK_REUSE" or receipt.get("execution_performed") is not False or len(sink) != 0
                    if unsafe:
                        metrics["unsafe_retired_historical_calls"] += max(1, len(sink))
                    recovery_ok = caller is not None and _caller_projection(caller) == new_expected
                    good = not unsafe and recovery_ok
                    row_result["checks"]["replaymark_retired_history_blocked"] = good
                    metrics["retired_history_blocked"] += int(good)
                final_rm = _post_preset(r["post_boundary_observation"])
                final_direct = _post_preset(d["post_boundary_observation"])
                consequence_ok = final_rm == final_direct == wanted
                row_result["checks"]["direct_reference_consequence_agreement"] = consequence_ok
                metrics["direct_reference_disagreements"] += int(not consequence_ok)
            if a.get("status") == "COMPLETE_PROTOCOL_NONEXECUTABLE":
                row_result["checks"]["replay_all_executable"] = False
                failures.append(f"{state_id}: Replay-All nonexecutable from sealed history")
            elif a.get("status") != "COMPLETE_OBSERVED":
                row_result["checks"]["replay_all_executable"] = False
                failures.append(f"{state_id}: Replay-All row {a.get('status')}")
            else:
                row_result["checks"]["replay_all_executable"] = True
                events = list(a.get("sink_events") or [])
                replay_all_ok = len(events) == 1 and _projection_from_event(events[0]) == old_expected
                row_result["checks"]["replay_all_exact_historical_dispatch"] = replay_all_ok
                if not compatible and replay_all_ok:
                    metrics["replay_all_retired_calls"] += 1
            for name, passed in row_result["checks"].items():
                if isinstance(passed, bool) and not passed and name not in {"replaymark_executable", "replay_all_executable"}:
                    failures.append(f"{state_id}: {name}=false")
        except Exception as exc:
            failures.append(f"{state_id}: {type(exc).__name__}: {exc}")
            row_result["adjudication_error"] = f"{type(exc).__name__}: {exc}"
        rows_out.append(row_result)
    promotion = metrics["old_native_source_agreement"] == 32 and metrics["new_direct_source_agreement"] == 32 and metrics["compatible_history_executed"] == 24 and metrics["retired_history_blocked"] == 8 and metrics["unsafe_retired_historical_calls"] == 0 and metrics["unnecessary_native_recoveries"] == 0 and metrics["direct_reference_disagreements"] == 0 and metrics["replay_all_retired_calls"] == 8 and metrics["version_lock_compatible_histories_discarded"] == 24
    return {"schema": "replaymark.ve1.independent-replica-adjudication.v1", "replica": replica, "status": "PASS" if promotion else "SCIENTIFIC_FAIL", "promotion": promotion, "metrics": metrics, "scientific_failures": failures, "rows": rows_out}


def main() -> None:
    parser = argparse.ArgumentParser()
    for replica in (0, 1):
        parser.add_argument(f"--r{replica}-old", required=True)
        parser.add_argument(f"--r{replica}-direct", required=True)
        parser.add_argument(f"--r{replica}-replaymark", required=True)
        parser.add_argument(f"--r{replica}-replay-all", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    expected = _expected_rows()
    replicas = []
    for replica in (0, 1):
        replicas.append(adjudicate_one(replica, _load(getattr(args, f"r{replica}_old"), "old_history", replica), _load(getattr(args, f"r{replica}_direct"), "new_direct", replica), _load(getattr(args, f"r{replica}_replaymark"), "replaymark", replica), _load(getattr(args, f"r{replica}_replay_all"), "replay_all", replica), expected))
    totals = {"state_instances": 64, "compatible_history_executed": sum(r["metrics"]["compatible_history_executed"] for r in replicas), "retired_history_blocked": sum(r["metrics"]["retired_history_blocked"] for r in replicas), "unsafe_retired_historical_calls": sum(r["metrics"]["unsafe_retired_historical_calls"] for r in replicas), "unnecessary_native_recoveries": sum(r["metrics"]["unnecessary_native_recoveries"] for r in replicas), "direct_reference_disagreements": sum(r["metrics"]["direct_reference_disagreements"] for r in replicas), "replay_all_retired_calls": sum(r["metrics"]["replay_all_retired_calls"] for r in replicas), "version_lock_compatible_histories_discarded": sum(r["metrics"]["version_lock_compatible_histories_discarded"] for r in replicas)}
    target = {"state_instances": 64, "compatible_history_executed": 48, "retired_history_blocked": 16, "unsafe_retired_historical_calls": 0, "unnecessary_native_recoveries": 0, "direct_reference_disagreements": 0, "replay_all_retired_calls": 16, "version_lock_compatible_histories_discarded": 48}
    promoted = all(r["promotion"] for r in replicas) and totals == target
    result = {"schema": "replaymark.ve1.independent-replicated-adjudication.v1", "status": "PASS" if promoted else "SCIENTIFIC_FAIL", "expected_rows_sha256": EXPECTED_ROWS_SHA256, "replicas": replicas, "replicated_metrics": totals, "promotion": promoted}
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "promotion": promoted}, sort_keys=True))


if __name__ == "__main__":
    main()
