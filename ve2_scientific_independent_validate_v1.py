from __future__ import annotations

"""Independent structural validator for VE2 raw scientific stages.

Stdlib only. It has no target-source model and cannot determine a scientific
frontier. It verifies evidence identity, handoff integrity, and no-fallback
execution laws before any post-run analysis is allowed.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

STAGE_SCHEMA = "replaymark.ve2.scientific-native-stage.v1"
ROW_SCHEMA = "replaymark.ve2.scientific-native-row.v1"
BEHAVIOR_SCHEMA = "replaymark.ve2.historical-behavior-capsule.v1"
CERT_SCHEMA = "replaymark.ve2.scientific-reuse-certificate.v1"
EXECUTION_SCHEMA = "replaymark.ve2.behavior-execution-receipt.v1"


def cb(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value: object) -> str:
    return hashlib.sha256(cb(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def fingerprinted(value: dict[str, Any], *, schema: str | None = None) -> None:
    require(isinstance(value, dict), "fingerprinted-not-mapping")
    if schema is not None:
        require(value.get("schema") == schema, "fingerprinted-schema")
    supplied = value.get("fingerprint")
    body = dict(value); body.pop("fingerprint", None)
    require(supplied == sha(body), "fingerprinted-digest")


def load_manifest(path: Path, transition: str) -> dict[str, Any]:
    doc = json.loads(path.read_bytes())
    schema = {"T01":"replaymark.ve2.t01.execution-state-manifest.v1","T02":"replaymark.ve2.t02.execution-state-manifest.v1"}[transition]
    count = {"T01":2,"T02":42}[transition]
    require(doc.get("schema") == schema, "manifest-schema")
    require(doc.get("state_count") == count, "manifest-count")
    rows = doc.get("states")
    require(isinstance(rows, list) and len(rows) == count, "manifest-rows")
    return doc


def load_history(path: Path, manifest: dict[str, Any], transition: str, replica: int) -> dict[str, dict[str, Any]]:
    doc = json.loads(path.read_bytes())
    verify_report(doc, manifest, transition=transition, stage="old_history", replica=replica, history=None)
    return {row["opaque_state_id"]: row for row in doc["rows"]}


def verify_behavior(value: dict[str, Any]) -> None:
    fingerprinted(value, schema=BEHAVIOR_SCHEMA)
    require(value.get("kind") in {"SERVICE","CERTIFIED_NO_ACTION"}, "behavior-kind")
    action = value.get("projected_action")
    require(isinstance(action, dict) and set(action) == {"operation","concrete_target","variant"}, "behavior-action")
    if value["kind"] == "SERVICE":
        require(isinstance(value.get("native_service_event"), dict), "service-native-event")
        require(value.get("absence_certificate") is None, "service-absence")
    else:
        require(value.get("native_service_event") is None, "noop-native-event")
        cert = value.get("absence_certificate")
        require(isinstance(cert, dict) and cert.get("qualified") is True, "noop-absence")
        require(cert.get("qualifying_service_count") == 0, "noop-service-count")
        require(action.get("operation") == "NO_ACTION" and action.get("variant") == "NO_ACTION", "noop-action")


def verify_source_row(row: dict[str, Any], *, stage: str) -> None:
    require(row.get("status") == "COMPLETE_OBSERVED" and row.get("failure") is None, "source-row-incomplete")
    inv_event = row.get("automation_invocation_event")
    invocation = row.get("invocation_witness")
    require(isinstance(inv_event, dict) and isinstance(invocation, dict), "source-invocation")
    fingerprinted(invocation, schema="replaymark.ve2.native-invocation-witness.v1")
    require(inv_event.get("context_id") == invocation.get("action_context_id"), "event-invocation-context")
    services = row.get("qualifying_service_events")
    require(isinstance(services, list) and len(services) <= 1, "source-service-cardinality")
    absence = row.get("absence_certificate")
    require(isinstance(absence, dict), "source-absence")
    require(absence.get("qualifying_service_count") == len(services), "source-absence-count")
    action = row.get("native_projected_action")
    require(isinstance(action, dict) and set(action) == {"operation","concrete_target","variant"}, "source-action")
    if stage == "old_history":
        behavior = row.get("historical_behavior")
        verify_behavior(behavior)
        require(behavior["projected_action"] == action, "old-action-behavior")
        require(behavior["invocation_fingerprint"] == invocation["fingerprint"], "old-invocation-behavior")
        if services:
            require(behavior["kind"] == "SERVICE", "old-service-kind")
        else:
            require(behavior["kind"] == "CERTIFIED_NO_ACTION", "old-noop-kind")
    else:
        require("historical_behavior" not in row, "new-direct-history-leak")


def verify_dispatch(dispatch: dict[str, Any]) -> None:
    require(isinstance(dispatch, dict), "dispatch-shape")
    require(dispatch.get("retry") is False and dispatch.get("fallback") is False, "dispatch-adaptive")
    events = dispatch.get("observed_consequential_service_events")
    require(isinstance(events, list) and len(events) <= 1, "dispatch-service-cardinality")
    require(dispatch.get("attempted") in {True, False}, "dispatch-attempted")


def verify_replaymark_row(row: dict[str, Any], history: dict[str, Any]) -> None:
    require(row.get("status") == "COMPLETE_OBSERVED" and row.get("failure") is None, "replaymark-incomplete")
    behavior = history["historical_behavior"]
    verify_behavior(behavior)
    require(row.get("historical_behavior_fingerprint") == behavior["fingerprint"], "replaymark-history-binding")
    presented = row.get("presented_certificate")
    recomputed = row.get("execution_gate_recomputed_certificate")
    fingerprinted(presented, schema=CERT_SCHEMA)
    fingerprinted(recomputed, schema=CERT_SCHEMA)
    require(cb(presented) == cb(recomputed), "certificate-gate-byte-mismatch")
    require(presented.get("behavior_fingerprint") == behavior["fingerprint"], "certificate-history-binding")
    require(presented.get("execution_performed") is False, "certificate-execution-bit")
    require(presented.get("admission") in {"ADMIT_REUSE","BLOCK_REUSE"}, "certificate-admission")
    receipt = row.get("behavior_gate_receipt")
    fingerprinted(receipt, schema=EXECUTION_SCHEMA)
    require(receipt.get("behavior_fingerprint") == behavior["fingerprint"], "gate-history-binding")
    require(receipt.get("admission") == presented["admission"], "gate-admission-binding")
    require(receipt.get("fallback") is False and receipt.get("retry") is False and receipt.get("regeneration") is False, "gate-adaptive")
    dispatch = row.get("dispatch")
    verify_dispatch(dispatch)
    if presented["admission"] == "BLOCK_REUSE":
        require(receipt.get("service_delegated") is False, "blocked-delegated")
        require(receipt.get("historical_sink_calls") == 0, "blocked-sink")
        require(dispatch.get("attempted") is False, "blocked-dispatch-attempt")
        require(dispatch.get("observed_consequential_service_events") == [], "blocked-observed-sink")
    elif behavior["kind"] == "SERVICE":
        require(receipt.get("service_delegated") is True and receipt.get("historical_sink_calls") == 1, "admitted-service-delegate")
        require(dispatch.get("attempted") is True, "admitted-service-attempt")
    else:
        require(receipt.get("certified_noop_reuse") is True, "admitted-noop-receipt")
        require(dispatch.get("attempted") is False, "admitted-noop-dispatch")
    require(row.get("caller_native_recovery") is False and row.get("regeneration") is False, "replaymark-recovery")


def verify_replay_all_row(row: dict[str, Any], history: dict[str, Any]) -> None:
    require(row.get("status") == "COMPLETE_OBSERVED" and row.get("failure") is None, "replay-all-incomplete")
    behavior = history["historical_behavior"]
    verify_behavior(behavior)
    require(row.get("historical_behavior_fingerprint") == behavior["fingerprint"], "replay-all-history-binding")
    require(row.get("semantic_authorization") is False, "replay-all-semantic-gate")
    require(row.get("caller_native_recovery") is False and row.get("regeneration") is False, "replay-all-recovery")
    dispatch = row.get("dispatch")
    verify_dispatch(dispatch)
    require(dispatch.get("attempted") == (behavior["kind"] == "SERVICE"), "replay-all-dispatch-law")


def verify_report(
    doc: dict[str, Any],
    manifest: dict[str, Any],
    *,
    transition: str,
    stage: str,
    replica: int,
    history: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    require(doc.get("schema") == STAGE_SCHEMA, "report-schema")
    supplied = doc.get("result_sha256")
    body = dict(doc); body.pop("result_sha256", None)
    require(supplied == sha(body), "report-digest")
    require(doc.get("transition") == transition and doc.get("stage") == stage and doc.get("replica") == replica, "report-identity")
    require(doc.get("status") == "SEALED_RAW_STAGE", "report-status")
    require(doc.get("state_count") == manifest["state_count"], "report-count")
    require(doc.get("manifest_canonical_sha256") == sha(manifest), "report-manifest-canonical")
    require(doc.get("scientific_summary_emitted") is False and doc.get("frontier_result_seen") is False, "report-summary-firewall")
    rows = doc.get("rows")
    require(isinstance(rows, list) and len(rows) == manifest["state_count"], "report-rows")
    expected = [(r["opaque_state_id"], r["fixture"]) for r in manifest["states"]]
    observed = [(r.get("opaque_state_id"), r.get("fixture")) for r in rows]
    require(observed == expected, "row-order-or-fixture")
    for row in rows:
        require(row.get("schema") == ROW_SCHEMA, "row-schema")
        row_hash = row.get("row_sha256")
        rb = dict(row); rb.pop("row_sha256", None)
        require(row_hash == sha(rb), "row-digest")
        require(row.get("transition") == transition and row.get("stage") == stage and row.get("replica") == replica, "row-identity")
        if stage in {"old_history","new_direct"}:
            verify_source_row(row, stage=stage)
        else:
            require(history is not None and row["opaque_state_id"] in history, "replay-history-row")
            if stage == "replaymark":
                verify_replaymark_row(row, history[row["opaque_state_id"]])
            else:
                verify_replay_all_row(row, history[row["opaque_state_id"]])
    return {
        "schema":"replaymark.ve2.raw-stage-independent-validation.v1",
        "status":"PASS",
        "transition":transition,
        "stage":stage,
        "replica":replica,
        "stage_result_sha256":supplied,
        "rows_verified":len(rows),
        "scientific_summary_emitted":False,
    }


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--transition", choices=["T01","T02"], required=True)
    ap.add_argument("--stage", choices=["old_history","new_direct","replaymark","replay_all"], required=True)
    ap.add_argument("--replica", type=int, choices=[0,1], required=True)
    ap.add_argument("--history")
    ap.add_argument("--out", required=True)
    args=ap.parse_args()
    manifest=load_manifest(Path(args.manifest), args.transition)
    history=None
    if args.stage in {"replaymark","replay_all"}:
        require(bool(args.history), "history-required")
        history=load_history(Path(args.history), manifest, args.transition, args.replica)
    else:
        require(args.history is None, "history-forbidden-source-stage")
    doc=json.loads(Path(args.report).read_bytes())
    result=verify_report(doc, manifest, transition=args.transition, stage=args.stage, replica=args.replica, history=history)
    result["validation_sha256"]=sha(result)
    Path(args.out).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"PASS","transition":args.transition,"stage":args.stage,"replica":args.replica,"rows_verified":result["rows_verified"]},sort_keys=True))


if __name__=="__main__":
    main()
