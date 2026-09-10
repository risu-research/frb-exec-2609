from __future__ import annotations

"""Transport-only execution and qualification support for VE1 scientific v3.

This module does not import ReplayMark, Home Assistant, Better Thermostat, the
frozen answer table, or experiment target semantics. It only moves opaque
artifacts across process/container boundaries, verifies cryptographic identity,
and records transport/provenance envelopes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any

STAGES = ("old_history", "new_direct", "replaymark", "replay_all")
DOWNSTREAM = {"replaymark", "replay_all"}
NATIVE = {"old_history", "new_direct"}
V2_RUN_ID = 34467293478
V1_PRE_INPUT_RUN_ID = 34465860182
EXPECTED_V2_SEAL_SHA256 = "055df628df72df5aeb2523f0166a6dfbb186c9656efd3802ac6f60b76f887ecb"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write_json(path: str | Path, value: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_json_bytes(value))


def _sha256(path: str | Path) -> str:
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


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _prepare_host_report(path: Path) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    os.chmod(path, 0o600)
    st = path.stat()
    assert st.st_uid == os.getuid(), ("unexpected host report uid", st.st_uid, os.getuid())
    assert _mode(path) == 0o600
    return st.st_uid, st.st_gid


def _seal_host_report(path: Path, owner: tuple[int, int]) -> None:
    assert path.is_file() and path.stat().st_size > 0, "producer report absent or empty"
    os.chmod(path, 0o444)
    st = path.stat()
    assert (st.st_uid, st.st_gid) == owner, ("report ownership changed", (st.st_uid, st.st_gid), owner)
    assert _mode(path) == 0o444, oct(_mode(path))


def _assert_digest(path: Path, expected: str) -> None:
    actual = _sha256(path)
    assert actual == expected, ("digest mismatch", str(path), actual, expected)


def _write_checksums(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "CHECKSUMS.sha256"):
        rel = path.relative_to(root).as_posix()
        rows.append(f"{_sha256(path)}  {rel}\n")
    assert rows, "no stage evidence to checksum"
    (root / "CHECKSUMS.sha256").write_text("".join(rows), encoding="utf-8")
    _verify_checksums(root)


def _verify_checksums(root: Path) -> None:
    manifest = root / "CHECKSUMS.sha256"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        expected, rel = line.split(None, 1)
        rel = rel.lstrip("* ")
        path = root / rel
        assert path.is_file(), rel
        _assert_digest(path, expected)


def _fallback_stage(stage: str, replica: int, detail: str, out: Path) -> None:
    _write_json(
        out,
        {
            "schema": "replaymark.ve1.native-stage.v1",
            "mode": "AUTHORITATIVE_FIRST_COMPLETE_STAGE",
            "stage": stage,
            "replica": replica,
            "fatal_failure": detail,
            "rows": [],
            "scientific_summary_emitted": False,
        },
    )


def _stage_provenance(
    *,
    stage: str,
    replica: int,
    blueprint_blob: str,
    producer_exit: int,
    validator_exit: int,
    report: Path,
    report_owner: tuple[int, int] | None,
    history_path: Path | None,
    history_sha256: str | None,
    outdir: Path,
) -> None:
    value = {
        "schema": "replaymark.ve1.stage-public-provenance.v3",
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "execution_head": os.environ.get("GITHUB_SHA"),
        "source_freeze_public_head": os.environ.get("SOURCE_FREEZE_HEAD"),
        "source_candidate_head": os.environ.get("SOURCE_CANDIDATE_HEAD"),
        "capsule_source_head": os.environ.get("CAPSULE_SOURCE_HEAD"),
        "e0q_result_seal_sha256": os.environ.get("E0Q_SEAL_SHA256"),
        "v2_post_open_seal_sha256": os.environ.get("V2_POST_OPEN_SEAL_SHA256"),
        "transport_qualification_pass_sha256": os.environ.get("TRANSPORT_QUALIFICATION_PASS_SHA256"),
        "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None,
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]) if os.environ.get("GITHUB_RUN_ATTEMPT") else None,
        "replica": replica,
        "stage": stage,
        "blueprint_git_blob_sha1": blueprint_blob,
        "producer_exit": producer_exit,
        "structural_validator_exit": validator_exit,
        "report_sha256": _sha256(report) if report.exists() and report.stat().st_size else None,
        "report_mode": f"{_mode(report):04o}" if report.exists() else None,
        "report_owner_uid": report_owner[0] if report_owner else None,
        "report_owner_gid": report_owner[1] if report_owner else None,
        "old_history_source_path": str(history_path) if history_path else None,
        "old_history_source_sha256": history_sha256,
        "old_history_mount_mode": "ro" if history_path else None,
        "prior_post_open_infrastructure_run_preserved": V2_RUN_ID,
        "pre_input_failure_run_preserved": V1_PRE_INPUT_RUN_ID,
        "rerun_authorized": False,
    }
    _write_json(outdir / "PROVENANCE.json", value)


def _scientific_docker_command(args: argparse.Namespace, report: Path, history: Path | None) -> list[str]:
    capsule = Path(args.capsule).resolve()
    origin = Path(args.origin).resolve()
    state_manifest = Path(args.state_manifest).resolve()
    blueprint = Path(args.blueprint).resolve()
    component = Path(args.ownership_component).resolve()
    report = report.resolve()
    for path in (capsule, origin, state_manifest, blueprint, component):
        assert path.exists(), str(path)

    command = [
        "docker", "run", "--rm", "--network", "none",
        "-e", "PYTHONPATH=/capsule:/origin/agentmark_e3b_lab:/origin",
        "-v", f"{capsule}:/capsule:ro",
        "-v", f"{origin}:/origin:ro",
        "-v", f"{state_manifest}:/inputs/state-manifest.json:ro",
        "-v", f"{blueprint}:/inputs/blueprint.yaml:ro",
        "-v", f"{component}:/inputs/component:ro",
    ]
    if history is not None:
        command += ["-v", f"{history.resolve()}:/sealed-old/REPORT.json:ro"]
    command += [
        "-v", f"{report}:/results/REPORT.json",
        "--entrypoint", "python3",
        args.image,
        "/capsule/ve1_native_execution.py",
        "--stage", args.stage,
        "--replica", str(args.replica),
        "--state-manifest", "/inputs/state-manifest.json",
        "--blueprint", "/inputs/blueprint.yaml",
        "--blueprint-git-blob", args.blueprint_blob,
        "--ownership-component", "/inputs/component",
    ]
    if history is not None:
        command += ["--old-history", "/sealed-old/REPORT.json"]
    command += ["--out", "/results/REPORT.json"]
    return command


def cmd_run_stage(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    report = outdir / "REPORT.json"
    producer_stdout = outdir / "PRODUCER_STDOUT.txt"
    producer_stderr = outdir / "PRODUCER_STDERR.txt"
    validator_stdout = outdir / "VALIDATOR_STDOUT.txt"
    validator_stderr = outdir / "VALIDATOR_STDERR.txt"
    conclusion = 1
    producer_rc = -1
    validator_rc = -1
    owner: tuple[int, int] | None = None
    history: Path | None = Path(args.old_history).resolve() if args.old_history else None
    history_digest: str | None = args.old_history_sha256

    try:
        assert args.stage in STAGES
        assert args.replica in (0, 1)
        if args.stage in DOWNSTREAM:
            assert history is not None and history_digest is not None
            assert len(history_digest) == 64
            assert history.is_file()
            assert _mode(history) == 0o444, ("Old-history report not host-sealed", oct(_mode(history)))
            _assert_digest(history, history_digest)
        else:
            assert args.stage in NATIVE
            assert history is None and history_digest is None

        owner = _prepare_host_report(report)
        command = _scientific_docker_command(args, report, history)
        with producer_stdout.open("wb") as out, producer_stderr.open("wb") as err:
            completed = subprocess.run(command, stdout=out, stderr=err, check=False)
        producer_rc = completed.returncode
        (outdir / "PRODUCER_EXIT.txt").write_text(f"{producer_rc}\n", encoding="utf-8")

        if report.stat().st_size == 0:
            _fallback_stage(args.stage, args.replica, f"RUNNER_DID_NOT_EMIT_REPORT exit={producer_rc}", report)
        _seal_host_report(report, owner)

        if history is not None:
            _assert_digest(history, history_digest or "")
            assert _mode(history) == 0o444

        validator = Path(args.validator).resolve()
        with validator_stdout.open("wb") as out, validator_stderr.open("wb") as err:
            completed = subprocess.run(
                [sys.executable, str(validator), str(report), "--out", str(outdir / "STRUCTURAL_VALIDATION.json")],
                stdout=out,
                stderr=err,
                check=False,
            )
        validator_rc = completed.returncode
        (outdir / "VALIDATOR_EXIT.txt").write_text(f"{validator_rc}\n", encoding="utf-8")

        if history is not None:
            _assert_digest(history, history_digest or "")
            assert _mode(history) == 0o444

        conclusion = 0 if producer_rc == 0 and validator_rc == 0 else 1
    except Exception as exc:
        _write_json(
            outdir / "TRANSPORT_FATAL.json",
            {
                "schema": "replaymark.ve1.stage-transport-failure.v3",
                "stage": args.stage,
                "replica": args.replica,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        if not report.exists() or report.stat().st_size == 0:
            try:
                if not report.exists():
                    owner = _prepare_host_report(report)
                _fallback_stage(args.stage, args.replica, f"TRANSPORT_CONTRACT_FAILURE: {type(exc).__name__}: {exc}", report)
            except Exception:
                pass
        if report.exists() and report.stat().st_size:
            try:
                if owner is None:
                    st = report.stat()
                    owner = (st.st_uid, st.st_gid)
                _seal_host_report(report, owner)
            except Exception:
                pass
        if not (outdir / "PRODUCER_EXIT.txt").exists():
            (outdir / "PRODUCER_EXIT.txt").write_text(f"{producer_rc}\n", encoding="utf-8")
        if not (outdir / "VALIDATOR_EXIT.txt").exists():
            (outdir / "VALIDATOR_EXIT.txt").write_text(f"{validator_rc}\n", encoding="utf-8")
    finally:
        try:
            _stage_provenance(
                stage=args.stage,
                replica=args.replica,
                blueprint_blob=args.blueprint_blob,
                producer_exit=producer_rc,
                validator_exit=validator_rc,
                report=report,
                report_owner=owner,
                history_path=history,
                history_sha256=history_digest,
                outdir=outdir,
            )
        except Exception as exc:
            _write_json(outdir / "PROVENANCE_FAILURE.json", {"error_type": type(exc).__name__, "error": str(exc)})
            conclusion = 1
        (outdir / "STAGE_TRANSPORT_CONCLUSION.txt").write_text(f"{conclusion}\n", encoding="utf-8")
        _write_checksums(outdir)


def _synthetic_write(image: str, output: Path, payload: str, history: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    owner = _prepare_host_report(output)
    script = (
        "from pathlib import Path; import hashlib,json; "
        f"payload={payload!r}; "
        "old=Path('/sealed-old/REPORT.json'); "
        "old_exists=old.exists(); "
        "old_digest=hashlib.sha256(old.read_bytes()).hexdigest() if old_exists else None; "
        "blocked=None; "
        "\nif old_exists:\n"
        "    try:\n"
        "        old.write_bytes(b'MUTATION')\n"
        "        blocked=False\n"
        "    except OSError:\n"
        "        blocked=True\n"
        "Path('/results/REPORT.json').write_text(json.dumps({'payload':payload,'old_exists':old_exists,'old_digest':old_digest,'old_write_blocked':blocked},sort_keys=True)+'\\n')"
    )
    command = ["docker", "run", "--rm", "--network", "none"]
    if history is not None:
        command += ["-v", f"{history.resolve()}:/sealed-old/REPORT.json:ro"]
    command += [
        "-v", f"{output.resolve()}:/results/REPORT.json",
        "--entrypoint", "python3",
        image,
        "-c", script,
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    _seal_host_report(output, owner)
    return completed


def cmd_qualify(args: argparse.Namespace) -> None:
    root = Path(args.scratch).resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    old = root / "old_history" / "REPORT.json"
    _synthetic_write(args.image, old, "SYNTHETIC_OLD_HISTORY")
    old_digest = _sha256(old)
    old_owner = (old.stat().st_uid, old.stat().st_gid)
    assert _mode(old) == 0o444

    new = root / "new_direct" / "REPORT.json"
    _synthetic_write(args.image, new, "SYNTHETIC_NEW_DIRECT")
    _assert_digest(old, old_digest)
    assert _mode(old) == 0o444

    downstream: dict[str, Any] = {}
    for stage in ("replaymark", "replay_all"):
        out = root / stage / "REPORT.json"
        _synthetic_write(args.image, out, f"SYNTHETIC_{stage.upper()}", old)
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert parsed["old_exists"] is True
        assert parsed["old_digest"] == old_digest
        assert parsed["old_write_blocked"] is True
        _assert_digest(old, old_digest)
        assert _mode(old) == 0o444
        downstream[stage] = {
            "old_digest_seen": parsed["old_digest"],
            "old_write_blocked": parsed["old_write_blocked"],
            "output_mode": f"{_mode(out):04o}",
            "output_owner_uid": out.stat().st_uid,
            "output_owner_gid": out.stat().st_gid,
        }

    value = {
        "schema": "replaymark.ve1.dynamic-transport-qualification.v3",
        "status": "PASS",
        "scientific_result_opened": False,
        "scientific_cells": 0,
        "result_bearing_controller_invocations": 0,
        "network_mode": "none",
        "runtime_image": args.image,
        "host_precreated_single_file_output_mount": True,
        "output_owner_preserved": True,
        "host_seal_mode": "0444",
        "old_history_sha256": old_digest,
        "old_history_owner_uid": old_owner[0],
        "old_history_owner_gid": old_owner[1],
        "old_history_survived_intervening_new_direct": True,
        "downstream_read_only_mount_enforced": True,
        "downstream": downstream,
        "shell_function_state_sharing_used": False,
        "separate_stage_process_contract": True,
    }
    _write_json(args.out, value)


def cmd_verify_bt(args: argparse.Namespace) -> None:
    root = Path(args.root)
    manifest = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    assert manifest == args.manifest_sha256
    parsed = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert parsed["domain"] == "better_thermostat"
    assert parsed["version"] == args.version
    assert _tree_sha256(root) == args.tree_sha256


def cmd_guard(args: argparse.Namespace) -> None:
    e0q = json.loads(Path(args.e0q_seal).read_text(encoding="utf-8"))
    v2 = json.loads(Path(args.v2_seal).read_text(encoding="utf-8"))
    qualification = json.loads(Path(args.qualification_pass).read_text(encoding="utf-8"))
    marker = json.loads(Path(args.marker).read_text(encoding="utf-8"))
    e0q_sha = _sha256(args.e0q_seal)
    v2_sha = _sha256(args.v2_seal)
    qualification_sha = _sha256(args.qualification_pass)

    assert e0q["schema"] == "replaymark.ve1.e0q-result-seal.v1"
    assert e0q["status"] == "PASS"
    assert e0q["scientific_result_opened"] is False
    assert e0q["rerun_authorized"] is False
    assert e0q["private_constitution_head"] == args.private

    assert v2_sha == EXPECTED_V2_SEAL_SHA256
    assert v2["schema"] == "replaymark.ve1.post-open-infrastructure-incomplete-seal.v2"
    assert v2["classification"] == "POST_OPEN_INFRASTRUCTURE_INCOMPLETE"
    assert v2["scientific_open_event_occurred"] is True
    assert v2["promotion"] is False
    assert v2["rerun_same_authority_authorized"] is False
    assert v2["scientific_result_reuse_authorized"] is False
    assert v2["fresh_successor_required"] is True
    assert v2["workflow_run_id"] == V2_RUN_ID

    assert qualification["schema"] == "replaymark.ve1.transport-qualification-pass.v3"
    assert qualification["status"] == "PASS"
    assert qualification["scientific_result_opened"] is False
    assert qualification["scientific_cells"] == 0
    assert qualification["source_candidate_head"] == args.source_candidate
    assert qualification["private_constitution_head"] == args.private
    assert qualification["v2_post_open_seal_sha256"] == v2_sha
    assert qualification["dynamic_transport_status"] == "PASS"
    for path, expected in qualification["source_files_sha256"].items():
        _assert_digest(Path(path), expected)

    expected_marker = {
        "schema": "replaymark.ve1.scientific-authority-open.v3",
        "authority": "AUTHORITATIVE_FIRST_COMPLETE_VERSION_EVOLUTION",
        "source_freeze_public_head": args.parent,
        "source_candidate_head": args.source_candidate,
        "e0q_result_seal_sha256": e0q_sha,
        "v2_post_open_seal_sha256": v2_sha,
        "transport_qualification_pass_sha256": qualification_sha,
        "private_constitution_head": args.private,
        "prior_post_open_infrastructure_run_id": V2_RUN_ID,
        "fresh_population_required": True,
        "rerun_authorized": False,
    }
    assert marker == expected_marker, (marker, expected_marker)

    with Path(args.github_output).open("a", encoding="utf-8") as handle:
        handle.write(f"source_freeze_head={args.parent}\n")
        handle.write(f"source_candidate_head={args.source_candidate}\n")
        handle.write(f"capsule_source_head={e0q['capsule_source_head']}\n")
        handle.write(f"e0q_seal_sha256={e0q_sha}\n")
        handle.write(f"v2_post_open_seal_sha256={v2_sha}\n")
        handle.write(f"transport_qualification_pass_sha256={qualification_sha}\n")
        handle.write("open=true\n")


def cmd_replica_manifest(args: argparse.Namespace) -> None:
    root = Path(args.results)
    stage_checksums: dict[str, str | None] = {}
    stage_conclusions: dict[str, int | None] = {}
    for stage in STAGES:
        checksum = root / stage / "CHECKSUMS.sha256"
        conclusion = root / stage / "STAGE_TRANSPORT_CONCLUSION.txt"
        stage_checksums[stage] = _sha256(checksum) if checksum.exists() else None
        stage_conclusions[stage] = int(conclusion.read_text().strip()) if conclusion.exists() else None
    value = {
        "schema": "replaymark.ve1.replica-first-complete-manifest.v3",
        "authority": "AUTHORITATIVE_FIRST_COMPLETE_VERSION_EVOLUTION",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "execution_head": os.environ["GITHUB_SHA"],
        "source_freeze_public_head": os.environ["SOURCE_FREEZE_HEAD"],
        "source_candidate_head": os.environ["SOURCE_CANDIDATE_HEAD"],
        "capsule_source_head": os.environ["CAPSULE_SOURCE_HEAD"],
        "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "replica": args.replica,
        "stage_order": list(STAGES),
        "stage_checksums_sha256": stage_checksums,
        "stage_transport_conclusions": stage_conclusions,
        "prior_post_open_infrastructure_run_preserved": V2_RUN_ID,
        "fresh_population_from_state_zero": True,
        "rerun_authorized": False,
    }
    _write_json(root / "REPLICA_MANIFEST.json", value)


def cmd_verify_replica(args: argparse.Namespace) -> None:
    root = Path(args.root)
    manifest = json.loads((root / "REPLICA_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "replaymark.ve1.replica-first-complete-manifest.v3"
    assert manifest["replica"] == args.replica
    assert manifest["stage_order"] == list(STAGES)
    assert manifest["fresh_population_from_state_zero"] is True
    for stage in STAGES:
        checksum = root / stage / "CHECKSUMS.sha256"
        assert checksum.is_file(), stage
        _assert_digest(checksum, manifest["stage_checksums_sha256"][stage])
        _verify_checksums(root / stage)
        report = root / stage / "REPORT.json"
        provenance = json.loads((root / stage / "PROVENANCE.json").read_text(encoding="utf-8"))
        assert report.is_file(), stage
        assert provenance["report_mode"] == "0444", (stage, provenance.get("report_mode"))
        assert provenance["report_sha256"] == _sha256(report), stage


def cmd_fallback_adjudication(args: argparse.Namespace) -> None:
    _write_json(
        args.out,
        {
            "schema": "replaymark.ve1.independent-replicated-adjudication.v1",
            "status": "INFRASTRUCTURE_INCOMPLETE",
            "promotion": False,
            "failure": f"adjudicator did not produce output; exit={args.exit_code}",
        },
    )


def cmd_aggregate_provenance(args: argparse.Namespace) -> None:
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    value = {
        "schema": "replaymark.ve1.first-complete-public-provenance.v3",
        "authority": "AUTHORITATIVE_FIRST_COMPLETE_VERSION_EVOLUTION",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "execution_head": os.environ["GITHUB_SHA"],
        "source_freeze_public_head": os.environ["SOURCE_FREEZE_HEAD"],
        "source_candidate_head": os.environ["SOURCE_CANDIDATE_HEAD"],
        "capsule_source_head": os.environ["CAPSULE_SOURCE_HEAD"],
        "e0q_result_seal_sha256": os.environ["E0Q_SEAL_SHA256"],
        "v2_post_open_seal_sha256": os.environ["V2_POST_OPEN_SEAL_SHA256"],
        "transport_qualification_pass_sha256": os.environ["TRANSPORT_QUALIFICATION_PASS_SHA256"],
        "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "scientific_status": result.get("status"),
        "promotion": bool(result.get("promotion", False)),
        "prior_post_open_infrastructure_run_preserved": V2_RUN_ID,
        "fresh_population_from_state_zero": True,
        "rerun_authorized": False,
    }
    _write_json(args.out, value)


def cmd_qualification_provenance(args: argparse.Namespace) -> None:
    static = json.loads(Path(args.static_audit).read_text(encoding="utf-8"))
    dynamic = json.loads(Path(args.dynamic_audit).read_text(encoding="utf-8"))
    value = {
        "schema": "replaymark.ve1.transport-qualification-public-provenance.v3",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "execution_head": os.environ["GITHUB_SHA"],
        "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "source_candidate_head": args.source_candidate,
        "private_constitution_head": args.private,
        "v2_post_open_seal_sha256": _sha256(args.v2_seal),
        "static_status": static.get("status"),
        "dynamic_transport_status": dynamic.get("status"),
        "scientific_result_opened": False,
        "scientific_cells": 0,
        "result_bearing_controller_invocations": 0,
        "rerun_authorized": False,
    }
    _write_json(args.out, value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run-stage")
    p.add_argument("--stage", required=True, choices=STAGES)
    p.add_argument("--replica", required=True, type=int)
    p.add_argument("--image", required=True)
    p.add_argument("--capsule", required=True)
    p.add_argument("--origin", required=True)
    p.add_argument("--state-manifest", required=True)
    p.add_argument("--blueprint", required=True)
    p.add_argument("--blueprint-blob", required=True)
    p.add_argument("--ownership-component", required=True)
    p.add_argument("--validator", required=True)
    p.add_argument("--old-history")
    p.add_argument("--old-history-sha256")
    p.add_argument("--outdir", required=True)
    p.set_defaults(func=cmd_run_stage)

    p = sub.add_parser("qualify")
    p.add_argument("--image", required=True)
    p.add_argument("--scratch", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_qualify)

    p = sub.add_parser("verify-bt")
    p.add_argument("--root", required=True)
    p.add_argument("--manifest-sha256", required=True)
    p.add_argument("--tree-sha256", required=True)
    p.add_argument("--version", required=True)
    p.set_defaults(func=cmd_verify_bt)

    p = sub.add_parser("guard")
    p.add_argument("--e0q-seal", required=True)
    p.add_argument("--v2-seal", required=True)
    p.add_argument("--qualification-pass", required=True)
    p.add_argument("--marker", required=True)
    p.add_argument("--private", required=True)
    p.add_argument("--parent", required=True)
    p.add_argument("--source-candidate", required=True)
    p.add_argument("--github-output", required=True)
    p.set_defaults(func=cmd_guard)

    p = sub.add_parser("replica-manifest")
    p.add_argument("--replica", required=True, type=int)
    p.add_argument("--results", required=True)
    p.set_defaults(func=cmd_replica_manifest)

    p = sub.add_parser("verify-replica")
    p.add_argument("--root", required=True)
    p.add_argument("--replica", required=True, type=int)
    p.set_defaults(func=cmd_verify_replica)

    p = sub.add_parser("fallback-adjudication")
    p.add_argument("--exit-code", required=True, type=int)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_fallback_adjudication)

    p = sub.add_parser("aggregate-provenance")
    p.add_argument("--result", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_aggregate_provenance)

    p = sub.add_parser("qualification-provenance")
    p.add_argument("--static-audit", required=True)
    p.add_argument("--dynamic-audit", required=True)
    p.add_argument("--v2-seal", required=True)
    p.add_argument("--source-candidate", required=True)
    p.add_argument("--private", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_qualification_provenance)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
