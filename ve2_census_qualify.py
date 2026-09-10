from __future__ import annotations

"""Independent pre-scientific qualification of the frozen VE2 upstream census.

This program reconstructs the frozen Better Thermostat blueprint universe and its
file-version histories from Git objects. It executes neither Home Assistant nor
ReplayMark and never opens a VE2 frontier result.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

SNAPSHOT = "d24bcf2da30b8dbaaf99c0a14ec91f3c3b58e942"
UPSTREAM = "https://github.com/KartoffelToby/better_thermostat.git"
CONSTITUTION = Path("VE2_VERSION_EVOLUTION_CENSUS_CONSTITUTION_V1_MIRROR.json")
MANIFEST = Path("VE2_UPSTREAM_CORPUS_MANIFEST_V1_MIRROR.json")
AUTHORITY = Path("VE2_PRE_RESULT_CENSUS_AUTHORITY_V1_MIRROR.json")
EXPECTED_MIRROR_BLOBS = {
    CONSTITUTION: "58e6cc7e1a46af3f14ba8b9e75d71b7c2292cb1d",
    MANIFEST: "cd0e4f02cc1d3f1b8088c91a6b651659465d9aa6",
    AUTHORITY: "9ef22d44242fa505c7e59769e3cef8882c144382",
}
EXPECTED_FILES = [
    "battery_low_notify.yaml",
    "device_error_notify.yaml",
    "heating_active_notify.yaml",
    "humidity_high_alert.yaml",
    "night_mode.yaml",
    "presence_away_preset.yaml",
    "weekly_heating_schedule.yaml",
]
EXPECTED_POSITIVE = {
    ("blueprints/night_mode.yaml", "cd4c3121c92f59d5ac1f3533424bc570209ce6ef", "96ae2f87b3b1a1b095dbf1f74f37f63fbc34c32f"): "VE2-T01-NIGHT-ACTION-FAMILY",
    ("blueprints/weekly_heating_schedule.yaml", "ac189909982c5edea1260e767027d6fad90ef4bd", "5b4496de5659fd2c6ec5c67a9797e6659797866c"): "VE2-T02-WEEKLY-GUARD-REALIZATION",
}


def sh(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob(path: Path) -> str:
    return sh("git", "hash-object", "--no-filters", str(path))


def file_versions(repo: Path, path: str) -> list[dict[str, str]]:
    commits = sh("git", "log", "--format=%H", "--reverse", SNAPSHOT, "--", path, cwd=repo).splitlines()
    out: list[dict[str, str]] = []
    for commit in commits:
        try:
            blob = sh("git", "rev-parse", f"{commit}:{path}", cwd=repo)
        except subprocess.CalledProcessError:
            continue
        if not out or out[-1]["blob"] != blob:
            out.append({"commit": commit, "blob": blob})
    return out


def source(repo: Path, commit: str, path: str) -> str:
    return sh("git", "show", f"{commit}:{path}", cwd=repo) + "\n"


def from_token(text: str, token: str) -> str:
    pos = text.index(token)
    return text[pos:]


def var_block(text: str, name: str) -> str:
    lines = text.splitlines()
    start = None
    needle = f"  {name}: >"
    for i, line in enumerate(lines):
        if line == needle:
            start = i
            break
    assert start is not None, name
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line.startswith("    "):
            break
        body.append(line)
    return "\n".join(body).strip()


def climate_trace_projection(text: str) -> list[tuple[str, str, str]]:
    lines = text.splitlines()
    out: list[tuple[str, str, str]] = []
    for i, line in enumerate(lines):
        if line.strip() != "- service: climate.set_preset_mode":
            continue
        preset = ""
        target = ""
        for line2 in lines[i + 1 : i + 9]:
            s = line2.strip()
            if s.startswith("preset_mode:"):
                preset = s
            if s.startswith("target:"):
                target = s
            if s.startswith("entity_id:") and target:
                target += "|" + s
        out.append(("climate.set_preset_mode", preset, target))
    return out


def thermostat_service_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("- service: climate.")
        or line.strip().startswith("- service: better_thermostat.")
    ]


def semantic_witnesses(repo: Path) -> dict[str, Any]:
    p_night = "blueprints/night_mode.yaml"
    n378 = source(repo, "3785543e30e7af52a742e9ba129527147c813480", p_night)
    nc6 = source(repo, "c6d9f4cd15dd381f803b96ac3d184d2ff41db4fb", p_night)
    ncd = source(repo, "cd4c3121c92f59d5ac1f3533424bc570209ce6ef", p_night)
    n96 = source(repo, "96ae2f87b3b1a1b095dbf1f74f37f63fbc34c32f", p_night)

    # X01: metadata-only URL movement.
    assert n378.replace("tree/master/blueprints/night_mode.yaml", "blob/master/blueprints/night_mode.yaml") == nc6
    # X02: selector/name changes occur above the native runtime mode/trigger/action block.
    assert from_token(nc6, "mode: queued") == from_token(ncd, "mode: queued")
    # T01: exact consequential action-family substitution.
    assert "service: better_thermostat.set_temp_target_temperature" in ncd
    assert "service: better_thermostat.restore_saved_target_temperature" in ncd
    assert "temperature: !input night_temp" in ncd
    assert "service: climate.set_preset_mode" not in ncd
    assert n96.count("service: climate.set_preset_mode") == 2
    assert "preset_mode: sleep" in n96 and "preset_mode: none" in n96
    assert "service: better_thermostat.set_temp_target_temperature" not in n96
    assert "service: better_thermostat.restore_saved_target_temperature" not in n96

    p_presence = "blueprints/presence_away_preset.yaml"
    pd = source(repo, "d496da5f283db323673d97efc27d6193791c17ac", p_presence)
    pa = source(repo, "ac189909982c5edea1260e767027d6fad90ef4bd", p_presence)
    # X03: notification mechanics change, but action-controlling presence law and climate trace do not.
    assert var_block(pd, "anyone_home") == var_block(pa, "anyone_home")
    assert climate_trace_projection(pd) == climate_trace_projection(pa)
    assert climate_trace_projection(pd) == [
        ("climate.set_preset_mode", "preset_mode: away", "target: !input thermostat_target"),
        ("climate.set_preset_mode", "preset_mode: !input home_preset", "target: !input thermostat_target"),
    ]

    p_weekly = "blueprints/weekly_heating_schedule.yaml"
    wd = source(repo, "d496da5f283db323673d97efc27d6193791c17ac", p_weekly)
    wa = source(repo, "ac189909982c5edea1260e767027d6fad90ef4bd", p_weekly)
    w5 = source(repo, "5b4496de5659fd2c6ec5c67a9797e6659797866c", p_weekly)
    # X04: d496->ac189 retains thermostat trace and the old single-entity action guards.
    assert climate_trace_projection(wd) == climate_trace_projection(wa)
    assert var_block(wd, "anyone_home") == var_block(wa, "anyone_home")
    assert var_block(wd, "schedule_paused") == var_block(wa, "schedule_paused")
    # T02: action surface remains climate.set_preset_mode, while guard realization changes.
    assert "presence_entity: !input presence_entity" in wa
    assert "states(presence_entity)" in wa
    assert "pause_switch: !input pause_switch" in wa
    assert "is_state(pause_switch, 'on')" in wa
    assert "%}true" in var_block(wa, "anyone_home")
    assert "%}false" in var_block(wa, "schedule_paused")
    assert "presence_entity_selection: !input presence_entity" in w5
    assert "presence_entities:" in w5
    assert "namespace(home=false)" in w5
    assert "pause_switch_selection: !input pause_switch" in w5
    assert "pause_switch_entities:" in w5
    assert "namespace(paused=false)" in w5
    assert "{{ true }}" in var_block(w5, "anyone_home")
    assert "{{ false }}" in var_block(w5, "schedule_paused")
    assert "one person still home" in w5
    assert thermostat_service_lines(wa) and thermostat_service_lines(w5)

    p_humidity = "blueprints/humidity_high_alert.yaml"
    hd = source(repo, "d496da5f283db323673d97efc27d6193791c17ac", p_humidity)
    ha = source(repo, "ac189909982c5edea1260e767027d6fad90ef4bd", p_humidity)
    # X05: source evolves, but neither side actuates thermostat/climate services.
    assert thermostat_service_lines(hd) == []
    assert thermostat_service_lines(ha) == []
    assert "service: switch.turn_on" in hd and "service: switch.turn_on" in ha

    return {
        "VE2-X01-NIGHT-METADATA": "PASS",
        "VE2-X02-NIGHT-SELECTOR": "PASS",
        "VE2-T01-NIGHT-ACTION-FAMILY": "PASS",
        "VE2-X03-PRESENCE-NOTIFICATION": "PASS",
        "VE2-X04-WEEKLY-DEFAULTS": "PASS",
        "VE2-T02-WEEKLY-GUARD-REALIZATION": "PASS",
        "VE2-X05-HUMIDITY-NONTHERMOSTAT": "PASS",
    }


def verify(work: Path) -> dict[str, Any]:
    constitution = json.loads(CONSTITUTION.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    for path, expected in EXPECTED_MIRROR_BLOBS.items():
        assert git_blob(path) == expected, (path, git_blob(path), expected)
    assert constitution["scientific_hygiene"]["ve2_runtime_result_opened"] is False
    assert authority["result_exposure_at_seal"]["ve2_home_assistant_scientific_cells"] == 0

    repo = work / "better_thermostat"
    subprocess.check_call(["git", "clone", "--quiet", "--no-tags", UPSTREAM, str(repo)])
    sh("git", "cat-file", "-e", f"{SNAPSHOT}^{{commit}}", cwd=repo)

    tree_files = sh("git", "ls-tree", "-r", "--name-only", SNAPSHOT, "--", "blueprints", cwd=repo).splitlines()
    actual_files = sorted(Path(x).name for x in tree_files if x.startswith("blueprints/") and "/" not in x[len("blueprints/"):])
    assert actual_files == EXPECTED_FILES, actual_files

    actual_histories: dict[str, list[dict[str, str]]] = {}
    for filename in actual_files:
        actual_histories[filename] = file_versions(repo, f"blueprints/{filename}")

    frozen_histories = manifest["complete_file_touch_histories"]
    assert set(actual_histories) == set(frozen_histories)
    for filename, actual in actual_histories.items():
        frozen = frozen_histories[filename]
        assert [x["commit"] for x in actual] == [x["commit"] for x in frozen], (filename, actual, frozen)
        for got, expected in zip(actual, frozen):
            if expected["blob"] is not None:
                assert got["blob"] == expected["blob"], (filename, got, expected)

    all_pairs: set[tuple[str, str, str]] = set()
    for filename, versions in actual_histories.items():
        for old, new in zip(versions, versions[1:]):
            all_pairs.add((f"blueprints/{filename}", old["commit"], new["commit"]))
    assert len(all_pairs) == 7

    frozen_positive = {
        (x["path"], x["old_file_touch_commit"], x["new_file_touch_commit"]): x["transition_id"]
        for x in manifest["included_semantic_transitions"]
    }
    assert frozen_positive == EXPECTED_POSITIVE
    frozen_excluded = {
        (x["path"], x["old_commit"], x["new_commit"])
        for x in manifest["excluded_or_nonpair_records"]
        if x["classification"].startswith("EXCLUDED_")
    }
    assert set(frozen_positive) | frozen_excluded == all_pairs
    assert set(frozen_positive).isdisjoint(frozen_excluded)

    witnesses = semantic_witnesses(repo)
    assert set(v for v in witnesses.values()) == {"PASS"}

    single_version_blobs = {
        filename: actual_histories[filename][0]["blob"]
        for filename in ("battery_low_notify.yaml", "device_error_notify.yaml", "heating_active_notify.yaml")
    }
    assert all(len(v) == 40 for v in single_version_blobs.values())

    return {
        "schema": "replaymark.ve2.public-census-qualification.v1",
        "status": "PASS",
        "scientific_result_opened": False,
        "ve2_home_assistant_scientific_cells": 0,
        "ve2_replaymark_scientific_cells": 0,
        "upstream_repository": "KartoffelToby/better_thermostat",
        "snapshot_head": SNAPSHOT,
        "universe_files": actual_files,
        "universe_file_count": len(actual_files),
        "actual_file_touch_histories": actual_histories,
        "adjacent_pair_count": len(all_pairs),
        "eligible_transition_ids": [EXPECTED_POSITIVE[k] for k in sorted(EXPECTED_POSITIVE)],
        "eligible_count": len(EXPECTED_POSITIVE),
        "excluded_pair_count": len(frozen_excluded),
        "single_version_blob_identities": single_version_blobs,
        "semantic_witnesses": witnesses,
        "mirror_git_blobs": {str(k): v for k, v in EXPECTED_MIRROR_BLOBS.items()},
        "mirror_sha256": {str(k): sha256(k) for k in EXPECTED_MIRROR_BLOBS},
        "corpus_membership_changed": False,
        "frontier_prediction_opened": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    work = Path(args.work)
    out = Path(args.out)
    work.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = verify(work)
    except Exception as exc:
        value = {
            "schema": "replaymark.ve2.public-census-qualification.v1",
            "status": "FAIL",
            "scientific_result_opened": False,
            "ve2_home_assistant_scientific_cells": 0,
            "ve2_replaymark_scientific_cells": 0,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        out.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    out.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
