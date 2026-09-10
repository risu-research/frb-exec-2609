from __future__ import annotations
import json
from collections import defaultdict

T01_TARGET = "climate.ve2_t01_thermostat"
T02_TARGET = "climate.ve2_t02_thermostat"
T02_SLOT_PRESETS = {1: "comfort", 2: "eco", 3: "home", 4: "sleep"}
T02_VACATION_PRESET = "away"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def projected_action(target: str, operation: str, variant: object | None = None) -> dict[str, str]:
    if operation == "NO_ACTION":
        return {"operation": "NO_ACTION", "concrete_target": target, "variant": "NO_ACTION"}
    return {
        "operation": operation,
        "concrete_target": target,
        "variant": canonical_json({} if variant is None else variant),
    }


def t01_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i, schedule_state in enumerate(("off", "on")):
        if schedule_state == "on":
            old = projected_action(T01_TARGET, "better_thermostat.set_temp_target_temperature", {"temperature": 18.0})
            new = projected_action(T01_TARGET, "climate.set_preset_mode", {"preset_mode": "sleep"})
            old_path = "schedule:on:set_temp_target_temperature"
            new_path = "schedule:on:set_preset_sleep"
        else:
            old = projected_action(T01_TARGET, "better_thermostat.restore_saved_target_temperature", {})
            new = projected_action(T01_TARGET, "climate.set_preset_mode", {"preset_mode": "none"})
            old_path = "schedule:off:restore_saved_target_temperature"
            new_path = "schedule:off:set_preset_none"
        rows.append({
            "analysis_state_id": f"VE2-T01-A{i:02d}",
            "execution_state_id": f"VE2-T01-S{i:02d}",
            "fixture": {"schedule_state": schedule_state},
            "old_projected_action": old,
            "new_projected_action": new,
            "old_causal_path": old_path,
            "new_causal_path": new_path,
            "compatibility": "COMPATIBLE_ACROSS_VERSION" if old == new else "RETIRED_BY_UPDATE",
        })
    return rows


def old_t02(state: dict[str, object]) -> tuple[dict[str, str], str]:
    tr = str(state["trigger_kind"])
    active = int(state["active_slot"])
    ep = bool(state["enable_presence_mode"])
    ph = bool(state["presence_home"])
    epa = bool(state["enable_pause_switch"])
    po = bool(state["pause_on"])
    # Old HA variable-rendering behavior frozen from the source defect:
    # bare lowercase true/false do not literal-eval to booleans and remain non-empty strings.
    anyone_home: object = "true" if not ep else ph
    schedule_paused: object = "false" if not epa else po

    if tr.startswith("slot"):
        n = int(tr[-1])
        if bool(schedule_paused):
            return projected_action(T02_TARGET, "NO_ACTION"), "slot:blocked_by_schedule_paused_truthiness"
        if ep and not bool(anyone_home):
            return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_VACATION_PRESET}), "slot:vacation"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_SLOT_PRESETS[n]}), "slot:normal"

    if tr == "startup":
        if bool(schedule_paused):
            return projected_action(T02_TARGET, "NO_ACTION"), "startup:blocked_by_schedule_paused_truthiness"
        if ep and not bool(anyone_home):
            return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_VACATION_PRESET}), "startup:vacation"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_SLOT_PRESETS[4]}), "startup:normal:old_active_slot_string_mismatch"

    if tr == "pause_off":
        if not epa:
            return projected_action(T02_TARGET, "NO_ACTION"), "pause_off:feature_disabled"
        if ep and not bool(anyone_home):
            return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_VACATION_PRESET}), "pause_off:vacation"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_SLOT_PRESETS[4]}), "pause_off:normal:old_active_slot_string_mismatch"

    if tr == "arrived_home":
        if not ep:
            return projected_action(T02_TARGET, "NO_ACTION"), "arrived_home:feature_disabled"
        if bool(schedule_paused):
            return projected_action(T02_TARGET, "NO_ACTION"), "arrived_home:blocked_by_schedule_paused_truthiness"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_SLOT_PRESETS[4]}), "arrived_home:normal:old_active_slot_string_mismatch"

    if tr == "left_home":
        if not ep:
            return projected_action(T02_TARGET, "NO_ACTION"), "left_home:feature_disabled"
        if bool(schedule_paused):
            return projected_action(T02_TARGET, "NO_ACTION"), "left_home:blocked_by_schedule_paused_truthiness"
        if ph:
            return projected_action(T02_TARGET, "NO_ACTION"), "left_home:presence_still_home"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_VACATION_PRESET}), "left_home:vacation"
    raise KeyError(tr)


def new_t02(state: dict[str, object]) -> tuple[dict[str, str], str]:
    tr = str(state["trigger_kind"])
    active = int(state["active_slot"])
    ep = bool(state["enable_presence_mode"])
    ph = bool(state["presence_home"])
    epa = bool(state["enable_pause_switch"])
    po = bool(state["pause_on"])
    anyone_home = True if not ep else ph
    schedule_paused = False if not epa else po

    if tr.startswith("slot"):
        n = int(tr[-1])
        if schedule_paused:
            return projected_action(T02_TARGET, "NO_ACTION"), "slot:blocked_by_schedule_paused"
        if ep and not anyone_home:
            return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_VACATION_PRESET}), "slot:vacation"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_SLOT_PRESETS[n]}), "slot:normal"

    if tr == "startup":
        if schedule_paused:
            return projected_action(T02_TARGET, "NO_ACTION"), "startup:blocked_by_schedule_paused"
        if ep and not anyone_home:
            return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_VACATION_PRESET}), "startup:vacation"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_SLOT_PRESETS[active]}), "startup:normal"

    if tr == "pause_off":
        if not epa:
            return projected_action(T02_TARGET, "NO_ACTION"), "pause_off:feature_disabled"
        if schedule_paused:
            return projected_action(T02_TARGET, "NO_ACTION"), "pause_off:still_paused"
        if ep and not anyone_home:
            return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_VACATION_PRESET}), "pause_off:vacation"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_SLOT_PRESETS[active]}), "pause_off:normal"

    if tr == "arrived_home":
        if not ep:
            return projected_action(T02_TARGET, "NO_ACTION"), "arrived_home:feature_disabled"
        if schedule_paused:
            return projected_action(T02_TARGET, "NO_ACTION"), "arrived_home:blocked_by_schedule_paused"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_SLOT_PRESETS[active]}), "arrived_home:normal"

    if tr == "left_home":
        if not ep:
            return projected_action(T02_TARGET, "NO_ACTION"), "left_home:feature_disabled"
        if schedule_paused:
            return projected_action(T02_TARGET, "NO_ACTION"), "left_home:blocked_by_schedule_paused"
        if anyone_home:
            return projected_action(T02_TARGET, "NO_ACTION"), "left_home:presence_still_home"
        return projected_action(T02_TARGET, "climate.set_preset_mode", {"preset_mode": T02_VACATION_PRESET}), "left_home:vacation"
    raise KeyError(tr)


def t02_abstract_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for tr in ("slot1", "slot2", "slot3", "slot4", "startup", "pause_off", "arrived_home", "left_home"):
        active_slots = (int(tr[-1]),) if tr.startswith("slot") else (1, 2, 3, 4)
        for active_slot in active_slots:
            for enable_presence_mode in (False, True):
                if tr == "arrived_home":
                    presence_values = (True,)
                elif tr == "left_home":
                    presence_values = (False,)
                elif enable_presence_mode:
                    presence_values = (False, True)
                else:
                    presence_values = (False,)
                for presence_home in presence_values:
                    for enable_pause_switch in (False, True):
                        if tr == "pause_off":
                            pause_values = (False,)
                        elif enable_pause_switch:
                            pause_values = (False, True)
                        else:
                            pause_values = (False,)
                        for pause_on in pause_values:
                            fixture = {
                                "trigger_kind": tr,
                                "active_slot": active_slot,
                                "enable_presence_mode": enable_presence_mode,
                                "presence_home": presence_home,
                                "enable_pause_switch": enable_pause_switch,
                                "pause_on": pause_on,
                            }
                            old_action, old_path = old_t02(fixture)
                            new_action, new_path = new_t02(fixture)
                            rows.append({
                                "fixture": fixture,
                                "old_projected_action": old_action,
                                "new_projected_action": new_action,
                                "old_causal_path": old_path,
                                "new_causal_path": new_path,
                                "compatibility": "COMPATIBLE_ACROSS_VERSION" if old_action == new_action else "RETIRED_BY_UPDATE",
                            })
    rows.sort(key=lambda row: canonical_json(row["fixture"]))
    for i, row in enumerate(rows):
        row["abstract_state_id"] = f"VE2-T02-A{i:03d}"
    return rows


def t02_quotient() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows = t02_abstract_rows()
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        key = canonical_json({
            "old_projected_action": row["old_projected_action"],
            "new_projected_action": row["new_projected_action"],
            "old_causal_path": row["old_causal_path"],
            "new_causal_path": row["new_causal_path"],
        })
        groups[key].append(row)
    classes: list[tuple[dict[str, object], list[dict[str, object]]]] = []
    for members in groups.values():
        members.sort(key=lambda row: canonical_json(row["fixture"]))
        classes.append((members[0], members))
    classes.sort(key=lambda item: canonical_json(item[0]["fixture"]))
    output: list[dict[str, object]] = []
    by_fixture: dict[str, str] = {}
    for i, (rep, members) in enumerate(classes):
        sid = f"VE2-T02-S{i:02d}"
        for member in members:
            by_fixture[canonical_json(member["fixture"])] = sid
        output.append({
            "execution_state_id": sid,
            "representative_fixture": rep["fixture"],
            "weight_in_144_state_superspace": len(members),
            "old_projected_action": rep["old_projected_action"],
            "new_projected_action": rep["new_projected_action"],
            "old_causal_path": rep["old_causal_path"],
            "new_causal_path": rep["new_causal_path"],
            "compatibility": rep["compatibility"],
        })
    for row in rows:
        row["execution_state_id"] = by_fixture[canonical_json(row["fixture"])]
    return rows, output


def summary() -> dict[str, object]:
    t01 = t01_rows()
    raw, quotient = t02_quotient()
    return {
        "t01": {
            "abstract_states": len(t01),
            "quotient_classes": len(t01),
            "compatible": sum(row["compatibility"] == "COMPATIBLE_ACROSS_VERSION" for row in t01),
            "retired": sum(row["compatibility"] == "RETIRED_BY_UPDATE" for row in t01),
        },
        "t02": {
            "abstract_states": len(raw),
            "abstract_compatible": sum(row["compatibility"] == "COMPATIBLE_ACROSS_VERSION" for row in raw),
            "abstract_retired": sum(row["compatibility"] == "RETIRED_BY_UPDATE" for row in raw),
            "quotient_classes": len(quotient),
            "quotient_compatible": sum(row["compatibility"] == "COMPATIBLE_ACROSS_VERSION" for row in quotient),
            "quotient_retired": sum(row["compatibility"] == "RETIRED_BY_UPDATE" for row in quotient),
        },
    }


if __name__ == "__main__":
    print(json.dumps(summary(), sort_keys=True))
