from __future__ import annotations

"""Independent literal oracle for HA-C1.

No production ReplayMark realization module is imported here.  The oracle
operates only on the frozen raw fixture grammar and returns literal expected
canonical state/action identities.
"""

import json
from typing import Mapping

ENTITIES = {
    "presence": "input_boolean.agentmark_presence",
    "motion": "binary_sensor.agentmark_motion",
    "night": "input_boolean.agentmark_night",
    "enable": "input_boolean.agentmark_enable",
    "climate": "climate.agentmark_thermostat",
}
TARGET = "climate.agentmark_thermostat"


def _bool(value: object) -> bool:
    if value == "on": return True
    if value == "off": return False
    raise ValueError("non-binary HA state")


def observation_expected(raw: Mapping[str, object]) -> dict[str, object]:
    if raw["schema"] != "replaymark.runtime.ha-bt-observation-record.v1": raise ValueError("schema")
    if raw["capture_point"] != "homeassistant.states.snapshot": raise ValueError("capture")
    if raw["clock_domain"] != "python.perf_counter_ns": raise ValueError("clock")
    if raw["entities"] != ENTITIES: raise ValueError("entities")
    s = raw["snapshot"]
    if set(s) != {"label","t_ns","presence","motion","night","enable","climate_state","climate_preset"}: raise ValueError("snapshot fields")
    if s["enable"] != "on" or s["climate_state"] != "heat": raise ValueError("scope")
    preset=s["climate_preset"]
    if not isinstance(preset,str) or not preset or preset != preset.strip(): raise ValueError("preset")
    token=json.dumps([_bool(s["presence"]),_bool(s["motion"]),_bool(s["night"]),preset],separators=(",",":"),ensure_ascii=False)
    return {"evidence_token":token,"clock_domain":"python.perf_counter_ns","boundary_timestamp_ns":s["t_ns"],"source_event_timestamp_ns":None}


def action_expected(raw: Mapping[str, object]) -> dict[str, object]:
    if raw["schema"] != "replaymark.runtime.ha-bt-historical-action-record.v1": raise ValueError("schema")
    if raw["capture_point"] != "homeassistant.event_bus.EVENT_CALL_SERVICE": raise ValueError("capture")
    if raw["clock_domain"] != "python.perf_counter_ns": raise ValueError("clock")
    s=raw["service_event"]; p=raw["parent_state_event"]
    if set(s)!={"t_ns","domain","service","service_data","context_id","context_parent_id"}: raise ValueError("service fields")
    if set(p)!={"t_ns","entity_id","old_state","new_state","context_id","context_parent_id"}: raise ValueError("parent fields")
    if (s["domain"],s["service"]) != ("climate","set_preset_mode"): raise ValueError("service")
    if s["context_parent_id"] != p["context_id"]: raise ValueError("context")
    if p["t_ns"] > s["t_ns"]: raise ValueError("ordering")
    data=s["service_data"]
    if set(data)!={"entity_id","preset_mode"}: raise ValueError("service data fields")
    if not isinstance(data["entity_id"],list) or len(data["entity_id"])!=1 or data["entity_id"][0]!=TARGET: raise ValueError("target")
    preset=data["preset_mode"]
    if not isinstance(preset,str) or not preset or preset != preset.strip(): raise ValueError("preset")
    variant=json.dumps({"preset_mode":preset},sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return {
        "operation":"climate.set_preset_mode",
        "target_class":"climate",
        "variant":variant,
        "concrete_target":TARGET,
        "service_domain":"climate",
        "service_name":"set_preset_mode",
        "preset_mode":preset,
    }
