from __future__ import annotations

"""Transport-only support for VE1 scientific workflow v2.

This module is transport-only and has no dependency on ReplayMark, Home Assistant, or experiment target semantics.
It creates and validates provenance/failure envelopes only.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _write_json(path: str | Path, value: Any) -> None:
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix().encode()
        body = path.read_bytes()
        digest.update(len(rel).to_bytes(8, "big"))
        digest.update(rel)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def cmd_guard(args: argparse.Namespace) -> None:
    seal = json.loads(Path(args.seal).read_text(encoding="utf-8"))
    marker = json.loads(Path(args.marker).read_text(encoding="utf-8"))
    static_pass = json.loads(Path(args.static_pass).read_text(encoding="utf-8"))
    seal_sha = _file_sha256(args.seal)
    static_pass_sha = _file_sha256(args.static_pass)

    assert seal["schema"] == "replaymark.ve1.e0q-result-seal.v1"
    assert seal["status"] == "PASS"
    assert seal["scientific_result_opened"] is False
    assert seal["rerun_authorized"] is False
    assert seal["private_constitution_head"] == args.private
    assert isinstance(seal["artifact_sha256"], str) and len(seal["artifact_sha256"]) == 64

    assert static_pass["schema"] == "replaymark.ve1.science-workflow-static-pass.v2"
    assert static_pass["status"] == "PASS"
    assert static_pass["scientific_result_opened"] is False
    assert static_pass["source_candidate_head"] == args.source_candidate
    assert static_pass["private_constitution_head"] == args.private
    for path, expected in static_pass["source_files_sha256"].items():
        assert _file_sha256(path) == expected, (path, _file_sha256(path), expected)

    expected_marker = {
        "schema": "replaymark.ve1.scientific-authority-open.v2",
        "authority": "AUTHORITATIVE_FIRST_COMPLETE_VERSION_EVOLUTION",
        "source_freeze_public_head": args.parent,
        "source_candidate_head": args.source_candidate,
        "e0q_result_seal_sha256": seal_sha,
        "static_pass_seal_sha256": static_pass_sha,
        "private_constitution_head": args.private,
        "pre_input_failure_run_id": 34465860182,
        "rerun_authorized": False,
    }
    assert marker == expected_marker, (marker, expected_marker)

    output = Path(args.github_output)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(f"source_freeze_head={args.parent}\n")
        handle.write(f"source_candidate_head={args.source_candidate}\n")
        handle.write(f"capsule_source_head={seal['capsule_source_head']}\n")
        handle.write(f"e0q_seal_sha256={seal_sha}\n")
        handle.write(f"static_pass_sha256={static_pass_sha}\n")
        handle.write("open=true\n")


def cmd_verify_bt(args: argparse.Namespace) -> None:
    root = Path(args.root)
    manifest = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    assert manifest == args.manifest_sha256
    parsed = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert parsed["domain"] == "better_thermostat"
    assert parsed["version"] == args.version
    assert _tree_sha256(root) == args.tree_sha256


def cmd_fallback_stage(args: argparse.Namespace) -> None:
    value = {
        "schema": "replaymark.ve1.native-stage.v1",
        "mode": "AUTHORITATIVE_FIRST_COMPLETE_STAGE",
        "stage": args.stage,
        "replica": args.replica,
        "fatal_failure": f"RUNNER_DID_NOT_EMIT_REPORT exit={args.exit_code}",
        "rows": [],
        "scientific_summary_emitted": False,
    }
    _write_json(args.out, value)


def cmd_stage_provenance(args: argparse.Namespace) -> None:
    value = {
        "schema": "replaymark.ve1.stage-public-provenance.v2",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "execution_head": os.environ["GITHUB_SHA"],
        "source_freeze_public_head": os.environ["SOURCE_FREEZE_HEAD"],
        "source_candidate_head": os.environ["SOURCE_CANDIDATE_HEAD"],
        "capsule_source_head": os.environ["CAPSULE_SOURCE_HEAD"],
        "e0q_result_seal_sha256": os.environ["E0Q_SEAL_SHA256"],
        "static_pass_seal_sha256": os.environ["STATIC_PASS_SHA256"],
        "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "replica": args.replica,
        "stage": args.stage,
        "blueprint_git_blob_sha1": args.blueprint_blob,
        "producer_exit": args.producer_exit,
        "structural_validator_exit": args.validator_exit,
        "pre_input_failure_run_preserved": 34465860182,
        "rerun_authorized": False,
    }
    _write_json(Path(args.outdir) / "PROVENANCE.json", value)


def cmd_replica_manifest(args: argparse.Namespace) -> None:
    stage_dirs = ["old_history", "new_direct", "replaymark", "replay_all"]
    stage_checksums: dict[str, str | None] = {}
    root = Path(args.results)
    for stage in stage_dirs:
        path = root / stage / "CHECKSUMS.sha256"
        stage_checksums[stage] = _file_sha256(path) if path.exists() else None
    value = {
        "schema": "replaymark.ve1.replica-first-complete-manifest.v2",
        "authority": "AUTHORITATIVE_FIRST_COMPLETE_VERSION_EVOLUTION",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "execution_head": os.environ["GITHUB_SHA"],
        "source_freeze_public_head": os.environ["SOURCE_FREEZE_HEAD"],
        "source_candidate_head": os.environ["SOURCE_CANDIDATE_HEAD"],
        "capsule_source_head": os.environ["CAPSULE_SOURCE_HEAD"],
        "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "replica": args.replica,
        "stage_order": stage_dirs,
        "stage_checksums_sha256": stage_checksums,
        "pre_input_failure_run_preserved": 34465860182,
        "rerun_authorized": False,
    }
    _write_json(root / "REPLICA_MANIFEST.json", value)


def cmd_verify_replica(args: argparse.Namespace) -> None:
    root = Path(args.root)
    manifest = json.loads((root / "REPLICA_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "replaymark.ve1.replica-first-complete-manifest.v2"
    assert manifest["replica"] == args.replica
    assert manifest["stage_order"] == ["old_history", "new_direct", "replaymark", "replay_all"]
    for stage in manifest["stage_order"]:
        checksum = root / stage / "CHECKSUMS.sha256"
        assert checksum.is_file(), stage
        assert _file_sha256(checksum) == manifest["stage_checksums_sha256"][stage], stage
        lines = checksum.read_text(encoding="utf-8").splitlines()
        assert lines, stage
        for line in lines:
            expected, rel = line.split(None, 1)
            rel = rel.lstrip("* ")
            path = root / stage / rel
            assert path.is_file(), (stage, rel)
            assert _file_sha256(path) == expected, (stage, rel)


def cmd_fallback_adjudication(args: argparse.Namespace) -> None:
    value = {
        "schema": "replaymark.ve1.independent-replicated-adjudication.v1",
        "status": "INFRASTRUCTURE_INCOMPLETE",
        "promotion": False,
        "failure": f"adjudicator did not produce output; exit={args.exit_code}",
    }
    _write_json(args.out, value)


def cmd_aggregate_provenance(args: argparse.Namespace) -> None:
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    value = {
        "schema": "replaymark.ve1.first-complete-public-provenance.v2",
        "authority": "AUTHORITATIVE_FIRST_COMPLETE_VERSION_EVOLUTION",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "execution_head": os.environ["GITHUB_SHA"],
        "source_freeze_public_head": os.environ["SOURCE_FREEZE_HEAD"],
        "source_candidate_head": os.environ["SOURCE_CANDIDATE_HEAD"],
        "capsule_source_head": os.environ["CAPSULE_SOURCE_HEAD"],
        "e0q_result_seal_sha256": os.environ["E0Q_SEAL_SHA256"],
        "static_pass_seal_sha256": os.environ["STATIC_PASS_SHA256"],
        "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "scientific_status": result.get("status"),
        "promotion": bool(result.get("promotion", False)),
        "pre_input_failure_run_preserved": 34465860182,
        "rerun_authorized": False,
    }
    _write_json(args.out, value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("guard")
    p.add_argument("--seal", required=True)
    p.add_argument("--marker", required=True)
    p.add_argument("--static-pass", required=True)
    p.add_argument("--private", required=True)
    p.add_argument("--parent", required=True)
    p.add_argument("--source-candidate", required=True)
    p.add_argument("--github-output", required=True)
    p.set_defaults(func=cmd_guard)

    p = sub.add_parser("verify-bt")
    p.add_argument("--root", required=True)
    p.add_argument("--manifest-sha256", required=True)
    p.add_argument("--tree-sha256", required=True)
    p.add_argument("--version", required=True)
    p.set_defaults(func=cmd_verify_bt)

    p = sub.add_parser("fallback-stage")
    p.add_argument("--stage", required=True)
    p.add_argument("--replica", type=int, required=True)
    p.add_argument("--exit-code", type=int, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_fallback_stage)

    p = sub.add_parser("stage-provenance")
    p.add_argument("--stage", required=True)
    p.add_argument("--replica", type=int, required=True)
    p.add_argument("--blueprint-blob", required=True)
    p.add_argument("--producer-exit", type=int, required=True)
    p.add_argument("--validator-exit", type=int, required=True)
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_stage_provenance)

    p = sub.add_parser("replica-manifest")
    p.add_argument("--replica", type=int, required=True)
    p.add_argument("--results", required=True)
    p.set_defaults(func=cmd_replica_manifest)

    p = sub.add_parser("verify-replica")
    p.add_argument("--root", required=True)
    p.add_argument("--replica", type=int, required=True)
    p.set_defaults(func=cmd_verify_replica)

    p = sub.add_parser("fallback-adjudication")
    p.add_argument("--exit-code", type=int, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_fallback_adjudication)

    p = sub.add_parser("aggregate-provenance")
    p.add_argument("--result", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_aggregate_provenance)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
