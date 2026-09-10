#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
from collections import defaultdict

UPSTREAM = "https://github.com/KartoffelToby/better_thermostat.git"
T01_OLD_COMMIT = "cd4c3121c92f59d5ac1f3533424bc570209ce6ef"
T01_NEW_COMMIT = "96ae2f87b3b1a1b095dbf1f74f37f63fbc34c32f"
T01_PATH = "blueprints/night_mode.yaml"
T01_OLD_BLOB = "8788f64ee1f6dfd25cdaaa42183b2ee94591e1f0"
T01_NEW_BLOB = "19c99196ed611729338f01bc77ea1b5deda7aa02"
T01_OLD_SHA256 = "9a2b545288a3cae15f497796cb9001e6a142fc02c6150df6b11975d79f6083d8"
T01_NEW_SHA256 = "9c2a4b03d57a59d6b13a34b0bf4031104c19abafa8331e1b329861f45eeef363"

T02_OLD_COMMIT = "ac189909982c5edea1260e767027d6fad90ef4bd"
T02_NEW_COMMIT = "5b4496de5659fd2c6ec5c67a9797e6659797866c"
T02_PATH = "blueprints/weekly_heating_schedule.yaml"
T02_OLD_BLOB = "2172a1a3ad1955132911aa0fd0f8a546ab6e2b76"
T02_NEW_BLOB = "3255957740ec44285d866d8be7d78bf905c1257c"
T02_OLD_SHA256 = "5593911e8ef5db3cc29f1ab4bb6658538f6e68fecbd010de0527ecc41b5d4115"
T02_NEW_SHA256 = "45375bb3a0a09b5ae7db9bdc038a73fcbec80425ec38e858e89633cb1dfdf37e"

EXPECTED_T01_ROWS_SHA256 = "6d4b4ac7738885bcf1226161d84726926b15d3139502dd5e31499a4850328f2a"
EXPECTED_T02_ABSTRACT_SHA256 = "6292de3f4889bb69491faf40cdc3c421576ea750e4d70cb032a6b0bbc81c60ae"
EXPECTED_T02_QUOTIENT_SHA256 = "c4c3d495df1659aaf94fb1d517b9fdd483759344c429e58aa51a45d415b74c25"
EXPECTED_T02_EXECUTION_MANIFEST_SHA256 = "f791b6b93ee3febe483c9f85aa977db04c3e431479bf4404f5c9d7d6194fed94"

T01_TARGET = "climate.ve2_t01_thermostat"
T02_TARGET = "climate.ve2_t02_thermostat"
SLOT_PRESETS = {1: "comfort", 2: "eco", 3: "home", 4: "sleep"}
VACATION = "away"


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(*args: str, cwd: pathlib.Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def git_bytes(repo: pathlib.Path, spec: str) -> bytes:
    return subprocess.check_output(["git", "show", spec], cwd=repo)


def action(operation: str, variant: dict[str, object] | None = None, target: str = T02_TARGET) -> dict[str, str]:
    if operation == "NO_ACTION":
        return {"operation": "NO_ACTION", "concrete_target": target, "variant": "NO_ACTION"}
    return {"operation": operation, "concrete_target": target, "variant": canonical({} if variant is None else variant)}


def t01_independent_rows() -> list[dict[str, object]]:
    table = [
        ("off", "better_thermostat.restore_saved_target_temperature", {}, "schedule:off:restore_saved_target_temperature", "climate.set_preset_mode", {"preset_mode": "none"}, "schedule:off:set_preset_none"),
        ("on", "better_thermostat.set_temp_target_temperature", {"temperature": 18.0}, "schedule:on:set_temp_target_temperature", "climate.set_preset_mode", {"preset_mode": "sleep"}, "schedule:on:set_preset_sleep"),
    ]
    rows = []
    for i, (state, old_op, old_var, old_path, new_op, new_var, new_path) in enumerate(table):
        old = action(old_op, old_var, T01_TARGET)
        new = action(new_op, new_var, T01_TARGET)
        rows.append({"analysis_state_id": f"VE2-T01-A{i:02d}", "execution_state_id": f"VE2-T01-S{i:02d}", "fixture": {"schedule_state": state}, "old_projected_action": old, "new_projected_action": new, "old_causal_path": old_path, "new_causal_path": new_path, "compatibility": "COMPATIBLE_ACROSS_VERSION" if old == new else "RETIRED_BY_UPDATE"})
    return rows


def old_weekly(f: dict[str, object]) -> tuple[dict[str, str], str]:
    trigger = str(f["trigger_kind"]); active_slot = int(f["active_slot"]); presence_enabled = bool(f["enable_presence_mode"]); presence_home = bool(f["presence_home"]); pause_enabled = bool(f["enable_pause_switch"]); pause_on = bool(f["pause_on"])
    old_anyone_home: object = "true" if not presence_enabled else presence_home
    old_paused: object = "false" if not pause_enabled else pause_on
    old_current_preset = SLOT_PRESETS[4]
    if trigger.startswith("slot"):
        requested = SLOT_PRESETS[int(trigger[-1])]
        if bool(old_paused): return action("NO_ACTION"), "slot:blocked_by_schedule_paused_truthiness"
        if presence_enabled and not bool(old_anyone_home): return action("climate.set_preset_mode", {"preset_mode": VACATION}), "slot:vacation"
        return action("climate.set_preset_mode", {"preset_mode": requested}), "slot:normal"
    if trigger == "startup":
        if bool(old_paused): return action("NO_ACTION"), "startup:blocked_by_schedule_paused_truthiness"
        if presence_enabled and not bool(old_anyone_home): return action("climate.set_preset_mode", {"preset_mode": VACATION}), "startup:vacation"
        return action("climate.set_preset_mode", {"preset_mode": old_current_preset}), "startup:normal:old_active_slot_string_mismatch"
    if trigger == "pause_off":
        if not pause_enabled: return action("NO_ACTION"), "pause_off:feature_disabled"
        if presence_enabled and not bool(old_anyone_home): return action("climate.set_preset_mode", {"preset_mode": VACATION}), "pause_off:vacation"
        return action("climate.set_preset_mode", {"preset_mode": old_current_preset}), "pause_off:normal:old_active_slot_string_mismatch"
    if trigger == "arrived_home":
        if not presence_enabled: return action("NO_ACTION"), "arrived_home:feature_disabled"
        if bool(old_paused): return action("NO_ACTION"), "arrived_home:blocked_by_schedule_paused_truthiness"
        return action("climate.set_preset_mode", {"preset_mode": old_current_preset}), "arrived_home:normal:old_active_slot_string_mismatch"
    if trigger == "left_home":
        if not presence_enabled: return action("NO_ACTION"), "left_home:feature_disabled"
        if bool(old_paused): return action("NO_ACTION"), "left_home:blocked_by_schedule_paused_truthiness"
        if presence_home: return action("NO_ACTION"), "left_home:presence_still_home"
        return action("climate.set_preset_mode", {"preset_mode": VACATION}), "left_home:vacation"
    raise AssertionError(trigger)


def new_weekly(f: dict[str, object]) -> tuple[dict[str, str], str]:
    trigger = str(f["trigger_kind"]); active_slot = int(f["active_slot"]); presence_enabled = bool(f["enable_presence_mode"]); presence_home = bool(f["presence_home"]); pause_enabled = bool(f["enable_pause_switch"]); pause_on = bool(f["pause_on"])
    anyone_home = True if not presence_enabled else presence_home
    paused = False if not pause_enabled else pause_on
    current_preset = SLOT_PRESETS[active_slot]
    if trigger.startswith("slot"):
        requested = SLOT_PRESETS[int(trigger[-1])]
        if paused: return action("NO_ACTION"), "slot:blocked_by_schedule_paused"
        if presence_enabled and not anyone_home: return action("climate.set_preset_mode", {"preset_mode": VACATION}), "slot:vacation"
        return action("climate.set_preset_mode", {"preset_mode": requested}), "slot:normal"
    if trigger == "startup":
        if paused: return action("NO_ACTION"), "startup:blocked_by_schedule_paused"
        if presence_enabled and not anyone_home: return action("climate.set_preset_mode", {"preset_mode": VACATION}), "startup:vacation"
        return action("climate.set_preset_mode", {"preset_mode": current_preset}), "startup:normal"
    if trigger == "pause_off":
        if not pause_enabled: return action("NO_ACTION"), "pause_off:feature_disabled"
        if paused: return action("NO_ACTION"), "pause_off:still_paused"
        if presence_enabled and not anyone_home: return action("climate.set_preset_mode", {"preset_mode": VACATION}), "pause_off:vacation"
        return action("climate.set_preset_mode", {"preset_mode": current_preset}), "pause_off:normal"
    if trigger == "arrived_home":
        if not presence_enabled: return action("NO_ACTION"), "arrived_home:feature_disabled"
        if paused: return action("NO_ACTION"), "arrived_home:blocked_by_schedule_paused"
        return action("climate.set_preset_mode", {"preset_mode": current_preset}), "arrived_home:normal"
    if trigger == "left_home":
        if not presence_enabled: return action("NO_ACTION"), "left_home:feature_disabled"
        if paused: return action("NO_ACTION"), "left_home:blocked_by_schedule_paused"
        if anyone_home: return action("NO_ACTION"), "left_home:presence_still_home"
        return action("climate.set_preset_mode", {"preset_mode": VACATION}), "left_home:vacation"
    raise AssertionError(trigger)


def reachable_fixtures() -> list[dict[str, object]]:
    fixtures = []
    for trigger in ("slot1", "slot2", "slot3", "slot4", "startup", "pause_off", "arrived_home", "left_home"):
        active_slots = (int(trigger[-1]),) if trigger.startswith("slot") else (1, 2, 3, 4)
        for active_slot in active_slots:
            for presence_enabled in (False, True):
                presence_values = (True,) if trigger == "arrived_home" else ((False,) if trigger == "left_home" else ((False, True) if presence_enabled else (False,)))
                for presence_home in presence_values:
                    for pause_enabled in (False, True):
                        pause_values = (False,) if trigger == "pause_off" else ((False, True) if pause_enabled else (False,))
                        for pause_on in pause_values:
                            fixtures.append({"trigger_kind": trigger, "active_slot": active_slot, "enable_presence_mode": presence_enabled, "presence_home": presence_home, "enable_pause_switch": pause_enabled, "pause_on": pause_on})
    fixtures.sort(key=canonical)
    return fixtures


def t02_independent_rows() -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    rows = []
    for i, fixture in enumerate(reachable_fixtures()):
        old, old_path = old_weekly(fixture); new, new_path = new_weekly(fixture)
        rows.append({"fixture": fixture, "old_projected_action": old, "new_projected_action": new, "old_causal_path": old_path, "new_causal_path": new_path, "compatibility": "COMPATIBLE_ACROSS_VERSION" if old == new else "RETIRED_BY_UPDATE", "abstract_state_id": f"VE2-T02-A{i:03d}"})
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[canonical({"old_projected_action": row["old_projected_action"], "new_projected_action": row["new_projected_action"], "old_causal_path": row["old_causal_path"], "new_causal_path": row["new_causal_path"]})].append(row)
    ordered_groups = []
    for members in groups.values():
        members.sort(key=lambda r: canonical(r["fixture"])); ordered_groups.append(members)
    ordered_groups.sort(key=lambda members: canonical(members[0]["fixture"]))
    quotient = []; fixture_to_sid = {}
    for i, members in enumerate(ordered_groups):
        rep = members[0]; sid = f"VE2-T02-S{i:02d}"
        for member in members: fixture_to_sid[canonical(member["fixture"])] = sid
        quotient.append({"execution_state_id": sid, "representative_fixture": rep["fixture"], "weight_in_144_state_superspace": len(members), "old_projected_action": rep["old_projected_action"], "new_projected_action": rep["new_projected_action"], "old_causal_path": rep["old_causal_path"], "new_causal_path": rep["new_causal_path"], "compatibility": rep["compatibility"]})
    for row in rows: row["execution_state_id"] = fixture_to_sid[canonical(row["fixture"])]
    manifest_rows = [{"opaque_state_id": q["execution_state_id"], "fixture": q["representative_fixture"]} for q in quotient]
    return rows, quotient, manifest_rows


def prepare_upstream(work: pathlib.Path) -> pathlib.Path:
    repo = work / "better_thermostat"
    if repo.exists(): shutil.rmtree(repo)
    subprocess.check_call(["git", "clone", "-q", "--no-checkout", UPSTREAM, str(repo)])
    for commit in (T01_OLD_COMMIT, T01_NEW_COMMIT, T02_OLD_COMMIT, T02_NEW_COMMIT): subprocess.check_call(["git", "fetch", "-q", "origin", commit], cwd=repo)
    return repo


def verify_blob(repo: pathlib.Path, commit: str, path: str, blob: str, digest: str) -> dict[str, str]:
    actual_blob = run("git", "rev-parse", f"{commit}:{path}", cwd=repo); assert actual_blob == blob
    data = git_bytes(repo, f"{commit}:{path}"); actual_digest = sha256_bytes(data); assert actual_digest == digest
    return {"commit": commit, "path": path, "blob_sha1": actual_blob, "sha256": actual_digest}


def verify_source_witnesses(repo: pathlib.Path) -> dict[str, object]:
    witnesses = {
        "t01_old_blueprint": verify_blob(repo, T01_OLD_COMMIT, T01_PATH, T01_OLD_BLOB, T01_OLD_SHA256),
        "t01_new_blueprint": verify_blob(repo, T01_NEW_COMMIT, T01_PATH, T01_NEW_BLOB, T01_NEW_SHA256),
        "t02_old_blueprint": verify_blob(repo, T02_OLD_COMMIT, T02_PATH, T02_OLD_BLOB, T02_OLD_SHA256),
        "t02_new_blueprint": verify_blob(repo, T02_NEW_COMMIT, T02_PATH, T02_NEW_BLOB, T02_NEW_SHA256),
    }
    t01_old = git_bytes(repo, f"{T01_OLD_COMMIT}:{T01_PATH}").decode(); t01_new = git_bytes(repo, f"{T01_NEW_COMMIT}:{T01_PATH}").decode()
    assert "better_thermostat.set_temp_target_temperature" in t01_old and "better_thermostat.restore_saved_target_temperature" in t01_old
    assert "climate.set_preset_mode" in t01_new and "preset_mode: sleep" in t01_new and "preset_mode: none" in t01_new
    old_services = git_bytes(repo, f"{T01_OLD_COMMIT}:custom_components/better_thermostat/services.yaml").decode(); new_services = git_bytes(repo, f"{T01_NEW_COMMIT}:custom_components/better_thermostat/services.yaml").decode()
    for token in ("save_current_target_temperature:", "restore_saved_target_temperature:", "set_temp_target_temperature:"):
        assert token in old_services and token not in new_services
    old_climate = git_bytes(repo, f"{T01_OLD_COMMIT}:custom_components/better_thermostat/climate.py").decode(); assert "set_temp_target_temperature" in old_climate and "restore_saved_target_temperature" in old_climate
    witnesses["t01_service_surface"] = {"old_declares_proprietary_surface": True, "old_climate_implements_or_registers_set_restore": True, "new_services_yaml_excludes_proprietary_surface": True}
    t02_old = git_bytes(repo, f"{T02_OLD_COMMIT}:{T02_PATH}").decode(); t02_new = git_bytes(repo, f"{T02_NEW_COMMIT}:{T02_PATH}").decode()
    assert "{% if active_slot == '1' %}" in t02_old and "{% if active_slot | int == 1 %}" in t02_new
    assert "{% if not enable_pause_switch or pause_switch == '' %}false" in t02_old and "{{ false }}" in t02_new
    assert "presence_entity_selection: !input presence_entity" in t02_new and "pause_switch_selection: !input pause_switch" in t02_new
    assert "value_template: \"{{ not schedule_paused }}\"" in t02_new and "value_template: \"{{ not anyone_home }}\"" in t02_new
    witnesses["t02_source_change"] = {"old_active_slot_string_compare_present": True, "new_active_slot_int_compare_present": True, "old_bare_lowercase_false_branch_present": True, "new_rendered_boolean_false_present": True, "new_scalar_list_normalization_present": True, "new_pause_off_aggregate_recheck_present": True, "new_left_home_aggregate_recheck_present": True}
    return witnesses


def verify_frozen_spec_files(repo_root: pathlib.Path) -> dict[str, object]:
    meta = json.loads((repo_root / "VE2_TRANSITION_META_CONSTITUTION_V1.json").read_text()); t01_frontier = json.loads((repo_root / "VE2_T01_EXPECTED_FRONTIER_V1.json").read_text()); t01_manifest = json.loads((repo_root / "VE2_T01_EXECUTION_STATE_MANIFEST_V1.json").read_text()); t02_frontier = json.loads((repo_root / "VE2_T02_EXPECTED_FRONTIER_V1.json").read_text()); t02_manifest = json.loads((repo_root / "VE2_T02_EXECUTION_STATE_MANIFEST_V1.json").read_text()); runtime = json.loads((repo_root / "VE2_LABEL_FIREWALLED_RUNTIME_CONSTITUTION_V1.json").read_text()); authority = json.loads((repo_root / "VE2_TRANSITION_PRE_RESULT_AUTHORITY_V1.json").read_text())
    assert meta["included_transitions"] == ["VE2-T01-NIGHT-ACTION-FAMILY", "VE2-T02-WEEKLY-GUARD-REALIZATION"]
    assert t01_frontier["counts"] == {"compatible": 0, "retired": 2, "states": 2} and t01_manifest["state_count"] == 2
    assert t02_frontier["abstract_table"]["row_count"] == 144 and t02_frontier["causal_path_quotient_table"]["row_count"] == 42 and t02_manifest["state_count"] == 42
    forbidden_keys = {"old_projected_action", "new_projected_action", "compatibility", "weight_in_144_state_superspace", "expected_counts", "RETIRED_BY_UPDATE", "COMPATIBLE_ACROSS_VERSION", "old_causal_path", "new_causal_path"}
    for manifest in (t01_manifest, t02_manifest):
        text = canonical(manifest["states"])
        for key in forbidden_keys: assert key not in text
    firewall = runtime["expectation_firewall"]
    assert "New Direct output" in firewall["replaymark_decision_forbidden"] and "source diff as authorization oracle" in firewall["replaymark_decision_forbidden"] and "version equality/inequality as authorization oracle" in firewall["replaymark_decision_forbidden"]
    assert runtime["scientific_exposure_at_freeze"]["ve2_home_assistant_scientific_cells"] == 0 and runtime["scientific_exposure_at_freeze"]["ve2_replaymark_scientific_cells"] == 0
    assert authority["authorization"]["science_open_authorized"] is False and authority["authorization"]["runtime_E0Q_required"] is True
    return {"label_free_t01_states": len(t01_manifest["states"]), "label_free_t02_states": len(t02_manifest["states"]), "runtime_E0Q_required": True, "science_open_authorized": False}


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--work", required=True); ap.add_argument("--out-dir", required=True); args = ap.parse_args()
    work = pathlib.Path(args.work).resolve(); out = pathlib.Path(args.out_dir).resolve()
    if work.exists(): shutil.rmtree(work)
    if out.exists(): shutil.rmtree(out)
    work.mkdir(parents=True); out.mkdir(parents=True)
    repo_root = pathlib.Path.cwd(); static_spec = verify_frozen_spec_files(repo_root); upstream = prepare_upstream(work); source_witnesses = verify_source_witnesses(upstream)
    t01_rows = t01_independent_rows(); t02_rows, t02_quotient, execution_manifest_rows = t02_independent_rows()
    t01_digest = sha256_bytes(canonical(t01_rows).encode()); t02_abstract_digest = sha256_bytes(canonical(t02_rows).encode()); t02_quotient_digest = sha256_bytes(canonical(t02_quotient).encode()); t02_manifest_digest = sha256_bytes(canonical(execution_manifest_rows).encode())
    assert t01_digest == EXPECTED_T01_ROWS_SHA256 and len(t01_rows) == 2 and sum(r["compatibility"] == "RETIRED_BY_UPDATE" for r in t01_rows) == 2
    assert t02_abstract_digest == EXPECTED_T02_ABSTRACT_SHA256 and len(t02_rows) == 144 and sum(r["compatibility"] == "COMPATIBLE_ACROSS_VERSION" for r in t02_rows) == 97 and sum(r["compatibility"] == "RETIRED_BY_UPDATE" for r in t02_rows) == 47
    assert t02_quotient_digest == EXPECTED_T02_QUOTIENT_SHA256 and len(t02_quotient) == 42 and sum(r["weight_in_144_state_superspace"] for r in t02_quotient) == 144 and sum(r["compatibility"] == "COMPATIBLE_ACROSS_VERSION" for r in t02_quotient) == 18 and sum(r["compatibility"] == "RETIRED_BY_UPDATE" for r in t02_quotient) == 24
    assert t02_manifest_digest == EXPECTED_T02_EXECUTION_MANIFEST_SHA256
    frozen_manifest = json.loads((repo_root / "VE2_T02_EXECUTION_STATE_MANIFEST_V1.json").read_text()); assert frozen_manifest["states"] == execution_manifest_rows
    write_json(out / "VE2_T01_INDEPENDENT_ROWS_V1.json", t01_rows); write_json(out / "VE2_T02_INDEPENDENT_ABSTRACT_ROWS_V1.json", t02_rows); write_json(out / "VE2_T02_INDEPENDENT_QUOTIENT_ROWS_V1.json", t02_quotient); write_json(out / "VE2_T02_INDEPENDENT_EXECUTION_MANIFEST_ROWS_V1.json", execution_manifest_rows); write_json(out / "VE2_TRANSITION_SOURCE_WITNESSES_V1.json", source_witnesses)
    qualification = {"schema": "replaymark.ve2.public-transition-static-qualification.v1", "status": "PASS", "private_authority_head": os.environ.get("PRIVATE_AUTHORITY_HEAD"), "execution_head": os.environ.get("GITHUB_SHA"), "workflow_run_id": int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None, "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]) if os.environ.get("GITHUB_RUN_ATTEMPT") else None, "claim_boundary": "home-assistant.native-service-call", "T01": {"states": 2, "compatible": 0, "retired": 2, "canonical_rows_sha256": t01_digest, "source_identity_and_static_service_surface_verified": True}, "T02": {"abstract_states": 144, "abstract_compatible": 97, "abstract_retired": 47, "abstract_rows_sha256": t02_abstract_digest, "quotient_classes": 42, "quotient_compatible": 18, "quotient_retired": 24, "class_weights_sum": 144, "quotient_rows_sha256": t02_quotient_digest, "label_free_execution_manifest_sha256": t02_manifest_digest, "source_identity_and_change_tokens_verified": True}, "label_firewall_static_checks": static_spec, "runtime_obligations_not_claimed_by_static_pass": ["T01 exact historical and new Home Assistant runtime pins plus service-surface E0Q", "T02 Home Assistant template-variable literal_eval/type realization under the selected common runtime", "T02 native trigger/condition/action realization for all 42 quotient representatives", "context-bound native service-event capture and completed-execution absence boundary"], "independence": {"private_semantics_generator_imported": False, "private_freeze_verifier_executed": False, "expected_frontier_used_as_runtime_input": False, "frontier_rederived_by_separate_literal_oracle": True}, "scientific_exposure": {"frontier_result_seen": False, "ve2_home_assistant_scientific_cells": 0, "ve2_replaymark_scientific_cells": 0}, "science_open_authorized": False, "next_gate": "Seal this public static PASS, receipt it privately, then freeze and qualify exact T01/T02 runtime pins and orthogonal E0Q before any scientific open."}
    write_json(out / "VE2_PUBLIC_TRANSITION_STATIC_QUALIFICATION_V1.json", qualification)


if __name__ == "__main__": main()
