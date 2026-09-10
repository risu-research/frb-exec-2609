from __future__ import annotations

"""Pre-result verifier for VE1 real-upstream version evolution.

This verifier is intentionally non-scientific. It never executes Home Assistant,
ReplayMark, or either controller. It proves only that the frozen protocol/table are
internally complete and that externally supplied old/new YAML bytes are exactly the
pinned upstream Git blobs with the source-level delta assumed by the protocol.
"""

import argparse
import hashlib
import json
from pathlib import Path

PROTOCOL_SCHEMA = "replaymark.ve1.upstream-version-evolution-protocol.v1"
TABLE_SCHEMA = "replaymark.ve1.expected-cross-version-table.v1"
C5_PARENT = "c7e04dad2426bec10449dfdde7a6644eb24ec694"
OLD_COMMIT = "611723a7cffd7cbc151afd0415c1a705900754f1"
NEW_COMMIT = "87e8844e3e0fa0a47e586cecd2c4d412c7bc718f"
OLD_BLOB = "6ce2d0e433b8380d03289d450aa3dc2fbe2d3977"
NEW_BLOB = "5091b299da53ed3eaed85098d4e2a554289597e1"
NEW_SHA256 = "16d52ce11dec44fa9ca533d15f3cec1eb9646d59bf6a455bd905af63cdf86443"
CLIMATE_ENTITY = "climate.agentmark_thermostat"
PRESETS = ("away", "home", "comfort", "sleep")


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _state_from_id(state_id: str) -> tuple[bool, bool, bool, str]:
    parts = state_id.split("-")
    if len(parts) != 5 or not parts[0].startswith("p") or not parts[1].startswith("m") or not parts[2].startswith("n") or parts[3] != "cur":
        raise AssertionError(("malformed state id", state_id))
    p = parts[0][1:]
    m = parts[1][1:]
    n = parts[2][1:]
    if p not in {"0", "1"} or m not in {"0", "1"} or n not in {"0", "1"}:
        raise AssertionError(("nonbinary state id", state_id))
    current = parts[4]
    if current not in PRESETS:
        raise AssertionError(("foreign preset", state_id))
    return p == "1", m == "1", n == "1", current


def _desired(presence: bool, motion: bool, night: bool) -> str:
    if night:
        return "sleep"
    if not presence:
        return "away"
    if motion:
        return "comfort"
    return "home"


def _extract_target_block(text: str) -> str:
    begin = "  target_preset: >\n"
    end = "\n\n  # Fallback-Temperatur"
    if text.count(begin) != 1:
        raise AssertionError("target_preset block cardinality is not one")
    tail = text.split(begin, 1)[1]
    if end not in tail:
        raise AssertionError("target_preset block terminator missing")
    return begin + tail.split(end, 1)[0]


def _verify_source_delta(old: bytes, new: bytes) -> dict[str, object]:
    if _git_blob_sha1(old) != OLD_BLOB:
        raise AssertionError(("old upstream blob mismatch", _git_blob_sha1(old)))
    if _git_blob_sha1(new) != NEW_BLOB:
        raise AssertionError(("new upstream blob mismatch", _git_blob_sha1(new)))
    new_sha = hashlib.sha256(new).hexdigest()
    if new_sha != NEW_SHA256:
        raise AssertionError(("new upstream sha256 mismatch", new_sha))

    old_text = old.decode("utf-8")
    new_text = new.decode("utf-8")
    if _extract_target_block(old_text) != _extract_target_block(new_text):
        raise AssertionError("target_preset policy changed between pinned revisions")

    old_action = "  - service: climate.set_preset_mode\n    target:\n      entity_id: \"{{ climate_entity }}\"\n    data:\n      preset_mode: \"{{ target_preset }}\""
    if old_text.count(old_action) != 1:
        raise AssertionError("old unconditional action block not exact")
    guard = "{{ ent != '' and cur != tgt }}"
    if new_text.count(guard) != 1:
        raise AssertionError("new redundant-action suppression guard not exact")
    if "writeback_enable:\n" not in new_text or "      default: false\n" not in new_text:
        raise AssertionError("new writeback-default-false source evidence missing")

    return {
        "old_git_blob_sha1": _git_blob_sha1(old),
        "old_sha256": hashlib.sha256(old).hexdigest(),
        "new_git_blob_sha1": _git_blob_sha1(new),
        "new_sha256": new_sha,
        "target_preset_block_byte_identical": True,
        "old_unconditional_call_block_present": True,
        "new_current_not_equal_target_guard_present": True,
    }


def verify(protocol_path: Path, table_path: Path, old_source: Path, new_source: Path) -> dict[str, object]:
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    table = json.loads(table_path.read_text(encoding="utf-8"))

    if protocol.get("schema") != PROTOCOL_SCHEMA or protocol.get("status") != "FROZEN_PRE_RESULT":
        raise AssertionError("foreign/unfrozen VE1 protocol")
    if protocol.get("authority_parent") != C5_PARENT:
        raise AssertionError("VE1 is not rooted directly in C5 final authority")
    if protocol["source_revisions"]["old"]["commit"] != OLD_COMMIT or protocol["source_revisions"]["new"]["commit"] != NEW_COMMIT:
        raise AssertionError("upstream revision pins changed")
    if protocol["source_revisions"]["old"]["git_blob_sha1"] != OLD_BLOB or protocol["source_revisions"]["new"]["git_blob_sha1"] != NEW_BLOB:
        raise AssertionError("upstream source blob pins changed")
    if protocol["scientific_hygiene"]["live_result_opened"] is not False:
        raise AssertionError("protocol claims a live result has already opened")
    if protocol["scientific_hygiene"]["expected_24_8_split_frozen_before_live_execution"] is not True:
        raise AssertionError("24/8 prediction not prospectively frozen")

    profile = protocol["evaluated_profile"]
    if profile != {
        "profile_name": "frozen four-preset Better Thermostat evaluation profile",
        "presence": [False, True],
        "motion": [False, True],
        "night": [False, True],
        "current_preset": ["away", "home", "comfort", "sleep"],
        "state_count": 32,
        "enable": True,
        "boost_entity": "unset",
        "eco_entity": "unset",
        "activity_entity": "unset",
        "writeback_enable": False,
        "writeback_bounds_enable": False,
        "scope_guardrail": "VE1 does not claim to cover the blueprint's full optional boost/eco/activity/writeback configuration space.",
    }:
        raise AssertionError("evaluated profile changed")

    if table.get("schema") != TABLE_SCHEMA or table.get("status") != "FROZEN_PRE_RESULT":
        raise AssertionError("foreign/unfrozen expected table")
    if table.get("row_count") != 32 or len(table.get("rows", [])) != 32:
        raise AssertionError("expected table is not complete")
    if table.get("projection", {}).get("concrete_target") != CLIMATE_ENTITY:
        raise AssertionError("expected table target changed")

    seen: set[str] = set()
    compatible = retired = 0
    for row in table["rows"]:
        state_id = row["state_id"]
        if state_id in seen:
            raise AssertionError(("duplicate state", state_id))
        seen.add(state_id)
        presence, motion, night, current = _state_from_id(state_id)
        target = _desired(presence, motion, night)
        if row["target_preset"] != target:
            raise AssertionError(("target derivation mismatch", state_id, row["target_preset"], target))
        expected_class = "RETIRED_BY_UPDATE" if current == target else "COMPATIBLE_ACROSS_VERSION"
        if row["compatibility"] != expected_class:
            raise AssertionError(("compatibility classification mismatch", state_id, row["compatibility"], expected_class))
        compatible += expected_class == "COMPATIBLE_ACROSS_VERSION"
        retired += expected_class == "RETIRED_BY_UPDATE"

    if compatible != 24 or retired != 8:
        raise AssertionError(("24/8 split changed", compatible, retired))
    if table["expected_counts"] != {"COMPATIBLE_ACROSS_VERSION": 24, "RETIRED_BY_UPDATE": 8}:
        raise AssertionError("expected table counts changed")
    if protocol["pre_result_expected_split"]["compatible_across_version"] != 24 or protocol["pre_result_expected_split"]["retired_by_update"] != 8:
        raise AssertionError("protocol 24/8 split changed")

    source = _verify_source_delta(old_source.read_bytes(), new_source.read_bytes())
    return {
        "schema": "replaymark.ve1.pre-result-freeze-verification.v1",
        "status": "PASS_PRE_RESULT_STATIC_ONLY",
        "home_assistant_executed": False,
        "replaymark_executed": False,
        "scientific_result_opened": False,
        "state_rows": 32,
        "compatible_across_version": compatible,
        "retired_by_update": retired,
        "source_identity": source,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--old-source", required=True)
    parser.add_argument("--new-source", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    result = verify(Path(args.protocol), Path(args.table), Path(args.old_source), Path(args.new_source))
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
