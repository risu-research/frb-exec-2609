from __future__ import annotations

"""Build the VE2 pre-science runtime bundle without opening scientific results.

The builder verifies immutable manifest and upstream-blueprint byte identities,
projects only label-free runtime manifest fields, and copies blueprint bytes
without parsing or reserialization. It never imports the transition model or
reads expected-frontier files.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

T01_MANIFEST_BLOB = "c1731d24387ec4c2dcb33167a286d89fc45ef254"
T02_MANIFEST_BLOB = "c9d543be934dd0cc33b67a2f987f0eae9705a83b"
BLUEPRINTS = {
    "T01_OLD": {
        "sha256": "9a2b545288a3cae15f497796cb9001e6a142fc02c6150df6b11975d79f6083d8",
        "git_blob": "8788f64ee1f6dfd25cdaaa42183b2ee94591e1f0",
        "output": "T01_OLD_NIGHT_MODE.yaml",
    },
    "T01_NEW": {
        "sha256": "9c2a4b03d57a59d6b13a34b0bf4031104c19abafa8331e1b329861f45eeef363",
        "git_blob": "19c99196ed611729338f01bc77ea1b5deda7aa02",
        "output": "T01_NEW_NIGHT_MODE.yaml",
    },
    "T02_OLD": {
        "sha256": "5593911e8ef5db3cc29f1ab4bb6658538f6e68fecbd010de0527ecc41b5d4115",
        "git_blob": "2172a1a3ad1955132911aa0fd0f8a546ab6e2b76",
        "output": "T02_OLD_WEEKLY_HEATING_SCHEDULE.yaml",
    },
    "T02_NEW": {
        "sha256": "45375bb3a0a09b5ae7db9bdc038a73fcbec80425ec38e858e89633cb1dfdf37e",
        "git_blob": "3255957740ec44285d866d8be7d78bf905c1257c",
        "output": "T02_NEW_WEEKLY_HEATING_SCHEDULE.yaml",
    },
}
BANNED_RUNTIME_LITERALS = {
    "old_projected_action",
    "new_projected_action",
    "compatibility",
    "weight_in_144_state_superspace",
    "expected_counts",
    "RETIRED_BY_UPDATE",
    "COMPATIBLE_ACROSS_VERSION",
    "old_causal_path",
    "new_causal_path",
    "forbidden_runtime_fields",
    "expected_frontier",
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_original_manifest(path: Path, *, transition: str, expected_blob: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if git_blob_sha(raw) != expected_blob:
        raise AssertionError(f"{transition}-manifest-git-blob")
    doc = json.loads(raw)
    expected_schema = {
        "T01": "replaymark.ve2.t01.execution-state-manifest.v1",
        "T02": "replaymark.ve2.t02.execution-state-manifest.v1",
    }[transition]
    expected_count = {"T01": 2, "T02": 42}[transition]
    if doc.get("schema") != expected_schema or doc.get("state_count") != expected_count:
        raise AssertionError(f"{transition}-manifest-identity")
    states = doc.get("states")
    fixed = doc.get("fixed_profile")
    if not isinstance(states, list) or len(states) != expected_count or not isinstance(fixed, dict):
        raise AssertionError(f"{transition}-manifest-shape")
    expected_ids = [f"VE2-{transition}-S{i:02d}" for i in range(expected_count)]
    if [row.get("opaque_state_id") for row in states] != expected_ids:
        raise AssertionError(f"{transition}-manifest-state-order")
    for row in states:
        if not isinstance(row, dict) or set(row) != {"opaque_state_id", "fixture"} or not isinstance(row["fixture"], dict):
            raise AssertionError(f"{transition}-manifest-runtime-row")
    return doc


def project_manifest(doc: dict[str, Any]) -> dict[str, Any]:
    projected = {
        "schema": doc["schema"],
        "state_count": doc["state_count"],
        "fixed_profile": doc["fixed_profile"],
        "states": doc["states"],
    }
    raw = canonical_bytes(projected).decode("utf-8")
    leaked = sorted(token for token in BANNED_RUNTIME_LITERALS if token in raw)
    if leaked:
        raise AssertionError(("runtime-manifest-label-leak", leaked))
    if set(projected) != {"schema", "state_count", "fixed_profile", "states"}:
        raise AssertionError("runtime-manifest-projection-keyset")
    return projected


def verify_blueprint(source: Path, role: str, output_dir: Path) -> dict[str, Any]:
    spec = BLUEPRINTS[role]
    raw = source.read_bytes()
    observed_sha = sha256_bytes(raw)
    observed_blob = git_blob_sha(raw)
    if observed_sha != spec["sha256"]:
        raise AssertionError((role, "blueprint-sha256", observed_sha))
    if observed_blob != spec["git_blob"]:
        raise AssertionError((role, "blueprint-git-blob", observed_blob))
    target = output_dir / str(spec["output"])
    shutil.copyfile(source, target)
    copied = target.read_bytes()
    if copied != raw:
        raise AssertionError((role, "blueprint-copy-not-byte-identical"))
    return {
        "role": role,
        "source_sha256": observed_sha,
        "source_git_blob": observed_blob,
        "byte_size": len(raw),
        "runtime_path": target.name,
        "runtime_sha256": sha256_bytes(copied),
        "runtime_git_blob": git_blob_sha(copied),
        "byte_identical_copy": True,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t01-manifest", required=True)
    ap.add_argument("--t02-manifest", required=True)
    ap.add_argument("--t01-old-blueprint", required=True)
    ap.add_argument("--t01-new-blueprint", required=True)
    ap.add_argument("--t02-old-blueprint", required=True)
    ap.add_argument("--t02-new-blueprint", required=True)
    ap.add_argument("--source-freeze", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    manifests_dir = out / "manifests"
    blueprints_dir = out / "blueprints"
    manifests_dir.mkdir(parents=True, exist_ok=False)
    blueprints_dir.mkdir(parents=True, exist_ok=False)

    t01_original = load_original_manifest(Path(args.t01_manifest), transition="T01", expected_blob=T01_MANIFEST_BLOB)
    t02_original = load_original_manifest(Path(args.t02_manifest), transition="T02", expected_blob=T02_MANIFEST_BLOB)
    t01_runtime = project_manifest(t01_original)
    t02_runtime = project_manifest(t02_original)
    t01_path = manifests_dir / "VE2_T01_RUNTIME_MANIFEST_V1.json"
    t02_path = manifests_dir / "VE2_T02_RUNTIME_MANIFEST_V1.json"
    write_json(t01_path, t01_runtime)
    write_json(t02_path, t02_runtime)

    manifest_receipts = []
    for transition, original, runtime_path, expected_blob in (
        ("T01", t01_original, t01_path, T01_MANIFEST_BLOB),
        ("T02", t02_original, t02_path, T02_MANIFEST_BLOB),
    ):
        runtime_raw = runtime_path.read_bytes()
        manifest_receipts.append({
            "transition": transition,
            "original_git_blob": expected_blob,
            "original_canonical_sha256": sha256_bytes(canonical_bytes(original)),
            "runtime_projection_keys": ["fixed_profile", "schema", "state_count", "states"],
            "runtime_path": runtime_path.name,
            "runtime_byte_size": len(runtime_raw),
            "runtime_raw_sha256": sha256_bytes(runtime_raw),
            "runtime_canonical_sha256": sha256_bytes(canonical_bytes(json.loads(runtime_raw))),
            "runtime_git_blob": git_blob_sha(runtime_raw),
            "state_count": runtime_path == t01_path and 2 or 42,
            "answer_bearing_metadata_removed": True,
        })

    blueprint_paths = {
        "T01_OLD": Path(args.t01_old_blueprint),
        "T01_NEW": Path(args.t01_new_blueprint),
        "T02_OLD": Path(args.t02_old_blueprint),
        "T02_NEW": Path(args.t02_new_blueprint),
    }
    blueprint_receipts = [verify_blueprint(blueprint_paths[role], role, blueprints_dir) for role in BLUEPRINTS]

    receipt = {
        "schema": "replaymark.ve2.scientific-runtime-bundle-receipt.v1",
        "status": "PASS_PRE_SCIENCE_RUNTIME_BUNDLE",
        "source_freeze": args.source_freeze,
        "manifests": manifest_receipts,
        "blueprints": blueprint_receipts,
        "runtime_worker_visibility": {
            "manifest_projection_only": True,
            "blueprint_bytes_unparsed_and_unmodified": True,
            "expected_frontier_present": False,
            "transition_semantics_present": False,
            "compatibility_labels_present": False,
            "class_weights_present": False,
        },
        "scientific_exposure": {
            "scientific_result_opened": False,
            "scientific_cells": 0,
            "frontier_result_seen": False,
            "trigger_stimulus_emitted": False,
        },
    }
    receipt["receipt_sha256"] = sha256_bytes(canonical_bytes(receipt))
    write_json(out / "VE2_SCIENTIFIC_RUNTIME_BUNDLE_RECEIPT_V1.json", receipt)
    print(json.dumps({"status": receipt["status"], "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
