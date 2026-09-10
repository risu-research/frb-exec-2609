#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys

import ve2_transition_independent_qualify_v1 as core


def corrected_verify_source_witnesses(repo: pathlib.Path) -> dict[str, object]:
    witnesses = {
        "t01_old_blueprint": core.verify_blob(repo, core.T01_OLD_COMMIT, core.T01_PATH, core.T01_OLD_BLOB, core.T01_OLD_SHA256),
        "t01_new_blueprint": core.verify_blob(repo, core.T01_NEW_COMMIT, core.T01_PATH, core.T01_NEW_BLOB, core.T01_NEW_SHA256),
        "t02_old_blueprint": core.verify_blob(repo, core.T02_OLD_COMMIT, core.T02_PATH, core.T02_OLD_BLOB, core.T02_OLD_SHA256),
        "t02_new_blueprint": core.verify_blob(repo, core.T02_NEW_COMMIT, core.T02_PATH, core.T02_NEW_BLOB, core.T02_NEW_SHA256),
    }

    t01_old = core.git_bytes(repo, f"{core.T01_OLD_COMMIT}:{core.T01_PATH}").decode()
    t01_new = core.git_bytes(repo, f"{core.T01_NEW_COMMIT}:{core.T01_PATH}").decode()
    assert "better_thermostat.set_temp_target_temperature" in t01_old
    assert "better_thermostat.restore_saved_target_temperature" in t01_old
    assert "climate.set_preset_mode" in t01_new
    assert "preset_mode: sleep" in t01_new
    assert "preset_mode: none" in t01_new

    old_services = core.git_bytes(repo, f"{core.T01_OLD_COMMIT}:custom_components/better_thermostat/services.yaml").decode()
    new_services = core.git_bytes(repo, f"{core.T01_NEW_COMMIT}:custom_components/better_thermostat/services.yaml").decode()
    for token in ("save_current_target_temperature:", "restore_saved_target_temperature:", "set_temp_target_temperature:"):
        assert token in old_services
        assert token not in new_services

    old_climate = core.git_bytes(repo, f"{core.T01_OLD_COMMIT}:custom_components/better_thermostat/climate.py").decode()
    for token in (
        "SERVICE_SET_TEMP_TARGET_TEMPERATURE",
        "SERVICE_RESTORE_SAVED_TARGET_TEMPERATURE",
        "async_register_entity_service",
        "async def set_temp_temperature",
        "async def restore_temp_temperature",
    ):
        assert token in old_climate
    witnesses["t01_service_surface"] = {
        "old_services_yaml_declares_proprietary_surface": True,
        "old_climate_registers_constant_named_set_restore_services": True,
        "old_climate_implements_set_restore_methods": True,
        "new_services_yaml_excludes_proprietary_surface": True,
    }

    t02_old = core.git_bytes(repo, f"{core.T02_OLD_COMMIT}:{core.T02_PATH}").decode()
    t02_new = core.git_bytes(repo, f"{core.T02_NEW_COMMIT}:{core.T02_PATH}").decode()
    assert "{% if active_slot == '1' %}" in t02_old
    assert "{% if active_slot | int == 1 %}" in t02_new
    assert "{% if not enable_pause_switch or pause_switch == '' %}false" in t02_old
    assert "{{ false }}" in t02_new
    assert "presence_entity_selection: !input presence_entity" in t02_new
    assert "pause_switch_selection: !input pause_switch" in t02_new
    assert "value_template: \"{{ not schedule_paused }}\"" in t02_new
    assert "value_template: \"{{ not anyone_home }}\"" in t02_new
    witnesses["t02_source_change"] = {
        "old_active_slot_string_compare_present": True,
        "new_active_slot_int_compare_present": True,
        "old_bare_lowercase_false_branch_present": True,
        "new_rendered_boolean_false_present": True,
        "new_scalar_list_normalization_present": True,
        "new_pause_off_aggregate_recheck_present": True,
        "new_left_home_aggregate_recheck_present": True,
    }
    return witnesses


def main() -> None:
    core.verify_source_witnesses = corrected_verify_source_witnesses
    core.main()
    out_arg = sys.argv[sys.argv.index("--out-dir") + 1]
    out = pathlib.Path(out_arg).resolve()
    core_path = out / "VE2_PUBLIC_TRANSITION_STATIC_QUALIFICATION_V1.json"
    payload = json.loads(core_path.read_text())
    payload["schema"] = "replaymark.ve2.public-transition-static-qualification.v2"
    payload["remediation"] = {
        "failed_v1_run_id": 34501014803,
        "failed_v1_execution_head": "0d25db7fd7be8099512c9674a408deb617ace9cb",
        "failure_record": "VE2_TRANSITION_STATIC_QUALIFICATION_V1_FAILURE_SEAL.json",
        "change_scope": "public source witness only; frozen scientific semantics/frontiers/state spaces/firewall unchanged",
    }
    payload["independence"]["frontier_core_reused_byte_identically_from_failed_v1_public_oracle"] = True
    corrected = out / "VE2_PUBLIC_TRANSITION_STATIC_QUALIFICATION_V2.json"
    core.write_json(corrected, payload)
    core_path.rename(out / "VE2_PUBLIC_TRANSITION_STATIC_QUALIFICATION_CORE_V1.json")


if __name__ == "__main__":
    main()
